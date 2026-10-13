"""Configuration source shared by all services, including credential hot reload."""

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import McpToolError


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise McpToolError("MCP_INVALID_ARGS", f"{name} must be true or false.")
    return value in {"true", "1", "yes"}


def _env_csv(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


def _read_secret_file(path: str) -> dict[str, Any]:
    try:
        with Path(path).expanduser().open("r", encoding="utf-8") as stream:
            mode = os.fstat(stream.fileno()).st_mode
            if not stat.S_ISREG(mode) or (os.name != "nt" and mode & 0o077):
                raise ValueError("file must be regular with mode 0600 or stricter")
            value = json.load(stream)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise McpToolError(
            "MCP_CREDENTIAL_ERROR",
            "The hot-reload credential file is unavailable or invalid.",
            hint=f"Atomically replace '{path}' with valid JSON and mode 0600 ({exc}).",
        ) from None
    if not isinstance(value, dict):
        raise McpToolError("MCP_CREDENTIAL_ERROR", "Credential file must be a JSON object.")
    return value


@dataclass(frozen=True)
class McpSettings:
    access_key: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)
    region: str = ""
    project_id: str | None = None
    domain_id: str | None = None
    security_token: str | None = field(default=None, repr=False)
    endpoint: str | None = None
    iam_endpoint: str = "https://iam.myhuaweicloud.com"
    read_only: bool = False
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    protected_ids: tuple[str, ...] = ()
    protected_names: tuple[str, ...] = ()
    protected_tags: tuple[str, ...] = ()
    guardrails_config_path: str | None = None
    audit_file: str | None = None
    credentials_file: str | None = None

    @classmethod
    def from_env(cls, *, require_credentials: bool = True) -> "McpSettings":
        credential_file = os.getenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE")
        secret = _read_secret_file(credential_file) if credential_file else {}

        def pick(file_key: str, env_key: str) -> str | None:
            value = secret.get(file_key) if credential_file else os.getenv(env_key)
            return str(value) if value not in (None, "") else None

        settings = cls(
            access_key=pick("access_key", "HUAWEICLOUD_ACCESS_KEY") or "",
            secret_key=pick("secret_key", "HUAWEICLOUD_SECRET_KEY") or "",
            region=pick("region", "HUAWEICLOUD_REGION") or "",
            project_id=pick("project_id", "HUAWEICLOUD_PROJECT_ID"),
            domain_id=pick("domain_id", "HUAWEICLOUD_DOMAIN_ID"),
            security_token=pick("security_token", "HUAWEICLOUD_SECURITY_TOKEN"),
            endpoint=os.getenv("HUAWEICLOUD_ENDPOINT"),
            iam_endpoint=os.getenv("HUAWEICLOUD_IAM_ENDPOINT", "https://iam.myhuaweicloud.com"),
            read_only=_env_bool("HUAWEICLOUD_MCP_READ_ONLY"),
            server_host=os.getenv("MCP_SERVER_HOST", "0.0.0.0"),
            server_port=int(os.getenv("MCP_SERVER_PORT", "8000")),
            protected_ids=_env_csv("HUAWEICLOUD_MCP_PROTECTED_IDS"),
            protected_names=_env_csv("HUAWEICLOUD_MCP_PROTECTED_NAMES"),
            protected_tags=_env_csv("HUAWEICLOUD_MCP_PROTECTED_TAGS"),
            guardrails_config_path=os.getenv("HUAWEICLOUD_MCP_GUARDRAILS_CONFIG"),
            audit_file=os.getenv("HUAWEICLOUD_MCP_AUDIT_FILE"),
            credentials_file=credential_file,
        )
        if not 1 <= settings.server_port <= 65535:
            raise McpToolError("MCP_INVALID_ARGS", "MCP_SERVER_PORT must be 1..65535.")
        if require_credentials:
            missing = [
                name
                for name, value in (
                    ("HUAWEICLOUD_ACCESS_KEY", settings.access_key),
                    ("HUAWEICLOUD_SECRET_KEY", settings.secret_key),
                    ("HUAWEICLOUD_REGION", settings.region),
                )
                if not value
            ]
            if missing:
                raise McpToolError(
                    "MCP_CREDENTIAL_ERROR",
                    f"Missing required configuration: {', '.join(missing)}.",
                    hint="Set the variables or HUAWEICLOUD_MCP_CREDENTIALS_FILE.",
                )
        return settings
