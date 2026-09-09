"""Container health check for PostgreSQL connectivity and service liveness."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import ServiceName, load_startup_settings
from app.database.models import ServiceHeartbeat

# Four missed 30-second heartbeats (see app.database.health.run_heartbeat's default interval).
HEARTBEAT_STALE_SECONDS = 120

# Services that publish to service_heartbeats. maintenance-worker does not and must not be
# required to: a bare "SELECT 1" is its whole check.
HEARTBEAT_PUBLISHING_SERVICES = frozenset(
    {ServiceName.TELEGRAM_LISTENER, ServiceName.CLASSIFICATION_WORKER, ServiceName.OPERATOR_BOT}
)


async def check_database(database_url: str) -> None:
    """Connect to PostgreSQL and execute a minimal query."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


async def check_heartbeat(
    session_factory: async_sessionmaker[AsyncSession],
    service: str,
    *,
    max_age_seconds: int = HEARTBEAT_STALE_SECONDS,
) -> None:
    """Fail when the named service has no heartbeat row or it is stale.

    Never logs message content, tokens or prompts: only the service name and its heartbeat
    age are reported on failure.
    """
    async with session_factory() as session:
        now = await session.scalar(select(func.now()))
        checked_at = await session.scalar(
            select(ServiceHeartbeat.checked_at).where(ServiceHeartbeat.service == service)
        )
    if now is None:
        raise SystemExit("Health check error: database did not return current time")
    if checked_at is None:
        raise SystemExit(f"Health check failed: no heartbeat recorded for service={service}")
    age_seconds = (now - checked_at).total_seconds()
    if age_seconds > max_age_seconds:
        raise SystemExit(
            f"Health check failed: stale heartbeat for service={service} "
            f"age_seconds={age_seconds:.0f}"
        )


async def _run_checks(database_url: str, service: str | None) -> None:
    """Always prove PostgreSQL is reachable; also require a fresh heartbeat when relevant."""
    await check_database(database_url)
    if service is None or service not in HEARTBEAT_PUBLISHING_SERVICES:
        return
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        await check_heartbeat(session_factory, service)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    """Run the database health check, optionally scoped to one service by name.

    Called with no service argument, behaviour is unchanged from before this check learned
    about services: only ``SELECT 1`` runs. Passing a service name that publishes a heartbeat
    (``telegram-listener``, ``classification-worker``, ``operator-bot``) additionally requires
    a heartbeat row no older than ``HEARTBEAT_STALE_SECONDS``. Any other service name, including
    ``maintenance-worker``, keeps the bare check.
    """
    args = sys.argv[1:] if argv is None else argv
    service = args[0] if args else None
    settings = load_startup_settings(ServiceName.MAINTENANCE_WORKER)
    database_url = settings.database_url
    if database_url is None:
        raise SystemExit("Configuration error: DATABASE_URL is required")
    asyncio.run(_run_checks(database_url.get_secret_value(), service))


if __name__ == "__main__":
    main()
