"""Telegram listener service entry point."""

from __future__ import annotations

import asyncio
import signal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import ServiceName, load_startup_settings
from app.database.session import create_session_factory
from app.listener.active_chats import (
    ActiveChatAllowList,
    database_active_chat_loader,
    run_active_chat_allow_list,
)
from app.listener.chat_verification import run_chat_verifier
from app.listener.events import IngestionHandler, database_message_persister
from app.listener.lifecycle import (
    ListenerAlreadyRunning,
    SessionFileLock,
    SessionNotAuthorized,
    run_listener,
)
from app.listener.mtproto import MTProtoClient, create_telethon_client
from app.listener.outbound import EditReplyWorker, SendReplyWorker
from app.logging import configure_logging


async def _run_connected_tasks(
    client: MTProtoClient,
    session_factory: async_sessionmaker[AsyncSession],
    allow_list: ActiveChatAllowList,
    stop_event: asyncio.Event,
    *,
    outbound_replies_enabled: bool,
) -> None:
    tasks = [
        run_chat_verifier(client, session_factory, stop_event),
        run_active_chat_allow_list(allow_list, stop_event),
    ]
    if outbound_replies_enabled:
        tasks.extend(
            (
                SendReplyWorker(session_factory, client).run_forever(),
                EditReplyWorker(session_factory, client).run_forever(),
            )
        )
    await asyncio.gather(*tasks)


async def _run() -> None:
    settings = load_startup_settings(ServiceName.TELEGRAM_LISTENER)
    configure_logging(ServiceName.TELEGRAM_LISTENER, settings)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop_event.set)

    with SessionFileLock(settings.telegram_session_path):
        client = create_telethon_client(settings)
        if settings.database_url is None:
            raise RuntimeError("Validated listener database URL is missing")
        engine, session_factory = create_session_factory(settings.database_url.get_secret_value())
        allow_list = ActiveChatAllowList(database_active_chat_loader(session_factory))
        client.add_new_message_handler(
            IngestionHandler(allow_list, database_message_persister(session_factory))
        )
        try:
            await run_listener(
                client,
                stop_event,
                connected_task_factory=lambda: _run_connected_tasks(
                    client,
                    session_factory,
                    allow_list,
                    stop_event,
                    outbound_replies_enabled=settings.outbound_replies_enabled,
                ),
            )
        finally:
            await engine.dispose()


def main() -> None:
    """Start the Telegram listener service."""
    try:
        asyncio.run(_run())
    except (ListenerAlreadyRunning, SessionNotAuthorized) as error:
        raise SystemExit(f"Listener startup error: {error}") from None


if __name__ == "__main__":
    main()
