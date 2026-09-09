"""Tests for network-free incoming message normalization and filtering."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from telethon import types  # type: ignore[import-untyped]

from app.listener.events import (
    FilterReasonCode,
    IncomingMessage,
    map_telethon_event,
    prefilter_message,
)
from app.listener.events.incoming import TelethonMessageEvent


def _incoming(text: str | None = "Нужна помощь с настройкой") -> IncomingMessage:
    return IncomingMessage(
        telegram_chat_id=-1001,
        telegram_message_id=42,
        topic_id=None,
        sender_telegram_id=7,
        sender_display_name="Test User",
        text=text,
        telegram_created_at=datetime(2026, 7, 12, tzinfo=UTC),
        is_own=False,
        is_service=False,
        has_sticker=False,
    )


def test_incoming_message_is_immutable() -> None:
    with pytest.raises(FrozenInstanceError):
        _incoming().text = "changed"  # type: ignore[misc]


def test_mapper_uses_only_cached_event_data() -> None:
    created_at = datetime(2026, 7, 12, 10, tzinfo=UTC)
    message = types.Message(
        id=12,
        peer_id=types.PeerChannel(1001),
        from_id=types.PeerUser(7),
        message="Hello",
        date=created_at,
        out=False,
    )
    message._sender = types.User(id=7, first_name="Test", last_name="User")
    event = SimpleNamespace(chat_id=-1001, message=message)

    result = map_telethon_event(cast(TelethonMessageEvent, event), topic_id=3)

    assert result == IncomingMessage(
        telegram_chat_id=-1001,
        telegram_message_id=12,
        topic_id=3,
        sender_telegram_id=7,
        sender_display_name="Test User",
        text="Hello",
        telegram_created_at=created_at,
        is_own=False,
        is_service=False,
        has_sticker=False,
    )


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        (replace(_incoming(), is_own=True), FilterReasonCode.OWN_MESSAGE),
        (replace(_incoming(), is_service=True), FilterReasonCode.SERVICE_MESSAGE),
        (_incoming(None), FilterReasonCode.NO_TEXT),
        (replace(_incoming(None), has_sticker=True), FilterReasonCode.STICKER_WITHOUT_CAPTION),
        (_incoming("👋🙂"), FilterReasonCode.ONLY_EMOJI),
        (_incoming("/start"), FilterReasonCode.BOT_COMMAND),
        (_incoming("https://example.com"), FilterReasonCode.ONLY_URL),
        (_incoming("Привет!"), FilterReasonCode.KNOWN_GREETING),
        (_incoming(" Спасибо. "), FilterReasonCode.KNOWN_THANKS),
    ],
)
def test_unambiguous_noise_is_rejected(message: IncomingMessage, reason: FilterReasonCode) -> None:
    result = prefilter_message(message)

    assert result.should_classify is False
    assert result.reason_code is reason


@pytest.mark.parametrize(
    "text",
    [
        "Нужна помощь с настройкой",
        "Привет, нужна помощь",
        "https://example.com не открывается",
        "/deploy production",
        "...",
        "Кто-нибудь сталкивался с блокировкой листинга? 😔",
        "Помогите разобраться с рекламой на Amazon 🙏🚀",
    ],
)
def test_ambiguous_text_without_hiring_intent_is_rejected(text: str) -> None:
    result = prefilter_message(_incoming(text))

    assert result.should_classify is False
    assert result.reason_code is FilterReasonCode.NO_HIRING_INTENT


@pytest.mark.parametrize(
    "text",
    [
        "Всем привет, нужен специалист, кто сделает расширение для браузера, за подробностями в лс",
        "Ищу разработчика для телеграм-бота, бюджет обсудим",
        "Кто может написать бота для парсинга?",
        "Потрібен програміст, хто зробить сайт для запису клієнтів",
        "Looking for a developer to build a Telegram bot, will pay",
        "🔥🔥 Нужен разработчик Telegram-бота 🤖 Оплата ✅",
    ],
)
def test_hiring_intent_passes_to_classifier(text: str) -> None:
    result = prefilter_message(_incoming(text))

    assert result.should_classify is True
    assert result.reason_code is FilterReasonCode.PASS_TO_CLASSIFIER


def test_weak_need_build_deliverable_branch_was_removed() -> None:
    """Was admitted only via the deleted `_WEAK_NEED + _BUILD_VERB + _DELIVERABLE`
    branch (2026-09-08 precision tightening): production measurement showed that
    branch admits 22 messages, 14 of them (64%) pure noise, and removing it loses
    zero wanted or low-value leads once counted against the other admitting rules.
    """
    text = "надо сделать сайт по типу призыва нет. и бота с анкетой НЕДОРОГО"

    result = prefilter_message(_incoming(text))

    assert result.should_classify is False
    assert result.reason_code is FilterReasonCode.NO_HIRING_INTENT


@pytest.mark.parametrize(
    "text",
    [
        "Нужен Java разработчик в офис на постоянку",
        "Looking for a mobile developer for our team",
    ],
)
def test_hiring_intent_without_stack_fit_is_rejected(text: str) -> None:
    result = prefilter_message(_incoming(text))

    assert result.should_classify is False
    assert result.reason_code is FilterReasonCode.NO_STACK_FIT


@pytest.mark.parametrize(
    "text",
    [
        "я пытаюсь из номенклатуры вытянуть картинку через rest api",
        "Ой блэт как это ещё автоматизировать",
        "Не получается запустить Cloudflare Tunnel через Podkop.",
        (
            "Посоветуйте ру хостера без тспу или же тспу с минимальным вмешательством "
            "как на клаудтрикс"
        ),
        "Сделай протокол vless",
        "Сравни конфиги Xray сперва, и на всякий случай проверь версию ядра",
        "is there anyway to convert walmart LMD_SAMEDAY tracking numbers using trackerbot?",
        (
            "eBay has put my payments on hold, as i was not giving the tracking. "
            "so now what is my way ahead?"
        ),
        "первий месяц спенд $377.93, второй $1,231.15, третий $2,245.09",
        "На 1420 норм ведёт себя тг ?",
        "Ищу работу разработчиком, готов на удалёнку",
    ],
)
def test_text_without_hiring_intent_is_rejected(text: str) -> None:
    result = prefilter_message(_incoming(text))

    assert result.should_classify is False
    assert result.reason_code is FilterReasonCode.NO_HIRING_INTENT


# --- Precision fixtures: 44 real production messages hand-labelled keep/drop. ---
# Source: 54 leads admitted by the gate since 2026-08-04, hand-labelled 21 wanted,
# 11 low-value-but-real, 22 pure noise. See docs/DECISIONS.md for the 2026-09-08
# gate-tightening decision this fixture backs.

_PRECISION_FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "prefilter_precision.json"
_PRECISION_FIXTURES = json.loads(_PRECISION_FIXTURE_PATH.read_text(encoding="utf-8"))

# Noise fixtures the tightened gate still cannot reject without risking a real lead.
# Each is a rule matching on vocabulary that also appears in genuine buyer messages,
# so no further tightening was attempted in this task. See final report for detail:
#   1  - "нужно" and a "разработчикам" stem co-occur in an unrelated sentence
#        (NEED_TOKEN + DEV_NOUN rule, out of scope for this task).
#   6  - "оплата" appears as an unrelated list item (ORDER_PAY rule, out of scope).
#   9  - peer pricing question for someone else's service; contains neither an
#        explanation marker nor a price marker, so WHO_TOKEN + BUILD_VERB still admits.
#   19 - DEV_NOUN's English "dev" stem over-matches the unrelated word "device".
#   28 - "нужно" and "программист" co-occur far apart in a long self-promotion post
#        (NEED_TOKEN + DEV_NOUN rule, out of scope for this task).
#   36 - "кто" and "автоматизировать" co-occur in unrelated sentences of a long essay;
#        WHO_TOKEN + BUILD_VERB has no proximity constraint (out of scope to add one).
#   46 - English spam matches WHO_TOKEN ("who") + BUILD_VERB ("make"); the explanation
#        markers added in this task are Russian-only, per the task's own examples.
_KNOWN_NOISE_LEAKS = frozenset({1, 6, 9, 19, 28, 36, 46})


def _fixture_id(fixture: dict[str, object]) -> str:
    return f"ref{fixture['ref']}-{fixture['expect']}"


@pytest.mark.parametrize(
    "fixture",
    [fx for fx in _PRECISION_FIXTURES if fx["expect"] == "keep"],
    ids=[_fixture_id(fx) for fx in _PRECISION_FIXTURES if fx["expect"] == "keep"],
)
def test_precision_fixtures_keep_every_real_lead(fixture: dict[str, object]) -> None:
    """No regression is acceptable here: losing a real lead outweighs noise."""
    result = prefilter_message(_incoming(cast(str, fixture["text"])))

    assert result.should_classify is True, (
        f"ref {fixture['ref']} ({fixture['note']}) must stay admitted, got {result.reason_code}"
    )


@pytest.mark.parametrize(
    "fixture",
    [fx for fx in _PRECISION_FIXTURES if fx["expect"] == "drop"],
    ids=[_fixture_id(fx) for fx in _PRECISION_FIXTURES if fx["expect"] == "drop"],
)
def test_precision_fixtures_reject_noise_where_the_gate_can(fixture: dict[str, object]) -> None:
    """Reject noise fixtures except the documented, still-leaking refs."""
    result = prefilter_message(_incoming(cast(str, fixture["text"])))
    ref = cast(int, fixture["ref"])

    if ref in _KNOWN_NOISE_LEAKS:
        assert result.should_classify is True, (
            f"ref {ref} was expected to still leak through; if this now fails, "
            "the gate got stricter and _KNOWN_NOISE_LEAKS should shrink"
        )
    else:
        assert result.should_classify is False, (
            f"ref {ref} ({fixture['note']}) should now be rejected, got {result.reason_code}"
        )


def test_who_build_admits_a_genuine_buyer() -> None:
    result = prefilter_message(_incoming("Кто может сделать бота для продаж"))

    assert result.should_classify is True
    assert result.reason_code is FilterReasonCode.PASS_TO_CLASSIFIER


def test_who_build_rejects_a_peer_seeking_an_explanation() -> None:
    result = prefilter_message(_incoming("Как сделать бота кто может рассказать?"))

    assert result.should_classify is False
    assert result.reason_code is FilterReasonCode.NO_HIRING_INTENT


def test_price_enquiry_is_kept_despite_containing_podskazhite() -> None:
    result = prefilter_message(_incoming("Подскажите, сколько будет стоить сделать бота"))

    assert result.should_classify is True
    assert result.reason_code is FilterReasonCode.PASS_TO_CLASSIFIER


def test_price_marker_wins_over_explanation_marker_in_who_build_rule() -> None:
    text = "нужно объяснить, кто может сделать бота, сколько будет стоить"

    result = prefilter_message(_incoming(text))

    assert result.should_classify is True
    assert result.reason_code is FilterReasonCode.PASS_TO_CLASSIFIER


@pytest.mark.parametrize(
    "text",
    [
        "🤖 TELEGRAM-БОТ ДЛЯ ВАШЕГО БИЗНЕСА — ОТ 3 000 р Клиенты постоянно задают одни "
        "и те же вопросы? Я создаю простых и удобных Telegram-ботов.",
        "Наша студия делает сайты под ключ, цена от 15000р, пишите в лс",
        "Прайс на разработку ботов внутри, пишите в лс, сделаем быстро",
    ],
)
def test_service_advertisement_is_rejected(text: str) -> None:
    result = prefilter_message(_incoming(text))

    assert result.should_classify is False
    assert result.reason_code is FilterReasonCode.ADVERTISEMENT


def test_service_ad_price_pattern_does_not_reject_a_buyers_budget() -> None:
    text = "Ищу человека который сможет написать сайт, бюджет от 2000-2500₽ кто сможет напишите"

    result = prefilter_message(_incoming(text))

    assert result.should_classify is True
    assert result.reason_code is FilterReasonCode.PASS_TO_CLASSIFIER


@pytest.mark.parametrize(
    "text",
    [
        # A "от N р" price shape alone must never read as an ad: buyers phrase their
        # own budget the same way. Regression for the 2026-09-08 fix — these two are
        # real leads that the "бюджет"-only substring escape wrongly rejected.
        "Ищу разработчика для телеграм бота, оплата от 5000р, пишите в лс",
        "Нужен программист на сайт, готов платить от 20 000 руб за работу",
        # The currency symbol sits at the very end of the string here: the previous
        # trailing `\b` cannot match right after a non-word character like "₽" at
        # end of string, so this exact shape used to slip past the ad check by
        # accident depending on the currency spelling. Assert it stays admitted now
        # that the price-offer pattern no longer decides ad status on its own.
        "Ищу кодера сделать бота. Оплата от 10000 ₽",
    ],
)
def test_buyer_price_offer_is_never_read_as_an_advertisement_on_its_own(text: str) -> None:
    result = prefilter_message(_incoming(text))

    assert result.should_classify is True
    assert result.reason_code is FilterReasonCode.PASS_TO_CLASSIFIER


def test_price_offer_combined_with_a_genuine_offer_signal_is_still_an_advertisement() -> None:
    """The price-offer regex's trailing-boundary fix must still catch a real ad
    whose currency symbol sits at the end of the string, once it co-occurs with a
    genuine offer-side signal (here: "Разработаем")."""
    text = "Разработаем бота для вас, оплата от 5000₽"

    result = prefilter_message(_incoming(text))

    assert result.should_classify is False
    assert result.reason_code is FilterReasonCode.ADVERTISEMENT
