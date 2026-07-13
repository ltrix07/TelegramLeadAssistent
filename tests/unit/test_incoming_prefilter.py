"""Tests for network-free incoming message normalization and filtering."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from telethon import types  # type: ignore[import-untyped]

from app.listener.events import (
    FilterReasonCode,
    IncomingMessage,
    map_telethon_event,
    prefilter_message,
)
from app.listener.events.incoming import TelethonMessageEvent


def _incoming(text: str | None = "Нужна помощь с настройкой") -> IncomingMessage:
    return IncomingMessage(
        telegram_chat_id=-1001,
        telegram_message_id=42,
        topic_id=None,
        sender_telegram_id=7,
        sender_display_name="Test User",
        text=text,
        telegram_created_at=datetime(2026, 7, 12, tzinfo=UTC),
        is_own=False,
        is_service=False,
        has_sticker=False,
    )


def test_incoming_message_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        _incoming().text = "changed"  # type: ignore[misc]


def test_mapper_uses_only_cached_event_data() -> None:
    created_at = datetime(2026, 7, 12, 10, tzinfo=UTC)
    message = types.Message(
        id=12,
        peer_id=types.PeerChannel(1001),
        from_id=types.PeerUser(7),
        message="Hello",
        date=created_at,
        out=False,
    )
    message._sender = types.User(id=7, first_name="Test", last_name="User")
    event = SimpleNamespace(chat_id=-1001, message=message)

    result = map_telethon_event(cast(TelethonMessageEvent, event), topic_id=3)

    assert result == IncomingMessage(
        telegram_chat_id=-1001,
        telegram_message_id=12,
        topic_id=3,
        sender_telegram_id=7,
        sender_display_name="Test User",
        text="Hello",
        telegram_created_at=created_at,
        is_own=False,
        is_service=False,
        has_sticker=False,
    )


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (replace(_incoming(), is_own=True), FilterReasonCode.OWN_MESSAGE),
        (replace(_incoming(), is_service=True), FilterReasonCode.SERVICE_MESSAGE),
        (_incoming(None), FilterReasonCode.NO_TEXT),
        (replace(_incoming(None), has_sticker=True), FilterReasonCode.STICKER_WITHOUT_CAPTION),
        (_incoming("👋🙂"), FilterReasonCode.ONLY_EMOJI),
        (_incoming("/start"), FilterReasonCode.BOT_COMMAND),
        (_incoming("https://example.com"), FilterReasonCode.ONLY_URL),
        (_incoming("Привет!"), FilterReasonCode.KNOWN_GREETING),
        (_incoming(" Спасибо. "), FilterReasonCode.KNOWN_THANKS),
    ],
)
def test_unambiguous_noise_is_rejected(message: IncomingMessage, reason: FilterReasonCode) -> None:
    result = prefilter_message(message)

    assert result.should_classify is False
    assert result.reason_code is reason


@pytest.mark.parametrize(
    "text",
    [
        "Нужна помощь с настройкой",
        "Привет, нужна помощь",
        "https://example.com не открывается",
        "/deploy production",
        "...",
    ],
)
def test_ambiguous_text_passes_without_requiring_question_mark(text: str) -> None:
    result = prefilter_message(_incoming(text))

    assert result.should_classify is True
    assert result.reason_code is FilterReasonCode.PASS_TO_CLASSIFIER
