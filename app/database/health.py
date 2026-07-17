"""Database-backed component liveness signals."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ServiceHeartbeat


class HeartbeatRepository:
    """Record service liveness without storing request or message data."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def touch(self, service: str) -> None:
        """Upsert one service heartbeat using database time."""
        await self._session.execute(
            insert(ServiceHeartbeat)
            .values(service=service, checked_at=func.now())
            .on_conflict_do_update(
                index_elements=[ServiceHeartbeat.service],
                set_={"checked_at": func.now()},
            )
        )


async def run_heartbeat(
    session_factory: async_sessionmaker[AsyncSession],
    service: str,
    *,
    interval: timedelta = timedelta(seconds=30),
) -> None:
    """Continuously publish a service heartbeat while its runtime is alive."""
    while True:
        async with session_factory.begin() as session:
            await HeartbeatRepository(session).touch(service)
        await asyncio.sleep(interval.total_seconds())
