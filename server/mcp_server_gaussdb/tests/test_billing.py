"""BSS SDK contracts, order scope, status transitions and cancellation safeguards."""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast

import pytest
from huaweicloud_mcp_core import McpSettings, McpToolError
from mcp import Client

from mcp_server_gaussdb.client.bss_client import BssOrderClient
from mcp_server_gaussdb.service.billing_service import BillingService

ORDER = "CS202610300000EXAMPLE"
GAUSSDB = "hws.service.type.gaussdb"


def response(status: int = 6, **info: Any) -> dict[str, Any]:
    return {
        "order_info": {
            "order_id": ORDER,
            "status": status,
            "service_type_code": GAUSSDB,
            "amount_after_discount": 120,
            "official_amount": 130,
            "currency": "CNY",
            "measure_id": 1,
            "payment_time": None,
            "user_name": "private-user",
            "customer_id": "private-account",
            "sub_order_infos": [],
            **info,
        },
        "total_count": 1,
        "order_line_items": [
            {
                "order_line_item_id": "line-1",
                "service_type_code": GAUSSDB,
                "product_spec_desc": "test GaussDB",
                "period_type": 2,
                "period_num": 1,
                "amount_after_discount": 120,
                "currency": "CNY",
                "internal": "omit",
            }
        ],
    }


class FakeBss(BssOrderClient):
    def __init__(self, pages: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.pages = pages or [response()]
        self.read_error_after_cancel = False
        self.cancelled = False

    async def get_order(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_order", kwargs))
        if self.cancelled and self.read_error_after_cancel:
            raise McpToolError(
                "HTTP_503", "temporary read failure", request_id="request-after-write"
            )
        return deepcopy(self.pages.pop(0) if len(self.pages) > 1 else self.pages[0])

    async def cancel_order(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("cancel_order", kwargs))
        self.cancelled = True
        return {}


async def test_details_keep_amount_and_currency_without_account_identity() -> None:
    page = response()
    page["total_count"] = 3
    client = FakeBss([page])
    result = await BillingService(client).get_order(order_id=ORDER, limit=1, marker="1")
    assert result["order"]["amount_after_discount"] == 120
    assert result["order"]["currency"] == "CNY"
    assert result["order"]["status_name"] == "pending_payment"
    assert "user_name" not in result["order"] and "customer_id" not in result["order"]
    assert "internal" not in result["items"][0]
    assert result["total"] == 3 and result["marker"] == "2"
    assert client.calls[0][1] == {"order_id": ORDER, "offset": 1, "limit": 1}
    assert "coupon" in result["hints"][0]
    page["total_count"] = 1
    end = await BillingService(FakeBss([page])).get_order(order_id=ORDER, limit=999)
    assert end["marker"] is None
    page.pop("total_count")
    unknown = await BillingService(FakeBss([page])).get_order(order_id=ORDER, limit=1)
    assert unknown["marker"] == "1"
    page["order_line_items"] = []
    assert (await BillingService(FakeBss([page])).get_order(order_id=ORDER))["marker"] is None


@pytest.mark.parametrize("order_id", ["", "x" * 65, "../x", "a?b", "a\nb"])
async def test_bad_id_fails_before_credential_or_cloud_access(order_id: str) -> None:
    with pytest.raises(McpToolError, match="order_id"):
        await BillingService().get_order(order_id=order_id)
    with pytest.raises(McpToolError, match="order_id"):
        await BillingService().cancel_order(order_id=order_id, confirm=True)


@pytest.mark.parametrize("marker", ["", "-1", "1.0", "next", "2147483648", "0" * 11])
async def test_bad_offset_is_rejected_before_cloud_access(marker: str) -> None:
    with pytest.raises(McpToolError, match="marker"):
        await BillingService().get_order(order_id=ORDER, marker=marker)


@pytest.mark.parametrize("kind", ["other", "mixed", "missing", "mismatch", "child", "line"])
async def test_non_gaussdb_or_unverifiable_orders_fail_closed(kind: str) -> None:
    page = response()
    if kind == "other":
        page["order_info"]["service_type_code"] = "hws.service.type.ec2"
    elif kind == "mixed":
        page["order_info"]["service_type_code"] += ",hws.service.type.ec2"
    elif kind == "missing":
        page.pop("order_info")
    elif kind == "mismatch":
        page["order_info"]["order_id"] = "OTHER"
    elif kind == "child":
        page["order_info"]["sub_order_infos"] = [{"service_type_code": "hws.service.type.ec2"}]
    else:
        page["order_line_items"][0]["service_type_code"] = "hws.service.type.ec2"
    client = FakeBss([page])
    with pytest.raises(McpToolError):
        await BillingService(client).get_order(order_id=ORDER)
    with pytest.raises(McpToolError):
        await BillingService(client).cancel_order(order_id=ORDER, confirm=True)
    assert not client.cancelled


async def test_preview_does_not_cancel_and_protection_is_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeBss()
    preview = await BillingService(client).cancel_order(order_id=ORDER)
    assert preview["confirmation_required"] is True
    assert preview["order"]["amount_after_discount"] == 120
    assert not client.cancelled
    monkeypatch.setenv("HUAWEICLOUD_MCP_PROTECTED_IDS", ORDER)
    with pytest.raises(McpToolError) as exc:
        await BillingService(client).cancel_order(order_id=ORDER, confirm=True)
    assert exc.value.code == "MCP_GUARDRAIL_BLOCKED" and not client.cancelled


@pytest.mark.parametrize("status", [1, 2, 3, 5, 9, 10, 11, 12, 13, 99])
async def test_only_pending_payment_can_be_cancelled(status: int) -> None:
    client = FakeBss([response(status)])
    with pytest.raises(McpToolError, match="pending-payment"):
        await BillingService(client).cancel_order(order_id=ORDER, confirm=True)
    assert not client.cancelled


async def test_paid_timestamp_blocks_cancellation_even_if_status_is_stale() -> None:
    client = FakeBss([response(payment_time="2026-10-30T01:00:00Z")])
    with pytest.raises(McpToolError):
        await BillingService(client).cancel_order(order_id=ORDER, confirm=True)
    assert not client.cancelled


async def test_already_cancelled_is_idempotent_without_a_second_write() -> None:
    client = FakeBss([response(4)])
    result = await BillingService(client).cancel_order(order_id=ORDER, confirm=True)
    assert result["cancellation_verified"] and result["already_cancelled"]
    assert not result["cancellation_submitted"] and not client.cancelled


async def test_all_order_pages_are_checked_and_cancellation_is_verified() -> None:
    first, second = response(), response()
    first["total_count"] = second["total_count"] = 2
    second["order_line_items"][0]["order_line_item_id"] = "line-2"
    client = FakeBss([first, second, response(4)])
    result = await BillingService(client).cancel_order(order_id=ORDER, confirm=True)
    assert result["cancellation_submitted"] and result["cancellation_verified"]
    assert [call[0] for call in client.calls] == [
        "get_order",
        "get_order",
        "cancel_order",
        "get_order",
    ]
    assert client.calls[1][1]["offset"] == 1
    assert result["order"]["status_name"] == "cancelled"


@pytest.mark.parametrize(
    "kind", ["other-product", "empty-page", "total-changed", "paid-page", "too-many"]
)
async def test_bad_later_page_prevents_cancellation(kind: str) -> None:
    first, second = response(), response()
    first["total_count"] = second["total_count"] = 2
    if kind == "other-product":
        second["order_line_items"][0]["service_type_code"] = "hws.service.type.ec2"
    elif kind == "empty-page":
        second["order_line_items"] = []
    elif kind == "total-changed":
        second["total_count"] = 3
    elif kind == "paid-page":
        second["order_info"]["status"] = 5
    else:
        first["total_count"] = 1001
    client = FakeBss([first, second])
    with pytest.raises(McpToolError):
        await BillingService(client).cancel_order(order_id=ORDER, confirm=True)
    assert not client.cancelled


async def test_successful_write_does_not_fabricate_verified_status() -> None:
    client = FakeBss()
    result = await BillingService(client).cancel_order(order_id=ORDER, confirm=True)
    assert result["cancellation_submitted"] and not result["cancellation_verified"]
    client = FakeBss()
    client.read_error_after_cancel = True
    result = await BillingService(client).cancel_order(order_id=ORDER, confirm=True)
    assert result["cancellation_submitted"] and not result["cancellation_verified"]
    assert result["verification_error"]["request_id"] == "request-after-write"
    assert len([x for x in client.calls if x[0] == "cancel_order"]) == 1


async def test_bss_sdk_wire_contract(settings: McpSettings) -> None:
    from huaweicloudsdkbss.v2 import BssClient as SdkBssClient

    class Recording:
        def __init__(self) -> None:
            self.read: Any = None
            self.cancel: Any = None

        def show_customer_order_details(self, request: Any) -> dict[str, Any]:
            self.read = request
            return response()

        def cancel_customer_order(self, request: Any) -> dict[str, Any]:
            self.cancel = request
            return {}

    sdk = Recording()
    client = BssOrderClient(settings, sdk_client=sdk)
    await client.get_order(order_id=ORDER, limit=20, offset=40)
    assert sdk.read.order_id == ORDER and sdk.read.offset == 40 and sdk.read.limit == 20
    assert sdk.read.indirect_partner_id is None
    info = SdkBssClient._show_customer_order_details_http_info(sdk.read)
    assert info["method"] == "GET"
    assert info["resource_path"] == "/v2/orders/customer-orders/details/{order_id}"
    await client.cancel_order(order_id=ORDER)
    assert sdk.cancel.body.order_id == ORDER
    info = SdkBssClient._cancel_customer_order_http_info(sdk.cancel)
    assert info["method"] == "PUT"
    assert info["resource_path"] == "/v2/orders/customer-orders/cancel"


async def test_sdk_errors_keep_request_id_and_permissions_hint(settings: McpSettings) -> None:
    from huaweicloudsdkcore.exceptions.exceptions import ClientRequestException

    class Denied:
        def show_customer_order_details(self, request: Any) -> None:
            raise ClientRequestException(
                403,
                SimpleNamespace(
                    error_code="CBC.0151",
                    error_msg="denied",
                    request_id="r-bss",
                    encoded_auth_msg=None,
                ),
            )

    with pytest.raises(McpToolError) as exc:
        await BssOrderClient(settings, sdk_client=Denied()).get_order(
            order_id=ORDER, limit=1, offset=0
        )
    assert exc.value.request_id == "r-bss" and "billing:order:view" in (exc.value.hint or "")


def test_global_credentials_reuse_sts_and_ignore_gaussdb_endpoint(
    settings: McpSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    monkeypatch.setenv("HUAWEICLOUD_BSS_ENDPOINT", "https://bss.example.com")
    client = BssOrderClient(replace(settings, domain_id="d", security_token="sts-token"))
    sdk = client._client
    assert sdk.get_credentials().domain_id == "d"
    assert sdk.get_credentials().security_token == "sts-token"


async def test_cancellation_requires_confirmation_without_cloud_access() -> None:
    from mcp_server_gaussdb.server import mcp

    async with Client(mcp) as client:
        # The generic middleware requires confirmation before constructing a BSS client.
        result = await client.call_tool("cancel_order", {"order_id": ORDER})
        assert result.structured_content["confirmation_required"] is True


async def test_readonly_blocks_order_cancellation_before_bss_access() -> None:
    from huaweicloud_mcp_core.guardrails.audit import AuditLogger
    from huaweicloud_mcp_core.guardrails.middleware import GuardrailsMiddleware

    context = SimpleNamespace(
        method="tools/call",
        params={
            "name": "cancel_order",
            "arguments": {"order_id": ORDER, "confirm": True},
        },
    )

    async def forbidden(ctx: Any) -> None:
        pytest.fail("Read-only cancellation must not reach the service")

    result = await GuardrailsMiddleware(read_only=True, rules=[], audit=AuditLogger())(
        cast(Any, context),
        forbidden,
    )
    assert result.structured_content["error"]["code"] == "MCP_READ_ONLY"


@pytest.mark.parametrize("source", ["child", "line"])
async def test_protected_suborder_cannot_be_cancelled_through_a_parent(
    source: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = response()
    if source == "child":
        page["order_info"]["sub_order_infos"] = [
            {"order_id": "PROTECTED-CHILD", "service_type_code": GAUSSDB},
        ]
    else:
        page["order_line_items"][0]["order_id"] = "PROTECTED-CHILD"
    monkeypatch.setenv("HUAWEICLOUD_MCP_PROTECTED_IDS", "PROTECTED-CHILD")
    client = FakeBss([page])
    with pytest.raises(McpToolError) as exc:
        await BillingService(client).cancel_order(order_id=ORDER, confirm=True)
    assert exc.value.code == "MCP_GUARDRAIL_BLOCKED" and not client.cancelled
