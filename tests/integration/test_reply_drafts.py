"""Integration coverage for immutable manual reply drafts."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from alembic.config import Config
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.database.models import (
    DetectedQuestion,
    MonitoredChat,
    OperatorSession,
    OutboundCommand,
    ReplyVersion,
)
from app.database.repositories.operator_sessions import OperatorSessionRepository
from app.database.repositories.outbound_commands import OutboundCommandRepository
from app.database.repositories.reply_drafts import (
    DraftUnavailableError,
    ReplyDraftRepository,
)
from app.domain.enums import MonitoredChatStatus, MonitoredChatType, QuestionStatus

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for reply draft integration tests")
    return value


async def _exercise_reply_drafts(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    operator_id = 42
    try:
        async with factory.begin() as session:
            await session.execute(delete(OperatorSession))
            await session.execute(delete(OutboundCommand))
            await session.execute(delete(ReplyVersion))
            await session.execute(delete(DetectedQuestion))
            await session.execute(delete(MonitoredChat))
            chat = MonitoredChat(
                telegram_chat_id=-100700,
                title="Seller <Europe>",
                chat_type=MonitoredChatType.FORUM_SUPERGROUP,
                status=MonitoredChatStatus.ACTIVE,
                added_by_telegram_user_id=operator_id,
            )
            session.add(chat)
            await session.flush()
            question = DetectedQuestion(
                monitored_chat_id=chat.id,
                telegram_chat_id=chat.telegram_chat_id,
                telegram_message_id=701,
                topic_id=11,
                topic_title="Inventory",
                telegram_created_at=datetime.now(UTC),
                original_text="Question",
                category="product",
            )
            session.add(question)
            await session.flush()
            question_id = question.id

        first_text = "First line\n<exact & outgoing>"
        second_text = "Edited text"
        async with factory.begin() as session:
            drafts = ReplyDraftRepository(session)
            sessions = OperatorSessionRepository(session)
            destination = await drafts.open(question_id)
            await sessions.open_question(operator_id, question_id)
            first = await drafts.create_version(question_id, first_text)
            assert destination.chat_title == "Seller <Europe>"
            assert destination.topic_title == "Inventory"
            assert first.text == first_text
            assert first.version_number == 1

        async with factory.begin() as session:
            drafts = ReplyDraftRepository(session)
            await drafts.reopen_for_edit(question_id)
            second = await drafts.create_version(question_id, second_text)
            assert second.version_number == 2
            assert await drafts.cancel(question_id) is True
            await OperatorSessionRepository(session).clear_active_question(operator_id)

        async with factory.begin() as session:
            drafts = ReplyDraftRepository(session)
            with pytest.raises(DraftUnavailableError):
                await drafts.open(question_id)
            with pytest.raises(DraftUnavailableError):
                await drafts.create_version(question_id, "must not send")

        async with factory() as session:
            question_status = await session.scalar(
                select(DetectedQuestion.status).where(DetectedQuestion.id == question_id)
            )
            versions = list(
                (
                    await session.scalars(
                        select(ReplyVersion)
                        .where(ReplyVersion.question_id == question_id)
                        .order_by(ReplyVersion.version_number)
                    )
                ).all()
            )
            command_count = await session.scalar(select(func.count(OutboundCommand.id)))
            active = await OperatorSessionRepository(session).get_active_question(operator_id)
            assert question_status is QuestionStatus.CANCELLED
            assert [(item.version_number, item.text, item.action) for item in versions] == [
                (1, first_text, "draft"),
                (2, second_text, "draft"),
            ]
            assert command_count == 0
            assert active is None
    finally:
        await engine.dispose()


def test_reply_draft_version_edit_cancel_and_no_send() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise_reply_drafts(_database_url()))


async def _exercise_confirmation(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory.begin() as session:
            await session.execute(delete(OperatorSession))
            await session.execute(delete(OutboundCommand))
            await session.execute(delete(ReplyVersion))
            await session.execute(delete(DetectedQuestion))
            await session.execute(delete(MonitoredChat))
            chat = MonitoredChat(
                telegram_chat_id=-100800,
                title="Confirm chat",
                chat_type=MonitoredChatType.SUPERGROUP,
                status=MonitoredChatStatus.ACTIVE,
                added_by_telegram_user_id=42,
            )
            session.add(chat)
            await session.flush()
            question = DetectedQuestion(
                monitored_chat_id=chat.id,
                telegram_chat_id=chat.telegram_chat_id,
                telegram_message_id=801,
                topic_id=15,
                telegram_created_at=datetime.now(UTC),
                original_text="Question",
                category="product",
            )
            session.add(question)
            await session.flush()
            question_id = question.id
            drafts = ReplyDraftRepository(session)
            await drafts.open(question_id)
            preview = await drafts.create_version(question_id, "Exact preview\n<unchanged>")

        async with factory.begin() as session:
            first = await OutboundCommandRepository(session).confirm_send(question_id)
        async with factory.begin() as session:
            repeated = await OutboundCommandRepository(session).confirm_send(question_id)

        assert first.created is True
        assert repeated.created is False
        assert repeated.command_id == first.command_id
        assert first.text == preview.text

        async with factory() as session:
            question_status = await session.scalar(
                select(DetectedQuestion.status).where(DetectedQuestion.id == question_id)
            )
            commands = list((await session.scalars(select(OutboundCommand))).all())
            versions = list(
                (
                    await session.scalars(
                        select(ReplyVersion)
                        .where(ReplyVersion.question_id == question_id)
                        .order_by(ReplyVersion.version_number)
                    )
                ).all()
            )
        assert question_status is QuestionStatus.SEND_REQUESTED
        assert len(commands) == 1
        assert commands[0].text == preview.text
        assert commands[0].reply_version == 2
        assert commands[0].idempotency_key == f"{question_id}:send_reply:2"
        assert [(version.action, version.text) for version in versions] == [
            ("draft", preview.text),
            ("sent", preview.text),
        ]

        with pytest.raises(RuntimeError):
            async with factory.begin() as session:
                rollback_question = await session.get(DetectedQuestion, question_id)
                assert rollback_question is not None
                rollback_question.status = QuestionStatus.WAITING_CONFIRMATION
                await session.execute(delete(OutboundCommand))
                await session.execute(delete(ReplyVersion).where(ReplyVersion.version_number == 2))
                await session.flush()
                await OutboundCommandRepository(session).confirm_send(question_id)
                raise RuntimeError("force transaction rollback")

        async with factory() as session:
            assert await session.scalar(select(func.count(OutboundCommand.id))) == 1
            assert await session.scalar(select(func.count(ReplyVersion.id))) == 2
            assert (
                await session.scalar(
                    select(DetectedQuestion.status).where(DetectedQuestion.id == question_id)
                )
                is QuestionStatus.SEND_REQUESTED
            )
    finally:
        await engine.dispose()


def test_confirm_send_is_atomic_exact_and_idempotent() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise_confirmation(_database_url()))
