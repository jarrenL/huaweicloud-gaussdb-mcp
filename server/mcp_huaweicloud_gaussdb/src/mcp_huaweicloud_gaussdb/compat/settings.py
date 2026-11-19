# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""GaussDB settings for credential sources and transport options absent in core 1.0."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from huaweicloud_mcp_core.config import McpSettings as CoreSettings
from huaweicloud_mcp_core.errors import McpToolError

from .credential_sources import config_value, read_credential_files, read_env_identity

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value not in _TRUE_VALUES | {"0", "false", "no", "off"}:
        raise McpToolError("MCP_CONFIG_ERROR", f"{name} must be a boolean.")
    return value in _TRUE_VALUES


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _selected_identity(
    env: dict[str, str | None], secret: dict[str, Any], devkit: dict[str, Any]
) -> dict[str, Any]:
    if any(env.values()):
        return env
    if any(secret.get(key) for key in env):
        return secret
    return {
        "access_key": devkit.get("ak"),
        "secret_key": devkit.get("sk"),
        "security_token": devkit.get("securityToken"),
    }


def _require_credential_fields(
    access_key: str, secret_key: str, region: str, *, require_credentials: bool
) -> None:
    if not require_credentials:
        return
    missing = [
        name
        for name, value in (
            ("HUAWEICLOUD_ACCESS_KEY", access_key),
            ("HUAWEICLOUD_SECRET_KEY", secret_key),
            ("HUAWEICLOUD_REGION", region),
        )
        if not value
    ]
    if missing:
        raise McpToolError(
            code="MCP_CREDENTIAL_ERROR",
            message=f"Missing required environment variables: {', '.join(missing)}.",
            hint=(
                "Export HUAWEICLOUD_ACCESS_KEY, HUAWEICLOUD_SECRET_KEY and "
                "HUAWEICLOUD_REGION, set HUAWEICLOUD_MCP_CREDENTIALS_FILE, or configure "
                "huaweicloud-devkit credentials (see the Configuration section)."
            ),
        )


@dataclass(frozen=True)
class McpSettings(CoreSettings):
    """Immutable GaussDB settings compatible with the core guardrails loader."""

    access_key: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)
    security_token: str | None = field(default=None, repr=False)
    server_host: str = "127.0.0.1"

    domain_id: str | None = None
    iam_endpoint: str = "https://iam.myhuaweicloud.com"
    credentials_file: str | None = None
    http_token: str | None = field(default=None, repr=False)
    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, *, require_credentials: bool = True) -> McpSettings:
        env_credentials = read_env_identity()
        env_region = config_value(os.getenv("HUAWEICLOUD_REGION"))
        secret, devkit = read_credential_files(
            env_auth=any(env_credentials.values()), env_region=env_region
        )
        source = _selected_identity(env_credentials, secret, devkit)
        access_key = config_value(source.get("access_key")) or ""
        secret_key = config_value(source.get("secret_key")) or ""
        if any(source.values()) and not (access_key and secret_key):
            raise McpToolError(
                "MCP_CREDENTIAL_ERROR",
                "The selected credential source must supply both AK and SK.",
                hint=(
                    "Configure AK/SK and optional STS token together in one source; "
                    "sources are never mixed."
                ),
            )
        region = (
            env_region
            or config_value(secret.get("region"))
            or config_value(devkit.get("region"))
            or ""
        )
        _require_credential_fields(
            access_key, secret_key, region, require_credentials=require_credentials
        )
        return cls(
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            project_id=config_value(os.getenv("HUAWEICLOUD_PROJECT_ID"))
            or (config_value(secret.get("project_id")) if source is secret else None),
            security_token=config_value(source.get("security_token")),
            endpoint=os.getenv("HUAWEICLOUD_ENDPOINT") or None,
            read_only=_env_bool("HUAWEICLOUD_MCP_READ_ONLY"),
            server_host=os.getenv("MCP_SERVER_HOST", "127.0.0.1"),
            server_port=_env_int("MCP_SERVER_PORT", 8000),
            protected_ids=_env_csv("HUAWEICLOUD_MCP_PROTECTED_IDS"),
            protected_names=_env_csv("HUAWEICLOUD_MCP_PROTECTED_NAMES"),
            protected_tags=_env_csv("HUAWEICLOUD_MCP_PROTECTED_TAGS"),
            guardrails_config_path=os.getenv("HUAWEICLOUD_MCP_GUARDRAILS_CONFIG") or None,
            audit_file=os.getenv("HUAWEICLOUD_MCP_AUDIT_FILE") or None,
            domain_id=config_value(os.getenv("HUAWEICLOUD_DOMAIN_ID"))
            or (config_value(secret.get("domain_id")) if source is secret else None),
            iam_endpoint=os.getenv("HUAWEICLOUD_IAM_ENDPOINT", "https://iam.myhuaweicloud.com"),
            credentials_file=os.getenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE") or None,
            http_token=config_value(os.getenv("HUAWEICLOUD_MCP_HTTP_TOKEN")),
            allowed_hosts=_env_csv("MCP_SERVER_ALLOWED_HOSTS"),
            allowed_origins=_env_csv("MCP_SERVER_ALLOWED_ORIGINS"),
        )
