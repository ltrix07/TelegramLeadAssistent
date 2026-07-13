"""Add terminal failed processing job status.

Revision ID: 71c74f9e582d
Revises: 0e3f01f9c238
Create Date: 2026-07-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "71c74f9e582d"
down_revision: str | None = "0e3f01f9c238"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the terminal status without rewriting the queue table."""
    op.execute("ALTER TYPE processing_job_status ADD VALUE IF NOT EXISTS 'failed'")


def downgrade() -> None:
    """Rebuild the enum after removing terminal jobs."""
    op.execute("DELETE FROM processing_jobs WHERE status = 'failed'")
    op.drop_index("idx_processing_jobs_claim", table_name="processing_jobs")
    op.execute("ALTER TYPE processing_job_status RENAME TO processing_job_status_old")
    op.execute("CREATE TYPE processing_job_status AS ENUM ('pending', 'processing', 'retry')")
    op.execute(
        "ALTER TABLE processing_jobs ALTER COLUMN status DROP DEFAULT, "
        "ALTER COLUMN status TYPE processing_job_status USING status::text::processing_job_status, "
        "ALTER COLUMN status SET DEFAULT 'pending'::processing_job_status"
    )
    op.execute("DROP TYPE processing_job_status_old")
    op.create_index(
        "idx_processing_jobs_claim",
        "processing_jobs",
        ["next_attempt_at", "created_at"],
        postgresql_where="status IN ('pending', 'retry')",
    )
