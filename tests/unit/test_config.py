"""Tests for typed, service-specific application settings."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.config import AppSettings, ConfigurationError, ServiceName, load_settings


@pytest.fixture(autouse=True)
def isolate_settings_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for field_name in AppSettings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)


def test_settings_can_be_constructed_with_fake_credentials() -> None:
    settings = AppSettings(
        database_url=SecretStr("postgresql+asyncpg://test:test@localhost/test"),
        telegram_api_id=1,
        telegram_api_hash=SecretStr("fake-api-hash"),
    )

    assert settings.validate_for_service(ServiceName.TELEGRAM_LISTENER) is settings
    assert settings.telegram_session_path == Path("/sessions/work_account.session")
    assert settings.openai_classifier_model == "gpt-5.4-nano-2026-03-17"


@pytest.mark.parametrize(
    ("service", "expected_names"),
    (
        (
            ServiceName.TELEGRAM_LISTENER,
            ("DATABASE_URL", "TELEGRAM_API_ID", "TELEGRAM_API_HASH"),
        ),
        (
            ServiceName.MTPROTO_SESSION_CREATOR,
            ("TELEGRAM_API_ID", "TELEGRAM_API_HASH"),
        ),
        (
            ServiceName.CLASSIFICATION_WORKER,
            ("DATABASE_URL", "OPENAI_API_KEY", "OPERATOR_TELEGRAM_USER_ID"),
        ),
        (
            ServiceName.OPERATOR_BOT,
            ("DATABASE_URL", "OPERATOR_BOT_TOKEN", "OPERATOR_TELEGRAM_USER_ID"),
        ),
        (ServiceName.TRANSLATION_MANAGER, ("DATABASE_URL",)),
        (ServiceName.MAINTENANCE_WORKER, ("DATABASE_URL",)),
    ),
)
def test_missing_settings_are_reported_by_environment_name(
    service: ServiceName,
    expected_names: tuple[str, ...],
) -> None:
    settings = AppSettings()

    with pytest.raises(ConfigurationError) as captured:
        settings.validate_for_service(service)

    error = str(captured.value)
    assert service.value in error
    assert all(name in error for name in expected_names)


def test_secret_values_are_redacted_from_representations_and_errors() -> None:
    secret = "unique-secret-value"
    settings = AppSettings(
        database_url=SecretStr(secret),
        operator_bot_token=SecretStr(secret),
    )

    with pytest.raises(ConfigurationError) as captured:
        settings.validate_for_service(ServiceName.OPERATOR_BOT)

    assert secret not in repr(settings)
    assert secret not in settings.model_dump_json()
    assert secret not in str(captured.value)


def test_spec_comma_separated_languages_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRANSLATION_REQUIRED_LANGUAGES", "en, ru, de")
    settings = AppSettings()

    assert settings.translation_required_languages == ("en", "ru", "de")


def test_empty_optional_environment_values_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
    monkeypatch.setenv("TELEGRAM_API_ID", "")
    monkeypatch.setenv("OPERATOR_TELEGRAM_USER_ID", "")

    settings = AppSettings()

    assert settings.database_url is not None
    assert settings.telegram_api_id is None
    assert settings.operator_telegram_user_id is None


def test_invalid_environment_error_does_not_expose_other_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_secret = "database-secret"
    telegram_secret = "telegram-secret"
    monkeypatch.setenv("DATABASE_URL", database_secret)
    monkeypatch.setenv("TELEGRAM_API_HASH", telegram_secret)
    monkeypatch.setenv("TELEGRAM_API_ID", "not-an-integer")

    with pytest.raises(ConfigurationError) as captured:
        load_settings(ServiceName.TELEGRAM_LISTENER)

    error = str(captured.value)
    assert database_secret not in error
    assert telegram_secret not in error


def test_api_cost_thresholds_must_increase() -> None:
    with pytest.raises(ValidationError, match="info < warning < critical"):
        AppSettings(
            api_info_threshold_usd=Decimal("10"),
            api_warning_threshold_usd=Decimal("8"),
            api_critical_threshold_usd=Decimal("5"),
        )


def test_classifier_prices_are_environment_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_CLASSIFIER_INPUT_PRICE_PER_MILLION_USD", "0.33")
    monkeypatch.setenv("OPENAI_CLASSIFIER_OUTPUT_PRICE_PER_MILLION_USD", "2.75")

    settings = AppSettings()

    assert settings.openai_classifier_input_price_per_million_usd == Decimal("0.33")
    assert settings.openai_classifier_output_price_per_million_usd == Decimal("2.75")


def test_maintenance_schedule_is_environment_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAINTENANCE_INTERVAL_SECONDS", "12.5")
    monkeypatch.setenv("STALE_LOCK_TIMEOUT_SECONDS", "90")

    settings = AppSettings()

    assert settings.maintenance_interval_seconds == 12.5
    assert settings.stale_lock_timeout_seconds == 90


def test_feature_flags_have_safe_defaults() -> None:
    flags = AppSettings().feature_flags()

    assert flags.monitoring_enabled is True
    assert flags.notifications_enabled is True
    assert flags.translation_enabled is True
    assert flags.outbound_replies_enabled is False


@pytest.mark.parametrize(
    "name",
    (
        "MONITORING_ENABLED",
        "NOTIFICATIONS_ENABLED",
        "OUTBOUND_REPLIES_ENABLED",
        "TRANSLATION_ENABLED",
    ),
)
def test_feature_flags_validate_environment_values(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "not-a-boolean")

    with pytest.raises(ConfigurationError, match="Invalid application settings"):
        load_settings(ServiceName.MAINTENANCE_WORKER)
