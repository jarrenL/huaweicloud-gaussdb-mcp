# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Environment-based configuration for Huawei Cloud MCP servers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from huaweicloud_mcp_core.credential_sources import _value, read_credential_sources
from huaweicloud_mcp_core.errors import McpToolError

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


@dataclass(frozen=True)
class McpSettings:
    """Immutable snapshot of all environment configuration."""

    access_key: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)
    region: str = ""
    project_id: str | None = None
    security_token: str | None = field(default=None, repr=False)
    endpoint: str | None = None
    read_only: bool = False
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    protected_ids: tuple[str, ...] = ()
    protected_names: tuple[str, ...] = ()
    protected_tags: tuple[str, ...] = ()
    guardrails_config_path: str | None = None
    audit_file: str | None = None

    domain_id: str | None = None
    iam_endpoint: str = "https://iam.myhuaweicloud.com"
    credentials_file: str | None = None
    http_token: str | None = field(default=None, repr=False)
    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, *, require_credentials: bool = True) -> McpSettings:
        secret, devkit = read_credential_sources()

        def pick(env_key: str, file_key: str, devkit_key: str | None = None) -> str | None:
            return (
                _value(os.getenv(env_key))
                or _value(secret.get(file_key))
                or (_value(devkit.get(devkit_key)) if devkit_key else None)
            )

        env_credentials = {
            "access_key": _value(os.getenv("HUAWEICLOUD_ACCESS_KEY")),
            "secret_key": _value(os.getenv("HUAWEICLOUD_SECRET_KEY")),
            "security_token": _value(os.getenv("HUAWEICLOUD_SECURITY_TOKEN")),
        }
        source = (
            env_credentials
            if any(env_credentials.values())
            else secret
            if any(secret.get(key) for key in ("access_key", "secret_key", "security_token"))
            else {
                "access_key": devkit.get("ak"),
                "secret_key": devkit.get("sk"),
                "security_token": devkit.get("securityToken"),
            }
        )
        access_key = _value(source.get("access_key")) or ""
        secret_key = _value(source.get("secret_key")) or ""
        if any(source.values()) and not (access_key and secret_key):
            raise McpToolError(
                "MCP_CREDENTIAL_ERROR",
                "The selected credential source must supply both AK and SK.",
                hint=(
                    "Configure AK/SK and optional STS token together in one source; "
                    "sources are never mixed."
                ),
            )
        region = pick("HUAWEICLOUD_REGION", "region", "region") or ""
        missing = [
            name
            for name, value in (
                ("HUAWEICLOUD_ACCESS_KEY", access_key),
                ("HUAWEICLOUD_SECRET_KEY", secret_key),
                ("HUAWEICLOUD_REGION", region),
            )
            if not value
        ]
        if missing and require_credentials:
            raise McpToolError(
                code="MCP_CREDENTIAL_ERROR",
                message=f"Missing required environment variables: {', '.join(missing)}.",
                hint=(
                    "Export HUAWEICLOUD_ACCESS_KEY, HUAWEICLOUD_SECRET_KEY and "
                    "HUAWEICLOUD_REGION, set HUAWEICLOUD_MCP_CREDENTIALS_FILE, or configure "
                    "huaweicloud-devkit credentials (see the Configuration section)."
                ),
            )
        return cls(
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            project_id=_value(os.getenv("HUAWEICLOUD_PROJECT_ID"))
            or (_value(secret.get("project_id")) if source is secret else None),
            security_token=_value(source.get("security_token")),
            endpoint=os.getenv("HUAWEICLOUD_ENDPOINT") or None,
            read_only=_env_bool("HUAWEICLOUD_MCP_READ_ONLY"),
            server_host=os.getenv("MCP_SERVER_HOST", "127.0.0.1"),
            server_port=_env_int("MCP_SERVER_PORT", 8000),
            protected_ids=_env_csv("HUAWEICLOUD_MCP_PROTECTED_IDS"),
            protected_names=_env_csv("HUAWEICLOUD_MCP_PROTECTED_NAMES"),
            protected_tags=_env_csv("HUAWEICLOUD_MCP_PROTECTED_TAGS"),
            guardrails_config_path=os.getenv("HUAWEICLOUD_MCP_GUARDRAILS_CONFIG") or None,
            audit_file=os.getenv("HUAWEICLOUD_MCP_AUDIT_FILE") or None,
            domain_id=_value(os.getenv("HUAWEICLOUD_DOMAIN_ID"))
            or (_value(secret.get("domain_id")) if source is secret else None),
            iam_endpoint=os.getenv("HUAWEICLOUD_IAM_ENDPOINT", "https://iam.myhuaweicloud.com"),
            credentials_file=os.getenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE") or None,
            http_token=_value(os.getenv("HUAWEICLOUD_MCP_HTTP_TOKEN")),
            allowed_hosts=_env_csv("MCP_SERVER_ALLOWED_HOSTS"),
            allowed_origins=_env_csv("MCP_SERVER_ALLOWED_ORIGINS"),
        )
