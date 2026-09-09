"""Aiogram application assembly and lifecycle."""

from __future__ import annotations

import asyncio
import logging

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
from app.database.health import run_heartbeat
from app.logging import log_event

logger = logging.getLogger(__name__)


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
    """Run the operator bot using long polling.

    Polling and the background delivery workers run as peers. If a background worker's
    ``run_forever`` exits — normally or with an exception — polling is stopped and the
    failure is re-raised so the process dies and the container restart policy recovers it,
    instead of the bot limping on with dead workers while polling keeps it looking healthy.
    """
    dispatcher = create_dispatcher(operator_user_id, session_factory, settings)
    async with Bot(token=token) as bot:
        background_tasks: list[asyncio.Task[None]] = []
        if settings is None or settings.notifications_enabled:
            notification_worker = BotNotificationWorker(session_factory, bot, operator_user_id)
            background_tasks.append(
                asyncio.create_task(
                    notification_worker.run_forever(), name="operator-notification-worker"
                )
            )
        alert_worker = OperationalAlertWorker(session_factory, bot, operator_user_id)
        background_tasks.append(
            asyncio.create_task(alert_worker.run_forever(), name="operational-alert-worker")
        )
        background_tasks.append(
            asyncio.create_task(
                run_heartbeat(session_factory, "operator-bot"), name="operator-bot-heartbeat"
            )
        )
        polling_task = asyncio.create_task(
            dispatcher.start_polling(
                bot,
                allowed_updates=dispatcher.resolve_used_update_types(),
            ),
            name="operator-bot-polling",
        )
        all_tasks = [polling_task, *background_tasks]
        try:
            done, _pending = await asyncio.wait(all_tasks, return_when=asyncio.FIRST_COMPLETED)
            failed_worker = next((task for task in background_tasks if task in done), None)
            if failed_worker is not None:
                raise _background_task_failure(failed_worker)
            if polling_task in done:
                polling_task.result()
        finally:
            for task in all_tasks:
                task.cancel()
            await asyncio.gather(*all_tasks, return_exceptions=True)


def _background_task_failure(task: asyncio.Task[None]) -> BaseException:
    """Log and return the failure that ended a background worker task."""
    error = task.exception()
    log_event(
        logger,
        logging.ERROR,
        "background_task_failed",
        task_name=task.get_name(),
        exception_type=type(error).__name__ if error is not None else None,
    )
    if error is not None:
        return error
    return RuntimeError(f"Background task {task.get_name()!r} exited unexpectedly")
