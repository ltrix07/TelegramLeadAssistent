"""Network-free normalization of incoming Telegram messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from telethon import types  # type: ignore[import-untyped]
from telethon.utils import get_display_name  # type: ignore[import-untyped]


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """Immutable message data consumed by ingestion domain logic."""

    telegram_chat_id: int
    telegram_message_id: int
    topic_id: int | None
    sender_telegram_id: int | None
    sender_display_name: str | None
    text: str | None
    telegram_created_at: datetime
    is_own: bool
    is_service: bool
    has_sticker: bool


class TelethonMessageEvent(Protocol):
    """Cached event attributes needed by the synchronous mapper."""

    chat_id: int | None
    message: types.Message


def map_telethon_event(
    event: TelethonMessageEvent,
    *,
    topic_id: int | None = None,
) -> IncomingMessage:
    """Map a Telethon event without performing entity or network lookups."""
    message = event.message
    if event.chat_id is None:
        raise ValueError("Incoming Telegram event has no chat ID")

    sender = message.sender
    sender_display_name = get_display_name(sender)[:255] if sender is not None else None
    raw_text = message.raw_text
    return IncomingMessage(
        telegram_chat_id=event.chat_id,
        telegram_message_id=message.id,
        topic_id=topic_id,
        sender_telegram_id=message.sender_id,
        sender_display_name=sender_display_name or None,
        text=raw_text if raw_text else None,
        telegram_created_at=message.date,
        is_own=bool(message.out),
        is_service=message.action is not None,
        has_sticker=message.sticker is not None,
    )


def extract_topic_id(message: types.Message) -> int | None:
    """Extract a forum topic ID from cached message fields without Telegram I/O."""
    reply = message.reply_to
    if isinstance(reply, types.MessageReplyHeader) and reply.forum_topic:
        return cast(int | None, reply.reply_to_top_id or reply.reply_to_msg_id)
    if isinstance(message.action, types.MessageActionTopicCreate):
        return cast(int, message.id)
    return None
