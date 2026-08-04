"""Tests for privacy-safe message-content normalization."""

from app.listener.events.fingerprint import message_fingerprint


def test_fingerprint_ignores_case_urls_mentions_emoji_and_punctuation() -> None:
    original = "Нужен Telegram-бот! @alice https://example.com/brief 🤖"
    repeated = "нужен telegram бот @bob ✅ https://another.example/path"

    assert message_fingerprint(original) == message_fingerprint(repeated)


def test_fingerprint_changes_when_normalized_content_changes() -> None:
    assert message_fingerprint("Нужен Telegram-бот") != message_fingerprint("Нужен парсер")
