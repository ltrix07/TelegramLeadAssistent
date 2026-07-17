"""Runtime wiring gate for listener-to-classifier PostgreSQL hand-off."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.bot.delivery import BotNotificationWorker
from app.classifier.downstream import DownstreamClassificationHandler
from app.classifier.openai_adapter import (
    ClassificationResponse,
    ClassificationUsage,
    OpenAIClassificationAdapter,
)
from app.classifier.relevant import RelevantQuestionPersistenceService
from app.classifier.schemas import (
    ClassificationCategory,
    ClassificationReasonCode,
    ClassificationResult,
)
from app.classifier.stage2 import Stage2ClassificationService
from app.classifier.usage import ClassificationPricing, UsageRepository
from app.database.downstream import DownstreamPhase
from app.database.models import BotNotification, DetectedQuestion, MonitoredChat, ProcessingJob
from app.database.queue import JobRepository, NewJob
from app.database.worker import DownstreamQueueWorker
from app.domain.enums import MonitoredChatStatus, MonitoredChatType, ProcessingJobStatus
from app.listener.reply_chain import ReplyMessage
from app.listener.reply_chain_worker import ReplyChainSnapshotHandler

pytestmark = pytest.mark.integration

CHAT_ID = -100777
TOPIC_ID = 71


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for downstream runtime integration")
    return value


def _response(*, relevant: bool, context_required: bool = False) -> ClassificationResponse:
    return ClassificationResponse(
        result=ClassificationResult.model_validate(
            {
                "is_relevant": relevant,
                "category": (
                    ClassificationCategory.TECHNICAL
                    if relevant
                    else ClassificationCategory.IRRELEVANT
                ),
                "confidence": 0.91,
                "context_required": context_required,
                "reason_code": (
                    ClassificationReasonCode.TECHNICAL_PROBLEM
                    if relevant
                    else ClassificationReasonCode.INSUFFICIENT_CONTEXT
                ),
            }
        ),
        usage=ClassificationUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )


class FinalRelevantTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def classify(
        self, *, model: str, instructions: str, target_text: str, timeout_seconds: float
    ) -> ClassificationResponse:
        del model, instructions, timeout_seconds
        self.calls.append(target_text)
        return _response(relevant=True)


class RuntimeReplySource:
    def __init__(self, message_ids: tuple[int, ...]) -> None:
        self._messages = {
            message_id: ReplyMessage(
                telegram_chat_id=CHAT_ID,
                telegram_message_id=message_id,
                reply_to_message_id=None,
                topic_id=TOPIC_ID,
                reply_to_top_message_id=TOPIC_ID,
                author_telegram_id=500 + message_id,
                author_display_name="Test author",
                telegram_created_at=datetime.now(UTC),
                text=f"target {message_id}",
            )
            for message_id in message_ids
        }

    async def get_reply_message(self, chat_id: int, message_id: int) -> ReplyMessage | None:
        assert chat_id == CHAT_ID
        return self._messages.get(message_id)

    async def get_forum_topic_title(self, chat_id: int, topic_id: int) -> str | None:
        assert (chat_id, topic_id) == (CHAT_ID, TOPIC_ID)
        return "Runtime"


class RecordingNotificationBot:
    def __init__(self) -> None:
        self.destinations: list[int] = []

    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> object:
        del text, kwargs
        self.destinations.append(chat_id)
        return SimpleNamespace(message_id=900 + len(self.destinations))


async def _seed_job(
    factory: async_sessionmaker[AsyncSession],
    chat_pk: UUID,
    message_id: int,
    *,
    context_required: bool,
) -> UUID:
    async with factory.begin() as session:
        job_id = await JobRepository(session).enqueue(
            NewJob(
                monitored_chat_id=chat_pk,
                telegram_chat_id=CHAT_ID,
                telegram_message_id=message_id,
                topic_id=TOPIC_ID,
                message_text=f"target {message_id}",
                telegram_created_at=datetime.now(UTC),
            )
        )
        job = await session.get(ProcessingJob, job_id)
        assert job is not None
        job.status = (
            ProcessingJobStatus.AWAITING_REPLY_CONTEXT
            if context_required
            else ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING
        )
        await UsageRepository(session).record_stage(
            telegram_chat_id=CHAT_ID,
            telegram_message_id=message_id,
            stage=1,
            queued_at=job.created_at,
            model="runtime-model",
            response=_response(relevant=not context_required, context_required=context_required),
            pricing=ClassificationPricing(Decimal("1"), Decimal("2")),
        )
        return job_id


async def _exercise_downstream_runtime() -> None:
    engine = create_async_engine(_database_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chat_pk = uuid4()
    message_ids = (201, 202)
    transport = FinalRelevantTransport()
    pricing = ClassificationPricing(Decimal("1"), Decimal("2"))
    chain_worker = DownstreamQueueWorker(
        factory,
        "listener-chain-test",
        DownstreamPhase.REPLY_CHAIN,
        ReplyChainSnapshotHandler(RuntimeReplySource(message_ids)),
    )
    classifier_worker = DownstreamQueueWorker(
        factory,
        "classifier-downstream-test",
        DownstreamPhase.CLASSIFICATION,
        DownstreamClassificationHandler(
            Stage2ClassificationService(
                OpenAIClassificationAdapter(
                    transport=transport,
                    model="runtime-model",
                    timeout_seconds=2,
                ),
                pricing,
            ),
            RelevantQuestionPersistenceService(operator_telegram_user_id=99),
        ),
    )
    notification_bot = RecordingNotificationBot()
    notification_worker = BotNotificationWorker(factory, notification_bot, 99)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "TRUNCATE classification_runs, api_usage_daily, monitored_chats CASCADE"
            )
        async with factory.begin() as session:
            session.add(
                MonitoredChat(
                    id=chat_pk,
                    telegram_chat_id=CHAT_ID,
                    title="Runtime forum",
                    chat_type=MonitoredChatType.FORUM_SUPERGROUP,
                    status=MonitoredChatStatus.ACTIVE,
                    added_by_telegram_user_id=1,
                )
            )
        direct_id = await _seed_job(factory, chat_pk, message_ids[0], context_required=False)
        context_id = await _seed_job(factory, chat_pk, message_ids[1], context_required=True)

        assert await chain_worker.run_once()
        assert await chain_worker.run_once()
        assert not await chain_worker.run_once()
        async with factory() as session:
            assert (await session.get(ProcessingJob, direct_id)).reply_chain_snapshot is not None  # type: ignore[union-attr]
            assert (await session.get(ProcessingJob, context_id)).reply_chain_snapshot is not None  # type: ignore[union-attr]

        assert await classifier_worker.run_once()
        assert await classifier_worker.run_once()
        assert await classifier_worker.run_once()
        assert not await classifier_worker.run_once()

        async with factory() as session:
            assert await session.get(ProcessingJob, direct_id) is None
            assert await session.get(ProcessingJob, context_id) is None
            assert await session.scalar(select(func.count()).select_from(DetectedQuestion)) == 2
            assert await session.scalar(select(func.count()).select_from(BotNotification)) == 2
            questions = list(
                await session.scalars(
                    select(DetectedQuestion).order_by(DetectedQuestion.telegram_message_id)
                )
            )
            assert [question.telegram_message_id for question in questions] == list(message_ids)
            assert all(question.topic_id == TOPIC_ID for question in questions)
        assert len(transport.calls) == 1
        assert transport.calls[0].endswith("[TARGET]\ntarget 202")

        assert await notification_worker.run_once()
        assert await notification_worker.run_once()
        assert not await notification_worker.run_once()
        async with factory() as session:
            notifications = list(
                await session.scalars(select(BotNotification).order_by(BotNotification.created_at))
            )
            assert [notification.status for notification in notifications] == ["sent", "sent"]
            assert all(notification.bot_message_id is not None for notification in notifications)
            assert all(notification.sent_at is not None for notification in notifications)
        assert notification_bot.destinations == [99, 99]
    finally:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "TRUNCATE classification_runs, api_usage_daily, monitored_chats CASCADE"
            )
        await engine.dispose()


def test_listener_snapshot_and_classifier_downstream_runtime() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise_downstream_runtime())
