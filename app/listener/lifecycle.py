"""Listener lifecycle and exclusive ownership of the MTProto session."""

from __future__ import annotations

import asyncio
import errno
import fcntl
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from types import TracebackType

from app.listener.mtproto.client import MTProtoListenerClient
from app.logging import log_event

logger = logging.getLogger(__name__)


class ListenerAlreadyRunning(RuntimeError):
    """Raised when another process already owns the MTProto session."""


class SessionNotAuthorized(RuntimeError):
    """Raised when the configured session has not been authorized."""


class SessionFileLock:
    """Hold a non-blocking process lock next to one MTProto session file."""

    def __init__(self, session_path: Path) -> None:
        self._lock_path = session_path.with_name(f"{session_path.name}.lock")
        self._file_descriptor: int | None = None

    def __enter__(self) -> SessionFileLock:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(descriptor)
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise ListenerAlreadyRunning(
                    "Another listener already owns the MTProto session"
                ) from None
            raise
        self._file_descriptor = descriptor
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        descriptor = self._file_descriptor
        if descriptor is None:
            return
        self._file_descriptor = None
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@asynccontextmanager
async def _connection_tasks(
    client: MTProtoListenerClient,
    stop_event: asyncio.Event,
    connected_task: Coroutine[object, object, None] | None,
) -> AsyncIterator[tuple[asyncio.Task[None], asyncio.Task[bool], asyncio.Task[None] | None]]:
    disconnected = asyncio.create_task(client.run_until_disconnected())
    stopping = asyncio.create_task(stop_event.wait())
    background: asyncio.Task[None] | None = (
        asyncio.create_task(connected_task) if connected_task is not None else None
    )
    try:
        yield disconnected, stopping, background
    finally:
        for task in (disconnected, stopping, background):
            if task is None:
                continue
            if not task.done():
                task.cancel()
        await asyncio.gather(disconnected, stopping, return_exceptions=True)


async def run_listener(
    client: MTProtoListenerClient,
    stop_event: asyncio.Event,
    *,
    reconnect_delay_seconds: float = 5.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    connected_task_factory: Callable[[], Coroutine[object, object, None]] | None = None,
) -> None:
    """Run until stopped, reconnecting after recoverable disconnects."""
    try:
        while not stop_event.is_set():
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise SessionNotAuthorized(
                        "MTProto session is not authorized; create it before starting listener"
                    )
                log_event(logger, logging.INFO, "mtproto_connected")

                connected_task = (
                    connected_task_factory() if connected_task_factory is not None else None
                )
                async with _connection_tasks(client, stop_event, connected_task) as tasks:
                    disconnected, stopping, background = tasks
                    wait_tasks = {disconnected, stopping}
                    if background is not None:
                        wait_tasks.add(background)
                    done, _ = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)
                    if stopping in done:
                        break
                    if background is not None and background in done:
                        await background
                    await disconnected
                log_event(logger, logging.WARNING, "mtproto_disconnected")
            except SessionNotAuthorized:
                raise
            except asyncio.CancelledError:
                raise
            except Exception:
                log_event(logger, logging.WARNING, "mtproto_connection_failed")

            if not stop_event.is_set():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=reconnect_delay_seconds)
                except TimeoutError:
                    await sleep(0)
    finally:
        await client.disconnect()
        log_event(logger, logging.INFO, "mtproto_stopped")
