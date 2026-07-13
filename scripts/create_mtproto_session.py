"""Interactively create and validate the work account MTProto session."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from app.config import ServiceName, load_startup_settings
from app.listener.mtproto import MTProtoSessionClient, create_telethon_client


async def create_session(
    client: MTProtoSessionClient,
    *,
    output: Callable[[str], None] = print,
) -> None:
    """Authorize a client, validate its account, and report safe identity fields."""
    try:
        await client.start()
        account = await client.get_account()
        output(f"Telegram user ID: {account.user_id}")
        output(f"Display name: {account.display_name}")
    finally:
        await client.disconnect()


def main() -> None:
    """Run interactive MTProto session creation from environment settings."""
    settings = load_startup_settings(ServiceName.MTPROTO_SESSION_CREATOR)
    asyncio.run(create_session(create_telethon_client(settings)))


if __name__ == "__main__":
    main()
