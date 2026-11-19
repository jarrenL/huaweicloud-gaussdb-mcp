# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""HTTP access gate for deployments using a shared token behind an HTTPS gateway.

This gate does not advertise an OAuth authorization server or prove human approval.
Cloud AK/SK are separate from the caller's access token.
"""

from __future__ import annotations

import hmac
import ipaddress
from typing import Any

from huaweicloud_mcp_core.errors import McpToolError
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .settings import McpSettings


class TokenGate:
    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
            if len(headers) != 1 or not hmac.compare_digest(headers[0], self._expected):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def secure_http_app(server: MCPServer[Any], settings: McpSettings) -> Starlette:
    try:
        local = ipaddress.ip_address(settings.server_host).is_loopback
    except ValueError:
        local = settings.server_host == "localhost"
    if settings.http_token is not None and len(settings.http_token) < 32:
        raise McpToolError(
            "MCP_CONFIG_ERROR", "The MCP HTTP token must contain at least 32 characters."
        )
    if not local and (not settings.http_token or not settings.allowed_hosts):
        raise McpToolError(
            "MCP_CONFIG_ERROR",
            "Non-loopback HTTP requires HUAWEICLOUD_MCP_HTTP_TOKEN and MCP_SERVER_ALLOWED_HOSTS.",
            hint="Use an HTTPS gateway with exact public Host/Origin allowlists.",
        )
    if any("*" in value for value in (*settings.allowed_hosts, *settings.allowed_origins)):
        raise McpToolError("MCP_CONFIG_ERROR", "HTTP Host/Origin wildcards are not allowed.")
    security = None
    if settings.allowed_hosts or settings.allowed_origins:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(settings.allowed_hosts),
            allowed_origins=list(settings.allowed_origins),
        )
    app = server.streamable_http_app(
        host=settings.server_host,
        transport_security=security,
        max_request_body_size=1024 * 1024,
        max_sessions=128,
        session_idle_timeout=300,
    )
    if settings.http_token:
        app.add_middleware(TokenGate, token=settings.http_token)
    return app
