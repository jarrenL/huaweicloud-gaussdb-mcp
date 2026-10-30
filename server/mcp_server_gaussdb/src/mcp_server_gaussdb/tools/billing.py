"""GaussDB order details, confirmed payment and unpaid-order cancellation tools."""

from typing import Any

from huaweicloud_mcp_core import ToolRisk, guard

from ..server import mcp
from ..service.billing_service import BillingService


@mcp.tool()
@guard(risk=ToolRisk.DANGEROUS)
async def pay_order(
    order_id: str, expected_amount: str, currency: str, confirm: bool = False
) -> dict[str, Any]:
    """Pay one pending GaussDB order from the account balance after explicit cost approval.

    Scenario: get_order returned an unpaid yearly/monthly order. Obtain approval for its exact
    ID, amount and currency. This submits a real payment; confirm is not proof of human approval.

    Args:
        order_id: Exact GaussDB order ID from create_instance/get_order, at most 64 characters.
        expected_amount: Approved decimal amount as a string, e.g. '1248.00'. Must match both
            official_amount and amount_after_discount; discounted orders are rejected to avoid
            losing a discount. This tool does not select coupons or discounts.
        currency: Exact three-letter currency from get_order, e.g. CNY; never infer from region.
        confirm: True only after authorization for this order and cost; false makes no payment.

    Returns:
        Submission/verification flags and current order state; no automatic payment retries.
        Requires billing:order:view and billing:order:pay. Rejects cancelled, protected,
        and mixed-product orders. Already processing/completed orders are not submitted again.
        Inspect get_order and get_instance after payment; acceptance is not provisioning success.
    """
    return await BillingService().pay_order(
        order_id=order_id, expected_amount=expected_amount, currency=currency, confirm=confirm
    )


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def get_order(order_id: str, limit: int = 20, marker: str | None = None) -> dict[str, Any]:
    """Inspect a GaussDB yearly/monthly order, amounts and paginated order lines.

    Scenario: create_instance returned order_id instead of a job_id. Check the order before
    payment or cancellation; an unpaid order does not mean the instance has been provisioned.

    Args:
        order_id: Exact order ID returned by create_instance, e.g. CS202610300000EXAMPLE.
            Accepts 1-64 letters, digits, underscores or hyphens; only GaussDB orders are allowed.
        limit: Order lines per page, default 20, clamped to 1-100.
        marker: Offset returned by the previous get_order call; omit for the first page.

    Returns:
        Order status, amount, currency, payment time, expiry for pending payment, and line items.
        Uses shared AK/SK/STS with global BSS credentials; requires billing:order:view.
    """
    return await BillingService().get_order(order_id=order_id, limit=limit, marker=marker)


@mcp.tool()
@guard(risk=ToolRisk.DANGEROUS)
async def cancel_order(order_id: str, confirm: bool = False) -> dict[str, Any]:
    """Cancel one unpaid GaussDB order after rechecking its cloud state and product scope.

    Scenario: abandon an unneeded pending-payment order from create_instance. Run get_order
    first and obtain authorization for this exact order; cancellation cannot be undone.

    Args:
        order_id: Exact GaussDB order ID from create_instance or get_order, at most 64 characters.
        confirm: Must be true after approval; false performs no cancellation.

    Returns:
        Submission and verification flags plus the current order state. Requires BSS order
        read/update permissions. Paid, mixed-product and protected orders are rejected. This
        tool does not pay, refund, unsubscribe, or delete an instance.
    """
    return await BillingService().cancel_order(order_id=order_id, confirm=confirm)
