"""Keyboards for the operator bot main menu."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

MAIN_MENU_BUTTONS = (
    "Найденные вопросы",
    "Отслеживаемые чаты",
    "Перевод",
    "Расход API",
    "Состояние системы",
    "Ошибки отправки",
)


def build_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Build the persistent operator main menu."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MAIN_MENU_BUTTONS[0])],
            [KeyboardButton(text=MAIN_MENU_BUTTONS[1])],
            [
                KeyboardButton(text=MAIN_MENU_BUTTONS[2]),
                KeyboardButton(text=MAIN_MENU_BUTTONS[3]),
            ],
            [
                KeyboardButton(text=MAIN_MENU_BUTTONS[4]),
                KeyboardButton(text=MAIN_MENU_BUTTONS[5]),
            ],
        ],
        resize_keyboard=True,
    )
