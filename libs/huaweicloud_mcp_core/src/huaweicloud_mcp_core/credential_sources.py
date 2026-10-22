# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Read shared credential sources without keeping secret values cached."""

import json
import os
import stat
from pathlib import Path
from typing import Any

from huaweicloud_mcp_core.errors import McpToolError

_DEFAULT_DEVKIT_CREDENTIALS_FILE = "~/.config/huaweicloud/credentials.json"


def _read_json_object(
    path: str,
    *,
    source_name: str,
    require_private_permissions: bool,
) -> dict[str, Any]:
    try:
        with Path(path).expanduser().open("r", encoding="utf-8") as stream:
            mode = os.fstat(stream.fileno()).st_mode
            if not stat.S_ISREG(mode):
                raise ValueError("file must be regular")
            if require_private_permissions and os.name != "nt" and mode & 0o077:
                raise ValueError("file must be regular with mode 0600 or stricter")
            value = json.load(stream)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        permission_hint = (
            " and mode 0600" if require_private_permissions and os.name != "nt" else ""
        )
        raise McpToolError(
            "MCP_CREDENTIAL_ERROR",
            f"The {source_name} credential file is unavailable or invalid.",
            hint=f"Provide a regular JSON object at '{path}'{permission_hint} ({exc}).",
        ) from None
    if not isinstance(value, dict):
        raise McpToolError(
            "MCP_CREDENTIAL_ERROR", f"The {source_name} credential file must be a JSON object."
        )
    return value


def _read_secret_file(path: str) -> dict[str, Any]:
    return _read_json_object(
        path,
        source_name="MCP",
        require_private_permissions=True,
    )


def _read_devkit_file(path: str) -> dict[str, Any]:
    return _read_json_object(
        path,
        source_name="huaweicloud-devkit",
        require_private_permissions=False,
    )


def _value(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def read_credential_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the MCP file and optional devkit S1 fallback for this settings snapshot."""
    credential_file = os.getenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE")
    secret = _read_secret_file(credential_file) if credential_file else {}
    configured = (
        _value(os.getenv(env_key)) or _value(secret.get(file_key))
        for env_key, file_key in (
            ("HUAWEICLOUD_ACCESS_KEY", "access_key"),
            ("HUAWEICLOUD_SECRET_KEY", "secret_key"),
            ("HUAWEICLOUD_REGION", "region"),
        )
    )
    skip = os.getenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "").strip().lower()
    devkit: dict[str, Any] = {}
    if skip not in {"1", "true", "yes", "on"} and not all(configured):
        explicit_path = os.getenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE")
        path = explicit_path or _DEFAULT_DEVKIT_CREDENTIALS_FILE
        if explicit_path or Path(path).expanduser().exists():
            devkit = _read_devkit_file(path)
    return secret, devkit
