"""Conservative, local filtering for incoming Telegram messages."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from app.listener.events.incoming import IncomingMessage


class FilterReasonCode(StrEnum):
    """Stable outcomes emitted by the local prefilter."""

    NO_TEXT = "NO_TEXT"
    OWN_MESSAGE = "OWN_MESSAGE"
    SERVICE_MESSAGE = "SERVICE_MESSAGE"
    STICKER_WITHOUT_CAPTION = "STICKER_WITHOUT_CAPTION"
    ONLY_EMOJI = "ONLY_EMOJI"
    BOT_COMMAND = "BOT_COMMAND"
    ONLY_URL = "ONLY_URL"
    KNOWN_GREETING = "KNOWN_GREETING"
    KNOWN_THANKS = "KNOWN_THANKS"
    PASS_TO_CLASSIFIER = "PASS_TO_CLASSIFIER"


@dataclass(frozen=True, slots=True)
class FilterResult:
    """Decision returned by the pure prefilter."""

    should_classify: bool
    reason_code: FilterReasonCode


_KNOWN_GREETINGS = frozenset(
    {
        "доброе утро",
        "добрый день",
        "добрый вечер",
        "здравствуйте",
        "привет",
        "hello",
        "hi",
    }
)
_KNOWN_THANKS = frozenset({"благодарю", "спасибо", "thank you", "thanks"})
_BOT_COMMAND = re.compile(r"^/[A-Za-z0-9_]+(?:@[A-Za-z0-9_]+)?$")
_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_EDGE_PUNCTUATION = " !.,?:;—–-…"


def prefilter_message(message: IncomingMessage) -> FilterResult:
    """Ignore only locally identifiable noise and pass all ambiguous text."""
    if message.is_own:
        return _reject(FilterReasonCode.OWN_MESSAGE)
    if message.is_service:
        return _reject(FilterReasonCode.SERVICE_MESSAGE)

    text = message.text.strip() if message.text is not None else ""
    if not text:
        reason = (
            FilterReasonCode.STICKER_WITHOUT_CAPTION
            if message.has_sticker
            else FilterReasonCode.NO_TEXT
        )
        return _reject(reason)
    if _is_only_emoji(text):
        return _reject(FilterReasonCode.ONLY_EMOJI)
    if _BOT_COMMAND.fullmatch(text):
        return _reject(FilterReasonCode.BOT_COMMAND)
    if _is_only_urls(text):
        return _reject(FilterReasonCode.ONLY_URL)

    normalized = " ".join(text.casefold().strip(_EDGE_PUNCTUATION).split())
    if normalized in _KNOWN_GREETINGS:
        return _reject(FilterReasonCode.KNOWN_GREETING)
    if normalized in _KNOWN_THANKS:
        return _reject(FilterReasonCode.KNOWN_THANKS)
    return FilterResult(True, FilterReasonCode.PASS_TO_CLASSIFIER)


def _reject(reason_code: FilterReasonCode) -> FilterResult:
    return FilterResult(False, reason_code)


def _is_only_urls(text: str) -> bool:
    matches = list(_URL.finditer(text))
    if not matches:
        return False
    remainder = _URL.sub("", text)
    return not remainder.strip(" \t\r\n,;")


def _is_only_emoji(text: str) -> bool:
    visible = (character for character in text if not character.isspace())
    return all(
        unicodedata.category(character) in {"So", "Sk", "Mn"} or character in {"\u200d", "\ufe0f"}
        for character in visible
    )
