"""Tests for privacy-safe structured operational metrics."""

from __future__ import annotations

import json
from io import StringIO
from time import perf_counter

import pytest
from pydantic import SecretStr

from app.config import AppSettings, ServiceName
from app.logging import configure_logging
from app.metrics import increment, observe_duration


def test_counter_and_duration_are_structured_and_content_free() -> None:
    stream = StringIO()
    settings = AppSettings(
        database_url=SecretStr("postgresql+asyncpg://test:test@localhost/test"),
        openai_api_key=SecretStr("configured-secret"),
    )
    configure_logging(ServiceName.CLASSIFICATION_WORKER, settings, stream=stream)

    increment("classification_stage1_total", stage=1)
    observe_duration("classification_latency_ms", perf_counter(), stage=1)

    counter, duration = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert counter["event"] == "metric_counter"
    assert counter["metric"] == "classification_stage1_total"
    assert counter["value"] == 1
    assert counter["stage"] == 1
    assert duration["event"] == "metric_duration"
    assert duration["metric"] == "classification_latency_ms"
    assert duration["duration_ms"] >= 0


@pytest.mark.parametrize("operation", ["counter", "duration"])
def test_unknown_metric_names_are_rejected(operation: str) -> None:
    with pytest.raises(ValueError, match="Unknown"):
        if operation == "counter":
            increment("message_text")
        else:
            observe_duration("draft_text", perf_counter())
