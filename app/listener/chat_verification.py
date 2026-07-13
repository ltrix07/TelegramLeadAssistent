"""Periodic MTProto verification for operator-selected chats."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.repositories import MonitoredChatRepository
from app.listener.mtproto import ChatVerificationTransientError, MTProtoListenerClient
from app.logging import log_event

logger = logging.getLogger(__name__)


async def verify_pending_chats_once(
    client: MTProtoListenerClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Verify one bounded pending batch, preserving state on transient failures."""
    async with session_factory() as session:
        pending = await MonitoredChatRepository(session).list_pending_verification()

    for chat in pending:
        try:
            result = await client.verify_chat(chat.telegram_chat_id)
        except ChatVerificationTransientError:
            log_event(logger, logging.WARNING, "chat_verification_deferred", chat_id=str(chat.id))
            continue
        async with session_factory.begin() as session:
            await MonitoredChatRepository(session).apply_verification(chat.id, result)
        log_event(
            logger,
            logging.INFO,
            "chat_verification_completed",
            chat_id=str(chat.id),
            outcome=result.outcome.value,
        )


async def run_chat_verifier(
    client: MTProtoListenerClient,
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event,
    *,
    interval_seconds: float = 5.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Poll pending chats until listener shutdown or connection loss."""
    while not stop_event.is_set():
        await verify_pending_chats_once(client, session_factory)
        await sleep(interval_seconds)
