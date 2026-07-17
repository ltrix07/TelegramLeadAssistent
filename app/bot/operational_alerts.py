"""Reliable delivery of content-free operational alerts to the operator."""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import OperationalAlert
from app.database.worker import RetryPolicy


class AlertBot(Protocol):
    async def send_message(self, chat_id: int, text: str) -> object: ...


class OperationalAlertWorker:
    """Claim and deliver operator-only alerts with bounded retries."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bot: AlertBot,
        operator_user_id: int,
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._bot = bot
        self._operator_user_id = operator_user_id
        self._retry_policy = retry_policy or RetryPolicy()

    async def run_once(self) -> bool:
        async with self._session_factory.begin() as session:
            alert = await session.scalar(
                select(OperationalAlert)
                .where(
                    OperationalAlert.status.in_(("pending", "retry")),
                    OperationalAlert.next_attempt_at <= func.now(),
                    OperationalAlert.operator_telegram_user_id == self._operator_user_id,
                )
                .order_by(OperationalAlert.next_attempt_at, OperationalAlert.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if alert is None:
                return False
            alert.status = "sending"
            alert.attempt_count += 1
            alert.last_error = None
            alert.updated_at = cast(datetime, await session.scalar(select(func.now())))
            try:
                await self._bot.send_message(
                    self._operator_user_id, render_operational_alert(alert)
                )
            except Exception as error:
                alert.last_error = type(error).__name__[:100]
                delay = self._retry_policy.delay_after_attempt(alert.attempt_count)
                if delay is None:
                    alert.status = "failed"
                else:
                    alert.status = "retry"
                    retry_at = await session.scalar(select(func.now() + delay))
                    if retry_at is None:
                        raise RuntimeError("Database did not return retry time") from error
                    alert.next_attempt_at = retry_at
            else:
                now = cast(datetime, await session.scalar(select(func.now())))
                alert.status = "sent"
                alert.sent_at = now
                alert.updated_at = now
        return True

    async def run_forever(self, poll_interval_seconds: float = 1.0) -> None:
        while True:
            if not await self.run_once():
                await asyncio.sleep(poll_interval_seconds)


def render_operational_alert(alert: OperationalAlert) -> str:
    """Render an allow-listed alert type without accepting arbitrary text."""
    if alert.alert_type == "budget_threshold":
        try:
            threshold = Decimal(str(alert.details["threshold_usd"]))
            cost = Decimal(str(alert.details["cost_usd"]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            return "⚠️ Расход API пересёк настроенный порог."
        return f"⚠️ Расход API пересёк ${threshold:.2f}. Текущий расход за месяц: ${cost:.2f}."
    messages = {
        "mtproto_disconnected": "⚠️ MTProto недоступен более 5 минут.",
        "queue_delayed": "⚠️ Самая старая задача в очереди старше 10 минут.",
        "translator_unavailable": "⚠️ Translator недоступен более 15 минут.",
    }
    return messages.get(alert.alert_type, "⚠️ Обнаружена операционная проблема.")


__all__ = ["OperationalAlertWorker", "render_operational_alert"]
