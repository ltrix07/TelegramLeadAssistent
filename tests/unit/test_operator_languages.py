"""Tests for the operator translation language UI."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from app.bot.handlers.languages import _effective_status, _format_language, manage_language
from app.bot.keyboards.languages import (
    build_language_actions_keyboard,
    build_language_confirmation_keyboard,
)
from app.database.models import TranslationLanguage, TranslationManagerJob
from app.domain.enums import TranslationManagerAction, TranslationManagerJobStatus


def make_callback(data: str, *, with_message: bool = False) -> CallbackQuery:
    message = None
    if with_message:
        message = Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=42, type="private"),
            from_user=User(id=42, is_bot=False, first_name="Operator"),
            text="language",
        )
    return CallbackQuery(
        id="callback-id",
        from_user=User(id=42, is_bot=False, first_name="Operator"),
        chat_instance="chat-instance",
        data=data,
        message=message,
    )


def test_required_language_has_no_mutating_actions() -> None:
    keyboard = build_language_actions_keyboard(
        language_code="ru", is_required=True, is_enabled=True, is_installed=True
    )

    assert keyboard is None


def test_available_and_installed_languages_have_state_appropriate_actions() -> None:
    available = build_language_actions_keyboard(
        language_code="de", is_required=False, is_enabled=False, is_installed=False
    )
    installed = build_language_actions_keyboard(
        language_code="de", is_required=False, is_enabled=True, is_installed=True
    )

    assert available is not None
    assert [button.text for row in available.inline_keyboard for button in row] == ["Установить"]
    assert installed is not None
    assert [button.text for row in installed.inline_keyboard for button in row] == [
        "Отключить",
        "Удалить",
    ]


def test_install_and_delete_require_confirmation() -> None:
    keyboard = build_language_confirmation_keyboard(TranslationManagerAction.DELETE, "de")

    assert [button.text for button in keyboard.inline_keyboard[0]] == [
        "Подтвердить",
        "Отменить",
    ]
    assert keyboard.inline_keyboard[0][0].callback_data == "lang:delete:de"


@pytest.mark.parametrize(
    ("job_status", "expected"),
    [
        (TranslationManagerJobStatus.PENDING, "installing"),
        (TranslationManagerJobStatus.PROCESSING, "installing"),
        (TranslationManagerJobStatus.FAILED, "failed"),
        (TranslationManagerJobStatus.SUCCEEDED, "installed"),
    ],
)
def test_install_job_state_is_reflected(
    job_status: TranslationManagerJobStatus, expected: str
) -> None:
    language = TranslationLanguage(
        language_code="de", display_name="German", installation_status="installed", is_enabled=True
    )
    job = TranslationManagerJob(
        action=TranslationManagerAction.INSTALL,
        status=job_status,
        language_code="de",
    )

    assert _effective_status(language, job) == expected


def test_failed_job_is_visible_in_language_card() -> None:
    language = TranslationLanguage(
        language_code="de", display_name="German", installation_status="installed", is_enabled=True
    )
    job = TranslationManagerJob(
        action=TranslationManagerAction.DISABLE,
        status=TranslationManagerJobStatus.FAILED,
        language_code="de",
    )

    assert "Состояние: ошибка" in _format_language("de", "German", language, job)


@pytest.mark.asyncio
async def test_required_language_callback_is_rejected_before_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback = make_callback("lang:delete:ru")
    answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)

    await manage_language(callback, AsyncMock())

    answer.assert_awaited_once_with("Обязательный язык нельзя изменить.", show_alert=True)


@pytest.mark.asyncio
async def test_install_callback_shows_confirmation_without_enqueuing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback = make_callback("lang:confirm_install:de", with_message=True)
    callback_answer = AsyncMock()
    message_answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    monkeypatch.setattr(Message, "answer", message_answer)

    await manage_language(callback, AsyncMock())

    message_answer.assert_awaited_once()
    call = message_answer.await_args
    assert call is not None
    text = call.args[0]
    assert "Язык: German" in text
    assert "установить переводческие пакеты" in text
    callback_answer.assert_awaited_once_with()
