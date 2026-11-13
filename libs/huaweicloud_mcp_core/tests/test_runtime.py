"""Bounded retry and ambiguous-write failure tests, without network access."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from huaweicloud_mcp_core import McpToolError, runtime


class Transient(Exception):
    status_code = 503


async def test_read_retry_is_bounded_and_write_is_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("huaweicloud_mcp_core.runtime.time.sleep", lambda _: None)
    calls = 0

    def fail() -> Any:
        nonlocal calls
        calls += 1
        raise Transient()

    for read_only, expected in ((True, 3), (False, 1)):
        calls = 0
        with pytest.raises(Transient if read_only else McpToolError):
            await runtime.run_sdk_call(fail, read_only=read_only)
        assert calls == expected
    calls = 0

    def recover() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise Transient()
        return "ok"

    assert await runtime.run_sdk_call(recover, read_only=True) == "ok"
    assert calls == 2


@pytest.mark.parametrize(
    "read_only,code", [(False, "MCP_WRITE_RESULT_UNKNOWN"), (True, "MCP_TIMEOUT")]
)
async def test_timeout_keeps_capacity_until_worker_exits(
    monkeypatch: pytest.MonkeyPatch,
    read_only: bool,
    code: str,
) -> None:
    capacity = threading.BoundedSemaphore(1)
    monkeypatch.setattr(runtime, "_CAPACITY", capacity)
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()

    def slow() -> str:
        entered.set()
        try:
            release.wait(3)
            return "finished"
        finally:
            exited.set()

    try:
        with pytest.raises(McpToolError) as error:
            await runtime.run_sdk_call(slow, timeout=0.03, read_only=read_only)
        assert entered.is_set() and error.value.code == code
        with pytest.raises(McpToolError, match="capacity"):
            await runtime.run_sdk_call(lambda: "must not run")
    finally:
        release.set()
        await asyncio.to_thread(exited.wait, 2)
    for _ in range(20):
        if capacity.acquire(blocking=False):
            capacity.release()
            break
        await asyncio.sleep(0.01)
    assert await runtime.run_sdk_call(lambda: "ok") == "ok"


async def test_cancelled_call_does_not_cancel_accepted_worker() -> None:
    entered, release = threading.Event(), threading.Event()

    def work() -> bool:
        entered.set()
        return release.wait(2)

    task = asyncio.create_task(runtime.run_sdk_call(work))
    await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()


async def test_cancelled_queued_write_is_not_dispatched(monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release = threading.Event(), threading.Event()
    submitted: list[str] = []

    def occupy() -> bool:
        entered.set()
        return release.wait(3)

    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(runtime, "_EXECUTOR", executor)
        first = asyncio.create_task(runtime.run_sdk_call(occupy))
        try:
            await asyncio.to_thread(entered.wait, 1)
            queued = asyncio.create_task(runtime.run_sdk_call(lambda: submitted.append("write")))
            await asyncio.sleep(0)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
        finally:
            release.set()
            await first
    assert not submitted
