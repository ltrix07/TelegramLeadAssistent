"""Integration coverage for durable Stage-1 classification routing."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.classifier.openai_adapter import (
    ClassificationPermanentError,
    ClassificationResponse,
    ClassificationSchemaError,
    ClassificationUsage,
    OpenAIClassificationAdapter,
)
from app.classifier.schemas import (
    ClassificationCategory,
    ClassificationReasonCode,
    ClassificationResult,
)
from app.classifier.usage import ClassificationPricing
from app.classifier.worker import Stage1ClassificationHandler
from app.database.models import ApiUsageDaily, ClassificationRun, MonitoredChat, ProcessingJob
from app.database.queue import JobRepository, NewJob
from app.database.worker import QueueWorker
from app.domain.enums import MonitoredChatStatus, MonitoredChatType, ProcessingJobStatus

pytestmark = pytest.mark.integration


class FakeTransport:
    """Record target-only calls and return results keyed by target text."""

    def __init__(self, results: dict[str, ClassificationResult]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    async def classify(
        self,
        *,
        model: str,
        instructions: str,
        target_text: str,
        timeout_seconds: float,
    ) -> ClassificationResponse:
        self.calls.append(
            {
                "model": model,
                "instructions": instructions,
                "target_text": target_text,
                "timeout_seconds": timeout_seconds,
            }
        )
        return ClassificationResponse(
            result=self.results[target_text],
            usage=ClassificationUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for Stage-1 integration tests")
    return value


async def _enqueue(
    factory: async_sessionmaker[AsyncSession], monitored_chat_id: UUID, message_id: int, text: str
) -> UUID:
    async with factory.begin() as session:
        return await JobRepository(session).enqueue(
            NewJob(
                monitored_chat_id=monitored_chat_id,
                telegram_chat_id=-100123456789,
                telegram_message_id=message_id,
                sender_telegram_id=123,
                sender_display_name="Must not reach API",
                message_text=text,
                telegram_created_at=datetime.now(UTC),
            )
        )


async def _exercise(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chat_id = uuid4()
    results = {
        "irrelevant target": ClassificationResult.model_validate(
            {
                "is_relevant": False,
                "category": ClassificationCategory.IRRELEVANT,
                "confidence": 0.99,
                "context_required": False,
                "reason_code": ClassificationReasonCode.CASUAL_CONVERSATION,
            }
        ),
        "relevant target": ClassificationResult.model_validate(
            {
                "is_relevant": True,
                "category": ClassificationCategory.TECHNICAL,
                "confidence": 0.94,
                "context_required": False,
                "reason_code": ClassificationReasonCode.TECHNICAL_PROBLEM,
            }
        ),
        "context target": ClassificationResult.model_validate(
            {
                "is_relevant": False,
                "category": ClassificationCategory.IRRELEVANT,
                "confidence": 0.51,
                "context_required": True,
                "reason_code": ClassificationReasonCode.INSUFFICIENT_CONTEXT,
            }
        ),
    }
    transport = FakeTransport(results)
    adapter = OpenAIClassificationAdapter(
        transport=transport,
        model="configured-test-model",
        timeout_seconds=7,
    )
    worker = QueueWorker(
        factory,
        "stage1-test",
        Stage1ClassificationHandler(
            adapter,
            ClassificationPricing(
                input_per_million_usd=Decimal("1"),
                output_per_million_usd=Decimal("2"),
            ),
        ),
    )
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE monitored_chats CASCADE")
        async with factory.begin() as session:
            session.add(
                MonitoredChat(
                    id=chat_id,
                    telegram_chat_id=-100123456789,
                    title="Test chat",
                    chat_type=MonitoredChatType.SUPERGROUP,
                    status=MonitoredChatStatus.ACTIVE,
                    added_by_telegram_user_id=1,
                )
            )

        irrelevant_id = await _enqueue(factory, chat_id, 1, "irrelevant target")
        relevant_id = await _enqueue(factory, chat_id, 2, "relevant target")
        context_id = await _enqueue(factory, chat_id, 3, "context target")
        assert await worker.run_once()
        assert await worker.run_once()
        assert await worker.run_once()
        assert not await worker.run_once()

        async with factory() as session:
            assert await session.get(ProcessingJob, irrelevant_id) is None
            relevant = await session.get(ProcessingJob, relevant_id)
            context = await session.get(ProcessingJob, context_id)
            assert relevant is not None
            assert relevant.status is ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING
            assert relevant.message_text == "relevant target"
            assert context is not None
            assert context.status is ProcessingJobStatus.AWAITING_REPLY_CONTEXT
            assert context.message_text == "context target"
            assert not list(
                await session.scalars(
                    select(ProcessingJob).where(
                        ProcessingJob.status == ProcessingJobStatus.PROCESSING
                    )
                )
            )
            runs = list(
                await session.scalars(
                    select(ClassificationRun).order_by(ClassificationRun.telegram_message_id)
                )
            )
            assert len(runs) == 3
            assert [run.input_tokens for run in runs] == [10, 10, 10]
            assert [run.output_tokens for run in runs] == [5, 5, 5]
            assert all(run.estimated_cost_usd == Decimal("0.000020") for run in runs)
            assert not any(
                column.name in {"message_text", "original_text", "text"}
                for column in ClassificationRun.__table__.columns
            )
            daily = (await session.scalars(select(ApiUsageDaily))).one()
            assert daily.model == "configured-test-model"
            assert daily.request_count == 3
            assert daily.input_tokens == 30
            assert daily.output_tokens == 15
            assert daily.estimated_cost_usd == Decimal("0.000060")

        assert [call["target_text"] for call in transport.calls] == [
            "irrelevant target",
            "relevant target",
            "context target",
        ]
        assert all(
            set(call) == {"model", "instructions", "target_text", "timeout_seconds"}
            for call in transport.calls
        )
        assert all(call["model"] == "configured-test-model" for call in transport.calls)
    finally:
        await engine.dispose()


def test_stage1_worker_routes_each_target_once() -> None:
    database_url = _database_url()
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise(database_url))


class ScriptedTransport:
    """Return or raise scripted outcomes without making network calls."""

    def __init__(self, outcomes: list[ClassificationResponse | Exception]) -> None:
        self.outcomes = outcomes
        self.call_count = 0

    async def classify(
        self,
        *,
        model: str,
        instructions: str,
        target_text: str,
        timeout_seconds: float,
    ) -> ClassificationResponse:
        del model, instructions, target_text, timeout_seconds
        outcome = self.outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _successful_response() -> ClassificationResponse:
    return ClassificationResponse(
        result=ClassificationResult.model_validate(
            {
                "is_relevant": True,
                "category": ClassificationCategory.TECHNICAL,
                "confidence": 0.9,
                "context_required": False,
                "reason_code": ClassificationReasonCode.TECHNICAL_PROBLEM,
            }
        ),
        usage=ClassificationUsage(input_tokens=8, output_tokens=3, total_tokens=11),
    )


def _make_worker(
    factory: async_sessionmaker[AsyncSession], transport: ScriptedTransport
) -> QueueWorker:
    return QueueWorker(
        factory,
        "failure-policy-test",
        Stage1ClassificationHandler(
            OpenAIClassificationAdapter(
                transport=transport,
                model="configured-test-model",
                timeout_seconds=2,
            ),
            ClassificationPricing(
                input_per_million_usd=Decimal("1"),
                output_per_million_usd=Decimal("2"),
            ),
        ),
    )


async def _force_retry_ready(factory: async_sessionmaker[AsyncSession], job_id: UUID) -> None:
    async with factory.begin() as session:
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(next_attempt_at=datetime.now(UTC))
        )


async def _exercise_failure_policy(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chat_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE monitored_chats CASCADE")
        async with factory.begin() as session:
            session.add(
                MonitoredChat(
                    id=chat_id,
                    telegram_chat_id=-100123456789,
                    title="Retry policy chat",
                    chat_type=MonitoredChatType.SUPERGROUP,
                    status=MonitoredChatStatus.ACTIVE,
                    added_by_telegram_user_id=1,
                )
            )

        retry_id = await _enqueue(factory, chat_id, 10, "retry then succeed")
        retry_transport = ScriptedTransport(
            [ClassificationSchemaError("bad schema"), _successful_response()]
        )
        retry_worker = _make_worker(factory, retry_transport)
        assert await retry_worker.run_once()
        async with factory() as session:
            retry_job = await session.get(ProcessingJob, retry_id)
            assert retry_job is not None
            assert retry_job.status is ProcessingJobStatus.RETRY
            assert retry_job.attempt_count == 1
            assert retry_job.last_error_code == "CLASSIFICATION_SCHEMA"
            assert retry_job.next_attempt_at > datetime.now(UTC)
            assert not list(
                await session.scalars(
                    select(ClassificationRun).where(ClassificationRun.telegram_message_id == 10)
                )
            )

        await _force_retry_ready(factory, retry_id)
        assert await retry_worker.run_once()
        assert not await retry_worker.run_once()
        assert retry_transport.call_count == 2
        async with factory() as session:
            retry_job = await session.get(ProcessingJob, retry_id)
            assert retry_job is not None
            assert retry_job.status is ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING
            assert (
                len(
                    list(
                        await session.scalars(
                            select(ClassificationRun).where(
                                ClassificationRun.telegram_message_id == 10
                            )
                        )
                    )
                )
                == 1
            )

        exhausted_id = await _enqueue(factory, chat_id, 11, "always invalid")
        exhausted_transport = ScriptedTransport(
            [ClassificationSchemaError("bad schema") for _ in range(5)]
        )
        exhausted_worker = _make_worker(factory, exhausted_transport)
        for attempt in range(1, 6):
            assert await exhausted_worker.run_once()
            if attempt < 5:
                await _force_retry_ready(factory, exhausted_id)
        async with factory() as session:
            exhausted = await session.get(ProcessingJob, exhausted_id)
            assert exhausted is not None
            assert exhausted.status is ProcessingJobStatus.FAILED
            assert exhausted.attempt_count == 5
            assert exhausted.last_error_code == "CLASSIFICATION_SCHEMA"

        permanent_id = await _enqueue(factory, chat_id, 12, "permanent failure")
        permanent_transport = ScriptedTransport([ClassificationPermanentError("request rejected")])
        permanent_worker = _make_worker(factory, permanent_transport)
        assert await permanent_worker.run_once()
        async with factory() as session:
            permanent = await session.get(ProcessingJob, permanent_id)
            assert permanent is not None
            assert permanent.status is ProcessingJobStatus.FAILED
            assert permanent.attempt_count == 1
            assert permanent.last_error_code == "CLASSIFICATION_PERMANENT"
        assert permanent_transport.call_count == 1
    finally:
        await engine.dispose()


def test_stage1_worker_applies_bounded_api_failure_policy() -> None:
    database_url = _database_url()
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise_failure_policy(database_url))
