"""M5 integration gate for reply-context classification and persistence."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
from app.classifier.stage2 import Stage2ClassificationError, Stage2ClassificationService
from app.classifier.usage import ClassificationPricing, UsageRepository
from app.database.models import (
    BotNotification,
    ClassificationRun,
    DetectedQuestion,
    MonitoredChat,
    ProcessingJob,
    QuestionChainMessage,
)
from app.database.queue import JobRepository, NewJob
from app.domain.enums import MonitoredChatStatus, MonitoredChatType, ProcessingJobStatus
from app.listener.reply_chain import ReplyChainLoader, ReplyMessage

pytestmark = pytest.mark.integration

CHAT_ID = -100555
TARGET_MESSAGE_ID = 101
PARENT_MESSAGE_ID = 100
TOPIC_ID = 77


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for the M5 integration gate")
    return value


def _result(*, context_required: bool) -> ClassificationResponse:
    return ClassificationResponse(
        result=ClassificationResult.model_validate(
            {
                "is_relevant": not context_required,
                "category": (
                    ClassificationCategory.TECHNICAL
                    if not context_required
                    else ClassificationCategory.IRRELEVANT
                ),
                "confidence": 0.92,
                "context_required": context_required,
                "reason_code": (
                    ClassificationReasonCode.TECHNICAL_PROBLEM
                    if not context_required
                    else ClassificationReasonCode.INSUFFICIENT_CONTEXT
                ),
            }
        ),
        usage=ClassificationUsage(input_tokens=12, output_tokens=4, total_tokens=16),
    )


class FinalRelevantTransport:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def classify(
        self, *, model: str, instructions: str, target_text: str, timeout_seconds: float
    ) -> ClassificationResponse:
        del model, instructions, timeout_seconds
        self.inputs.append(target_text)
        return _result(context_required=False)


class ForumReplySource:
    def __init__(self, *, deleted_parent: bool) -> None:
        now = datetime.now(UTC)
        self._messages = {
            TARGET_MESSAGE_ID: ReplyMessage(
                CHAT_ID,
                TARGET_MESSAGE_ID,
                PARENT_MESSAGE_ID,
                TOPIC_ID,
                TOPIC_ID,
                42,
                "Customer",
                now,
                "How can I fix it?",
            ),
        }
        if not deleted_parent:
            self._messages[PARENT_MESSAGE_ID] = ReplyMessage(
                CHAT_ID,
                PARENT_MESSAGE_ID,
                None,
                TOPIC_ID,
                TOPIC_ID,
                7,
                "Parent author",
                now - timedelta(minutes=1),
                "The deployment failed.",
            )

    async def get_reply_message(self, chat_id: int, message_id: int) -> ReplyMessage | None:
        assert chat_id == CHAT_ID
        return self._messages.get(message_id)

    async def get_forum_topic_title(self, chat_id: int, topic_id: int) -> str | None:
        assert (chat_id, topic_id) == (CHAT_ID, TOPIC_ID)
        return "Deployments"


async def _seed_context_job(factory: async_sessionmaker[AsyncSession], chat_pk: UUID) -> UUID:
    async with factory.begin() as session:
        job_id = await JobRepository(session).enqueue(
            NewJob(
                monitored_chat_id=chat_pk,
                telegram_chat_id=CHAT_ID,
                telegram_message_id=TARGET_MESSAGE_ID,
                topic_id=TOPIC_ID,
                sender_telegram_id=42,
                sender_display_name="Customer",
                message_text="How can I fix it?",
                telegram_created_at=datetime.now(UTC),
            )
        )
        job = await session.get(ProcessingJob, job_id)
        assert job is not None
        job.status = ProcessingJobStatus.AWAITING_REPLY_CONTEXT
        await UsageRepository(session).record_stage(
            telegram_chat_id=CHAT_ID,
            telegram_message_id=TARGET_MESSAGE_ID,
            stage=1,
            model="gate-model",
            response=_result(context_required=True),
            pricing=ClassificationPricing(Decimal("1"), Decimal("2")),
        )
        return job_id


@pytest.mark.asyncio
@pytest.mark.parametrize("deleted_parent", [False, True], ids=["forum-topic", "deleted-parent"])
async def test_m5_reply_context_gate(deleted_parent: bool) -> None:
    engine = create_async_engine(_database_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chat_pk = uuid4()
    transport = FinalRelevantTransport()
    stage2 = Stage2ClassificationService(
        OpenAIClassificationAdapter(
            transport=transport,
            model="gate-model",
            timeout_seconds=2,
        ),
        ClassificationPricing(Decimal("1"), Decimal("2")),
    )
    persistence = RelevantQuestionPersistenceService(operator_telegram_user_id=99)
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
                    title="Forum",
                    chat_type=MonitoredChatType.FORUM_SUPERGROUP,
                    status=MonitoredChatStatus.ACTIVE,
                    added_by_telegram_user_id=1,
                )
            )
        job_id = await _seed_context_job(factory, chat_pk)
        chain = await ReplyChainLoader(
            ForumReplySource(deleted_parent=deleted_parent)
        ).get_reply_chain(CHAT_ID, TARGET_MESSAGE_ID)

        assert chain.topic_id == TOPIC_ID
        assert chain.topic_title == "Deployments"
        assert chain.items[-1].is_target
        assert chain.items[0].is_unavailable is deleted_parent

        async with factory.begin() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            await stage2.classify(job, chain, session)

        async with factory.begin() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            assert job.status is ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING
            question_id = await persistence.persist(job, chain, session)

        async with factory.begin() as session:
            duplicate_job_id = await JobRepository(session).enqueue(
                NewJob(
                    monitored_chat_id=chat_pk,
                    telegram_chat_id=CHAT_ID,
                    telegram_message_id=TARGET_MESSAGE_ID,
                    message_text="duplicate raw text",
                    telegram_created_at=datetime.now(UTC),
                )
            )
            duplicate = await session.get(ProcessingJob, duplicate_job_id)
            assert duplicate is not None
            duplicate.status = ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING
            assert await persistence.persist(duplicate, chain, session) == question_id

        async with factory.begin() as session:
            duplicate_stage2_job_id = await JobRepository(session).enqueue(
                NewJob(
                    monitored_chat_id=chat_pk,
                    telegram_chat_id=CHAT_ID,
                    telegram_message_id=TARGET_MESSAGE_ID + 1,
                    message_text="duplicate result",
                    telegram_created_at=datetime.now(UTC),
                )
            )
            duplicate_stage2_job = await session.get(ProcessingJob, duplicate_stage2_job_id)
            assert duplicate_stage2_job is not None
            duplicate_stage2_job.status = ProcessingJobStatus.AWAITING_REPLY_CONTEXT
            with pytest.raises(Stage2ClassificationError):
                await stage2.classify(duplicate_stage2_job, chain, session)

        async with factory() as session:
            question = await session.get(DetectedQuestion, question_id)
            assert question is not None
            assert question.topic_id == TOPIC_ID
            assert question.topic_title == "Deployments"
            assert timedelta(days=59, hours=23) < question.expires_at - question.detected_at
            assert question.expires_at - question.detected_at < timedelta(days=60, minutes=1)

            chain_rows = list(
                await session.scalars(
                    select(QuestionChainMessage)
                    .where(QuestionChainMessage.question_id == question_id)
                    .order_by(QuestionChainMessage.position)
                )
            )
            assert len(chain_rows) == (1 if deleted_parent else 2)
            assert chain_rows[-1].is_target
            assert all(row.translation_status == "disabled" for row in chain_rows)
            assert await session.scalar(select(func.count()).select_from(DetectedQuestion)) == 1
            assert await session.scalar(select(func.count()).select_from(BotNotification)) == 1
            assert [
                run.stage
                for run in await session.scalars(
                    select(ClassificationRun).order_by(ClassificationRun.stage)
                )
            ] == [1, 2]
            assert not any(
                column.name in {"message_text", "original_text", "text", "prompt"}
                for column in ClassificationRun.__table__.columns
            )

        assert len(transport.inputs) == 1
        assert transport.inputs[0].endswith("[TARGET]\nHow can I fix it?")
        assert ("[unavailable message]" in transport.inputs[0]) is deleted_parent
    finally:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "TRUNCATE classification_runs, api_usage_daily, monitored_chats CASCADE"
            )
        await engine.dispose()
