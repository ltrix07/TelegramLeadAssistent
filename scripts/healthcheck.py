"""Container health check for PostgreSQL connectivity."""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import ServiceName, load_startup_settings


async def check_database(database_url: str) -> None:
    """Connect to PostgreSQL and execute a minimal query."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


def main() -> None:
    """Run the database health check using application settings."""
    settings = load_startup_settings(ServiceName.MAINTENANCE_WORKER)
    database_url = settings.database_url
    if database_url is None:
        raise SystemExit("Configuration error: DATABASE_URL is required")
    asyncio.run(check_database(database_url.get_secret_value()))


if __name__ == "__main__":
    main()
