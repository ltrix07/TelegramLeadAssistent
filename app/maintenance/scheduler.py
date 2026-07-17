"""Periodic maintenance scheduling and stale-lock recovery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.status import StatusRepository, TranslatorHealthProbe
from app.database.queue import JobRepository
from app.database.repositories.operational_alerts import OperationalAlertRepository
from app.database.repositories.outbound_commands import OutboundCommandRepository
from app.database.repositories.retention import RetentionCleanupResult, RetentionRepository

RETENTION_BATCH_SIZE = 500


@dataclass(frozen=True, slots=True)
class MaintenanceResult:
    """Work completed by one maintenance transaction."""

    processing_recovered: list[UUID]
    outbound_recovered: list[UUID]
    retention: RetentionCleanupResult
    alerts_created: int = 0


class MaintenanceScheduler:
    """Run idempotent maintenance operations on a configurable cadence."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        interval_seconds: float,
        stale_lock_timeout: timedelta,
        temporary_ttl: timedelta,
        relevant_retention: timedelta,
        retention_batch_size: int = RETENTION_BATCH_SIZE,
        operator_user_id: int | None = None,
        translator_probe: TranslatorHealthProbe | None = None,
        budget_thresholds: tuple[Decimal, ...] = (),
        mtproto_alert_after: timedelta = timedelta(minutes=5),
        queue_delay_alert_after: timedelta = timedelta(minutes=10),
        translator_alert_after: timedelta = timedelta(minutes=15),
    ) -> None:
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._stale_lock_timeout = stale_lock_timeout
        self._temporary_ttl = temporary_ttl
        self._relevant_retention = relevant_retention
        self._retention_batch_size = retention_batch_size
        self._operator_user_id = operator_user_id
        self._translator_probe = translator_probe
        self._budget_thresholds = budget_thresholds
        self._mtproto_alert_after = mtproto_alert_after
        self._queue_delay_alert_after = queue_delay_alert_after
        self._translator_alert_after = translator_alert_after

    async def run_once(self) -> MaintenanceResult:
        """Recover stale claims and delete one bounded retention batch."""
        translator_healthy = (
            await self._translator_probe.healthy() if self._translator_probe is not None else True
        )
        alerts_created = 0
        async with self._session_factory.begin() as session:
            stale_before = await session.scalar(select(func.now() - self._stale_lock_timeout))
            if stale_before is None:
                raise RuntimeError("Database did not return stale-lock cutoff")
            processing_ids = await JobRepository(session).recover_stale(stale_before)
            outbound_ids = await OutboundCommandRepository(session).recover_stale(stale_before)
            retention = await RetentionRepository(session).cleanup_once(
                temporary_ttl=self._temporary_ttl,
                relevant_retention=self._relevant_retention,
                batch_size=self._retention_batch_size,
            )
            if self._operator_user_id is not None:
                snapshot = await StatusRepository(session).collect(
                    translator_healthy=translator_healthy
                )
                alerts = OperationalAlertRepository(session)
                database_now = await session.scalar(select(func.now()))
                if database_now is None:
                    raise RuntimeError("Database did not return current time")
                alerts_created += await alerts.enqueue_budget_thresholds(
                    month_key=database_now.strftime("%Y-%m"),
                    cost_usd=snapshot.api_cost_month_usd,
                    thresholds=self._budget_thresholds,
                    operator_user_id=self._operator_user_id,
                )
                observations = (
                    (
                        "mtproto",
                        not snapshot.mtproto_healthy,
                        timedelta(0)
                        if snapshot.mtproto_heartbeat_age_seconds is not None
                        and snapshot.mtproto_heartbeat_age_seconds
                        > self._mtproto_alert_after.total_seconds()
                        else self._mtproto_alert_after,
                        "mtproto_disconnected",
                    ),
                    (
                        "queue_delay",
                        snapshot.oldest_job_age_seconds
                        > self._queue_delay_alert_after.total_seconds(),
                        timedelta(0),
                        "queue_delayed",
                    ),
                    (
                        "translator",
                        not snapshot.translator_healthy,
                        self._translator_alert_after,
                        "translator_unavailable",
                    ),
                )
                for condition_key, failing, threshold, alert_type in observations:
                    alerts_created += int(
                        await alerts.observe_condition(
                            condition_key=condition_key,
                            failing=failing,
                            threshold=threshold,
                            alert_type=alert_type,
                            operator_user_id=self._operator_user_id,
                        )
                    )
        return MaintenanceResult(processing_ids, outbound_ids, retention, alerts_created)

    async def run_forever(self) -> None:
        """Run maintenance immediately and then at the configured interval."""
        while True:
            await self.run_once()
            await asyncio.sleep(self._interval_seconds)
