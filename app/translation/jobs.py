"""Allow-listed translation manager job workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.translation_languages import TranslationLanguageRepository
from app.domain.enums import TranslationManagerAction

LANGUAGE_ALLOWLIST: dict[str, str] = {
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "pl": "Polish",
    "ru": "Russian",
    "uk": "Ukrainian",
}
REQUIRED_LANGUAGE_CODES = frozenset({"en", "ru"})


class TranslationControlPlane(Protocol):
    """Narrow boundary implemented inside the translation-manager container."""

    async def install(self, language_code: str) -> None: ...
    async def delete(self, language_code: str) -> None: ...
    async def reload(self) -> None: ...
    async def test(self, language_code: str) -> None: ...


@dataclass(frozen=True, slots=True)
class TranslationJobRequest:
    """Validated data accepted from the future operator UI."""

    action: TranslationManagerAction
    language_code: str | None = None


class TranslationJobError(RuntimeError):
    """Safe job rejection or control-plane failure."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = False


class TranslationJobHandler:
    """Execute one typed manager request without accepting command fragments."""

    def __init__(self, control_plane: TranslationControlPlane) -> None:
        self._control_plane = control_plane

    async def execute(self, request: TranslationJobRequest, session: AsyncSession) -> None:
        code = request.language_code.lower() if request.language_code else None
        if request.action is TranslationManagerAction.RELOAD:
            if code is not None:
                raise TranslationJobError("language_not_allowed_for_reload")
            await self._control_plane.reload()
            return
        if code is None or code not in LANGUAGE_ALLOWLIST:
            raise TranslationJobError("unknown_language_code")
        if code in REQUIRED_LANGUAGE_CODES and request.action in {
            TranslationManagerAction.INSTALL,
            TranslationManagerAction.DISABLE,
            TranslationManagerAction.DELETE,
        }:
            raise TranslationJobError("required_language_is_immutable")

        repository = TranslationLanguageRepository(session)
        if request.action is TranslationManagerAction.INSTALL:
            await repository.mark_installing(code, LANGUAGE_ALLOWLIST[code])
            await session.flush()
            await self._control_plane.install(code)
            await repository.mark_installed(code)
            await self._control_plane.reload()
        elif request.action is TranslationManagerAction.ENABLE:
            if not await repository.enable(code):
                raise TranslationJobError("language_not_installed_or_already_enabled")
            await self._control_plane.reload()
        elif request.action is TranslationManagerAction.DISABLE:
            if not await repository.disable(code):
                raise TranslationJobError("required_or_already_disabled")
            await self._control_plane.reload()
        elif request.action is TranslationManagerAction.DELETE:
            if not await repository.delete(code):
                raise TranslationJobError("required_or_unknown_language")
            await self._control_plane.delete(code)
            await self._control_plane.reload()
        elif request.action is TranslationManagerAction.TEST:
            await self._control_plane.test(code)
        else:
            raise TranslationJobError("unknown_action")


class FakeTranslationControlPlane:
    """Deterministic fake that records typed operations only."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def install(self, language_code: str) -> None:
        self.calls.append(("install", language_code))

    async def delete(self, language_code: str) -> None:
        self.calls.append(("delete", language_code))

    async def reload(self) -> None:
        self.calls.append(("reload", None))

    async def test(self, language_code: str) -> None:
        self.calls.append(("test", language_code))
