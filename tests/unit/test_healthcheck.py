"""Tests for the container database health check."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from app.config import AppSettings
from scripts import healthcheck


class _FakeSession:
    """Yield canned scalar() results in call order, without touching a real database."""

    def __init__(self, values: list[object]) -> None:
        self._values = iter(values)

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalar(self, *_args: object, **_kwargs: object) -> object:
        return next(self._values)


def _fake_session_factory(values: list[object]) -> Callable[[], _FakeSession]:
    def factory() -> _FakeSession:
        return _FakeSession(values)

    return factory


def test_healthcheck_uses_configured_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "postgresql+asyncpg://test:test@postgres/test"
    observed: list[str] = []

    async def fake_check_database(value: str) -> None:
        observed.append(value)

    settings = AppSettings(database_url=SecretStr(database_url))
    monkeypatch.setattr(healthcheck, "load_startup_settings", lambda service: settings)
    monkeypatch.setattr(healthcheck, "check_database", fake_check_database)

    healthcheck.main([])

    assert observed == [database_url]


def test_no_argument_form_does_not_check_any_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Called bare, behaviour must stay exactly what it was before this check knew services."""
    settings = AppSettings(database_url=SecretStr("postgresql+asyncpg://test:test@postgres/test"))
    heartbeat_calls: list[object] = []

    async def fake_check_database(_value: str) -> None:
        return None

    async def fake_check_heartbeat(*args: object, **kwargs: object) -> None:
        heartbeat_calls.append((args, kwargs))

    monkeypatch.setattr(healthcheck, "load_startup_settings", lambda service: settings)
    monkeypatch.setattr(healthcheck, "check_database", fake_check_database)
    monkeypatch.setattr(healthcheck, "check_heartbeat", fake_check_heartbeat)

    healthcheck.main([])

    assert heartbeat_calls == []


def test_maintenance_worker_passes_without_any_heartbeat_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """maintenance-worker publishes no heartbeat; it must never be required to have one."""
    settings = AppSettings(database_url=SecretStr("postgresql+asyncpg://test:test@postgres/test"))
    heartbeat_calls: list[object] = []

    async def fake_check_database(_value: str) -> None:
        return None

    async def fake_check_heartbeat(*args: object, **kwargs: object) -> None:
        heartbeat_calls.append((args, kwargs))

    monkeypatch.setattr(healthcheck, "load_startup_settings", lambda service: settings)
    monkeypatch.setattr(healthcheck, "check_database", fake_check_database)
    monkeypatch.setattr(healthcheck, "check_heartbeat", fake_check_heartbeat)

    healthcheck.main(["maintenance-worker"])

    assert heartbeat_calls == []


def test_heartbeat_publishing_service_argument_triggers_freshness_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service known to publish heartbeats must have its freshness checked."""
    settings = AppSettings(database_url=SecretStr("postgresql+asyncpg://test:test@postgres/test"))
    heartbeat_calls: list[str] = []

    async def fake_check_database(_value: str) -> None:
        return None

    async def fake_check_heartbeat(_session_factory: object, service: str) -> None:
        heartbeat_calls.append(service)

    monkeypatch.setattr(healthcheck, "load_startup_settings", lambda service: settings)
    monkeypatch.setattr(healthcheck, "check_database", fake_check_database)
    monkeypatch.setattr(healthcheck, "check_heartbeat", fake_check_heartbeat)

    healthcheck.main(["operator-bot"])

    assert heartbeat_calls == ["operator-bot"]


@pytest.mark.parametrize("service", ["telegram-listener", "classification-worker", "operator-bot"])
def test_check_heartbeat_passes_when_fresh(service: str) -> None:
    now = datetime(2026, 9, 8, tzinfo=UTC)
    checked_at = now - timedelta(seconds=10)
    session_factory = _fake_session_factory([now, checked_at])

    asyncio.run(
        asyncio.wait_for(
            healthcheck.check_heartbeat(session_factory, service),  # type: ignore[arg-type]
            timeout=2.0,
        )
    )


def test_check_heartbeat_fails_when_stale() -> None:
    now = datetime(2026, 9, 8, tzinfo=UTC)
    checked_at = now - timedelta(seconds=healthcheck.HEARTBEAT_STALE_SECONDS + 1)
    session_factory = _fake_session_factory([now, checked_at])

    with pytest.raises(SystemExit, match="operator-bot"):
        asyncio.run(
            asyncio.wait_for(
                healthcheck.check_heartbeat(session_factory, "operator-bot"),  # type: ignore[arg-type]
                timeout=2.0,
            )
        )


def test_check_heartbeat_fails_when_never_started() -> None:
    now = datetime(2026, 9, 8, tzinfo=UTC)
    session_factory = _fake_session_factory([now, None])

    with pytest.raises(SystemExit, match="no heartbeat recorded"):
        asyncio.run(
            asyncio.wait_for(
                healthcheck.check_heartbeat(session_factory, "operator-bot"),  # type: ignore[arg-type]
                timeout=2.0,
            )
        )


def test_check_heartbeat_exactly_at_threshold_passes() -> None:
    """The boundary belongs to the healthy side: exactly the threshold age must still pass."""
    now = datetime(2026, 9, 8, tzinfo=UTC)
    checked_at = now - timedelta(seconds=healthcheck.HEARTBEAT_STALE_SECONDS)
    session_factory = _fake_session_factory([now, checked_at])

    asyncio.run(
        asyncio.wait_for(
            healthcheck.check_heartbeat(session_factory, "operator-bot"),  # type: ignore[arg-type]
            timeout=2.0,
        )
    )
