"""Real HTTP transport gate checks using an in-process ASGI client."""

from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from huaweicloud_mcp_core import McpSettings, McpToolError, build_server
from huaweicloud_mcp_core.http_security import secure_http_app


def test_public_bind_requires_auth_and_explicit_hosts() -> None:
    server = build_server("test")
    with pytest.raises(McpToolError, match="Non-loopback"):
        secure_http_app(server, McpSettings(server_host="0.0.0.0"))
    with pytest.raises(McpToolError, match="32 characters"):
        secure_http_app(server, McpSettings(http_token="short"))
    with pytest.raises(McpToolError, match="wildcards"):
        secure_http_app(server, McpSettings(allowed_hosts=("*",)))
    assert secure_http_app(server, McpSettings()) is not None


def test_token_and_origin_are_enforced_on_transport() -> None:
    settings = McpSettings(
        server_host="0.0.0.0",
        http_token="example-token-" + "x" * 32,
        allowed_hosts=("testserver",),
        allowed_origins=("https://client.example",),
    )
    app = secure_http_app(build_server("test"), settings)
    headers = {
        "Authorization": f"Bearer {settings.http_token}",
        "Accept": "application/json, text/event-stream",
        "Origin": "https://client.example",
    }
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    with TestClient(app) as client:
        assert client.post("/mcp", json=message).status_code == 401
        assert (
            client.post(
                "/mcp", json=message, headers={**headers, "Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/mcp", json=message, headers={**headers, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/mcp", json=message, headers={**headers, "Host": "evil.example"}
            ).status_code
            == 421
        )
        assert client.post("/mcp", json=message, headers=headers).status_code == 200
    assert (
        secure_http_app(build_server("test"), replace(settings, server_host="localhost"))
        is not None
    )
