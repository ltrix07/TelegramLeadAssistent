"""Detach retained questions when a monitored chat is removed.

Revision ID: f1c2d3e4a5b6
Revises: e3b7a1c9d402
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1c2d3e4a5b6"
down_revision: str | None = "e3b7a1c9d402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve detected-question history when a monitored chat is deleted."""
    op.drop_constraint(
        "fk_detected_questions_monitored_chat_id_monitored_chats",
        "detected_questions",
        type_="foreignkey",
    )
    op.alter_column("detected_questions", "monitored_chat_id", nullable=True)
    op.create_foreign_key(
        "fk_detected_questions_monitored_chat_id_monitored_chats",
        "detected_questions",
        "monitored_chats",
        ["monitored_chat_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Restore the original required monitored-chat reference."""
    op.drop_constraint(
        "fk_detected_questions_monitored_chat_id_monitored_chats",
        "detected_questions",
        type_="foreignkey",
    )
    # This fails if upgrade-created orphaned questions exist; that is intentional.
    op.alter_column("detected_questions", "monitored_chat_id", nullable=False)
    op.create_foreign_key(
        "fk_detected_questions_monitored_chat_id_monitored_chats",
        "detected_questions",
        "monitored_chats",
        ["monitored_chat_id"],
        ["id"],
    )
