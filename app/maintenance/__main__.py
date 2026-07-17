"""Maintenance service entry point."""

import asyncio
from datetime import timedelta

from app.bot.status import TranslatorHealthProbe
from app.config import ServiceName, load_startup_settings
from app.database.session import create_session_factory
from app.logging import configure_logging
from app.maintenance.scheduler import MaintenanceScheduler


async def _run() -> None:
    """Start the maintenance service."""
    settings = load_startup_settings(ServiceName.MAINTENANCE_WORKER)
    configure_logging(ServiceName.MAINTENANCE_WORKER, settings)
    assert settings.database_url is not None
    if settings.operator_telegram_user_id is None:
        raise SystemExit(
            "Configuration error: Missing settings for maintenance-worker: "
            "OPERATOR_TELEGRAM_USER_ID"
        )
    engine, session_factory = create_session_factory(settings.database_url.get_secret_value())
    scheduler = MaintenanceScheduler(
        session_factory,
        interval_seconds=settings.maintenance_interval_seconds,
        stale_lock_timeout=timedelta(seconds=settings.stale_lock_timeout_seconds),
        temporary_ttl=timedelta(hours=settings.temporary_message_ttl_hours),
        relevant_retention=timedelta(days=settings.message_retention_days),
        operator_user_id=settings.operator_telegram_user_id,
        translator_probe=TranslatorHealthProbe(
            settings.translation_base_url, settings.translation_request_timeout_seconds
        ),
        budget_thresholds=(
            settings.api_info_threshold_usd,
            settings.api_warning_threshold_usd,
            settings.api_critical_threshold_usd,
        ),
        mtproto_alert_after=timedelta(seconds=settings.mtproto_alert_after_seconds),
        queue_delay_alert_after=timedelta(seconds=settings.queue_delay_alert_after_seconds),
        translator_alert_after=timedelta(seconds=settings.translator_alert_after_seconds),
    )
    try:
        await scheduler.run_forever()
    finally:
        await engine.dispose()


def main() -> None:
    """Run the maintenance worker until shutdown."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
