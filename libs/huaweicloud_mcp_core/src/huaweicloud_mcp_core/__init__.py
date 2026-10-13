"""Stable public API shared by Huawei Cloud MCP servers."""

from .config import McpSettings
from .credentials import (
    CredentialScope,
    ProjectContext,
    build_credentials,
    resolve_project_context,
    resolve_project_id,
)
from .errors import McpToolError, wrap_sdk_error
from .output import clamp_limit, page_result, single_result
from .security import ToolRisk, guard
from .server import build_server, run_standard

__all__ = [
    "CredentialScope",
    "McpSettings",
    "McpToolError",
    "ProjectContext",
    "ToolRisk",
    "build_credentials",
    "build_server",
    "clamp_limit",
    "guard",
    "page_result",
    "resolve_project_context",
    "resolve_project_id",
    "run_standard",
    "single_result",
    "wrap_sdk_error",
]
