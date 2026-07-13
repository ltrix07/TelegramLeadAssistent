"""Unit tests for bounded queue worker retries."""

from datetime import timedelta

import pytest

from app.database.worker import RetryPolicy


def test_retry_policy_uses_spec_backoff_and_then_stops() -> None:
    policy = RetryPolicy()

    assert [policy.delay_after_attempt(attempt) for attempt in range(1, 6)] == [
        timedelta(seconds=15),
        timedelta(seconds=60),
        timedelta(minutes=5),
        timedelta(minutes=30),
        None,
    ]


def test_retry_policy_rejects_unclaimed_attempt() -> None:
    with pytest.raises(ValueError, match="positive"):
        RetryPolicy().delay_after_attempt(0)
