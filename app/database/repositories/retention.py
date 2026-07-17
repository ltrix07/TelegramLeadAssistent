"""Bounded PostgreSQL retention cleanup operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.database.models import ClassificationRun, DetectedQuestion, ProcessingJob


@dataclass(frozen=True, slots=True)
class RetentionCleanupResult:
    """Rows removed by one bounded cleanup pass."""

    processing_jobs: int
    detected_questions: int
    classification_runs: int


class RetentionRepository:
    """Delete at most one small batch from each TTL-governed table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def cleanup_once(
        self,
        *,
        temporary_ttl: timedelta,
        relevant_retention: timedelta,
        batch_size: int,
    ) -> RetentionCleanupResult:
        """Delete expired rows using database time and bounded candidate sets."""
        now = func.now()
        processing = await self._delete_batch(
            ProcessingJob,
            ProcessingJob.id,
            or_(
                ProcessingJob.expires_at < now,
                ProcessingJob.created_at < now - temporary_ttl,
            ),
            ProcessingJob.expires_at,
            batch_size,
        )
        questions = await self._delete_batch(
            DetectedQuestion,
            DetectedQuestion.id,
            or_(
                DetectedQuestion.expires_at < now,
                DetectedQuestion.detected_at < now - relevant_retention,
            ),
            DetectedQuestion.expires_at,
            batch_size,
        )
        classification = await self._delete_batch(
            ClassificationRun,
            ClassificationRun.id,
            ClassificationRun.created_at < now - relevant_retention,
            ClassificationRun.created_at,
            batch_size,
        )
        return RetentionCleanupResult(processing, questions, classification)

    async def _delete_batch(
        self,
        model: type[Any],
        id_column: InstrumentedAttribute[Any],
        expiry_condition: ColumnElement[bool],
        order_column: InstrumentedAttribute[Any],
        batch_size: int,
    ) -> int:
        candidates = (
            select(id_column)
            .where(expiry_condition)
            .order_by(order_column, id_column)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(
            delete(model).where(id_column.in_(candidates)).returning(id_column)
        )
        return len(result.scalars().all())
