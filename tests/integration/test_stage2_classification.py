"""PostgreSQL integration coverage for final Stage-2 classification."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.classifier.openai_adapter import (
    ClassificationResponse,
    ClassificationUsage,
    OpenAIClassificationAdapter,
)
from app.classifier.schemas import (
    ClassificationCategory,
    ClassificationReasonCode,
    ClassificationResult,
)
from app.classifier.stage2 import Stage2ClassificationError, Stage2ClassificationService
from app.classifier.usage import ClassificationPricing, UsageRepository
from app.database.models import ClassificationRun, MonitoredChat, ProcessingJob
from app.database.queue import JobRepository, NewJob
from app.domain.enums import MonitoredChatStatus, MonitoredChatType, ProcessingJobStatus
from app.listener.reply_chain import ReplyChain, ReplyChainItem

pytestmark = pytest.mark.integration


class RecordingTransport:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def classify(
        self, *, model: str, instructions: str, target_text: str, timeout_seconds: float
    ) -> ClassificationResponse:
        del model, instructions, timeout_seconds
        self.inputs.append(target_text)
        return _response(is_relevant=True, context_required=False)


def _response(*, is_relevant: bool, context_required: bool) -> ClassificationResponse:
    return ClassificationResponse(
        result=ClassificationResult.model_validate(
            {
                "is_relevant": is_relevant,
                "category": (
                    ClassificationCategory.TECHNICAL
                    if is_relevant
                    else ClassificationCategory.IRRELEVANT
                ),
                "confidence": 0.91,
                "context_required": context_required,
                "reason_code": (
                    ClassificationReasonCode.TECHNICAL_PROBLEM
                    if is_relevant
                    else ClassificationReasonCode.INSUFFICIENT_CONTEXT
                ),
            }
        ),
        usage=ClassificationUsage(input_tokens=20, output_tokens=5, total_tokens=25),
    )


def _chain() -> ReplyChain:
    now = datetime.now(UTC)
    return ReplyChain(
        chat_id=-100123,
        items=(
            ReplyChainItem(10, None, None, None, None, None, now, "Deploy failed", False),
            ReplyChainItem(11, 10, None, None, None, None, now, "How can I fix it?", True),
        ),
    )


@pytest.mark.asyncio
async def test_stage2_requires_context_stage1_persists_final_decision_and_cannot_repeat() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for Stage-2 integration tests")
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    transport = RecordingTransport()
    adapter = OpenAIClassificationAdapter(
        transport=transport, model="configured-test-model", timeout_seconds=2
    )
    pricing = ClassificationPricing(Decimal("1"), Decimal("2"))
    service = Stage2ClassificationService(adapter, pricing)
    monitored_chat_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE monitored_chats CASCADE")
        async with factory.begin() as session:
            session.add(
                MonitoredChat(
                    id=monitored_chat_id,
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
                    monitored_chat_id=monitored_chat_id,
                    telegram_chat_id=-100123,
                    telegram_message_id=11,
                    message_text="How can I fix it?",
                    telegram_created_at=datetime.now(UTC),
                )
            )
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            job.status = ProcessingJobStatus.AWAITING_REPLY_CONTEXT
            await UsageRepository(session).record_stage(
                telegram_chat_id=job.telegram_chat_id,
                telegram_message_id=job.telegram_message_id,
                stage=1,
                model=adapter.model,
                response=_response(is_relevant=False, context_required=True),
                pricing=pricing,
            )

            final_stage1_job_id = await JobRepository(session).enqueue(
                NewJob(
                    monitored_chat_id=monitored_chat_id,
                    telegram_chat_id=-100123,
                    telegram_message_id=12,
                    message_text="Final at Stage 1",
                    telegram_created_at=datetime.now(UTC),
                )
            )
            final_stage1_job = await session.get(ProcessingJob, final_stage1_job_id)
            assert final_stage1_job is not None
            final_stage1_job.status = ProcessingJobStatus.AWAITING_REPLY_CONTEXT
            await UsageRepository(session).record_stage(
                telegram_chat_id=final_stage1_job.telegram_chat_id,
                telegram_message_id=final_stage1_job.telegram_message_id,
                stage=1,
                model=adapter.model,
                response=_response(is_relevant=True, context_required=False),
                pricing=pricing,
            )

        async with factory.begin() as session:
            final_stage1_job = await session.get(ProcessingJob, final_stage1_job_id)
            assert final_stage1_job is not None
            with pytest.raises(Stage2ClassificationError):
                await service.classify(final_stage1_job, _chain(), session)
        assert transport.inputs == []

        async with factory.begin() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            await service.classify(job, _chain(), session)

        async with factory.begin() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            assert job.status is ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING
            runs = list(
                await session.scalars(
                    select(ClassificationRun)
                    .where(ClassificationRun.telegram_message_id == 11)
                    .order_by(ClassificationRun.stage)
                )
            )
            assert [run.stage for run in runs] == [1, 2]
            assert runs[1].result == "relevant"
            job.status = ProcessingJobStatus.AWAITING_REPLY_CONTEXT
            with pytest.raises(Stage2ClassificationError):
                await service.classify(job, _chain(), session)

        assert len(transport.inputs) == 1
        assert transport.inputs[0].endswith("[TARGET]\nHow can I fix it?")
    finally:
        await engine.dispose()
