"""Typed application configuration shared by all services."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Literal, Self

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError


class ServiceName(StrEnum):
    """Independently launched application services."""

    TELEGRAM_LISTENER = "telegram-listener"
    MTPROTO_SESSION_CREATOR = "mtproto-session-creator"
    CLASSIFICATION_WORKER = "classification-worker"
    OPERATOR_BOT = "operator-bot"
    TRANSLATION_MANAGER = "translation-manager"
    MAINTENANCE_WORKER = "maintenance-worker"


class ConfigurationError(ValueError):
    """Raised when a service lacks required configuration."""


class AppSettings(BaseSettings):
    """Environment-backed settings for all application services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    app_env: str = "production"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    database_url: SecretStr | None = None

    telegram_api_id: int | None = Field(default=None, gt=0)
    telegram_api_hash: SecretStr | None = None
    telegram_session_path: Path = Path("/sessions/work_account.session")

    operator_bot_token: SecretStr | None = None
    operator_telegram_user_id: int | None = Field(default=None, gt=0)

    openai_api_key: SecretStr | None = None
    openai_classifier_model: str = "gpt-5.4-nano-2026-03-17"
    openai_classifier_input_price_per_million_usd: Decimal = Field(default=Decimal("0.20"), ge=0)
    openai_classifier_output_price_per_million_usd: Decimal = Field(default=Decimal("1.25"), ge=0)

    classification_workers: int = Field(default=1, gt=0)
    classification_max_attempts: int = Field(default=4, gt=0)
    classification_request_timeout_seconds: int = Field(default=30, gt=0)

    translation_enabled: bool = True
    outbound_replies_enabled: bool = False
    translation_base_url: str = "http://libretranslate:5000"
    translation_request_timeout_seconds: float = Field(default=10, gt=0)
    translation_required_languages: Annotated[tuple[str, ...], NoDecode] = ("en", "ru")

    message_retention_days: int = Field(default=60, gt=0)
    temporary_message_ttl_hours: int = Field(default=24, gt=0)
    technical_log_retention_days: int = Field(default=30, gt=0)

    maintenance_interval_seconds: float = Field(default=30, gt=0)
    stale_lock_timeout_seconds: int = Field(default=300, gt=0)

    api_info_threshold_usd: Decimal = Field(default=Decimal("5"), ge=0)
    api_warning_threshold_usd: Decimal = Field(default=Decimal("8"), ge=0)
    api_critical_threshold_usd: Decimal = Field(default=Decimal("10"), ge=0)
    mtproto_alert_after_seconds: int = Field(default=300, gt=0)
    queue_delay_alert_after_seconds: int = Field(default=600, gt=0)
    translator_alert_after_seconds: int = Field(default=900, gt=0)

    _required_fields: ClassVar[dict[ServiceName, tuple[tuple[str, str], ...]]] = {
        ServiceName.TELEGRAM_LISTENER: (
            ("database_url", "DATABASE_URL"),
            ("telegram_api_id", "TELEGRAM_API_ID"),
            ("telegram_api_hash", "TELEGRAM_API_HASH"),
        ),
        ServiceName.MTPROTO_SESSION_CREATOR: (
            ("telegram_api_id", "TELEGRAM_API_ID"),
            ("telegram_api_hash", "TELEGRAM_API_HASH"),
        ),
        ServiceName.CLASSIFICATION_WORKER: (
            ("database_url", "DATABASE_URL"),
            ("openai_api_key", "OPENAI_API_KEY"),
            ("operator_telegram_user_id", "OPERATOR_TELEGRAM_USER_ID"),
        ),
        ServiceName.OPERATOR_BOT: (
            ("database_url", "DATABASE_URL"),
            ("operator_bot_token", "OPERATOR_BOT_TOKEN"),
            ("operator_telegram_user_id", "OPERATOR_TELEGRAM_USER_ID"),
        ),
        ServiceName.TRANSLATION_MANAGER: (("database_url", "DATABASE_URL"),),
        ServiceName.MAINTENANCE_WORKER: (("database_url", "DATABASE_URL"),),
    }

    @field_validator("translation_required_languages", mode="before")
    @classmethod
    def parse_required_languages(cls, value: object) -> object:
        """Parse the comma-separated environment representation from SPEC."""
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @model_validator(mode="after")
    def validate_threshold_order(self) -> Self:
        """Require API budget notification thresholds to increase."""
        if not (
            self.api_info_threshold_usd
            < self.api_warning_threshold_usd
            < self.api_critical_threshold_usd
        ):
            raise ValueError("API cost thresholds must satisfy info < warning < critical")
        return self

    def validate_for_service(self, service: ServiceName) -> Self:
        """Ensure all values needed by one service are present."""
        missing = [
            env_name
            for field_name, env_name in self._required_fields[service]
            if getattr(self, field_name) is None
        ]
        if missing:
            names = ", ".join(missing)
            raise ConfigurationError(f"Missing settings for {service.value}: {names}")
        return self


def load_settings(service: ServiceName) -> AppSettings:
    """Load environment settings and validate them for one service."""
    try:
        settings = AppSettings()
    except (SettingsError, ValidationError):
        raise ConfigurationError(
            "Invalid application settings; check environment value types"
        ) from None
    return settings.validate_for_service(service)


def load_startup_settings(service: ServiceName) -> AppSettings:
    """Load service settings or terminate startup with a safe message."""
    try:
        return load_settings(service)
    except ConfigurationError as error:
        raise SystemExit(f"Configuration error: {error}") from None
