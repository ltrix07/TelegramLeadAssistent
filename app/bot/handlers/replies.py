"""Manual draft, preview, edit, and cancel operator flow."""

from __future__ import annotations

from html import escape
from uuid import UUID

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards.replies import (
    build_draft_conflict_keyboard,
    build_draft_preview_keyboard,
    build_sent_edit_keyboard,
)
from app.bot.states import ReplyFlow
from app.database.models import DetectedQuestion
from app.database.repositories.operator_sessions import OperatorSessionRepository
from app.database.repositories.outbound_commands import (
    ConfirmationUnavailableError,
    OutboundCommandRepository,
    SentEditPreview,
)
from app.database.repositories.reply_drafts import (
    DraftUnavailableError,
    ReplyDraftRepository,
    StoredDraft,
)
from app.domain.enums import QuestionStatus

router = Router(name="reply-drafts")


def _parse_callback(data: str | None) -> tuple[str, UUID] | None:
    if data is None:
        return None
    try:
        prefix, action, raw_question_id = data.split(":", maxsplit=2)
        if prefix not in {"question", "draft"}:
            return None
        return action, UUID(raw_question_id)
    except (ValueError, TypeError):
        return None


def _render_preview(draft: StoredDraft) -> str:
    topic = draft.destination.topic_title or "Без темы"
    return (
        f"<b>Чат:</b> {escape(draft.destination.chat_title)}\n"
        f"<b>Тема:</b> {escape(topic)}\n\n"
        f"<b>Предпросмотр ответа:</b>\n<pre>{escape(draft.text)}</pre>"
    )


def _render_sent_edit_preview(preview: SentEditPreview) -> str:
    return (
        f"<b>Текущий ответ:</b>\n<pre>{escape(preview.old_text)}</pre>\n\n"
        f"<b>Новый ответ:</b>\n<pre>{escape(preview.new_text)}</pre>"
    )


@router.callback_query(F.data.startswith("question:edit-sent:"))
async def start_sent_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing an already sent reply by opaque question ID."""
    parsed = _parse_callback(callback.data)
    if parsed is None:
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    await state.set_state(ReplyFlow.waiting_for_sent_edit)
    await state.set_data({"question_id": str(parsed[1])})
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer("Введите новый текст отправленного ответа.")


@router.message(ReplyFlow.waiting_for_sent_edit, F.text)
async def accept_sent_edit(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Persist and display old/new text without changing the sent final state."""
    if message.text is None:
        return
    data = await state.get_data()
    try:
        question_id = UUID(str(data["question_id"]))
        async with session_factory.begin() as session:
            preview = await OutboundCommandRepository(session).prepare_edit(
                question_id, message.text
            )
    except (KeyError, ValueError, TypeError, ConfirmationUnavailableError):
        await state.clear()
        await message.answer("Отправленный ответ больше недоступен для изменения.")
        return
    await state.set_state(ReplyFlow.waiting_for_sent_edit_confirmation)
    await message.answer(
        _render_sent_edit_preview(preview),
        parse_mode=ParseMode.HTML,
        reply_markup=build_sent_edit_keyboard(question_id),
    )


@router.callback_query(F.data.startswith("sent-edit:"))
async def confirm_sent_edit(
    callback: CallbackQuery,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Create one durable edit command or cancel the pending confirmation."""
    try:
        prefix, action, raw_question_id = (callback.data or "").split(":", maxsplit=2)
        if prefix != "sent-edit" or action not in {"confirm", "cancel"}:
            raise ValueError
        question_id = UUID(raw_question_id)
    except (ValueError, TypeError):
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    if action == "cancel":
        await state.clear()
        await callback.answer("Изменение отменено.")
        if isinstance(callback.message, Message):
            await callback.message.edit_reply_markup(reply_markup=None)
        return
    try:
        async with session_factory.begin() as session:
            result = await OutboundCommandRepository(session).confirm_edit(question_id)
    except ConfirmationUnavailableError:
        await callback.answer("Изменение больше недоступно.", show_alert=True)
        return
    await state.clear()
    await callback.answer("Изменение поставлено в очередь.")
    if result.created and isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=None)


async def _open_question(
    callback: CallbackQuery,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    question_id: UUID,
    *,
    replace: bool,
) -> None:
    operator_id = callback.from_user.id
    async with session_factory.begin() as session:
        sessions = OperatorSessionRepository(session)
        active = await sessions.get_active_question(operator_id)
        if active not in (None, question_id) and not replace:
            assert active is not None
            if isinstance(callback.message, Message):
                await callback.message.answer(
                    "Сейчас открыт черновик для другого вопроса.",
                    reply_markup=build_draft_conflict_keyboard(active, question_id),
                )
            await callback.answer()
            return
        if replace and active not in (None, question_id):
            assert active is not None
            try:
                await ReplyDraftRepository(session).cancel(active)
            except DraftUnavailableError:
                pass
        try:
            await ReplyDraftRepository(session).open(question_id)
        except DraftUnavailableError:
            await callback.answer("Этот вопрос больше недоступен.", show_alert=True)
            return
        await sessions.open_question(operator_id, question_id, replace=replace)
    await state.set_state(ReplyFlow.waiting_for_draft)
    await state.set_data({"question_id": str(question_id)})
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer("Введите текст ответа.")


@router.callback_query(F.data.startswith("question:reply:"))
async def start_reply(
    callback: CallbackQuery,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Bind manual text entry to exactly one detected question."""
    parsed = _parse_callback(callback.data)
    if parsed is None:
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    async with session_factory() as session:
        status = await session.scalar(
            select(DetectedQuestion.status).where(DetectedQuestion.id == parsed[1])
        )
    if status is QuestionStatus.SENT:
        await state.set_state(ReplyFlow.waiting_for_sent_edit)
        await state.set_data({"question_id": str(parsed[1])})
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer("Введите новый текст отправленного ответа.")
        return
    await _open_question(callback, state, session_factory, parsed[1], replace=False)


@router.message(ReplyFlow.waiting_for_draft, F.text)
async def accept_draft(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Persist an immutable version and render its exact outgoing text."""
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    try:
        question_id = UUID(str(data["question_id"]))
    except (KeyError, ValueError, TypeError):
        await state.clear()
        await message.answer("Черновик не найден. Откройте вопрос заново.")
        return
    try:
        async with session_factory.begin() as session:
            sessions = OperatorSessionRepository(session)
            if await sessions.get_active_question(message.from_user.id) != question_id:
                raise DraftUnavailableError
            draft = await ReplyDraftRepository(session).create_version(question_id, message.text)
    except DraftUnavailableError:
        await state.clear()
        await message.answer("Этот черновик больше недоступен.")
        return
    await state.set_state(ReplyFlow.waiting_for_send_confirmation)
    await message.answer(
        _render_preview(draft),
        parse_mode=ParseMode.HTML,
        reply_markup=build_draft_preview_keyboard(question_id),
    )


@router.callback_query(F.data.startswith("draft:"))
async def manage_draft(
    callback: CallbackQuery,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Edit, cancel, resume, or safely defer sending a stored draft."""
    parsed = _parse_callback(callback.data)
    if parsed is None:
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    action, question_id = parsed
    if action == "replace":
        await _open_question(callback, state, session_factory, question_id, replace=True)
        return
    if action == "continue":
        async with session_factory.begin() as session:
            sessions = OperatorSessionRepository(session)
            if await sessions.get_active_question(callback.from_user.id) != question_id:
                await callback.answer("Этот черновик больше недоступен.", show_alert=True)
                return
            draft = await ReplyDraftRepository(session).latest(question_id)
        if draft is not None and isinstance(callback.message, Message):
            await state.set_state(ReplyFlow.waiting_for_send_confirmation)
            await state.set_data({"question_id": str(question_id)})
            await callback.message.answer(
                _render_preview(draft),
                parse_mode=ParseMode.HTML,
                reply_markup=build_draft_preview_keyboard(question_id),
            )
        elif isinstance(callback.message, Message):
            await state.set_state(ReplyFlow.waiting_for_draft)
            await state.set_data({"question_id": str(question_id)})
            await callback.message.answer("Введите текст ответа.")
        await callback.answer()
        return
    if action == "confirm":
        try:
            async with session_factory.begin() as session:
                sessions = OperatorSessionRepository(session)
                if await sessions.get_active_question(callback.from_user.id) != question_id:
                    raise ConfirmationUnavailableError
                result = await OutboundCommandRepository(session).confirm_send(question_id)
                await sessions.clear_active_question(callback.from_user.id)
        except ConfirmationUnavailableError:
            await callback.answer("Этот черновик больше недоступен.", show_alert=True)
            return
        await state.clear()
        await callback.answer("Ответ поставлен в очередь на отправку.")
        if result.created and isinstance(callback.message, Message):
            await callback.message.edit_reply_markup(reply_markup=None)
        return
    try:
        async with session_factory.begin() as session:
            sessions = OperatorSessionRepository(session)
            if await sessions.get_active_question(callback.from_user.id) != question_id:
                raise DraftUnavailableError
            drafts = ReplyDraftRepository(session)
            if action == "edit":
                await drafts.reopen_for_edit(question_id)
            elif action == "cancel":
                await drafts.cancel(question_id)
                await sessions.clear_active_question(callback.from_user.id)
            else:
                await callback.answer("Некорректное действие.", show_alert=True)
                return
    except DraftUnavailableError:
        await callback.answer("Этот черновик больше недоступен.", show_alert=True)
        return
    if action == "edit":
        await state.set_state(ReplyFlow.waiting_for_draft)
        await state.set_data({"question_id": str(question_id)})
        await callback.answer()
        if isinstance(callback.message, Message):
            await callback.message.answer("Введите новый текст ответа.")
    else:
        await state.clear()
        await callback.answer("Черновик отменён.")
        if isinstance(callback.message, Message):
            await callback.message.edit_reply_markup(reply_markup=None)


__all__ = ["router"]
