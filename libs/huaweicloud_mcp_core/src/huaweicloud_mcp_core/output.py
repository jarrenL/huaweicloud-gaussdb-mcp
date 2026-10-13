"""Stable envelopes and token-budget enforcement."""

from typing import Any, cast

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_FIELD_LENGTH = 2000


def clamp_limit(limit: int) -> int:
    return min(max(limit, 1), MAX_PAGE_SIZE)


def _truncate_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_FIELD_LENGTH]
    if isinstance(value, list):
        return [_truncate_value(item) for item in value]
    if isinstance(value, dict):
        result = {key: _truncate_value(item) for key, item in value.items()}
        if any(isinstance(item, str) and len(item) > MAX_FIELD_LENGTH for item in value.values()):
            result["_truncated"] = True
        return result
    return value


def page_result(
    items: list[dict[str, Any]], total: int | None = None, marker: str | None = None
) -> dict[str, Any]:
    return {
        "items": [_truncate_value(item) for item in items],
        "count": len(items),
        "total": total if total is not None else len(items),
        "marker": marker,
        "truncated": total is not None and total > len(items),
    }


def single_result(obj: dict[str, Any], hints: list[str] | None = None) -> dict[str, Any]:
    result = cast(dict[str, Any], _truncate_value(obj))
    if hints:
        result["hints"] = hints
    return result
