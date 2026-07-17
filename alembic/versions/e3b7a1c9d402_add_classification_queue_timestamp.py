"""Add classification queue timestamp for shadow-mode latency reports.

Revision ID: e3b7a1c9d402
Revises: d8a1e4c7f206
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3b7a1c9d402"
down_revision: str | None = "d8a1e4c7f206"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "classification_runs",
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE classification_runs SET queued_at = created_at WHERE queued_at IS NULL")
    op.alter_column("classification_runs", "queued_at", nullable=False)


def downgrade() -> None:
    op.drop_column("classification_runs", "queued_at")
