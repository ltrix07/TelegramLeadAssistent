"""add processing reply chain snapshot

Revision ID: 7d2f6a9c4e11
Revises: c2a94b7d31e8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7d2f6a9c4e11"
down_revision: str | None = "c2a94b7d31e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column(
            "reply_chain_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    downstream_statuses = "status IN ('awaiting_relevant_processing', 'awaiting_reply_context')"
    op.create_index(
        "idx_processing_jobs_chain_load",
        "processing_jobs",
        ["next_attempt_at", "created_at"],
        unique=False,
        postgresql_where=sa.text(f"{downstream_statuses} AND reply_chain_snapshot IS NULL"),
    )
    op.create_index(
        "idx_processing_jobs_downstream",
        "processing_jobs",
        ["next_attempt_at", "created_at"],
        unique=False,
        postgresql_where=sa.text(f"{downstream_statuses} AND reply_chain_snapshot IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_processing_jobs_downstream", table_name="processing_jobs")
    op.drop_index("idx_processing_jobs_chain_load", table_name="processing_jobs")
    op.drop_column("processing_jobs", "reply_chain_snapshot")
