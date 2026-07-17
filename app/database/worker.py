"""Reusable at-least-once worker runtime for PostgreSQL queue jobs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.downstream import DownstreamJobRepository, DownstreamPhase
from app.database.models import ProcessingJob
from app.database.queue import JobRepository


class JobDisposition(StrEnum):
    """Whether a successful handler leaves or deletes its claimed queue row."""

    COMPLETE = "complete"
    RETAIN = "retain"


JobHandler = Callable[[ProcessingJob, AsyncSession], Awaitable[JobDisposition | None]]
QueueAgeObserver = Callable[[float], None]
DownstreamJobHandler = Callable[[ProcessingJob, AsyncSession], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry schedule from the product specification."""

    delays_seconds: Sequence[int] = (15, 60, 300, 1800)

    def delay_after_attempt(self, attempt_count: int) -> timedelta | None:
        """Return the delay after a failed attempt, or None when retries are exhausted."""
        if attempt_count < 1:
            raise ValueError("attempt_count must be positive")
        index = attempt_count - 1
        if index >= len(self.delays_seconds):
            return None
        return timedelta(seconds=self.delays_seconds[index])


class QueueWorker:
    """Claim and process one job per transaction-owned iteration."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        worker_id: str,
        handler: JobHandler,
        *,
        retry_policy: RetryPolicy | None = None,
        queue_age_observer: QueueAgeObserver | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._worker_id = worker_id
        self._handler = handler
        self._retry_policy = retry_policy or RetryPolicy()
        self._queue_age_observer = queue_age_observer

    async def run_once(self) -> bool:
        """Process at most one job and report whether a job was claimed."""
        async with self._session_factory.begin() as session:
            repository = JobRepository(session)
            if self._queue_age_observer is not None:
                self._queue_age_observer(await repository.oldest_job_age_seconds())
            job = await repository.claim(self._worker_id)
            if job is None:
                return False

            try:
                async with session.begin_nested():
                    disposition = await self._handler(job, session)
            except Exception as error:
                await session.refresh(job)
                retryable = getattr(error, "retryable", True) is not False
                delay = (
                    self._retry_policy.delay_after_attempt(job.attempt_count) if retryable else None
                )
                configured_error_code = getattr(error, "error_code", None)
                error_code = (
                    configured_error_code
                    if isinstance(configured_error_code, str)
                    else type(error).__name__
                )[:100]
                if delay is None:
                    await repository.fail(job.id, error_code)
                else:
                    retry_at = await session.scalar(select(func.now() + delay))
                    if retry_at is None:
                        raise RuntimeError("Database did not return retry time") from error
                    await repository.retry(job.id, error_code, retry_at)
            else:
                if disposition is not JobDisposition.RETAIN:
                    await repository.complete(job.id)
        return True

    async def run_forever(self, poll_interval_seconds: float = 1.0) -> None:
        """Poll continuously while preserving cancellation for graceful shutdown."""
        while True:
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(poll_interval_seconds)


class DownstreamQueueWorker:
    """Run one of the two PostgreSQL-backed downstream phases at least once."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        worker_id: str,
        phase: DownstreamPhase,
        handler: DownstreamJobHandler,
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._worker_id = worker_id
        self._phase = phase
        self._handler = handler
        self._retry_policy = retry_policy or RetryPolicy()

    async def run_once(self) -> bool:
        """Process at most one downstream row for this phase."""
        async with self._session_factory.begin() as session:
            repository = DownstreamJobRepository(session)
            job = await repository.claim(self._worker_id, self._phase)
            if job is None:
                return False
            try:
                async with session.begin_nested():
                    await self._handler(job, session)
            except Exception as error:
                await session.refresh(job)
                retryable = getattr(error, "retryable", True) is not False
                delay = (
                    self._retry_policy.delay_after_attempt(job.attempt_count) if retryable else None
                )
                configured_error_code = getattr(error, "error_code", None)
                error_code = (
                    configured_error_code
                    if isinstance(configured_error_code, str)
                    else type(error).__name__
                )[:100]
                if delay is None:
                    await repository.fail(job.id, error_code)
                else:
                    retry_at = await session.scalar(select(func.now() + delay))
                    if retry_at is None:
                        raise RuntimeError("Database did not return retry time") from error
                    await repository.retry(job.id, error_code, retry_at)
        return True

    async def run_forever(self, poll_interval_seconds: float = 1.0) -> None:
        """Poll continuously while preserving cancellation."""
        while True:
            processed = await self.run_once()
            if not processed:
                await asyncio.sleep(poll_interval_seconds)


async def recover_stale_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    lock_timeout: timedelta,
) -> list[UUID]:
    """Recover locks older than the configured timeout using database time."""
    async with session_factory.begin() as session:
        stale_before = await session.scalar(select(func.now() - lock_timeout))
        if stale_before is None:
            raise RuntimeError("Database did not return stale-lock cutoff")
        return await JobRepository(session).recover_stale(stale_before)
