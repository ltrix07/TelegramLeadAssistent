"""Fail-closed controls for outbound failure review."""

from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_outbound_failure_keyboard(
    command_id: UUID,
    *,
    original_url: str | None,
    answer_url: str | None,
    retry_allowed: bool,
) -> InlineKeyboardMarkup | None:
    """Build links and expose retry only when the repository permits it."""
    rows: list[list[InlineKeyboardButton]] = []
    links: list[InlineKeyboardButton] = []
    if original_url is not None:
        links.append(InlineKeyboardButton(text="Открыть оригинал", url=original_url))
    if answer_url is not None:
        links.append(InlineKeyboardButton(text="Открыть ответ", url=answer_url))
    if links:
        rows.append(links)
    if retry_allowed:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Повторить безопасно",
                    callback_data=f"outbound-retry:{command_id}",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


__all__ = ["build_outbound_failure_keyboard"]
