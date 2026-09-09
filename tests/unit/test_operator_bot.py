"""Tests for the private operator bot skeleton."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.application import create_dispatcher, run_bot
from app.bot.delivery import BotNotificationWorker
from app.bot.keyboards.chats import CHAT_PICKER_REQUEST_ID, build_chat_picker_keyboard
from app.bot.keyboards.main_menu import MAIN_MENU_BUTTONS, build_main_menu_keyboard
from app.bot.middleware.authorization import OperatorAuthorizationMiddleware
from app.config import AppSettings


def make_message(user_id: int) -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Operator"),
        text="/start",
    )


def make_callback(user_id: int) -> CallbackQuery:
    return CallbackQuery(
        id="callback-id",
        from_user=User(id=user_id, is_bot=False, first_name="Operator"),
        chat_instance="chat-instance",
        data="action",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("event_factory", [make_message, make_callback])
async def test_authorized_messages_and_callbacks_reach_handlers(
    event_factory: Callable[[int], Message | CallbackQuery],
) -> None:
    middleware = OperatorAuthorizationMiddleware(operator_user_id=42)
    handler = AsyncMock(return_value="handled")
    event = event_factory(42)

    result = await middleware(handler, event, {"event_from_user": event.from_user})

    assert result == "handled"
    handler.assert_awaited_once_with(event, {"event_from_user": event.from_user})


@pytest.mark.asyncio
async def test_unauthorized_message_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = OperatorAuthorizationMiddleware(operator_user_id=42)
    handler = AsyncMock()
    message = make_message(7)
    answer = AsyncMock()
    monkeypatch.setattr(Message, "answer", answer)

    result = await middleware(handler, message, {"event_from_user": message.from_user})

    assert result is None
    handler.assert_not_awaited()
    answer.assert_awaited_once_with("Доступ запрещён.")


@pytest.mark.asyncio
async def test_unauthorized_callback_is_denied_and_acknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware = OperatorAuthorizationMiddleware(operator_user_id=42)
    handler = AsyncMock()
    callback = make_callback(7)
    answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)

    result = await middleware(handler, callback, {"event_from_user": callback.from_user})

    assert result is None
    handler.assert_not_awaited()
    answer.assert_awaited_once_with("Доступ запрещён.", show_alert=True)


def test_dispatcher_registers_menu_and_authorization_middleware() -> None:
    dispatcher = create_dispatcher(operator_user_id=42, session_factory=MagicMock())

    assert dispatcher.resolve_used_update_types() == ["callback_query", "message"]
    assert len(dispatcher.message.outer_middleware) == 1
    assert len(dispatcher.callback_query.outer_middleware) == 1
    assert dispatcher.storage.__class__.__name__ == "PostgresOperatorStorage"


def test_main_menu_contains_specified_sections() -> None:
    keyboard = build_main_menu_keyboard()

    assert tuple(button.text for row in keyboard.keyboard for button in row) == MAIN_MENU_BUTTONS


def test_chat_picker_accepts_groups_but_not_channels() -> None:
    keyboard = build_chat_picker_keyboard()
    request = keyboard.keyboard[0][0].request_chat

    assert request is not None
    assert request.request_id == CHAT_PICKER_REQUEST_ID
    assert request.chat_is_channel is False
    assert request.request_title is True
    assert request.request_username is True


@pytest.mark.asyncio
async def test_run_bot_starts_long_polling_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    start_polling = AsyncMock()
    worker_started = asyncio.Event()
    alert_worker_started = asyncio.Event()
    heartbeat_started = asyncio.Event()
    heartbeat_calls: list[tuple[object, ...]] = []

    class FakeDispatcher:
        def resolve_used_update_types(self) -> list[str]:
            return ["message"]

        async def start_polling(self, *args: object, **kwargs: object) -> None:
            await asyncio.sleep(0)
            await start_polling(*args, **kwargs)

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token

        async def __aenter__(self) -> FakeBot:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeNotificationWorker:
        def __init__(self, *args: object) -> None:
            pass

        async def run_forever(self) -> None:
            worker_started.set()
            await asyncio.Event().wait()

    class FakeAlertWorker:
        def __init__(self, *args: object) -> None:
            pass

        async def run_forever(self) -> None:
            alert_worker_started.set()
            await asyncio.Event().wait()

    async def fake_run_heartbeat(*args: object, **kwargs: object) -> None:
        heartbeat_calls.append(args)
        heartbeat_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.bot.application.create_dispatcher", lambda *_: FakeDispatcher())
    monkeypatch.setattr("app.bot.application.Bot", FakeBot)
    monkeypatch.setattr("app.bot.application.BotNotificationWorker", FakeNotificationWorker)
    monkeypatch.setattr("app.bot.application.OperationalAlertWorker", FakeAlertWorker)
    monkeypatch.setattr("app.bot.application.run_heartbeat", fake_run_heartbeat)

    await run_bot("123456:fake-token", 42, AsyncMock())

    start_polling.assert_awaited_once()
    assert worker_started.is_set()
    assert alert_worker_started.is_set()
    assert heartbeat_started.is_set()
    assert heartbeat_calls[0][1] == "operator-bot"


@pytest.mark.asyncio
async def test_notifications_flag_prevents_notification_worker_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notification_worker_created = False

    class FakeDispatcher:
        def resolve_used_update_types(self) -> list[str]:
            return []

        async def start_polling(self, *_args: object, **_kwargs: object) -> None:
            return None

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token

        async def __aenter__(self) -> FakeBot:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class ForbiddenNotificationWorker:
        def __init__(self, *_args: object) -> None:
            nonlocal notification_worker_created
            notification_worker_created = True

    class FakeAlertWorker:
        def __init__(self, *_args: object) -> None:
            pass

        async def run_forever(self) -> None:
            await asyncio.Event().wait()

    async def fake_run_heartbeat(*_args: object, **_kwargs: object) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr("app.bot.application.create_dispatcher", lambda *_: FakeDispatcher())
    monkeypatch.setattr("app.bot.application.Bot", FakeBot)
    monkeypatch.setattr("app.bot.application.BotNotificationWorker", ForbiddenNotificationWorker)
    monkeypatch.setattr("app.bot.application.OperationalAlertWorker", FakeAlertWorker)
    monkeypatch.setattr("app.bot.application.run_heartbeat", fake_run_heartbeat)

    await run_bot(
        "123456:fake-token",
        42,
        AsyncMock(),
        AppSettings(notifications_enabled=False),
    )

    assert notification_worker_created is False


@pytest.mark.asyncio
async def test_background_worker_failure_stops_polling_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead background worker must kill run_bot instead of leaving polling alone."""
    polling_cancelled = asyncio.Event()

    class FakeDispatcher:
        def resolve_used_update_types(self) -> list[str]:
            return ["message"]

        async def start_polling(self, *args: object, **kwargs: object) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                polling_cancelled.set()
                raise

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token

        async def __aenter__(self) -> FakeBot:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    class FailingNotificationWorker:
        def __init__(self, *args: object) -> None:
            pass

        async def run_forever(self) -> None:
            raise ConnectionError("db connection dropped")

    class FakeAlertWorker:
        def __init__(self, *args: object) -> None:
            pass

        async def run_forever(self) -> None:
            await asyncio.Event().wait()

    async def fake_run_heartbeat(*args: object, **kwargs: object) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr("app.bot.application.create_dispatcher", lambda *_: FakeDispatcher())
    monkeypatch.setattr("app.bot.application.Bot", FakeBot)
    monkeypatch.setattr("app.bot.application.BotNotificationWorker", FailingNotificationWorker)
    monkeypatch.setattr("app.bot.application.OperationalAlertWorker", FakeAlertWorker)
    monkeypatch.setattr("app.bot.application.run_heartbeat", fake_run_heartbeat)

    with pytest.raises(ConnectionError, match="db connection dropped"):
        await asyncio.wait_for(run_bot("123456:fake-token", 42, AsyncMock()), timeout=2.0)

    assert polling_cancelled.is_set()


@pytest.mark.asyncio
async def test_shutdown_cancellation_propagates_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling run_bot for a graceful shutdown must not surface anything but CancelledError."""
    polling_started = asyncio.Event()
    notification_started = asyncio.Event()
    alert_started = asyncio.Event()
    heartbeat_started = asyncio.Event()
    cancelled_cleanly: list[str] = []

    class FakeDispatcher:
        def resolve_used_update_types(self) -> list[str]:
            return ["message"]

        async def start_polling(self, *args: object, **kwargs: object) -> None:
            polling_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled_cleanly.append("polling")
                raise

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token

        async def __aenter__(self) -> FakeBot:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeNotificationWorker:
        def __init__(self, *args: object) -> None:
            pass

        async def run_forever(self) -> None:
            notification_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled_cleanly.append("notification")
                raise

    class FakeAlertWorker:
        def __init__(self, *args: object) -> None:
            pass

        async def run_forever(self) -> None:
            alert_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled_cleanly.append("alert")
                raise

    async def fake_run_heartbeat(*args: object, **kwargs: object) -> None:
        heartbeat_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled_cleanly.append("heartbeat")
            raise

    monkeypatch.setattr("app.bot.application.create_dispatcher", lambda *_: FakeDispatcher())
    monkeypatch.setattr("app.bot.application.Bot", FakeBot)
    monkeypatch.setattr("app.bot.application.BotNotificationWorker", FakeNotificationWorker)
    monkeypatch.setattr("app.bot.application.OperationalAlertWorker", FakeAlertWorker)
    monkeypatch.setattr("app.bot.application.run_heartbeat", fake_run_heartbeat)

    run_bot_task = asyncio.create_task(run_bot("123456:fake-token", 42, AsyncMock()))
    await asyncio.wait_for(polling_started.wait(), timeout=2.0)
    await asyncio.wait_for(notification_started.wait(), timeout=2.0)
    await asyncio.wait_for(alert_started.wait(), timeout=2.0)
    await asyncio.wait_for(heartbeat_started.wait(), timeout=2.0)

    run_bot_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(run_bot_task, timeout=2.0)

    assert set(cancelled_cleanly) == {"polling", "notification", "alert", "heartbeat"}


@pytest.mark.asyncio
async def test_notification_worker_claim_failure_escapes_run_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a dropped DB connection during claim() must not be swallowed silently."""

    @asynccontextmanager
    async def transaction() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    session_factory = MagicMock()
    session_factory.begin.side_effect = transaction

    class FailingRepository:
        def __init__(self, session: object) -> None:
            pass

        async def claim(self, operator_user_id: int) -> None:
            raise ConnectionError("connection reset by peer")

    monkeypatch.setattr("app.bot.delivery.BotNotificationRepository", FailingRepository)

    worker = BotNotificationWorker(session_factory, AsyncMock(), 42)

    with pytest.raises(ConnectionError, match="connection reset by peer"):
        await asyncio.wait_for(worker.run_forever(), timeout=2.0)


@pytest.mark.asyncio
async def test_heartbeat_worker_failure_stops_polling_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead operator-bot heartbeat loop must kill run_bot, same as any other worker (task A)."""
    polling_cancelled = asyncio.Event()

    class FakeDispatcher:
        def resolve_used_update_types(self) -> list[str]:
            return ["message"]

        async def start_polling(self, *args: object, **kwargs: object) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                polling_cancelled.set()
                raise

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token

        async def __aenter__(self) -> FakeBot:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeNotificationWorker:
        def __init__(self, *args: object) -> None:
            pass

        async def run_forever(self) -> None:
            await asyncio.Event().wait()

    class FakeAlertWorker:
        def __init__(self, *args: object) -> None:
            pass

        async def run_forever(self) -> None:
            await asyncio.Event().wait()

    async def failing_run_heartbeat(*args: object, **kwargs: object) -> None:
        raise ConnectionError("heartbeat write failed")

    monkeypatch.setattr("app.bot.application.create_dispatcher", lambda *_: FakeDispatcher())
    monkeypatch.setattr("app.bot.application.Bot", FakeBot)
    monkeypatch.setattr("app.bot.application.BotNotificationWorker", FakeNotificationWorker)
    monkeypatch.setattr("app.bot.application.OperationalAlertWorker", FakeAlertWorker)
    monkeypatch.setattr("app.bot.application.run_heartbeat", failing_run_heartbeat)

    with pytest.raises(ConnectionError, match="heartbeat write failed"):
        await asyncio.wait_for(run_bot("123456:fake-token", 42, AsyncMock()), timeout=2.0)

    assert polling_cancelled.is_set()
