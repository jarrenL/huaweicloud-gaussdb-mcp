# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Server bootstrap: MCPServer construction with guardrails auto-installed."""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from huaweicloud_mcp_core.config import McpSettings
from huaweicloud_mcp_core.guardrails.audit import AuditLogger
from huaweicloud_mcp_core.guardrails.middleware import GuardrailsMiddleware
from huaweicloud_mcp_core.guardrails.rules import load_rules


def build_server(
    service_name: str,
    settings: McpSettings | None = None,
    *,
    version: str = "",
    instructions: str | None = None,
) -> MCPServer:
    """Create the MCPServer instance and auto-install the guardrails middleware."""
    resolved = settings or McpSettings.from_env(require_credentials=False)
    rules = load_rules(resolved)
    audit = AuditLogger(file_path=resolved.audit_file)
    middleware = GuardrailsMiddleware(
        read_only=resolved.read_only,
        rules=rules,
        audit=audit,
    )
    return MCPServer(
        f"huaweicloud-{service_name}",
        version=version,
        instructions=instructions,
        middleware=[middleware],
    )


def run_standard(server: MCPServer, service_name: str) -> None:
    """Unified entrypoint: parse -t/--transport and run the server."""
    parser = argparse.ArgumentParser(description=f"Run the huaweicloud-{service_name} MCP Server")
    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport protocol to use (default: stdio)",
    )
    args = parser.parse_args()
    if args.transport == "streamable-http":
        settings = McpSettings.from_env(require_credentials=False)
        server.run(
            transport="streamable-http",
            host=settings.server_host,
            port=settings.server_port,
        )
    else:
        server.run(transport=args.transport)
