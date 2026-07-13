"""Inline controls for operator question notifications."""

import re
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

PRIVATE_CHAT_ID_PREFIX = "-100"
PUBLIC_USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_]+")


def question_action_data(action: str, question_id: UUID) -> str:
    """Build callback data containing only an action and an opaque question ID."""
    return f"question:{action}:{question_id}"


def build_original_message_url(
    *,
    chat_username: str | None,
    telegram_chat_id: int,
    telegram_message_id: int,
    topic_id: int | None,
) -> str | None:
    """Build a public or private Telegram link to a target message when possible."""
    if telegram_message_id <= 0 or (topic_id is not None and topic_id <= 0):
        return None

    username = chat_username.removeprefix("@") if chat_username else None
    if username and PUBLIC_USERNAME_PATTERN.fullmatch(username):
        chat_path = username
    else:
        raw_chat_id = str(telegram_chat_id)
        if not raw_chat_id.startswith(PRIVATE_CHAT_ID_PREFIX):
            return None
        private_chat_id = raw_chat_id[len(PRIVATE_CHAT_ID_PREFIX) :]
        if not private_chat_id.isdigit() or int(private_chat_id) <= 0:
            return None
        chat_path = f"c/{private_chat_id}"

    topic_path = f"/{topic_id}" if topic_id is not None else ""
    return f"https://t.me/{chat_path}{topic_path}/{telegram_message_id}"


def build_question_controls(
    question_id: UUID, *, original_message_url: str | None = None
) -> InlineKeyboardMarkup:
    """Build controls that start or dismiss the manual operator workflow."""
    rows: list[list[InlineKeyboardButton]] = []
    if original_message_url is not None:
        rows.append([InlineKeyboardButton(text="Открыть оригинал", url=original_message_url)])
    rows.append(
        [
            InlineKeyboardButton(
                text="Ответить",
                callback_data=question_action_data("reply", question_id),
            ),
            InlineKeyboardButton(
                text="Не релевантно",
                callback_data=question_action_data("dismiss", question_id),
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_dismissed_question_controls(question_id: UUID) -> InlineKeyboardMarkup:
    """Show the only explicit transition allowed after dismissal."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Вернуть вопрос",
                    callback_data=question_action_data("reopen", question_id),
                )
            ]
        ]
    )


__all__ = [
    "build_original_message_url",
    "build_dismissed_question_controls",
    "build_question_controls",
    "question_action_data",
]
