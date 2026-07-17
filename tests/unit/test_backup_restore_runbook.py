"""Tests for the backup and restore runbook contract."""

from __future__ import annotations

from pathlib import Path

RUNBOOK = Path("docs/BACKUP_RESTORE.md")


def test_backup_restore_runbook_keeps_secrets_out_and_restores_separately() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")

    assert "--format=custom" in content
    assert "--cipher-algo AES256" in content
    assert "--passphrase-fd" in content
    assert "RESTORE_DB=app_restore_test" in content
    assert 'test "$RESTORE_DB" != "$ACTIVE_DB"' in content
    assert "--exit-on-error" in content
    assert "mtproto_session" in content
    assert "never add the\nsession file to this backup" in content


def test_backup_restore_runbook_states_retention_and_recovery_validation() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")

    assert "seven daily backups and four weekly backups" in content
    assert "at least once every 90 days" in content
    assert "at most 24 hours" in content
    assert "SELECT version_num FROM alembic_version" in content
    assert "OUTBOUND_REPLIES_ENABLED=false" in content
