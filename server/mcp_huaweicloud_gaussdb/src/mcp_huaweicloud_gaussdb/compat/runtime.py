# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Bounded GaussDB SDK execution on the official shared core."""

from __future__ import annotations

import asyncio
import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from huaweicloud_mcp_core.errors import McpToolError

T = TypeVar("T")
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mcp-sdk")
_CAPACITY = threading.BoundedSemaphore(16)
_RETRY_STATUSES = {429, 502, 503, 504}
_AMBIGUOUS_STATUSES = {502, 503, 504}
_AMBIGUOUS_EXCEPTION_NAMES = {
    "ConnectionException",
    "ReadTimeout",
    "ConnectTimeout",
    "CallTimeoutException",
    "RequestTimeoutException",
    "HostUnreachableException",
}


def _status(exc: BaseException) -> int | None:
    for error in (exc, exc.__cause__):
        value = getattr(error, "status_code", None)
        if isinstance(value, int):
            return value
        code = getattr(error, "code", "")
        if isinstance(code, str) and code.startswith("HTTP_") and code[5:].isdigit():
            return int(code[5:])
    return None


def _is_ambiguous(exc: Exception) -> bool:
    return _status(exc) in _AMBIGUOUS_STATUSES or any(
        isinstance(error, (TimeoutError, ConnectionError))
        or type(error).__name__ in _AMBIGUOUS_EXCEPTION_NAMES
        for error in (exc, exc.__cause__)
    )


def _invoke_with_retry(
    invoke: Callable[[], T], *, read_only: bool, deadline: float, cancelled: threading.Event
) -> T:
    attempt = 0
    while True:
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise McpToolError("MCP_CANCELLED", "Request cancelled before dispatch.")
        try:
            return invoke()
        except Exception as exc:
            if not read_only and _is_ambiguous(exc):
                raise McpToolError(
                    "MCP_WRITE_RESULT_UNKNOWN",
                    "The cloud write may have been accepted.",
                    request_id=getattr(exc, "request_id", None),
                    hint="Query the resource, job_id or order_id before submitting again.",
                ) from exc
            if not read_only or attempt == 2 or _status(exc) not in _RETRY_STATUSES:
                raise
            delay = (0.2 * 2**attempt) + random.uniform(0, 0.1)
            if time.monotonic() + delay >= deadline:
                raise
            time.sleep(delay)
            attempt += 1


async def run_sdk_call(
    invoke: Callable[[], T], *, read_only: bool = False, timeout: float = 60
) -> T:
    """Retry only explicitly read-only 429/502/503/504 calls, within one deadline.

    Admission includes running and queued work. Cancellation does not terminate a
    synchronous HTTP request: the worker retains its capacity until it actually exits.
    """
    if not _CAPACITY.acquire(blocking=False):
        raise McpToolError("MCP_BUSY", "SDK worker capacity reached; retry later.")
    deadline = time.monotonic() + timeout
    cancelled = threading.Event()

    def worker() -> T:
        try:
            return _invoke_with_retry(
                invoke, read_only=read_only, deadline=deadline, cancelled=cancelled
            )
        finally:
            _CAPACITY.release()

    try:
        future = asyncio.get_running_loop().run_in_executor(_EXECUTOR, worker)
    except BaseException:
        _CAPACITY.release()
        raise
    # Consume late errors after the caller has timed out or cancelled.
    future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        cancelled.set()
        raise McpToolError(
            "MCP_TIMEOUT" if read_only else "MCP_WRITE_RESULT_UNKNOWN",
            "Cloud request exceeded its deadline."
            if read_only
            else "The write result is unknown; the cloud request may still complete.",
            hint="Query the resource, job_id or order_id before resubmitting any write.",
        ) from None
    except asyncio.CancelledError:
        cancelled.set()
        raise
