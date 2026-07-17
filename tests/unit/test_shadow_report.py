"""Unit coverage for the content-free shadow stability report."""

from datetime import UTC, datetime
from decimal import Decimal

from app.rollout.shadow import ShadowReport, render_shadow_report


def test_shadow_report_renders_aggregate_evidence_only() -> None:
    report = ShadowReport(
        chat_id=-100123,
        started_at=datetime(2026, 7, 16, tzinfo=UTC),
        ended_at=datetime(2026, 7, 17, tzinfo=UTC),
        classification_calls=12,
        classified_messages=10,
        relevant=2,
        irrelevant=8,
        context_required=2,
        failed_jobs=0,
        pending_jobs=0,
        average_queue_latency_seconds=1.25,
        maximum_queue_latency_seconds=4.5,
        estimated_cost_usd=Decimal("0.001234"),
        sent_operator_notifications=0,
        outbound_commands=0,
        expired_temporary_rows=0,
    )

    rendered = render_shadow_report(report)

    assert "Verdict: PASS" in rendered
    assert "Classified messages: 10" in rendered
    assert "average=1.250s, maximum=4.500s" in rendered
    assert "Estimated API cost: $0.001234" in rendered
    assert "Sent operator notifications: 0" in rendered
    assert "Outbound commands created: 0" in rendered
