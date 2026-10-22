# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Tests for GuardrailsMiddleware behavior (block / confirm / warn / fail-closed)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from mcp.types import CallToolResult, TextContent

from huaweicloud_mcp_core.errors import McpToolError
from huaweicloud_mcp_core.guardrails.audit import AuditLogger
from huaweicloud_mcp_core.guardrails.middleware import GuardrailsMiddleware
from huaweicloud_mcp_core.guardrails.rules import ResourceSpec, Rule
from huaweicloud_mcp_core.security import ToolRisk, guard


@guard(risk=ToolRisk.READ)
async def list_widgets(limit: int = 20) -> dict[str, Any]:
    return {"items": [{"id": "w-1"}], "count": 1}


@guard(risk=ToolRisk.WRITE)
async def update_widget(widget_id: str, name: str | None = None) -> dict[str, Any]:
    return {"widget_id": widget_id, "name": name, "password": "hunter2"}


@guard(risk=ToolRisk.DANGEROUS)
async def delete_widget(widget_id: str, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        return {"confirmation_required": True, "preview": {"name": widget_id, "tags": {}}}
    return {"deleted": True}


class SpyAudit(AuditLogger):
    """AuditLogger that records events without writing to stderr or a file."""

    def emit(self, **event: Any) -> None:
        self.events.append(self._build_record(**event))


def _ctx(method: str, params: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(method=method, params=params)


def _tool_ctx(tool_name: str, arguments: dict[str, Any]) -> Any:
    return _ctx("tools/call", {"name": tool_name, "arguments": arguments})


def _ok_result(payload: dict[str, Any]) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))])


def _payload(result: Any) -> dict[str, Any]:
    if isinstance(result, CallToolResult):
        first = result.content[0]
        assert isinstance(first, TextContent)
        return cast(dict[str, Any], json.loads(first.text))
    return cast(dict[str, Any], result)


def _make_call_next(outcome: Any) -> Any:
    async def call_next(ctx: Any) -> Any:
        return outcome

    return call_next


async def _run(
    middleware: GuardrailsMiddleware,
    tool_name: str,
    arguments: dict[str, Any],
    tool_result: dict[str, Any] | None = None,
) -> Any:
    if tool_result is None:
        tool_result = {"ok": True}
    return await middleware(
        _tool_ctx(tool_name, arguments), _make_call_next(_ok_result(tool_result))
    )


def _middleware(**kwargs: Any) -> GuardrailsMiddleware:
    kwargs.setdefault("rules", [])
    kwargs.setdefault("audit", SpyAudit())
    return GuardrailsMiddleware(**kwargs)


async def test_non_tool_requests_pass_through_untouched() -> None:
    middleware = _middleware()

    async def call_next(ctx: Any) -> Any:
        return {"tools": []}

    result = await middleware(_ctx("tools/list"), call_next)
    assert result == {"tools": []}
    assert middleware._audit.events == []


async def test_undeclared_tool_is_blocked() -> None:
    middleware = _middleware()
    result = await _run(middleware, "undeclared_tool", {})
    payload = _payload(result)
    assert payload["error"]["code"] == "MCP_GUARDRAIL_ERROR"
    assert middleware._audit.events[-1]["decision"] == "blocked"


async def test_read_only_blocks_write_but_not_read() -> None:
    middleware = _middleware(read_only=True)
    blocked = await _run(middleware, "update_widget", {"widget_id": "w-1"})
    assert _payload(blocked)["error"]["code"] == "MCP_READ_ONLY"
    allowed = await _run(middleware, "list_widgets", {})
    assert _payload(allowed) == {"ok": True}


async def test_block_rule_returns_error_with_rule_id() -> None:
    rules = [Rule(id="protect-w1", action="block", resources=ResourceSpec(ids=("w-1",)))]
    middleware = _middleware(rules=rules)
    result = await _run(middleware, "update_widget", {"widget_id": "w-1"})
    payload = _payload(result)
    assert payload["error"]["code"] == "MCP_GUARDRAIL_BLOCKED"
    assert "protect-w1" in payload["error"]["hint"]
    event = middleware._audit.events[-1]
    assert event["decision"] == "blocked"
    assert event["rules_hit"] == ["protect-w1"]


async def test_block_rule_not_matching_other_resource() -> None:
    rules = [Rule(id="protect-w1", action="block", resources=ResourceSpec(ids=("w-1",)))]
    middleware = _middleware(rules=rules)
    result = await _run(middleware, "update_widget", {"widget_id": "w-2"})
    assert _payload(result) == {"ok": True}


async def test_confirm_rule_escalates_then_allows_with_confirm_true() -> None:
    rules = [
        Rule(
            id="staging-confirm",
            action="confirm",
            resources=ResourceSpec(id_prefixes=("staging-",)),
        )
    ]
    middleware = _middleware(rules=rules)
    escalated = await _run(middleware, "delete_widget", {"widget_id": "staging-1"})
    payload = _payload(escalated)
    assert payload["confirmation_required"] is True
    assert "staging-confirm" in payload["rules_hit"]
    assert middleware._audit.events[-1]["decision"] == "confirm_required"
    allowed = await _run(middleware, "delete_widget", {"widget_id": "staging-1", "confirm": True})
    assert _payload(allowed) == {"ok": True}


async def test_confirm_rule_degrades_to_block_without_confirm_param() -> None:
    rules = [Rule(id="warn-then-confirm", action="confirm", resources=ResourceSpec(ids=("w-1",)))]
    middleware = _middleware(rules=rules)
    result = await _run(middleware, "update_widget", {"widget_id": "w-1"})
    payload = _payload(result)
    assert payload["error"]["code"] == "MCP_GUARDRAIL_BLOCKED"


async def test_warn_rule_injects_warnings_and_still_executes() -> None:
    rules = [
        Rule(
            id="prod-notice",
            action="warn",
            message="Production widget touched.",
            resources=ResourceSpec(ids=("w-1",)),
        )
    ]
    middleware = _middleware(rules=rules)
    result = await _run(middleware, "update_widget", {"widget_id": "w-1"}, tool_result={"ok": True})
    payload = _payload(result)
    assert payload["ok"] is True
    assert payload["warnings"] == [
        {"rule_id": "prod-notice", "message": "Production widget touched."}
    ]
    assert middleware._audit.events[-1]["decision"] == "warned"


async def test_output_is_masked_after_execution() -> None:
    middleware = _middleware()
    result = await _run(
        middleware,
        "update_widget",
        {"widget_id": "w-1"},
        tool_result={"password": "hunter2", "name": "w-1"},
    )
    payload = _payload(result)
    assert payload["password"] == "***"
    assert payload["password_masked"] is True
    assert payload["name"] == "w-1"


async def test_audit_params_are_masked() -> None:
    middleware = _middleware()
    await _run(middleware, "update_widget", {"widget_id": "w-1", "auth_token": "secret-value"})
    event = middleware._audit.events[-1]
    assert event["params"]["auth_token"] == "***"


async def test_fail_closed_blocks_write_on_engine_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> list[Any]:
        raise RuntimeError("engine exploded")

    monkeypatch.setattr("huaweicloud_mcp_core.guardrails.middleware.evaluate_rules", boom)
    middleware = _middleware()
    blocked = await _run(middleware, "update_widget", {"widget_id": "w-1"})
    payload = _payload(blocked)
    assert payload["error"]["code"] == "MCP_GUARDRAIL_ERROR"
    assert middleware._audit.events[-1]["decision"] == "fail_closed"


async def test_fail_closed_allows_read_on_engine_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> list[Any]:
        raise RuntimeError("engine exploded")

    monkeypatch.setattr("huaweicloud_mcp_core.guardrails.middleware.evaluate_rules", boom)
    middleware = _middleware()
    allowed = await _run(middleware, "list_widgets", {})
    assert _payload(allowed) == {"ok": True}
    assert middleware._audit.events[-1]["decision"] == "fail_closed"


async def test_tool_error_from_execution_is_wrapped() -> None:
    middleware = _middleware()

    async def call_next(ctx: Any) -> Any:
        raise McpToolError("MCP_NOT_FOUND", "widget missing", hint="retry")

    result = await middleware(_tool_ctx("list_widgets", {}), call_next)
    payload = _payload(result)
    assert payload["error"]["code"] == "MCP_NOT_FOUND"
    assert payload["error"]["hint"] == "retry"


async def test_dict_result_is_masked_directly() -> None:
    middleware = _middleware()
    outcome = {"secret_key": "abcdef", "value": 1}

    async def call_next(ctx: Any) -> Any:
        return outcome

    result = await middleware(_tool_ctx("list_widgets", {}), call_next)
    assert result["secret_key"] == "***"
    assert result["value"] == 1


async def test_non_json_tool_result_masked_as_text() -> None:
    middleware = _middleware()

    async def call_next(ctx: Any) -> Any:
        return CallToolResult(
            content=[TextContent(type="text", text="raw token Bearer abc123XYZdef456")]
        )

    result = await middleware(_tool_ctx("list_widgets", {}), call_next)
    assert "abc123XYZdef456" not in result.content[0].text


async def test_dangerous_call_requires_confirmation_without_a_rule() -> None:
    result = await _run(_middleware(), "delete_widget", {"widget_id": "w-1"})
    assert _payload(result)["confirmation_required"] is True
    allowed = await _run(_middleware(), "delete_widget", {"widget_id": "w-1", "confirm": True})
    assert _payload(allowed) == {"ok": True}


async def test_warn_rule_does_not_bypass_dangerous_confirmation() -> None:
    middleware = _middleware(rules=[Rule(id="notice", action="warn")])
    result = await _run(middleware, "delete_widget", {"widget_id": "w-1"})
    assert _payload(result)["confirmation_required"] is True
