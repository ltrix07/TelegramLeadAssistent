"""Tests for the listener's fail-closed active-chat allow-list."""

from __future__ import annotations

import asyncio

import pytest

from app.listener.active_chats import ActiveChatAllowList, run_active_chat_allow_list


@pytest.mark.asyncio
async def test_inactive_chat_is_not_allowed_after_startup_load() -> None:
    async def load() -> frozenset[int]:
        return frozenset({-1001})

    allow_list = ActiveChatAllowList(load)

    assert -1001 not in allow_list
    assert await allow_list.refresh() is True
    assert -1001 in allow_list
    assert -1002 not in allow_list


@pytest.mark.asyncio
async def test_refresh_reflects_paused_chat_without_restart() -> None:
    snapshots = iter((frozenset({-1001, -1002}), frozenset({-1002})))

    async def load() -> frozenset[int]:
        return next(snapshots)

    allow_list = ActiveChatAllowList(load)

    await allow_list.refresh()
    assert -1001 in allow_list
    await allow_list.refresh()
    assert -1001 not in allow_list


@pytest.mark.asyncio
async def test_refresh_failure_retains_last_safe_snapshot() -> None:
    calls = 0

    async def load() -> frozenset[int]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("database unavailable")
        return frozenset({-1001})

    allow_list = ActiveChatAllowList(load)

    assert await allow_list.refresh() is True
    assert await allow_list.refresh() is False
    assert allow_list.chat_ids == frozenset({-1001})


@pytest.mark.asyncio
async def test_periodic_runner_loads_at_startup_and_refreshes_again() -> None:
    stop_event = asyncio.Event()
    loads = 0

    async def load() -> frozenset[int]:
        nonlocal loads
        loads += 1
        return frozenset()

    async def sleep(_: float) -> None:
        if loads == 2:
            stop_event.set()

    await run_active_chat_allow_list(
        ActiveChatAllowList(load), stop_event, interval_seconds=60, sleep=sleep
    )

    assert loads == 2
