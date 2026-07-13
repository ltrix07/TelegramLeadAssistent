"""Tests for deterministic and Telegram-safe operator notifications."""

from decimal import Decimal
from html.parser import HTMLParser
from uuid import UUID

from aiogram.enums import ParseMode

from app.bot.keyboards.notifications import build_dismissed_question_controls
from app.bot.notifications import (
    TELEGRAM_MESSAGE_LIMIT,
    NotificationChainItem,
    NotificationContent,
    render_notification,
)


class _StrictHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)

    def handle_endtag(self, tag: str) -> None:
        assert self.tags.pop() == tag


def _content(
    *, original: str = "Original", translated: str | None = "Перевод"
) -> NotificationContent:
    return NotificationContent(
        question_id=UUID("12345678-1234-5678-1234-567812345678"),
        chat_title="Community <sales>",
        topic_title="Plans & pricing",
        category="pricing",
        confidence=Decimal("0.8750"),
        chat_username="sales_europe",
        telegram_chat_id=-1001234567890,
        telegram_message_id=42,
        topic_id=7,
        chain=(
            NotificationChainItem(
                position=0,
                author_display_name="Alice & Bob",
                original_text=original,
                translated_text=translated,
                is_target=True,
            ),
        ),
    )


def test_renderer_escapes_content_and_attaches_opaque_controls() -> None:
    parts = render_notification(_content(original="Can I use <b>this</b> & that?"))

    assert len(parts) == 1
    assert parts[0].parse_mode is ParseMode.HTML
    assert "Community &lt;sales&gt;" in parts[0].text
    assert "&lt;b&gt;this&lt;/b&gt; &amp; that?" in parts[0].text
    assert parts[0].reply_markup is not None
    callbacks = [
        str(button.callback_data)
        for row in parts[0].reply_markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]
    assert callbacks == [
        "question:reply:12345678-1234-5678-1234-567812345678",
        "question:dismiss:12345678-1234-5678-1234-567812345678",
    ]
    assert all("Community" not in callback and "pricing" not in callback for callback in callbacks)
    assert parts[0].reply_markup.inline_keyboard[0][0].url == ("https://t.me/sales_europe/7/42")


def test_dismissed_controls_require_an_explicit_opaque_reopen_action() -> None:
    question_id = UUID("12345678-1234-5678-1234-567812345678")

    markup = build_dismissed_question_controls(question_id)

    assert len(markup.inline_keyboard) == 1
    assert markup.inline_keyboard[0][0].text == "Вернуть вопрос"
    assert markup.inline_keyboard[0][0].callback_data == (
        "question:reopen:12345678-1234-5678-1234-567812345678"
    )


def test_long_chain_is_deterministic_bounded_and_each_part_has_balanced_html() -> None:
    content = _content(original=("<&> long line\n" * 1000), translated=("перевод " * 1000))

    first = render_notification(content)
    second = render_notification(content)

    assert first == second
    assert len(first) > 2
    assert all(len(part.text) <= TELEGRAM_MESSAGE_LIMIT for part in first)
    assert all(part.reply_markup is None for part in first[:-1])
    assert first[-1].reply_markup is not None
    for part in first:
        parser = _StrictHTMLParser()
        parser.feed(part.text)
        parser.close()
        assert parser.tags == []


def test_chain_is_rendered_by_position_with_original_and_translation() -> None:
    content = NotificationContent(
        question_id=UUID("12345678-1234-5678-1234-567812345678"),
        chat_title="Chat",
        topic_title=None,
        category="other",
        confidence=None,
        chat_username=None,
        telegram_chat_id=-1009876543210,
        telegram_message_id=22,
        topic_id=None,
        chain=(
            NotificationChainItem(1, None, "second", None, True),
            NotificationChainItem(0, "Author", "first", "первый", False),
        ),
    )

    text = "\n".join(part.text for part in render_notification(content))

    assert text.index("first") < text.index("second")
    assert "первый" in text
    assert text.count("<b>Перевод:</b> недоступен") == 1
    assert "<b>Тема:</b> Без темы" in text
    assert "<b>Уверенность:</b> —" in text


def test_private_forum_message_link_uses_internal_supergroup_id_and_topic() -> None:
    content = _content()
    content = NotificationContent(
        question_id=content.question_id,
        chat_title=content.chat_title,
        topic_title=None,
        category=content.category,
        confidence=content.confidence,
        chat_username=None,
        telegram_chat_id=-1001234567890,
        telegram_message_id=99,
        topic_id=17,
        chain=content.chain,
    )

    markup = render_notification(content)[-1].reply_markup

    assert markup is not None
    assert markup.inline_keyboard[0][0].url == "https://t.me/c/1234567890/17/99"


def test_unavailable_original_link_does_not_block_notification() -> None:
    content = _content()
    content = NotificationContent(
        question_id=content.question_id,
        chat_title=content.chat_title,
        topic_title=content.topic_title,
        category=content.category,
        confidence=content.confidence,
        chat_username=None,
        telegram_chat_id=-12345,
        telegram_message_id=42,
        topic_id=7,
        chain=content.chain,
    )

    part = render_notification(content)[-1]

    assert part.reply_markup is not None
    assert [button.text for button in part.reply_markup.inline_keyboard[0]] == [
        "Ответить",
        "Не релевантно",
    ]
