"""Tests for the offline-first classification evaluation harness."""

import asyncio
from collections import Counter

import pytest

from app.classifier.evaluation import (
    EvaluationFixture,
    FixtureClassifier,
    evaluate,
    fixture_distribution,
    format_report,
    load_fixtures,
    main,
)
from app.classifier.schemas import (
    ClassificationCategory,
    ClassificationReasonCode,
    ClassificationResult,
)


def test_fixture_dataset_matches_spec_distribution() -> None:
    fixtures = load_fixtures()

    assert len(fixtures) == 100
    assert fixture_distribution(fixtures) == Counter(
        {
            "technical": 30,
            "strategy": 20,
            "operational": 15,
            "analytics": 10,
            "irrelevant": 25,
        }
    )
    assert sum(fixture.expected_is_relevant for fixture in fixtures) == 75
    assert all(fixture.text.strip() for fixture in fixtures)


@pytest.mark.asyncio
async def test_deterministic_fake_evaluation_meets_initial_quality_gate() -> None:
    report = await evaluate(load_fixtures(), FixtureClassifier())

    assert report.precision >= 0.75
    assert report.recall >= 0.85
    assert report.category_accuracy == 1.0
    assert report.context_accuracy == 1.0
    assert report.total == 100


@pytest.mark.asyncio
async def test_report_calculates_false_positive_and_false_negative() -> None:
    fixtures = load_fixtures()[:2]

    class WrongClassifier:
        calls = 0

        async def classify(self, fixture: EvaluationFixture) -> ClassificationResult:
            self.calls += 1
            is_relevant = self.calls == 2
            return ClassificationResult(
                is_relevant=is_relevant,
                category=ClassificationCategory.IRRELEVANT,
                confidence=0.5,
                context_required=False,
                reason_code=ClassificationReasonCode.UNRELATED_TOPIC,
            )

    report = await evaluate(fixtures, WrongClassifier())

    assert report.true_positives == 1
    assert report.false_positives == 0
    assert report.false_negatives == 1
    assert report.precision == 1.0
    assert report.recall == 0.5


def test_default_command_is_offline_and_prints_aggregate_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert main([]) == 0

    output = capsys.readouterr().out
    assert "mode=fake" in output
    assert "fixtures=100" in output
    assert "precision=1.000" in output
    assert "recall=1.000" in output
    assert "OPENAI" not in output


def test_live_command_requires_explicit_key_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="OPENAI_API_KEY is required only with --live"):
        main(["--live"])


def test_report_contains_only_aggregate_metrics() -> None:
    report_text = format_report(
        asyncio.run(evaluate(load_fixtures(), FixtureClassifier())),
        mode="fake",
    )

    assert load_fixtures()[0].text not in report_text
