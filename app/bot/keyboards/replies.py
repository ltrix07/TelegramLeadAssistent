"""Inline keyboards for manual reply composition."""

from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_draft_preview_keyboard(question_id: UUID) -> InlineKeyboardMarkup:
    """Offer only actions that are safe before outbound sending exists."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить",
                    callback_data=f"draft:confirm:{question_id}",
                ),
                InlineKeyboardButton(
                    text="Изменить",
                    callback_data=f"draft:edit:{question_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отменить",
                    callback_data=f"draft:cancel:{question_id}",
                )
            ],
        ]
    )


def build_draft_conflict_keyboard(
    active_question_id: UUID, requested_question_id: UUID
) -> InlineKeyboardMarkup:
    """Require an explicit choice before replacing an active question."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Продолжить текущий",
                    callback_data=f"draft:continue:{active_question_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отменить и открыть новый",
                    callback_data=f"draft:replace:{requested_question_id}",
                )
            ],
        ]
    )


def build_sent_edit_keyboard(question_id: UUID) -> InlineKeyboardMarkup:
    """Confirm or cancel an edit of an already sent Telegram reply."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить изменение",
                    callback_data=f"sent-edit:confirm:{question_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отменить",
                    callback_data=f"sent-edit:cancel:{question_id}",
                )
            ],
        ]
    )


__all__ = [
    "build_draft_conflict_keyboard",
    "build_draft_preview_keyboard",
    "build_sent_edit_keyboard",
]
