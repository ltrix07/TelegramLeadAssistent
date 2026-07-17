"""Tests for the Telethon session adapter factory."""

from pathlib import Path
from typing import cast

import pytest
from pydantic import SecretStr
from telethon import TelegramClient, errors, types  # type: ignore[import-untyped]

from app.config import AppSettings
from app.domain.errors import TelegramErrorCode, TelegramFailureKind, TelegramOutboundError
from app.listener.mtproto.client import TelethonSessionClient, create_telethon_client


def test_factory_creates_session_parent_at_configured_path(tmp_path: Path) -> None:
    session_path = tmp_path / "private" / "work.session"
    settings = AppSettings(
        telegram_api_id=123,
        telegram_api_hash=SecretStr("fake-api-hash"),
        telegram_session_path=session_path,
    )

    client = create_telethon_client(settings)

    assert isinstance(client, TelethonSessionClient)
    assert session_path.parent.is_dir()
    assert session_path.is_file()


def test_session_volume_is_mounted_only_by_listener() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert compose.count("- mtproto_session:/sessions") == 1
    assert "target: runtime" in compose
    assert "install -d -o app -g app /sessions" in dockerfile


@pytest.mark.asyncio
async def test_adapter_rejects_session_when_get_me_returns_none() -> None:
    class FakeTelethonClient:
        async def get_me(self) -> None:
            return None

    adapter = TelethonSessionClient(cast(TelegramClient, FakeTelethonClient()))

    with pytest.raises(RuntimeError, match="session validation failed"):
        await adapter.get_account()


@pytest.mark.asyncio
async def test_send_reply_uses_exact_target_message() -> None:
    class FakeTelethonClient:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str, int]] = []

        async def send_message(self, chat_id: int, text: str, *, reply_to: int) -> types.Message:
            self.calls.append((chat_id, text, reply_to))
            return types.Message(id=404, peer_id=types.PeerChannel(123))

    client = FakeTelethonClient()
    adapter = TelethonSessionClient(cast(TelegramClient, client))

    sent_message_id = await adapter.send_reply(-100123, 77, "confirmed")

    assert sent_message_id == 404
    assert client.calls == [(-100123, "confirmed", 77)]


@pytest.mark.asyncio
async def test_edit_message_uses_exact_stored_sent_message_id() -> None:
    class FakeTelethonClient:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, str]] = []

        async def edit_message(self, chat_id: int, message_id: int, text: str) -> None:
            self.calls.append((chat_id, message_id, text))

    client = FakeTelethonClient()
    adapter = TelethonSessionClient(cast(TelegramClient, client))

    await adapter.edit_message(-100123, 404, "edited")

    assert client.calls == [(-100123, 404, "edited")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("telethon_error", "expected_code"),
    [
        (errors.MessageIdInvalidError(request=None), TelegramErrorCode.SOURCE_MESSAGE_DELETED),
        (errors.TopicDeletedError(request=None), TelegramErrorCode.TOPIC_DELETED),
        (errors.ChatWriteForbiddenError(request=None), TelegramErrorCode.CHAT_WRITE_FORBIDDEN),
        (errors.ChannelPrivateError(request=None), TelegramErrorCode.ACCESS_LOST),
    ],
)
async def test_send_reply_normalizes_permanent_telegram_errors(
    telethon_error: Exception, expected_code: TelegramErrorCode
) -> None:
    class FakeTelethonClient:
        async def send_message(self, chat_id: int, text: str, *, reply_to: int) -> None:
            raise telethon_error

    adapter = TelethonSessionClient(cast(TelegramClient, FakeTelethonClient()))

    with pytest.raises(TelegramOutboundError) as caught:
        await adapter.send_reply(-100123, 77, "confirmed")

    assert caught.value.code is expected_code
    assert caught.value.kind is TelegramFailureKind.PERMANENT


@pytest.mark.asyncio
async def test_send_reply_preserves_flood_wait_and_marks_network_result_ambiguous() -> None:
    class FakeTelethonClient:
        def __init__(self) -> None:
            self.error: Exception = errors.FloodWaitError(request=None, capture=37)

        async def send_message(self, chat_id: int, text: str, *, reply_to: int) -> None:
            raise self.error

    client = FakeTelethonClient()
    adapter = TelethonSessionClient(cast(TelegramClient, client))

    with pytest.raises(TelegramOutboundError) as flood:
        await adapter.send_reply(-100123, 77, "confirmed")
    assert flood.value.code is TelegramErrorCode.FLOOD_WAIT
    assert flood.value.kind is TelegramFailureKind.TEMPORARY
    assert flood.value.retry_after_seconds == 37

    client.error = TimeoutError()
    with pytest.raises(TelegramOutboundError) as ambiguous:
        await adapter.send_reply(-100123, 77, "confirmed")
    assert ambiguous.value.code is TelegramErrorCode.UNKNOWN_ERROR
    assert ambiguous.value.kind is TelegramFailureKind.AMBIGUOUS
