"""Telegram listener service entry point."""

from __future__ import annotations

import asyncio
import signal
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import ServiceName, load_startup_settings
from app.database.downstream import DownstreamPhase
from app.database.health import run_heartbeat
from app.database.session import create_session_factory
from app.database.worker import DownstreamQueueWorker
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
from app.listener.reply_chain import ReplyMessageSource
from app.listener.reply_chain_worker import ReplyChainSnapshotHandler
from app.logging import configure_logging


def _register_ingestion_handler(
    client: MTProtoClient,
    allow_list: ActiveChatAllowList,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    monitoring_enabled: bool,
) -> None:
    """Attach message ingestion only when monitoring is enabled."""
    if monitoring_enabled:
        client.add_new_message_handler(
            IngestionHandler(allow_list, database_message_persister(session_factory))
        )


def _outbound_workers(
    client: MTProtoClient,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    outbound_replies_enabled: bool,
) -> tuple[SendReplyWorker | EditReplyWorker, ...]:
    """Build no command executors while outbound replies are disabled."""
    if not outbound_replies_enabled:
        return ()
    return (
        SendReplyWorker(session_factory, client),
        EditReplyWorker(session_factory, client),
    )


async def _run_connected_tasks(
    client: MTProtoClient,
    session_factory: async_sessionmaker[AsyncSession],
    allow_list: ActiveChatAllowList,
    stop_event: asyncio.Event,
    *,
    outbound_replies_enabled: bool,
) -> None:
    tasks = [
        run_heartbeat(session_factory, "telegram-listener"),
        run_chat_verifier(client, session_factory, stop_event),
        run_active_chat_allow_list(allow_list, stop_event),
        DownstreamQueueWorker(
            session_factory,
            "telegram-listener-reply-chain-1",
            DownstreamPhase.REPLY_CHAIN,
            ReplyChainSnapshotHandler(cast(ReplyMessageSource, client)),
        ).run_forever(),
    ]
    tasks.extend(
        worker.run_forever()
        for worker in _outbound_workers(
            client,
            session_factory,
            outbound_replies_enabled=outbound_replies_enabled,
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
        _register_ingestion_handler(
            client,
            allow_list,
            session_factory,
            monitoring_enabled=settings.monitoring_enabled,
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
