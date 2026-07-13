"""Tests for configurable API pricing and monthly projection."""

from datetime import date
from decimal import Decimal

from app.classifier.usage import ClassificationPricing, project_month_cost


def test_cost_uses_configured_input_and_output_prices() -> None:
    pricing = ClassificationPricing(
        input_per_million_usd=Decimal("0.20"),
        output_per_million_usd=Decimal("1.25"),
    )

    assert pricing.estimate(input_tokens=1_000_000, output_tokens=2_000_000) == Decimal("2.700000")


def test_month_projection_uses_elapsed_calendar_days() -> None:
    assert project_month_cost(Decimal("5.000000"), as_of=date(2026, 7, 10)) == Decimal("15.500000")
