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
from app.listener.events.ingestion import IngestionHandler, PersistOutcome


def _event(*, chat_id: int = -1001, message_id: int = 42) -> TelethonMessageEvent:
    message = types.Message(
        id=message_id,
        peer_id=types.PeerChannel(abs(chat_id)),
        from_id=types.PeerUser(7),
        message="Нужен разработчик Telegram-бота",
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
async def test_enqueued_message_is_passed_to_persistence_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted: list[IncomingMessage] = []
    metrics: list[str] = []

    async def persist(message: IncomingMessage) -> PersistOutcome:
        persisted.append(message)
        return PersistOutcome.ENQUEUED

    monkeypatch.setattr(
        "app.listener.events.ingestion.increment", lambda name, **_: metrics.append(name)
    )

    handler = IngestionHandler(await _allow_list(), persist)
    await asyncio.wait_for(handler(_event()), timeout=0.1)

    assert len(persisted) == 1
    assert persisted[0].telegram_message_id == 42
    assert metrics == ["telegram_messages_received_total", "processing_jobs_created_total"]


@pytest.mark.asyncio
async def test_duplicate_message_increments_prevented_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics: list[str] = []

    async def persist(_: IncomingMessage) -> PersistOutcome:
        return PersistOutcome.DUPLICATE_SUPPRESSED

    monkeypatch.setattr(
        "app.listener.events.ingestion.increment", lambda name, **_: metrics.append(name)
    )

    await IngestionHandler(await _allow_list(), persist)(_event())

    assert metrics == ["telegram_messages_received_total", "duplicate_messages_prevented_total"]


@pytest.mark.asyncio
async def test_inactive_chat_is_ignored_without_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics: list[str] = []

    async def persist(message: IncomingMessage) -> PersistOutcome:
        raise AssertionError(f"Unexpected persistence for {message.telegram_chat_id}")

    monkeypatch.setattr(
        "app.listener.events.ingestion.increment", lambda name, **_: metrics.append(name)
    )
    await IngestionHandler(await _allow_list(), persist)(_event(chat_id=-1002))

    assert metrics == []


@pytest.mark.asyncio
async def test_database_failure_is_logged_and_not_propagated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fail(_: IncomingMessage) -> PersistOutcome:
        raise RuntimeError("database unavailable")

    handler = IngestionHandler(await _allow_list(), fail)
    await handler(_event())

    assert "message_ingestion_database_failed" in caplog.text
