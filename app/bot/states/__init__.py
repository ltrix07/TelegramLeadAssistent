"""Operator bot states."""

from aiogram.fsm.state import State, StatesGroup


class ReplyFlow(StatesGroup):
    """Durable manual reply composition flow."""

    waiting_for_draft = State()
    waiting_for_send_confirmation = State()
    waiting_for_sent_edit = State()
    waiting_for_sent_edit_confirmation = State()


__all__ = ["ReplyFlow"]
