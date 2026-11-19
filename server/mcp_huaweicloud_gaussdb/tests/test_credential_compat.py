# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Regression tests for GaussDB credential behavior on core 1.0."""

import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from huaweicloud_mcp_core import McpToolError
from huaweicloud_mcp_core.credentials import CredentialScope
from huaweicloudsdkcore.auth.credentials import BasicCredentials, GlobalCredentials

from mcp_huaweicloud_gaussdb.compat.credentials import (
    build_credentials,
    reset_project_cache,
    resolve_project_context,
)
from mcp_huaweicloud_gaussdb.compat.settings import McpSettings


def _write(path: Path, value: object, mode: int = 0o600) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(mode)


def test_devkit_fallback_reloads_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "devkit.json"
    _write(
        path,
        {"ak": "team-ak-a", "sk": "team-sk-a", "securityToken": "team-token", "region": "r1"},
        0o644,
    )
    monkeypatch.setenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "0")
    monkeypatch.setenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE", str(path))
    first = McpSettings.from_env()
    assert (first.access_key, first.secret_key, first.security_token, first.region) == (
        "team-ak-a",
        "team-sk-a",
        "team-token",
        "r1",
    )
    assert all(secret not in repr(first) for secret in ("team-ak-a", "team-sk-a", "team-token"))
    _write(path, {"ak": "team-ak-b", "sk": "team-sk-b", "region": "r2"}, 0o644)
    second = McpSettings.from_env()
    assert (second.access_key, second.secret_key, second.security_token, second.region) == (
        "team-ak-b",
        "team-sk-b",
        None,
        "r2",
    )
    assert second.project_id is None and second.domain_id is None


def test_env_identity_does_not_inherit_file_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mcp.json"
    _write(
        path,
        {
            "access_key": "file-ak",
            "secret_key": "file-sk",
            "security_token": "file-token",
            "region": "r1",
            "project_id": "file-project",
            "domain_id": "file-domain",
        },
    )
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(path))
    file_settings = McpSettings.from_env()
    assert (file_settings.access_key, file_settings.secret_key) == ("file-ak", "file-sk")
    assert (file_settings.project_id, file_settings.domain_id) == ("file-project", "file-domain")

    monkeypatch.setenv("HUAWEICLOUD_ACCESS_KEY", "env-ak")
    with pytest.raises(McpToolError, match="both AK and SK"):
        McpSettings.from_env()
    monkeypatch.setenv("HUAWEICLOUD_SECRET_KEY", "env-sk")
    settings = McpSettings.from_env()
    assert (settings.access_key, settings.secret_key, settings.region) == ("env-ak", "env-sk", "r1")
    assert settings.security_token is None
    assert settings.project_id is None and settings.domain_id is None

    monkeypatch.setenv("HUAWEICLOUD_REGION", "r2")
    path.unlink()
    assert McpSettings.from_env().region == "r2"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_mcp_file_requires_private_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "mcp.json"
    _write(path, {"access_key": "file-ak", "secret_key": "file-sk", "region": "r1"}, 0o644)
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(path))
    with pytest.raises(McpToolError, match="unavailable or invalid") as excinfo:
        McpSettings.from_env()
    assert "0600" in (excinfo.value.hint or "")


def test_invalid_credential_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mcp.json"
    _write(path, [])
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(path))
    with pytest.raises(McpToolError, match="JSON object") as excinfo:
        McpSettings.from_env(require_credentials=False)
    assert excinfo.value.code == "MCP_CREDENTIAL_ERROR"


def test_read_only_env_validation_during_credential_free_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HUAWEICLOUD_MCP_READ_ONLY", "on")
    monkeypatch.setenv("MCP_SERVER_PORT", "9000")
    settings = McpSettings.from_env(require_credentials=False)
    assert settings.read_only and settings.server_port == 9000
    with pytest.raises(McpToolError, match="Missing required environment variables") as excinfo:
        McpSettings.from_env()
    assert excinfo.value.code == "MCP_CREDENTIAL_ERROR"

    monkeypatch.setenv("HUAWEICLOUD_MCP_READ_ONLY", "invalid")
    with pytest.raises(McpToolError, match="must be a boolean") as excinfo:
        McpSettings.from_env(require_credentials=False)
    assert excinfo.value.code == "MCP_CONFIG_ERROR"


@pytest.fixture
def iam(monkeypatch: pytest.MonkeyPatch) -> Mock:
    reset_project_cache()
    builder = Mock()
    builder.with_credentials.return_value = builder
    builder.with_endpoint.return_value = builder
    builder.with_http_config.return_value = builder
    builder.build.return_value = builder
    monkeypatch.setattr("huaweicloudsdkiam.v3.IamClient.new_builder", lambda: builder)
    return builder


def test_iam_cache_is_account_scoped_and_retains_domain(iam: Mock) -> None:
    iam.keystone_list_projects.side_effect = [
        SimpleNamespace(projects=[SimpleNamespace(id="project-a", domain_id="domain-a")]),
        SimpleNamespace(projects=[SimpleNamespace(id="project-b", domain_id="domain-b")]),
    ]
    first = McpSettings(
        access_key="team-ak-a",
        secret_key="team-sk-a",
        security_token="team-token-a",
        region="cn-north-4",
        iam_endpoint="https://iam.example.invalid",
    )
    second = replace(first, access_key="team-ak-b", secret_key="team-sk-b")
    assert resolve_project_context(first).domain_id == "domain-a"
    credentials = build_credentials(CredentialScope.PROJECT, second)
    assert isinstance(credentials, BasicCredentials)
    assert credentials.project_id == "project-b"
    assert credentials.security_token == "team-token-a"
    assert resolve_project_context(second).domain_id == "domain-b"
    assert iam.keystone_list_projects.call_count == 2
    assert iam.keystone_list_projects.call_args.args[0].name == "cn-north-4"
    iam.with_endpoint.assert_called_with("https://iam.example.invalid")


def test_explicit_project_and_global_domain_do_not_require_iam(iam: Mock) -> None:
    settings = McpSettings(
        access_key="team-ak",
        secret_key="team-sk",
        security_token="team-token",
        region="cn-north-4",
        project_id="project",
        domain_id="domain",
    )
    assert resolve_project_context(settings).domain_id == "domain"
    project_credentials = build_credentials(CredentialScope.PROJECT, settings)
    assert isinstance(project_credentials, BasicCredentials)
    assert project_credentials.project_id == "project"
    global_credentials = build_credentials(CredentialScope.GLOBAL, settings)
    assert isinstance(global_credentials, GlobalCredentials)
    assert global_credentials.domain_id == "domain"
    assert global_credentials.security_token == "team-token"
    iam.keystone_list_projects.assert_not_called()


def test_iam_error_keeps_manual_project_id_hint(iam: Mock) -> None:
    iam.keystone_list_projects.side_effect = RuntimeError("network disconnected")
    settings = McpSettings(access_key="team-ak", secret_key="team-sk", region="cn-north-4")
    with pytest.raises(McpToolError, match="via IAM") as excinfo:
        resolve_project_context(settings)
    assert "HUAWEICLOUD_PROJECT_ID" in (excinfo.value.hint or "")

    iam.keystone_list_projects.side_effect = None
    iam.keystone_list_projects.return_value = SimpleNamespace(projects=[])
    with pytest.raises(McpToolError) as excinfo:
        resolve_project_context(settings)
    assert excinfo.value.code == "MCP_PROJECT_NOT_FOUND"
