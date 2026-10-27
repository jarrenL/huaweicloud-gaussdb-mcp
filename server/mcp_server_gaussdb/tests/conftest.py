"""Shared fixtures with full environment isolation."""

import os
from typing import Any

import pytest
from huaweicloud_mcp_core import McpSettings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.getenv("HUAWEICLOUD_MCP_LIVE_TEST") == "1":
        return
    for key in (
        "HUAWEICLOUD_ACCESS_KEY",
        "HUAWEICLOUD_SECRET_KEY",
        "HUAWEICLOUD_REGION",
        "HUAWEICLOUD_PROJECT_ID",
        "HUAWEICLOUD_DOMAIN_ID",
        "HUAWEICLOUD_SECURITY_TOKEN",
        "HUAWEICLOUD_ENDPOINT",
        "HUAWEICLOUD_CES_ENDPOINT",
        "HUAWEICLOUD_MCP_CREDENTIALS_FILE",
        "HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE",
        "HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS",
        "HUAWEICLOUD_MCP_READ_ONLY",
        "HUAWEICLOUD_MCP_PROTECTED_IDS",
        "HUAWEICLOUD_MCP_PROTECTED_NAMES",
        "HUAWEICLOUD_MCP_PROTECTED_TAGS",
        "HUAWEICLOUD_MCP_GUARDRAILS_CONFIG",
        "HUAWEICLOUD_MCP_AUDIT_FILE",
        "MCP_SERVER_HOST",
        "MCP_SERVER_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "1")


@pytest.fixture
def settings() -> McpSettings:
    return McpSettings(
        access_key="A" * 16, secret_key="s" * 40, region="cn-north-4", project_id="0" * 32
    )


class FakeGaussDBClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses: dict[str, dict[str, Any]] = {}

    def _method(self, name: str):  # type: ignore[no-untyped-def]
        async def call(**kwargs: Any) -> dict[str, Any]:
            self.calls.append((name, kwargs))
            return self.responses.get(name, {})

        return call

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return self._method(name)


@pytest.fixture
def fake_client() -> FakeGaussDBClient:
    return FakeGaussDBClient()
