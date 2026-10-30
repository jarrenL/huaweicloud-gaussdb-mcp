"""GaussDB-only order details, bounded pagination and guarded unpaid-order cancellation."""

import re
from typing import Any

from huaweicloud_mcp_core import McpToolError, clamp_limit, page_result, single_result
from huaweicloud_mcp_core.guardrails.protect import assert_not_protected

from ..client.bss_client import BssOrderClient

_GAUSSDB = "hws.service.type.gaussdb"
_ORDER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_ORDER_FIELDS = (
    "order_id",
    "service_type_code",
    "service_type_name",
    "status",
    "order_type",
    "official_amount",
    "amount_after_discount",
    "measure_id",
    "currency",
    "create_time",
    "payment_time",
    "pending_payment_end_time",
)
_ITEM_FIELDS = (
    "order_line_item_id",
    "order_id",
    "service_type_code",
    "service_type_name",
    "product_id",
    "product_spec_desc",
    "period_type",
    "period_num",
    "subscription_num",
    "effective_time",
    "expire_time",
    "official_amount",
    "amount_after_discount",
    "currency",
)
_STATUSES = {
    1: "pending_review",
    2: "pending_refund",
    3: "processing",
    4: "cancelled",
    5: "completed",
    6: "pending_payment",
    9: "pending_confirmation",
    10: "pending_delivery",
    11: "pending_receipt",
    12: "pending_pickup",
    13: "replacement_in_progress",
}


def _invalid(message: str) -> McpToolError:
    return McpToolError(
        "MCP_INVALID_ARGS", message, hint="Use the order_id returned by create_instance."
    )


def _validate_id(order_id: str) -> None:
    if not isinstance(order_id, str) or not _ORDER_ID.fullmatch(order_id):
        raise _invalid("order_id must contain 1-64 letters, digits, underscores or hyphens.")


def _scope_error() -> McpToolError:
    return McpToolError(
        "MCP_INVALID_ARGS",
        "This tool only handles GaussDB orders; non-GaussDB or mixed-product orders are rejected.",
        hint="Verify the order_id in the billing console. "
        "Use the appropriate service for other orders.",
    )


def _gaussdb_only(code: Any) -> bool:
    return isinstance(code, str) and {part.strip() for part in code.split(",")} == {_GAUSSDB}


def _order_info(response: dict[str, Any], order_id: str) -> dict[str, Any]:
    info = response.get("order_info")
    if not isinstance(info, dict) or info.get("order_id") != order_id:
        raise McpToolError(
            "MCP_SDK_ERROR",
            "BSS returned missing or mismatched order details.",
            hint="Verify the order in the billing console before retrying.",
        )
    if not _gaussdb_only(info.get("service_type_code")):
        raise _scope_error()
    children = info.get("sub_order_infos") or []
    if not isinstance(children, list) or any(
        not isinstance(child, dict) or not _gaussdb_only(child.get("service_type_code"))
        for child in children
    ):
        raise _scope_error()
    return info


def _items(response: dict[str, Any]) -> list[dict[str, Any]]:
    items = response.get("order_line_items") or []
    if not isinstance(items, list) or any(
        not isinstance(item, dict) or not _gaussdb_only(item.get("service_type_code"))
        for item in items
    ):
        raise _scope_error()
    return items


def _summary(info: dict[str, Any]) -> dict[str, Any]:
    result = {key: info[key] for key in _ORDER_FIELDS if key in info}
    status = info.get("status")
    result["status_name"] = _STATUSES.get(status, "unknown") if type(status) is int else "unknown"
    result["sub_order_infos"] = [
        {key: child[key] for key in _ORDER_FIELDS if key in child}
        for child in info.get("sub_order_infos") or []
    ]
    return result


def _require_unpaid(info: dict[str, Any]) -> None:
    if type(info.get("status")) is not int or info["status"] != 6 or info.get("payment_time"):
        raise McpToolError(
            "MCP_INVALID_ARGS",
            "Only an unpaid pending-payment GaussDB order can be cancelled.",
            hint="Call get_order to inspect the latest status. Paid resources require the separate "
            "unsubscription workflow; this tool never deletes or unsubscribes an instance.",
        )


def _check_protection(info: dict[str, Any], items: list[dict[str, Any]]) -> None:
    order_ids = {info["order_id"]}
    order_ids.update(
        child["order_id"] for child in info.get("sub_order_infos") or [] if child.get("order_id")
    )
    order_ids.update(item["order_id"] for item in items if item.get("order_id"))
    for order_id in order_ids:
        assert_not_protected({"id": order_id, "name": order_id}, tool_name="cancel_order")


class BillingService:
    def __init__(self, client: BssOrderClient | None = None) -> None:
        self._client = client

    def _bss(self) -> BssOrderClient:
        if self._client is None:
            self._client = BssOrderClient()
        return self._client

    async def get_order(
        self, *, order_id: str, limit: int = 20, marker: str | None = None
    ) -> dict[str, Any]:
        _validate_id(order_id)
        if marker is not None and (
            not isinstance(marker, str)
            or not re.fullmatch(r"[0-9]{1,10}", marker)
            or int(marker) > 2147483647
        ):
            raise _invalid("marker must be a BSS offset returned by get_order.")
        offset = int(marker or 0)
        limit = clamp_limit(limit)
        response = await self._bss().get_order(order_id=order_id, limit=limit, offset=offset)
        info, items = _order_info(response, order_id), _items(response)
        total = response.get("total_count")
        next_marker = (
            str(offset + len(items))
            if items
            and (offset + len(items) < total if isinstance(total, int) else len(items) == limit)
            else None
        )
        return {
            **page_result(
                [{key: item[key] for key in _ITEM_FIELDS if key in item} for item in items],
                total=total,
                marker=next_marker,
            ),
            "order": _summary(info),
            "hints": [
                "amount_after_discount excludes coupon/card deductions; preserve the returned "
                "currency and measure_id. An order ID or pending-payment state does not mean "
                "an instance has been provisioned. "
                "Payment requires a separate authorized workflow.",
            ],
        }

    async def cancel_order(self, *, order_id: str, confirm: bool = False) -> dict[str, Any]:
        _validate_id(order_id)
        response = await self._bss().get_order(order_id=order_id, limit=100, offset=0)
        info = _order_info(response, order_id)
        if info.get("status") == 4 and not info.get("payment_time"):
            return single_result(
                {
                    "order": _summary(info),
                    "cancellation_submitted": False,
                    "cancellation_verified": True,
                    "already_cancelled": True,
                }
            )
        _require_unpaid(info)
        items = _items(response)
        _check_protection(info, items)
        if confirm is not True:
            return single_result(
                {
                    "confirmation_required": True,
                    "order": _summary(info),
                    "message": "Cancel this exact unpaid order permanently; "
                    "call again with confirm=true.",
                }
            )
        # Read every line so mixed-product orders cannot hide beyond the first page.
        total = response.get("total_count")
        if type(total) is not int or not 1 <= total <= 1000 or not items or len(items) > total:
            raise _invalid("Cannot verify all order lines within the 1000-line cancellation limit.")
        offset = len(items)
        while offset < total:
            page = await self._bss().get_order(order_id=order_id, limit=100, offset=offset)
            latest = _order_info(page, order_id)
            _require_unpaid(latest)
            chunk = _items(page)
            _check_protection(latest, chunk)
            if page.get("total_count") != total or not chunk or offset + len(chunk) > total:
                raise _invalid(
                    "Order lines changed or pagination was incomplete; cancellation stopped."
                )
            offset += len(chunk)
        await self._bss().cancel_order(order_id=order_id)
        # A successful submission is not proof that the cloud state has changed.
        try:
            checked = _order_info(
                await self._bss().get_order(order_id=order_id, limit=1, offset=0), order_id
            )
        except McpToolError as exc:
            return single_result(
                {
                    "order_id": order_id,
                    "cancellation_submitted": True,
                    "cancellation_verified": False,
                    "verification_error": exc.to_dict()["error"],
                },
                ["Cancellation was submitted. Call get_order to verify; do not resubmit blindly."],
            )
        return single_result(
            {
                "order": _summary(checked),
                "cancellation_submitted": True,
                "cancellation_verified": checked.get("status") == 4,
            },
            ["Use get_order to track the order until status_name is cancelled."],
        )
