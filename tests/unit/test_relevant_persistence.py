"""Unit checks for relevant-question persistence guards."""

import pytest

from app.classifier.relevant import RelevantQuestionPersistenceService
from app.translation.client import FakeTranslationAdapter


def test_relevant_persistence_requires_positive_operator_id() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        RelevantQuestionPersistenceService(0)


def test_relevant_persistence_requires_adapter_when_translation_is_enabled() -> None:
    with pytest.raises(ValueError, match="translation_service is required"):
        RelevantQuestionPersistenceService(1, translation_enabled=True)


def test_relevant_persistence_accepts_translation_adapter() -> None:
    service = RelevantQuestionPersistenceService(
        1,
        translation_service=FakeTranslationAdapter(),
        translation_enabled=True,
    )

    assert service is not None
