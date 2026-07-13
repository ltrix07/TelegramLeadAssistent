"""PostgreSQL-backed aiogram FSM storage for the operator bot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.repositories.operator_sessions import OperatorSessionRepository


class PostgresOperatorStorage(BaseStorage):
    """Persist private operator FSM state without owning the shared DB engine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        async with self._session_factory.begin() as session:
            await OperatorSessionRepository(session).set_state(key.user_id, value)

    async def get_state(self, key: StorageKey) -> str | None:
        async with self._session_factory() as session:
            return await OperatorSessionRepository(session).get_state(key.user_id)

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        async with self._session_factory.begin() as session:
            await OperatorSessionRepository(session).set_data(key.user_id, data)

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with self._session_factory() as session:
            return await OperatorSessionRepository(session).get_data(key.user_id)

    async def update_data(self, key: StorageKey, data: Mapping[str, Any]) -> dict[str, Any]:
        async with self._session_factory.begin() as session:
            return await OperatorSessionRepository(session).update_data(key.user_id, data)

    async def close(self) -> None:
        """Leave lifecycle management to the application-owned shared engine."""
