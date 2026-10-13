"""Recursive credential and secret masking. This layer cannot be disabled."""

import re
from typing import Any

MASK = "***"
_KEY = re.compile(r"password|secret|token|passwd|private.?key|auth|access.?key", re.IGNORECASE)
_PATTERNS = (
    re.compile(r"(?<![A-Z0-9])[A-Z0-9]{16}(?![A-Z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{40}(?![A-Za-z0-9])"),
    re.compile(r"Bearer\s+[^\s,;]+", re.IGNORECASE),
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL),
)


class MaskingEngine:
    def mask_text(self, text: str) -> str:
        for pattern in _PATTERNS:
            text = pattern.sub(MASK, text)
        return text

    def mask(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.mask_text(value)
        if isinstance(value, list):
            return [self.mask(item) for item in value]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            masked = False
            for key, item in value.items():
                if _KEY.search(str(key)):
                    result[str(key)] = MASK
                    masked = True
                else:
                    result[str(key)] = self.mask(item)
            if masked:
                result["_masked"] = True
            return result
        return value
