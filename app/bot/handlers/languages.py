"""Operator UI for local translation languages."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards.languages import (
    build_language_actions_keyboard,
    build_language_confirmation_keyboard,
)
from app.database.models import TranslationLanguage, TranslationManagerJob
from app.database.repositories.translation_languages import TranslationLanguageRepository
from app.database.repositories.translation_manager_jobs import TranslationManagerJobRepository
from app.domain.enums import TranslationManagerAction, TranslationManagerJobStatus
from app.translation.jobs import LANGUAGE_ALLOWLIST, REQUIRED_LANGUAGE_CODES

router = Router(name="translation-languages")

_STATUS_LABELS = {
    "not_installed": "доступен",
    "installing": "устанавливается",
    "installed": "установлен",
    "failed": "ошибка",
}


def _latest_jobs_by_language(
    jobs: list[TranslationManagerJob],
) -> dict[str, TranslationManagerJob]:
    result: dict[str, TranslationManagerJob] = {}
    for job in jobs:
        if job.language_code is not None:
            result.setdefault(job.language_code, job)
    return result


def _effective_status(
    language: TranslationLanguage | None, job: TranslationManagerJob | None
) -> str:
    if job is not None and job.status in {
        TranslationManagerJobStatus.PENDING,
        TranslationManagerJobStatus.PROCESSING,
    }:
        return "installing" if job.action is TranslationManagerAction.INSTALL else "processing"
    if job is not None and job.status is TranslationManagerJobStatus.FAILED:
        return "failed"
    return language.installation_status if language is not None else "not_installed"


def _format_language(
    code: str, name: str, language: TranslationLanguage | None, job: TranslationManagerJob | None
) -> str:
    status = _effective_status(language, job)
    status_label = _STATUS_LABELS.get(status, "изменяется")
    enabled = language is not None and language.is_enabled
    suffix = " · обязателен" if code in REQUIRED_LANGUAGE_CODES else ""
    if status == "installed":
        suffix += " · активен" if enabled else " · отключён"
    return f"{name} ({code})\nСостояние: {status_label}{suffix}"


async def _show_languages(
    message: Message, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        languages = await TranslationLanguageRepository(session).list_all()
        jobs = await TranslationManagerJobRepository(session).list_recent()
    configured = {language.language_code: language for language in languages}
    latest_jobs = _latest_jobs_by_language(jobs)
    busy = any(
        job.status in {TranslationManagerJobStatus.PENDING, TranslationManagerJobStatus.PROCESSING}
        for job in jobs
    )
    await message.answer(f"Переводчик: {'выполняет изменение' if busy else 'готов'}")
    for code, name in LANGUAGE_ALLOWLIST.items():
        language = configured.get(code)
        keyboard = build_language_actions_keyboard(
            language_code=code,
            is_required=code in REQUIRED_LANGUAGE_CODES,
            is_enabled=language.is_enabled if language is not None else False,
            is_installed=(language is not None and language.installation_status == "installed"),
        )
        await message.answer(
            _format_language(code, name, language, latest_jobs.get(code)), reply_markup=keyboard
        )


@router.message(F.text == "Перевод")
async def show_languages(
    message: Message, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """List required, installed, and available translation languages."""
    await _show_languages(message, session_factory)


@router.callback_query(F.data.startswith("lang:"))
async def manage_language(
    callback: CallbackQuery, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Confirm destructive actions or enqueue one typed manager job."""
    if callback.data is None:
        return
    try:
        _, raw_action, code = callback.data.split(":", maxsplit=2)
    except ValueError:
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    if code not in LANGUAGE_ALLOWLIST:
        await callback.answer("Неизвестный язык.", show_alert=True)
        return
    if raw_action == "cancel":
        await callback.answer("Действие отменено.")
        if isinstance(callback.message, Message):
            await callback.message.delete()
        return
    if raw_action in {"confirm_install", "confirm_delete"}:
        action = (
            TranslationManagerAction.INSTALL
            if raw_action == "confirm_install"
            else TranslationManagerAction.DELETE
        )
        if code in REQUIRED_LANGUAGE_CODES:
            await callback.answer("Обязательный язык нельзя изменить.", show_alert=True)
            return
        warning = (
            "Потребуется установить переводческие пакеты."
            if action is TranslationManagerAction.INSTALL
            else "Переводческая модель будет удалена."
        )
        if isinstance(callback.message, Message):
            await callback.message.answer(
                f"Язык: {LANGUAGE_ALLOWLIST[code]}\n{warning}\n"
                "Во время перезапуска перевод может быть временно недоступен.",
                reply_markup=build_language_confirmation_keyboard(action, code),
            )
        await callback.answer()
        return
    try:
        action = TranslationManagerAction(raw_action)
    except ValueError:
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    if code in REQUIRED_LANGUAGE_CODES and action in {
        TranslationManagerAction.INSTALL,
        TranslationManagerAction.DISABLE,
        TranslationManagerAction.DELETE,
    }:
        await callback.answer("Обязательный язык нельзя изменить.", show_alert=True)
        return
    async with session_factory.begin() as session:
        await TranslationManagerJobRepository(session).enqueue(action, code)
    await callback.answer("Действие поставлено в очередь.")
    if isinstance(callback.message, Message):
        await callback.message.delete()
