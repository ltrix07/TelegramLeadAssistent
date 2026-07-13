"""Transactional persistence for operator-authored reply drafts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DetectedQuestion, MonitoredChat, ReplyVersion
from app.domain.enums import QuestionStatus


class DraftUnavailableError(Exception):
    """Raised when a question cannot participate in draft composition."""


@dataclass(frozen=True, slots=True)
class DraftDestination:
    """Question destination displayed alongside an exact draft preview."""

    question_id: UUID
    chat_title: str
    topic_title: str | None


@dataclass(frozen=True, slots=True)
class StoredDraft:
    """One immutable stored reply version and its destination."""

    destination: DraftDestination
    version_number: int
    text: str


class ReplyDraftRepository:
    """Create immutable draft versions under a locked question row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def open(self, question_id: UUID) -> DraftDestination:
        question = await self._lock_question(question_id)
        if question.status not in {
            QuestionStatus.DETECTED,
            QuestionStatus.WAITING_FOR_DRAFT,
            QuestionStatus.WAITING_CONFIRMATION,
        }:
            raise DraftUnavailableError
        question.status = QuestionStatus.WAITING_FOR_DRAFT
        return await self._destination(question)

    async def create_version(self, question_id: UUID, text: str) -> StoredDraft:
        question = await self._lock_question(question_id)
        if question.status is not QuestionStatus.WAITING_FOR_DRAFT:
            raise DraftUnavailableError
        latest = await self._session.scalar(
            select(func.max(ReplyVersion.version_number)).where(
                ReplyVersion.question_id == question_id
            )
        )
        version_number = (latest or 0) + 1
        self._session.add(
            ReplyVersion(
                question_id=question_id,
                version_number=version_number,
                text=text,
                action="draft",
            )
        )
        question.status = QuestionStatus.WAITING_CONFIRMATION
        await self._session.flush()
        return StoredDraft(await self._destination(question), version_number, text)

    async def reopen_for_edit(self, question_id: UUID) -> None:
        question = await self._lock_question(question_id)
        if question.status is not QuestionStatus.WAITING_CONFIRMATION:
            raise DraftUnavailableError
        question.status = QuestionStatus.WAITING_FOR_DRAFT

    async def cancel(self, question_id: UUID) -> bool:
        question = await self._lock_question(question_id)
        if question.status is QuestionStatus.CANCELLED:
            return False
        if question.status not in {
            QuestionStatus.WAITING_FOR_DRAFT,
            QuestionStatus.WAITING_CONFIRMATION,
        }:
            raise DraftUnavailableError
        question.status = QuestionStatus.CANCELLED
        return True

    async def latest(self, question_id: UUID) -> StoredDraft | None:
        question = await self._lock_question(question_id)
        version = await self._session.scalar(
            select(ReplyVersion)
            .where(ReplyVersion.question_id == question_id)
            .order_by(ReplyVersion.version_number.desc())
            .limit(1)
        )
        if version is None:
            return None
        return StoredDraft(await self._destination(question), version.version_number, version.text)

    async def _lock_question(self, question_id: UUID) -> DetectedQuestion:
        question = await self._session.scalar(
            select(DetectedQuestion).where(DetectedQuestion.id == question_id).with_for_update()
        )
        if question is None:
            raise DraftUnavailableError
        return question

    async def _destination(self, question: DetectedQuestion) -> DraftDestination:
        chat_title = await self._session.scalar(
            select(MonitoredChat.title).where(MonitoredChat.id == question.monitored_chat_id)
        )
        if chat_title is None:
            raise DraftUnavailableError
        return DraftDestination(question.id, chat_title, question.topic_title)


__all__ = [
    "DraftDestination",
    "DraftUnavailableError",
    "ReplyDraftRepository",
    "StoredDraft",
]
