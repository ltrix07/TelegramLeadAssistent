"""Integration coverage for periodic stale-lock recovery."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from alembic.config import Config
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.database.models import (
    BotNotification,
    ClassificationRun,
    DetectedQuestion,
    MonitoredChat,
    OutboundCommand,
    ProcessingJob,
    QuestionChainMessage,
    ReplyVersion,
)
from app.database.queue import JobRepository, NewJob
from app.database.repositories.retention import RetentionCleanupResult
from app.domain.enums import (
    MonitoredChatStatus,
    MonitoredChatType,
    OutboundCommandStatus,
    ProcessingJobStatus,
    QuestionStatus,
)
from app.maintenance.scheduler import MaintenanceScheduler

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for maintenance integration tests")
    return value


async def _exercise(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE monitored_chats CASCADE")
        async with factory.begin() as session:
            chat = MonitoredChat(
                telegram_chat_id=-1009001,
                title="Maintenance Test",
                chat_type=MonitoredChatType.SUPERGROUP,
                status=MonitoredChatStatus.ACTIVE,
                added_by_telegram_user_id=1,
            )
            session.add(chat)
            await session.flush()
            repository = JobRepository(session)
            stale_job_id = await repository.enqueue(
                NewJob(chat.id, chat.telegram_chat_id, 1, "stale", now)
            )
            active_job_id = await repository.enqueue(
                NewJob(chat.id, chat.telegram_chat_id, 2, "active", now)
            )
            question = DetectedQuestion(
                monitored_chat_id=chat.id,
                telegram_chat_id=chat.telegram_chat_id,
                telegram_message_id=3,
                telegram_created_at=now,
                original_text="question",
                category="product",
                status=QuestionStatus.SEND_REQUESTED,
            )
            session.add(question)
            await session.flush()
            outbound = OutboundCommand(
                question_id=question.id,
                command_type="send_reply",
                reply_version=1,
                idempotency_key="maintenance-stale-send",
                telegram_chat_id=chat.telegram_chat_id,
                source_message_id=question.telegram_message_id,
                text="reply",
                status=OutboundCommandStatus.PROCESSING,
                locked_at=now - timedelta(minutes=10),
                locked_by="crashed-listener",
            )
            session.add(outbound)
            await session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == stale_job_id)
                .values(
                    status=ProcessingJobStatus.PROCESSING,
                    locked_at=now - timedelta(minutes=10),
                    locked_by="crashed-worker",
                )
            )
            await session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id == active_job_id)
                .values(
                    status=ProcessingJobStatus.PROCESSING,
                    locked_at=now,
                    locked_by="active-worker",
                )
            )
            await session.flush()
            outbound_id = outbound.id

            expired_job_ids = []
            for message_id in (10, 11):
                job_id = await repository.enqueue(
                    NewJob(chat.id, chat.telegram_chat_id, message_id, "expired", now)
                )
                expired_job_ids.append(job_id)
            await session.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id.in_(expired_job_ids))
                .values(expires_at=now - timedelta(seconds=1))
            )

            expired_question = DetectedQuestion(
                monitored_chat_id=chat.id,
                telegram_chat_id=chat.telegram_chat_id,
                telegram_message_id=20,
                telegram_created_at=now - timedelta(days=61),
                original_text="expired question",
                category="product",
                expires_at=now - timedelta(seconds=1),
            )
            fresh_question = DetectedQuestion(
                monitored_chat_id=chat.id,
                telegram_chat_id=chat.telegram_chat_id,
                telegram_message_id=21,
                telegram_created_at=now,
                original_text="fresh question",
                category="product",
                expires_at=now + timedelta(days=60),
            )
            session.add_all([expired_question, fresh_question])
            await session.flush()
            session.add_all(
                [
                    QuestionChainMessage(
                        question_id=expired_question.id,
                        position=0,
                        telegram_message_id=20,
                        telegram_created_at=now,
                        original_text="expired chain",
                        translation_status="not_required",
                        is_target=True,
                    ),
                    ReplyVersion(
                        question_id=expired_question.id,
                        version_number=1,
                        text="expired reply",
                        action="draft",
                    ),
                    BotNotification(
                        question_id=expired_question.id,
                        operator_telegram_user_id=1,
                        bot_chat_id=1,
                    ),
                    OutboundCommand(
                        question_id=expired_question.id,
                        command_type="send_reply",
                        reply_version=1,
                        idempotency_key="expired-outbound",
                        telegram_chat_id=chat.telegram_chat_id,
                        source_message_id=20,
                        text="expired reply",
                    ),
                    ClassificationRun(
                        telegram_chat_id=chat.telegram_chat_id,
                        telegram_message_id=30,
                        stage=1,
                        result="relevant",
                        category="product",
                        model="test-model",
                        created_at=now - timedelta(days=61),
                    ),
                    ClassificationRun(
                        telegram_chat_id=chat.telegram_chat_id,
                        telegram_message_id=31,
                        stage=1,
                        result="relevant",
                        category="product",
                        model="test-model",
                        created_at=now,
                    ),
                ]
            )
            await session.flush()
            expired_question_id = expired_question.id
            fresh_question_id = fresh_question.id

        scheduler = MaintenanceScheduler(
            factory,
            interval_seconds=30,
            stale_lock_timeout=timedelta(minutes=5),
            temporary_ttl=timedelta(hours=24),
            relevant_retention=timedelta(days=60),
            retention_batch_size=1,
        )
        first = await scheduler.run_once()
        second = await scheduler.run_once()
        third = await scheduler.run_once()

        assert first.processing_recovered == [stale_job_id]
        assert first.outbound_recovered == [outbound_id]
        assert first.retention == RetentionCleanupResult(1, 1, 1)
        assert second.processing_recovered == []
        assert second.outbound_recovered == []
        assert second.retention == RetentionCleanupResult(1, 0, 0)
        assert third.retention == RetentionCleanupResult(0, 0, 0)
        async with factory() as session:
            stale_job = await session.get(ProcessingJob, stale_job_id)
            active_job = await session.get(ProcessingJob, active_job_id)
            stored_outbound = await session.get(OutboundCommand, outbound_id)
            stored_question_status = await session.scalar(
                select(DetectedQuestion.status).where(DetectedQuestion.id == question.id)
            )
            assert stale_job is not None and stale_job.status is ProcessingJobStatus.RETRY
            assert stale_job.locked_at is None and stale_job.locked_by is None
            assert active_job is not None and active_job.status is ProcessingJobStatus.PROCESSING
            assert active_job.locked_by == "active-worker"
            assert stored_outbound is not None
            assert stored_outbound.status is OutboundCommandStatus.NEEDS_REVIEW
            assert stored_outbound.locked_at is None and stored_outbound.locked_by is None
            assert stored_question_status is QuestionStatus.SEND_FAILED
            assert await session.get(DetectedQuestion, expired_question_id) is None
            assert await session.get(DetectedQuestion, fresh_question_id) is not None
            for model in (QuestionChainMessage, ReplyVersion, BotNotification):
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.question_id == expired_question_id)
                    )
                    == 0
                )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(OutboundCommand)
                    .where(OutboundCommand.question_id == expired_question_id)
                )
                == 0
            )
            assert await session.scalar(select(func.count()).select_from(ClassificationRun)) == 1
    finally:
        await engine.dispose()


def test_stale_locks_are_recovered_once_and_restart_is_safe() -> None:
    database_url = _database_url()
    command.upgrade(Config("alembic.ini"), "head")

    asyncio.run(_exercise(database_url))
