"""Integration coverage for durable operator FSM sessions."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from aiogram.fsm.storage.base import StorageKey
from alembic.config import Config
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.bot.storage import PostgresOperatorStorage
from app.database.models import DetectedQuestion, MonitoredChat, OperatorSession
from app.database.repositories.operator_sessions import (
    ActiveDraftConflictError,
    OperatorSessionRepository,
)
from app.domain.enums import MonitoredChatStatus, MonitoredChatType

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for operator session integration tests")
    return value


async def _exercise_operator_sessions(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    key = StorageKey(bot_id=1, chat_id=42, user_id=42)
    try:
        async with factory.begin() as session:
            await session.execute(delete(OperatorSession))
            chat = MonitoredChat(
                telegram_chat_id=-1001,
                title="Test group",
                chat_type=MonitoredChatType.SUPERGROUP,
                status=MonitoredChatStatus.ACTIVE,
                added_by_telegram_user_id=42,
            )
            session.add(chat)
            await session.flush()
            first = DetectedQuestion(
                monitored_chat_id=chat.id,
                telegram_chat_id=-1001,
                telegram_message_id=10,
                telegram_created_at=datetime.now(UTC),
                original_text="First",
                category="product",
            )
            second = DetectedQuestion(
                monitored_chat_id=chat.id,
                telegram_chat_id=-1001,
                telegram_message_id=11,
                telegram_created_at=datetime.now(UTC),
                original_text="Second",
                category="product",
            )
            session.add_all((first, second))
            await session.flush()
            first_id, second_id = first.id, second.id

        storage_before_restart = PostgresOperatorStorage(factory)
        await storage_before_restart.set_state(key, "ReplyFlow:waiting_for_draft")
        await storage_before_restart.set_data(key, {"question_id": str(first_id)})

        storage_after_restart = PostgresOperatorStorage(factory)
        assert await storage_after_restart.get_state(key) == "ReplyFlow:waiting_for_draft"
        assert await storage_after_restart.get_data(key) == {"question_id": str(first_id)}

        async with factory.begin() as session:
            repository = OperatorSessionRepository(session)
            await repository.open_question(42, first_id)

        with pytest.raises(ActiveDraftConflictError):
            async with factory.begin() as session:
                await OperatorSessionRepository(session).open_question(42, second_id)

        async with factory.begin() as session:
            await OperatorSessionRepository(session).open_question(42, second_id, replace=True)

        async with factory() as session:
            row = await session.get(OperatorSession, 42)
            assert row is not None
            assert row.active_question_id == second_id
    finally:
        await engine.dispose()


def test_operator_fsm_survives_restart_and_requires_explicit_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")

    asyncio.run(_exercise_operator_sessions(database_url))
