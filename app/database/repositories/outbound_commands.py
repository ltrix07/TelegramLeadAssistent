"""Transactional creation of idempotent outbound Telegram commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import DetectedQuestion, MonitoredChat, OutboundCommand, ReplyVersion
from app.domain.enums import MonitoredChatStatus, OutboundCommandStatus, QuestionStatus


class ConfirmationUnavailableError(Exception):
    """Raised when a question has no confirmable reply preview."""


@dataclass(frozen=True, slots=True)
class ConfirmedCommand:
    """Stable result returned for both initial and repeated confirmations."""

    command_id: UUID
    reply_version: int
    text: str
    created: bool


@dataclass(frozen=True, slots=True)
class SentEditPreview:
    """Durable old/new text pair shown before an edit is confirmed."""

    question_id: UUID
    old_text: str
    new_text: str


@dataclass(frozen=True, slots=True)
class OutboundFailure:
    """Privacy-safe outbound failure data required by the operator UI."""

    command_id: UUID
    command_type: str
    status: OutboundCommandStatus
    error_code: str
    next_attempt_at: datetime
    telegram_chat_id: int
    source_message_id: int
    topic_id: int | None
    sent_message_id: int | None
    chat_username: str | None
    retry_allowed: bool


class OutboundRetryUnavailableError(Exception):
    """Raised when a manual retry would be unsafe or bypass a retry delay."""


class OutboundCommandRepository:
    """Atomically finalize a preview and enqueue its send command."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def request_chat_verification(self, telegram_chat_id: int) -> bool:
        """Schedule a prompt access check after a relevant outbound error."""
        changed_id = await self._session.scalar(
            update(MonitoredChat)
            .where(
                MonitoredChat.telegram_chat_id == telegram_chat_id,
                MonitoredChat.status != MonitoredChatStatus.DISABLED,
            )
            .values(next_verification_at=func.now(), updated_at=func.now())
            .returning(MonitoredChat.id)
        )
        return changed_id is not None

    async def recover_stale(self, stale_before: datetime) -> list[UUID]:
        """Move ambiguous expired outbound claims to manual review exactly once."""
        statement = (
            update(OutboundCommand)
            .where(
                OutboundCommand.status == OutboundCommandStatus.PROCESSING,
                OutboundCommand.locked_at < stale_before,
            )
            .values(
                status=OutboundCommandStatus.NEEDS_REVIEW,
                locked_at=None,
                locked_by=None,
                last_error_code="STALE_LOCK_RECOVERED",
                last_error_message="STALE_LOCK_RECOVERED",
            )
            .returning(
                OutboundCommand.id, OutboundCommand.question_id, OutboundCommand.command_type
            )
        )
        recovered = list((await self._session.execute(statement)).tuples())
        send_question_ids = [
            question_id
            for _, question_id, command_type in recovered
            if command_type == "send_reply"
        ]
        if send_question_ids:
            await self._session.execute(
                update(DetectedQuestion)
                .where(DetectedQuestion.id.in_(send_question_ids))
                .values(status=QuestionStatus.SEND_FAILED, updated_at=func.now())
            )
        return [command_id for command_id, _, _ in recovered]

    async def list_failures(self, *, limit: int = 50) -> tuple[OutboundFailure, ...]:
        """List current failures without exposing stored reply text or raw errors."""
        rows = await self._session.execute(
            select(OutboundCommand, MonitoredChat.username)
            .join(DetectedQuestion, DetectedQuestion.id == OutboundCommand.question_id)
            .join(MonitoredChat, MonitoredChat.id == DetectedQuestion.monitored_chat_id)
            .where(
                (OutboundCommand.status == OutboundCommandStatus.FAILED)
                | (OutboundCommand.status == OutboundCommandStatus.NEEDS_REVIEW)
                | (
                    (OutboundCommand.status == OutboundCommandStatus.PENDING)
                    & OutboundCommand.last_error_code.is_not(None)
                )
            )
            .order_by(OutboundCommand.created_at.desc())
            .limit(limit)
        )
        return tuple(
            OutboundFailure(
                command_id=command.id,
                command_type=command.command_type,
                status=command.status,
                error_code=command.last_error_code or "UNKNOWN_ERROR",
                next_attempt_at=command.next_attempt_at,
                telegram_chat_id=command.telegram_chat_id,
                source_message_id=command.source_message_id,
                topic_id=command.topic_id,
                sent_message_id=command.sent_message_id,
                chat_username=chat_username,
                retry_allowed=self._manual_retry_allowed(command),
            )
            for command, chat_username in rows.all()
        )

    async def retry_failed(self, command_id: UUID) -> None:
        """Requeue only a demonstrably idempotent failed edit."""
        command = await self._session.scalar(
            select(OutboundCommand).where(OutboundCommand.id == command_id).with_for_update()
        )
        if command is None or not self._manual_retry_allowed(command):
            raise OutboundRetryUnavailableError
        command.status = OutboundCommandStatus.PENDING
        command.next_attempt_at = cast(datetime, await self._session.scalar(select(func.now())))
        command.locked_at = None
        command.locked_by = None
        await self._session.flush()

    @staticmethod
    def _manual_retry_allowed(command: OutboundCommand) -> bool:
        return (
            command.status is OutboundCommandStatus.FAILED
            and command.command_type == "edit_reply"
            and command.sent_message_id is not None
            and command.last_error_code == "UNKNOWN_ERROR"
        )

    async def claim_send(self, worker_id: str) -> OutboundCommand | None:
        """Lock and claim the oldest due send command without blocking peers."""
        command = await self._session.scalar(
            select(OutboundCommand)
            .options(selectinload(OutboundCommand.question))
            .where(
                OutboundCommand.command_type == "send_reply",
                OutboundCommand.status == OutboundCommandStatus.PENDING,
                OutboundCommand.next_attempt_at <= func.now(),
            )
            .order_by(OutboundCommand.next_attempt_at, OutboundCommand.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if command is not None:
            command.status = OutboundCommandStatus.PROCESSING
            command.attempt_count += 1
            command.locked_at = cast(datetime, await self._session.scalar(select(func.now())))
            command.locked_by = worker_id
            await self._session.flush()
        return command

    async def claim_edit(self, worker_id: str) -> OutboundCommand | None:
        """Lock and claim the oldest due edit command without blocking peers."""
        command = await self._session.scalar(
            select(OutboundCommand)
            .options(selectinload(OutboundCommand.question))
            .where(
                OutboundCommand.command_type == "edit_reply",
                OutboundCommand.status == OutboundCommandStatus.PENDING,
                OutboundCommand.next_attempt_at <= func.now(),
            )
            .order_by(OutboundCommand.next_attempt_at, OutboundCommand.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if command is not None:
            command.status = OutboundCommandStatus.PROCESSING
            command.attempt_count += 1
            command.locked_at = cast(datetime, await self._session.scalar(select(func.now())))
            command.locked_by = worker_id
            await self._session.flush()
        return command

    async def prepare_edit(self, question_id: UUID, text: str) -> SentEditPreview:
        """Persist edited draft text while retaining the last successful final version."""
        question = await self._session.scalar(
            select(DetectedQuestion).where(DetectedQuestion.id == question_id).with_for_update()
        )
        if question is None or question.status is not QuestionStatus.SENT:
            raise ConfirmationUnavailableError
        current = await self._latest_final(question_id)
        if current is None or await self._stored_sent_message_id(question_id) is None:
            raise ConfirmationUnavailableError
        latest_number = await self._latest_version_number(question_id)
        self._session.add(
            ReplyVersion(
                question_id=question_id,
                version_number=latest_number + 1,
                text=text,
                action="draft",
            )
        )
        await self._session.flush()
        return SentEditPreview(question_id, current.text, text)

    async def confirm_edit(self, question_id: UUID) -> ConfirmedCommand:
        """Create one idempotent edit command for the latest preview."""
        question = await self._session.scalar(
            select(DetectedQuestion).where(DetectedQuestion.id == question_id).with_for_update()
        )
        if question is None or question.status is not QuestionStatus.SENT:
            raise ConfirmationUnavailableError
        preview = await self._session.scalar(
            select(ReplyVersion)
            .where(ReplyVersion.question_id == question_id)
            .order_by(ReplyVersion.version_number.desc())
            .limit(1)
        )
        if preview is None or preview.action != "draft":
            raise ConfirmationUnavailableError
        key = f"{question_id}:edit_reply:{preview.version_number}"
        existing = await self._session.scalar(
            select(OutboundCommand).where(OutboundCommand.idempotency_key == key)
        )
        if existing is not None:
            return ConfirmedCommand(existing.id, existing.reply_version, existing.text, False)
        sent_message_id = await self._stored_sent_message_id(question_id)
        if sent_message_id is None:
            raise ConfirmationUnavailableError
        command = OutboundCommand(
            question_id=question_id,
            command_type="edit_reply",
            reply_version=preview.version_number + 1,
            idempotency_key=key,
            telegram_chat_id=question.telegram_chat_id,
            source_message_id=question.telegram_message_id,
            topic_id=question.topic_id,
            sent_message_id=sent_message_id,
            text=preview.text,
        )
        self._session.add(command)
        await self._session.flush()
        return ConfirmedCommand(command.id, command.reply_version, command.text, True)

    async def complete_edit(self, command: OutboundCommand) -> None:
        """Append the new final version only after Telegram confirms the edit."""
        question = await self._session.scalar(
            select(DetectedQuestion)
            .where(DetectedQuestion.id == command.question_id)
            .with_for_update()
        )
        if question is None or question.status is not QuestionStatus.SENT:
            raise ConfirmationUnavailableError
        self._session.add(
            ReplyVersion(
                question_id=command.question_id,
                version_number=command.reply_version,
                text=command.text,
                action="edited",
            )
        )
        command.status = OutboundCommandStatus.SUCCEEDED
        command.completed_at = cast(datetime, await self._session.scalar(select(func.now())))
        command.locked_at = None
        command.locked_by = None
        await self._session.flush()

    async def fail_edit(self, command: OutboundCommand, *, error_code: str) -> None:
        """Fail an edit without changing the sent question or its final version."""
        command.status = OutboundCommandStatus.FAILED
        command.last_error_code = error_code
        command.last_error_message = error_code
        command.locked_at = None
        command.locked_by = None
        await self._session.flush()

    async def _stored_sent_message_id(self, question_id: UUID) -> int | None:
        return await self._session.scalar(
            select(OutboundCommand.sent_message_id)
            .where(
                OutboundCommand.question_id == question_id,
                OutboundCommand.command_type == "send_reply",
                OutboundCommand.status == OutboundCommandStatus.SUCCEEDED,
                OutboundCommand.sent_message_id.is_not(None),
            )
            .order_by(OutboundCommand.completed_at.desc())
            .limit(1)
        )

    async def _latest_final(self, question_id: UUID) -> ReplyVersion | None:
        return cast(
            ReplyVersion | None,
            await self._session.scalar(
                select(ReplyVersion)
                .where(
                    ReplyVersion.question_id == question_id,
                    ReplyVersion.action.in_(("sent", "edited")),
                )
                .order_by(ReplyVersion.version_number.desc())
                .limit(1)
            ),
        )

    async def _latest_version_number(self, question_id: UUID) -> int:
        latest = await self._session.scalar(
            select(func.max(ReplyVersion.version_number)).where(
                ReplyVersion.question_id == question_id
            )
        )
        return latest or 0

    async def complete_send(self, command: OutboundCommand, sent_message_id: int) -> None:
        """Atomically finish one accepted send and its owning question."""
        question = await self._session.scalar(
            select(DetectedQuestion)
            .where(DetectedQuestion.id == command.question_id)
            .with_for_update()
        )
        if question is None or question.status is not QuestionStatus.SEND_REQUESTED:
            raise ConfirmationUnavailableError
        command.sent_message_id = sent_message_id
        command.status = OutboundCommandStatus.SUCCEEDED
        completed_at = cast(datetime, await self._session.scalar(select(func.now())))
        command.completed_at = completed_at
        command.locked_at = None
        command.locked_by = None
        question.status = QuestionStatus.SENT
        question.updated_at = completed_at
        await self._session.flush()

    async def retry_send(
        self, command: OutboundCommand, *, error_code: str, delay_seconds: int
    ) -> None:
        """Release a command for a safe, explicitly delayed retry."""
        database_now = cast(datetime, await self._session.scalar(select(func.now())))
        command.status = OutboundCommandStatus.PENDING
        command.next_attempt_at = database_now + timedelta(seconds=delay_seconds)
        command.last_error_code = error_code
        command.last_error_message = error_code
        command.locked_at = None
        command.locked_by = None
        await self._session.flush()

    async def fail_send(
        self, command: OutboundCommand, *, error_code: str, needs_review: bool
    ) -> None:
        """Persist a terminal or ambiguous outcome without another automatic send."""
        command.status = (
            OutboundCommandStatus.NEEDS_REVIEW if needs_review else OutboundCommandStatus.FAILED
        )
        command.last_error_code = error_code
        command.last_error_message = error_code
        command.locked_at = None
        command.locked_by = None
        command.question.status = QuestionStatus.SEND_FAILED
        command.question.updated_at = cast(datetime, await self._session.scalar(select(func.now())))
        await self._session.flush()

    async def confirm_send(self, question_id: UUID) -> ConfirmedCommand:
        question = await self._session.scalar(
            select(DetectedQuestion).where(DetectedQuestion.id == question_id).with_for_update()
        )
        if question is None:
            raise ConfirmationUnavailableError

        existing = await self._session.scalar(
            select(OutboundCommand).where(
                OutboundCommand.question_id == question_id,
                OutboundCommand.command_type == "send_reply",
            )
        )
        if existing is not None:
            if question.status is not QuestionStatus.SEND_REQUESTED:
                raise ConfirmationUnavailableError
            return ConfirmedCommand(
                existing.id, existing.reply_version, existing.text, created=False
            )

        if question.status is not QuestionStatus.WAITING_CONFIRMATION:
            raise ConfirmationUnavailableError

        preview = await self._session.scalar(
            select(ReplyVersion)
            .where(ReplyVersion.question_id == question_id)
            .order_by(ReplyVersion.version_number.desc())
            .limit(1)
        )
        if preview is None or preview.action != "draft":
            raise ConfirmationUnavailableError

        latest_number = await self._session.scalar(
            select(func.max(ReplyVersion.version_number)).where(
                ReplyVersion.question_id == question_id
            )
        )
        final_version = (latest_number or 0) + 1
        self._session.add(
            ReplyVersion(
                question_id=question_id,
                version_number=final_version,
                text=preview.text,
                action="sent",
            )
        )
        command = OutboundCommand(
            question_id=question_id,
            command_type="send_reply",
            reply_version=final_version,
            idempotency_key=f"{question_id}:send_reply:{final_version}",
            telegram_chat_id=question.telegram_chat_id,
            source_message_id=question.telegram_message_id,
            topic_id=question.topic_id,
            text=preview.text,
        )
        self._session.add(command)
        question.status = QuestionStatus.SEND_REQUESTED
        await self._session.flush()
        return ConfirmedCommand(command.id, final_version, preview.text, created=True)


__all__ = [
    "ConfirmationUnavailableError",
    "ConfirmedCommand",
    "OutboundFailure",
    "OutboundCommandRepository",
    "OutboundRetryUnavailableError",
    "SentEditPreview",
]
