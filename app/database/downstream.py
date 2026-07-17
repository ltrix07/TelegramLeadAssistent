"""PostgreSQL hand-off queue for reply-chain and downstream classification work."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ProcessingJob
from app.database.queue import JobRepository
from app.domain.enums import ProcessingJobStatus


class DownstreamPhase(StrEnum):
    """Disjoint consumers of one durable processing row."""

    REPLY_CHAIN = "reply_chain"
    CLASSIFICATION = "classification"


class DownstreamJobRepository:
    """Claim downstream jobs without exposing MTProto outside the listener."""

    STALE_LOCK_AFTER = timedelta(minutes=5)
    _STATUSES = (
        ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING,
        ProcessingJobStatus.AWAITING_REPLY_CONTEXT,
    )

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(self, worker_id: str, phase: DownstreamPhase) -> ProcessingJob | None:
        """Claim the oldest ready row for exactly one downstream phase."""
        snapshot_predicate = (
            ProcessingJob.reply_chain_snapshot.is_(None)
            if phase is DownstreamPhase.REPLY_CHAIN
            else ProcessingJob.reply_chain_snapshot.is_not(None)
        )
        stale_before = func.now() - self.STALE_LOCK_AFTER
        statement = (
            select(ProcessingJob)
            .where(
                ProcessingJob.status.in_(self._STATUSES),
                ProcessingJob.next_attempt_at <= func.now(),
                snapshot_predicate,
                or_(ProcessingJob.locked_at.is_(None), ProcessingJob.locked_at < stale_before),
            )
            .order_by(ProcessingJob.created_at, ProcessingJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = await self._session.scalar(statement)
        if job is None:
            return None
        job.locked_at = cast(datetime, await self._session.scalar(select(func.now())))
        job.locked_by = worker_id
        job.attempt_count += 1
        await self._session.flush()
        return job

    async def save_reply_chain(self, job_id: UUID, snapshot: dict[str, Any]) -> None:
        """Publish a validated JSON snapshot to the classifier phase."""
        job = await self._get_locked(job_id)
        job.reply_chain_snapshot = snapshot
        job.attempt_count = 0
        job.next_attempt_at = cast(datetime, await self._session.scalar(select(func.now())))
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = None
        job.last_error_message = None
        await self._session.flush()

    async def retry(self, job_id: UUID, error_code: str, retry_at: datetime) -> None:
        """Release downstream work without routing it back through Stage 1."""
        job = await self._get_locked(job_id)
        job.next_attempt_at = retry_at
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = error_code[:100]
        job.last_error_message = None
        await self._session.flush()

    async def fail(self, job_id: UUID, error_code: str) -> None:
        """Move exhausted downstream work to terminal operator review."""
        await JobRepository(self._session).fail(job_id, error_code[:100])

    async def _get_locked(self, job_id: UUID) -> ProcessingJob:
        job = await self._session.scalar(
            select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update()
        )
        if job is None:
            raise LookupError(f"Downstream job not found: {job_id}")
        return job
