"""Operator bot service entry point."""

import asyncio

from app.bot.application import run_bot
from app.config import ServiceName, load_startup_settings
from app.database.session import create_session_factory
from app.logging import configure_logging


def main() -> None:
    """Start the operator bot service."""
    settings = load_startup_settings(ServiceName.OPERATOR_BOT)
    configure_logging(ServiceName.OPERATOR_BOT, settings)
    assert settings.operator_bot_token is not None
    assert settings.operator_telegram_user_id is not None
    assert settings.database_url is not None
    token = settings.operator_bot_token.get_secret_value()
    operator_user_id = settings.operator_telegram_user_id
    engine, session_factory = create_session_factory(settings.database_url.get_secret_value())

    async def run() -> None:
        try:
            await run_bot(
                token,
                operator_user_id,
                session_factory,
                settings,
            )
        finally:
            await engine.dispose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
