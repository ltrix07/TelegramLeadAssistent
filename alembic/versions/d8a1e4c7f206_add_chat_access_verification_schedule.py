"""add durable chat access verification schedule

Revision ID: d8a1e4c7f206
Revises: a4e7c1d9b205
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8a1e4c7f206"
down_revision: str | None = "a4e7c1d9b205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add daily scheduling and consecutive access-loss evidence."""
    op.add_column(
        "monitored_chats",
        sa.Column(
            "next_verification_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.add_column(
        "monitored_chats",
        sa.Column(
            "consecutive_access_failures",
            sa.SmallInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "monitored_chats_access_failures_non_negative",
        "monitored_chats",
        "consecutive_access_failures >= 0",
    )
    op.create_index(
        "idx_monitored_chats_verification_due",
        "monitored_chats",
        ["next_verification_at"],
        postgresql_where=sa.text("status <> 'disabled'"),
    )


def downgrade() -> None:
    """Remove durable chat verification scheduling."""
    op.drop_index("idx_monitored_chats_verification_due", table_name="monitored_chats")
    op.drop_constraint(
        "monitored_chats_access_failures_non_negative", "monitored_chats", type_="check"
    )
    op.drop_column("monitored_chats", "consecutive_access_failures")
    op.drop_column("monitored_chats", "next_verification_at")
