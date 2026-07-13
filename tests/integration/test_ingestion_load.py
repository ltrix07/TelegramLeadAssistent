"""Synthetic load coverage for the complete listener ingestion path."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from time import perf_counter
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from telethon import types  # type: ignore[import-untyped]

from alembic import command
from app.database.models import MonitoredChat, ProcessingJob
from app.database.queue import JobRepository
from app.domain.enums import MonitoredChatStatus, MonitoredChatType
from app.listener.active_chats import ActiveChatAllowList
from app.listener.events.incoming import TelethonMessageEvent
from app.listener.events.ingestion import IngestionHandler, database_message_persister

pytestmark = pytest.mark.integration

MESSAGE_COUNT = 10_000
DUPLICATE_COUNT = 250
CHAT_ID = -100123456789
BATCH_SIZE = 200
REQUIRED_MESSAGES_PER_SECOND = MESSAGE_COUNT / (24 * 60 * 60)


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for ingestion load tests")
    return value


def _event(message_id: int) -> TelethonMessageEvent:
    message = types.Message(
        id=message_id,
        peer_id=types.PeerChannel(abs(CHAT_ID)),
        from_id=types.PeerUser(7),
        message=f"Нужна помощь с настройкой заказа {message_id}",
        date=datetime(2026, 7, 12, tzinfo=UTC),
        out=False,
    )
    return cast(TelethonMessageEvent, SimpleNamespace(chat_id=CHAT_ID, message=message))


async def _run_load(database_url: str) -> tuple[float, float, int]:
    engine = create_async_engine(database_url, pool_size=20, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monitored_chat_id = uuid4()
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE monitored_chats CASCADE")
        async with factory.begin() as session:
            session.add(
                MonitoredChat(
                    id=monitored_chat_id,
                    telegram_chat_id=CHAT_ID,
                    title="Ingestion Load Test Chat",
                    chat_type=MonitoredChatType.SUPERGROUP,
                    status=MonitoredChatStatus.ACTIVE,
                    added_by_telegram_user_id=1,
                )
            )

        async def load_active_chats() -> frozenset[int]:
            return frozenset({CHAT_ID})

        allow_list = ActiveChatAllowList(load_active_chats)
        await allow_list.refresh()
        handler = IngestionHandler(allow_list, database_message_persister(factory))

        heartbeat_count = 0
        stop_heartbeat = asyncio.Event()

        async def heartbeat() -> None:
            nonlocal heartbeat_count
            while not stop_heartbeat.is_set():
                heartbeat_count += 1
                await asyncio.sleep(0)

        heartbeat_task = asyncio.create_task(heartbeat())
        started_at = perf_counter()
        message_ids = [*range(1, MESSAGE_COUNT + 1), *range(1, DUPLICATE_COUNT + 1)]
        for offset in range(0, len(message_ids), BATCH_SIZE):
            batch = message_ids[offset : offset + BATCH_SIZE]
            await asyncio.gather(*(handler(_event(message_id)) for message_id in batch))
        elapsed_seconds = perf_counter() - started_at
        stop_heartbeat.set()
        await heartbeat_task

        async with factory() as session:
            count = await session.scalar(select(func.count()).select_from(ProcessingJob))
            distinct_count = await session.scalar(
                select(func.count(func.distinct(ProcessingJob.telegram_message_id)))
            )
            minimum_id = await session.scalar(select(func.min(ProcessingJob.telegram_message_id)))
            maximum_id = await session.scalar(select(func.max(ProcessingJob.telegram_message_id)))
            oldest_job_age = await JobRepository(session).oldest_job_age_seconds()

        assert count == MESSAGE_COUNT
        assert distinct_count == MESSAGE_COUNT
        assert minimum_id == 1
        assert maximum_id == MESSAGE_COUNT
        return elapsed_seconds, oldest_job_age, heartbeat_count
    finally:
        await engine.dispose()


def test_ingestion_sustains_daily_volume_without_loss_or_event_loop_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")

    elapsed_seconds, oldest_job_age, heartbeat_count = asyncio.run(_run_load(database_url))
    throughput = MESSAGE_COUNT / elapsed_seconds

    assert throughput >= REQUIRED_MESSAGES_PER_SECOND
    assert oldest_job_age >= 0
    assert heartbeat_count > 1
    print(
        f"ingestion_load messages={MESSAGE_COUNT} duplicates={DUPLICATE_COUNT} "
        f"elapsed_seconds={elapsed_seconds:.3f} throughput_per_second={throughput:.1f} "
        f"oldest_job_age_seconds={oldest_job_age:.3f} heartbeats={heartbeat_count}"
    )
