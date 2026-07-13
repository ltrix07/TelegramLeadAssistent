"""Inline keyboards for local translation language management."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.domain.enums import TranslationManagerAction


def language_action_data(action: TranslationManagerAction | str, language_code: str) -> str:
    """Build compact callback data from an allow-listed action and language code."""
    action_value = action.value if isinstance(action, TranslationManagerAction) else action
    return f"lang:{action_value}:{language_code}"


def build_language_actions_keyboard(
    *, language_code: str, is_required: bool, is_enabled: bool, is_installed: bool
) -> InlineKeyboardMarkup | None:
    """Build only actions valid for the language's current durable state."""
    if is_required:
        return None
    if not is_installed:
        buttons = [
            InlineKeyboardButton(
                text="Установить",
                callback_data=language_action_data("confirm_install", language_code),
            )
        ]
    else:
        toggle = TranslationManagerAction.DISABLE if is_enabled else TranslationManagerAction.ENABLE
        buttons = [
            InlineKeyboardButton(
                text="Отключить" if is_enabled else "Включить",
                callback_data=language_action_data(toggle, language_code),
            ),
            InlineKeyboardButton(
                text="Удалить",
                callback_data=language_action_data("confirm_delete", language_code),
            ),
        ]
    return InlineKeyboardMarkup(inline_keyboard=[[button] for button in buttons])


def build_language_confirmation_keyboard(
    action: TranslationManagerAction, language_code: str
) -> InlineKeyboardMarkup:
    """Require an explicit confirmation for install and model deletion."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить",
                    callback_data=language_action_data(action, language_code),
                ),
                InlineKeyboardButton(
                    text="Отменить", callback_data=language_action_data("cancel", language_code)
                ),
            ]
        ]
    )
