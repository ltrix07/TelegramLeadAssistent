"""Tests for the strict stage-1 classification contract."""

import json

import pytest
from pydantic import ValidationError

from app.classifier.prompts import STAGE1_PROMPT_VERSION, STAGE1_SYSTEM_PROMPT
from app.classifier.schemas import (
    ClassificationCategory,
    ClassificationReasonCode,
    ClassificationResult,
)


def test_valid_structured_result_parses() -> None:
    result = ClassificationResult.model_validate_json(
        json.dumps(
            {
                "is_relevant": True,
                "category": "strategy",
                "confidence": 0.91,
                "context_required": False,
                "reason_code": "STRATEGY_DECISION",
            }
        )
    )

    assert result.category is ClassificationCategory.STRATEGY
    assert result.reason_code is ClassificationReasonCode.STRATEGY_DECISION
    assert result.confidence == 0.91


@pytest.mark.parametrize(
    "payload",
    [
        "This looks like a strategy question.",
        '{"is_relevant": true}',
        json.dumps(
            {
                "is_relevant": True,
                "category": "sales",
                "confidence": 0.8,
                "context_required": False,
                "reason_code": "STRATEGY_DECISION",
            }
        ),
        json.dumps(
            {
                "is_relevant": True,
                "category": "technical",
                "confidence": 1.1,
                "context_required": False,
                "reason_code": "TECHNICAL_PROBLEM",
            }
        ),
        json.dumps(
            {
                "is_relevant": True,
                "category": "technical",
                "confidence": 0.9,
                "context_required": False,
                "reason_code": "TECHNICAL_PROBLEM",
                "answer": "Try restarting it.",
            }
        ),
    ],
)
def test_invalid_or_free_form_result_is_rejected(payload: str) -> None:
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate_json(payload)


def test_python_input_is_not_coerced() -> None:
    with pytest.raises(ValidationError):
        ClassificationResult.model_validate(
            {
                "is_relevant": "true",
                "category": "technical",
                "confidence": "0.9",
                "context_required": False,
                "reason_code": "TECHNICAL_PROBLEM",
            }
        )


def test_json_schema_is_closed_and_all_fields_are_required() -> None:
    schema = ClassificationResult.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "is_relevant",
        "category",
        "confidence",
        "context_required",
        "reason_code",
    }


def test_stage1_prompt_is_versioned_and_has_no_profile_fields() -> None:
    normalized_prompt = STAGE1_SYSTEM_PROMPT.casefold()

    assert STAGE1_PROMPT_VERSION == "stage1_v2"
    assert "do not answer" in normalized_prompt
    assert "structured classificationresult fields" in normalized_prompt
    for forbidden_field in (
        "username",
        "display_name",
        "first_name",
        "last_name",
        "phone",
        "bio",
        "telegram_user_id",
    ):
        assert forbidden_field not in normalized_prompt
