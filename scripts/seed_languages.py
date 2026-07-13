"""Seed required local translation languages."""

from __future__ import annotations

import asyncio

from app.config import ServiceName, load_startup_settings
from app.database.repositories import TranslationLanguageRepository
from app.database.session import create_session_factory


async def seed_languages(database_url: str) -> None:
    """Persist the required base-language configuration."""
    engine, factory = create_session_factory(database_url)
    try:
        async with factory.begin() as session:
            await TranslationLanguageRepository(session).seed_required()
    finally:
        await engine.dispose()


def main() -> None:
    """Load validated settings and seed the required languages."""
    settings = load_startup_settings(ServiceName.TRANSLATION_MANAGER)
    database_url = settings.database_url
    if database_url is None:
        raise SystemExit("Configuration error: DATABASE_URL is required")
    asyncio.run(seed_languages(database_url.get_secret_value()))


if __name__ == "__main__":
    main()
