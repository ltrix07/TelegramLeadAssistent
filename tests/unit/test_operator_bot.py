"""Tests for the private operator bot skeleton."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.application import create_dispatcher, run_bot
from app.bot.keyboards.chats import CHAT_PICKER_REQUEST_ID, build_chat_picker_keyboard
from app.bot.keyboards.main_menu import MAIN_MENU_BUTTONS, build_main_menu_keyboard
from app.bot.middleware.authorization import OperatorAuthorizationMiddleware


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

    monkeypatch.setattr("app.bot.application.create_dispatcher", lambda *_: FakeDispatcher())
    monkeypatch.setattr("app.bot.application.Bot", FakeBot)
    monkeypatch.setattr("app.bot.application.BotNotificationWorker", FakeNotificationWorker)
    monkeypatch.setattr("app.bot.application.OperationalAlertWorker", FakeAlertWorker)

    await run_bot("123456:fake-token", 42, AsyncMock())

    start_polling.assert_awaited_once()
    assert worker_started.is_set()
    assert alert_worker_started.is_set()
