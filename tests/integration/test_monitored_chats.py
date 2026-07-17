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

        access_lost = ChatVerificationResult(
            ChatVerificationOutcome.ACCESS_LOST,
            error_code="membership_or_access_lost",
        )
        async with factory.begin() as session:
            assert await MonitoredChatRepository(session).apply_verification(first.id, access_lost)
        async with factory() as session:
            first_failure = await session.get(MonitoredChat, first.id)
            assert first_failure is not None
            assert first_failure.status == MonitoredChatStatus.ACTIVE
            assert first_failure.consecutive_access_failures == 1
            assert first_failure.access_lost_at is None

        async with factory.begin() as session:
            assert await MonitoredChatRepository(session).apply_verification(first.id, access_lost)
        async with factory() as session:
            confirmed_loss = await session.get(MonitoredChat, first.id)
            assert confirmed_loss is not None
            assert confirmed_loss.status == MonitoredChatStatus.ACCESS_LOST
            assert confirmed_loss.consecutive_access_failures == 2
            assert confirmed_loss.access_lost_at is not None

        async with factory.begin() as session:
            assert await MonitoredChatRepository(session).apply_verification(
                first.id, ChatVerificationResult(ChatVerificationOutcome.ACTIVE)
            )
        async with factory() as session:
            restored = await session.get(MonitoredChat, first.id)
            assert restored is not None
            assert restored.status == MonitoredChatStatus.ACTIVE
            assert restored.consecutive_access_failures == 0
            assert restored.access_lost_at is None
            assert restored.last_verified_at is not None
            assert restored.next_verification_at > restored.last_verified_at

        async with factory.begin() as session:
            repository = MonitoredChatRepository(session)
            assert await repository.request_verification(selected.telegram_chat_id)
            due = await repository.list_due_verification()
            assert [chat.id for chat in due] == [first.id]
            assert await repository.defer_verification(first.id)
        async with factory() as session:
            deferred = await session.get(MonitoredChat, first.id)
            assert deferred is not None
            assert deferred.status == MonitoredChatStatus.ACTIVE
            assert deferred.consecutive_access_failures == 0

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
