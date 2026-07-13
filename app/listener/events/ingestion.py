"""Fast, idempotent persistence of eligible Telegram messages."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.queue import JobRepository, NewJob
from app.database.repositories import MonitoredChatRepository
from app.listener.active_chats import ActiveChatAllowList
from app.listener.events.incoming import (
    IncomingMessage,
    TelethonMessageEvent,
    extract_topic_id,
    map_telethon_event,
)
from app.listener.events.prefilter import prefilter_message
from app.logging import log_event

logger = logging.getLogger(__name__)
MessagePersister = Callable[[IncomingMessage], Awaitable[None]]


def database_message_persister(
    session_factory: async_sessionmaker[AsyncSession],
) -> MessagePersister:
    """Build the short transaction that rechecks activity and enqueues a message."""

    async def persist(message: IncomingMessage) -> None:
        if message.text is None:
            return
        async with session_factory.begin() as session:
            monitored_chat_id = await MonitoredChatRepository(
                session
            ).get_active_id_by_telegram_chat_id(message.telegram_chat_id)
            if monitored_chat_id is None:
                return
            await JobRepository(session).enqueue(
                NewJob(
                    monitored_chat_id=monitored_chat_id,
                    telegram_chat_id=message.telegram_chat_id,
                    telegram_message_id=message.telegram_message_id,
                    topic_id=message.topic_id,
                    sender_telegram_id=message.sender_telegram_id,
                    sender_display_name=message.sender_display_name,
                    message_text=message.text,
                    telegram_created_at=message.telegram_created_at,
                )
            )

    return persist


class IngestionHandler:
    """Normalize, filter, and enqueue a Telegram update without external API calls."""

    def __init__(
        self,
        allow_list: ActiveChatAllowList,
        persist: MessagePersister,
    ) -> None:
        self._allow_list = allow_list
        self._persist = persist

    async def __call__(self, event: TelethonMessageEvent) -> None:
        """Persist one eligible update, swallowing DB failures at the event boundary."""
        if event.chat_id is None or event.chat_id not in self._allow_list:
            return

        message = map_telethon_event(event, topic_id=extract_topic_id(event.message))
        result = prefilter_message(message)
        if not result.should_classify or message.text is None:
            return

        try:
            await self._persist(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            log_event(
                logger,
                logging.ERROR,
                "message_ingestion_database_failed",
                telegram_chat_id=message.telegram_chat_id,
                telegram_message_id=message.telegram_message_id,
            )
