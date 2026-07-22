"""Alembic environment for async SQLAlchemy migrations."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import context
from app.config import ServiceName, load_startup_settings
from app.database.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    settings = load_startup_settings(ServiceName.MAINTENANCE_WORKER)
    database_url = settings.database_url
    if database_url is None:
        raise SystemExit("Configuration error: DATABASE_URL is required")
    return database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Run migrations without opening a database connection."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations through one async database connection."""
    engine = create_async_engine(_database_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_sync_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
