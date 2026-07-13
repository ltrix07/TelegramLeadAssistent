"""Dismiss and explicit reopen callbacks for operator notifications."""

from __future__ import annotations

from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards.notifications import (
    build_dismissed_question_controls,
    build_question_controls,
)
from app.database.repositories.question_feedback import (
    QuestionFeedbackRepository,
    QuestionFeedbackUnavailableError,
)

router = Router(name="question-feedback")


def _question_id(data: str | None) -> UUID | None:
    if data is None:
        return None
    try:
        prefix, action, raw_question_id = data.split(":", maxsplit=2)
        if prefix != "question" or action not in {"dismiss", "reopen"}:
            return None
        return UUID(raw_question_id)
    except (ValueError, TypeError):
        return None


@router.callback_query(F.data.startswith("question:dismiss:"))
async def dismiss_question(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Record false-positive feedback without retaining any additional text."""
    question_id = _question_id(callback.data)
    if question_id is None:
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    try:
        async with session_factory.begin() as session:
            await QuestionFeedbackRepository(session).dismiss(question_id)
    except QuestionFeedbackUnavailableError:
        await callback.answer("Этот вопрос больше недоступен.", show_alert=True)
        return
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=build_dismissed_question_controls(question_id)
        )
    await callback.answer("Отмечено как нерелевантное.")


@router.callback_query(F.data.startswith("question:reopen:"))
async def reopen_question(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Explicitly return a dismissed question to the detected queue."""
    question_id = _question_id(callback.data)
    if question_id is None:
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    try:
        async with session_factory.begin() as session:
            await QuestionFeedbackRepository(session).reopen(question_id)
    except QuestionFeedbackUnavailableError:
        await callback.answer("Этот вопрос больше недоступен.", show_alert=True)
        return
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=build_question_controls(question_id))
    await callback.answer("Вопрос снова открыт.")


__all__ = ["router"]
