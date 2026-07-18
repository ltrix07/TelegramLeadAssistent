"""Diagnose why monitored chats are classified read_only.

Content-free: prints only chat identifiers, titles, participant type, and permission
booleans as reported by MTProto. It never reads or prints message content.

Run with the listener stopped so the MTProto session file is not locked:

    docker compose stop telegram-listener
    docker compose run --rm telegram-listener python -m scripts.diagnose_chat_permissions
    docker compose start telegram-listener
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from telethon import TelegramClient  # type: ignore[import-untyped]

from app.config import ServiceName, load_startup_settings
from app.database.models.entities import MonitoredChat
from app.database.session import create_session_factory
from app.domain.enums import MonitoredChatStatus

_PERMISSION_FLAGS = (
    "is_creator",
    "is_admin",
    "is_banned",
    "is_default",
    "send_messages",
    "send_media",
    "send_polls",
    "send_stickers",
    "send_gifs",
    "send_inline",
    "embed_links",
)


async def _load_read_only_chats(database_url: str) -> list[tuple[int, str]]:
    engine, session_factory = create_session_factory(database_url)
    try:
        async with session_factory() as session:
            rows = await session.execute(
                select(MonitoredChat.telegram_chat_id, MonitoredChat.title).where(
                    MonitoredChat.status == MonitoredChatStatus.READ_ONLY
                )
            )
            return [(int(cid), str(title)) for cid, title in rows.all()]
    finally:
        await engine.dispose()


def _describe(value: object) -> str:
    return "true" if value else "false"


async def _diagnose() -> None:
    settings = load_startup_settings(ServiceName.TELEGRAM_LISTENER)
    if settings.database_url is None:
        raise SystemExit("DATABASE_URL is not configured")
    if settings.telegram_api_id is None or settings.telegram_api_hash is None:
        raise SystemExit("MTProto credentials are not configured")

    chats = await _load_read_only_chats(settings.database_url.get_secret_value())
    if not chats:
        print("No read_only chats found.")
        return

    session_path = settings.telegram_session_path
    session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        str(session_path),
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise SystemExit("MTProto session is not authorized")

        for telegram_chat_id, title in chats:
            print(f"\n=== {title} ({telegram_chat_id}) ===")
            try:
                entity = await client.get_entity(telegram_chat_id)
            except Exception as exc:  # noqa: BLE001 - diagnostic surface
                print(f"  get_entity error: {type(exc).__name__}")
                continue

            default_banned = getattr(entity, "default_banned_rights", None)
            if default_banned is not None:
                banned = _describe(getattr(default_banned, "send_messages", False))
                until = getattr(default_banned, "until_date", None)
                print(
                    "  chat.default_banned_rights: "
                    f"send_messages_banned={banned} until_date={until}"
                )
            print(
                f"  chat.slowmode_enabled={_describe(getattr(entity, 'slowmode_enabled', False))}"
            )

            try:
                permissions = await client.get_permissions(entity, "me")
            except Exception as exc:  # noqa: BLE001 - diagnostic surface
                print(f"  get_permissions error: {type(exc).__name__}")
                continue

            print(f"  participant type: {type(getattr(permissions, 'participant', None)).__name__}")
            for name in _PERMISSION_FLAGS:
                print(f"  {name}={_describe(getattr(permissions, name, None))}")

            banned_rights = getattr(
                getattr(permissions, "participant", None), "banned_rights", None
            )
            if banned_rights is not None:
                banned = _describe(getattr(banned_rights, "send_messages", False))
                until = getattr(banned_rights, "until_date", None)
                print(
                    f"  participant.banned_rights: send_messages_banned={banned} until_date={until}"
                )
    finally:
        await client.disconnect()


def main() -> None:
    """Print MTProto permission diagnostics for read_only monitored chats."""
    asyncio.run(_diagnose())


if __name__ == "__main__":
    main()
