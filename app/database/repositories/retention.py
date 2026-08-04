"""Bounded PostgreSQL retention cleanup operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.database.models import (
    ClassificationRun,
    DetectedQuestion,
    ProcessingJob,
    RecentMessageFingerprint,
)


@dataclass(frozen=True, slots=True)
class RetentionCleanupResult:
    """Rows removed by one bounded cleanup pass."""

    processing_jobs: int
    detected_questions: int
    classification_runs: int
    message_fingerprints: int


class RetentionRepository:
    """Delete at most one small batch from each TTL-governed table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def cleanup_once(
        self,
        *,
        temporary_ttl: timedelta,
        relevant_retention: timedelta,
        fingerprint_ttl: timedelta,
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
        fingerprints = await self._delete_batch(
            RecentMessageFingerprint,
            (RecentMessageFingerprint.telegram_chat_id, RecentMessageFingerprint.fingerprint),
            RecentMessageFingerprint.last_seen_at < now - fingerprint_ttl,
            RecentMessageFingerprint.last_seen_at,
            batch_size,
        )
        return RetentionCleanupResult(processing, questions, classification, fingerprints)

    async def _delete_batch(
        self,
        model: type[Any],
        id_column: InstrumentedAttribute[Any]
        | tuple[InstrumentedAttribute[Any], InstrumentedAttribute[Any]],
        expiry_condition: ColumnElement[bool],
        order_column: InstrumentedAttribute[Any],
        batch_size: int,
    ) -> int:
        id_columns = id_column if isinstance(id_column, tuple) else (id_column,)
        candidates = (
            select(*id_columns)
            .where(expiry_condition)
            .order_by(order_column, *id_columns)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        identity = id_columns[0] if len(id_columns) == 1 else tuple_(*id_columns)
        result = await self._session.execute(
            delete(model).where(identity.in_(candidates)).returning(*id_columns)
        )
        return len(result.scalars().all())
