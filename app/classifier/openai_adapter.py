"""Async OpenAI Responses API adapter for strict classification output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openai import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    RateLimitError,
)
from pydantic import ValidationError

from app.classifier.schemas import ClassificationResult


class ClassificationAdapterError(RuntimeError):
    """Base error exposed by the classification API adapter."""

    error_code = "CLASSIFICATION_PERMANENT"
    retryable = False


class ClassificationTimeoutError(ClassificationAdapterError):
    """Raised when the classification request exceeds its configured timeout."""

    error_code = "CLASSIFICATION_TIMEOUT"
    retryable = True


class ClassificationRateLimitError(ClassificationAdapterError):
    """Raised when the classification API rate limit is reached."""

    error_code = "CLASSIFICATION_RATE_LIMIT"
    retryable = True


class ClassificationTemporaryError(ClassificationAdapterError):
    """Raised for transient connection and server-side API failures."""

    error_code = "CLASSIFICATION_TEMPORARY"
    retryable = True


class ClassificationSchemaError(ClassificationAdapterError):
    """Raised when the API does not produce a valid structured classification."""

    error_code = "CLASSIFICATION_SCHEMA"
    retryable = True


class ClassificationPermanentError(ClassificationAdapterError):
    """Raised for API failures that cannot be corrected by retrying the same request."""

    error_code = "CLASSIFICATION_PERMANENT"


@dataclass(frozen=True, slots=True)
class ClassificationUsage:
    """Token usage reported by one Responses API call."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class ClassificationResponse:
    """Validated classification and its usage metadata."""

    result: ClassificationResult
    usage: ClassificationUsage


class ClassificationTransport(Protocol):
    """Transport seam used by production OpenAI and deterministic test fakes."""

    async def classify(
        self,
        *,
        model: str,
        instructions: str,
        target_text: str,
        timeout_seconds: float,
    ) -> ClassificationResponse:
        """Request one strict classification response."""


class OpenAIResponsesTransport:
    """OpenAI SDK implementation of the classification transport."""

    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client

    async def classify(
        self,
        *,
        model: str,
        instructions: str,
        target_text: str,
        timeout_seconds: float,
    ) -> ClassificationResponse:
        """Call Responses API with a strict Pydantic Structured Output."""
        try:
            response = await self._client.responses.parse(
                model=model,
                instructions=instructions,
                input=target_text,
                text_format=ClassificationResult,
                timeout=timeout_seconds,
            )
        except APITimeoutError as error:
            raise ClassificationTimeoutError("Classification request timed out") from error
        except RateLimitError as error:
            raise ClassificationRateLimitError("Classification API rate limit reached") from error
        except (
            APIResponseValidationError,
            ContentFilterFinishReasonError,
            LengthFinishReasonError,
            ValidationError,
        ) as error:
            raise ClassificationSchemaError(
                "Classification response did not match the required schema"
            ) from error
        except APIConnectionError as error:
            raise ClassificationTemporaryError("Classification API connection failed") from error
        except APIStatusError as error:
            if error.status_code >= 500:
                raise ClassificationTemporaryError(
                    "Classification API server request failed"
                ) from error
            raise ClassificationPermanentError("Classification API rejected the request") from error
        except APIError as error:
            raise ClassificationPermanentError("Classification API request failed") from error

        parsed = response.output_parsed
        usage = response.usage
        if parsed is None or usage is None:
            raise ClassificationSchemaError(
                "Classification response did not contain structured output and usage"
            )

        return ClassificationResponse(
            result=parsed,
            usage=ClassificationUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
            ),
        )


class OpenAIClassificationAdapter:
    """Configured async boundary used by classification workflows."""

    def __init__(
        self,
        *,
        transport: ClassificationTransport,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self._transport = transport
        self._model = model
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        """Return the configured model name used for accounting metadata."""
        return self._model

    async def classify(self, *, instructions: str, target_text: str) -> ClassificationResponse:
        """Classify target text using configured API settings."""
        return await self._transport.classify(
            model=self._model,
            instructions=instructions,
            target_text=target_text,
            timeout_seconds=self._timeout_seconds,
        )


def build_openai_classification_adapter(
    *, api_key: str, model: str, timeout_seconds: float
) -> OpenAIClassificationAdapter:
    """Build the production adapter without exposing SDK details to workflows."""
    client = AsyncOpenAI(api_key=api_key, max_retries=0)
    return OpenAIClassificationAdapter(
        transport=OpenAIResponsesTransport(client),
        model=model,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "ClassificationAdapterError",
    "ClassificationResponse",
    "ClassificationPermanentError",
    "ClassificationRateLimitError",
    "ClassificationSchemaError",
    "ClassificationTemporaryError",
    "ClassificationTimeoutError",
    "ClassificationTransport",
    "ClassificationUsage",
    "OpenAIClassificationAdapter",
    "OpenAIResponsesTransport",
    "build_openai_classification_adapter",
]
