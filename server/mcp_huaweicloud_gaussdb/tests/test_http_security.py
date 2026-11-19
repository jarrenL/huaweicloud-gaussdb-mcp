"""Exercise public HTTP transport safeguards with an in-process ASGI client."""

import pytest
from huaweicloud_mcp_core.errors import McpToolError
from starlette.testclient import TestClient

from mcp_huaweicloud_gaussdb.compat.http_security import secure_http_app
from mcp_huaweicloud_gaussdb.compat.settings import McpSettings
from mcp_huaweicloud_gaussdb.server import mcp


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (McpSettings(server_host="0.0.0.0"), "Non-loopback"),
        (McpSettings(http_token="short"), "32 characters"),
        (McpSettings(allowed_hosts=("*.example",)), "wildcards"),
    ],
)
def test_invalid_http_settings_are_rejected(settings: McpSettings, message: str) -> None:
    with pytest.raises(McpToolError, match=message):
        secure_http_app(mcp, settings)


def test_token_host_origin_and_body_limit_are_enforced() -> None:
    settings = McpSettings(
        server_host="0.0.0.0",
        http_token="example-token-" + "x" * 32,
        allowed_hosts=("testserver",),
        allowed_origins=("https://client.example",),
    )
    app = secure_http_app(mcp, settings)
    headers = {
        "Authorization": f"Bearer {settings.http_token}",
        "Accept": "application/json, text/event-stream",
        "Origin": "https://client.example",
    }
    initialize = {
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
        assert client.post("/mcp", json=initialize).status_code == 401
        wrong_token = {**headers, "Authorization": "Bearer wrong"}
        assert client.post("/mcp", json=initialize, headers=wrong_token).status_code == 401
        wrong_origin = {**headers, "Origin": "https://other.example"}
        assert client.post("/mcp", json=initialize, headers=wrong_origin).status_code == 403
        wrong_host = {**headers, "Host": "other.example"}
        assert client.post("/mcp", json=initialize, headers=wrong_host).status_code == 421
        oversized = {**initialize, "unused": "x" * (1024 * 1024)}
        assert client.post("/mcp", json=oversized, headers=headers).status_code == 413
        response = client.post("/mcp", json=initialize, headers=headers)
        assert response.status_code == 200
        assert "huaweicloud-gaussdb" in response.text and '"version":"0.1.1"' in response.text


def test_local_hostname_needs_no_token() -> None:
    assert secure_http_app(mcp, McpSettings(server_host="localhost")) is not None
