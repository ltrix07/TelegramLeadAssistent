"""Idempotent classification usage and cost accounting."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier.openai_adapter import ClassificationResponse
from app.database.models import ApiUsageDaily, ClassificationRun

USD_QUANTUM = Decimal("0.000001")
TOKENS_PER_MILLION = Decimal("1000000")


@dataclass(frozen=True, slots=True)
class ClassificationPricing:
    """Configurable token prices in USD per one million tokens."""

    input_per_million_usd: Decimal
    output_per_million_usd: Decimal

    def estimate(self, *, input_tokens: int, output_tokens: int) -> Decimal:
        """Calculate a database-scale estimated cost for one API call."""
        cost = (
            Decimal(input_tokens) * self.input_per_million_usd
            + Decimal(output_tokens) * self.output_per_million_usd
        ) / TOKENS_PER_MILLION
        return cost.quantize(USD_QUANTUM, rounding=ROUND_HALF_UP)


def project_month_cost(month_to_date_cost: Decimal, *, as_of: date) -> Decimal:
    """Project full-month cost from the inclusive month-to-date average."""
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    projection = month_to_date_cost * Decimal(days_in_month) / Decimal(as_of.day)
    return projection.quantize(USD_QUANTUM, rounding=ROUND_HALF_UP)


class UsageRepository:
    """Persist per-call metadata and derived daily aggregates atomically."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_stage(
        self,
        *,
        telegram_chat_id: int,
        telegram_message_id: int,
        stage: int,
        queued_at: datetime,
        model: str,
        response: ClassificationResponse,
        pricing: ClassificationPricing,
    ) -> bool:
        """Record one stage once and update its daily aggregate when inserted."""
        result = response.result
        result_name = (
            "context_required"
            if result.context_required
            else ("relevant" if result.is_relevant else "irrelevant")
        )
        estimated_cost = pricing.estimate(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        inserted_id = (
            await self._session.execute(
                insert(ClassificationRun)
                .values(
                    telegram_chat_id=telegram_chat_id,
                    telegram_message_id=telegram_message_id,
                    stage=stage,
                    queued_at=queued_at,
                    result=result_name,
                    category=result.category.value,
                    confidence=Decimal(str(result.confidence)),
                    reason_code=result.reason_code.value,
                    context_used=stage == 2,
                    model=model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    estimated_cost_usd=estimated_cost,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        ClassificationRun.telegram_chat_id,
                        ClassificationRun.telegram_message_id,
                        ClassificationRun.stage,
                    ]
                )
                .returning(ClassificationRun.id)
            )
        ).scalar_one_or_none()
        if inserted_id is None:
            return False

        await self._session.execute(
            insert(ApiUsageDaily)
            .values(
                usage_date=func.current_date(),
                model=model,
                request_count=1,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                estimated_cost_usd=estimated_cost,
            )
            .on_conflict_do_update(
                index_elements=[ApiUsageDaily.usage_date, ApiUsageDaily.model],
                set_={
                    "request_count": ApiUsageDaily.request_count + 1,
                    "input_tokens": (ApiUsageDaily.input_tokens + response.usage.input_tokens),
                    "output_tokens": (ApiUsageDaily.output_tokens + response.usage.output_tokens),
                    "estimated_cost_usd": (ApiUsageDaily.estimated_cost_usd + estimated_cost),
                },
            )
        )
        return True

    async def projected_month_cost(self, *, as_of: date) -> Decimal:
        """Return the projected cost for the month containing ``as_of``."""
        month_start = as_of.replace(day=1)
        total = await self._session.scalar(
            select(func.coalesce(func.sum(ApiUsageDaily.estimated_cost_usd), 0)).where(
                ApiUsageDaily.usage_date.between(month_start, as_of)
            )
        )
        return project_month_cost(total or Decimal("0"), as_of=as_of)


__all__ = [
    "ClassificationPricing",
    "UsageRepository",
    "project_month_cost",
]
