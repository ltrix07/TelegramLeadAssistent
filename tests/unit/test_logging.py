"""Tests for structured logging, correlation context, and redaction."""

from __future__ import annotations

import json
import logging
from io import StringIO

from pydantic import SecretStr

from app.config import AppSettings, ServiceName
from app.logging import configure_logging, correlation_context, get_correlation_id, log_event


def _settings(secret: str = "configured-secret") -> AppSettings:
    return AppSettings(
        database_url=SecretStr("postgresql+asyncpg://test:test@localhost/test"),
        openai_api_key=SecretStr(secret),
    )


def test_log_contains_required_structured_fields() -> None:
    stream = StringIO()
    configure_logging(ServiceName.CLASSIFICATION_WORKER, _settings(), stream=stream)

    with correlation_context("correlation-123"):
        log_event(
            logging.getLogger("test"),
            logging.INFO,
            "classification_completed",
            question_id="question-1",
            telegram_chat_id=42,
            duration_ms=12,
        )

    payload = json.loads(stream.getvalue())
    assert payload["level"] == "INFO"
    assert payload["service"] == "classification-worker"
    assert payload["event"] == "classification_completed"
    assert payload["correlation_id"] == "correlation-123"
    assert payload["question_id"] == "question-1"
    assert payload["telegram_chat_id"] == 42
    assert payload["duration_ms"] == 12
    assert payload["timestamp"].endswith("+00:00")


def test_correlation_context_is_created_and_restored() -> None:
    assert get_correlation_id() is None

    with correlation_context() as correlation_id:
        assert get_correlation_id() == correlation_id

    assert get_correlation_id() is None


def test_sensitive_fields_and_configured_secret_values_are_redacted() -> None:
    stream = StringIO()
    secret = "configured-secret-value"
    configure_logging(ServiceName.OPERATOR_BOT, _settings(secret), stream=stream)

    log_event(
        logging.getLogger("test"),
        logging.WARNING,
        "notification_failed",
        message_text="private community message",
        translated_text="private translation",
        draft_text="private draft",
        prompt="private prompt",
        telegram_session_path="/sessions/private.session",
        metadata={
            "bot_token": "private bot token",
            "safe": f"failure included {secret}",
        },
        telegram_message_id=123,
    )

    output = stream.getvalue()
    payload = json.loads(output)
    assert "private community message" not in output
    assert "private translation" not in output
    assert "private draft" not in output
    assert "private prompt" not in output
    assert "private bot token" not in output
    assert "/sessions/private.session" not in output
    assert secret not in output
    assert payload["message_text"] == "[REDACTED]"
    assert payload["metadata"]["bot_token"] == "[REDACTED]"
    assert payload["telegram_message_id"] == 123


def test_configured_secret_is_redacted_from_exception_text() -> None:
    stream = StringIO()
    secret = "exception-secret-value"
    configure_logging(ServiceName.CLASSIFICATION_WORKER, _settings(secret), stream=stream)
    logger = logging.getLogger("test")

    try:
        raise RuntimeError(f"remote failure included {secret}")
    except RuntimeError:
        logger.exception("classification_failed", extra={"event": "classification_failed"})

    output = stream.getvalue()
    assert secret not in output
    assert "[REDACTED]" in json.loads(output)["exception"]
