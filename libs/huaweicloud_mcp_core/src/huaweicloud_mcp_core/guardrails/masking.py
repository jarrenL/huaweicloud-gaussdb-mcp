# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Output masking engine for credentials and secrets (always on)."""

from __future__ import annotations

import re
from typing import Any

MASK = "***"

_FIELD_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "passwd",
    "private_key",
    "auth",
    "access_key",
    "accesskey",
)

_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b[A-Z0-9]{16}\b"),
    re.compile(r"\b[A-Za-z0-9]{40}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"),
)

ExtraPattern = tuple[str, str]


class MaskingEngine:
    """Masks Huawei Cloud credentials and secret-like values on every output path."""

    def __init__(self, extra_patterns: tuple[ExtraPattern, ...] = ()) -> None:
        self._patterns = tuple((name, re.compile(pattern)) for name, pattern in extra_patterns)

    def mask_text(self, text: str) -> str:
        for pattern in _VALUE_PATTERNS:
            text = pattern.sub(MASK, text)
        for _, pattern in self._patterns:
            text = pattern.sub(MASK, text)
        return text

    def mask(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.mask_text(value)
        if isinstance(value, (list, tuple)):
            return [self.mask(item) for item in value]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if _is_sensitive_key(str(key)):
                    result[str(key)] = MASK
                    result[f"{key}_masked"] = True
                else:
                    result[str(key)] = self.mask(item)
            if any(str(key).endswith("_masked") for key in result):
                result["_masked"] = True
            return result
        return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _FIELD_KEY_MARKERS)
