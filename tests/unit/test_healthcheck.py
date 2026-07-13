"""Tests for the container database health check."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.config import AppSettings
from scripts import healthcheck


def test_healthcheck_uses_configured_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "postgresql+asyncpg://test:test@postgres/test"
    observed: list[str] = []

    async def fake_check_database(value: str) -> None:
        observed.append(value)

    settings = AppSettings(database_url=SecretStr(database_url))
    monkeypatch.setattr(healthcheck, "load_startup_settings", lambda service: settings)
    monkeypatch.setattr(healthcheck, "check_database", fake_check_database)

    healthcheck.main()

    assert observed == [database_url]
