"""PostgreSQL proof for budget and prolonged-failure alert deduplication."""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from decimal import Decimal

import pytest
from alembic.config import Config
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.database.models import AlertCondition, OperationalAlert
from app.database.repositories.operational_alerts import OperationalAlertRepository

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for alert integration tests")
    return value


async def _exercise(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.execute(delete(OperationalAlert))
            await connection.execute(delete(AlertCondition))

        async with factory.begin() as session:
            repository = OperationalAlertRepository(session)
            assert (
                await repository.enqueue_budget_thresholds(
                    month_key="2026-07",
                    cost_usd=Decimal("8.50"),
                    thresholds=(Decimal("5"), Decimal("8"), Decimal("10")),
                    operator_user_id=77,
                )
                == 2
            )
            assert (
                await repository.enqueue_budget_thresholds(
                    month_key="2026-07",
                    cost_usd=Decimal("10.25"),
                    thresholds=(Decimal("5"), Decimal("8"), Decimal("10")),
                    operator_user_id=77,
                )
                == 1
            )

        async with factory.begin() as session:
            repository = OperationalAlertRepository(session)
            assert not await repository.observe_condition(
                condition_key="translator",
                failing=True,
                threshold=timedelta(minutes=15),
                alert_type="translator_unavailable",
                operator_user_id=77,
            )
            await session.execute(
                update(AlertCondition)
                .where(AlertCondition.condition_key == "translator")
                .values(failing_since=func.now() - timedelta(minutes=16))
            )

        async with factory.begin() as session:
            repository = OperationalAlertRepository(session)
            assert await repository.observe_condition(
                condition_key="translator",
                failing=True,
                threshold=timedelta(minutes=15),
                alert_type="translator_unavailable",
                operator_user_id=77,
            )
            assert not await repository.observe_condition(
                condition_key="translator",
                failing=True,
                threshold=timedelta(minutes=15),
                alert_type="translator_unavailable",
                operator_user_id=77,
            )
            assert not await repository.observe_condition(
                condition_key="translator",
                failing=False,
                threshold=timedelta(minutes=15),
                alert_type="translator_unavailable",
                operator_user_id=77,
            )

        async with factory() as session:
            alerts = list(
                await session.scalars(
                    select(OperationalAlert).order_by(OperationalAlert.created_at)
                )
            )
            assert len(alerts) == 4
            assert all(alert.operator_telegram_user_id == 77 for alert in alerts)
            assert [alert.alert_type for alert in alerts].count("budget_threshold") == 3
            assert [alert.alert_type for alert in alerts].count("translator_unavailable") == 1
            assert await session.get(AlertCondition, "translator") is None
    finally:
        await engine.dispose()


def test_alert_threshold_crossings_and_failure_episodes(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _database_url()
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise(database_url))
