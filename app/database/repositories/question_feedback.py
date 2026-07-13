"""Transactional operator feedback for detected questions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DetectedQuestion
from app.domain.enums import QuestionStatus


class QuestionFeedbackUnavailableError(Exception):
    """Raised when feedback cannot change the current question workflow."""


class QuestionFeedbackRepository:
    """Record text-free dismiss feedback under a locked question row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def dismiss(self, question_id: UUID) -> bool:
        """Dismiss a detected question, returning false for an idempotent repeat."""
        question = await self._lock_question(question_id)
        if question.status is QuestionStatus.DISMISSED:
            return False
        if question.status is not QuestionStatus.DETECTED:
            raise QuestionFeedbackUnavailableError
        question.status = QuestionStatus.DISMISSED
        return True

    async def reopen(self, question_id: UUID) -> bool:
        """Explicitly reopen a dismissed question for the operator workflow."""
        question = await self._lock_question(question_id)
        if question.status is QuestionStatus.DETECTED:
            return False
        if question.status is not QuestionStatus.DISMISSED:
            raise QuestionFeedbackUnavailableError
        question.status = QuestionStatus.DETECTED
        return True

    async def _lock_question(self, question_id: UUID) -> DetectedQuestion:
        question = await self._session.scalar(
            select(DetectedQuestion).where(DetectedQuestion.id == question_id).with_for_update()
        )
        if question is None:
            raise QuestionFeedbackUnavailableError
        return question


__all__ = ["QuestionFeedbackRepository", "QuestionFeedbackUnavailableError"]
