"""PostgreSQL integration coverage for atomic relevant-question persistence."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.classifier.openai_adapter import ClassificationResponse, ClassificationUsage
from app.classifier.relevant import RelevantQuestionPersistenceService
from app.classifier.schemas import (
    ClassificationCategory,
    ClassificationReasonCode,
    ClassificationResult,
)
from app.classifier.usage import ClassificationPricing, UsageRepository
from app.database.models import (
    BotNotification,
    DetectedQuestion,
    MonitoredChat,
    ProcessingJob,
    QuestionChainMessage,
)
from app.database.queue import JobRepository, NewJob
from app.domain.enums import MonitoredChatStatus, MonitoredChatType, ProcessingJobStatus
from app.listener.reply_chain import ReplyChain, ReplyChainItem
from app.translation.client import FakeTranslationAdapter

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for persistence integration tests")
    return value


def _classification_response() -> ClassificationResponse:
    return ClassificationResponse(
        result=ClassificationResult.model_validate(
            {
                "is_relevant": True,
                "category": ClassificationCategory.TECHNICAL,
                "confidence": 0.93,
                "context_required": False,
                "reason_code": ClassificationReasonCode.TECHNICAL_PROBLEM,
            }
        ),
        usage=ClassificationUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )


async def _seed_job(
    factory: async_sessionmaker[AsyncSession], chat_pk: UUID, message_id: int
) -> UUID:
    async with factory.begin() as session:
        job_id = await JobRepository(session).enqueue(
            NewJob(
                monitored_chat_id=chat_pk,
                telegram_chat_id=-100123,
                telegram_message_id=message_id,
                sender_telegram_id=42,
                sender_display_name="Customer",
                message_text="How can I fix it?",
                telegram_created_at=datetime.now(UTC),
            )
        )
        job = await session.get(ProcessingJob, job_id)
        assert job is not None
        job.status = ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING
        await UsageRepository(session).record_stage(
            telegram_chat_id=job.telegram_chat_id,
            telegram_message_id=job.telegram_message_id,
            stage=1,
            model="test-model",
            response=_classification_response(),
            pricing=ClassificationPricing(Decimal("1"), Decimal("2")),
        )
        return job_id


def _chain(message_id: int) -> ReplyChain:
    now = datetime.now(UTC)
    return ReplyChain(
        chat_id=-100123,
        items=(
            ReplyChainItem(10, None, None, None, 7, "Parent", now, "Deploy failed", False),
            ReplyChainItem(
                message_id, 10, None, None, 42, "Customer", now, "How can I fix it?", True
            ),
        ),
    )


@pytest.mark.asyncio
async def test_persistence_is_atomic_and_idempotent() -> None:
    engine = create_async_engine(_database_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chat_pk = uuid4()
    translator = FakeTranslationAdapter(
        detected_languages={"Deploy failed": "en", "How can I fix it?": "en"},
        translations={"Deploy failed": "Развёртывание не удалось"},
        failing_texts={"How can I fix it?"},
    )
    service = RelevantQuestionPersistenceService(
        operator_telegram_user_id=99,
        translation_service=translator,
        translation_enabled=True,
    )
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "TRUNCATE classification_runs, api_usage_daily, monitored_chats CASCADE"
            )
        async with factory.begin() as session:
            session.add(
                MonitoredChat(
                    id=chat_pk,
                    telegram_chat_id=-100123,
                    title="Test",
                    chat_type=MonitoredChatType.SUPERGROUP,
                    status=MonitoredChatStatus.ACTIVE,
                    added_by_telegram_user_id=1,
                )
            )

        rollback_job_id = await _seed_job(factory, chat_pk, 20)
        with pytest.raises(RuntimeError, match="force rollback"):
            async with factory.begin() as session:
                job = await session.get(ProcessingJob, rollback_job_id)
                assert job is not None
                await service.persist(job, _chain(20), session)
                raise RuntimeError("force rollback")

        async with factory() as session:
            assert await session.get(ProcessingJob, rollback_job_id) is not None
            assert await session.scalar(select(func.count()).select_from(DetectedQuestion)) == 0
            assert await session.scalar(select(func.count()).select_from(BotNotification)) == 0
        translator.translation_calls.clear()

        async with factory.begin() as session:
            job = await session.get(ProcessingJob, rollback_job_id)
            assert job is not None
            question_id = await service.persist(job, _chain(20), session)

        async with factory.begin() as session:
            duplicate_job_id = await JobRepository(session).enqueue(
                NewJob(
                    monitored_chat_id=chat_pk,
                    telegram_chat_id=-100123,
                    telegram_message_id=20,
                    message_text="retry raw text",
                    telegram_created_at=datetime.now(UTC),
                )
            )
            duplicate = await session.get(ProcessingJob, duplicate_job_id)
            assert duplicate is not None
            duplicate.status = ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING
            assert await service.persist(duplicate, _chain(20), session) == question_id

        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(DetectedQuestion)) == 1
            assert await session.scalar(select(func.count()).select_from(QuestionChainMessage)) == 2
            assert await session.scalar(select(func.count()).select_from(BotNotification)) == 1
            notification = (await session.scalars(select(BotNotification))).one()
            assert notification.status == "pending"
            assert notification.operator_telegram_user_id == 99
            assert notification.bot_chat_id == 99
            assert await session.get(ProcessingJob, duplicate_job_id) is None
            question = await session.get(DetectedQuestion, question_id)
            assert question is not None
            assert question.category == ClassificationCategory.TECHNICAL.value
            assert question.confidence == Decimal("0.9300")
            assert question.translated_text is None
            assert question.source_language == "en"
            chain_rows = list(
                await session.scalars(
                    select(QuestionChainMessage)
                    .where(QuestionChainMessage.question_id == question_id)
                    .order_by(QuestionChainMessage.position)
                )
            )
            assert [row.translation_status for row in chain_rows] == [
                "translated",
                "failed",
            ]
            assert [row.source_language for row in chain_rows] == ["en", "en"]
            assert [row.translated_text for row in chain_rows] == [
                "Развёртывание не удалось",
                None,
            ]
            assert translator.translation_calls == [
                "Deploy failed",
                "How can I fix it?",
            ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_irrelevant_completion_retains_no_raw_text() -> None:
    engine = create_async_engine(_database_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chat_pk = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "TRUNCATE classification_runs, api_usage_daily, monitored_chats CASCADE"
            )
        async with factory.begin() as session:
            session.add(
                MonitoredChat(
                    id=chat_pk,
                    telegram_chat_id=-100123,
                    title="Test",
                    chat_type=MonitoredChatType.SUPERGROUP,
                    status=MonitoredChatStatus.ACTIVE,
                    added_by_telegram_user_id=1,
                )
            )
        async with factory.begin() as session:
            job_id = await JobRepository(session).enqueue(
                NewJob(
                    monitored_chat_id=chat_pk,
                    telegram_chat_id=-100123,
                    telegram_message_id=30,
                    message_text="raw irrelevant text",
                    telegram_created_at=datetime.now(UTC),
                )
            )
            await JobRepository(session).complete(job_id)

        async with factory() as session:
            assert await session.get(ProcessingJob, job_id) is None
            assert await session.scalar(select(func.count()).select_from(DetectedQuestion)) == 0
            assert await session.scalar(select(func.count()).select_from(QuestionChainMessage)) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_translation_disabled_still_persists_notification() -> None:
    engine = create_async_engine(_database_url())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chat_pk = uuid4()
    service = RelevantQuestionPersistenceService(operator_telegram_user_id=99)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql(
                "TRUNCATE classification_runs, api_usage_daily, monitored_chats CASCADE"
            )
        async with factory.begin() as session:
            session.add(
                MonitoredChat(
                    id=chat_pk,
                    telegram_chat_id=-100123,
                    title="Test",
                    chat_type=MonitoredChatType.SUPERGROUP,
                    status=MonitoredChatStatus.ACTIVE,
                    added_by_telegram_user_id=1,
                )
            )
        job_id = await _seed_job(factory, chat_pk, 40)

        async with factory.begin() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            question_id = await service.persist(job, _chain(40), session)

        async with factory() as session:
            notification = await session.scalar(
                select(BotNotification).where(BotNotification.question_id == question_id)
            )
            assert notification is not None
            chain_rows = list(
                await session.scalars(
                    select(QuestionChainMessage).where(
                        QuestionChainMessage.question_id == question_id
                    )
                )
            )
            assert {row.translation_status for row in chain_rows} == {"disabled"}
            assert all(row.translated_text is None for row in chain_rows)
            assert all(row.source_language is None for row in chain_rows)
    finally:
        await engine.dispose()
