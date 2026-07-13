"""Strict schemas returned by the classification model."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ClassificationCategory(StrEnum):
    """Supported relevance categories."""

    TECHNICAL = "technical"
    OPERATIONAL = "operational"
    STRATEGY = "strategy"
    ANALYTICS = "analytics"
    PROBLEM_SOLVING = "problem_solving"
    IRRELEVANT = "irrelevant"


class ClassificationReasonCode(StrEnum):
    """Closed reason-code vocabulary for classification decisions."""

    TECHNICAL_PROBLEM = "TECHNICAL_PROBLEM"
    IMPLEMENTATION_QUESTION = "IMPLEMENTATION_QUESTION"
    PROCESS_PROBLEM = "PROCESS_PROBLEM"
    STRATEGY_DECISION = "STRATEGY_DECISION"
    COMPARISON_REQUEST = "COMPARISON_REQUEST"
    ANALYTICS_QUESTION = "ANALYTICS_QUESTION"
    REQUESTS_RECOMMENDATION = "REQUESTS_RECOMMENDATION"
    CASUAL_CONVERSATION = "CASUAL_CONVERSATION"
    ADVERTISEMENT = "ADVERTISEMENT"
    RHETORICAL_QUESTION = "RHETORICAL_QUESTION"
    UNRELATED_TOPIC = "UNRELATED_TOPIC"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class ClassificationResult(BaseModel):
    """Strict structured output contract shared with the OpenAI adapter."""

    model_config = ConfigDict(extra="forbid", strict=True)

    is_relevant: bool
    category: ClassificationCategory
    confidence: float = Field(ge=0, le=1)
    context_required: bool
    reason_code: ClassificationReasonCode


__all__ = [
    "ClassificationCategory",
    "ClassificationReasonCode",
    "ClassificationResult",
]
