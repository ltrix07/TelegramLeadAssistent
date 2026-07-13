"""Persistence operations for operator FSM sessions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import OperatorSession


class ActiveDraftConflictError(Exception):
    """Raised when an operator must explicitly replace another active draft."""


class OperatorSessionRepository:
    """Store one durable FSM session per Telegram operator."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_state(self, operator_user_id: int, state: str | None) -> None:
        statement = insert(OperatorSession).values(
            operator_telegram_user_id=operator_user_id,
            state=state,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[OperatorSession.operator_telegram_user_id],
                set_={"state": state, "updated_at": statement.excluded.updated_at},
            )
        )

    async def get_state(self, operator_user_id: int) -> str | None:
        return await self._session.scalar(
            select(OperatorSession.state).where(
                OperatorSession.operator_telegram_user_id == operator_user_id
            )
        )

    async def set_data(self, operator_user_id: int, data: Mapping[str, Any]) -> None:
        stored_data = dict(data)
        statement = insert(OperatorSession).values(
            operator_telegram_user_id=operator_user_id,
            data=stored_data,
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[OperatorSession.operator_telegram_user_id],
                set_={"data": stored_data, "updated_at": statement.excluded.updated_at},
            )
        )

    async def get_data(self, operator_user_id: int) -> dict[str, Any]:
        value = await self._session.scalar(
            select(OperatorSession.data).where(
                OperatorSession.operator_telegram_user_id == operator_user_id
            )
        )
        return dict(value) if value is not None else {}

    async def update_data(self, operator_user_id: int, data: Mapping[str, Any]) -> dict[str, Any]:
        row = await self._session.scalar(
            select(OperatorSession)
            .where(OperatorSession.operator_telegram_user_id == operator_user_id)
            .with_for_update()
        )
        if row is None:
            row = OperatorSession(operator_telegram_user_id=operator_user_id, data=dict(data))
            self._session.add(row)
        else:
            row.data = {**row.data, **data}
        await self._session.flush()
        return dict(row.data)

    async def open_question(
        self, operator_user_id: int, question_id: UUID, *, replace: bool = False
    ) -> None:
        row = await self._session.scalar(
            select(OperatorSession)
            .where(OperatorSession.operator_telegram_user_id == operator_user_id)
            .with_for_update()
        )
        if row is None:
            self._session.add(
                OperatorSession(
                    operator_telegram_user_id=operator_user_id,
                    active_question_id=question_id,
                )
            )
            await self._session.flush()
            return
        if row.active_question_id not in (None, question_id) and not replace:
            raise ActiveDraftConflictError
        row.active_question_id = question_id
        await self._session.flush()

    async def clear_active_question(self, operator_user_id: int) -> None:
        row = await self._session.get(OperatorSession, operator_user_id)
        if row is not None:
            row.active_question_id = None
            await self._session.flush()

    async def get_active_question(self, operator_user_id: int) -> UUID | None:
        """Return the question currently bound to the operator flow."""
        return await self._session.scalar(
            select(OperatorSession.active_question_id).where(
                OperatorSession.operator_telegram_user_id == operator_user_id
            )
        )
