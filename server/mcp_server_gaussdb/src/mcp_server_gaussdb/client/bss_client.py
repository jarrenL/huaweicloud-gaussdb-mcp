"""Thin asynchronous SDK wrapper for customer billing order APIs."""

import asyncio
import os
from typing import Any, cast

from huaweicloud_mcp_core import (
    CredentialScope,
    McpSettings,
    McpToolError,
    build_credentials,
    wrap_sdk_error,
)

from .gaussdb_client import sdk_to_dict


class BssOrderClient:
    def __init__(self, settings: McpSettings | None = None, sdk_client: Any = None) -> None:
        self._settings = settings or McpSettings.from_env()
        if sdk_client is not None:
            self._client = sdk_client
            return
        from huaweicloudsdkbss.v2 import BssClient
        from huaweicloudsdkcore.http.http_config import HttpConfig

        config = HttpConfig.get_default_config()
        config.timeout = 60
        self._client = (
            BssClient.new_builder()
            .with_credentials(build_credentials(CredentialScope.GLOBAL, self._settings))
            .with_endpoint(os.getenv("HUAWEICLOUD_BSS_ENDPOINT") or "https://bss.myhuaweicloud.com")
            .with_http_config(config)
            .build()
        )

    async def _call(self, method: str, request: Any) -> dict[str, Any]:
        def invoke() -> dict[str, Any]:
            try:
                return cast(dict[str, Any], sdk_to_dict(getattr(self._client, method)(request)))
            except Exception as exc:
                wrapped = wrap_sdk_error(exc)
                raise McpToolError(
                    wrapped.code,
                    wrapped.message,
                    request_id=wrapped.request_id,
                    hint="Check the customer account, BSS endpoint and billing permissions. "
                    "Order details require billing:order:view; cancellation also needs the "
                    "applicable BSS order-update permission under your authorization model. "
                    "Only pending-payment orders can be cancelled. "
                    "Query get_order before retrying.",
                ) from exc

        return await asyncio.to_thread(invoke)

    async def get_order(self, *, order_id: str, limit: int, offset: int) -> dict[str, Any]:
        from huaweicloudsdkbss.v2 import ShowCustomerOrderDetailsRequest

        return await self._call(
            "show_customer_order_details",
            ShowCustomerOrderDetailsRequest(
                x_language="zh_CN", order_id=order_id, limit=limit, offset=offset
            ),
        )

    async def cancel_order(self, *, order_id: str) -> dict[str, Any]:
        from huaweicloudsdkbss.v2 import CancelCustomerOrderReq, CancelCustomerOrderRequest

        return await self._call(
            "cancel_customer_order",
            CancelCustomerOrderRequest(body=CancelCustomerOrderReq(order_id=order_id)),
        )
