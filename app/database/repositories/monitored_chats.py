"""Persistence operations for operator-managed Telegram chats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import MonitoredChat
from app.domain.enums import MonitoredChatStatus, MonitoredChatType
from app.listener.mtproto.client import ChatVerificationOutcome, ChatVerificationResult


@dataclass(frozen=True, slots=True)
class NewMonitoredChat:
    """Bot API metadata captured from a group picker result."""

    telegram_chat_id: int
    title: str
    username: str | None
    added_by_telegram_user_id: int


class MonitoredChatRepository:
    """Store and mutate monitored chats within the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_pending(self, chat: NewMonitoredChat) -> tuple[MonitoredChat, bool]:
        """Insert a pending chat once and return whether this call created it."""
        chat_id = uuid4()
        inserted_id = await self._session.scalar(
            insert(MonitoredChat)
            .values(
                id=chat_id,
                telegram_chat_id=chat.telegram_chat_id,
                title=chat.title,
                username=chat.username,
                chat_type=MonitoredChatType.GROUP,
                status=MonitoredChatStatus.PENDING_VERIFICATION,
                added_by_telegram_user_id=chat.added_by_telegram_user_id,
            )
            .on_conflict_do_nothing(index_elements=[MonitoredChat.telegram_chat_id])
            .returning(MonitoredChat.id)
        )
        created = inserted_id is not None
        predicate = (
            MonitoredChat.id == inserted_id
            if created
            else MonitoredChat.telegram_chat_id == chat.telegram_chat_id
        )
        result = await self._session.scalar(select(MonitoredChat).where(predicate))
        if result is None:
            raise RuntimeError("Monitored chat insert did not return a persisted row")
        return result, created

    async def list_all(self) -> list[MonitoredChat]:
        """List chats in stable operator-facing order."""
        rows = await self._session.scalars(
            select(MonitoredChat).order_by(MonitoredChat.added_at, MonitoredChat.id)
        )
        return list(rows)

    async def list_active_telegram_chat_ids(self) -> frozenset[int]:
        """Return the Telegram IDs currently eligible for ingestion."""
        rows = await self._session.scalars(
            select(MonitoredChat.telegram_chat_id).where(
                MonitoredChat.status == MonitoredChatStatus.ACTIVE
            )
        )
        return frozenset(rows)

    async def get_active_id_by_telegram_chat_id(self, telegram_chat_id: int) -> UUID | None:
        """Return the internal ID only while the monitored chat is active."""
        return cast(
            UUID | None,
            await self._session.scalar(
                select(MonitoredChat.id).where(
                    MonitoredChat.telegram_chat_id == telegram_chat_id,
                    MonitoredChat.status == MonitoredChatStatus.ACTIVE,
                )
            ),
        )

    async def list_pending_verification(self, *, limit: int = 20) -> list[MonitoredChat]:
        """Return a bounded batch of chats waiting for MTProto verification."""
        rows = await self._session.scalars(
            select(MonitoredChat)
            .where(MonitoredChat.status == MonitoredChatStatus.PENDING_VERIFICATION)
            .order_by(MonitoredChat.updated_at, MonitoredChat.id)
            .limit(limit)
        )
        return list(rows)

    async def apply_verification(self, chat_id: UUID, result: ChatVerificationResult) -> bool:
        """Persist a terminal result only while the chat is still pending."""
        status = MonitoredChatStatus(result.outcome.value)
        if result.is_forum:
            chat_type = MonitoredChatType.FORUM_SUPERGROUP
        elif result.is_supergroup:
            chat_type = MonitoredChatType.SUPERGROUP
        else:
            chat_type = MonitoredChatType.GROUP
        values: dict[str, object] = {
            "status": status,
            "chat_type": chat_type,
            "last_verified_at": func.now(),
            "updated_at": func.now(),
            "last_error_code": result.error_code,
            "last_error_message": None,
            "access_lost_at": (
                func.now() if result.outcome == ChatVerificationOutcome.ACCESS_LOST else None
            ),
        }
        changed_id = await self._session.scalar(
            update(MonitoredChat)
            .where(
                MonitoredChat.id == chat_id,
                MonitoredChat.status == MonitoredChatStatus.PENDING_VERIFICATION,
            )
            .values(**values)
            .returning(MonitoredChat.id)
        )
        return changed_id is not None

    async def pause(self, chat_id: UUID) -> bool:
        """Disable a chat without deleting its history."""
        changed_id = await self._session.scalar(
            update(MonitoredChat)
            .where(
                MonitoredChat.id == chat_id,
                MonitoredChat.status != MonitoredChatStatus.DISABLED,
            )
            .values(status=MonitoredChatStatus.DISABLED, updated_at=func.now())
            .returning(MonitoredChat.id)
        )
        return changed_id is not None

    async def resume(self, chat_id: UUID) -> bool:
        """Queue a disabled chat for verification before monitoring resumes."""
        changed_id = await self._session.scalar(
            update(MonitoredChat)
            .where(
                MonitoredChat.id == chat_id,
                MonitoredChat.status == MonitoredChatStatus.DISABLED,
            )
            .values(
                status=MonitoredChatStatus.PENDING_VERIFICATION,
                updated_at=func.now(),
            )
            .returning(MonitoredChat.id)
        )
        return changed_id is not None

    async def remove(self, chat_id: UUID) -> bool:
        """Remove a chat from monitoring without any Telegram-side action."""
        removed_id = await self._session.scalar(
            delete(MonitoredChat).where(MonitoredChat.id == chat_id).returning(MonitoredChat.id)
        )
        return removed_id is not None
