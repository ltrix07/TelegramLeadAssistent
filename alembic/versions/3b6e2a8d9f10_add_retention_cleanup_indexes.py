"""add retention cleanup indexes and cascade

Revision ID: 3b6e2a8d9f10
Revises: 7d2f6a9c4e11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3b6e2a8d9f10"
down_revision: str | None = "7d2f6a9c4e11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Support bounded TTL scans and cascade question-owned commands."""
    op.create_index("idx_processing_jobs_expiry", "processing_jobs", ["expires_at"], unique=False)
    op.create_index(
        "idx_classification_runs_created_at",
        "classification_runs",
        ["created_at"],
        unique=False,
    )
    op.drop_constraint(
        "fk_outbound_commands_question_id_detected_questions",
        "outbound_commands",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_outbound_commands_question_id_detected_questions",
        "outbound_commands",
        "detected_questions",
        ["question_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Restore the original outbound foreign key and remove cleanup indexes."""
    op.drop_constraint(
        "fk_outbound_commands_question_id_detected_questions",
        "outbound_commands",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_outbound_commands_question_id_detected_questions",
        "outbound_commands",
        "detected_questions",
        ["question_id"],
        ["id"],
    )
    op.drop_index("idx_classification_runs_created_at", table_name="classification_runs")
    op.drop_index("idx_processing_jobs_expiry", table_name="processing_jobs")
