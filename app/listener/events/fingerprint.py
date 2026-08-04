"""Privacy-safe content fingerprints for ingestion deduplication."""

from __future__ import annotations

import hashlib
import re
import unicodedata

URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_MENTION = re.compile(r"@\w+")
_REMOVED_CATEGORIES = frozenset({"So", "Sk", "Mn"})
_REMOVED_CODEPOINTS = frozenset({"\u200d", "\ufe0f"})


def message_fingerprint(text: str) -> str:
    """Return the SHA-256 hash of normalized message content without retaining it."""
    normalized = URL_PATTERN.sub("", text.casefold())
    normalized = "".join(
        character
        for character in normalized
        if unicodedata.category(character) not in _REMOVED_CATEGORIES
        and character not in _REMOVED_CODEPOINTS
    )
    normalized = _MENTION.sub("", normalized)
    normalized = " ".join(
        "".join(character if character.isalnum() else " " for character in normalized).split()
    )
    return hashlib.sha256(normalized.encode()).hexdigest()
