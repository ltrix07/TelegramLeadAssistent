"""Integration coverage for the listener-owned outbound reply worker."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.database.models import DetectedQuestion, MonitoredChat, OutboundCommand, ReplyVersion
from app.database.repositories.outbound_commands import (
    OutboundCommandRepository,
    OutboundRetryUnavailableError,
)
from app.database.repositories.reply_drafts import ReplyDraftRepository
from app.domain.enums import (
    MonitoredChatStatus,
    MonitoredChatType,
    OutboundCommandStatus,
    QuestionStatus,
)
from app.domain.errors import TelegramErrorCode, TelegramFailureKind, TelegramOutboundError
from app.listener.mtproto import (
    ChatVerificationOutcome,
    ChatVerificationResult,
    ChatVerificationTransientError,
)
from app.listener.outbound import EditReplyWorker, SendReplyWorker
from app.listener.reply_chain import ReplyMessage

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for send worker integration tests")
    return value


class FakeOutboundClient:
    def __init__(
        self,
        *,
        chat_id: int,
        message_id: int,
        topic_id: int | None,
        verification: ChatVerificationOutcome = ChatVerificationOutcome.ACTIVE,
        target_exists: bool = True,
        send_error: TelegramOutboundError | None = None,
        verification_error: bool = False,
    ) -> None:
        self.chat_id = chat_id
        self.message_id = message_id
        self.topic_id = topic_id
        self.verification = verification
        self.target_exists = target_exists
        self.send_error = send_error
        self.verification_error = verification_error
        self.send_calls: list[tuple[int, int, str]] = []
        self.edit_calls: list[tuple[int, int, str]] = []

    async def verify_chat(self, telegram_chat_id: int) -> ChatVerificationResult:
        assert telegram_chat_id == self.chat_id
        if self.verification_error:
            raise ChatVerificationTransientError
        return ChatVerificationResult(self.verification, is_forum=True)

    async def get_reply_message(
        self, telegram_chat_id: int, telegram_message_id: int
    ) -> ReplyMessage | None:
        if not self.target_exists:
            return None
        return ReplyMessage(
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            reply_to_message_id=None,
            topic_id=self.topic_id,
            reply_to_top_message_id=self.topic_id,
            author_telegram_id=1,
            author_display_name=None,
            telegram_created_at=datetime.now(UTC),
            text="target",
        )

    async def send_reply(self, telegram_chat_id: int, telegram_message_id: int, text: str) -> int:
        self.send_calls.append((telegram_chat_id, telegram_message_id, text))
        if self.send_error is not None:
            raise self.send_error
        await asyncio.sleep(0)
        return 9901

    async def edit_message(
        self, telegram_chat_id: int, telegram_message_id: int, text: str
    ) -> None:
        self.edit_calls.append((telegram_chat_id, telegram_message_id, text))
        if self.send_error is not None:
            raise self.send_error

    async def connect(self) -> None: ...
    async def is_user_authorized(self) -> bool:
        return True

    def add_new_message_handler(self, handler: Callable[[Any], Awaitable[None]]) -> None: ...
    async def run_until_disconnected(self) -> None: ...
    async def disconnect(self) -> None: ...


async def _exercise_send_worker(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chat_id = -1008802
    message_id = 802
    topic_id = 88
    text = "Exact confirmed reply"
    try:
        async with factory.begin() as session:
            await session.execute(delete(OutboundCommand))
            existing_chat = await session.scalar(
                select(MonitoredChat).where(MonitoredChat.telegram_chat_id == chat_id)
            )
            if existing_chat is not None:
                await session.execute(
                    delete(OutboundCommand).where(
                        OutboundCommand.question_id.in_(
                            select(DetectedQuestion.id).where(
                                DetectedQuestion.monitored_chat_id == existing_chat.id
                            )
                        )
                    )
                )
                await session.execute(
                    delete(DetectedQuestion).where(
                        DetectedQuestion.monitored_chat_id == existing_chat.id
                    )
                )
                await session.delete(existing_chat)
            chat = MonitoredChat(
                telegram_chat_id=chat_id,
                title="Forum",
                chat_type=MonitoredChatType.FORUM_SUPERGROUP,
                status=MonitoredChatStatus.ACTIVE,
                added_by_telegram_user_id=42,
            )
            session.add(chat)
            await session.flush()
            question = DetectedQuestion(
                monitored_chat_id=chat.id,
                telegram_chat_id=chat_id,
                telegram_message_id=message_id,
                topic_id=topic_id,
                topic_title="Sales",
                telegram_created_at=datetime.now(UTC),
                original_text="Question",
                category="product",
            )
            session.add(question)
            await session.flush()
            question_id = question.id
            await ReplyDraftRepository(session).open(question_id)
            await ReplyDraftRepository(session).create_version(question_id, text)
            await OutboundCommandRepository(session).confirm_send(question_id)

        client = FakeOutboundClient(chat_id=chat_id, message_id=message_id, topic_id=topic_id)
        workers = (
            SendReplyWorker(factory, client, worker_id="listener-a"),
            SendReplyWorker(factory, client, worker_id="listener-b"),
        )
        results = await asyncio.gather(*(worker.run_once() for worker in workers))
        assert sorted(results) == [False, True]
        assert client.send_calls == [(chat_id, message_id, text)]

        assert await workers[0].run_once() is False
        assert client.send_calls == [(chat_id, message_id, text)]

        async with factory() as session:
            stored = await session.scalar(
                select(OutboundCommand).where(OutboundCommand.question_id == question_id)
            )
            question_status = await session.scalar(
                select(DetectedQuestion.status).where(DetectedQuestion.id == question_id)
            )
            assert stored is not None
            assert stored.status is OutboundCommandStatus.SUCCEEDED
            assert stored.sent_message_id == 9901
            assert stored.attempt_count == 1
            assert stored.locked_at is None
            assert stored.locked_by is None
            assert stored.completed_at is not None
            assert question_status is QuestionStatus.SENT
    finally:
        await engine.dispose()


def test_send_reply_targets_question_topic_and_is_idempotent() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise_send_worker(_database_url()))


async def _exercise_edit_worker(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    chat_id = -1008812
    source_message_id = 812
    try:
        async with factory.begin() as session:
            await session.execute(delete(OutboundCommand))
            await session.execute(delete(DetectedQuestion))
            await session.execute(delete(MonitoredChat))
            chat = MonitoredChat(
                telegram_chat_id=chat_id,
                title="Edit flow",
                chat_type=MonitoredChatType.SUPERGROUP,
                status=MonitoredChatStatus.ACTIVE,
                added_by_telegram_user_id=42,
            )
            session.add(chat)
            await session.flush()
            question = DetectedQuestion(
                monitored_chat_id=chat.id,
                telegram_chat_id=chat_id,
                telegram_message_id=source_message_id,
                telegram_created_at=datetime.now(UTC),
                original_text="Original question",
                category="product",
            )
            session.add(question)
            await session.flush()
            question_id = question.id
            await ReplyDraftRepository(session).open(question_id)
            await ReplyDraftRepository(session).create_version(question_id, "Previous final")
            await OutboundCommandRepository(session).confirm_send(question_id)

        client = FakeOutboundClient(chat_id=chat_id, message_id=source_message_id, topic_id=None)
        assert await SendReplyWorker(factory, client).run_once() is True

        async with factory.begin() as session:
            repository = OutboundCommandRepository(session)
            preview = await repository.prepare_edit(question_id, "Edited final")
            assert (preview.old_text, preview.new_text) == ("Previous final", "Edited final")
            first = await repository.confirm_edit(question_id)
            duplicate = await repository.confirm_edit(question_id)
            assert first.command_id == duplicate.command_id
            assert first.created is True
            assert duplicate.created is False

        assert await EditReplyWorker(factory, client).run_once() is True
        assert client.edit_calls == [(chat_id, 9901, "Edited final")]
        assert all(call[1] != source_message_id for call in client.edit_calls)

        async with factory.begin() as session:
            repository = OutboundCommandRepository(session)
            await repository.prepare_edit(question_id, "Failed replacement")
            failed = await repository.confirm_edit(question_id)

        client.send_error = TelegramOutboundError(
            TelegramErrorCode.CHAT_WRITE_FORBIDDEN, TelegramFailureKind.PERMANENT
        )
        assert await EditReplyWorker(factory, client).run_once() is True

        async with factory() as session:
            failed_command = await session.get(OutboundCommand, failed.command_id)
            final = await session.scalar(
                select(ReplyVersion)
                .where(
                    ReplyVersion.question_id == question_id,
                    ReplyVersion.action.in_(("sent", "edited")),
                )
                .order_by(ReplyVersion.version_number.desc())
                .limit(1)
            )
            status = await session.scalar(
                select(DetectedQuestion.status).where(DetectedQuestion.id == question_id)
            )
            assert failed_command is not None
            assert failed_command.status is OutboundCommandStatus.FAILED
            assert final is not None
            assert final.text == "Edited final"
            assert final.action == "edited"
            assert status is QuestionStatus.SENT
    finally:
        await engine.dispose()


def test_edit_reply_uses_stored_sent_id_is_idempotent_and_preserves_final_on_failure() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise_edit_worker(_database_url()))


async def _seed_command(
    factory: async_sessionmaker[Any], *, chat_id: int, message_id: int
) -> tuple[Any, Any]:
    async with factory.begin() as session:
        chat = MonitoredChat(
            telegram_chat_id=chat_id,
            title="Failures",
            chat_type=MonitoredChatType.SUPERGROUP,
            status=MonitoredChatStatus.ACTIVE,
            added_by_telegram_user_id=42,
        )
        session.add(chat)
        await session.flush()
        question = DetectedQuestion(
            monitored_chat_id=chat.id,
            telegram_chat_id=chat_id,
            telegram_message_id=message_id,
            telegram_created_at=datetime.now(UTC),
            original_text="Question",
            category="product",
        )
        session.add(question)
        await session.flush()
        await ReplyDraftRepository(session).open(question.id)
        await ReplyDraftRepository(session).create_version(question.id, "Reply")
        result = await OutboundCommandRepository(session).confirm_send(question.id)
        return question.id, result.command_id


async def _exercise_normalized_failures(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory.begin() as session:
            await session.execute(delete(OutboundCommand))
            await session.execute(delete(DetectedQuestion))
            await session.execute(delete(MonitoredChat))

        cases = (
            (
                -1009101,
                FakeOutboundClient(
                    chat_id=-1009101, message_id=901, topic_id=None, target_exists=False
                ),
                OutboundCommandStatus.FAILED,
                TelegramErrorCode.SOURCE_MESSAGE_DELETED,
                None,
            ),
            (
                -1009102,
                FakeOutboundClient(
                    chat_id=-1009102,
                    message_id=902,
                    topic_id=None,
                    verification=ChatVerificationOutcome.READ_ONLY,
                ),
                OutboundCommandStatus.FAILED,
                TelegramErrorCode.CHAT_WRITE_FORBIDDEN,
                None,
            ),
            (
                -1009103,
                FakeOutboundClient(
                    chat_id=-1009103,
                    message_id=903,
                    topic_id=None,
                    send_error=TelegramOutboundError(
                        TelegramErrorCode.FLOOD_WAIT,
                        TelegramFailureKind.TEMPORARY,
                        retry_after_seconds=42,
                    ),
                ),
                OutboundCommandStatus.PENDING,
                TelegramErrorCode.FLOOD_WAIT,
                42,
            ),
            (
                -1009105,
                FakeOutboundClient(
                    chat_id=-1009105,
                    message_id=905,
                    topic_id=None,
                    verification_error=True,
                ),
                OutboundCommandStatus.PENDING,
                TelegramErrorCode.UNKNOWN_ERROR,
                15,
            ),
            (
                -1009104,
                FakeOutboundClient(
                    chat_id=-1009104,
                    message_id=904,
                    topic_id=None,
                    send_error=TelegramOutboundError(
                        TelegramErrorCode.UNKNOWN_ERROR, TelegramFailureKind.AMBIGUOUS
                    ),
                ),
                OutboundCommandStatus.NEEDS_REVIEW,
                TelegramErrorCode.UNKNOWN_ERROR,
                None,
            ),
        )
        command_ids: list[Any] = []
        for offset, (
            chat_id,
            client,
            expected_status,
            expected_code,
            expected_delay,
        ) in enumerate(cases, 901):
            question_id, command_id = await _seed_command(
                factory, chat_id=chat_id, message_id=offset
            )
            command_ids.append(command_id)
            assert await SendReplyWorker(factory, client).run_once() is True
            async with factory() as session:
                stored = await session.get(OutboundCommand, command_id)
                assert stored is not None
                assert stored.status is expected_status
                assert stored.last_error_code == expected_code.value
                assert stored.locked_at is None
                assert stored.locked_by is None
                question_status = await session.scalar(
                    select(DetectedQuestion.status).where(DetectedQuestion.id == question_id)
                )
                if expected_status is OutboundCommandStatus.PENDING:
                    database_now = await session.scalar(select(func.now()))
                    assert database_now is not None
                    delay = (stored.next_attempt_at - database_now).total_seconds()
                    assert expected_delay is not None
                    assert expected_delay - 1 <= delay <= expected_delay
                    assert question_status is QuestionStatus.SEND_REQUESTED
                else:
                    assert question_status is QuestionStatus.SEND_FAILED
        assert cases[-1][1].send_calls == [(-1009104, 905, "Reply")]

        async with factory.begin() as session:
            repository = OutboundCommandRepository(session)
            failures = await repository.list_failures()
            assert {failure.command_id for failure in failures} == set(command_ids)
            by_id = {failure.command_id: failure for failure in failures}
            assert by_id[command_ids[2]].error_code == "FLOOD_WAIT"
            assert by_id[command_ids[2]].retry_allowed is False
            assert by_id[command_ids[4]].status is OutboundCommandStatus.NEEDS_REVIEW
            assert by_id[command_ids[4]].retry_allowed is False
            with pytest.raises(OutboundRetryUnavailableError):
                await repository.retry_failed(command_ids[2])
            with pytest.raises(OutboundRetryUnavailableError):
                await repository.retry_failed(command_ids[4])

        async with factory.begin() as session:
            safe_edit = await session.get(OutboundCommand, command_ids[0])
            assert safe_edit is not None
            safe_edit.command_type = "edit_reply"
            safe_edit.sent_message_id = 9901
            safe_edit.last_error_code = "UNKNOWN_ERROR"

        async with factory.begin() as session:
            repository = OutboundCommandRepository(session)
            failures = await repository.list_failures()
            safe_failure = next(item for item in failures if item.command_id == command_ids[0])
            assert safe_failure.retry_allowed is True
            await repository.retry_failed(command_ids[0])

        async with factory() as session:
            retried = await session.get(OutboundCommand, command_ids[0])
            assert retried is not None
            assert retried.status is OutboundCommandStatus.PENDING
    finally:
        await engine.dispose()


def test_send_reply_normalizes_permanent_flood_wait_and_ambiguous_errors() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    asyncio.run(_exercise_normalized_failures(_database_url()))
