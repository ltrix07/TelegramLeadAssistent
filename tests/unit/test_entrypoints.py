"""Tests for the initial package and service entry points."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import app

ENTRYPOINT_ENV = {
    "app.listener": {
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
        "TELEGRAM_API_ID": "1",
        "TELEGRAM_API_HASH": "fake-api-hash",
    },
    "app.classifier.worker": {
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
        "OPENAI_API_KEY": "fake-openai-key",
    },
    "app.bot": {
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
        "OPERATOR_BOT_TOKEN": "fake-bot-token",
        "OPERATOR_TELEGRAM_USER_ID": "1",
    },
    "app.translation.manager": {
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    },
    "app.maintenance": {
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
    },
}


def test_app_package_imports() -> None:
    assert app.__doc__


def test_maintenance_entrypoint_is_importable() -> None:
    module = importlib.import_module("app.maintenance.__main__")

    assert callable(module.main)


def test_entrypoint_fails_before_start_when_required_settings_are_missing(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-m", "app.classifier.worker"],
        check=False,
        capture_output=True,
        cwd=tmp_path,
        env={"PYTHONPATH": str(project_root)},
        text=True,
        timeout=5,
    )

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "Configuration error:" in result.stderr
    assert "DATABASE_URL" in result.stderr
    assert "OPENAI_API_KEY" in result.stderr
