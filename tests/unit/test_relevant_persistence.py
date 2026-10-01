"""Unit checks for relevant-question persistence guards."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier.relevant import (
    RelevantQuestionPersistenceError,
    RelevantQuestionPersistenceService,
)
from app.database.models import (
    BotNotification,
    ClassificationRun,
    DetectedQuestion,
    ProcessingJob,
    QuestionChainMessage,
)
from app.database.queue import JobRepository
from app.domain.enums import ProcessingJobStatus
from app.listener.reply_chain import ReplyChain, ReplyChainItem
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


NOW = datetime(2026, 10, 1, tzinfo=UTC)


class _FakeSession:
    """Minimal session double: first scalar finds no question, second finds the run."""

    def __init__(self, classification: object) -> None:
        self._scalars: list[object | None] = [None, classification]
        self.added: list[object] = []

    async def scalar(self, statement: object) -> object | None:
        del statement
        return self._scalars.pop(0)

    def add(self, instance: object) -> None:
        if isinstance(instance, DetectedQuestion):
            instance.id = uuid4()
        self.added.append(instance)

    async def flush(self) -> None:
        return None


def _job(message_text: str | None = "Need a Python developer") -> ProcessingJob:
    return ProcessingJob(
        id=uuid4(),
        monitored_chat_id=uuid4(),
        telegram_chat_id=-100,
        telegram_message_id=50,
        sender_telegram_id=42,
        sender_display_name="Customer",
        message_text=message_text,
        telegram_created_at=NOW,
        status=ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING,
    )


def _parent() -> ReplyChainItem:
    return ReplyChainItem(10, None, None, None, 7, "Parent", NOW, "Parent text", False)


def _unavailable_target() -> ReplyChainItem:
    return ReplyChainItem(50, None, None, None, None, None, None, None, True, True)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    items: tuple[ReplyChainItem, ...],
    job: ProcessingJob,
    translator: FakeTranslationAdapter,
) -> tuple[_FakeSession, UUID]:
    classification = ClassificationRun(category="technical", confidence=Decimal("0.9"))
    session = _FakeSession(classification)

    async def fake_complete(self: JobRepository, job_id: UUID) -> None:
        del self, job_id

    monkeypatch.setattr(JobRepository, "complete", fake_complete)
    service = RelevantQuestionPersistenceService(
        1, translation_service=translator, translation_enabled=True
    )
    question_id = asyncio.run(
        service.persist(job, ReplyChain(chat_id=-100, items=items), cast(AsyncSession, session))
    )
    return session, question_id


def _chain_rows(session: _FakeSession) -> list[QuestionChainMessage]:
    rows = [item for item in session.added if isinstance(item, QuestionChainMessage)]
    return sorted(rows, key=lambda row: row.position)


def test_unavailable_target_is_delivered_from_job_data(monkeypatch: pytest.MonkeyPatch) -> None:
    translator = FakeTranslationAdapter(
        detected_languages={"Need a Python developer": "en"},
        translations={"Need a Python developer": "Нужен Python-разработчик"},
    )

    session, _ = _run(monkeypatch, (_unavailable_target(),), _job(), translator)

    rows = _chain_rows(session)
    assert len(rows) == 1
    row = rows[0]
    assert (row.position, row.is_target, row.reply_to_message_id) == (0, True, None)
    assert row.telegram_message_id == 50
    assert row.original_text == "Need a Python developer"
    assert row.translated_text == "Нужен Python-разработчик"
    assert row.author_telegram_id == 42
    assert row.author_display_name == "Customer"
    assert row.telegram_created_at == NOW
    assert translator.translation_calls == ["Need a Python developer"]
    question = next(item for item in session.added if isinstance(item, DetectedQuestion))
    assert question.translated_text == "Нужен Python-разработчик"
    assert any(isinstance(item, BotNotification) for item in session.added)


def test_available_parents_precede_unavailable_target(monkeypatch: pytest.MonkeyPatch) -> None:
    translator = FakeTranslationAdapter()

    session, _ = _run(monkeypatch, (_parent(), _unavailable_target()), _job(), translator)

    rows = _chain_rows(session)
    assert [(row.position, row.telegram_message_id, row.is_target) for row in rows] == [
        (0, 10, False),
        (1, 50, True),
    ]
    assert rows[1].original_text == "Need a Python developer"


def test_unavailable_target_without_job_text_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RelevantQuestionPersistenceError) as raised:
        _run(monkeypatch, (_unavailable_target(),), _job(None), FakeTranslationAdapter())

    assert raised.value.retryable is False
    assert raised.value.error_code == "RELEVANT_PERSISTENCE_REJECTED"


def test_available_chain_is_persisted_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    target = ReplyChainItem(50, 10, None, None, 42, "Customer", NOW, "How to fix?", True)

    session, _ = _run(monkeypatch, (_parent(), target), _job(), FakeTranslationAdapter())

    rows = _chain_rows(session)
    assert [(row.position, row.telegram_message_id, row.is_target) for row in rows] == [
        (0, 10, False),
        (1, 50, True),
    ]
    assert rows[1].original_text == "How to fix?"
    assert rows[1].reply_to_message_id == 10
