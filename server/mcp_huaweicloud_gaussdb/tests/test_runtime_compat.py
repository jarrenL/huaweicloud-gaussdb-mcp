"""Verify SDK deadlines, cancellation and retry boundaries without cloud calls."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from huaweicloud_mcp_core.errors import McpToolError

from mcp_huaweicloud_gaussdb.compat import runtime


async def test_transient_read_can_recover_on_third_attempt() -> None:
    attempts = 0

    def read() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise McpToolError("HTTP_503", "Service unavailable")
        return "done"

    assert await runtime.run_sdk_call(read, read_only=True) == "done"
    assert attempts == 3


@pytest.mark.parametrize(
    "cause, expected_code",
    [(ConnectionError(), "MCP_WRITE_RESULT_UNKNOWN"), (None, "HTTP_429")],
)
async def test_failed_write_never_retries(cause: Exception | None, expected_code: str) -> None:
    attempts = 0

    def write() -> None:
        nonlocal attempts
        attempts += 1
        code = "MCP_SDK_ERROR" if cause else "HTTP_429"
        raise McpToolError(code, "Write failed", request_id="request-1") from cause

    with pytest.raises(McpToolError) as error:
        await runtime.run_sdk_call(write)
    assert error.value.code == expected_code
    assert error.value.request_id == "request-1"
    assert attempts == 1


@pytest.mark.parametrize(
    "read_only, expected_code",
    [(False, "MCP_WRITE_RESULT_UNKNOWN"), (True, "MCP_TIMEOUT")],
)
async def test_deadline_holds_capacity_until_inflight_worker_exits(
    monkeypatch: pytest.MonkeyPatch, read_only: bool, expected_code: str
) -> None:
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    capacity = threading.BoundedSemaphore(1)
    monkeypatch.setattr(runtime, "_CAPACITY", capacity)

    def work() -> bool:
        loop.call_soon_threadsafe(entered.set)
        return release.wait(3)

    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(runtime, "_EXECUTOR", executor)
        waiting = asyncio.create_task(runtime.run_sdk_call(work, read_only=read_only, timeout=0.25))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            with pytest.raises(McpToolError) as timeout:
                await waiting
            assert timeout.value.code == expected_code
            with pytest.raises(McpToolError) as overloaded:
                await runtime.run_sdk_call(lambda: pytest.fail("Work admitted while at capacity"))
            assert overloaded.value.code == "MCP_BUSY"
        finally:
            release.set()

    assert capacity.acquire(blocking=False)
    capacity.release()


async def test_cancelled_queued_write_is_not_dispatched(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    writes = []

    def occupy() -> bool:
        loop.call_soon_threadsafe(entered.set)
        return release.wait(3)

    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(runtime, "_EXECUTOR", executor)
        first = asyncio.create_task(runtime.run_sdk_call(occupy))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            queued = asyncio.create_task(runtime.run_sdk_call(lambda: writes.append("dispatched")))
            await asyncio.sleep(0)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
        finally:
            release.set()
            await first
    assert not writes
