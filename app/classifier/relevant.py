"""Transactional persistence for a classified relevant question."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    BotNotification,
    ClassificationRun,
    DetectedQuestion,
    ProcessingJob,
    QuestionChainMessage,
)
from app.database.queue import JobRepository
from app.domain.enums import ProcessingJobStatus
from app.listener.reply_chain import ReplyChain
from app.translation.client import (
    TranslationResult,
    TranslationService,
    TranslationStatus,
)


class RelevantQuestionPersistenceError(RuntimeError):
    """Reject persistence when the durable classification route is invalid."""


class RelevantQuestionPersistenceService:
    """Persist all durable relevant-question state in the caller's transaction."""

    def __init__(
        self,
        operator_telegram_user_id: int,
        *,
        translation_service: TranslationService | None = None,
        translation_enabled: bool = False,
    ) -> None:
        if operator_telegram_user_id <= 0:
            raise ValueError("operator_telegram_user_id must be positive")
        self._operator_telegram_user_id = operator_telegram_user_id
        if translation_enabled and translation_service is None:
            raise ValueError("translation_service is required when translation is enabled")
        self._translation_service = translation_service
        self._translation_enabled = translation_enabled

    async def persist(
        self,
        job: ProcessingJob,
        chain: ReplyChain,
        session: AsyncSession,
    ) -> UUID:
        """Create one question, chain snapshot and notification, then remove the job."""
        if job.status is not ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING:
            raise RelevantQuestionPersistenceError("Job is not awaiting relevant processing")
        if chain.chat_id != job.telegram_chat_id:
            raise RelevantQuestionPersistenceError("Reply chain belongs to another chat")

        existing_id = await session.scalar(
            select(DetectedQuestion.id).where(
                DetectedQuestion.telegram_chat_id == job.telegram_chat_id,
                DetectedQuestion.telegram_message_id == job.telegram_message_id,
            )
        )
        if existing_id is not None:
            await JobRepository(session).complete(job.id)
            return existing_id

        classification = await session.scalar(
            select(ClassificationRun)
            .where(
                ClassificationRun.telegram_chat_id == job.telegram_chat_id,
                ClassificationRun.telegram_message_id == job.telegram_message_id,
                ClassificationRun.result == "relevant",
            )
            .order_by(ClassificationRun.stage.desc())
            .limit(1)
        )
        if classification is None:
            raise RelevantQuestionPersistenceError("Final relevant classification is missing")

        target_items = [item for item in chain.items if item.is_target]
        if len(target_items) != 1 or target_items[0].telegram_message_id != job.telegram_message_id:
            raise RelevantQuestionPersistenceError("Reply chain does not identify the target job")

        available_items = [item for item in chain.items if not item.is_unavailable]
        translations = [
            await self._translate(item.text) for item in available_items if item.text is not None
        ]
        if len(translations) != len(available_items):
            raise RelevantQuestionPersistenceError("Available chain message is incomplete")
        target_translation = translations[available_items.index(target_items[0])]

        question = DetectedQuestion(
            monitored_chat_id=job.monitored_chat_id,
            telegram_chat_id=job.telegram_chat_id,
            telegram_message_id=job.telegram_message_id,
            topic_id=chain.topic_id if chain.topic_id is not None else job.topic_id,
            topic_title=chain.topic_title,
            author_telegram_id=job.sender_telegram_id,
            author_display_name=job.sender_display_name,
            telegram_created_at=job.telegram_created_at,
            original_text=job.message_text,
            translated_text=target_translation.translated_text,
            source_language=target_translation.source_language,
            category=classification.category,
            confidence=classification.confidence,
        )
        session.add(question)
        await session.flush()

        for position, (item, translation) in enumerate(zip(available_items, translations)):
            if item.text is None or item.telegram_created_at is None:
                raise RelevantQuestionPersistenceError("Available chain message is incomplete")
            session.add(
                QuestionChainMessage(
                    question_id=question.id,
                    position=position,
                    telegram_message_id=item.telegram_message_id,
                    reply_to_message_id=item.reply_to_message_id,
                    author_telegram_id=item.author_telegram_id,
                    author_display_name=item.author_display_name,
                    telegram_created_at=item.telegram_created_at,
                    original_text=item.text,
                    translated_text=translation.translated_text,
                    source_language=translation.source_language,
                    translation_status=translation.status.value,
                    is_target=item.is_target,
                )
            )

        session.add(
            BotNotification(
                question_id=question.id,
                operator_telegram_user_id=self._operator_telegram_user_id,
                bot_chat_id=self._operator_telegram_user_id,
            )
        )
        await JobRepository(session).complete(job.id)
        await session.flush()
        return question.id

    async def _translate(self, text: str | None) -> TranslationResult:
        if text is None:
            raise RelevantQuestionPersistenceError("Available chain message is incomplete")
        if not self._translation_enabled:
            return TranslationResult(text, None, None, TranslationStatus.DISABLED)

        assert self._translation_service is not None
        try:
            source_language = await self._translation_service.detect_language(text)
            return await self._translation_service.translate_to_russian(text, source_language)
        except Exception:
            return TranslationResult(
                text,
                None,
                None,
                TranslationStatus.FAILED,
                "unexpected_translation_error",
            )


__all__ = ["RelevantQuestionPersistenceError", "RelevantQuestionPersistenceService"]
