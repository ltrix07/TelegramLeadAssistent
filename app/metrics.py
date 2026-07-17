"""Privacy-safe structured counters and duration observations."""

from __future__ import annotations

import logging
from time import perf_counter

from app.logging import log_event

logger = logging.getLogger(__name__)

COUNTER_NAMES = frozenset(
    {
        "telegram_messages_received_total",
        "messages_filtered_locally_total",
        "processing_jobs_created_total",
        "processing_jobs_failed_total",
        "classification_stage1_total",
        "classification_stage2_total",
        "classification_relevant_total",
        "classification_irrelevant_total",
        "classification_api_errors_total",
        "translation_jobs_total",
        "translation_errors_total",
        "operator_notifications_total",
        "notifications_failed_total",
        "outbound_commands_total",
        "outbound_send_success_total",
        "outbound_send_failed_total",
        "duplicate_messages_prevented_total",
        "duplicate_replies_created_total",
    }
)

DURATION_NAMES = frozenset(
    {
        "classification_latency_ms",
        "notification_latency_ms",
        "operator_reaction_time_ms",
        "outbound_send_latency_ms",
    }
)


def increment(name: str, *, value: int = 1, **labels: object) -> None:
    """Emit one allow-listed monotonic counter increment."""
    if name not in COUNTER_NAMES:
        raise ValueError(f"Unknown counter: {name}")
    if value < 1:
        raise ValueError("Counter increments must be positive")
    log_event(logger, logging.INFO, "metric_counter", metric=name, value=value, **labels)


def observe_duration(name: str, started_at: float, **labels: object) -> None:
    """Emit one allow-listed non-negative elapsed duration in milliseconds."""
    if name not in DURATION_NAMES:
        raise ValueError(f"Unknown duration: {name}")
    duration_ms = max(round((perf_counter() - started_at) * 1000, 3), 0.0)
    log_event(
        logger,
        logging.INFO,
        "metric_duration",
        metric=name,
        duration_ms=duration_ms,
        **labels,
    )


__all__ = ["COUNTER_NAMES", "DURATION_NAMES", "increment", "observe_duration"]
