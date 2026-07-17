"""PostgreSQL proof for the aggregate-only shadow-mode report."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.config import FeatureFlags
from app.database.models import ClassificationRun, MonitoredChat
from app.domain.enums import MonitoredChatStatus, MonitoredChatType
from app.rollout.shadow import ShadowReportRepository

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for shadow report integration tests")
    return value


async def _exercise(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE monitored_chats CASCADE")
            await connection.exec_driver_sql("TRUNCATE classification_runs CASCADE")
        async with factory.begin() as session:
            session.add(
                MonitoredChat(
                    telegram_chat_id=-100902,
                    title="Shadow test",
                    chat_type=MonitoredChatType.SUPERGROUP,
                    status=MonitoredChatStatus.ACTIVE,
                    added_by_telegram_user_id=1,
                )
            )
            session.add_all(
                (
                    ClassificationRun(
                        telegram_chat_id=-100902,
                        telegram_message_id=1,
                        stage=1,
                        result="irrelevant",
                        category="other",
                        model="test-model",
                        input_tokens=10,
                        output_tokens=2,
                        estimated_cost_usd=Decimal("0.000010"),
                        queued_at=now - timedelta(seconds=3),
                        created_at=now,
                    ),
                    ClassificationRun(
                        telegram_chat_id=-100902,
                        telegram_message_id=2,
                        stage=1,
                        result="relevant",
                        category="product",
                        model="test-model",
                        input_tokens=12,
                        output_tokens=3,
                        estimated_cost_usd=Decimal("0.000020"),
                        queued_at=now - timedelta(seconds=1),
                        created_at=now,
                    ),
                )
            )

        flags = FeatureFlags(
            monitoring_enabled=True,
            notifications_enabled=False,
            outbound_replies_enabled=False,
            translation_enabled=False,
        )
        async with factory() as session:
            report = await ShadowReportRepository(session).collect(
                chat_id=-100902,
                started_at=now - timedelta(minutes=1),
                ended_at=now + timedelta(minutes=1),
                flags=flags,
            )
        assert report.safe is True
        assert report.classification_calls == 2
        assert report.classified_messages == 2
        assert report.relevant == 1
        assert report.irrelevant == 1
        assert report.average_queue_latency_seconds == pytest.approx(2.0)
        assert report.maximum_queue_latency_seconds == pytest.approx(3.0)
        assert report.estimated_cost_usd == Decimal("0.000030")
        assert report.sent_operator_notifications == 0
        assert report.outbound_commands == 0
    finally:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE monitored_chats CASCADE")
            await connection.exec_driver_sql("TRUNCATE classification_runs CASCADE")
        await engine.dispose()


def test_shadow_report_aggregates_one_active_chat() -> None:
    database_url = _database_url()
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise(database_url))
