"""Offline-first evaluation harness for the stage-1 classifier."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, TypeAdapter

from app.classifier.openai_adapter import (
    OpenAIClassificationAdapter,
    build_openai_classification_adapter,
)
from app.classifier.prompts import STAGE1_SYSTEM_PROMPT
from app.classifier.schemas import (
    ClassificationCategory,
    ClassificationReasonCode,
    ClassificationResult,
)

DEFAULT_FIXTURE_PATH = Path(__file__).with_name("fixtures") / "stage1_v1.json"


class EvaluationFixture(BaseModel):
    """One labeled stage-1 message without Telegram profile data."""

    model_config = ConfigDict(extra="forbid", strict=True)

    fixture_id: str
    text: str
    expected_is_relevant: bool
    expected_category: ClassificationCategory
    expected_context_required: bool = False


class EvaluationClassifier(Protocol):
    """Small classifier boundary shared by fake and live evaluation."""

    async def classify(self, fixture: EvaluationFixture) -> ClassificationResult:
        """Classify one fixture."""


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Aggregate binary and category metrics for one dataset run."""

    total: int
    true_positives: int
    false_positives: int
    false_negatives: int
    category_matches: int
    context_matches: int

    @property
    def precision(self) -> float:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else 1.0

    @property
    def category_accuracy(self) -> float:
        return self.category_matches / self.total if self.total else 1.0

    @property
    def context_accuracy(self) -> float:
        return self.context_matches / self.total if self.total else 1.0


class FixtureClassifier:
    """Deterministic network-free classifier used by the default evaluation."""

    async def classify(self, fixture: EvaluationFixture) -> ClassificationResult:
        """Return the fixture label through the production result schema."""
        return ClassificationResult(
            is_relevant=fixture.expected_is_relevant,
            category=fixture.expected_category,
            confidence=1.0,
            context_required=fixture.expected_context_required,
            reason_code=_reason_code_for(fixture.expected_category),
        )


class LiveClassifier:
    """Explicit live adapter wrapper for manual prompt evaluation."""

    def __init__(self, adapter: OpenAIClassificationAdapter) -> None:
        self._adapter = adapter

    async def classify(self, fixture: EvaluationFixture) -> ClassificationResult:
        """Classify only the labeled target text through Responses API."""
        response = await self._adapter.classify(
            instructions=STAGE1_SYSTEM_PROMPT,
            target_text=fixture.text,
        )
        return response.result


def _reason_code_for(category: ClassificationCategory) -> ClassificationReasonCode:
    return {
        ClassificationCategory.TECHNICAL: ClassificationReasonCode.TECHNICAL_PROBLEM,
        ClassificationCategory.OPERATIONAL: ClassificationReasonCode.PROCESS_PROBLEM,
        ClassificationCategory.STRATEGY: ClassificationReasonCode.STRATEGY_DECISION,
        ClassificationCategory.ANALYTICS: ClassificationReasonCode.ANALYTICS_QUESTION,
        ClassificationCategory.PROBLEM_SOLVING: ClassificationReasonCode.REQUESTS_RECOMMENDATION,
        ClassificationCategory.IRRELEVANT: ClassificationReasonCode.UNRELATED_TOPIC,
    }[category]


def load_fixtures(path: Path = DEFAULT_FIXTURE_PATH) -> list[EvaluationFixture]:
    """Load and strictly validate a JSON fixture dataset."""
    fixtures = TypeAdapter(list[EvaluationFixture]).validate_json(path.read_text(encoding="utf-8"))
    fixture_ids = [fixture.fixture_id for fixture in fixtures]
    if len(fixture_ids) != len(set(fixture_ids)):
        raise ValueError("Evaluation fixture ids must be unique")
    return fixtures


async def evaluate(
    fixtures: Sequence[EvaluationFixture], classifier: EvaluationClassifier
) -> EvaluationReport:
    """Evaluate labeled fixtures without retaining predictions or message text."""
    true_positives = false_positives = false_negatives = 0
    category_matches = context_matches = 0
    for fixture in fixtures:
        result = await classifier.classify(fixture)
        if result.is_relevant and fixture.expected_is_relevant:
            true_positives += 1
        elif result.is_relevant:
            false_positives += 1
        elif fixture.expected_is_relevant:
            false_negatives += 1
        category_matches += result.category is fixture.expected_category
        context_matches += result.context_required is fixture.expected_context_required

    return EvaluationReport(
        total=len(fixtures),
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        category_matches=category_matches,
        context_matches=context_matches,
    )


def fixture_distribution(fixtures: Sequence[EvaluationFixture]) -> Counter[str]:
    """Return category counts suitable for acceptance checks and reports."""
    return Counter(fixture.expected_category.value for fixture in fixtures)


def format_report(report: EvaluationReport, *, mode: str) -> str:
    """Format aggregate metrics only; fixture text and secrets are never included."""
    return "\n".join(
        (
            f"mode={mode}",
            f"fixtures={report.total}",
            f"precision={report.precision:.3f}",
            f"recall={report.recall:.3f}",
            f"category_accuracy={report.category_accuracy:.3f}",
            f"context_accuracy={report.context_accuracy:.3f}",
            f"true_positives={report.true_positives}",
            f"false_positives={report.false_positives}",
            f"false_negatives={report.false_negatives}",
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate stage-1 classification fixtures")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument(
        "--live",
        action="store_true",
        help="explicitly use the configured OpenAI Responses API instead of the fake",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_CLASSIFIER_MODEL", "gpt-5.4-nano-2026-03-17"),
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


async def _run(args: argparse.Namespace) -> EvaluationReport:
    fixtures = load_fixtures(args.fixtures)
    if args.live:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY is required only with --live")
        classifier: EvaluationClassifier = LiveClassifier(
            build_openai_classification_adapter(
                api_key=api_key,
                model=args.model,
                timeout_seconds=args.timeout,
            )
        )
    else:
        classifier = FixtureClassifier()
    return await evaluate(fixtures, classifier)


def main(argv: Sequence[str] | None = None) -> int:
    """Run deterministic evaluation by default and live evaluation only by opt-in."""
    args = _build_parser().parse_args(argv)
    report = asyncio.run(_run(args))
    print(format_report(report, mode="live" if args.live else "fake"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
