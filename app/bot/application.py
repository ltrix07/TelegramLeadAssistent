"""Aiogram application assembly and lifecycle."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.delivery import BotNotificationWorker
from app.bot.handlers.chats import router as chats_router
from app.bot.handlers.languages import router as languages_router
from app.bot.handlers.menu import router as menu_router
from app.bot.handlers.outbound_failures import router as outbound_failures_router
from app.bot.handlers.question_feedback import router as question_feedback_router
from app.bot.handlers.replies import router as replies_router
from app.bot.middleware.authorization import OperatorAuthorizationMiddleware
from app.bot.operational_alerts import OperationalAlertWorker
from app.bot.storage import PostgresOperatorStorage
from app.config import AppSettings


def create_dispatcher(
    operator_user_id: int,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    settings: AppSettings | None = None,
) -> Dispatcher:
    """Create an operator-only dispatcher with application routes."""
    storage = PostgresOperatorStorage(session_factory) if session_factory is not None else None
    dispatcher = Dispatcher(storage=storage)
    authorization = OperatorAuthorizationMiddleware(operator_user_id)
    dispatcher.message.outer_middleware(authorization)
    dispatcher.callback_query.outer_middleware(authorization)
    if session_factory is not None:
        dispatcher["session_factory"] = session_factory
    if settings is not None:
        dispatcher["settings"] = settings
    dispatcher.include_router(chats_router)
    dispatcher.include_router(languages_router)
    dispatcher.include_router(question_feedback_router)
    dispatcher.include_router(replies_router)
    dispatcher.include_router(outbound_failures_router)
    dispatcher.include_router(menu_router)
    return dispatcher


async def run_bot(
    token: str,
    operator_user_id: int,
    session_factory: async_sessionmaker[AsyncSession],
    settings: AppSettings | None = None,
) -> None:
    """Run the operator bot using long polling."""
    dispatcher = create_dispatcher(operator_user_id, session_factory, settings)
    async with Bot(token=token) as bot:
        notification_worker = BotNotificationWorker(session_factory, bot, operator_user_id)
        notification_task = asyncio.create_task(
            notification_worker.run_forever(), name="operator-notification-worker"
        )
        alert_worker = OperationalAlertWorker(session_factory, bot, operator_user_id)
        alert_task = asyncio.create_task(
            alert_worker.run_forever(), name="operational-alert-worker"
        )
        try:
            await dispatcher.start_polling(
                bot,
                allowed_updates=dispatcher.resolve_used_update_types(),
            )
        finally:
            notification_task.cancel()
            alert_task.cancel()
            await asyncio.gather(notification_task, alert_task, return_exceptions=True)
