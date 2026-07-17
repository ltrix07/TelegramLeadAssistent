"""add operational alert state and delivery queue

Revision ID: a4e7c1d9b205
Revises: 5f8c2d1a7b03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a4e7c1d9b205"
down_revision: str | None = "5f8c2d1a7b03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable failure state and idempotent alert delivery records."""
    op.create_table(
        "alert_conditions",
        sa.Column("condition_key", sa.String(length=100), nullable=False),
        sa.Column("failing_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("condition_key"),
    )
    op.create_table(
        "operational_alerts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("deduplication_key", sa.String(length=160), nullable=False),
        sa.Column("alert_type", sa.String(length=50), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("operator_telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'retry', 'sent', 'failed')",
            name=op.f("ck_operational_alerts_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deduplication_key"),
    )
    op.create_index(
        "idx_operational_alerts_claim",
        "operational_alerts",
        ["next_attempt_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'retry')"),
    )


def downgrade() -> None:
    """Remove operational alert storage."""
    op.drop_index("idx_operational_alerts_claim", table_name="operational_alerts")
    op.drop_table("operational_alerts")
    op.drop_table("alert_conditions")
