"""add persistent operator sessions

Revision ID: c2a94b7d31e8
Revises: 9b31d6f7a4c2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c2a94b7d31e8"
down_revision: str | None = "9b31d6f7a4c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_sessions",
        sa.Column("operator_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=255), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("active_question_id", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["active_question_id"],
            ["detected_questions.id"],
            name=op.f("fk_operator_sessions_active_question_id_detected_questions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("operator_telegram_user_id", name=op.f("pk_operator_sessions")),
    )


def downgrade() -> None:
    op.drop_table("operator_sessions")
