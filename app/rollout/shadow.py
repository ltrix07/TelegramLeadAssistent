"""Content-free shadow-mode stability reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import FeatureFlags
from app.database.models import (
    BotNotification,
    ClassificationRun,
    DetectedQuestion,
    MonitoredChat,
    OutboundCommand,
    ProcessingJob,
)
from app.domain.enums import MonitoredChatStatus, ProcessingJobStatus


@dataclass(frozen=True, slots=True)
class ShadowReport:
    chat_id: int
    started_at: datetime
    ended_at: datetime
    classification_calls: int
    classified_messages: int
    relevant: int
    irrelevant: int
    context_required: int
    failed_jobs: int
    pending_jobs: int
    average_queue_latency_seconds: float
    maximum_queue_latency_seconds: float
    estimated_cost_usd: Decimal
    sent_operator_notifications: int
    outbound_commands: int
    expired_temporary_rows: int

    @property
    def safe(self) -> bool:
        return self.sent_operator_notifications == 0 and self.outbound_commands == 0


class ShadowModeError(ValueError):
    """Reject a report that cannot prove the shadow-mode boundary."""


class ShadowReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def collect(
        self,
        *,
        chat_id: int,
        started_at: datetime,
        ended_at: datetime,
        flags: FeatureFlags,
    ) -> ShadowReport:
        """Collect aggregate-only evidence for one active chat and time window."""
        if started_at >= ended_at:
            raise ShadowModeError("Shadow report start must precede its end")
        if flags.notifications_enabled or flags.outbound_replies_enabled:
            raise ShadowModeError(
                "Shadow mode requires notifications and outbound replies disabled"
            )
        active_ids = list(
            await self._session.scalars(
                select(MonitoredChat.telegram_chat_id).where(
                    MonitoredChat.status == MonitoredChatStatus.ACTIVE
                )
            )
        )
        if active_ids != [chat_id]:
            raise ShadowModeError("Shadow mode requires exactly the selected active chat")

        window = ClassificationRun.created_at.between(started_at, ended_at)
        latency = func.extract("epoch", ClassificationRun.created_at - ClassificationRun.queued_at)
        run_row = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count(func.distinct(ClassificationRun.telegram_message_id)),
                    func.sum(case((ClassificationRun.result == "relevant", 1), else_=0)),
                    func.sum(case((ClassificationRun.result == "irrelevant", 1), else_=0)),
                    func.sum(case((ClassificationRun.result == "context_required", 1), else_=0)),
                    func.coalesce(func.avg(latency), 0),
                    func.coalesce(func.max(latency), 0),
                    func.coalesce(func.sum(ClassificationRun.estimated_cost_usd), 0),
                ).where(ClassificationRun.telegram_chat_id == chat_id, window)
            )
        ).one()
        failed_jobs, pending_jobs, expired_rows = (
            await self._session.execute(
                select(
                    func.sum(
                        case((ProcessingJob.status == ProcessingJobStatus.FAILED, 1), else_=0)
                    ),
                    func.sum(
                        case((ProcessingJob.status != ProcessingJobStatus.FAILED, 1), else_=0)
                    ),
                    func.sum(case((ProcessingJob.expires_at < func.now(), 1), else_=0)),
                ).where(ProcessingJob.telegram_chat_id == chat_id)
            )
        ).one()
        sent_notifications = await self._session.scalar(
            select(func.count())
            .select_from(BotNotification)
            .join(DetectedQuestion)
            .where(
                DetectedQuestion.telegram_chat_id == chat_id,
                BotNotification.sent_at.between(started_at, ended_at),
            )
        )
        outbound = await self._session.scalar(
            select(func.count())
            .select_from(OutboundCommand)
            .where(
                OutboundCommand.telegram_chat_id == chat_id,
                or_(
                    OutboundCommand.created_at.between(started_at, ended_at),
                    OutboundCommand.completed_at.between(started_at, ended_at),
                ),
            )
        )
        return ShadowReport(
            chat_id=chat_id,
            started_at=started_at,
            ended_at=ended_at,
            classification_calls=int(run_row[0]),
            classified_messages=int(run_row[1]),
            relevant=int(run_row[2] or 0),
            irrelevant=int(run_row[3] or 0),
            context_required=int(run_row[4] or 0),
            average_queue_latency_seconds=float(run_row[5]),
            maximum_queue_latency_seconds=float(run_row[6]),
            estimated_cost_usd=Decimal(run_row[7]),
            failed_jobs=int(failed_jobs or 0),
            pending_jobs=int(pending_jobs or 0),
            sent_operator_notifications=int(sent_notifications or 0),
            outbound_commands=int(outbound or 0),
            expired_temporary_rows=int(expired_rows or 0),
        )


def render_shadow_report(report: ShadowReport) -> str:
    """Render a content-free Markdown stability report."""
    verdict = "PASS" if report.safe else "FAIL"
    return "\n".join(
        (
            "# Shadow mode stability report",
            "",
            f"- Verdict: {verdict}",
            f"- Selected chat ID: {report.chat_id}",
            f"- Window: {report.started_at.isoformat()} — {report.ended_at.isoformat()}",
            f"- Classified messages: {report.classified_messages}",
            f"- Classification calls: {report.classification_calls}",
            "- Results: "
            f"relevant={report.relevant}, irrelevant={report.irrelevant}, "
            f"context_required={report.context_required}",
            "- Queue latency: "
            f"average={report.average_queue_latency_seconds:.3f}s, "
            f"maximum={report.maximum_queue_latency_seconds:.3f}s",
            f"- Estimated API cost: ${report.estimated_cost_usd:.6f}",
            f"- Queue state: failed={report.failed_jobs}, pending={report.pending_jobs}",
            f"- Sent operator notifications: {report.sent_operator_notifications}",
            f"- Outbound commands created: {report.outbound_commands}",
            f"- Expired temporary rows awaiting cleanup: {report.expired_temporary_rows}",
        )
    )
