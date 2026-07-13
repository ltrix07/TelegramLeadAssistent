"""Translation manager allow-list and control-plane tests."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import TranslationManagerAction
from app.translation.control import ArgosControlPlane
from app.translation.jobs import (
    FakeTranslationControlPlane,
    TranslationJobError,
    TranslationJobHandler,
    TranslationJobRequest,
)


@pytest.mark.asyncio
async def test_unknown_language_code_is_rejected_before_control_plane() -> None:
    control = FakeTranslationControlPlane()
    handler = TranslationJobHandler(control)

    with pytest.raises(TranslationJobError, match="unknown_language_code"):
        await handler.execute(
            TranslationJobRequest(TranslationManagerAction.INSTALL, "en; shutdown -h now"),
            AsyncMock(spec=AsyncSession),
        )

    assert control.calls == []


@pytest.mark.asyncio
async def test_reload_rejects_language_payload() -> None:
    control = FakeTranslationControlPlane()

    with pytest.raises(TranslationJobError, match="language_not_allowed_for_reload"):
        await TranslationJobHandler(control).execute(
            TranslationJobRequest(TranslationManagerAction.RELOAD, "ru"),
            AsyncMock(spec=AsyncSession),
        )


@pytest.mark.asyncio
async def test_reload_uses_only_configured_libretranslate_pid() -> None:
    plane = ArgosControlPlane(translation_base_url="http://translator", libretranslate_pid=41)

    with patch("app.translation.control.os.kill") as kill:
        await plane.reload()

    kill.assert_called_once()
    assert kill.call_args.args[0] == 41


@pytest.mark.asyncio
async def test_install_builds_fixed_argv_without_shell() -> None:
    calls: list[tuple[str, ...]] = []

    async def runner(argv: tuple[str, ...]) -> None:
        calls.append(argv)

    plane = ArgosControlPlane(translation_base_url="http://translator", runner=runner)
    await plane.install("pl")

    assert calls == [
        ("/app/.venv/bin/argospm", "update"),
        ("/app/.venv/bin/argospm", "install", "translate-pl_en"),
        ("/app/.venv/bin/argospm", "install", "translate-en_pl"),
    ]
