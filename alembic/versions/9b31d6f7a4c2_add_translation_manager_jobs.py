"""add translation manager jobs

Revision ID: 9b31d6f7a4c2
Revises: 4dc3c0a1e7b2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9b31d6f7a4c2"
down_revision: str | None = "4dc3c0a1e7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    action = sa.Enum(
        "install",
        "enable",
        "disable",
        "delete",
        "reload",
        "test",
        name="translation_manager_action",
    )
    status = sa.Enum(
        "pending", "processing", "succeeded", "failed", name="translation_manager_job_status"
    )
    op.create_table(
        "translation_manager_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("action", action, nullable=False),
        sa.Column("language_code", sa.String(length=10), nullable=True),
        sa.Column("status", status, server_default="pending", nullable=False),
        sa.Column("result_code", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_translation_manager_jobs")),
    )
    op.create_index(
        "idx_translation_manager_jobs_claim",
        "translation_manager_jobs",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("idx_translation_manager_jobs_claim", table_name="translation_manager_jobs")
    op.drop_table("translation_manager_jobs")
    sa.Enum(name="translation_manager_job_status").drop(op.get_bind())
    sa.Enum(name="translation_manager_action").drop(op.get_bind())
