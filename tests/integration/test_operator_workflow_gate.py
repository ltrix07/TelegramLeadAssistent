"""Integration gate for operator authorization and bounded notifications."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot.application import create_dispatcher
from app.bot.notifications import (
    TELEGRAM_MESSAGE_LIMIT,
    NotificationChainItem,
    NotificationContent,
    render_notification,
)

pytestmark = pytest.mark.integration


class RecordingSession(BaseSession):
    """Network-free Bot API boundary that records outgoing methods."""

    def __init__(self) -> None:
        super().__init__()
        self.methods: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        del bot, timeout
        self.methods.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=len(self.methods),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        if isinstance(method, AnswerCallbackQuery):
            return True
        raise AssertionError(f"Unexpected Bot API method: {type(method).__name__}")

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        del url, headers, timeout, chunk_size, raise_for_status
        if False:
            yield b""


def _message_update(*, update_id: int, user_id: int) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Operator"),
            text="/start",
        ),
    )


@pytest.mark.asyncio
async def test_dispatcher_enforces_operator_authorization_without_network() -> None:
    session = RecordingSession()
    bot = Bot("123456:fake-token", session=session)
    dispatcher = create_dispatcher(operator_user_id=42)

    await dispatcher.feed_update(bot, _message_update(update_id=1, user_id=7))
    await dispatcher.feed_update(bot, _message_update(update_id=2, user_id=42))
    callback = CallbackQuery(
        id="unauthorized-callback",
        from_user=User(id=7, is_bot=False, first_name="Other"),
        chat_instance="private-chat",
        data="question:dismiss:12345678-1234-5678-1234-567812345678",
    )
    await dispatcher.feed_update(bot, Update(update_id=3, callback_query=callback))

    sent = [method for method in session.methods if isinstance(method, SendMessage)]
    callbacks = [method for method in session.methods if isinstance(method, AnswerCallbackQuery)]
    assert [method.text for method in sent] == ["Доступ запрещён.", "Главное меню"]
    assert len(callbacks) == 1
    assert callbacks[0].text == "Доступ запрещён."
    assert callbacks[0].show_alert is True


@pytest.mark.asyncio
async def test_long_notification_crosses_bot_api_boundary_in_bounded_parts() -> None:
    session = RecordingSession()
    bot = Bot("123456:fake-token", session=session)
    content = NotificationContent(
        question_id=UUID("12345678-1234-5678-1234-567812345678"),
        chat_title="Large community",
        topic_title="Support",
        category="product",
        confidence=Decimal("0.8750"),
        chat_username="large_community",
        telegram_chat_id=-1001234567890,
        telegram_message_id=42,
        topic_id=7,
        chain=(
            NotificationChainItem(
                position=0,
                author_display_name="Customer",
                original_text="<&> long line\n" * 1000,
                translated_text="длинный перевод " * 1000,
                is_target=True,
            ),
        ),
    )

    parts = render_notification(content)
    for part in parts:
        await bot.send_message(
            chat_id=42,
            text=part.text,
            parse_mode=part.parse_mode,
            reply_markup=part.reply_markup,
        )

    sent = cast(list[SendMessage], session.methods)
    assert len(sent) == len(parts)
    assert len(sent) > 2
    assert all(len(method.text) <= TELEGRAM_MESSAGE_LIMIT for method in sent)
    assert all(method.reply_markup is None for method in sent[:-1])
    assert sent[-1].reply_markup is not None
