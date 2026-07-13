"""Async adapter for the internal LibreTranslate service."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import httpx


class TranslationStatus(StrEnum):
    """Outcome persisted for one independently translated message."""

    TRANSLATED = "translated"
    BYPASSED = "bypassed"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """Translation outcome that always retains the original text path."""

    original_text: str
    translated_text: str | None
    source_language: str | None
    status: TranslationStatus
    error_code: str | None = None

    @property
    def display_text(self) -> str:
        """Return translated text when available, otherwise the original."""
        return self.translated_text or self.original_text


class TranslationService(Protocol):
    """Boundary used by translation workflows and deterministic fakes."""

    async def detect_language(self, text: str) -> str | None:
        """Detect an ISO language code, or return None when unavailable."""

    async def translate_to_russian(
        self, text: str, source_language: str | None
    ) -> TranslationResult:
        """Translate one message without hiding its original on failure."""


class LibreTranslateAdapter:
    """HTTP adapter for an internal LibreTranslate instance."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"))
        self._owns_client = client is None
        self._timeout_seconds = timeout_seconds

    async def __aenter__(self) -> LibreTranslateAdapter:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the internally created HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def detect_language(self, text: str) -> str | None:
        """Detect a language, normalizing service failures to None."""
        try:
            response = await self._client.post(
                "/detect", json={"q": text}, timeout=self._timeout_seconds
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                return None
            language = payload[0].get("language") if isinstance(payload[0], dict) else None
            return language.lower() if isinstance(language, str) and language else None
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    async def translate_to_russian(
        self, text: str, source_language: str | None
    ) -> TranslationResult:
        """Translate one message and return an explicit non-throwing outcome."""
        normalized_source = source_language.lower() if source_language else None
        if normalized_source == "ru":
            return TranslationResult(
                original_text=text,
                translated_text=None,
                source_language="ru",
                status=TranslationStatus.BYPASSED,
            )

        try:
            response = await self._client.post(
                "/translate",
                json={
                    "q": text,
                    "source": normalized_source or "auto",
                    "target": "ru",
                    "format": "text",
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            translated = payload.get("translatedText") if isinstance(payload, dict) else None
            if not isinstance(translated, str) or not translated:
                return self._failure(text, normalized_source, "invalid_response")
        except httpx.TimeoutException:
            return self._failure(text, normalized_source, "timeout")
        except (httpx.HTTPError, ValueError, TypeError):
            return self._failure(text, normalized_source, "service_unavailable")

        return TranslationResult(
            original_text=text,
            translated_text=translated,
            source_language=normalized_source,
            status=TranslationStatus.TRANSLATED,
        )

    @staticmethod
    def _failure(text: str, source_language: str | None, error_code: str) -> TranslationResult:
        return TranslationResult(
            original_text=text,
            translated_text=None,
            source_language=source_language,
            status=TranslationStatus.FAILED,
            error_code=error_code,
        )


class FakeTranslationAdapter:
    """In-memory adapter for workflow tests without external calls."""

    def __init__(
        self,
        *,
        detected_languages: dict[str, str | None] | None = None,
        translations: dict[str, str] | None = None,
        failing_texts: set[str] | None = None,
    ) -> None:
        self.detected_languages = detected_languages or {}
        self.translations = translations or {}
        self.failing_texts = failing_texts or set()
        self.translation_calls: list[str] = []

    async def detect_language(self, text: str) -> str | None:
        """Return a configured deterministic detection."""
        return self.detected_languages.get(text)

    async def translate_to_russian(
        self, text: str, source_language: str | None
    ) -> TranslationResult:
        """Return a configured translation, bypass, or failure."""
        normalized_source = source_language.lower() if source_language else None
        if normalized_source == "ru":
            return TranslationResult(text, None, "ru", TranslationStatus.BYPASSED)
        self.translation_calls.append(text)
        if text in self.failing_texts or text not in self.translations:
            return TranslationResult(
                text, None, normalized_source, TranslationStatus.FAILED, "fake_failure"
            )
        return TranslationResult(
            text,
            self.translations[text],
            normalized_source,
            TranslationStatus.TRANSLATED,
        )


__all__ = [
    "FakeTranslationAdapter",
    "LibreTranslateAdapter",
    "TranslationResult",
    "TranslationService",
    "TranslationStatus",
]
