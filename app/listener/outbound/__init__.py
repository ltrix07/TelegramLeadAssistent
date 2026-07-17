"""Listener-owned worker for confirmed outbound Telegram replies."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import OutboundCommand
from app.database.repositories.outbound_commands import OutboundCommandRepository
from app.domain.enums import QuestionStatus
from app.domain.errors import TelegramErrorCode, TelegramFailureKind, TelegramOutboundError
from app.listener.mtproto import (
    ChatVerificationOutcome,
    ChatVerificationTransientError,
    MTProtoOutboundClient,
)
from app.metrics import increment, observe_duration


class OutboundValidationError(RuntimeError):
    """Reject a command whose durable destination no longer matches Telegram."""


@dataclass(frozen=True, slots=True)
class ReplyDestination:
    """Validated immutable destination for one outbound command."""

    telegram_chat_id: int
    source_message_id: int
    topic_id: int | None


class SendReplyWorker:
    """Claim, validate, send, and atomically persist confirmed replies."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: MTProtoOutboundClient,
        *,
        worker_id: str = "telegram-listener-send",
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._worker_id = worker_id

    async def run_once(self) -> bool:
        """Process at most one due command while retaining its row lock."""
        async with self._session_factory.begin() as session:
            repository = OutboundCommandRepository(session)
            command = await repository.claim_send(self._worker_id)
            if command is None:
                return False
            increment("outbound_commands_total", command_type="send_reply")
            started_at = perf_counter()
            try:
                await self._validate(command)
            except TelegramOutboundError as error:
                await self._record_error(repository, command, error)
                increment("outbound_send_failed_total", error_code=error.code.value)
                return True
            except ChatVerificationTransientError:
                await self._record_error(
                    repository,
                    command,
                    TelegramOutboundError(
                        TelegramErrorCode.UNKNOWN_ERROR, TelegramFailureKind.TEMPORARY
                    ),
                )
                increment("outbound_send_failed_total", error_code="UNKNOWN_ERROR")
                return True
            try:
                sent_message_id = await self._client.send_reply(
                    command.telegram_chat_id,
                    command.source_message_id,
                    command.text,
                )
            except TelegramOutboundError as error:
                await self._record_error(repository, command, error)
                increment("outbound_send_failed_total", error_code=error.code.value)
                return True
            await repository.complete_send(command, sent_message_id)
            increment("outbound_send_success_total")
            observe_duration("outbound_send_latency_ms", started_at)
        return True

    async def _record_error(
        self,
        repository: OutboundCommandRepository,
        command: OutboundCommand,
        error: TelegramOutboundError,
    ) -> None:
        if error.code in {TelegramErrorCode.ACCESS_LOST, TelegramErrorCode.CHAT_WRITE_FORBIDDEN}:
            await repository.request_chat_verification(command.telegram_chat_id)
        if error.kind is TelegramFailureKind.TEMPORARY:
            retry_delays = (15, 60, 300, 1800)
            if error.code is TelegramErrorCode.FLOOD_WAIT:
                delay = error.retry_after_seconds or 0
            elif command.attempt_count <= len(retry_delays):
                delay = retry_delays[command.attempt_count - 1]
            else:
                await repository.fail_send(command, error_code=error.code.value, needs_review=True)
                return
            await repository.retry_send(command, error_code=error.code.value, delay_seconds=delay)
            return
        await repository.fail_send(
            command,
            error_code=error.code.value,
            needs_review=error.kind is TelegramFailureKind.AMBIGUOUS,
        )

    async def _validate(self, command: OutboundCommand) -> ReplyDestination:
        question = command.question
        if (
            question.status is not QuestionStatus.SEND_REQUESTED
            or question.telegram_chat_id != command.telegram_chat_id
            or question.telegram_message_id != command.source_message_id
            or question.topic_id != command.topic_id
        ):
            raise OutboundValidationError("Outbound destination does not match question")

        access = await self._client.verify_chat(command.telegram_chat_id)
        if access.outcome is not ChatVerificationOutcome.ACTIVE:
            code = (
                TelegramErrorCode.CHAT_WRITE_FORBIDDEN
                if access.outcome is ChatVerificationOutcome.READ_ONLY
                else TelegramErrorCode.ACCESS_LOST
            )
            raise TelegramOutboundError(code, TelegramFailureKind.PERMANENT)
        target = await self._client.get_reply_message(
            command.telegram_chat_id, command.source_message_id
        )
        if target is None:
            raise TelegramOutboundError(
                TelegramErrorCode.SOURCE_MESSAGE_DELETED, TelegramFailureKind.PERMANENT
            )
        if (
            target.telegram_chat_id != command.telegram_chat_id
            or target.telegram_message_id != command.source_message_id
            or target.topic_id != command.topic_id
        ):
            raise OutboundValidationError("Telegram target does not match command")
        return ReplyDestination(
            command.telegram_chat_id, command.source_message_id, command.topic_id
        )

    async def run_forever(self, *, poll_interval_seconds: float = 1.0) -> None:
        """Poll the durable queue until the listener lifecycle cancels the task."""
        while True:
            if not await self.run_once():
                await asyncio.sleep(poll_interval_seconds)


class EditReplyWorker:
    """Edit only the message ID persisted by a successful send command."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: MTProtoOutboundClient,
        *,
        worker_id: str = "telegram-listener-edit",
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._worker_id = worker_id

    async def run_once(self) -> bool:
        """Process at most one edit while retaining its durable row lock."""
        async with self._session_factory.begin() as session:
            repository = OutboundCommandRepository(session)
            command = await repository.claim_edit(self._worker_id)
            if command is None:
                return False
            if (
                command.question.status is not QuestionStatus.SENT
                or command.sent_message_id is None
                or command.telegram_chat_id != command.question.telegram_chat_id
            ):
                await repository.fail_edit(command, error_code="INVALID_EDIT_TARGET")
                return True
            try:
                await self._client.edit_message(
                    command.telegram_chat_id, command.sent_message_id, command.text
                )
            except TelegramOutboundError as error:
                await repository.fail_edit(command, error_code=error.code.value)
                return True
            await repository.complete_edit(command)
        return True

    async def run_forever(self, *, poll_interval_seconds: float = 1.0) -> None:
        """Poll the durable edit queue until listener shutdown."""
        while True:
            if not await self.run_once():
                await asyncio.sleep(poll_interval_seconds)


__all__ = [
    "EditReplyWorker",
    "OutboundValidationError",
    "ReplyDestination",
    "SendReplyWorker",
]
