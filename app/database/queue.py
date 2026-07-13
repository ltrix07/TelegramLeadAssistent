"""Transaction-scoped repository for the PostgreSQL processing queue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ProcessingJob
from app.domain.enums import ProcessingJobStatus


@dataclass(frozen=True, slots=True)
class NewJob:
    """Values required to enqueue one Telegram message."""

    monitored_chat_id: UUID
    telegram_chat_id: int
    telegram_message_id: int
    message_text: str
    telegram_created_at: datetime
    topic_id: int | None = None
    sender_telegram_id: int | None = None
    sender_display_name: str | None = None


class JobRepository:
    """Queue operations that participate in the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, job: NewJob) -> UUID:
        """Insert a job once and return the existing ID for a duplicate message."""
        statement = (
            insert(ProcessingJob)
            .values(
                monitored_chat_id=job.monitored_chat_id,
                telegram_chat_id=job.telegram_chat_id,
                telegram_message_id=job.telegram_message_id,
                topic_id=job.topic_id,
                sender_telegram_id=job.sender_telegram_id,
                sender_display_name=job.sender_display_name,
                message_text=job.message_text,
                telegram_created_at=job.telegram_created_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ProcessingJob.telegram_chat_id,
                    ProcessingJob.telegram_message_id,
                ]
            )
            .returning(ProcessingJob.id)
        )
        job_id = (await self._session.execute(statement)).scalar_one_or_none()
        if job_id is not None:
            return job_id

        existing_id = await self._session.scalar(
            select(ProcessingJob.id).where(
                ProcessingJob.telegram_chat_id == job.telegram_chat_id,
                ProcessingJob.telegram_message_id == job.telegram_message_id,
            )
        )
        if existing_id is None:
            raise RuntimeError("Duplicate queue job disappeared before it could be read")
        return existing_id

    async def claim(self, worker_id: str) -> ProcessingJob | None:
        """Lock and claim the oldest ready job without waiting for locked rows."""
        statement = (
            select(ProcessingJob)
            .where(
                ProcessingJob.status.in_((ProcessingJobStatus.PENDING, ProcessingJobStatus.RETRY)),
                ProcessingJob.next_attempt_at <= func.now(),
            )
            .order_by(ProcessingJob.created_at, ProcessingJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = await self._session.scalar(statement)
        if job is None:
            return None

        job.status = ProcessingJobStatus.PROCESSING
        job.locked_at = cast(datetime, await self._session.scalar(select(func.now())))
        job.locked_by = worker_id
        job.attempt_count += 1
        await self._session.flush()
        return job

    async def retry(
        self,
        job_id: UUID,
        error_code: str,
        retry_at: datetime,
        *,
        error_message: str | None = None,
    ) -> None:
        """Release a claimed job and make it available at the requested time."""
        job = await self._get_locked(job_id)
        job.status = ProcessingJobStatus.RETRY
        job.next_attempt_at = retry_at
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = error_code
        job.last_error_message = error_message
        await self._session.flush()

    async def complete(self, job_id: UUID) -> None:
        """Delete a successfully processed temporary job."""
        await self._session.execute(delete(ProcessingJob).where(ProcessingJob.id == job_id))

    async def route(self, job_id: UUID, status: ProcessingJobStatus) -> None:
        """Release a classified job into a non-claimable downstream state."""
        if status not in (
            ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING,
            ProcessingJobStatus.AWAITING_REPLY_CONTEXT,
        ):
            raise ValueError("Unsupported classification route")
        job = await self._get_locked(job_id)
        job.status = status
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = None
        job.last_error_message = None
        await self._session.flush()

    async def fail(
        self,
        job_id: UUID,
        error_code: str,
        *,
        error_message: str | None = None,
    ) -> None:
        """Release a poison job into a terminal state for operator review."""
        job = await self._get_locked(job_id)
        job.status = ProcessingJobStatus.FAILED
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = error_code
        job.last_error_message = error_message
        await self._session.flush()

    async def oldest_job_age_seconds(self) -> float:
        """Return the age of the oldest claimable queue job using database time."""
        age = await self._session.scalar(
            select(
                func.extract(
                    "epoch",
                    func.now() - func.min(ProcessingJob.created_at),
                )
            ).where(
                ProcessingJob.status.in_((ProcessingJobStatus.PENDING, ProcessingJobStatus.RETRY))
            )
        )
        return max(float(age or 0), 0.0)

    async def recover_stale(self, stale_before: datetime) -> list[UUID]:
        """Return processing jobs with expired locks to the retry state."""
        statement = (
            update(ProcessingJob)
            .where(
                ProcessingJob.status == ProcessingJobStatus.PROCESSING,
                ProcessingJob.locked_at < stale_before,
            )
            .values(
                status=ProcessingJobStatus.RETRY,
                next_attempt_at=func.now(),
                locked_at=None,
                locked_by=None,
                last_error_code="STALE_LOCK_RECOVERED",
            )
            .returning(ProcessingJob.id)
        )
        result = await self._session.execute(statement)
        return list(result.scalars())

    async def _get_locked(self, job_id: UUID) -> ProcessingJob:
        statement = select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update()
        job = await self._session.scalar(statement)
        if job is None:
            raise LookupError(f"Queue job not found: {job_id}")
        return job
