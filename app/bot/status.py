"""Safe operational status collection and rendering for the operator bot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    ApiUsageDaily,
    MonitoredChat,
    OutboundCommand,
    ProcessingJob,
    ServiceHeartbeat,
)
from app.domain.enums import MonitoredChatStatus, OutboundCommandStatus, ProcessingJobStatus

HEARTBEAT_MAX_AGE = timedelta(seconds=90)


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    """Content-free operational counters and component states."""

    mtproto_healthy: bool
    classifier_healthy: bool
    translator_healthy: bool
    active_chats: int
    pending_classification_jobs: int
    pending_outbound_commands: int
    outbound_needs_review: int
    oldest_job_age_seconds: float
    api_cost_month_usd: Decimal
    mtproto_heartbeat_age_seconds: float | None = None


class TranslatorHealthProbe:
    """Check the internal translator health endpoint without sending content."""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def healthy(self) -> bool:
        """Return false for transport errors and malformed/unhealthy responses."""
        try:
            async with httpx.AsyncClient(base_url=self._base_url) as client:
                response = await client.get("/health", timeout=self._timeout_seconds)
                response.raise_for_status()
                payload = response.json()
            return isinstance(payload, dict) and payload.get("status") == "ok"
        except (httpx.HTTPError, ValueError, TypeError):
            return False


class StatusRepository:
    """Read a consistent operational snapshot from PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def collect(self, *, translator_healthy: bool) -> StatusSnapshot:
        """Aggregate status without selecting any sensitive text columns."""
        now = await self._session.scalar(select(func.now()))
        if now is None:
            raise RuntimeError("Database did not return current time")
        heartbeat_rows = (
            (
                await self._session.execute(
                    select(ServiceHeartbeat.service, ServiceHeartbeat.checked_at).where(
                        ServiceHeartbeat.service.in_(("telegram-listener", "classification-worker"))
                    )
                )
            )
            .tuples()
            .all()
        )
        heartbeats: dict[str, datetime] = {
            service: checked_at for service, checked_at in heartbeat_rows
        }

        active_chats = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(MonitoredChat)
                    .where(MonitoredChat.status == MonitoredChatStatus.ACTIVE)
                )
            )
            or 0
        )
        classification_states = (
            ProcessingJobStatus.PENDING,
            ProcessingJobStatus.PROCESSING,
            ProcessingJobStatus.RETRY,
            ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING,
            ProcessingJobStatus.AWAITING_REPLY_CONTEXT,
        )
        pending_classification = int(
            (
                await self._session.scalar(
                    select(func.count())
                    .select_from(ProcessingJob)
                    .where(ProcessingJob.status.in_(classification_states))
                )
            )
            or 0
        )
        outbound_counts = (
            await self._session.execute(
                select(
                    func.sum(
                        case(
                            (
                                OutboundCommand.status.in_(
                                    (
                                        OutboundCommandStatus.PENDING,
                                        OutboundCommandStatus.PROCESSING,
                                    )
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    func.sum(
                        case(
                            (OutboundCommand.status == OutboundCommandStatus.NEEDS_REVIEW, 1),
                            else_=0,
                        )
                    ),
                )
            )
        ).one()
        oldest_created = await self._session.scalar(
            select(func.min(ProcessingJob.created_at)).where(
                ProcessingJob.status.in_(classification_states)
            )
        )
        month_start = now.date().replace(day=1)
        month_cost = await self._session.scalar(
            select(func.coalesce(func.sum(ApiUsageDaily.estimated_cost_usd), 0)).where(
                ApiUsageDaily.usage_date.between(month_start, now.date())
            )
        )

        def heartbeat_is_fresh(service: str) -> bool:
            checked_at = heartbeats.get(service)
            return checked_at is not None and now - checked_at <= HEARTBEAT_MAX_AGE

        oldest_age = max((now - oldest_created).total_seconds(), 0.0) if oldest_created else 0.0
        mtproto_checked_at = heartbeats.get("telegram-listener")
        mtproto_age = (
            max((now - mtproto_checked_at).total_seconds(), 0.0)
            if mtproto_checked_at is not None
            else None
        )
        return StatusSnapshot(
            mtproto_healthy=heartbeat_is_fresh("telegram-listener"),
            classifier_healthy=heartbeat_is_fresh("classification-worker"),
            translator_healthy=translator_healthy,
            active_chats=active_chats,
            pending_classification_jobs=pending_classification,
            pending_outbound_commands=int(outbound_counts[0] or 0),
            outbound_needs_review=int(outbound_counts[1] or 0),
            oldest_job_age_seconds=oldest_age,
            api_cost_month_usd=Decimal(month_cost or 0),
            mtproto_heartbeat_age_seconds=mtproto_age,
        )


def render_status(snapshot: StatusSnapshot) -> str:
    """Render only health labels, counters, durations, and aggregate cost."""
    state = {True: "работает", False: "НЕДОСТУПЕН"}
    oldest = f"{snapshot.oldest_job_age_seconds:.0f} сек."
    return "\n".join(
        (
            "Состояние системы",
            f"MTProto: {state[snapshot.mtproto_healthy]}",
            "Bot API: работает",
            "PostgreSQL: работает",
            f"Classifier: {state[snapshot.classifier_healthy]}",
            f"Translator: {state[snapshot.translator_healthy]}",
            f"Активные чаты: {snapshot.active_chats}",
            f"Задачи классификации: {snapshot.pending_classification_jobs}",
            f"Исходящие команды: {snapshot.pending_outbound_commands}",
            f"Требуют проверки: {snapshot.outbound_needs_review}",
            f"Самая старая задача: {oldest}",
            f"Расход API за месяц: ${snapshot.api_cost_month_usd:.2f}",
        )
    )
