"""Operator keyboards for monitored chat management."""

from uuid import UUID

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestChat,
    ReplyKeyboardMarkup,
)

from app.database.models import MonitoredChat
from app.domain.enums import MonitoredChatStatus

CHAT_PICKER_REQUEST_ID = 1


def build_chat_picker_keyboard() -> ReplyKeyboardMarkup:
    """Request a group or supergroup; Telegram excludes broadcast channels."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Выбрать группу",
                    request_chat=KeyboardButtonRequestChat(
                        request_id=CHAT_PICKER_REQUEST_ID,
                        chat_is_channel=False,
                        request_title=True,
                        request_username=True,
                    ),
                )
            ],
            [KeyboardButton(text="Главное меню")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def chat_action_data(action: str, chat_id: UUID) -> str:
    """Build compact callback data for one persisted chat."""
    return f"chat:{action}:{chat_id}"


def build_chat_actions_keyboard(chat: MonitoredChat) -> InlineKeyboardMarkup:
    """Build state-aware actions for a monitored chat."""
    if chat.status == MonitoredChatStatus.DISABLED:
        state_action = InlineKeyboardButton(
            text="Возобновить", callback_data=chat_action_data("resume", chat.id)
        )
    else:
        state_action = InlineKeyboardButton(
            text="Приостановить", callback_data=chat_action_data("pause", chat.id)
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [state_action],
            [
                InlineKeyboardButton(
                    text="Удалить", callback_data=chat_action_data("remove", chat.id)
                )
            ],
        ]
    )
