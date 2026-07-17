"""Durable detection and delivery state for content-free operator alerts."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AlertCondition, OperationalAlert


class OperationalAlertRepository:
    """Create deduplicated alerts and track prolonged condition episodes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_budget_thresholds(
        self,
        *,
        month_key: str,
        cost_usd: Decimal,
        thresholds: tuple[Decimal, ...],
        operator_user_id: int,
    ) -> int:
        """Enqueue each crossed monthly threshold exactly once."""
        created = 0
        for threshold in thresholds:
            if cost_usd < threshold:
                continue
            result = await self._session.execute(
                insert(OperationalAlert)
                .values(
                    deduplication_key=f"budget:{month_key}:{threshold}",
                    alert_type="budget_threshold",
                    details={"threshold_usd": str(threshold), "cost_usd": str(cost_usd)},
                    operator_telegram_user_id=operator_user_id,
                )
                .on_conflict_do_nothing(index_elements=[OperationalAlert.deduplication_key])
                .returning(OperationalAlert.id)
            )
            created += int(result.scalar_one_or_none() is not None)
        return created

    async def observe_condition(
        self,
        *,
        condition_key: str,
        failing: bool,
        threshold: timedelta,
        alert_type: str,
        operator_user_id: int,
        details: dict[str, str] | None = None,
    ) -> bool:
        """Enqueue once after one continuous failure crosses its threshold."""
        now = cast(datetime, await self._session.scalar(select(func.now())))
        state = await self._session.get(AlertCondition, condition_key, with_for_update=True)
        if not failing:
            if state is not None:
                await self._session.execute(
                    delete(AlertCondition).where(AlertCondition.condition_key == condition_key)
                )
            return False
        if state is None:
            state = AlertCondition(condition_key=condition_key, failing_since=now, updated_at=now)
            self._session.add(state)
            await self._session.flush()
        else:
            state.updated_at = now
        if now - state.failing_since < threshold:
            return False
        episode = state.failing_since.isoformat()
        result = await self._session.execute(
            insert(OperationalAlert)
            .values(
                deduplication_key=f"failure:{condition_key}:{episode}",
                alert_type=alert_type,
                details=details or {},
                operator_telegram_user_id=operator_user_id,
            )
            .on_conflict_do_nothing(index_elements=[OperationalAlert.deduplication_key])
            .returning(OperationalAlert.id)
        )
        return result.scalar_one_or_none() is not None


__all__ = ["OperationalAlertRepository"]
