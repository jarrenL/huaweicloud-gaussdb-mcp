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
    return raw.strip().lower() in _TRUE_VALUES


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
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    protected_ids: tuple[str, ...] = ()
    protected_names: tuple[str, ...] = ()
    protected_tags: tuple[str, ...] = ()
    guardrails_config_path: str | None = None
    audit_file: str | None = None

    domain_id: str | None = None
    iam_endpoint: str = "https://iam.myhuaweicloud.com"
    credentials_file: str | None = None

    @classmethod
    def from_env(cls, *, require_credentials: bool = True) -> McpSettings:
        secret, devkit = read_credential_sources()

        def pick(env_key: str, file_key: str, devkit_key: str | None = None) -> str | None:
            return (
                _value(os.getenv(env_key))
                or _value(secret.get(file_key))
                or (_value(devkit.get(devkit_key)) if devkit_key else None)
            )

        access_key = pick("HUAWEICLOUD_ACCESS_KEY", "access_key", "ak") or ""
        secret_key = pick("HUAWEICLOUD_SECRET_KEY", "secret_key", "sk") or ""
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
            project_id=pick("HUAWEICLOUD_PROJECT_ID", "project_id"),
            security_token=pick("HUAWEICLOUD_SECURITY_TOKEN", "security_token", "securityToken"),
            endpoint=os.getenv("HUAWEICLOUD_ENDPOINT") or None,
            read_only=_env_bool("HUAWEICLOUD_MCP_READ_ONLY"),
            server_host=os.getenv("MCP_SERVER_HOST", "0.0.0.0"),
            server_port=_env_int("MCP_SERVER_PORT", 8000),
            protected_ids=_env_csv("HUAWEICLOUD_MCP_PROTECTED_IDS"),
            protected_names=_env_csv("HUAWEICLOUD_MCP_PROTECTED_NAMES"),
            protected_tags=_env_csv("HUAWEICLOUD_MCP_PROTECTED_TAGS"),
            guardrails_config_path=os.getenv("HUAWEICLOUD_MCP_GUARDRAILS_CONFIG") or None,
            audit_file=os.getenv("HUAWEICLOUD_MCP_AUDIT_FILE") or None,
            domain_id=pick("HUAWEICLOUD_DOMAIN_ID", "domain_id"),
            iam_endpoint=os.getenv("HUAWEICLOUD_IAM_ENDPOINT", "https://iam.myhuaweicloud.com"),
            credentials_file=os.getenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE") or None,
        )
