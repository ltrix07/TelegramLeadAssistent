"""Main menu handlers for the operator bot."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards.main_menu import build_main_menu_keyboard
from app.bot.status import StatusRepository, TranslatorHealthProbe, render_status
from app.config import AppSettings

router = Router(name="operator-menu")


@router.message(CommandStart())
async def show_main_menu(message: Message) -> None:
    """Show the private operator menu."""
    await message.answer("Главное меню", reply_markup=build_main_menu_keyboard())


@router.message(F.text == "Главное меню")
async def return_to_main_menu(message: Message) -> None:
    """Restore the persistent main menu after a picker flow."""
    await message.answer("Главное меню", reply_markup=build_main_menu_keyboard())


@router.message(Command("status"))
@router.message(F.text == "Состояние системы")
async def show_status(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: AppSettings,
) -> None:
    """Show explicit component failures and content-free operational aggregates."""
    translator_healthy = await TranslatorHealthProbe(
        settings.translation_base_url,
        settings.translation_request_timeout_seconds,
    ).healthy()
    try:
        async with session_factory() as session:
            snapshot = await StatusRepository(session).collect(
                translator_healthy=translator_healthy
            )
    except (SQLAlchemyError, RuntimeError):
        await message.answer(
            "Состояние системы\n"
            "PostgreSQL: НЕДОСТУПЕН\n"
            "MTProto: состояние неизвестно\n"
            "Classifier: состояние неизвестно\n"
            f"Translator: {'работает' if translator_healthy else 'НЕДОСТУПЕН'}"
        )
        return
    await message.answer(render_status(snapshot))
