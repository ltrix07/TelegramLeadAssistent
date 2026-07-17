"""PostgreSQL integration coverage for health and status aggregation."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from alembic.config import Config
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.bot.status import StatusRepository
from app.database.health import HeartbeatRepository
from app.database.models import ApiUsageDaily, MonitoredChat, ServiceHeartbeat
from app.database.queue import JobRepository, NewJob
from app.domain.enums import MonitoredChatStatus, MonitoredChatType

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for status integration tests")
    return value


async def _exercise(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE monitored_chats CASCADE")
            await connection.execute(delete(ApiUsageDaily))
            await connection.execute(delete(ServiceHeartbeat))
        async with factory.begin() as session:
            chat = MonitoredChat(
                telegram_chat_id=-100903,
                title="Status test",
                chat_type=MonitoredChatType.SUPERGROUP,
                status=MonitoredChatStatus.ACTIVE,
                added_by_telegram_user_id=1,
            )
            session.add(chat)
            await session.flush()
            await JobRepository(session).enqueue(
                NewJob(chat.id, chat.telegram_chat_id, 7, "sensitive body", datetime.now(UTC))
            )
            session.add(
                ApiUsageDaily(
                    usage_date=date.today(),
                    model="test-model",
                    request_count=1,
                    input_tokens=1,
                    output_tokens=1,
                    estimated_cost_usd=Decimal("1.25"),
                )
            )
            heartbeats = HeartbeatRepository(session)
            await heartbeats.touch("telegram-listener")
            await heartbeats.touch("classification-worker")

        async with factory() as session:
            snapshot = await StatusRepository(session).collect(translator_healthy=False)
        assert snapshot.mtproto_healthy is True
        assert snapshot.classifier_healthy is True
        assert snapshot.translator_healthy is False
        assert snapshot.active_chats == 1
        assert snapshot.pending_classification_jobs == 1
        assert snapshot.api_cost_month_usd == Decimal("1.250000")

        async with factory.begin() as session:
            await session.execute(
                update(ServiceHeartbeat).values(checked_at=datetime.now(UTC) - timedelta(minutes=5))
            )
        async with factory() as session:
            stale = await StatusRepository(session).collect(translator_healthy=True)
        assert stale.mtproto_healthy is False
        assert stale.classifier_healthy is False
    finally:
        await engine.dispose()


def test_status_snapshot_and_stale_heartbeats(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _database_url()
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise(database_url))
