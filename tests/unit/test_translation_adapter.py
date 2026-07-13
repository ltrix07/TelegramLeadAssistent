"""Tests for the local LibreTranslate adapter contract."""

import httpx
import pytest

from app.translation.client import (
    FakeTranslationAdapter,
    LibreTranslateAdapter,
    TranslationService,
    TranslationStatus,
)


def make_adapter(handler: httpx.MockTransport) -> LibreTranslateAdapter:
    client = httpx.AsyncClient(base_url="http://translator", transport=handler)
    return LibreTranslateAdapter(base_url="http://ignored", timeout_seconds=2, client=client)


@pytest.mark.asyncio
async def test_detect_and_translate_to_russian() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/detect":
            return httpx.Response(200, json=[{"language": "EN", "confidence": 99.0}])
        assert request.url.path == "/translate"
        assert request.method == "POST"
        assert request.content == b'{"q":"Hello","source":"en","target":"ru","format":"text"}'
        return httpx.Response(200, json={"translatedText": "Привет"})

    adapter = make_adapter(httpx.MockTransport(handle))

    language = await adapter.detect_language("Hello")
    result = await adapter.translate_to_russian("Hello", language)

    assert language == "en"
    assert result.status is TranslationStatus.TRANSLATED
    assert result.translated_text == "Привет"
    assert result.display_text == "Привет"
    assert result.error_code is None


@pytest.mark.asyncio
async def test_russian_text_bypasses_http_translation() -> None:
    def fail_if_called(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Russian text must not reach LibreTranslate")

    adapter = make_adapter(httpx.MockTransport(fail_if_called))
    result = await adapter.translate_to_russian("Уже по-русски", "RU")

    assert result.status is TranslationStatus.BYPASSED
    assert result.display_text == "Уже по-русски"
    assert result.translated_text is None


@pytest.mark.asyncio
async def test_timeout_returns_original_with_explicit_failure() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    adapter = make_adapter(httpx.MockTransport(timeout))
    result = await adapter.translate_to_russian("Hello", "en")

    assert result.status is TranslationStatus.FAILED
    assert result.error_code == "timeout"
    assert result.display_text == "Hello"


@pytest.mark.asyncio
async def test_detection_and_invalid_translation_fail_independently() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/detect":
            return httpx.Response(503)
        return httpx.Response(200, json={"unexpected": "shape"})

    adapter = make_adapter(httpx.MockTransport(handle))

    assert await adapter.detect_language("unknown") is None
    result = await adapter.translate_to_russian("unknown", None)
    assert result.status is TranslationStatus.FAILED
    assert result.error_code == "invalid_response"
    assert result.display_text == "unknown"


@pytest.mark.asyncio
async def test_fake_adapter_satisfies_protocol_and_supports_partial_failure() -> None:
    adapter = FakeTranslationAdapter(
        detected_languages={"Hello": "en", "Broken": "de"},
        translations={"Hello": "Привет"},
        failing_texts={"Broken"},
    )
    service: TranslationService = adapter

    success = await service.translate_to_russian("Hello", await service.detect_language("Hello"))
    failure = await service.translate_to_russian("Broken", await service.detect_language("Broken"))

    assert success.status is TranslationStatus.TRANSLATED
    assert failure.status is TranslationStatus.FAILED
    assert failure.display_text == "Broken"
    assert adapter.translation_calls == ["Hello", "Broken"]
