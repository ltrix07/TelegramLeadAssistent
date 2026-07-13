"""Integration coverage for required translation-language invariants."""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic.config import Config
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.database.models import TranslationLanguage, TranslationManagerJob
from app.database.repositories import TranslationLanguageRepository
from app.database.repositories.translation_manager_jobs import TranslationManagerJobRepository
from app.domain.enums import TranslationManagerAction, TranslationManagerJobStatus

pytestmark = pytest.mark.integration


def _database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for translation language integration tests")
    return value


async def _exercise_required_languages(database_url: str) -> None:
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory.begin() as session:
            repository = TranslationLanguageRepository(session)
            await repository.seed_required()
            await repository.seed_required()

        async with factory() as session:
            languages = list(
                await session.scalars(
                    select(TranslationLanguage)
                    .where(TranslationLanguage.language_code.in_(("en", "ru")))
                    .order_by(TranslationLanguage.language_code)
                )
            )
            assert [language.language_code for language in languages] == ["en", "ru"]
            assert all(language.is_required for language in languages)
            assert all(language.is_enabled for language in languages)
            assert all(language.installation_status == "installed" for language in languages)
            assert all(language.installed_at is not None for language in languages)

        async with factory.begin() as session:
            repository = TranslationLanguageRepository(session)
            assert await repository.disable("en") is False
            assert await repository.delete("ru") is False

        async with factory.begin() as session:
            session.add(
                TranslationLanguage(
                    language_code="de",
                    display_name="German",
                    is_required=False,
                    is_enabled=True,
                    installation_status="installed",
                )
            )
        async with factory.begin() as session:
            repository = TranslationLanguageRepository(session)
            assert await repository.disable("de") is True
            assert await repository.delete("de") is True

        for statement in (
            update(TranslationLanguage)
            .where(TranslationLanguage.language_code == "en")
            .values(is_required=False, is_enabled=False),
            delete(TranslationLanguage).where(TranslationLanguage.language_code == "ru"),
        ):
            with pytest.raises(DBAPIError):
                async with factory.begin() as session:
                    await session.execute(statement)

        async with factory.begin() as session:
            await session.execute(delete(TranslationManagerJob))
            job_repository = TranslationManagerJobRepository(session)
            install = await job_repository.enqueue(TranslationManagerAction.INSTALL, "de")
            disable = await job_repository.enqueue(TranslationManagerAction.DISABLE, "de")

        async with factory() as session:
            jobs = await TranslationManagerJobRepository(session).list_recent()
            assert [job.id for job in jobs] == [disable.id, install.id]
            assert all(job.status is TranslationManagerJobStatus.PENDING for job in jobs)
            assert all(job.language_code == "de" for job in jobs)
    finally:
        await engine.dispose()


def test_required_language_seed_and_invariants(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = _database_url()
    monkeypatch.setenv("DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")

    asyncio.run(_exercise_required_languages(database_url))
