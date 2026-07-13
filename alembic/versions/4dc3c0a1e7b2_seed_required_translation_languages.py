"""Seed and protect required translation languages.

Revision ID: 4dc3c0a1e7b2
Revises: 8e3f5af41b2c
Create Date: 2026-07-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4dc3c0a1e7b2"
down_revision: str | None = "8e3f5af41b2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Seed base languages and prevent required rows from being weakened or deleted."""
    op.execute(
        """
        INSERT INTO translation_languages (
            language_code, display_name, is_required, is_enabled,
            installation_status, installed_at
        ) VALUES
            ('en', 'English', TRUE, TRUE, 'installed', NOW()),
            ('ru', 'Russian', TRUE, TRUE, 'installed', NOW())
        ON CONFLICT (language_code) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            is_required = TRUE,
            is_enabled = TRUE,
            installation_status = 'installed',
            installed_at = COALESCE(translation_languages.installed_at, NOW()),
            updated_at = NOW()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_required_translation_language() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.is_required THEN
                    RAISE EXCEPTION 'required translation language cannot be deleted';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.is_required AND (NOT NEW.is_required OR NOT NEW.is_enabled) THEN
                RAISE EXCEPTION 'required translation language cannot be disabled or demoted';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_protect_required_translation_language
        BEFORE UPDATE OR DELETE ON translation_languages
        FOR EACH ROW EXECUTE FUNCTION protect_required_translation_language()
        """
    )


def downgrade() -> None:
    """Remove protection and the M6-03 seed rows."""
    op.execute(
        "DROP TRIGGER IF EXISTS trg_protect_required_translation_language ON translation_languages"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_required_translation_language()")
    op.execute("DELETE FROM translation_languages WHERE language_code IN ('en', 'ru')")
