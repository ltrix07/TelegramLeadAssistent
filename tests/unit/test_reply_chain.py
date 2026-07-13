"""Tests for bounded and chat-safe reply-chain reconstruction."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.listener.reply_chain import (
    ReplyChainLoader,
    ReplyChainStopReason,
    ReplyMessage,
)


class FakeReplyMessageSource:
    def __init__(
        self,
        messages: dict[int, ReplyMessage],
        *,
        topic_titles: dict[int, str | None] | None = None,
    ) -> None:
        self.messages = messages
        self.topic_titles = topic_titles or {}
        self.requests: list[tuple[int, int]] = []
        self.topic_requests: list[tuple[int, int]] = []

    async def get_reply_message(self, chat_id: int, message_id: int) -> ReplyMessage | None:
        self.requests.append((chat_id, message_id))
        return self.messages.get(message_id)

    async def get_forum_topic_title(self, chat_id: int, topic_id: int) -> str | None:
        self.topic_requests.append((chat_id, topic_id))
        return self.topic_titles.get(topic_id)


def _message(
    message_id: int,
    reply_to: int | None,
    *,
    chat_id: int = -1001,
    topic_id: int | None = None,
    top_message_id: int | None = None,
) -> ReplyMessage:
    return ReplyMessage(
        telegram_chat_id=chat_id,
        telegram_message_id=message_id,
        reply_to_message_id=reply_to,
        topic_id=topic_id,
        reply_to_top_message_id=top_message_id,
        author_telegram_id=message_id + 100,
        author_display_name=f"User {message_id}",
        telegram_created_at=datetime(2026, 7, 12, tzinfo=UTC),
        text=f"message {message_id}",
    )


@pytest.mark.asyncio
async def test_no_reply_chain_contains_only_marked_target() -> None:
    loader = ReplyChainLoader(FakeReplyMessageSource({7: _message(7, None)}))

    chain = await loader.get_reply_chain(-1001, 7)

    assert [item.telegram_message_id for item in chain.items] == [7]
    assert chain.items[0].is_target is True
    assert chain.stop_reason is None


@pytest.mark.asyncio
async def test_chain_is_ordered_oldest_to_target() -> None:
    loader = ReplyChainLoader(
        FakeReplyMessageSource({3: _message(3, 2), 2: _message(2, 1), 1: _message(1, None)})
    )

    chain = await loader.get_reply_chain(-1001, 3)

    assert [item.telegram_message_id for item in chain.items] == [1, 2, 3]
    assert [item.is_target for item in chain.items] == [False, False, True]


@pytest.mark.asyncio
async def test_long_chain_is_capped_at_ten_items() -> None:
    messages = {
        message_id: _message(message_id, message_id - 1 if message_id > 1 else None)
        for message_id in range(1, 13)
    }
    source = FakeReplyMessageSource(messages)

    chain = await ReplyChainLoader(source).get_reply_chain(-1001, 12)

    assert [item.telegram_message_id for item in chain.items] == list(range(3, 13))
    assert chain.stop_reason is ReplyChainStopReason.MAX_DEPTH
    assert len(source.requests) == 10


@pytest.mark.asyncio
async def test_deleted_parent_is_safe_unavailable_oldest_item() -> None:
    loader = ReplyChainLoader(FakeReplyMessageSource({3: _message(3, 2)}))

    chain = await loader.get_reply_chain(-1001, 3)

    assert [item.telegram_message_id for item in chain.items] == [2, 3]
    assert chain.items[0].is_unavailable is True
    assert chain.items[0].text is None
    assert chain.items[1].is_target is True
    assert chain.stop_reason is ReplyChainStopReason.MISSING_PARENT


@pytest.mark.asyncio
async def test_cross_chat_parent_content_is_not_included() -> None:
    source = FakeReplyMessageSource({3: _message(3, 2), 2: _message(2, None, chat_id=-1002)})

    chain = await ReplyChainLoader(source).get_reply_chain(-1001, 3)

    assert [item.telegram_message_id for item in chain.items] == [2, 3]
    assert chain.items[0].is_unavailable is True
    assert chain.items[0].text is None
    assert chain.stop_reason is ReplyChainStopReason.CROSS_CHAT_PARENT


@pytest.mark.asyncio
async def test_cycle_stops_without_duplicate_items() -> None:
    loader = ReplyChainLoader(FakeReplyMessageSource({3: _message(3, 2), 2: _message(2, 3)}))

    chain = await loader.get_reply_chain(-1001, 3)

    assert [item.telegram_message_id for item in chain.items] == [2, 3]
    assert chain.stop_reason is ReplyChainStopReason.CYCLE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("topic_id", "title"),
    [(1, "General"), (42, "Support")],
)
async def test_forum_chain_preserves_topic_metadata(topic_id: int, title: str) -> None:
    source = FakeReplyMessageSource(
        {
            8: _message(8, 7, topic_id=topic_id, top_message_id=topic_id),
            7: _message(7, None, topic_id=topic_id, top_message_id=topic_id),
        },
        topic_titles={topic_id: title},
    )

    chain = await ReplyChainLoader(source).get_reply_chain(-1001, 8)

    assert chain.topic_id == topic_id
    assert chain.reply_to_top_message_id == topic_id
    assert chain.topic_title == title
    assert [item.topic_id for item in chain.items] == [topic_id, topic_id]
    assert [item.reply_to_top_message_id for item in chain.items] == [topic_id, topic_id]
    assert source.topic_requests == [(-1001, topic_id)]


@pytest.mark.asyncio
async def test_chain_cannot_cross_forum_topics() -> None:
    source = FakeReplyMessageSource(
        {
            8: _message(8, 7, topic_id=42, top_message_id=42),
            7: _message(7, None, topic_id=41, top_message_id=41),
        },
        topic_titles={42: "Support"},
    )

    chain = await ReplyChainLoader(source).get_reply_chain(-1001, 8)

    assert [item.telegram_message_id for item in chain.items] == [7, 8]
    assert chain.items[0].is_unavailable is True
    assert chain.items[0].text is None
    assert chain.stop_reason is ReplyChainStopReason.CROSS_TOPIC_PARENT
    assert chain.topic_id == 42
    assert chain.topic_title == "Support"


@pytest.mark.asyncio
async def test_deleted_or_closed_topic_metadata_does_not_break_chain() -> None:
    source = FakeReplyMessageSource(
        {8: _message(8, None, topic_id=42, top_message_id=42)},
        topic_titles={42: None},
    )

    chain = await ReplyChainLoader(source).get_reply_chain(-1001, 8)

    assert chain.topic_id == 42
    assert chain.reply_to_top_message_id == 42
    assert chain.topic_title is None
    assert chain.items[-1].is_target is True
    assert chain.stop_reason is None


@pytest.mark.parametrize("max_depth", [0, 11])
@pytest.mark.asyncio
async def test_depth_outside_supported_range_is_rejected(max_depth: int) -> None:
    loader = ReplyChainLoader(FakeReplyMessageSource({}))

    with pytest.raises(ValueError, match="between 1 and 10"):
        await loader.get_reply_chain(-1001, 1, max_depth=max_depth)
