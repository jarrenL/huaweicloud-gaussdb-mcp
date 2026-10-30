"""Real payment boundary: exact cost, state, product scope and ambiguous outcomes."""

import asyncio
from typing import Any

import pytest
from huaweicloud_mcp_core import McpSettings, McpToolError
from mcp import Client

from mcp_server_gaussdb.client.bss_client import BssOrderClient
from mcp_server_gaussdb.service.billing_service import BillingService
from tests.test_billing import ORDER, FakeBss, response

ARGS: dict[str, Any] = {"order_id": ORDER, "expected_amount": "130.00", "currency": "CNY"}


def clean(status: int = 6, **info: Any) -> dict[str, Any]:
    return response(status, amount_after_discount=130, **info)


class PaymentBss(FakeBss):
    def __init__(self, pages: list[dict[str, Any]] | None = None) -> None:
        super().__init__(pages or [clean(), clean(), clean(3, payment_time="2026-10-30T01:00:00Z")])
        self.attempted = False
        self.fail_payment = False
        self.fail_verification = False

    async def get_order(self, **kwargs: Any) -> dict[str, Any]:
        if self.attempted and self.fail_verification:
            raise McpToolError("HTTP_503", "read unavailable", request_id="verify-r")
        return await super().get_order(**kwargs)

    async def pay_order(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("pay_order", kwargs))
        self.attempted = True
        if self.fail_payment:
            raise McpToolError("HTTP_504", "response lost", request_id="pay-r")
        return {}


async def test_payment_binds_cost_refreshes_order_and_verifies_cloud_state() -> None:
    client = PaymentBss()
    result = await BillingService(client).pay_order(**ARGS, confirm=True)
    assert result["payment_submitted"] and result["payment_verified"]
    assert result["order"]["status_name"] == "processing"
    assert result["currency"] == "CNY" and result["expected_amount"] == "130.00"
    assert [c[0] for c in client.calls] == ["get_order", "get_order", "pay_order", "get_order"]
    assert client.calls[2][1] == {"order_id": ORDER}
    assert "instance" in result["hints"][0]


async def test_payment_preview_never_sends_payment() -> None:
    client = PaymentBss()
    result = await BillingService(client).pay_order(**ARGS)
    assert result["confirmation_required"] and result["order"]["official_amount"] == 130
    assert not client.attempted


@pytest.mark.parametrize(
    "changes",
    [
        {"order_id": "../x"},
        {"expected_amount": "-1"},
        {"expected_amount": "nan"},
        {"expected_amount": "1e2"},
        {"expected_amount": "Infinity"},
        {"expected_amount": ""},
        {"expected_amount": 130.0},
        {"expected_amount": True},
        {"currency": "cny"},
        {"currency": ""},
        {"currency": None},
    ],
)
async def test_bad_payment_args_fail_before_credentials(changes: dict[str, Any]) -> None:
    with pytest.raises(McpToolError):
        await BillingService().pay_order(**(ARGS | changes), confirm=True)


@pytest.mark.parametrize(
    "info",
    [
        {"official_amount": 131},
        {"currency": "USD"},
        {"official_amount": None},
        {"official_amount": float("nan")},
        {"official_amount": -1},
        {"official_amount": True},
        {"official_amount": "bad-money"},
    ],
)
async def test_bad_or_changed_cloud_amounts_prevent_payment(info: dict[str, Any]) -> None:
    client = PaymentBss([clean(**info)])
    with pytest.raises(McpToolError):
        await BillingService(client).pay_order(**ARGS, confirm=True)
    assert not client.attempted


async def test_discount_is_not_silently_lost() -> None:
    client = PaymentBss([response()])  # list price 130, discounted price 120
    with pytest.raises(McpToolError, match="discount"):
        await BillingService(client).pay_order(**ARGS, confirm=True)
    assert not client.attempted


@pytest.mark.parametrize("status", [1, 2, 4, 9, 10, 11, 12, 13, 99])
async def test_nonpayable_states_never_submit_payment(status: int) -> None:
    client = PaymentBss([clean(status)])
    with pytest.raises(McpToolError, match="pending-payment"):
        await BillingService(client).pay_order(**ARGS, confirm=True)
    assert not client.attempted


@pytest.mark.parametrize("status", [3, 5])
async def test_processing_or_completed_orders_are_not_paid_again(status: int) -> None:
    client = PaymentBss([clean(status, payment_time="2026-10-30T01:00:00Z")])
    result = await BillingService(client).pay_order(**ARGS, confirm=True)
    assert not result["payment_submitted"] and result["already_processed"]
    assert result["payment_verified"] and not client.attempted


@pytest.mark.parametrize("kind", ["price", "state", "count"])
async def test_final_refresh_can_stop_a_stale_payment(kind: str) -> None:
    final = clean()
    if kind == "price":
        final["order_info"].update(official_amount=131, amount_after_discount=131)
    elif kind == "state":
        final["order_info"]["status"] = 4
    else:
        final["total_count"] = 2
    client = PaymentBss([clean(), final])
    with pytest.raises(McpToolError):
        await BillingService(client).pay_order(**ARGS, confirm=True)
    assert not client.attempted


@pytest.mark.parametrize("kind", ["other-product", "protected-child", "incomplete"])
async def test_later_pages_cannot_hide_unsafe_payment_lines(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = clean(), clean()
    first["total_count"] = second["total_count"] = 2
    if kind == "other-product":
        second["order_line_items"][0]["service_type_code"] = "hws.service.type.ec2"
    elif kind == "protected-child":
        second["order_line_items"][0]["order_id"] = "PROTECTED-ORDER"
        monkeypatch.setenv("HUAWEICLOUD_MCP_PROTECTED_IDS", "PROTECTED-ORDER")
    else:
        second["order_line_items"] = []
    client = PaymentBss([first, second])
    with pytest.raises(McpToolError):
        await BillingService(client).pay_order(**ARGS, confirm=True)
    assert not client.attempted


async def test_complete_pagination_precedes_payment() -> None:
    first, second = clean(), clean()
    first["total_count"] = second["total_count"] = 2
    second["order_line_items"][0]["order_line_item_id"] = "line-2"
    client = PaymentBss([first, second, first, clean(5, payment_time="2026-10-30T01:00:00Z")])
    result = await BillingService(client).pay_order(**ARGS, confirm=True)
    assert result["payment_verified"]
    assert client.calls[1][1]["offset"] == 1


async def test_no_auto_retry_or_fabricated_success_after_ambiguous_response() -> None:
    client = PaymentBss([clean()])
    client.fail_payment = True
    result = await BillingService(client).pay_order(**ARGS, confirm=True)
    assert result["payment_submitted"] is None and not result["payment_verified"]
    assert result["submission_error"]["request_id"] == "pay-r"
    assert sum(c[0] == "pay_order" for c in client.calls) == 1
    client = PaymentBss()
    client.fail_verification = True
    result = await BillingService(client).pay_order(**ARGS, confirm=True)
    assert result["payment_submitted"] and not result["payment_verified"]
    assert result["verification_error"]["request_id"] == "verify-r"


async def test_sdk_payment_contract(settings: McpSettings) -> None:
    from huaweicloudsdkbss.v2 import BssClient as SdkBssClient

    class Recording:
        def __init__(self) -> None:
            self.request: Any = None

        def pay_orders(self, request: Any) -> dict[str, Any]:
            self.request = request
            return {}

    sdk = Recording()
    await BssOrderClient(settings, sdk_client=sdk).pay_order(order_id=ORDER)
    body = sdk.request.body
    assert body.order_id == ORDER and body.use_coupon == "NO" and body.use_discount == "NO"
    assert body.coupon_infos is None and body.discount_infos is None
    info = SdkBssClient._pay_orders_http_info(sdk.request)
    assert info["method"] == "POST"
    assert info["resource_path"] == "/v3/orders/customer-orders/pay"
    assert "expected_amount" not in body.attribute_map  # preflight check, not an atomic BSS cap


async def test_payment_confirmation_and_readonly_do_not_reach_cloud() -> None:
    from types import SimpleNamespace
    from typing import cast

    from huaweicloud_mcp_core.guardrails.audit import AuditLogger
    from huaweicloud_mcp_core.guardrails.middleware import GuardrailsMiddleware

    from mcp_server_gaussdb.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool("pay_order", ARGS)
        assert result.structured_content["confirmation_required"] is True
    context = SimpleNamespace(
        method="tools/call",
        params={
            "name": "pay_order",
            "arguments": ARGS | {"confirm": True},
        },
    )

    async def forbidden(ctx: Any) -> None:
        pytest.fail("Read-only payment must not reach the SDK")

    result = await GuardrailsMiddleware(read_only=True, rules=[], audit=AuditLogger())(
        cast(Any, context),
        forbidden,
    )
    assert result.structured_content["error"]["code"] == "MCP_READ_ONLY"


async def test_concurrent_payment_calls_recheck_state_after_the_first_submission() -> None:
    class Stateful(PaymentBss):
        async def get_order(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(("get_order", kwargs))
            return clean(3, payment_time="2026-10-30T01:00:00Z") if self.attempted else clean()

        async def pay_order(self, **kwargs: Any) -> dict[str, Any]:
            await asyncio.sleep(0.01)
            return await super().pay_order(**kwargs)

    client = Stateful()
    results = await asyncio.gather(
        *[BillingService(client).pay_order(**ARGS, confirm=True) for _ in range(2)]
    )
    assert sum(c[0] == "pay_order" for c in client.calls) == 1
    assert sum(result["payment_submitted"] for result in results) == 1


async def test_changed_amount_after_payment_is_flagged_without_compensating_write() -> None:
    paid = clean(3, payment_time="2026-10-30T01:00:00Z", official_amount=131)
    client = PaymentBss([clean(), clean(), paid])
    result = await BillingService(client).pay_order(**ARGS, confirm=True)
    assert result["payment_submitted"] and result["payment_verified"]
    assert not result["order_amount_matches_approval"] and result["warnings"]
    assert sum(c[0] == "pay_order" for c in client.calls) == 1
