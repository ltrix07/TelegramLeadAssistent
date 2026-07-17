"""Tests for listener lifecycle and exclusive session ownership."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from app.listener.__main__ import _outbound_workers, _register_ingestion_handler
from app.listener.lifecycle import (
    ListenerAlreadyRunning,
    SessionFileLock,
    SessionNotAuthorized,
    run_listener,
)
from app.listener.mtproto import ChatVerificationResult


class FakeListenerClient:
    def __init__(self, stop_event: asyncio.Event, *, authorized: bool = True) -> None:
        self.stop_event = stop_event
        self.authorized = authorized
        self.connect_calls = 0
        self.run_calls = 0
        self.disconnect_calls = 0

    async def connect(self) -> None:
        self.connect_calls += 1

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def verify_chat(self, telegram_chat_id: int) -> ChatVerificationResult:
        raise AssertionError("Chat verification is not expected in lifecycle tests")

    def add_new_message_handler(self, handler: Callable[[Any], Awaitable[None]]) -> None:
        raise AssertionError("Handler registration is not expected in lifecycle tests")

    async def run_until_disconnected(self) -> None:
        self.run_calls += 1
        if self.run_calls == 1:
            return
        self.stop_event.set()
        await asyncio.sleep(0)

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


def test_second_session_owner_fails_and_lock_can_be_reacquired(tmp_path: Path) -> None:
    session_path = tmp_path / "work.session"

    with SessionFileLock(session_path):
        with pytest.raises(ListenerAlreadyRunning, match="already owns"):
            with SessionFileLock(session_path):
                pass

    with SessionFileLock(session_path):
        assert (tmp_path / "work.session.lock").stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_listener_reconnects_after_brief_disconnect() -> None:
    stop_event = asyncio.Event()
    client = FakeListenerClient(stop_event)

    await run_listener(client, stop_event, reconnect_delay_seconds=0)

    assert client.connect_calls == 2
    assert client.run_calls == 2
    assert client.disconnect_calls == 1


@pytest.mark.asyncio
async def test_graceful_stop_disconnects_blocked_client() -> None:
    stop_event = asyncio.Event()

    class BlockingClient(FakeListenerClient):
        async def run_until_disconnected(self) -> None:
            self.run_calls += 1
            await asyncio.Future()

    client = BlockingClient(stop_event)
    listener = asyncio.create_task(run_listener(client, stop_event))
    while client.run_calls == 0:
        await asyncio.sleep(0)

    stop_event.set()
    await listener

    assert client.disconnect_calls == 1


@pytest.mark.asyncio
async def test_unauthorized_session_fails_without_interactive_login() -> None:
    stop_event = asyncio.Event()
    client = FakeListenerClient(stop_event, authorized=False)

    with pytest.raises(SessionNotAuthorized, match="not authorized"):
        await run_listener(client, stop_event)

    assert client.run_calls == 0
    assert client.disconnect_calls == 1


def test_outbound_disabled_keeps_ingestion_and_builds_no_command_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handlers: list[object] = []

    class RegistrationClient:
        def add_new_message_handler(self, handler: object) -> None:
            handlers.append(handler)

    monkeypatch.setattr(
        "app.listener.__main__.database_message_persister", lambda _factory: object()
    )
    client = RegistrationClient()
    session_factory = object()
    allow_list = object()

    _register_ingestion_handler(
        client,  # type: ignore[arg-type]
        allow_list,  # type: ignore[arg-type]
        session_factory,  # type: ignore[arg-type]
        monitoring_enabled=True,
    )
    workers = _outbound_workers(
        client,  # type: ignore[arg-type]
        session_factory,  # type: ignore[arg-type]
        outbound_replies_enabled=False,
    )

    assert len(handlers) == 1
    assert workers == ()


def test_monitoring_disabled_registers_no_ingestion_handler() -> None:
    class RegistrationClient:
        def add_new_message_handler(self, _handler: object) -> None:
            raise AssertionError("Monitoring-disabled listener must not ingest messages")

    _register_ingestion_handler(
        RegistrationClient(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        monitoring_enabled=False,
    )
