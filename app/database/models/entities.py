"""SQLAlchemy models for the agreed PostgreSQL schema."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PythonEnum
from typing import Any
from uuid import UUID as PythonUUID
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base
from app.domain.enums import (
    MonitoredChatStatus,
    MonitoredChatType,
    OutboundCommandStatus,
    ProcessingJobStatus,
    QuestionStatus,
    TranslationManagerAction,
    TranslationManagerJobStatus,
)


def _enum_values(enum_class: type[PythonEnum]) -> list[str]:
    return [str(member.value) for member in enum_class]


class MonitoredChat(Base):
    """Telegram group selected for monitoring."""

    __tablename__ = "monitored_chats"
    __table_args__ = (
        CheckConstraint(
            "consecutive_access_failures >= 0",
            name="access_failures_non_negative",
        ),
        Index(
            "idx_monitored_chats_active",
            "telegram_chat_id",
            postgresql_where=sql_text("status = 'active'"),
        ),
        Index(
            "idx_monitored_chats_verification_due",
            "next_verification_at",
            postgresql_where=sql_text("status <> 'disabled'"),
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    chat_type: Mapped[MonitoredChatType] = mapped_column(
        Enum(
            MonitoredChatType,
            name="monitored_chat_type",
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    status: Mapped[MonitoredChatStatus] = mapped_column(
        Enum(
            MonitoredChatStatus,
            name="monitored_chat_status",
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=MonitoredChatStatus.PENDING_VERIFICATION.value,
    )
    added_by_telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_verification_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    consecutive_access_failures: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=sql_text("0")
    )
    last_message_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )

    processing_jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="monitored_chat",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    detected_questions: Mapped[list[DetectedQuestion]] = relationship(
        back_populates="monitored_chat"
    )


class ProcessingJob(Base):
    """Durable PostgreSQL classification queue item."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        UniqueConstraint(
            "telegram_chat_id",
            "telegram_message_id",
            name="uq_processing_jobs_telegram_message",
        ),
        Index(
            "idx_processing_jobs_claim",
            "next_attempt_at",
            "created_at",
            postgresql_where=sql_text("status IN ('pending', 'retry')"),
        ),
        Index(
            "idx_processing_jobs_chain_load",
            "next_attempt_at",
            "created_at",
            postgresql_where=sql_text(
                "status IN ('awaiting_relevant_processing', 'awaiting_reply_context') "
                "AND reply_chain_snapshot IS NULL"
            ),
        ),
        Index(
            "idx_processing_jobs_downstream",
            "next_attempt_at",
            "created_at",
            postgresql_where=sql_text(
                "status IN ('awaiting_relevant_processing', 'awaiting_reply_context') "
                "AND reply_chain_snapshot IS NOT NULL"
            ),
        ),
        Index("idx_processing_jobs_expiry", "expires_at"),
    )

    id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    monitored_chat_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monitored_chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic_id: Mapped[int | None] = mapped_column(BigInteger)
    sender_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    sender_display_name: Mapped[str | None] = mapped_column(String(255))
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ProcessingJobStatus] = mapped_column(
        Enum(
            ProcessingJobStatus,
            name="processing_job_status",
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=ProcessingJobStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=sql_text("0")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    reply_chain_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("NOW() + INTERVAL '24 hours'"),
    )

    monitored_chat: Mapped[MonitoredChat] = relationship(back_populates="processing_jobs")


class ClassificationRun(Base):
    """Metadata and API usage for one classification stage."""

    __tablename__ = "classification_runs"
    __table_args__ = (
        CheckConstraint("stage IN (1, 2)", name="stage_valid"),
        UniqueConstraint(
            "telegram_chat_id",
            "telegram_message_id",
            "stage",
            name="uq_classification_runs_message_stage",
        ),
        Index("idx_classification_runs_created_at", "created_at"),
    )

    id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stage: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    result: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    reason_code: Mapped[str | None] = mapped_column(String(100))
    context_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("FALSE")
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=sql_text("0")
    )
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )


class DetectedQuestion(Base):
    """Relevant question retained for the operator workflow."""

    __tablename__ = "detected_questions"
    __table_args__ = (
        UniqueConstraint(
            "telegram_chat_id",
            "telegram_message_id",
            name="uq_detected_questions_telegram_message",
        ),
        Index("idx_detected_questions_operator_queue", "status", "detected_at"),
        Index("idx_detected_questions_expiry", "expires_at"),
    )

    id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    monitored_chat_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("monitored_chats.id", ondelete="SET NULL"),
        nullable=True,
    )
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic_id: Mapped[int | None] = mapped_column(BigInteger)
    topic_title: Mapped[str | None] = mapped_column(String(255))
    author_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    author_display_name: Mapped[str | None] = mapped_column(String(255))
    telegram_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str | None] = mapped_column(Text)
    source_language: Mapped[str | None] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    status: Mapped[QuestionStatus] = mapped_column(
        Enum(QuestionStatus, name="question_status", values_callable=_enum_values),
        nullable=False,
        server_default=QuestionStatus.DETECTED.value,
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sql_text("NOW() + INTERVAL '60 days'"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )

    monitored_chat: Mapped[MonitoredChat | None] = relationship(back_populates="detected_questions")
    chain_messages: Mapped[list[QuestionChainMessage]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    bot_notification: Mapped[BotNotification | None] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    reply_versions: Mapped[list[ReplyVersion]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    outbound_commands: Mapped[list[OutboundCommand]] = relationship(back_populates="question")


class QuestionChainMessage(Base):
    """Immutable snapshot of one message in a relevant reply chain."""

    __tablename__ = "question_chain_messages"
    __table_args__ = (
        CheckConstraint("position BETWEEN 0 AND 9", name="position_valid"),
        UniqueConstraint("question_id", "position", name="uq_chain_messages_question_position"),
        UniqueConstraint(
            "question_id",
            "telegram_message_id",
            name="uq_chain_messages_question_message",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    question_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("detected_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reply_to_message_id: Mapped[int | None] = mapped_column(BigInteger)
    author_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    author_display_name: Mapped[str | None] = mapped_column(String(255))
    telegram_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str | None] = mapped_column(Text)
    source_language: Mapped[str | None] = mapped_column(String(10))
    translation_status: Mapped[str] = mapped_column(String(30), nullable=False)
    is_target: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("FALSE")
    )

    question: Mapped[DetectedQuestion] = relationship(back_populates="chain_messages")


class BotNotification(Base):
    """Reliable operator notification delivery state."""

    __tablename__ = "bot_notifications"

    id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    question_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("detected_questions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    operator_telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bot_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bot_message_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=sql_text("0")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )

    question: Mapped[DetectedQuestion] = relationship(back_populates="bot_notification")


class OperatorSession(Base):
    """Persistent aiogram FSM state and active question for one operator."""

    __tablename__ = "operator_sessions"

    operator_telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    state: Mapped[str | None] = mapped_column(String(255))
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    active_question_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("detected_questions.id", ondelete="SET NULL"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )


class ReplyVersion(Base):
    """Immutable operator-authored reply version."""

    __tablename__ = "reply_versions"
    __table_args__ = (
        CheckConstraint("action IN ('draft', 'sent', 'edited')", name="action_valid"),
        UniqueConstraint(
            "question_id", "version_number", name="uq_reply_versions_question_version"
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    question_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("detected_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )

    question: Mapped[DetectedQuestion] = relationship(back_populates="reply_versions")


class OutboundCommand(Base):
    """Idempotent MTProto send or edit command."""

    __tablename__ = "outbound_commands"
    __table_args__ = (
        CheckConstraint(
            "command_type IN ('send_reply', 'edit_reply')",
            name="command_type_valid",
        ),
        Index(
            "idx_outbound_commands_claim",
            "next_attempt_at",
            "created_at",
            postgresql_where=sql_text("status = 'pending'"),
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    question_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("detected_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    command_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reply_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic_id: Mapped[int | None] = mapped_column(BigInteger)
    sent_message_id: Mapped[int | None] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[OutboundCommandStatus] = mapped_column(
        Enum(
            OutboundCommandStatus,
            name="outbound_command_status",
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=OutboundCommandStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=sql_text("0")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    question: Mapped[DetectedQuestion] = relationship(back_populates="outbound_commands")


class TranslationLanguage(Base):
    """Installed and enabled local translation language."""

    __tablename__ = "translation_languages"
    __table_args__ = (
        CheckConstraint(
            "installation_status IN ('not_installed', 'installing', 'installed', 'failed')",
            name="installation_status_valid",
        ),
        CheckConstraint("NOT is_required OR is_enabled", name="required_enabled"),
    )

    language_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("FALSE")
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_text("FALSE")
    )
    installation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )


class TranslationManagerJob(Base):
    """Durable allow-listed request for the isolated translation control plane."""

    __tablename__ = "translation_manager_jobs"
    __table_args__ = (
        Index(
            "idx_translation_manager_jobs_claim",
            "created_at",
            postgresql_where=sql_text("status = 'pending'"),
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    action: Mapped[TranslationManagerAction] = mapped_column(
        Enum(
            TranslationManagerAction,
            name="translation_manager_action",
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    language_code: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[TranslationManagerJobStatus] = mapped_column(
        Enum(
            TranslationManagerJobStatus,
            name="translation_manager_job_status",
            values_callable=_enum_values,
        ),
        nullable=False,
        server_default=TranslationManagerJobStatus.PENDING.value,
    )
    result_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiUsageDaily(Base):
    """Daily aggregate of classification API usage and estimated cost."""

    __tablename__ = "api_usage_daily"

    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    request_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    input_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=sql_text("0")
    )
    output_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=sql_text("0")
    )
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=sql_text("0")
    )


class ApplicationSetting(Base):
    """Durable application setting represented as JSON."""

    __tablename__ = "application_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )


class ServiceHeartbeat(Base):
    """Last database-visible liveness signal from an application service."""

    __tablename__ = "service_heartbeats"

    service: Mapped[str] = mapped_column(String(50), primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )


class AlertCondition(Base):
    """Durable start time for a currently failing monitored condition."""

    __tablename__ = "alert_conditions"

    condition_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    failing_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )


class OperationalAlert(Base):
    """Content-free, idempotent operator alert delivery record."""

    __tablename__ = "operational_alerts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sending', 'retry', 'sent', 'failed')",
            name="status_valid",
        ),
        Index(
            "idx_operational_alerts_claim",
            "next_attempt_at",
            "created_at",
            postgresql_where=sql_text("status IN ('pending', 'retry')"),
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    deduplication_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_text("'{}'::jsonb")
    )
    operator_telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=sql_text("0")
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sql_text("NOW()")
    )
