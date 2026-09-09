"""PostgreSQL integration coverage for the service-aware container health check."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from alembic.config import Config
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.database.health import HeartbeatRepository
from app.database.models import ServiceHeartbeat
from scripts.healthcheck import check_heartbeat

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for health check integration tests")
    return value


async def _exercise(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(delete(ServiceHeartbeat))

        # A service that should publish a heartbeat but never started must fail, not pass.
        with pytest.raises(SystemExit, match="operator-bot"):
            await check_heartbeat(factory, "operator-bot")

        async with factory.begin() as session:
            await HeartbeatRepository(session).touch("operator-bot")

        # A heartbeat just written must pass using real database time, not client clock.
        await check_heartbeat(factory, "operator-bot")

        async with factory.begin() as session:
            await session.execute(
                update(ServiceHeartbeat)
                .where(ServiceHeartbeat.service == "operator-bot")
                .values(checked_at=datetime.now(UTC) - timedelta(seconds=200))
            )

        # A heartbeat older than the staleness threshold must fail.
        with pytest.raises(SystemExit, match="operator-bot"):
            await check_heartbeat(factory, "operator-bot")
    finally:
        await engine.dispose()


def test_check_heartbeat_against_real_database(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _database_url()
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise(database_url))
