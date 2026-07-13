"""Bounded reconstruction of explicit Telegram reply chains."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class ReplyChainStopReason(StrEnum):
    """Reason why traversal stopped before reaching a reply root."""

    MISSING_PARENT = "missing_parent"
    CROSS_CHAT_PARENT = "cross_chat_parent"
    CROSS_TOPIC_PARENT = "cross_topic_parent"
    CYCLE = "cycle"
    MAX_DEPTH = "max_depth"


@dataclass(frozen=True, slots=True)
class ReplyMessage:
    """Normalized Telegram message returned by the MTProto adapter."""

    telegram_chat_id: int
    telegram_message_id: int
    reply_to_message_id: int | None
    topic_id: int | None
    reply_to_top_message_id: int | None
    author_telegram_id: int | None
    author_display_name: str | None
    telegram_created_at: datetime
    text: str


@dataclass(frozen=True, slots=True)
class ReplyChainItem:
    """One ordered message or safe unavailable-parent marker."""

    telegram_message_id: int
    reply_to_message_id: int | None
    topic_id: int | None
    reply_to_top_message_id: int | None
    author_telegram_id: int | None
    author_display_name: str | None
    telegram_created_at: datetime | None
    text: str | None
    is_target: bool
    is_unavailable: bool = False


@dataclass(frozen=True, slots=True)
class ReplyChain:
    """Oldest-to-target reply chain with explicit truncation metadata."""

    chat_id: int
    items: tuple[ReplyChainItem, ...]
    topic_id: int | None = None
    reply_to_top_message_id: int | None = None
    topic_title: str | None = None
    stop_reason: ReplyChainStopReason | None = None


class ReplyMessageSource(Protocol):
    """Minimal MTProto history interface required by the chain loader."""

    async def get_reply_message(self, chat_id: int, message_id: int) -> ReplyMessage | None:
        """Load one message by its identity, returning None when unavailable."""

    async def get_forum_topic_title(self, chat_id: int, topic_id: int) -> str | None:
        """Resolve a cached topic title, returning None when metadata is unavailable."""


class ReplyChainLoader:
    """Load explicit parents without leaving the target chat or exceeding ten items."""

    MAX_DEPTH = 10

    def __init__(self, source: ReplyMessageSource) -> None:
        self._source = source

    async def get_reply_chain(
        self,
        chat_id: int,
        message_id: int,
        max_depth: int = MAX_DEPTH,
    ) -> ReplyChain:
        """Return a bounded chain ordered from the oldest item to the target."""
        if max_depth < 1 or max_depth > self.MAX_DEPTH:
            raise ValueError("Reply-chain depth must be between 1 and 10")

        newest_first: list[ReplyChainItem] = []
        visited_message_ids: set[int] = set()
        current_id = message_id
        stop_reason: ReplyChainStopReason | None = None
        target_topic_id: int | None = None
        target_top_message_id: int | None = None

        while len(newest_first) < max_depth:
            if current_id in visited_message_ids:
                stop_reason = ReplyChainStopReason.CYCLE
                break
            visited_message_ids.add(current_id)

            message = await self._source.get_reply_message(chat_id, current_id)
            if message is None:
                newest_first.append(self._unavailable_item(current_id))
                stop_reason = ReplyChainStopReason.MISSING_PARENT
                break
            if message.telegram_chat_id != chat_id:
                newest_first.append(self._unavailable_item(current_id))
                stop_reason = ReplyChainStopReason.CROSS_CHAT_PARENT
                break

            if not newest_first:
                target_topic_id = message.topic_id
                target_top_message_id = message.reply_to_top_message_id
            elif message.topic_id != target_topic_id:
                newest_first.append(self._unavailable_item(current_id))
                stop_reason = ReplyChainStopReason.CROSS_TOPIC_PARENT
                break

            newest_first.append(self._available_item(message))
            if message.reply_to_message_id is None:
                break
            current_id = message.reply_to_message_id
        else:
            if newest_first[-1].reply_to_message_id is not None:
                stop_reason = ReplyChainStopReason.MAX_DEPTH

        ordered = list(reversed(newest_first))
        if ordered:
            ordered[-1] = replace(ordered[-1], is_target=True)
        topic_title = (
            await self._source.get_forum_topic_title(chat_id, target_topic_id)
            if target_topic_id is not None
            else None
        )
        return ReplyChain(
            chat_id=chat_id,
            items=tuple(ordered),
            topic_id=target_topic_id,
            reply_to_top_message_id=target_top_message_id,
            topic_title=topic_title,
            stop_reason=stop_reason,
        )

    @staticmethod
    def _available_item(message: ReplyMessage) -> ReplyChainItem:
        return ReplyChainItem(
            telegram_message_id=message.telegram_message_id,
            reply_to_message_id=message.reply_to_message_id,
            topic_id=message.topic_id,
            reply_to_top_message_id=message.reply_to_top_message_id,
            author_telegram_id=message.author_telegram_id,
            author_display_name=message.author_display_name,
            telegram_created_at=message.telegram_created_at,
            text=message.text,
            is_target=False,
        )

    @staticmethod
    def _unavailable_item(message_id: int) -> ReplyChainItem:
        return ReplyChainItem(
            telegram_message_id=message_id,
            reply_to_message_id=None,
            topic_id=None,
            reply_to_top_message_id=None,
            author_telegram_id=None,
            author_display_name=None,
            telegram_created_at=None,
            text=None,
            is_target=False,
            is_unavailable=True,
        )
