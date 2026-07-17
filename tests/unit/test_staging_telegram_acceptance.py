"""Safety contract for the live staging Telegram acceptance preflight."""

from pathlib import Path

import pytest

from scripts.staging_telegram_acceptance import (
    PRODUCTION_ACCOUNT_OPT_IN,
    StagingAcceptanceError,
    StagingAcceptanceSettings,
)


def test_preflight_runs_inside_the_session_owning_listener_container() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "docker compose run --rm" in makefile
    for name in (
        "STAGING_TELEGRAM_ACCEPTANCE",
        "STAGING_TELEGRAM_ACCOUNT_ID",
        "PRODUCTION_TELEGRAM_ACCOUNT_ID",
        "STAGING_TELEGRAM_FORUM_CHAT_ID",
    ):
        assert f"-e {name}" in makefile
    assert "telegram-listener" in makefile
    assert "python -m scripts.staging_telegram_acceptance" in makefile
    assert "OUTBOUND_REPLIES_ENABLED: ${OUTBOUND_REPLIES_ENABLED:-false}" in compose


def _set_safe_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STAGING_TELEGRAM_ACCEPTANCE", "I_UNDERSTAND_THIS_SENDS_MESSAGES")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("OUTBOUND_REPLIES_ENABLED", "true")
    monkeypatch.setenv("STAGING_TELEGRAM_ACCOUNT_ID", "101")
    monkeypatch.setenv("PRODUCTION_TELEGRAM_ACCOUNT_ID", "202")
    monkeypatch.setenv("STAGING_TELEGRAM_FORUM_CHAT_ID", "-100303")


def test_preflight_settings_accept_explicit_non_production_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_environment(monkeypatch)

    settings = StagingAcceptanceSettings.from_environment()

    assert settings.account_id == 101
    assert settings.production_account_id == 202
    assert settings.forum_chat_id == -100303


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("STAGING_TELEGRAM_ACCEPTANCE", ""),
        ("APP_ENV", "production"),
        ("OUTBOUND_REPLIES_ENABLED", "false"),
        ("STAGING_TELEGRAM_FORUM_CHAT_ID", "0"),
    ],
)
def test_preflight_settings_fail_closed(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    _set_safe_environment(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(StagingAcceptanceError):
        StagingAcceptanceSettings.from_environment()


def test_preflight_rejects_production_account_without_stronger_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_environment(monkeypatch)
    monkeypatch.setenv("PRODUCTION_TELEGRAM_ACCOUNT_ID", "101")

    with pytest.raises(StagingAcceptanceError, match="production-account opt-in"):
        StagingAcceptanceSettings.from_environment()


def test_preflight_accepts_production_account_with_stronger_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_safe_environment(monkeypatch)
    monkeypatch.setenv("PRODUCTION_TELEGRAM_ACCOUNT_ID", "101")
    monkeypatch.setenv("STAGING_TELEGRAM_ACCEPTANCE", PRODUCTION_ACCOUNT_OPT_IN)

    settings = StagingAcceptanceSettings.from_environment()

    assert settings.account_id == settings.production_account_id == 101
