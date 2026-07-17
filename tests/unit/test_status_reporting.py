"""Tests for content-free operator status reporting."""

from decimal import Decimal

import httpx
import pytest

from app.bot.status import StatusSnapshot, TranslatorHealthProbe, render_status
from app.config import FeatureFlags


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "status_code", "expected"),
    [({"status": "ok"}, 200, True), ({"status": "error"}, 200, False), ({}, 503, False)],
)
async def test_translator_health_probe_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, str],
    status_code: int,
    expected: bool,
) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(status_code, json=payload))
    client = httpx.AsyncClient(transport=transport, base_url="http://translator")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: client)

    assert await TranslatorHealthProbe("http://translator", 1).healthy() is expected


def test_status_renderer_contains_only_operational_aggregates() -> None:
    rendered = render_status(
        StatusSnapshot(
            mtproto_healthy=False,
            classifier_healthy=True,
            translator_healthy=False,
            active_chats=2,
            pending_classification_jobs=3,
            pending_outbound_commands=1,
            outbound_needs_review=4,
            oldest_job_age_seconds=8.4,
            api_cost_month_usd=Decimal("2.845"),
        ),
        FeatureFlags(
            monitoring_enabled=True,
            notifications_enabled=False,
            outbound_replies_enabled=False,
            translation_enabled=True,
        ),
    )

    assert "MTProto: НЕДОСТУПЕН" in rendered
    assert "Classifier: работает" in rendered
    assert "Translator: НЕДОСТУПЕН" in rendered
    assert "Самая старая задача: 8 сек." in rendered
    assert "Расход API за месяц: $2.84" in rendered
    assert "Мониторинг: включён" in rendered
    assert "Уведомления: отключён" in rendered
    assert "Исходящие ответы: отключён" in rendered
    assert "message" not in rendered.lower()
    assert "prompt" not in rendered.lower()
