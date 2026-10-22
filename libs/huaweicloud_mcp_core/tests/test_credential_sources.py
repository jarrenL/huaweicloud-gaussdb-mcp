# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Regression checks for shared credentials, hot reload, and source permissions."""

import json
import os
from pathlib import Path

import pytest

from huaweicloud_mcp_core import McpSettings, McpToolError


def _write(path: Path, value: object, mode: int = 0o600) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(mode)


def test_devkit_mapping_and_hot_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "credentials.json"
    _write(
        path, {"ak": "account-a", "sk": "secret-a", "securityToken": "sts", "region": "r1"}, 0o644
    )
    monkeypatch.setenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "0")
    monkeypatch.setenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE", str(path))
    first = McpSettings.from_env()
    assert (first.access_key, first.secret_key, first.security_token, first.region) == (
        "account-a",
        "secret-a",
        "sts",
        "r1",
    )
    assert first.project_id is None and first.domain_id is None
    assert "secret-a" not in repr(first)
    _write(path, {"ak": "account-b", "sk": "secret-b", "region": "r2"}, 0o644)
    second = McpSettings.from_env()
    assert (second.access_key, second.secret_key, second.region) == (
        "account-b",
        "secret-b",
        "r2",
    )


def test_default_devkit_location(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".config/huaweicloud/credentials.json"
    path.parent.mkdir(parents=True)
    _write(path, {"ak": "a", "sk": "s", "region": "r"}, 0o644)
    monkeypatch.setattr(
        Path,
        "expanduser",
        lambda self: tmp_path / str(self)[2:] if str(self).startswith("~/") else self,
    )
    monkeypatch.setenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "0")
    assert McpSettings.from_env().region == "r"


def test_source_precedence_and_file_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    devkit = tmp_path / "s1.json"
    mcp = tmp_path / "mcp.json"
    _write(devkit, {"ak": "devkit-a", "sk": "devkit-s", "region": "devkit-r"})
    _write(mcp, {"access_key": "file-a", "project_id": "pid", "domain_id": "did"})
    monkeypatch.setenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "0")
    monkeypatch.setenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE", str(devkit))
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(mcp))
    monkeypatch.setenv("HUAWEICLOUD_ACCESS_KEY", "env-a")
    settings = McpSettings.from_env()
    assert (settings.access_key, settings.secret_key, settings.region) == (
        "env-a",
        "devkit-s",
        "devkit-r",
    )
    assert (settings.project_id, settings.domain_id) == ("pid", "did")
    _write(mcp, {"access_key": "file-b", "secret_key": "file-s", "region": "file-r"})
    monkeypatch.delenv("HUAWEICLOUD_ACCESS_KEY")
    settings = McpSettings.from_env()
    assert (settings.access_key, settings.secret_key, settings.region) == (
        "file-b",
        "file-s",
        "file-r",
    )


def test_skip_and_explicit_env_do_not_read_devkit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE", str(tmp_path / "absent.json"))
    with pytest.raises(McpToolError, match="Missing"):
        McpSettings.from_env()
    monkeypatch.setenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "0")
    for key, value in (("ACCESS_KEY", "a"), ("SECRET_KEY", "s"), ("REGION", "r")):
        monkeypatch.setenv(f"HUAWEICLOUD_{key}", value)
    assert McpSettings.from_env().access_key == "a"


@pytest.mark.parametrize("value", [[], None, "text"])
def test_non_object_credential_files_fail_closed(
    value: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "credentials.json"
    _write(path, value)
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(path))
    with pytest.raises(McpToolError) as excinfo:
        McpSettings.from_env(require_credentials=False)
    assert excinfo.value.code == "MCP_CREDENTIAL_ERROR"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_mcp_file_still_requires_private_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "credentials.json"
    _write(path, {"access_key": "a", "secret_key": "s", "region": "r"}, 0o644)
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(path))
    with pytest.raises(McpToolError) as excinfo:
        McpSettings.from_env()
    assert "0600" in (excinfo.value.hint or "")


def test_malformed_devkit_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "credentials.json"
    path.write_text("{", encoding="utf-8")
    monkeypatch.setenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "0")
    monkeypatch.setenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE", str(path))
    with pytest.raises(McpToolError) as excinfo:
        McpSettings.from_env()
    assert excinfo.value.code == "MCP_CREDENTIAL_ERROR"
