"""Domain errors shared across infrastructure adapters and workers."""

from dataclasses import dataclass
from enum import StrEnum


class TelegramErrorCode(StrEnum):
    """Stable, operator-facing Telegram failure categories."""

    SOURCE_MESSAGE_DELETED = "SOURCE_MESSAGE_DELETED"
    CHAT_WRITE_FORBIDDEN = "CHAT_WRITE_FORBIDDEN"
    TOPIC_CLOSED = "TOPIC_CLOSED"
    TOPIC_DELETED = "TOPIC_DELETED"
    FLOOD_WAIT = "FLOOD_WAIT"
    ACCESS_LOST = "ACCESS_LOST"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class TelegramFailureKind(StrEnum):
    """Controls whether an outbound command may run automatically again."""

    PERMANENT = "permanent"
    TEMPORARY = "temporary"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class TelegramOutboundError(RuntimeError):
    """Privacy-safe normalized failure raised by the MTProto adapter."""

    code: TelegramErrorCode
    kind: TelegramFailureKind
    retry_after_seconds: int | None = None

    def __str__(self) -> str:
        return self.code.value
