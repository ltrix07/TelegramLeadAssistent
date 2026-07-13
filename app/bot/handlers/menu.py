"""Main menu handlers for the operator bot."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.bot.keyboards.main_menu import build_main_menu_keyboard

router = Router(name="operator-menu")


@router.message(CommandStart())
async def show_main_menu(message: Message) -> None:
    """Show the private operator menu."""
    await message.answer("Главное меню", reply_markup=build_main_menu_keyboard())


@router.message(F.text == "Главное меню")
async def return_to_main_menu(message: Message) -> None:
    """Restore the persistent main menu after a picker flow."""
    await message.answer("Главное меню", reply_markup=build_main_menu_keyboard())


@router.message(F.text == "Состояние системы")
async def show_health_placeholder(message: Message) -> None:
    """Show the health placeholder until component checks are implemented."""
    await message.answer("Состояние системы: проверка компонентов пока не реализована.")
