"""Operator workflow for selecting and managing monitored chats."""

from __future__ import annotations

from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards.chats import (
    CHAT_PICKER_REQUEST_ID,
    build_chat_actions_keyboard,
    build_chat_picker_keyboard,
)
from app.bot.keyboards.main_menu import build_main_menu_keyboard
from app.database.repositories import MonitoredChatRepository, NewMonitoredChat

router = Router(name="monitored-chats")


def _format_chat(chat: object) -> str:
    title = getattr(chat, "title")
    status = getattr(chat, "status").value
    return f"{title}\nСтатус: {status}"


async def _send_chat_list(
    message: Message, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        chats = await MonitoredChatRepository(session).list_all()
    if not chats:
        await message.answer("Отслеживаемых чатов пока нет.")
    for chat in chats:
        await message.answer(_format_chat(chat), reply_markup=build_chat_actions_keyboard(chat))


@router.message(F.text == "Отслеживаемые чаты")
async def show_monitored_chats(
    message: Message, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """List chats and offer the group picker."""
    await _send_chat_list(message, session_factory)
    await message.answer("Добавить чат:", reply_markup=build_chat_picker_keyboard())


@router.message(F.chat_shared)
async def add_shared_chat(
    message: Message, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Persist a group picker result for later MTProto verification."""
    shared = message.chat_shared
    if shared is None or shared.request_id != CHAT_PICKER_REQUEST_ID:
        await message.answer("Этот выбор чата не поддерживается.")
        return
    if message.from_user is None:
        await message.answer("Не удалось определить оператора.")
        return

    new_chat = NewMonitoredChat(
        telegram_chat_id=shared.chat_id,
        title=shared.title or f"Чат {shared.chat_id}",
        username=shared.username,
        added_by_telegram_user_id=message.from_user.id,
    )
    async with session_factory.begin() as session:
        chat, created = await MonitoredChatRepository(session).add_pending(new_chat)
    text = "Чат добавлен и ожидает проверки доступа." if created else "Этот чат уже добавлен."
    await message.answer(text, reply_markup=build_main_menu_keyboard())
    await message.answer(_format_chat(chat), reply_markup=build_chat_actions_keyboard(chat))


@router.callback_query(F.data.startswith("chat:"))
async def manage_chat(
    callback: CallbackQuery, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Persist pause, resume, and remove actions from a chat card."""
    if callback.data is None:
        return
    try:
        _, action, raw_chat_id = callback.data.split(":", maxsplit=2)
        chat_id = UUID(raw_chat_id)
    except (ValueError, TypeError):
        await callback.answer("Некорректное действие.", show_alert=True)
        return

    async with session_factory.begin() as session:
        repository = MonitoredChatRepository(session)
        if action == "pause":
            changed = await repository.pause(chat_id)
            result_text = "Чат приостановлен."
        elif action == "resume":
            changed = await repository.resume(chat_id)
            result_text = "Чат ожидает повторной проверки доступа."
        elif action == "remove":
            changed = await repository.remove(chat_id)
            result_text = "Чат удалён из мониторинга."
        else:
            await callback.answer("Некорректное действие.", show_alert=True)
            return

    await callback.answer(result_text if changed else "Состояние чата уже изменилось.")
    if isinstance(callback.message, Message):
        await callback.message.delete()
