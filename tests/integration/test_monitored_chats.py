"""Integration coverage for monitored chat persistence and state changes."""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.database.models import MonitoredChat
from app.database.repositories import MonitoredChatRepository, NewMonitoredChat
from app.domain.enums import MonitoredChatStatus, MonitoredChatType
from app.listener.mtproto import ChatVerificationOutcome, ChatVerificationResult

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for monitored chat integration tests")
    return value


async def _exercise_persistence(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    selected = NewMonitoredChat(
        telegram_chat_id=-100987654321,
        title="Test Group",
        username="test_group",
        added_by_telegram_user_id=42,
    )
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE monitored_chats CASCADE")

        async with factory.begin() as session:
            first, first_created = await MonitoredChatRepository(session).add_pending(selected)
        async with factory.begin() as session:
            duplicate, duplicate_created = await MonitoredChatRepository(session).add_pending(
                selected
            )
            count = await session.scalar(select(func.count()).select_from(MonitoredChat))

        assert first_created is True
        assert duplicate_created is False
        assert duplicate.id == first.id
        assert count == 1
        assert first.status == MonitoredChatStatus.PENDING_VERIFICATION

        async with factory() as session:
            active_ids = await MonitoredChatRepository(session).list_active_telegram_chat_ids()
        assert active_ids == frozenset()

        async with factory.begin() as session:
            assert await MonitoredChatRepository(session).pause(first.id) is True
        async with factory() as session:
            paused = await session.get(MonitoredChat, first.id)
            assert paused is not None
            assert paused.status == MonitoredChatStatus.DISABLED

        async with factory.begin() as session:
            assert await MonitoredChatRepository(session).resume(first.id) is True
        async with factory() as session:
            resumed = await session.get(MonitoredChat, first.id)
            assert resumed is not None
            assert resumed.status == MonitoredChatStatus.PENDING_VERIFICATION

        async with factory.begin() as session:
            applied = await MonitoredChatRepository(session).apply_verification(
                first.id,
                ChatVerificationResult(
                    ChatVerificationOutcome.ACTIVE,
                    is_supergroup=True,
                    is_forum=True,
                ),
            )
            assert applied is True
        async with factory() as session:
            verified = await session.get(MonitoredChat, first.id)
            assert verified is not None
            assert verified.status == MonitoredChatStatus.ACTIVE
            assert verified.chat_type == MonitoredChatType.FORUM_SUPERGROUP
            assert verified.last_verified_at is not None
            assert verified.last_error_code is None

        async with factory() as session:
            active_ids = await MonitoredChatRepository(session).list_active_telegram_chat_ids()
        assert active_ids == frozenset({selected.telegram_chat_id})

        async with factory.begin() as session:
            assert await MonitoredChatRepository(session).remove(first.id) is True
        async with factory() as session:
            assert await session.get(MonitoredChat, first.id) is None
    finally:
        await engine.dispose()


def test_monitored_chat_duplicate_pause_resume_and_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")

    asyncio.run(_exercise_persistence(database_url))
