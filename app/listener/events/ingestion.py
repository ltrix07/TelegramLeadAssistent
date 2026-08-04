"""Fast, idempotent persistence of eligible Telegram messages."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.queue import JobRepository, NewJob
from app.database.repositories import MonitoredChatRepository
from app.listener.active_chats import ActiveChatAllowList
from app.listener.events.fingerprint import message_fingerprint
from app.listener.events.incoming import (
    IncomingMessage,
    TelethonMessageEvent,
    extract_topic_id,
    map_telethon_event,
)
from app.listener.events.prefilter import prefilter_message
from app.logging import log_event
from app.metrics import increment

logger = logging.getLogger(__name__)


class PersistOutcome(StrEnum):
    """Result of the short ingestion persistence transaction."""

    ENQUEUED = "enqueued"
    DUPLICATE_SUPPRESSED = "duplicate_suppressed"
    INACTIVE_CHAT = "inactive_chat"


MessagePersister = Callable[[IncomingMessage], Awaitable[PersistOutcome]]


def database_message_persister(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dedup_window: timedelta,
) -> MessagePersister:
    """Build the short transaction that rechecks activity and enqueues a message."""

    async def persist(message: IncomingMessage) -> PersistOutcome:
        if message.text is None:
            return PersistOutcome.INACTIVE_CHAT
        async with session_factory.begin() as session:
            monitored_chat_id = await MonitoredChatRepository(
                session
            ).get_active_id_by_telegram_chat_id(message.telegram_chat_id)
            if monitored_chat_id is None:
                return PersistOutcome.INACTIVE_CHAT
            fingerprint = message_fingerprint(message.text)
            admitted = await JobRepository(session).register_fingerprint(
                message.telegram_chat_id, fingerprint, dedup_window
            )
            if not admitted:
                return PersistOutcome.DUPLICATE_SUPPRESSED
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
            return PersistOutcome.ENQUEUED

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
        increment("telegram_messages_received_total")

        message = map_telethon_event(event, topic_id=extract_topic_id(event.message))
        result = prefilter_message(message)
        if not result.should_classify or message.text is None:
            increment("messages_filtered_locally_total", reason_code=result.reason_code.value)
            return

        try:
            outcome = await self._persist(message)
            if outcome is PersistOutcome.ENQUEUED:
                increment("processing_jobs_created_total")
            elif outcome is PersistOutcome.DUPLICATE_SUPPRESSED:
                increment("duplicate_messages_prevented_total")
        except asyncio.CancelledError:
            raise
        except Exception:
            increment("processing_jobs_failed_total", error_code="DATABASE_ERROR")
            log_event(
                logger,
                logging.ERROR,
                "message_ingestion_database_failed",
                telegram_chat_id=message.telegram_chat_id,
                telegram_message_id=message.telegram_message_id,
            )
