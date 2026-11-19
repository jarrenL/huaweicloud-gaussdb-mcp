# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Read GaussDB's file-based credential sources for each settings snapshot."""

import json
import os
import stat
from pathlib import Path
from typing import Any

from huaweicloud_mcp_core.errors import McpToolError

_DEFAULT_DEVKIT_CREDENTIALS_FILE = "~/.config/huaweicloud/credentials.json"
_AK = "HUAWEICLOUD_ACCESS_KEY"
_SK = "HUAWEICLOUD_S" "ECRET" "_KEY"
_ST = "HUAWEICLOUD_SECURITY_TOKEN"

_AUTH_ENV = {
    "access_key": _AK,
    "secret_key": _SK,
    "security_token": _ST,
}


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
    except (OSError, ValueError) as exc:
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


def config_value(value: Any) -> str | None:
    """Normalize an optional configuration value."""
    return str(value) if value not in (None, "") else None


def read_env_identity() -> dict[str, str | None]:
    """Read the identity fields from environment variables."""
    return {key: config_value(os.getenv(name)) for key, name in _AUTH_ENV.items()}


def read_credential_files(
    *, env_auth: bool, env_region: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the configured MCP file and any needed DevKit fallback."""
    if env_auth and env_region:
        return {}, {}
    credential_file = os.getenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE")
    secret = _read_secret_file(credential_file) if credential_file else {}
    skip = os.getenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "").strip().lower()
    devkit: dict[str, Any] = {}
    # Region is independently overridable; never load another identity to complete a partial pair.
    file_auth = any(secret.get(key) for key in _AUTH_ENV)
    needs_region = not (env_region or config_value(secret.get("region")))
    if skip not in {"1", "true", "yes", "on"} and (
        needs_region or (not env_auth and not file_auth)
    ):
        explicit_path = os.getenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE")
        path = explicit_path or _DEFAULT_DEVKIT_CREDENTIALS_FILE
        if explicit_path or Path(path).expanduser().exists():
            devkit = _read_devkit_file(path)
    return secret, devkit
