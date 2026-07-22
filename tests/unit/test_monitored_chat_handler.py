"""Tests for monitored-chat callback failure handling."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram.types import CallbackQuery, User

from app.bot.handlers.chats import manage_chat
from app.database.repositories import MonitoredChatRepository


def _callback(chat_id: str) -> CallbackQuery:
    return CallbackQuery(
        id="callback-id",
        from_user=User(id=42, is_bot=False, first_name="Operator"),
        chat_instance="chat-instance",
        data=f"chat:remove:{chat_id}",
        date=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_manage_chat_acknowledges_database_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def transaction() -> object:
        yield MagicMock()

    session_factory = MagicMock()
    session_factory.begin.side_effect = transaction
    answer = AsyncMock()
    remove = AsyncMock(side_effect=RuntimeError("database unavailable"))
    log = MagicMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    monkeypatch.setattr(MonitoredChatRepository, "remove", remove)
    monkeypatch.setattr("app.bot.handlers.chats.log_event", log)

    await manage_chat(_callback(str(uuid4())), session_factory)

    answer.assert_awaited_once_with("Не удалось выполнить действие.", show_alert=True)
    log.assert_called_once()
