"""Time-window parsing shared by diagnostics and monitoring tools."""

from datetime import datetime

from huaweicloud_mcp_core import McpToolError


def normalize_time_ms(value: int | str, field_name: str) -> int:
    """Normalize an epoch-millisecond or timezone-aware ISO 8601 value."""
    if isinstance(value, bool):
        normalized: int | None = None
    elif isinstance(value, int):
        normalized = value
    elif isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            normalized = int(text)
        else:
            try:
                iso_value = f"{text[:-1]}+00:00" if text.upper().endswith("Z") else text
                parsed = datetime.fromisoformat(iso_value)
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError("timezone required")
                normalized = int(parsed.timestamp() * 1000)
            except (OverflowError, ValueError):
                normalized = None
    else:
        normalized = None
    if normalized is None:
        raise McpToolError(
            "MCP_INVALID_ARGS",
            f"{field_name} must be Unix epoch milliseconds or ISO 8601 with a timezone.",
            hint=(
                f"Use an integer such as 1761046200000 or a value such as "
                f"2026-10-21T15:30:00+08:00 / 2026-10-21T07:30:00Z for {field_name}."
            ),
        )
    return normalized
