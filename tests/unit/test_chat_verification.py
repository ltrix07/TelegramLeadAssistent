"""Tests for MTProto chat verification and transient retry semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from telethon import TelegramClient, errors, types  # type: ignore[import-untyped]

from app.listener.mtproto import (
    ChatVerificationOutcome,
    ChatVerificationTransientError,
    TopicTitleCache,
)
from app.listener.mtproto.client import TelethonSessionClient


class FakePermissions:
    def __init__(
        self, *, send_messages: bool, is_creator: bool = False, is_admin: bool = False
    ) -> None:
        self.send_messages = send_messages
        self.is_creator = is_creator
        self.is_admin = is_admin


class FakeTelethonClient:
    def __init__(
        self,
        entity: object | BaseException,
        *,
        can_send: bool = True,
        is_creator: bool = False,
        is_admin: bool = False,
        topics: list[object] | BaseException | None = None,
    ) -> None:
        self.entity = entity
        self.can_send = can_send
        self.is_creator = is_creator
        self.is_admin = is_admin
        self.history_calls = 0
        self.topics = [] if topics is None else topics
        self.topic_calls = 0

    async def get_entity(self, telegram_chat_id: int) -> object:
        if isinstance(self.entity, BaseException):
            raise self.entity
        return self.entity

    async def get_messages(self, entity: object, *, limit: int) -> list[object]:
        self.history_calls += 1
        return []

    async def get_permissions(self, entity: object, participant: str) -> FakePermissions:
        return FakePermissions(
            send_messages=self.can_send,
            is_creator=self.is_creator,
            is_admin=self.is_admin,
        )

    async def __call__(self, request: object) -> object:
        self.topic_calls += 1
        if isinstance(self.topics, BaseException):
            raise self.topics
        return SimpleNamespace(topics=self.topics)


def _group() -> types.Chat:
    return types.Chat(
        id=1,
        title="Test",
        photo=types.ChatPhotoEmpty(),
        participants_count=2,
        date=datetime.now(UTC),
        version=1,
    )


def _channel(*, broadcast: bool, megagroup: bool, forum: bool = False) -> types.Channel:
    return types.Channel(
        id=1,
        title="Test",
        photo=types.ChatPhotoEmpty(),
        date=datetime.now(UTC),
        broadcast=broadcast,
        megagroup=megagroup,
        forum=forum,
    )


def _forum_message(*, message_id: int, topic_id: int) -> types.Message:
    return types.Message(
        id=message_id,
        peer_id=types.PeerChannel(1),
        reply_to=types.MessageReplyHeader(
            forum_topic=True,
            reply_to_msg_id=topic_id,
            reply_to_top_id=topic_id,
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("entity", [_group(), _channel(broadcast=False, megagroup=True)])
async def test_accessible_group_becomes_active(entity: object) -> None:
    adapter = TelethonSessionClient(cast(TelegramClient, FakeTelethonClient(entity)))

    result = await adapter.verify_chat(-1001)

    assert result.outcome == ChatVerificationOutcome.ACTIVE


@pytest.mark.asyncio
async def test_read_only_group_is_normalized() -> None:
    adapter = TelethonSessionClient(
        cast(TelegramClient, FakeTelethonClient(_group(), can_send=False))
    )

    result = await adapter.verify_chat(-1)

    assert result.outcome == ChatVerificationOutcome.READ_ONLY


@pytest.mark.asyncio
async def test_creator_is_writable_when_telethon_send_messages_flag_is_false() -> None:
    adapter = TelethonSessionClient(
        cast(
            TelegramClient,
            FakeTelethonClient(_group(), can_send=False, is_creator=True),
        )
    )

    result = await adapter.verify_chat(-1)

    assert result.outcome == ChatVerificationOutcome.ACTIVE


@pytest.mark.asyncio
async def test_broadcast_channel_is_rejected_without_history_access() -> None:
    fake = FakeTelethonClient(_channel(broadcast=True, megagroup=False))
    adapter = TelethonSessionClient(cast(TelegramClient, fake))

    result = await adapter.verify_chat(-1001)

    assert result.outcome == ChatVerificationOutcome.VERIFICATION_FAILED
    assert result.error_code == "unsupported_chat_type"
    assert fake.history_calls == 0


@pytest.mark.asyncio
async def test_missing_membership_becomes_access_lost() -> None:
    error = errors.ChannelPrivateError(request=None)
    adapter = TelethonSessionClient(cast(TelegramClient, FakeTelethonClient(error)))

    result = await adapter.verify_chat(-1001)

    assert result.outcome == ChatVerificationOutcome.ACCESS_LOST
    assert result.error_code == "membership_or_access_lost"


@pytest.mark.asyncio
async def test_unresolvable_peer_becomes_access_lost() -> None:
    adapter = TelethonSessionClient(
        cast(TelegramClient, FakeTelethonClient(ValueError("no cached entity")))
    )

    result = await adapter.verify_chat(-1001)

    assert result.outcome == ChatVerificationOutcome.ACCESS_LOST
    assert result.error_code == "peer_unavailable"


@pytest.mark.asyncio
async def test_network_error_is_transient() -> None:
    adapter = TelethonSessionClient(
        cast(TelegramClient, FakeTelethonClient(ConnectionError("offline")))
    )

    with pytest.raises(ChatVerificationTransientError):
        await adapter.verify_chat(-1001)


@pytest.mark.asyncio
async def test_forum_supergroup_is_detected_during_verification() -> None:
    adapter = TelethonSessionClient(
        cast(
            TelegramClient,
            FakeTelethonClient(_channel(broadcast=False, megagroup=True, forum=True)),
        )
    )

    result = await adapter.verify_chat(-1001)

    assert result.outcome == ChatVerificationOutcome.ACTIVE
    assert result.is_supergroup is True
    assert result.is_forum is True


@pytest.mark.asyncio
async def test_general_and_named_topics_are_resolved_and_cached() -> None:
    general = SimpleNamespace(id=1, title="General")
    named = SimpleNamespace(id=42, title="Support")
    fake = FakeTelethonClient(_channel(broadcast=False, megagroup=True), topics=[])
    adapter = TelethonSessionClient(cast(TelegramClient, fake))

    fake.topics = [general]
    general_metadata = await adapter.get_forum_topic_metadata(
        -1001, _forum_message(message_id=2, topic_id=1)
    )
    fake.topics = [named]
    named_metadata = await adapter.get_forum_topic_metadata(
        -1001, _forum_message(message_id=43, topic_id=42)
    )
    cached_metadata = await adapter.get_forum_topic_metadata(
        -1001, _forum_message(message_id=44, topic_id=42)
    )

    assert general_metadata is not None
    assert (general_metadata.topic_id, general_metadata.title) == (1, "General")
    assert named_metadata is not None
    assert (named_metadata.topic_id, named_metadata.title) == (42, "Support")
    assert cached_metadata == named_metadata
    assert fake.topic_calls == 2


@pytest.mark.asyncio
async def test_unknown_or_deleted_topic_returns_metadata_without_title() -> None:
    fake = FakeTelethonClient(_channel(broadcast=False, megagroup=True), topics=[])
    adapter = TelethonSessionClient(cast(TelegramClient, fake))

    first = await adapter.get_forum_topic_metadata(-1001, _forum_message(message_id=10, topic_id=9))
    second = await adapter.get_forum_topic_metadata(
        -1001, _forum_message(message_id=11, topic_id=9)
    )

    assert first is not None
    assert first.topic_id == 9
    assert first.title is None
    assert second == first
    assert fake.topic_calls == 1


def test_topic_title_cache_is_bounded_and_scoped_by_chat() -> None:
    cache = TopicTitleCache(max_size=2)
    cache.put(-1001, 1, "General")
    cache.put(-1002, 1, "General elsewhere")
    assert cache.get(-1001, 1) == (True, "General")

    cache.put(-1001, 2, "Support")

    assert cache.get(-1002, 1) == (False, None)
    assert cache.get(-1001, 1) == (True, "General")
    assert cache.get(-1001, 2) == (True, "Support")
