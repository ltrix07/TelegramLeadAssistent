"""Manual review UI for normalized outbound failures."""

from __future__ import annotations

from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards.notifications import build_original_message_url
from app.bot.keyboards.outbound_failures import build_outbound_failure_keyboard
from app.database.repositories.outbound_commands import (
    OutboundCommandRepository,
    OutboundFailure,
    OutboundRetryUnavailableError,
)
from app.domain.enums import OutboundCommandStatus

router = Router(name="outbound-failures")

ERROR_LABELS = {
    "SOURCE_MESSAGE_DELETED": "Исходное сообщение удалено",
    "CHAT_WRITE_FORBIDDEN": "Отправка в чат запрещена",
    "TOPIC_CLOSED": "Тема закрыта",
    "TOPIC_DELETED": "Тема удалена",
    "FLOOD_WAIT": "Telegram временно ограничил отправку",
    "ACCESS_LOST": "Доступ к чату потерян",
    "UNKNOWN_ERROR": "Временная ошибка Telegram",
    "INVALID_EDIT_TARGET": "Сохранённый ответ недоступен для изменения",
}


def _render_failure(failure: OutboundFailure) -> str:
    error = ERROR_LABELS.get(failure.error_code, "Неизвестная ошибка отправки")
    if failure.status is OutboundCommandStatus.NEEDS_REVIEW:
        action = "Требуется ручная проверка. Повтор отключён из-за риска дубликата."
    elif failure.status is OutboundCommandStatus.PENDING:
        action = (
            f"Безопасный повтор уже запланирован: {failure.next_attempt_at:%Y-%m-%d %H:%M:%S %Z}."
        )
    elif failure.retry_allowed:
        action = "Доступен безопасный повтор изменения ответа."
    else:
        action = "Повтор недоступен: ошибка постоянная или результат нельзя подтвердить."
    operation = "изменение ответа" if failure.command_type == "edit_reply" else "отправка ответа"
    return (
        "<b>Ошибка исходящей команды</b>\n"
        f"<b>Операция:</b> {operation}\n"
        f"<b>Ошибка:</b> {escape(error)}\n"
        f"<b>Действие:</b> {escape(action)}"
    )


def _failure_keyboard(failure: OutboundFailure) -> InlineKeyboardMarkup | None:
    original_url = build_original_message_url(
        chat_username=failure.chat_username,
        telegram_chat_id=failure.telegram_chat_id,
        telegram_message_id=failure.source_message_id,
        topic_id=failure.topic_id,
    )
    answer_url = None
    if failure.sent_message_id is not None:
        answer_url = build_original_message_url(
            chat_username=failure.chat_username,
            telegram_chat_id=failure.telegram_chat_id,
            telegram_message_id=failure.sent_message_id,
            topic_id=failure.topic_id,
        )
    return build_outbound_failure_keyboard(
        failure.command_id,
        original_url=original_url,
        answer_url=answer_url,
        retry_allowed=failure.retry_allowed,
    )


@router.message(F.text == "Ошибки отправки")
async def show_outbound_failures(
    message: Message, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Show bounded normalized cards for active outbound failures."""
    async with session_factory() as session:
        failures = await OutboundCommandRepository(session).list_failures()
    if not failures:
        await message.answer("Ошибок исходящих команд нет.")
        return
    for failure in failures:
        await message.answer(
            _render_failure(failure),
            parse_mode="HTML",
            reply_markup=_failure_keyboard(failure),
        )


@router.callback_query(F.data.startswith("outbound-retry:"))
async def retry_outbound_failure(
    callback: CallbackQuery, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Requeue only a repository-validated safe retry."""
    try:
        command_id = UUID((callback.data or "").removeprefix("outbound-retry:"))
    except (ValueError, TypeError):
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    try:
        async with session_factory.begin() as session:
            await OutboundCommandRepository(session).retry_failed(command_id)
    except OutboundRetryUnavailableError:
        await callback.answer("Повтор недоступен или уже запланирован.", show_alert=True)
        return
    await callback.answer("Безопасный повтор поставлен в очередь.")
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)


__all__ = ["router"]
