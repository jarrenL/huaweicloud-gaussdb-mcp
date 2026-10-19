"""Configuration source shared by all services, including credential hot reload."""

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import McpToolError

_DEFAULT_DEVKIT_CREDENTIALS_FILE = "~/.config/huaweicloud/credentials.json"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise McpToolError("MCP_INVALID_ARGS", f"{name} must be true or false.")
    return value in {"true", "1", "yes"}


def _env_csv(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


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

        def configured(env_key: str, file_key: str) -> str | None:
            return _value(os.getenv(env_key)) or _value(secret.get(file_key))

        configured_access_key = configured("HUAWEICLOUD_ACCESS_KEY", "access_key")
        configured_secret_key = configured("HUAWEICLOUD_SECRET_KEY", "secret_key")
        configured_region = configured("HUAWEICLOUD_REGION", "region")

        devkit: dict[str, Any] = {}
        skip_devkit = _env_bool("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS")
        needs_devkit = not all(
            (configured_access_key, configured_secret_key, configured_region)
        )
        if not skip_devkit and needs_devkit:
            configured_devkit_file = os.getenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE")
            devkit_file = configured_devkit_file or _DEFAULT_DEVKIT_CREDENTIALS_FILE
            expanded_devkit_file = Path(devkit_file).expanduser()
            if configured_devkit_file or expanded_devkit_file.exists():
                devkit = _read_devkit_file(devkit_file)

        def pick(env_key: str, file_key: str, devkit_key: str | None = None) -> str | None:
            return (
                _value(os.getenv(env_key))
                or _value(secret.get(file_key))
                or (_value(devkit.get(devkit_key)) if devkit_key else None)
            )

        settings = cls(
            access_key=pick("HUAWEICLOUD_ACCESS_KEY", "access_key", "ak") or "",
            secret_key=pick("HUAWEICLOUD_SECRET_KEY", "secret_key", "sk") or "",
            region=pick("HUAWEICLOUD_REGION", "region", "region") or "",
            project_id=pick("HUAWEICLOUD_PROJECT_ID", "project_id"),
            domain_id=pick("HUAWEICLOUD_DOMAIN_ID", "domain_id"),
            security_token=pick(
                "HUAWEICLOUD_SECURITY_TOKEN", "security_token", "securityToken"
            ),
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
                    hint=(
                        "Set the variables, HUAWEICLOUD_MCP_CREDENTIALS_FILE, or configure "
                        "huaweicloud-devkit credentials."
                    ),
                )
        return settings
