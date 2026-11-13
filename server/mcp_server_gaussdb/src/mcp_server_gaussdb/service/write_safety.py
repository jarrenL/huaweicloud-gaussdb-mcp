"""Shared checks for billing flags on dedicated and generic cloud writes."""

from typing import Any

from huaweicloud_mcp_core import McpToolError


def require_manual_payment(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"is_auto_pay", "is_auto_renew"} and item not in (
                None,
                False,
                "false",
                "False",
            ):
                raise McpToolError(
                    "MCP_INVALID_ARGS",
                    "Automatic payment and renewal must be disabled for MCP provisioning.",
                    hint="Create an unpaid order, call get_order, obtain approval for its exact "
                    "amount/currency, then use pay_order. Manage renewal in the billing console.",
                )
            require_manual_payment(item)
    elif isinstance(value, list):
        for item in value:
            require_manual_payment(item)
