"""Persistence operations for local translation languages."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TranslationLanguage


@dataclass(frozen=True, slots=True)
class RequiredLanguage:
    """A language that must remain installed and enabled."""

    code: str
    display_name: str


REQUIRED_LANGUAGES = (
    RequiredLanguage(code="en", display_name="English"),
    RequiredLanguage(code="ru", display_name="Russian"),
)


class TranslationLanguageRepository:
    """Store and mutate language configuration within the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def seed_required(self) -> None:
        """Idempotently ensure all base languages are required, enabled, and installed."""
        for language in REQUIRED_LANGUAGES:
            await self._session.execute(
                insert(TranslationLanguage)
                .values(
                    language_code=language.code,
                    display_name=language.display_name,
                    is_required=True,
                    is_enabled=True,
                    installation_status="installed",
                    installed_at=func.now(),
                )
                .on_conflict_do_update(
                    index_elements=[TranslationLanguage.language_code],
                    set_={
                        "display_name": language.display_name,
                        "is_required": True,
                        "is_enabled": True,
                        "installation_status": "installed",
                        "installed_at": func.coalesce(TranslationLanguage.installed_at, func.now()),
                        "updated_at": func.now(),
                    },
                )
            )

    async def disable(self, language_code: str) -> bool:
        """Disable a non-required language, returning whether it changed."""
        changed = await self._session.scalar(
            update(TranslationLanguage)
            .where(
                TranslationLanguage.language_code == language_code,
                TranslationLanguage.is_required.is_(False),
                TranslationLanguage.is_enabled.is_(True),
            )
            .values(is_enabled=False, updated_at=func.now())
            .returning(TranslationLanguage.language_code)
        )
        return changed is not None

    async def enable(self, language_code: str) -> bool:
        """Enable an installed language, returning whether it changed."""
        changed = await self._session.scalar(
            update(TranslationLanguage)
            .where(
                TranslationLanguage.language_code == language_code,
                TranslationLanguage.installation_status == "installed",
                TranslationLanguage.is_enabled.is_(False),
            )
            .values(is_enabled=True, updated_at=func.now())
            .returning(TranslationLanguage.language_code)
        )
        return changed is not None

    async def mark_installing(self, language_code: str, display_name: str) -> None:
        """Create or transition a non-required language to installing."""
        await self._session.execute(
            insert(TranslationLanguage)
            .values(
                language_code=language_code,
                display_name=display_name,
                installation_status="installing",
            )
            .on_conflict_do_update(
                index_elements=[TranslationLanguage.language_code],
                set_={"installation_status": "installing", "updated_at": func.now()},
            )
        )

    async def mark_installed(self, language_code: str) -> None:
        """Persist a successful package installation and enable the language."""
        await self._session.execute(
            update(TranslationLanguage)
            .where(TranslationLanguage.language_code == language_code)
            .values(
                installation_status="installed",
                is_enabled=True,
                installed_at=func.now(),
                updated_at=func.now(),
            )
        )

    async def delete(self, language_code: str) -> bool:
        """Delete a non-required language, returning whether it existed."""
        removed = await self._session.scalar(
            delete(TranslationLanguage)
            .where(
                TranslationLanguage.language_code == language_code,
                TranslationLanguage.is_required.is_(False),
            )
            .returning(TranslationLanguage.language_code)
        )
        return removed is not None

    async def list_all(self) -> list[TranslationLanguage]:
        """List configured languages with required languages first."""
        rows = await self._session.scalars(
            select(TranslationLanguage).order_by(
                TranslationLanguage.is_required.desc(), TranslationLanguage.language_code
            )
        )
        return list(rows)
