"""Local filtering that passes only messages with explicit hiring intent."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from app.listener.events.fingerprint import URL_PATTERN
from app.listener.events.incoming import IncomingMessage


class FilterReasonCode(StrEnum):
    """Stable outcomes emitted by the local prefilter."""

    NO_TEXT = "NO_TEXT"
    OWN_MESSAGE = "OWN_MESSAGE"
    SERVICE_MESSAGE = "SERVICE_MESSAGE"
    STICKER_WITHOUT_CAPTION = "STICKER_WITHOUT_CAPTION"
    ONLY_EMOJI = "ONLY_EMOJI"
    BOT_COMMAND = "BOT_COMMAND"
    ONLY_URL = "ONLY_URL"
    KNOWN_GREETING = "KNOWN_GREETING"
    KNOWN_THANKS = "KNOWN_THANKS"
    NO_HIRING_INTENT = "NO_HIRING_INTENT"
    NO_STACK_FIT = "NO_STACK_FIT"
    PASS_TO_CLASSIFIER = "PASS_TO_CLASSIFIER"


@dataclass(frozen=True, slots=True)
class FilterResult:
    """Decision returned by the pure prefilter."""

    should_classify: bool
    reason_code: FilterReasonCode


_KNOWN_GREETINGS = frozenset(
    {
        "доброе утро",
        "добрый день",
        "добрый вечер",
        "здравствуйте",
        "привет",
        "hello",
        "hi",
    }
)
_KNOWN_THANKS = frozenset({"благодарю", "спасибо", "thank you", "thanks"})
_BOT_COMMAND = re.compile(r"^/[A-Za-z0-9_]+(?:@[A-Za-z0-9_]+)?$")
_EDGE_PUNCTUATION = " !.,?:;—–-…"


def _compile_stem_terms(*terms: str) -> re.Pattern[str]:
    """Compile Unicode-boundary terms whose word parts accept inflection suffixes."""
    patterns: list[str] = []
    for term in terms:
        parts = re.split(r"(\w+)", term)
        pattern = "".join(
            f"{re.escape(part)}\\w*" if part.isalnum() or part == "_" else re.escape(part)
            for part in parts
        )
        patterns.append(pattern.replace(r"\ ", r"\s+"))
    return re.compile(rf"\b(?:{'|'.join(patterns)})\b")


# Russian
_DEV_NOUN = _compile_stem_terms(
    "разработчик",
    "программист",
    "кодер",
    "прогер",
    "специалист",
    "исполнитель",
    "фрилансер",
    "верстальщик",
    "девелопер",
    # Ukrainian
    "розробник",
    "програміст",
    "спеціаліст",
    "виконавець",
    "фрілансер",
    "верстальник",
    # English
    "developer",
    "programmer",
    "coder",
    "engineer",
    "freelancer",
    "contractor",
    "dev",
)
_NEED_TOKEN = _compile_stem_terms(
    "нужен",
    "нужна",
    "нужно",
    "нужны",
    "требуется",
    "требуются",
    "ищу",
    "ищем",
    "разыскивается",
    # Ukrainian
    "потрібен",
    "потрібна",
    "потрібно",
    "потрібні",
    "шукаю",
    "шукаємо",
    "треба",
    "розшукується",
    # English
    "need",
    "needed",
    "looking for",
    "seeking",
    "searching for",
    "hiring",
    "want",
    "wanted",
)
_WHO_TOKEN = _compile_stem_terms(
    "кто",
    "хто",
    # English
    "who",
    "anyone",
    "can someone",
    "can anyone",
    "somebody who",
    "someone who",
)
_BUILD_VERB = _compile_stem_terms(
    "написать",
    "сделать",
    "разработать",
    "запилить",
    "собрать",
    "создать",
    "сверстать",
    "автоматизировать",
    "спарсить",
    "спроектировать",
    # Ukrainian
    "написати",
    "зробити",
    "розробити",
    "зібрати",
    "створити",
    "автоматизувати",
    # English
    "make",
    "build",
    "write",
    "develop",
    "create",
    "code",
    "automate",
    "parse",
    "scrape",
)
_WEAK_NEED = _compile_stem_terms(
    "надо",
    "нужно",
    "нужен",
    "требуется",
    # Ukrainian
    "треба",
    "потрібно",
    # English
    "need to",
    "want to",
    "gotta",
    "have to",
)
_DELIVERABLE = _compile_stem_terms(
    "сайт",
    "лендинг",
    "бот",
    "чат-бот",
    "приложени",
    "интеграц",
    "парсер",
    "скрипт",
    "автоматизац",
    "расширение",
    "плагин",
    "api",
    "интерфейс",
    # Ukrainian
    "додаток",
    "застосунок",
    "розширення",
    # English
    "website",
    "site",
    "landing",
    "bot",
    "chatbot",
    "app",
    "application",
    "integration",
    "parser",
    "scraper",
    "script",
    "extension",
    "plugin",
    "automation",
    "dashboard",
)
_STACK_TOKEN = _compile_stem_terms(
    # Russian
    "бот",
    "чат-бот",
    "телеграм-бот",
    "сайт",
    "лендинг",
    "парсер",
    "парсинг",
    "скрейпинг",
    "скрипт",
    "интеграц",
    "автоматизац",
    "api",
    "вебхук",
    "расширение",
    "плагин",
    "приложени",
    "crm",
    "нейросет",
    "искусственный интеллект",
    "машинное обучение",
    "gpt",
    "chatgpt",
    "ai",
    "llm",
    "дашборд",
    "выгрузк",
    "сбор данных",
    "гугл таблиц",
    # Ukrainian
    "додаток",
    "застосунок",
    "розширення",
    "парсер",
    "парсинг",
    "інтеграц",
    "автоматизац",
    "нейромереж",
    "штучний інтелект",
    # English
    "bot",
    "chatbot",
    "website",
    "site",
    "landing",
    "parser",
    "parsing",
    "scraper",
    "scraping",
    "web scraping",
    "script",
    "integration",
    "automation",
    "automate",
    "api",
    "webhook",
    "extension",
    "plugin",
    "app",
    "application",
    "crm",
    "dashboard",
    "ai",
    "llm",
    "gpt",
    "chatgpt",
    "machine learning",
    "neural",
    "data pipeline",
    "etl",
)
_ORDER_PAY = _compile_stem_terms(
    "закажу",
    "заказать разработку",
    "оплачу",
    "оплата",
    "готов оплатить",
    "за оплату",
    "за деньги",
    "сколько стоит сделать",
    "сколько будет стоить",
    # Ukrainian
    "замовлю",
    "замовити розробку",
    "готовий оплатити",
    "за оплату",
    "скільки коштує зробити",
    # English
    "hire",
    "for hire",
    "will pay",
    "ready to pay",
    "paid gig",
    "paid project",
    "how much to build",
    "how much would it cost",
    "quote",
)
_EXCLUSION = _compile_stem_terms(
    "ищу работу",
    "ищу подработку",
    "резюме",
    # Ukrainian
    "шукаю роботу",
    # English
    "looking for a job",
    "looking for work",
    "my resume",
    "cv",
    "vacancy",
    "вакансия",
    "вакансію",
)


def prefilter_message(message: IncomingMessage) -> FilterResult:
    """Reject local noise and requests outside the supported hiring scope."""
    if message.is_own:
        return _reject(FilterReasonCode.OWN_MESSAGE)
    if message.is_service:
        return _reject(FilterReasonCode.SERVICE_MESSAGE)

    text = message.text.strip() if message.text is not None else ""
    if not text:
        reason = (
            FilterReasonCode.STICKER_WITHOUT_CAPTION
            if message.has_sticker
            else FilterReasonCode.NO_TEXT
        )
        return _reject(reason)
    if _is_only_emoji(text):
        return _reject(FilterReasonCode.ONLY_EMOJI)
    if _BOT_COMMAND.fullmatch(text):
        return _reject(FilterReasonCode.BOT_COMMAND)
    if _is_only_urls(text):
        return _reject(FilterReasonCode.ONLY_URL)

    normalized = " ".join(text.casefold().strip(_EDGE_PUNCTUATION).split())
    if normalized in _KNOWN_GREETINGS:
        return _reject(FilterReasonCode.KNOWN_GREETING)
    if normalized in _KNOWN_THANKS:
        return _reject(FilterReasonCode.KNOWN_THANKS)

    text_casefolded = text.casefold()
    has_hiring_intent = (
        (_NEED_TOKEN.search(text_casefolded) and _DEV_NOUN.search(text_casefolded))
        or (_WHO_TOKEN.search(text_casefolded) and _BUILD_VERB.search(text_casefolded))
        or (
            _WEAK_NEED.search(text_casefolded)
            and _BUILD_VERB.search(text_casefolded)
            and _DELIVERABLE.search(text_casefolded)
        )
        or _ORDER_PAY.search(text_casefolded)
    )
    has_stack_fit = _STACK_TOKEN.search(text_casefolded)
    if _EXCLUSION.search(text_casefolded):
        return _reject(FilterReasonCode.NO_HIRING_INTENT)
    if not has_hiring_intent:
        return _reject(FilterReasonCode.NO_HIRING_INTENT)
    if not has_stack_fit:
        return _reject(FilterReasonCode.NO_STACK_FIT)
    return FilterResult(True, FilterReasonCode.PASS_TO_CLASSIFIER)


def _reject(reason_code: FilterReasonCode) -> FilterResult:
    return FilterResult(False, reason_code)


def _is_only_urls(text: str) -> bool:
    matches = list(URL_PATTERN.finditer(text))
    if not matches:
        return False
    remainder = URL_PATTERN.sub("", text)
    return not remainder.strip(" \t\r\n,;")


def _is_only_emoji(text: str) -> bool:
    visible = (character for character in text if not character.isspace())
    return all(
        unicodedata.category(character) in {"So", "Sk", "Mn"} or character in {"\u200d", "\ufe0f"}
        for character in visible
    )
