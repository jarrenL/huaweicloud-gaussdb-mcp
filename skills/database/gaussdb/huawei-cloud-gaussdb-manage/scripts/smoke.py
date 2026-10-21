#!/usr/bin/env python3
"""Run a read-only stdio smoke test against the GaussDB MCP server.

The script initializes the server, checks its core tool inventory, calls
``list_instances(limit=1)``, and proves that read-only mode blocks a write tool.
It prints only counts and status values, never resource records or credentials.

Examples:
    uv run python scripts/smoke.py -- \
        uv run --directory /path/to/huaweicloud-gaussdb-mcp \
        mcp-server-huaweicloud-gaussdb

    uv run --with 'mcp>=1,<3' python scripts/smoke.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MINIMUM_TOOLS = {
    "list_instances",
    "get_instance",
    "discover_create_options",
    "get_instance_parameters",
    "get_job",
    "wait_job",
    "list_openapi_operations",
    "describe_openapi_operation",
    "invoke_dangerous_openapi",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify GaussDB MCP registration, credentials, and read-only guardrails."
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Overall timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--skip-cloud",
        action="store_true",
        help="Only initialize and list tools; skip credential-backed list_instances.",
    )
    parser.add_argument(
        "server",
        nargs=argparse.REMAINDER,
        help=(
            "Server command after '--'. Defaults to "
            "'uvx mcp-server-huaweicloud-gaussdb'."
        ),
    )
    return parser


def _server_command(values: Sequence[str]) -> tuple[str, list[str]]:
    command = list(values)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        return "uvx", ["mcp-server-huaweicloud-gaussdb"]
    return command[0], command[1:]


def _structured(result: Any) -> dict[str, Any]:
    value = getattr(result, "structuredContent", None)
    if isinstance(value, dict):
        return value
    value = getattr(result, "structured_content", None)
    return value if isinstance(value, dict) else {}


def _error_code(result: Any) -> str | None:
    payload = _structured(result)
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"]
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", "")
        if not isinstance(text, str):
            continue
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            if "MCP_READ_ONLY" in text:
                return "MCP_READ_ONLY"
            continue
        error = decoded.get("error") if isinstance(decoded, dict) else None
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            return error["code"]
    return None


def _payloads(result: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    structured = _structured(result)
    if structured:
        payloads.append(structured)
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", "")
        if not isinstance(text, str):
            continue
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            payloads.append(decoded)
    return payloads


def _find_items(value: Any) -> list[Any] | None:
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return items
        for child in value.values():
            if (found := _find_items(child)) is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            if (found := _find_items(child)) is not None:
                return found
    return None


def _item_count(result: Any) -> int | None:
    for payload in _payloads(result):
        if (items := _find_items(payload)) is not None:
            return len(items)
    return None


async def _smoke(command: str, args: list[str], skip_cloud: bool) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["HUAWEICLOUD_MCP_READ_ONLY"] = "true"
    parameters = StdioServerParameters(command=command, args=args, env=environment)
    failure: str | None = None
    summary: dict[str, Any] | None = None

    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        listed = await session.list_tools()
        tool_names = {tool.name for tool in listed.tools}
        missing = sorted(MINIMUM_TOOLS - tool_names)
        if missing:
            failure = f"missing required tools: {', '.join(missing)}"

        cloud_checked = False
        items_returned: int | None = None
        if failure is None and not skip_cloud:
            result = await session.call_tool("list_instances", {"limit": 1})
            code = _error_code(result)
            if getattr(result, "is_error", getattr(result, "isError", False)) or code:
                code = code or "unknown"
                failure = f"list_instances failed with {code}"
            else:
                cloud_checked = True
                items_returned = _item_count(result)

        blocked_code: str | None = None
        if failure is None:
            blocked = await session.call_tool(
                "restart_instance",
                {
                    "instance_id": "00000000-0000-0000-0000-000000000000",
                    "confirm": False,
                },
            )
            blocked_code = _error_code(blocked)
            if blocked_code != "MCP_READ_ONLY":
                failure = (
                    "read-only guardrail did not return MCP_READ_ONLY "
                    f"(received {blocked_code or 'no error code'})"
                )

        server_info = initialized.server_info
        summary = {
            "server": server_info.name,
            "version": server_info.version,
            "tools": len(tool_names),
            "cloud_checked": cloud_checked,
            "items_returned": items_returned,
            "read_only_guard": blocked_code,
        }

    if failure is not None:
        raise RuntimeError(failure)
    if summary is None:
        raise RuntimeError("server closed before the smoke-test summary was produced")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, run the bounded smoke test, and print a safe summary."""
    options = _parser().parse_args(argv)
    if options.timeout <= 0:
        print("FAIL: --timeout must be greater than zero", file=sys.stderr)
        return 2
    command, args = _server_command(options.server)
    try:
        summary = asyncio.run(
            asyncio.wait_for(
                _smoke(command, args, options.skip_cloud),
                timeout=options.timeout,
            )
        )
    except (TimeoutError, OSError, RuntimeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("PASS: " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
