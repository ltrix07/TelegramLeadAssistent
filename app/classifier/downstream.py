"""Classifier-owned Stage-2 and relevant-question downstream processing."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier.relevant import RelevantQuestionPersistenceService
from app.classifier.stage2 import Stage2ClassificationService
from app.database.models import ProcessingJob
from app.domain.enums import ProcessingJobStatus
from app.listener.reply_chain import deserialize_reply_chain


class DownstreamClassificationError(RuntimeError):
    """Reject malformed or unsupported downstream hand-off state."""

    retryable = False
    error_code = "INVALID_DOWNSTREAM_HANDOFF"


class DownstreamClassificationHandler:
    """Consume a listener snapshot without acquiring MTProto access."""

    def __init__(
        self,
        stage2: Stage2ClassificationService,
        persistence: RelevantQuestionPersistenceService,
    ) -> None:
        self._stage2 = stage2
        self._persistence = persistence

    async def __call__(self, job: ProcessingJob, session: AsyncSession) -> None:
        if job.reply_chain_snapshot is None:
            raise DownstreamClassificationError("Reply-chain snapshot is missing")
        chain = deserialize_reply_chain(job.reply_chain_snapshot)
        if chain.chat_id != job.telegram_chat_id:
            raise DownstreamClassificationError("Reply-chain snapshot belongs to another chat")

        if job.status is ProcessingJobStatus.AWAITING_REPLY_CONTEXT:
            await self._stage2.classify(job, chain, session)
            return
        if job.status is ProcessingJobStatus.AWAITING_RELEVANT_PROCESSING:
            await self._persistence.persist(job, chain, session)
            return
        raise DownstreamClassificationError("Unsupported downstream job status")


__all__ = ["DownstreamClassificationError", "DownstreamClassificationHandler"]
