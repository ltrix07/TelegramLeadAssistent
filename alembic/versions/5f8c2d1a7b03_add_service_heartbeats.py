"""add service heartbeats

Revision ID: 5f8c2d1a7b03
Revises: 3b6e2a8d9f10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5f8c2d1a7b03"
down_revision: str | None = "3b6e2a8d9f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the cross-process liveness table."""
    op.create_table(
        "service_heartbeats",
        sa.Column("service", sa.String(length=50), nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("service"),
    )


def downgrade() -> None:
    """Remove cross-process liveness storage."""
    op.drop_table("service_heartbeats")
