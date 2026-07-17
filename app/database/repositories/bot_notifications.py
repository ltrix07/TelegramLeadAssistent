"""PostgreSQL queue access for operator notification delivery."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database.models import BotNotification, DetectedQuestion


class BotNotificationRepository:
    """Claim and update operator notifications using database-owned state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(self, operator_user_id: int) -> BotNotification | None:
        """Claim the oldest eligible notification for the configured operator."""
        statement = (
            select(BotNotification)
            .where(
                BotNotification.status.in_(("pending", "retry")),
                BotNotification.next_attempt_at <= func.now(),
                BotNotification.operator_telegram_user_id == operator_user_id,
                BotNotification.bot_chat_id == operator_user_id,
            )
            .options(
                joinedload(BotNotification.question).joinedload(DetectedQuestion.monitored_chat),
                joinedload(BotNotification.question).selectinload(DetectedQuestion.chain_messages),
            )
            .order_by(BotNotification.next_attempt_at, BotNotification.created_at)
            .with_for_update(skip_locked=True, of=BotNotification)
            .limit(1)
        )
        notification = await self._session.scalar(statement)
        if notification is None:
            return None
        notification.status = "sending"
        notification.attempt_count += 1
        notification.last_error = None
        notification.updated_at = cast(datetime, await self._session.scalar(select(func.now())))
        await self._session.flush()
        return notification

    async def mark_sent(self, notification: BotNotification, bot_message_id: int) -> None:
        """Persist successful delivery of the final interactive message part."""
        database_now = cast(datetime, await self._session.scalar(select(func.now())))
        notification.status = "sent"
        notification.bot_message_id = bot_message_id
        notification.sent_at = database_now
        notification.last_error = None
        notification.updated_at = database_now

    async def retry(
        self,
        notification: BotNotification,
        *,
        error_code: str,
        retry_at: datetime,
    ) -> None:
        """Schedule a retry when Telegram accepted no message part."""
        notification.status = "retry"
        notification.next_attempt_at = retry_at
        notification.last_error = error_code[:100]
        notification.updated_at = cast(datetime, await self._session.scalar(select(func.now())))

    async def fail(self, notification: BotNotification, *, error_code: str) -> None:
        """Stop automatic delivery after exhaustion or ambiguous partial delivery."""
        notification.status = "failed"
        notification.last_error = error_code[:100]
        notification.updated_at = cast(datetime, await self._session.scalar(select(func.now())))


__all__ = ["BotNotificationRepository"]
