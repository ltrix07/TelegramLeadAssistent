"""Tests for the fast Telegram NewMessage ingestion boundary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from telethon import types  # type: ignore[import-untyped]

from app.listener.active_chats import ActiveChatAllowList
from app.listener.events.incoming import IncomingMessage, TelethonMessageEvent
from app.listener.events.ingestion import IngestionHandler


def _event(*, chat_id: int = -1001, message_id: int = 42) -> TelethonMessageEvent:
    message = types.Message(
        id=message_id,
        peer_id=types.PeerChannel(abs(chat_id)),
        from_id=types.PeerUser(7),
        message="Нужна помощь с настройкой",
        date=datetime(2026, 7, 12, tzinfo=UTC),
        out=False,
    )
    return cast(TelethonMessageEvent, SimpleNamespace(chat_id=chat_id, message=message))


async def _allow_list() -> ActiveChatAllowList:
    async def load() -> frozenset[int]:
        return frozenset({-1001})

    result = ActiveChatAllowList(load)
    await result.refresh()
    return result


@pytest.mark.asyncio
async def test_eligible_message_is_passed_to_persistence_once() -> None:
    persisted: list[IncomingMessage] = []

    async def persist(message: IncomingMessage) -> None:
        persisted.append(message)

    handler = IngestionHandler(await _allow_list(), persist)
    await asyncio.wait_for(handler(_event()), timeout=0.1)

    assert len(persisted) == 1
    assert persisted[0].telegram_message_id == 42


@pytest.mark.asyncio
async def test_inactive_chat_is_ignored_without_persistence() -> None:
    async def persist(message: IncomingMessage) -> None:
        raise AssertionError(f"Unexpected persistence for {message.telegram_chat_id}")

    await IngestionHandler(await _allow_list(), persist)(_event(chat_id=-1002))


@pytest.mark.asyncio
async def test_database_failure_is_logged_and_not_propagated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fail(_: IncomingMessage) -> None:
        raise RuntimeError("database unavailable")

    handler = IngestionHandler(await _allow_list(), fail)
    await handler(_event())

    assert "message_ingestion_database_failed" in caplog.text
