"""Tests for safe interactive MTProto session creation orchestration."""

import pytest

from app.listener.mtproto import TelegramAccount
from scripts.create_mtproto_session import create_session


class FakeSessionClient:
    def __init__(self, account: TelegramAccount) -> None:
        self.account = account
        self.calls: list[str] = []

    async def start(self) -> None:
        self.calls.append("start")

    async def get_account(self) -> TelegramAccount:
        self.calls.append("get_account")
        return self.account

    async def disconnect(self) -> None:
        self.calls.append("disconnect")


@pytest.mark.asyncio
async def test_session_script_validates_account_without_real_login() -> None:
    client = FakeSessionClient(TelegramAccount(user_id=42, display_name="Test User"))
    output: list[str] = []

    await create_session(client, output=output.append)

    assert client.calls == ["start", "get_account", "disconnect"]
    assert output == ["Telegram user ID: 42", "Display name: Test User"]


@pytest.mark.asyncio
async def test_session_script_disconnects_when_validation_fails() -> None:
    class FailingClient(FakeSessionClient):
        async def get_account(self) -> TelegramAccount:
            self.calls.append("get_account")
            raise RuntimeError("validation failed")

    client = FailingClient(TelegramAccount(user_id=42, display_name="Test User"))

    with pytest.raises(RuntimeError, match="validation failed"):
        await create_session(client)

    assert client.calls == ["start", "get_account", "disconnect"]
