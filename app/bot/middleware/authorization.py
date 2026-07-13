"""Authorization middleware for the private operator bot."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class OperatorAuthorizationMiddleware(BaseMiddleware):
    """Allow bot updates only from the configured operator."""

    def __init__(self, operator_user_id: int) -> None:
        self._operator_user_id = operator_user_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Reject unauthorized messages and callbacks before routing."""
        user = data.get("event_from_user")
        if user is not None and user.id == self._operator_user_id:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer("Доступ запрещён.", show_alert=True)
        elif isinstance(event, Message):
            await event.answer("Доступ запрещён.")
        return None
