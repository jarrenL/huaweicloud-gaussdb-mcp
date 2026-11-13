# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Tests for McpSettings environment parsing."""

from __future__ import annotations

import pytest

from huaweicloud_mcp_core.config import McpSettings
from huaweicloud_mcp_core.errors import McpToolError


def test_missing_required_credentials_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(McpToolError) as excinfo:
        McpSettings.from_env()
    message = excinfo.value.message
    assert "HUAWEICLOUD_ACCESS_KEY" in message
    assert "HUAWEICLOUD_SECRET_KEY" in message
    assert "HUAWEICLOUD_REGION" in message
    assert "Export" in (excinfo.value.hint or "")


def test_missing_single_variable_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUAWEICLOUD_ACCESS_KEY", "ak")
    monkeypatch.setenv("HUAWEICLOUD_SECRET_KEY", "sk")
    with pytest.raises(McpToolError) as excinfo:
        McpSettings.from_env()
    assert "HUAWEICLOUD_REGION" in excinfo.value.message


def test_non_strict_mode_allows_missing_credentials() -> None:
    settings = McpSettings.from_env(require_credentials=False)
    assert settings.access_key == ""
    assert settings.read_only is False


def test_full_env_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUAWEICLOUD_ACCESS_KEY", "ak")
    monkeypatch.setenv("HUAWEICLOUD_SECRET_KEY", "sk")
    monkeypatch.setenv("HUAWEICLOUD_REGION", "cn-north-4")
    monkeypatch.setenv("HUAWEICLOUD_PROJECT_ID", "pid-1")
    monkeypatch.setenv("HUAWEICLOUD_SECURITY_TOKEN", "tok")
    monkeypatch.setenv("HUAWEICLOUD_MCP_READ_ONLY", "TRUE")
    monkeypatch.setenv("MCP_SERVER_PORT", "9001")
    monkeypatch.setenv("MCP_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("HUAWEICLOUD_MCP_PROTECTED_IDS", " a , b ,")
    monkeypatch.setenv("HUAWEICLOUD_MCP_PROTECTED_TAGS", "env=prod")
    settings = McpSettings.from_env()
    assert settings.access_key == "ak"
    assert settings.region == "cn-north-4"
    assert settings.project_id == "pid-1"
    assert settings.security_token == "tok"
    assert settings.read_only is True
    assert settings.server_port == 9001
    assert settings.server_host == "127.0.0.1"
    assert settings.protected_ids == ("a", "b")
    assert settings.protected_tags == ("env=prod",)


def test_bool_and_int_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUAWEICLOUD_ACCESS_KEY", "ak")
    monkeypatch.setenv("HUAWEICLOUD_SECRET_KEY", "sk")
    monkeypatch.setenv("HUAWEICLOUD_REGION", "r")
    monkeypatch.setenv("HUAWEICLOUD_MCP_READ_ONLY", "nope")
    with pytest.raises(McpToolError, match="boolean"):
        McpSettings.from_env()
    monkeypatch.setenv("HUAWEICLOUD_MCP_READ_ONLY", "false")
    monkeypatch.setenv("MCP_SERVER_PORT", "not-a-number")
    settings = McpSettings.from_env()
    assert settings.read_only is False
    assert settings.server_port == 8000
