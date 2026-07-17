"""Generate a content-free stability report for one shadow-mode window."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from app.config import AppSettings, ConfigurationError
from app.database.session import create_session_factory
from app.rollout.shadow import ShadowReportRepository, render_shadow_report


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", type=int, required=True)
    parser.add_argument("--started-at", type=_timestamp, required=True)
    parser.add_argument("--ended-at", type=_timestamp, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> str:
    settings = AppSettings()
    if settings.database_url is None:
        raise ConfigurationError("DATABASE_URL is required")
    engine, factory = create_session_factory(settings.database_url.get_secret_value())
    try:
        async with factory() as session:
            report = await ShadowReportRepository(session).collect(
                chat_id=arguments.chat_id,
                started_at=arguments.started_at,
                ended_at=arguments.ended_at,
                flags=settings.feature_flags(),
            )
        return render_shadow_report(report)
    finally:
        await engine.dispose()


def main() -> None:
    arguments = _arguments()
    report = asyncio.run(_run(arguments))
    if arguments.output is None:
        print(report)
        return
    arguments.output.write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
