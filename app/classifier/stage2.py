"""Final classification using a bounded explicit reply chain."""

from __future__ import annotations

from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier.openai_adapter import OpenAIClassificationAdapter
from app.classifier.prompts import STAGE2_SYSTEM_PROMPT
from app.classifier.usage import ClassificationPricing, UsageRepository
from app.database.models import ClassificationRun, ProcessingJob
from app.database.queue import JobRepository
from app.database.worker import JobDisposition
from app.domain.enums import ProcessingJobStatus
from app.listener.reply_chain import ReplyChain
from app.metrics import increment, observe_duration


class Stage2ClassificationError(RuntimeError):
    """Reject an invalid Stage-2 transition without making another API call."""


class Stage2NonFinalResultError(RuntimeError):
    """Reject a Stage-2 response that incorrectly requests more context."""

    retryable = False
    error_code = "STAGE2_NON_FINAL_RESULT"


def format_stage2_input(chain: ReplyChain) -> str:
    """Render an oldest-to-target chain without Telegram profile metadata."""
    if not 1 <= len(chain.items) <= 10:
        raise ValueError("Stage-2 reply chain must contain between 1 and 10 items")
    if sum(item.is_target for item in chain.items) != 1 or not chain.items[-1].is_target:
        raise ValueError("Stage-2 reply chain must end with exactly one target")

    rendered: list[str] = []
    for item in chain.items:
        marker = "[TARGET]" if item.is_target else "[CONTEXT]"
        text = "[unavailable message]" if item.is_unavailable else item.text
        if text is None:
            raise ValueError("Available reply-chain items must contain text")
        rendered.append(f"{marker}\n{text}")
    return "\n\n".join(rendered)


class Stage2ClassificationService:
    """Perform the sole allowed context classification and persist its final route."""

    def __init__(
        self,
        adapter: OpenAIClassificationAdapter,
        pricing: ClassificationPricing,
    ) -> None:
        self._adapter = adapter
        self._pricing = pricing

    async def classify(
        self,
        job: ProcessingJob,
        chain: ReplyChain,
        session: AsyncSession,
    ) -> JobDisposition:
        """Run Stage 2 only after a context-required Stage 1 and never more than once."""
        if job.status is not ProcessingJobStatus.AWAITING_REPLY_CONTEXT:
            raise Stage2ClassificationError("Job is not awaiting reply context")

        runs = list(
            await session.scalars(
                select(ClassificationRun).where(
                    ClassificationRun.telegram_chat_id == job.telegram_chat_id,
                    ClassificationRun.telegram_message_id == job.telegram_message_id,
                )
            )
        )
        stage1 = next((run for run in runs if run.stage == 1), None)
        if stage1 is None or stage1.result != "context_required":
            raise Stage2ClassificationError("Stage 1 did not request reply context")
        if any(run.stage == 2 for run in runs):
            raise Stage2ClassificationError("Stage 2 has already completed")

        started_at = perf_counter()
        try:
            response = await self._adapter.classify(
                instructions=STAGE2_SYSTEM_PROMPT,
                target_text=format_stage2_input(chain),
            )
        except Exception:
            increment("classification_api_errors_total", stage=2)
            raise
        increment("classification_stage2_total")
        observe_duration("classification_latency_ms", started_at, stage=2)
        if response.result.context_required:
            raise Stage2NonFinalResultError("Stage 2 must return a final decision")

        inserted = await UsageRepository(session).record_stage(
            telegram_chat_id=job.telegram_chat_id,
            telegram_message_id=job.telegram_message_id,
            stage=2,
            queued_at=job.created_at,
            model=self._adapter.model,
            response=response,
            pricing=self._pricing,
        )
        if not inserted:
            raise Stage2ClassificationError("Stage 2 has already completed")

        if response.result.is_relevant:
            increment("classification_relevant_total", stage=2)
            await JobRepository(session).route(
                job.id, ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING
            )
            return JobDisposition.RETAIN
        increment("classification_irrelevant_total", stage=2)
        await JobRepository(session).complete(job.id)
        return JobDisposition.COMPLETE


__all__ = [
    "Stage2ClassificationError",
    "Stage2ClassificationService",
    "Stage2NonFinalResultError",
    "format_stage2_input",
]
