"""Add durable stage-1 classification route statuses.

Revision ID: 8e3f5af41b2c
Revises: 71c74f9e582d
Create Date: 2026-07-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8e3f5af41b2c"
down_revision: str | None = "71c74f9e582d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add non-claimable downstream route states."""
    op.execute(
        "ALTER TYPE processing_job_status ADD VALUE IF NOT EXISTS 'awaiting_relevant_processing'"
    )
    op.execute("ALTER TYPE processing_job_status ADD VALUE IF NOT EXISTS 'awaiting_reply_context'")


def downgrade() -> None:
    """Rebuild the enum after removing downstream-routed jobs."""
    op.execute(
        "DELETE FROM processing_jobs WHERE status IN "
        "('awaiting_relevant_processing', 'awaiting_reply_context')"
    )
    op.drop_index("idx_processing_jobs_claim", table_name="processing_jobs")
    op.execute("ALTER TYPE processing_job_status RENAME TO processing_job_status_old")
    op.execute(
        "CREATE TYPE processing_job_status AS ENUM ('pending', 'processing', 'retry', 'failed')"
    )
    op.execute(
        "ALTER TABLE processing_jobs ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE processing_job_status "
        "USING status::text::processing_job_status, "
        "ALTER COLUMN status SET DEFAULT 'pending'::processing_job_status"
    )
    op.execute("DROP TYPE processing_job_status_old")
    op.create_index(
        "idx_processing_jobs_claim",
        "processing_jobs",
        ["next_attempt_at", "created_at"],
        postgresql_where="status IN ('pending', 'retry')",
    )
