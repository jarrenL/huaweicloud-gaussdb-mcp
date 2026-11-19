# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Structured JSONL audit logging (always on)."""

from __future__ import annotations

import contextlib
import json
import os
import stat
import sys
import threading
import time
from typing import Any

from .masking import MaskingEngine

_MAX_PARAM_LENGTH = 200


def _trim_params(params: Any, depth: int = 0, *, trim_strings: bool = True) -> Any:
    if depth >= 8:
        return "<truncated>"
    if isinstance(params, dict):
        return _trim_mapping(params, depth, trim_strings=trim_strings)
    if isinstance(params, (list, tuple)):
        return [_trim_params(item, depth + 1, trim_strings=trim_strings) for item in params[:100]]
    if trim_strings and isinstance(params, str) and len(params) > _MAX_PARAM_LENGTH:
        return params[:_MAX_PARAM_LENGTH]
    return params


def _trim_mapping(
    params: dict[Any, Any], depth: int = 0, *, trim_strings: bool = True
) -> dict[str, Any]:
    return {
        str(key): _trim_params(value, depth + 1, trim_strings=trim_strings)
        for key, value in list(params.items())[:100]
        if value is not None
    }


class AuditLogger:
    """Emits one JSONL record per tool call to stderr and (optionally) a file."""

    def __init__(
        self,
        file_path: str | None = None,
        masking: MaskingEngine | None = None,
        *,
        history_limit: int = 1000,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 3,
    ) -> None:
        if history_limit < 0 or max_bytes < 1 or not 1 <= backup_count <= 20:
            raise ValueError("Invalid audit history or rotation limits")
        self._file_path = file_path
        self._masking = masking or MaskingEngine()
        self.events: list[dict[str, Any]] = []
        self._history_limit = history_limit
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._lock = threading.Lock()
        self.file_errors = 0

    @property
    def file_path(self) -> str | None:
        return self._file_path

    def _build_record(self, **event: Any) -> dict[str, Any]:
        raw_record: dict[str, Any] = {
            "ts": _utc_timestamp(),
            "event": "tool_call",
        }
        raw_record.update(event)
        bounded_record = _trim_mapping(raw_record, trim_strings=False)
        masked_record = _trim_mapping(self._masking.mask(bounded_record))
        if len(json.dumps(masked_record, ensure_ascii=False, default=str).encode()) <= 16 * 1024:
            return masked_record
        compact_record: dict[str, Any] = {
            key: masked_record[key]
            for key in (
                "ts",
                "event",
                "tool",
                "risk",
                "decision",
                "outcome",
                "error_code",
                "request_id",
                "duration_ms",
            )
            if key in masked_record
        }
        compact_record["params"] = {"_truncated": True, "reason": "audit_size_limit"}
        return compact_record

    def emit(self, **event: Any) -> None:
        record = self._build_record(**event)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            if self._history_limit:
                self.events.append(record)
                del self.events[: -self._history_limit]
            try:
                print(line, file=sys.stderr)
                if self._file_path:
                    self._write_file(self._file_path, (line + "\n").encode("utf-8"))
            except OSError:
                self.file_errors += 1
                fallback = json.dumps(
                    {"event": "audit_file_error", "severity": "ERROR", "path": self._file_path}
                )
                # A broken logging sink must not disguise an accepted cloud write.
                with contextlib.suppress(OSError):
                    print(fallback, file=sys.stderr)

    def _write_file(self, file_path: str, data: bytes) -> None:
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(file_path, flags, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and info.st_mode & 0o077):
                raise OSError("Audit file must be a private regular file")
            if info.st_size and info.st_size + len(data) > self._max_bytes:
                os.close(descriptor)
                descriptor = -1
                for index in range(self._backup_count, 0, -1):
                    source = file_path if index == 1 else f"{file_path}.{index - 1}"
                    if os.path.lexists(source):
                        os.replace(source, f"{file_path}.{index}")
                descriptor = os.open(file_path, flags, 0o600)
            with os.fdopen(descriptor, "ab", closefd=False) as handle:
                handle.write(data)
        finally:
            if descriptor >= 0:
                os.close(descriptor)


def _utc_timestamp() -> str:
    now = time.time()
    base = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now))
    return f"{base}.{int(now * 1000) % 1000:03d}Z"
