"""Reliable delivery loop for PostgreSQL-backed operator notifications."""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Protocol

from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.notifications import (
    NotificationChainItem,
    NotificationContent,
    render_notification,
)
from app.database.models import BotNotification
from app.database.repositories.bot_notifications import BotNotificationRepository
from app.database.worker import RetryPolicy
from app.metrics import increment, observe_duration


class NotificationBot(Protocol):
    """Narrow Bot API boundary required by notification delivery."""

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: ParseMode,
        reply_markup: InlineKeyboardMarkup | None,
    ) -> object: ...


class BotNotificationWorker:
    """Claim, render and deliver one operator notification at a time."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bot: NotificationBot,
        operator_user_id: int,
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._bot = bot
        self._operator_user_id = operator_user_id
        self._retry_policy = retry_policy or RetryPolicy()

    async def run_once(self) -> bool:
        """Deliver at most one pending notification."""
        async with self._session_factory.begin() as session:
            repository = BotNotificationRepository(session)
            notification = await repository.claim(self._operator_user_id)
            if notification is None:
                return False

            sent_part_count = 0
            started_at = perf_counter()
            try:
                final_message_id: int | None = None
                for part in render_notification(_build_content(notification)):
                    message = await self._bot.send_message(
                        notification.bot_chat_id,
                        part.text,
                        parse_mode=part.parse_mode,
                        reply_markup=part.reply_markup,
                    )
                    final_message_id = _message_id(message)
                    sent_part_count += 1
                if final_message_id is None:
                    raise RuntimeError("Notification renderer returned no parts")
            except Exception as error:
                increment("notifications_failed_total", error_code=type(error).__name__[:100])
                error_code = type(error).__name__[:100]
                delay = self._retry_policy.delay_after_attempt(notification.attempt_count)
                if sent_part_count > 0 or delay is None:
                    await repository.fail(notification, error_code=error_code)
                else:
                    retry_at = await session.scalar(select(func.now() + delay))
                    if retry_at is None:
                        raise RuntimeError("Database did not return retry time") from error
                    await repository.retry(
                        notification,
                        error_code=error_code,
                        retry_at=retry_at,
                    )
            else:
                await repository.mark_sent(notification, final_message_id)
                increment("operator_notifications_total")
                observe_duration("notification_latency_ms", started_at)
        return True

    async def run_forever(self, poll_interval_seconds: float = 1.0) -> None:
        """Poll continuously while preserving graceful cancellation."""
        while True:
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(poll_interval_seconds)


def _build_content(notification: BotNotification) -> NotificationContent:
    question = notification.question
    chat = question.monitored_chat
    return NotificationContent(
        question_id=question.id,
        chat_title=chat.title,
        topic_title=question.topic_title,
        category=question.category,
        confidence=question.confidence,
        chat_username=chat.username,
        telegram_chat_id=question.telegram_chat_id,
        telegram_message_id=question.telegram_message_id,
        topic_id=question.topic_id,
        chain=tuple(
            NotificationChainItem(
                position=item.position,
                author_display_name=item.author_display_name,
                original_text=item.original_text,
                translated_text=item.translated_text,
                is_target=item.is_target,
            )
            for item in sorted(question.chain_messages, key=lambda value: value.position)
        ),
    )


def _message_id(message: object) -> int:
    value = getattr(message, "message_id", None)
    if not isinstance(value, int):
        raise TypeError("Bot API response lacks message_id")
    return value


__all__ = ["BotNotificationWorker", "NotificationBot"]
