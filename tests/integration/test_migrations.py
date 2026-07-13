"""Integration tests for the complete initial migration lifecycle."""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.database.models import Base

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for migration integration tests")
    return value


def _alembic_config() -> Config:
    return Config("alembic.ini")


async def _async_schema_state(database_url: str) -> tuple[set[str], list[object]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(_compare_schema)
    finally:
        await engine.dispose()


def _schema_state(database_url: str) -> tuple[set[str], list[object]]:
    return asyncio.run(_async_schema_state(database_url))


def _compare_schema(connection: Connection) -> tuple[set[str], list[object]]:
    tables = set(inspect(connection).get_table_names())
    migration_context = MigrationContext.configure(connection)
    differences = compare_metadata(migration_context, Base.metadata)
    return tables, differences


def test_upgrade_downgrade_upgrade_and_metadata_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _database_url()
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = _alembic_config()

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    tables, differences = _schema_state(database_url)
    assert set(Base.metadata.tables) <= tables
    assert differences == []

    command.downgrade(config, "base")
    tables_after_downgrade, _ = _schema_state(database_url)
    assert tables_after_downgrade == {"alembic_version"}

    command.upgrade(config, "head")
    tables_after_second_upgrade, differences_after_second_upgrade = _schema_state(database_url)
    assert set(Base.metadata.tables) <= tables_after_second_upgrade
    assert differences_after_second_upgrade == []
