"""Fail-closed in-memory allow-list of active Telegram chats."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.repositories import MonitoredChatRepository
from app.logging import log_event

logger = logging.getLogger(__name__)

ActiveChatLoader = Callable[[], Awaitable[frozenset[int]]]


def database_active_chat_loader(
    session_factory: async_sessionmaker[AsyncSession],
) -> ActiveChatLoader:
    """Build a loader whose query and session lifetime are kept together."""

    async def load() -> frozenset[int]:
        async with session_factory() as session:
            return await MonitoredChatRepository(session).list_active_telegram_chat_ids()

    return load


class ActiveChatAllowList:
    """Atomically replace active chat IDs only after a successful refresh."""

    def __init__(self, loader: ActiveChatLoader) -> None:
        self._loader = loader
        self._chat_ids: frozenset[int] = frozenset()

    def __contains__(self, telegram_chat_id: int) -> bool:
        """Check one chat against the last safe snapshot without I/O."""
        return telegram_chat_id in self._chat_ids

    @property
    def chat_ids(self) -> frozenset[int]:
        """Expose the immutable current snapshot for diagnostics and tests."""
        return self._chat_ids

    async def refresh(self) -> bool:
        """Load and atomically publish a new snapshot, retaining it on failure."""
        try:
            chat_ids = await self._loader()
        except asyncio.CancelledError:
            raise
        except Exception:
            log_event(logger, logging.WARNING, "active_chat_allow_list_refresh_failed")
            return False
        self._chat_ids = frozenset(chat_ids)
        log_event(
            logger,
            logging.INFO,
            "active_chat_allow_list_refreshed",
            active_chat_count=len(chat_ids),
        )
        return True


async def run_active_chat_allow_list(
    allow_list: ActiveChatAllowList,
    stop_event: asyncio.Event,
    *,
    interval_seconds: float = 60.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Refresh at startup and periodically until listener shutdown."""
    while not stop_event.is_set():
        await allow_list.refresh()
        await sleep(interval_seconds)
