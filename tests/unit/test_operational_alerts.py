"""Unit coverage for allow-listed operational alert rendering."""

from decimal import Decimal

from app.bot.operational_alerts import render_operational_alert
from app.database.models import OperationalAlert


def _alert(alert_type: str, details: dict[str, str] | None = None) -> OperationalAlert:
    return OperationalAlert(
        deduplication_key=f"test:{alert_type}",
        alert_type=alert_type,
        details=details or {},
        operator_telegram_user_id=123,
    )


def test_budget_alert_renders_only_numeric_aggregate_details() -> None:
    text = render_operational_alert(
        _alert(
            "budget_threshold",
            {"threshold_usd": str(Decimal("5")), "cost_usd": str(Decimal("8.25"))},
        )
    )

    assert "$5.00" in text
    assert "$8.25" in text


def test_failure_alerts_have_fixed_content_free_text() -> None:
    assert "5 минут" in render_operational_alert(_alert("mtproto_disconnected"))
    assert "10 минут" in render_operational_alert(_alert("queue_delayed"))
    assert "15 минут" in render_operational_alert(_alert("translator_unavailable"))
