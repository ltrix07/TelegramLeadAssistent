"""Deterministic, Telegram-safe rendering of operator notifications."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html import escape
from uuid import UUID

from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards.notifications import (
    build_original_message_url,
    build_question_controls,
)

TELEGRAM_MESSAGE_LIMIT = 4096


@dataclass(frozen=True, slots=True)
class NotificationChainItem:
    """One persisted reply-chain item required by the renderer."""

    position: int
    author_display_name: str | None
    original_text: str
    translated_text: str | None
    is_target: bool


@dataclass(frozen=True, slots=True)
class NotificationContent:
    """Persisted question metadata required by the renderer."""

    question_id: UUID
    chat_title: str
    topic_title: str | None
    category: str
    confidence: Decimal | None
    chat_username: str | None
    telegram_chat_id: int
    telegram_message_id: int
    topic_id: int | None
    chain: tuple[NotificationChainItem, ...]


@dataclass(frozen=True, slots=True)
class NotificationPart:
    """One independently valid Telegram message."""

    text: str
    parse_mode: ParseMode
    reply_markup: InlineKeyboardMarkup | None = None


def render_notification(content: NotificationContent) -> tuple[NotificationPart, ...]:
    """Render a notification as bounded, independently valid HTML messages."""
    blocks = [_render_metadata(content)]
    for item in sorted(content.chain, key=lambda value: value.position):
        blocks.extend(_render_chain_item(item))

    texts = _pack_blocks(blocks)
    original_message_url = build_original_message_url(
        chat_username=content.chat_username,
        telegram_chat_id=content.telegram_chat_id,
        telegram_message_id=content.telegram_message_id,
        topic_id=content.topic_id,
    )
    controls = build_question_controls(
        content.question_id,
        original_message_url=original_message_url,
    )
    return tuple(
        NotificationPart(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=controls if index == len(texts) - 1 else None,
        )
        for index, text in enumerate(texts)
    )


def _render_metadata(content: NotificationContent) -> str:
    topic = content.topic_title or "Без темы"
    confidence = "—" if content.confidence is None else f"{content.confidence:.0%}"
    return "\n".join(
        (
            "<b>Новый вопрос</b>",
            f"<b>Чат:</b> {escape(content.chat_title)}",
            f"<b>Тема:</b> {escape(topic)}",
            f"<b>Категория:</b> {escape(content.category)}",
            f"<b>Уверенность:</b> {confidence}",
        )
    )


def _render_chain_item(item: NotificationChainItem) -> list[str]:
    marker = " • целевое сообщение" if item.is_target else ""
    author = item.author_display_name or "Неизвестный автор"
    heading = f"<b>Сообщение {item.position + 1}{marker}</b>\n<b>Автор:</b> {escape(author)}"
    blocks = [heading]
    blocks.extend(_render_text_blocks("Оригинал", item.original_text))
    if item.translated_text is not None and item.translated_text != item.original_text:
        blocks.extend(_render_text_blocks("Перевод", item.translated_text))
    else:
        blocks.append("<b>Перевод:</b> недоступен")
    return blocks


def _render_text_blocks(label: str, text: str) -> list[str]:
    prefix = f"<b>{label}:</b>\n<blockquote>"
    suffix = "</blockquote>"
    payload_limit = TELEGRAM_MESSAGE_LIMIT - len(prefix) - len(suffix)
    chunks = _split_escaped_text(text, payload_limit)
    return [f"{prefix}{chunk}{suffix}" for chunk in chunks]


def _split_escaped_text(text: str, limit: int) -> list[str]:
    if not text:
        return [""]
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for character in text:
        escaped = escape(character)
        if current and current_length + len(escaped) > limit:
            chunks.append("".join(current))
            current = []
            current_length = 0
        current.append(escaped)
        current_length += len(escaped)
    if current:
        chunks.append("".join(current))
    return chunks


def _pack_blocks(blocks: list[str]) -> list[str]:
    messages: list[str] = []
    current = ""
    for block in blocks:
        separator = "\n\n" if current else ""
        if current and len(current) + len(separator) + len(block) > TELEGRAM_MESSAGE_LIMIT:
            messages.append(current)
            current = block
        else:
            current = f"{current}{separator}{block}"
    if current:
        messages.append(current)
    return messages


__all__ = [
    "NotificationChainItem",
    "NotificationContent",
    "NotificationPart",
    "TELEGRAM_MESSAGE_LIMIT",
    "render_notification",
]
