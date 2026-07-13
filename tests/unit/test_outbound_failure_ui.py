"""Unit coverage for fail-closed outbound failure review controls."""

from datetime import UTC, datetime
from uuid import uuid4

from app.bot.handlers.outbound_failures import _failure_keyboard, _render_failure
from app.database.repositories.outbound_commands import OutboundFailure
from app.domain.enums import OutboundCommandStatus


def _failure(
    *,
    status: OutboundCommandStatus,
    error_code: str,
    command_type: str = "send_reply",
    sent_message_id: int | None = None,
    retry_allowed: bool = False,
) -> OutboundFailure:
    return OutboundFailure(
        command_id=uuid4(),
        command_type=command_type,
        status=status,
        error_code=error_code,
        next_attempt_at=datetime(2026, 7, 12, 12, tzinfo=UTC),
        telegram_chat_id=-100123456,
        source_message_id=41,
        topic_id=7,
        sent_message_id=sent_message_id,
        chat_username=None,
        retry_allowed=retry_allowed,
    )


def test_ambiguous_failure_has_normalized_text_links_and_no_retry() -> None:
    failure = _failure(
        status=OutboundCommandStatus.NEEDS_REVIEW,
        error_code="UNKNOWN_ERROR",
    )

    rendered = _render_failure(failure)
    keyboard = _failure_keyboard(failure)

    assert "Временная ошибка Telegram" in rendered
    assert "риска дубликата" in rendered
    assert keyboard is not None
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["Открыть оригинал"]
    assert all(button.callback_data is None for button in buttons)


def test_flood_wait_has_no_manual_bypass() -> None:
    failure = _failure(
        status=OutboundCommandStatus.PENDING,
        error_code="FLOOD_WAIT",
    )

    rendered = _render_failure(failure)
    keyboard = _failure_keyboard(failure)

    assert "повтор уже запланирован" in rendered
    assert keyboard is not None
    assert all(button.callback_data is None for row in keyboard.inline_keyboard for button in row)


def test_permanent_failure_has_no_blind_retry() -> None:
    failure = _failure(
        status=OutboundCommandStatus.FAILED,
        error_code="SOURCE_MESSAGE_DELETED",
    )

    keyboard = _failure_keyboard(failure)

    assert keyboard is not None
    assert [button.text for row in keyboard.inline_keyboard for button in row] == [
        "Открыть оригинал"
    ]


def test_safe_edit_retry_includes_original_and_answer_controls() -> None:
    failure = _failure(
        status=OutboundCommandStatus.FAILED,
        error_code="UNKNOWN_ERROR",
        command_type="edit_reply",
        sent_message_id=99,
        retry_allowed=True,
    )

    keyboard = _failure_keyboard(failure)

    assert keyboard is not None
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert [button.text for button in buttons] == [
        "Открыть оригинал",
        "Открыть ответ",
        "Повторить безопасно",
    ]
    assert buttons[-1].callback_data == f"outbound-retry:{failure.command_id}"
