"""Add privacy-safe content fingerprints for classification deduplication.

Revision ID: b2d4e6f8a091
Revises: f1c2d3e4a5b6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2d4e6f8a091"
down_revision: str | None = "f1c2d3e4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recent_message_fingerprints",
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "telegram_chat_id",
            "fingerprint",
            name=op.f("pk_recent_message_fingerprints"),
        ),
    )
    op.create_index(
        "idx_recent_fingerprints_last_seen",
        "recent_message_fingerprints",
        ["last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_recent_fingerprints_last_seen", table_name="recent_message_fingerprints")
    op.drop_table("recent_message_fingerprints")
