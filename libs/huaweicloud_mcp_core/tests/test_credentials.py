# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Tests for credentials building and project_id resolution."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from huaweicloud_mcp_core.config import McpSettings
from huaweicloud_mcp_core.credentials import (
    CredentialScope,
    build_credentials,
    reset_project_cache,
    resolve_project_context,
    resolve_project_id,
)
from huaweicloud_mcp_core.errors import McpToolError


def _settings(**overrides: Any) -> McpSettings:
    values: dict[str, Any] = {
        "access_key": "AKTESTKEY000001",
        "secret_key": "sk" + "0" * 38,
        "region": "cn-north-4",
    }
    values.update(overrides)
    return McpSettings(**values)


class _FakeIamClient:
    instances: ClassVar[list[_FakeIamClient]] = []
    projects: ClassVar[list[Any]] = []
    error: ClassVar[Exception | None] = None

    def __init__(self) -> None:
        self.credentials: Any = None
        self.endpoint: str | None = None
        _FakeIamClient.instances.append(self)

    @classmethod
    def new_builder(cls) -> _FakeIamClient:
        return cls()

    def with_credentials(self, credentials: Any) -> _FakeIamClient:
        self.credentials = credentials
        return self

    def with_endpoint(self, endpoint: str) -> _FakeIamClient:
        self.endpoint = endpoint
        return self

    def build(self) -> _FakeIamClient:
        return self

    def keystone_list_projects(self, request: Any) -> Any:
        if _FakeIamClient.error:
            raise _FakeIamClient.error
        return SimpleNamespace(projects=list(_FakeIamClient.projects))


@pytest.fixture(autouse=True)
def _reset_iam_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeIamClient.instances.clear()
    _FakeIamClient.projects = []
    _FakeIamClient.error = None
    reset_project_cache()
    monkeypatch.setattr("huaweicloudsdkiam.v3.IamClient", _FakeIamClient)


def test_explicit_project_id_short_circuits() -> None:
    assert resolve_project_id(_settings(project_id="pid-explicit")) == "pid-explicit"
    assert _FakeIamClient.instances == []


def test_project_id_resolved_via_iam_and_cached() -> None:
    _FakeIamClient.projects = [SimpleNamespace(id="pid-iam")]
    assert resolve_project_id(_settings()) == "pid-iam"
    assert len(_FakeIamClient.instances) == 1
    assert _FakeIamClient.instances[0].endpoint == "https://iam.myhuaweicloud.com"
    assert resolve_project_id(_settings()) == "pid-iam"
    assert len(_FakeIamClient.instances) == 1


def test_missing_project_raises_with_hint() -> None:
    _FakeIamClient.projects = []
    with pytest.raises(McpToolError) as excinfo:
        resolve_project_id(_settings())
    assert excinfo.value.code == "MCP_PROJECT_NOT_FOUND"
    assert "HUAWEICLOUD_PROJECT_ID" in (excinfo.value.hint or "")


def test_iam_failure_wrapped_with_hint() -> None:
    _FakeIamClient.error = RuntimeError("network down")
    with pytest.raises(McpToolError) as excinfo:
        resolve_project_id(_settings())
    assert "project_id" in excinfo.value.message
    assert "HUAWEICLOUD_PROJECT_ID" in (excinfo.value.hint or "")


def test_build_credentials_project_scope() -> None:
    _FakeIamClient.projects = [SimpleNamespace(id="pid-iam")]
    credentials = build_credentials(CredentialScope.PROJECT, _settings())
    assert credentials.ak == "AKTESTKEY000001"
    assert credentials.project_id == "pid-iam"


def test_build_credentials_global_scope_skips_project() -> None:
    credentials = build_credentials(CredentialScope.GLOBAL, _settings())
    assert credentials.ak == "AKTESTKEY000001"
    assert _FakeIamClient.instances == []


def test_build_credentials_with_security_token() -> None:
    _FakeIamClient.projects = [SimpleNamespace(id="pid-iam")]
    credentials = build_credentials(CredentialScope.PROJECT, _settings(security_token="tok-1"))
    assert credentials.security_token == "tok-1"


def test_project_context_includes_domain_and_is_account_scoped() -> None:
    _FakeIamClient.projects = [SimpleNamespace(id="pid-a", domain_id="domain-a")]
    first = resolve_project_context(_settings(access_key="account-a"))
    assert (first.project_id, first.domain_id) == ("pid-a", "domain-a")
    _FakeIamClient.projects = [SimpleNamespace(id="pid-b", domain_id="domain-b")]
    second = resolve_project_context(_settings(access_key="account-b"))
    assert (second.project_id, second.domain_id) == ("pid-b", "domain-b")
    assert len(_FakeIamClient.instances) == 2


def test_explicit_context_skips_iam_and_global_credentials_keep_domain() -> None:
    settings = _settings(project_id="pid", domain_id="domain")
    assert resolve_project_context(settings).domain_id == "domain"
    assert _FakeIamClient.instances == []
    credentials = build_credentials(CredentialScope.GLOBAL, settings)
    assert credentials.domain_id == "domain"


def test_explicit_project_filters_context_lookup() -> None:
    _FakeIamClient.projects = [
        SimpleNamespace(id="other", domain_id="wrong"),
        SimpleNamespace(id="selected", domain_id="right"),
    ]
    result = resolve_project_context(_settings(project_id="selected"))
    assert (result.project_id, result.domain_id) == ("selected", "right")
