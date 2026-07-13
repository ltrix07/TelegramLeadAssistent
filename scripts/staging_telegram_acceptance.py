"""Fail-closed preflight for the manual staging Telegram acceptance suite."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass

from app.config import ServiceName, load_startup_settings
from app.listener.mtproto import ChatVerificationOutcome, create_telethon_client


class StagingAcceptanceError(RuntimeError):
    """Raised when the environment is not safe for live staging acceptance."""


@dataclass(frozen=True, slots=True)
class StagingAcceptanceSettings:
    """Explicit non-production identities required before any staging send."""

    account_id: int
    production_account_id: int
    forum_chat_id: int

    @classmethod
    def from_environment(cls) -> StagingAcceptanceSettings:
        if os.getenv("STAGING_TELEGRAM_ACCEPTANCE") != "I_UNDERSTAND_THIS_SENDS_MESSAGES":
            raise StagingAcceptanceError("Explicit staging acceptance opt-in is required")
        if os.getenv("APP_ENV") != "staging":
            raise StagingAcceptanceError("APP_ENV must be staging")
        if os.getenv("OUTBOUND_REPLIES_ENABLED", "").lower() != "true":
            raise StagingAcceptanceError("Outbound replies must be explicitly enabled")

        values: dict[str, int] = {}
        for name in (
            "STAGING_TELEGRAM_ACCOUNT_ID",
            "PRODUCTION_TELEGRAM_ACCOUNT_ID",
            "STAGING_TELEGRAM_FORUM_CHAT_ID",
        ):
            raw = os.getenv(name)
            try:
                values[name] = int(raw) if raw is not None else 0
            except ValueError as error:
                raise StagingAcceptanceError(f"{name} must be an integer") from error
            if values[name] == 0:
                raise StagingAcceptanceError(f"{name} is required and must be non-zero")

        if values["STAGING_TELEGRAM_ACCOUNT_ID"] == values["PRODUCTION_TELEGRAM_ACCOUNT_ID"]:
            raise StagingAcceptanceError("Staging and production Telegram accounts must differ")
        return cls(
            account_id=values["STAGING_TELEGRAM_ACCOUNT_ID"],
            production_account_id=values["PRODUCTION_TELEGRAM_ACCOUNT_ID"],
            forum_chat_id=values["STAGING_TELEGRAM_FORUM_CHAT_ID"],
        )


async def run_preflight(settings: StagingAcceptanceSettings) -> None:
    """Verify the authorized account and writable forum without mutating Telegram."""
    app_settings = load_startup_settings(ServiceName.TELEGRAM_LISTENER)
    client = create_telethon_client(app_settings)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise StagingAcceptanceError("MTProto staging session is not authorized")
        account = await client.get_account()
        if account.user_id != settings.account_id:
            raise StagingAcceptanceError("Authorized session does not match staging account")
        result = await client.verify_chat(settings.forum_chat_id)
        if result.outcome is not ChatVerificationOutcome.ACTIVE or not result.is_forum:
            raise StagingAcceptanceError("Staging chat must be a writable forum")
    finally:
        await client.disconnect()


def main() -> None:
    """Run the read-only staging safety preflight."""
    try:
        settings = StagingAcceptanceSettings.from_environment()
        asyncio.run(run_preflight(settings))
    except StagingAcceptanceError as error:
        print(f"Staging Telegram preflight blocked: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    print("Staging Telegram preflight passed; execute the documented scenarios manually.")


if __name__ == "__main__":
    main()
