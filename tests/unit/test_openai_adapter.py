"""Tests for the async OpenAI Responses API adapter."""

from dataclasses import dataclass

import httpx
import pytest
from openai import APITimeoutError, AsyncOpenAI

from app.classifier.openai_adapter import (
    ClassificationPermanentError,
    ClassificationRateLimitError,
    ClassificationResponse,
    ClassificationSchemaError,
    ClassificationTemporaryError,
    ClassificationTimeoutError,
    ClassificationUsage,
    OpenAIClassificationAdapter,
    OpenAIResponsesTransport,
)
from app.classifier.schemas import (
    ClassificationCategory,
    ClassificationReasonCode,
    ClassificationResult,
)


@dataclass
class FakeTransport:
    response: ClassificationResponse
    model: str | None = None
    instructions: str | None = None
    target_text: str | None = None
    timeout_seconds: float | None = None

    async def classify(
        self,
        *,
        model: str,
        instructions: str,
        target_text: str,
        timeout_seconds: float,
    ) -> ClassificationResponse:
        self.model = model
        self.instructions = instructions
        self.target_text = target_text
        self.timeout_seconds = timeout_seconds
        return self.response


def _classification_response() -> ClassificationResponse:
    return ClassificationResponse(
        result=ClassificationResult.model_validate(
            {
                "is_relevant": True,
                "category": ClassificationCategory.TECHNICAL,
                "confidence": 0.93,
                "context_required": False,
                "reason_code": ClassificationReasonCode.TECHNICAL_PROBLEM,
            }
        ),
        usage=ClassificationUsage(input_tokens=31, output_tokens=12, total_tokens=43),
    )


@pytest.mark.asyncio
async def test_adapter_uses_configured_model_timeout_and_fake_transport() -> None:
    transport = FakeTransport(_classification_response())
    adapter = OpenAIClassificationAdapter(
        transport=transport,
        model="configured-classifier-model",
        timeout_seconds=7.5,
    )

    response = await adapter.classify(
        instructions="Classify only the target.", target_text="How do I fix this?"
    )

    assert response.result.is_relevant is True
    assert response.usage == ClassificationUsage(31, 12, 43)
    assert transport.model == "configured-classifier-model"
    assert transport.timeout_seconds == 7.5
    assert transport.instructions == "Classify only the target."
    assert transport.target_text == "How do I fix this?"


@pytest.mark.asyncio
async def test_openai_transport_requests_strict_schema_and_exposes_usage() -> None:
    captured_request: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_request.update(request=request, json=__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_fake",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "configured-classifier-model",
                "output": [
                    {
                        "id": "msg_fake",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "annotations": [],
                                "logprobs": [],
                                "text": (
                                    '{"is_relevant":true,"category":"technical",'
                                    '"confidence":0.93,"context_required":false,'
                                    '"reason_code":"TECHNICAL_PROBLEM"}'
                                ),
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 31,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 12,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 43,
                },
            },
        )

    client = AsyncOpenAI(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        response = await OpenAIResponsesTransport(client).classify(
            model="configured-classifier-model",
            instructions="System rules",
            target_text="Target only",
            timeout_seconds=4,
        )
    finally:
        await client.close()

    payload = captured_request["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "configured-classifier-model"
    assert payload["instructions"] == "System rules"
    assert payload["input"] == "Target only"
    text_config = payload["text"]
    assert isinstance(text_config, dict)
    format_config = text_config["format"]
    assert isinstance(format_config, dict)
    assert format_config["strict"] is True
    assert response == _classification_response()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (429, ClassificationRateLimitError),
        (500, ClassificationTemporaryError),
        (400, ClassificationPermanentError),
    ],
)
async def test_api_status_errors_are_normalized_by_retry_category(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            request=request,
            json={"error": {"message": "safe test error", "type": "test_error"}},
        )

    client = AsyncOpenAI(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        with pytest.raises(expected_error):
            await OpenAIResponsesTransport(client).classify(
                model="configured-model",
                instructions="rules",
                target_text="target",
                timeout_seconds=1,
            )
    finally:
        await client.close()


def test_normalized_errors_expose_stable_retry_policy() -> None:
    assert ClassificationTimeoutError.retryable is True
    assert ClassificationRateLimitError.retryable is True
    assert ClassificationTemporaryError.retryable is True
    assert ClassificationSchemaError.retryable is True
    assert ClassificationPermanentError.retryable is False
    assert ClassificationSchemaError.error_code == "CLASSIFICATION_SCHEMA"


@pytest.mark.asyncio
async def test_openai_timeout_is_normalized() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fake timeout", request=request)

    client = AsyncOpenAI(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        with pytest.raises(ClassificationTimeoutError) as captured:
            await OpenAIResponsesTransport(client).classify(
                model="configured-model",
                instructions="rules",
                target_text="target",
                timeout_seconds=1,
            )
    finally:
        await client.close()

    assert isinstance(captured.value.__cause__, APITimeoutError)


@pytest.mark.asyncio
async def test_invalid_structured_output_is_normalized() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_fake",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "configured-model",
                "output": [
                    {
                        "id": "msg_fake",
                        "type": "message",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "annotations": [],
                                "logprobs": [],
                                "text": "not structured JSON",
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 1,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 1,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 2,
                },
            },
        )

    client = AsyncOpenAI(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        with pytest.raises(ClassificationSchemaError):
            await OpenAIResponsesTransport(client).classify(
                model="configured-model",
                instructions="rules",
                target_text="target",
                timeout_seconds=1,
            )
    finally:
        await client.close()
