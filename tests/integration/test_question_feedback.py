"""Integration coverage for idempotent dismiss and explicit reopen feedback."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from alembic.config import Config
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.database.models import DetectedQuestion, MonitoredChat, OutboundCommand, ReplyVersion
from app.database.repositories.question_feedback import QuestionFeedbackRepository
from app.database.repositories.reply_drafts import DraftUnavailableError, ReplyDraftRepository
from app.domain.enums import MonitoredChatStatus, MonitoredChatType, QuestionStatus

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for question feedback integration tests")
    return value


async def _exercise_question_feedback(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory.begin() as session:
            await session.execute(delete(OutboundCommand))
            await session.execute(delete(ReplyVersion))
            await session.execute(delete(DetectedQuestion))
            await session.execute(delete(MonitoredChat))
            chat = MonitoredChat(
                telegram_chat_id=-100705,
                title="Feedback group",
                chat_type=MonitoredChatType.SUPERGROUP,
                status=MonitoredChatStatus.ACTIVE,
                added_by_telegram_user_id=42,
            )
            session.add(chat)
            await session.flush()
            question = DetectedQuestion(
                monitored_chat_id=chat.id,
                telegram_chat_id=chat.telegram_chat_id,
                telegram_message_id=706,
                telegram_created_at=datetime.now(UTC),
                original_text="Retained once under the existing 60-day policy",
                category="other",
            )
            session.add(question)
            await session.flush()
            question_id = question.id

        async with factory.begin() as session:
            feedback = QuestionFeedbackRepository(session)
            assert await feedback.dismiss(question_id) is True
            assert await feedback.dismiss(question_id) is False

        async with factory.begin() as session:
            with pytest.raises(DraftUnavailableError):
                await ReplyDraftRepository(session).open(question_id)

        async with factory.begin() as session:
            feedback = QuestionFeedbackRepository(session)
            assert await feedback.reopen(question_id) is True
            assert await feedback.reopen(question_id) is False
            await ReplyDraftRepository(session).open(question_id)

        async with factory() as session:
            stored_question = await session.get(DetectedQuestion, question_id)
            assert stored_question is not None
            assert stored_question.status is QuestionStatus.WAITING_FOR_DRAFT
            assert stored_question.original_text == "Retained once under the existing 60-day policy"
            assert await session.scalar(select(func.count(ReplyVersion.id))) == 0
            assert await session.scalar(select(func.count(OutboundCommand.id))) == 0
    finally:
        await engine.dispose()


def test_dismiss_is_idempotent_and_requires_explicit_reopen() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise_question_feedback(_database_url()))
