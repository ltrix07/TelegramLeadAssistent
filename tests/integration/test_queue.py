"""Integration tests for PostgreSQL queue delivery and locking semantics."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.database.models import MonitoredChat, ProcessingJob
from app.database.queue import JobRepository, NewJob
from app.database.worker import QueueWorker, recover_stale_jobs
from app.domain.enums import MonitoredChatStatus, MonitoredChatType
from app.listener.events.incoming import IncomingMessage
from app.listener.events.ingestion import database_message_persister

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for queue integration tests")
    return value


def _new_job(monitored_chat_id: UUID, message_id: int) -> NewJob:
    return NewJob(
        monitored_chat_id=monitored_chat_id,
        telegram_chat_id=-100123456789,
        telegram_message_id=message_id,
        message_text=f"test message {message_id}",
        telegram_created_at=datetime.now(UTC),
    )


async def _prepare_chat(database_url: str) -> UUID:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monitored_chat_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE monitored_chats CASCADE")
        async with factory.begin() as session:
            session.add(
                MonitoredChat(
                    id=monitored_chat_id,
                    telegram_chat_id=-100123456789,
                    title="Integration Test Chat",
                    chat_type=MonitoredChatType.SUPERGROUP,
                    status=MonitoredChatStatus.ACTIVE,
                    added_by_telegram_user_id=1,
                )
            )
        return monitored_chat_id
    finally:
        await engine.dispose()


async def _exercise_queue(database_url: str, monitored_chat_id: UUID) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await _assert_duplicate_enqueue(factory, monitored_chat_id)
        await _assert_duplicate_ingestion(factory)
        await _assert_concurrent_claims_skip_locked(factory, monitored_chat_id)
        await _assert_retry_time_and_completion(factory, monitored_chat_id)
        await _assert_stale_recovery(factory, monitored_chat_id)
        await _assert_rollback_preserves_at_least_once(factory, monitored_chat_id)
        await _assert_worker_retry_and_poison_state(factory, monitored_chat_id)
        await _assert_queue_age_metric(factory, monitored_chat_id)
    finally:
        await engine.dispose()


async def _assert_duplicate_enqueue(
    factory: async_sessionmaker[AsyncSession], monitored_chat_id: UUID
) -> None:
    async with factory.begin() as session:
        repository = JobRepository(session)
        first_id = await repository.enqueue(_new_job(monitored_chat_id, 1))
        duplicate_id = await repository.enqueue(_new_job(monitored_chat_id, 1))
        count = await session.scalar(select(func.count()).select_from(ProcessingJob))

    assert duplicate_id == first_id
    assert count == 1


async def _assert_duplicate_ingestion(factory: async_sessionmaker[AsyncSession]) -> None:
    message = IncomingMessage(
        telegram_chat_id=-100123456789,
        telegram_message_id=10,
        topic_id=None,
        sender_telegram_id=7,
        sender_display_name="Integration User",
        text="Нужна помощь с настройкой",
        telegram_created_at=datetime.now(UTC),
        is_own=False,
        is_service=False,
        has_sticker=False,
    )
    persist = database_message_persister(factory)

    await persist(message)
    await persist(message)

    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(ProcessingJob.telegram_message_id == message.telegram_message_id)
        )
    assert count == 1


async def _assert_concurrent_claims_skip_locked(
    factory: async_sessionmaker[AsyncSession], monitored_chat_id: UUID
) -> None:
    async with factory.begin() as session:
        await JobRepository(session).enqueue(_new_job(monitored_chat_id, 2))

    first_claimed = asyncio.Event()
    release_first = asyncio.Event()

    async def hold_first_lock() -> UUID:
        async with factory.begin() as session:
            claimed = await JobRepository(session).claim("worker-one")
            assert claimed is not None
            first_claimed.set()
            await release_first.wait()
            return claimed.id

    first_task = asyncio.create_task(hold_first_lock())
    await asyncio.wait_for(first_claimed.wait(), timeout=5)
    async with factory.begin() as session:
        second = await asyncio.wait_for(JobRepository(session).claim("worker-two"), timeout=5)
        assert second is not None
        second_id = second.id
    release_first.set()
    first_id = await first_task

    assert first_id != second_id


async def _assert_retry_time_and_completion(
    factory: async_sessionmaker[AsyncSession], monitored_chat_id: UUID
) -> None:
    async with factory.begin() as session:
        repository = JobRepository(session)
        job_id = await repository.enqueue(_new_job(monitored_chat_id, 3))
        claimed = await repository.claim("retry-worker")
        assert claimed is not None
        await repository.retry(job_id, "TEMPORARY", datetime.now(UTC) + timedelta(hours=1))

    async with factory.begin() as session:
        assert await JobRepository(session).claim("too-early") is None

    async with factory.begin() as session:
        repository = JobRepository(session)
        await repository.retry(job_id, "READY", datetime.now(UTC) - timedelta(seconds=1))
        claimed_again = await repository.claim("retry-worker")
        assert claimed_again is not None
        assert claimed_again.id == job_id
        await repository.complete(job_id)

    async with factory() as session:
        assert await session.get(ProcessingJob, job_id) is None


async def _assert_stale_recovery(
    factory: async_sessionmaker[AsyncSession], monitored_chat_id: UUID
) -> None:
    async with factory.begin() as session:
        repository = JobRepository(session)
        job_id = await repository.enqueue(_new_job(monitored_chat_id, 4))
        claimed = await repository.claim("crashed-worker")
        assert claimed is not None

    async with factory.begin() as session:
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(locked_at=datetime.now(UTC) - timedelta(hours=1))
        )

    async with factory.begin() as session:
        recovered = await JobRepository(session).recover_stale(
            datetime.now(UTC) - timedelta(minutes=5)
        )
    assert recovered == [job_id]

    async with factory.begin() as session:
        claimed_again = await JobRepository(session).claim("recovery-worker")
        assert claimed_again is not None
        assert claimed_again.id == job_id
        assert claimed_again.attempt_count == 2
        assert claimed_again.last_error_code == "STALE_LOCK_RECOVERED"


async def _assert_rollback_preserves_at_least_once(
    factory: async_sessionmaker[AsyncSession], monitored_chat_id: UUID
) -> None:
    async with factory.begin() as session:
        job_id = await JobRepository(session).enqueue(_new_job(monitored_chat_id, 5))

    session = factory()
    try:
        await session.begin()
        first_claim = await JobRepository(session).claim("failed-worker")
        assert first_claim is not None
        assert first_claim.id == job_id
        await session.rollback()
    finally:
        await session.close()

    async with factory.begin() as retry_session:
        second_claim = await JobRepository(retry_session).claim("replacement-worker")
        assert second_claim is not None
        assert second_claim.id == job_id
        assert second_claim.attempt_count == 1


async def _assert_worker_retry_and_poison_state(
    factory: async_sessionmaker[AsyncSession], monitored_chat_id: UUID
) -> None:
    async with factory.begin() as session:
        job_id = await JobRepository(session).enqueue(_new_job(monitored_chat_id, 6))

    async def poison_handler(job: ProcessingJob, session: AsyncSession) -> None:
        job.sender_display_name = "must roll back"
        await session.flush()
        raise TimeoutError

    worker = QueueWorker(factory, "poison-worker", poison_handler)
    for attempt in range(1, 6):
        assert await worker.run_once()
        async with factory.begin() as session:
            job = await session.get(ProcessingJob, job_id)
            assert job is not None
            assert job.attempt_count == attempt
            if attempt < 5:
                await session.execute(
                    update(ProcessingJob)
                    .where(ProcessingJob.id == job_id)
                    .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
                )

    async with factory() as session:
        failed = await session.get(ProcessingJob, job_id)
        assert failed is not None
        assert failed.status.value == "failed"
        assert failed.locked_at is None
        assert failed.locked_by is None
        assert failed.last_error_code == "TimeoutError"
        assert failed.sender_display_name is None


async def _assert_queue_age_metric(
    factory: async_sessionmaker[AsyncSession], monitored_chat_id: UUID
) -> None:
    async with factory.begin() as session:
        job_id = await JobRepository(session).enqueue(_new_job(monitored_chat_id, 7))
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(created_at=datetime.now(UTC) - timedelta(seconds=10))
        )

    observed: list[float] = []

    async def successful_handler(job: ProcessingJob, session: AsyncSession) -> None:
        del job, session

    worker = QueueWorker(
        factory,
        "metrics-worker",
        successful_handler,
        queue_age_observer=observed.append,
    )
    assert await worker.run_once()
    assert observed and observed[0] >= 9

    async with factory.begin() as session:
        stale_id = await JobRepository(session).enqueue(_new_job(monitored_chat_id, 8))
        claimed = await JobRepository(session).claim("crashed-again")
        assert claimed is not None
        assert claimed.id == stale_id
        await session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == stale_id)
            .values(locked_at=datetime.now(UTC) - timedelta(minutes=10))
        )

    recovered = await recover_stale_jobs(factory, timedelta(minutes=5))
    assert recovered == [stale_id]


def test_postgresql_queue_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _database_url()
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")
    monitored_chat_id = asyncio.run(_prepare_chat(database_url))

    asyncio.run(_exercise_queue(database_url, monitored_chat_id))
