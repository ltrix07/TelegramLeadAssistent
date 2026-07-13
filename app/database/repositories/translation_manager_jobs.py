"""PostgreSQL queue operations for translation control jobs."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TranslationManagerJob
from app.domain.enums import TranslationManagerAction, TranslationManagerJobStatus


class TranslationManagerJobRepository:
    """Claim and finish manager jobs in caller-owned transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self, action: TranslationManagerAction, language_code: str | None = None
    ) -> TranslationManagerJob:
        """Create a typed control-plane request for asynchronous processing."""
        created_at = await self._session.scalar(func.clock_timestamp())
        job = TranslationManagerJob(
            action=action,
            language_code=language_code,
            created_at=created_at,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def list_recent(self) -> list[TranslationManagerJob]:
        """List manager jobs newest first for operator status rendering."""
        rows = await self._session.scalars(
            select(TranslationManagerJob).order_by(
                TranslationManagerJob.created_at.desc(), TranslationManagerJob.id.desc()
            )
        )
        return list(rows)

    async def claim(self) -> TranslationManagerJob | None:
        """Claim the oldest pending job without blocking another manager."""
        job = await self._session.scalar(
            select(TranslationManagerJob)
            .where(TranslationManagerJob.status == TranslationManagerJobStatus.PENDING)
            .order_by(TranslationManagerJob.created_at, TranslationManagerJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is not None:
            job.status = TranslationManagerJobStatus.PROCESSING
            await self._session.flush()
        return job

    async def finish(self, job: TranslationManagerJob, result_code: str | None = None) -> None:
        """Persist a safe terminal result without command output."""
        job.status = (
            TranslationManagerJobStatus.SUCCEEDED
            if result_code is None
            else TranslationManagerJobStatus.FAILED
        )
        job.result_code = result_code
        job.completed_at = await self._session.scalar(select(func.now()))
        await self._session.flush()
