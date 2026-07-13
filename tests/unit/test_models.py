"""Tests for ORM metadata, constraints, indexes, and cascade definitions."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Enum, UniqueConstraint

from app.database.models import Base, DetectedQuestion, MonitoredChat
from app.domain.enums import (
    MonitoredChatStatus,
    MonitoredChatType,
    OutboundCommandStatus,
    ProcessingJobStatus,
    QuestionStatus,
)

EXPECTED_TABLES = {
    "api_usage_daily",
    "application_settings",
    "bot_notifications",
    "classification_runs",
    "detected_questions",
    "monitored_chats",
    "operator_sessions",
    "outbound_commands",
    "processing_jobs",
    "question_chain_messages",
    "reply_versions",
    "translation_languages",
    "translation_manager_jobs",
}


def _unique_column_sets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _foreign_key_ondelete(table_name: str, column_name: str) -> str | None:
    column = Base.metadata.tables[table_name].c[column_name]
    return next(iter(column.foreign_keys)).ondelete


def test_metadata_contains_all_agreed_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_duplicate_ingestion_and_idempotency_constraints_exist() -> None:
    assert ("telegram_chat_id", "telegram_message_id") in _unique_column_sets("processing_jobs")
    assert ("telegram_chat_id", "telegram_message_id", "stage") in _unique_column_sets(
        "classification_runs"
    )
    assert ("telegram_chat_id", "telegram_message_id") in _unique_column_sets("detected_questions")
    assert Base.metadata.tables["outbound_commands"].c.idempotency_key.unique is True


def test_postgresql_enum_types_store_spec_values() -> None:
    expected = {
        "monitored_chat_status": [item.value for item in MonitoredChatStatus],
        "monitored_chat_type": [item.value for item in MonitoredChatType],
        "processing_job_status": [item.value for item in ProcessingJobStatus],
        "question_status": [item.value for item in QuestionStatus],
        "outbound_command_status": [item.value for item in OutboundCommandStatus],
    }
    enum_columns = (
        Base.metadata.tables["monitored_chats"].c.status,
        Base.metadata.tables["monitored_chats"].c.chat_type,
        Base.metadata.tables["processing_jobs"].c.status,
        Base.metadata.tables["detected_questions"].c.status,
        Base.metadata.tables["outbound_commands"].c.status,
    )

    for column in enum_columns:
        assert isinstance(column.type, Enum)
        enum_name = column.type.name
        assert enum_name is not None
        assert column.type.enums == expected[enum_name]


def test_queue_indexes_are_partial_and_named() -> None:
    for table_name, index_name in (
        ("monitored_chats", "idx_monitored_chats_active"),
        ("processing_jobs", "idx_processing_jobs_claim"),
        ("outbound_commands", "idx_outbound_commands_claim"),
    ):
        index = next(
            item for item in Base.metadata.tables[table_name].indexes if item.name == index_name
        )
        assert index.dialect_options["postgresql"]["where"] is not None


def test_range_and_state_check_constraints_exist() -> None:
    checks = {
        constraint.name
        for table_name in (
            "classification_runs",
            "question_chain_messages",
            "reply_versions",
            "outbound_commands",
            "translation_languages",
        )
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_classification_runs_stage_valid",
        "ck_question_chain_messages_position_valid",
        "ck_reply_versions_action_valid",
        "ck_outbound_commands_command_type_valid",
        "ck_translation_languages_installation_status_valid",
        "ck_translation_languages_required_enabled",
    } <= checks


def test_database_and_orm_cascade_definitions_match_spec() -> None:
    assert _foreign_key_ondelete("processing_jobs", "monitored_chat_id") == "CASCADE"
    assert _foreign_key_ondelete("question_chain_messages", "question_id") == "CASCADE"
    assert _foreign_key_ondelete("bot_notifications", "question_id") == "CASCADE"
    assert _foreign_key_ondelete("reply_versions", "question_id") == "CASCADE"
    assert _foreign_key_ondelete("outbound_commands", "question_id") is None

    assert "delete-orphan" in MonitoredChat.processing_jobs.property.cascade
    assert "delete-orphan" in DetectedQuestion.chain_messages.property.cascade
    assert "delete-orphan" in DetectedQuestion.bot_notification.property.cascade
    assert "delete-orphan" in DetectedQuestion.reply_versions.property.cascade
    assert "delete" not in DetectedQuestion.outbound_commands.property.cascade


def test_raw_message_and_reply_text_columns_are_limited_to_agreed_tables() -> None:
    raw_text_columns = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name in {"message_text", "original_text", "translated_text", "text"}
    }
    assert raw_text_columns == {
        ("processing_jobs", "message_text"),
        ("detected_questions", "original_text"),
        ("detected_questions", "translated_text"),
        ("question_chain_messages", "original_text"),
        ("question_chain_messages", "translated_text"),
        ("reply_versions", "text"),
        ("outbound_commands", "text"),
    }
