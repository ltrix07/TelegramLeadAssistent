"""Listener-owned MTProto reply-chain snapshot worker."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.downstream import DownstreamJobRepository
from app.database.models import ProcessingJob
from app.listener.reply_chain import ReplyChainLoader, ReplyMessageSource, serialize_reply_chain


class ReplyChainSnapshotHandler:
    """Load a bounded chain through MTProto and publish it through PostgreSQL."""

    def __init__(self, source: ReplyMessageSource) -> None:
        self._loader = ReplyChainLoader(source)

    async def __call__(self, job: ProcessingJob, session: AsyncSession) -> None:
        chain = await self._loader.get_reply_chain(
            job.telegram_chat_id,
            job.telegram_message_id,
        )
        await DownstreamJobRepository(session).save_reply_chain(
            job.id,
            serialize_reply_chain(chain),
        )


__all__ = ["ReplyChainSnapshotHandler"]
