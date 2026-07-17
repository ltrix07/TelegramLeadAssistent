"""Stage-1 classification workflow and worker entry point."""

from __future__ import annotations

import asyncio
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier.downstream import DownstreamClassificationHandler
from app.classifier.openai_adapter import (
    OpenAIClassificationAdapter,
    build_openai_classification_adapter,
)
from app.classifier.prompts import STAGE1_SYSTEM_PROMPT
from app.classifier.relevant import RelevantQuestionPersistenceService
from app.classifier.stage2 import Stage2ClassificationService
from app.classifier.usage import ClassificationPricing, UsageRepository
from app.config import ServiceName, load_startup_settings
from app.database.downstream import DownstreamPhase
from app.database.health import run_heartbeat
from app.database.models import ProcessingJob
from app.database.queue import JobRepository
from app.database.session import create_session_factory
from app.database.worker import DownstreamQueueWorker, JobDisposition, QueueWorker
from app.domain.enums import ProcessingJobStatus
from app.logging import configure_logging
from app.metrics import increment, observe_duration
from app.translation.client import LibreTranslateAdapter


class Stage1ClassificationHandler:
    """Classify one claimed target and persist its downstream route atomically."""

    def __init__(
        self,
        adapter: OpenAIClassificationAdapter,
        pricing: ClassificationPricing,
    ) -> None:
        self._adapter = adapter
        self._pricing = pricing

    async def __call__(self, job: ProcessingJob, session: AsyncSession) -> JobDisposition:
        """Send only raw target text and route the validated result."""
        if job.status is not ProcessingJobStatus.PROCESSING:
            return JobDisposition.RETAIN

        started_at = perf_counter()
        try:
            response = await self._adapter.classify(
                instructions=STAGE1_SYSTEM_PROMPT,
                target_text=job.message_text,
            )
        except Exception:
            increment("classification_api_errors_total", stage=1)
            raise
        increment("classification_stage1_total")
        observe_duration("classification_latency_ms", started_at, stage=1)
        await UsageRepository(session).record_stage(
            telegram_chat_id=job.telegram_chat_id,
            telegram_message_id=job.telegram_message_id,
            stage=1,
            queued_at=job.created_at,
            model=self._adapter.model,
            response=response,
            pricing=self._pricing,
        )
        repository = JobRepository(session)
        if response.result.context_required:
            await repository.route(job.id, ProcessingJobStatus.AWAITING_REPLY_CONTEXT)
            return JobDisposition.RETAIN
        if response.result.is_relevant:
            increment("classification_relevant_total", stage=1)
            await repository.route(job.id, ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING)
            return JobDisposition.RETAIN
        increment("classification_irrelevant_total", stage=1)
        return JobDisposition.COMPLETE


async def _run() -> None:
    settings = load_startup_settings(ServiceName.CLASSIFICATION_WORKER)
    configure_logging(ServiceName.CLASSIFICATION_WORKER, settings)
    assert settings.database_url is not None
    assert settings.openai_api_key is not None
    engine, session_factory = create_session_factory(settings.database_url.get_secret_value())
    adapter = build_openai_classification_adapter(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_classifier_model,
        timeout_seconds=settings.classification_request_timeout_seconds,
    )
    pricing = ClassificationPricing(
        input_per_million_usd=settings.openai_classifier_input_price_per_million_usd,
        output_per_million_usd=settings.openai_classifier_output_price_per_million_usd,
    )
    stage1_worker = QueueWorker(
        session_factory,
        "classification-worker-1",
        Stage1ClassificationHandler(adapter, pricing),
    )
    if settings.operator_telegram_user_id is None:
        raise RuntimeError("Validated classifier operator user ID is missing")
    translation = LibreTranslateAdapter(
        base_url=settings.translation_base_url,
        timeout_seconds=settings.translation_request_timeout_seconds,
    )
    downstream_worker = DownstreamQueueWorker(
        session_factory,
        "classification-downstream-worker-1",
        DownstreamPhase.CLASSIFICATION,
        DownstreamClassificationHandler(
            Stage2ClassificationService(adapter, pricing),
            RelevantQuestionPersistenceService(
                settings.operator_telegram_user_id,
                translation_service=translation,
                translation_enabled=settings.translation_enabled,
            ),
        ),
    )
    try:
        await asyncio.gather(
            run_heartbeat(session_factory, "classification-worker"),
            stage1_worker.run_forever(),
            downstream_worker.run_forever(),
        )
    finally:
        await translation.aclose()
        await engine.dispose()


def main() -> None:
    """Start the classification worker."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
