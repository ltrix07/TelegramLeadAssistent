"""Translation manager service entry point."""

import asyncio

from app.config import ServiceName, load_startup_settings
from app.database.repositories.translation_manager_jobs import TranslationManagerJobRepository
from app.database.session import create_session_factory
from app.logging import configure_logging
from app.translation.control import ArgosControlPlane
from app.translation.jobs import TranslationJobHandler, TranslationJobRequest


async def run() -> None:
    """Poll durable jobs and execute constrained control-plane operations."""
    settings = load_startup_settings(ServiceName.TRANSLATION_MANAGER)
    configure_logging(ServiceName.TRANSLATION_MANAGER, settings)
    if settings.database_url is None:
        raise RuntimeError("validated translation manager database URL is missing")
    database_url = settings.database_url.get_secret_value()
    engine, session_factory = create_session_factory(database_url)
    handler = TranslationJobHandler(
        ArgosControlPlane(translation_base_url=settings.translation_base_url)
    )
    try:
        while True:
            processed = False
            async with session_factory.begin() as session:
                repository = TranslationManagerJobRepository(session)
                job = await repository.claim()
                if job is not None:
                    processed = True
                    try:
                        await handler.execute(
                            TranslationJobRequest(
                                action=job.action,
                                language_code=job.language_code,
                            ),
                            session,
                        )
                    except Exception as error:
                        code = getattr(error, "error_code", type(error).__name__)
                        await repository.finish(job, str(code)[:100])
                    else:
                        await repository.finish(job)
            if not processed:
                await asyncio.sleep(1)
    finally:
        await engine.dispose()


def main() -> None:
    """Start the translation manager service."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
