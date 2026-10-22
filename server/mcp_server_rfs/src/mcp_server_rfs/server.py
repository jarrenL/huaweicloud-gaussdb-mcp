# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""FastMCP instance construction for the RFS server (guardrails auto-installed)."""

from huaweicloud_mcp_core.server import build_server
from starlette.requests import Request
from starlette.responses import JSONResponse

mcp = build_server("rfs")


@mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]  # MCP SDK decorator.
async def health_check(_request: Request) -> JSONResponse:
    """Lightweight liveness probe used by the MCP client/agent.

    The standard MCP protocol runs on /mcp; clients that probe /health
    otherwise get a 404. This returns 200 {"status":"ok","service":"rfs"} so
    the agent's readiness check passes.
    """
    return JSONResponse({"status": "ok", "service": "rfs"})


from mcp_server_rfs.tools import stack  # noqa: E402,F401
