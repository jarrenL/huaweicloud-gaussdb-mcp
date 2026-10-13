"""Structured JSONL audit output to stderr and an optional append-only file."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .masking import MaskingEngine


class AuditLogger:
    def __init__(self, file_path: str | None = None) -> None:
        self.file_path = file_path
        self.masking = MaskingEngine()

    def emit(self, event: dict[str, Any]) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "tool_call",
            **event,
        }
        params = payload.get("params")
        if isinstance(params, dict):
            payload["params"] = self.masking.mask(
                {
                    key: value[:200] if isinstance(value, str) else value
                    for key, value in params.items()
                }
            )
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        sys.stderr.write(line + "\n")
        if self.file_path:
            with Path(self.file_path).open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
