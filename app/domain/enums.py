"""Domain enumerations persisted by PostgreSQL."""

from enum import StrEnum


class MonitoredChatStatus(StrEnum):
    """Verification and monitoring state of a Telegram chat."""

    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    ACCESS_LOST = "access_lost"
    READ_ONLY = "read_only"
    DISABLED = "disabled"
    VERIFICATION_FAILED = "verification_failed"


class MonitoredChatType(StrEnum):
    """Supported Telegram chat types."""

    GROUP = "group"
    SUPERGROUP = "supergroup"
    FORUM_SUPERGROUP = "forum_supergroup"


class ProcessingJobStatus(StrEnum):
    """Lifecycle state of a classification queue job."""

    PENDING = "pending"
    PROCESSING = "processing"
    RETRY = "retry"
    FAILED = "failed"
    AWAITING_RELEVANT_PROCESSING = "awaiting_relevant_processing"
    AWAITING_REPLY_CONTEXT = "awaiting_reply_context"


class QuestionStatus(StrEnum):
    """Operator workflow state for a detected question."""

    DETECTED = "detected"
    WAITING_FOR_DRAFT = "waiting_for_draft"
    WAITING_CONFIRMATION = "waiting_confirmation"
    SEND_REQUESTED = "send_requested"
    SENT = "sent"
    SEND_FAILED = "send_failed"
    DISMISSED = "dismissed"
    CANCELLED = "cancelled"


class OutboundCommandStatus(StrEnum):
    """Lifecycle state of an outbound Telegram command."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class TranslationManagerAction(StrEnum):
    """Allow-listed operations accepted by the translation manager."""

    INSTALL = "install"
    ENABLE = "enable"
    DISABLE = "disable"
    DELETE = "delete"
    RELOAD = "reload"
    TEST = "test"


class TranslationManagerJobStatus(StrEnum):
    """Lifecycle state of a translation control-plane job."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
