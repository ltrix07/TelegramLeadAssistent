"""Constrained local control plane for persistent Argos models."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

CommandRunner = Callable[[tuple[str, ...]], Awaitable[None]]


async def run_command(argv: tuple[str, ...]) -> None:
    """Run a fixed argv command and discard potentially sensitive output."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    if await process.wait() != 0:
        raise RuntimeError("translation_control_command_failed")


class ArgosControlPlane:
    """Manage only allow-listed package names and signal only LibreTranslate."""

    def __init__(
        self,
        *,
        translation_base_url: str,
        libretranslate_pid: int | None = None,
        runner: CommandRunner = run_command,
    ) -> None:
        self._base_url = translation_base_url.rstrip("/")
        self._pid = libretranslate_pid
        self._runner = runner

    async def install(self, language_code: str) -> None:
        await self._runner(("/app/.venv/bin/argospm", "update"))
        await self._runner(("/app/.venv/bin/argospm", "install", f"translate-{language_code}_en"))
        await self._runner(("/app/.venv/bin/argospm", "install", f"translate-en_{language_code}"))

    async def delete(self, language_code: str) -> None:
        await self._runner(("/app/.venv/bin/argospm", "remove", f"translate-{language_code}_en"))
        await self._runner(("/app/.venv/bin/argospm", "remove", f"translate-en_{language_code}"))

    async def reload(self) -> None:
        os.kill(self._pid or find_libretranslate_pid(), signal.SIGHUP)

    async def test(self, language_code: str) -> None:
        async with httpx.AsyncClient(base_url=self._base_url) as client:
            response = await client.post(
                "/translate",
                json={"q": "test", "source": "en", "target": language_code, "format": "text"},
                timeout=10,
            )
            response.raise_for_status()


def find_libretranslate_pid(proc_root: Path = Path("/proc")) -> int:
    """Find the Gunicorn master in the shared LibreTranslate PID namespace."""
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if b"gunicorn" in command and b"wsgi:app()" in command:
            return int(entry.name)
    raise RuntimeError("libretranslate_process_not_found")
