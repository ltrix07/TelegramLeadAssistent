"""Async database session factory construction."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_session_factory(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create the engine and transaction-ready session factory for a service."""
    engine = create_async_engine(database_url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
