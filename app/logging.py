"""Structured logging with correlation context and sensitive-data redaction."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import SecretStr

from app.config import AppSettings, ServiceName

if TYPE_CHECKING:
    from logging import LogRecord

_REDACTED = "[REDACTED]"
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_SENSITIVE_FIELDS = frozenset(
    {
        "api_hash",
        "api_key",
        "api_prompt",
        "answer",
        "bot_token",
        "database_url",
        "draft_text",
        "draft",
        "final_answer",
        "final_text",
        "message_text",
        "mtproto_session",
        "openai_api_key",
        "operator_bot_token",
        "original_text",
        "phone",
        "phone_number",
        "prompt",
        "raw_text",
        "reply_text",
        "session",
        "session_data",
        "telegram_api_hash",
        "telegram_session",
        "telegram_session_path",
        "text",
        "translated_text",
        "translation",
    }
)

_STANDARD_LOG_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}


def new_correlation_id() -> str:
    """Create an opaque correlation identifier."""
    return str(uuid4())


def get_correlation_id() -> str | None:
    """Return the correlation identifier for the current async context."""
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> Token[str | None]:
    """Set correlation context and return a token for restoring it."""
    return _correlation_id.set(value)


def reset_correlation_id(token: Token[str | None]) -> None:
    """Restore a previously saved correlation context."""
    _correlation_id.reset(token)


@contextmanager
def correlation_context(value: str | None = None) -> Iterator[str]:
    """Set a correlation identifier for the duration of one operation."""
    correlation_id = value or new_correlation_id()
    token = set_correlation_id(correlation_id)
    try:
        yield correlation_id
    finally:
        reset_correlation_id(token)


class JsonFormatter(logging.Formatter):
    """Serialize log records as one redacted JSON object per line."""

    def __init__(self, service: ServiceName, secret_values: frozenset[str]) -> None:
        super().__init__()
        self._service = service.value
        self._secret_values = secret_values

    def format(self, record: LogRecord) -> str:
        """Format one record without exposing configured secrets or text fields."""
        event = getattr(record, "event", record.getMessage())
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "event": self._sanitize_value(event),
            "correlation_id": get_correlation_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_FIELDS and key != "event":
                payload[key] = self._sanitize_field(key, value)
        if record.exc_info:
            payload["exception"] = self._sanitize_value(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False, separators=(",", ":"))

    def _sanitize_field(self, key: str, value: object) -> object:
        if key.lower() in _SENSITIVE_FIELDS:
            return _REDACTED
        return self._sanitize_value(value)

    def _sanitize_value(self, value: object) -> object:
        if isinstance(value, SecretStr):
            return _REDACTED
        if isinstance(value, Mapping):
            return {
                str(key): self._sanitize_field(str(key), nested_value)
                for key, nested_value in value.items()
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            return [self._sanitize_value(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, str):
            sanitized = value
            for secret in self._secret_values:
                sanitized = sanitized.replace(secret, _REDACTED)
            return sanitized
        return value


def _configured_secret_values(settings: AppSettings) -> frozenset[str]:
    values: set[str] = set()
    for field_name in type(settings).model_fields:
        value = getattr(settings, field_name)
        if isinstance(value, SecretStr):
            secret = value.get_secret_value()
            if secret:
                values.add(secret)
    return frozenset(values)


def configure_logging(
    service: ServiceName,
    settings: AppSettings,
    *,
    stream: IO[str] | None = None,
) -> None:
    """Configure the root logger for one application service."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(service, _configured_secret_values(settings)))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: object,
) -> None:
    """Write one structured event with optional non-sensitive fields."""
    logger.log(level, event, extra={"event": event, **fields})
