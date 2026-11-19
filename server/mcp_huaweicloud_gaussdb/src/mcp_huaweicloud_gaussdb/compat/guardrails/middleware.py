# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Apply GaussDB's confirmation, masking, and audit rules to every tool call."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from huaweicloud_mcp_core.errors import McpToolError
from huaweicloud_mcp_core.guardrails.rules import Rule, RuleHit, strictest_hit
from huaweicloud_mcp_core.security import ToolRisk, get_tool_risk, tool_supports_confirm
from mcp.server.context import ServerRequestContext
from mcp.types import CallToolResult, TextContent

from .audit import AuditLogger
from .masking import MaskingEngine
from .protect import evaluate_rules

CallNext = Callable[[ServerRequestContext[Any, Any]], Awaitable[Any]]


@dataclass(frozen=True)
class _ToolCall:
    name: str
    arguments: dict[str, Any]
    risk: ToolRisk | None
    started: float

    @classmethod
    def from_context(cls, ctx: ServerRequestContext[Any, Any]) -> _ToolCall:
        params = ctx.params
        if params is None or isinstance(params, dict):
            raw = params or {}
            name = raw.get("name")
            arguments = raw.get("arguments")
        else:
            name = getattr(params, "name", "")
            arguments = getattr(params, "arguments", None)
        tool_name = str(name or "")
        return cls(tool_name, dict(arguments or {}), get_tool_risk(tool_name), time.monotonic())


class GuardrailsMiddleware:
    """Check tool policy and capacity before dispatching; mask and audit the result."""

    def __init__(
        self,
        *,
        read_only: bool = False,
        rules: list[Rule] | None = None,
        masking: MaskingEngine | None = None,
        audit: AuditLogger | None = None,
        max_concurrent: int = 16,
    ) -> None:
        self._read_only = read_only
        self._rules = rules if rules is not None else []
        self._masking = masking or MaskingEngine()
        self._audit = audit or AuditLogger()
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        self._capacity = threading.BoundedSemaphore(max_concurrent)

    @property
    def rules(self) -> list[Rule]:
        return self._rules

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> Any:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        call = _ToolCall.from_context(ctx)
        decision, hits, result = self._evaluate_call(call)
        if result is None:
            decision, result = await self._run_tool(ctx, call_next, decision, hits)
        return self._finish(call, decision, hits, result)

    def _evaluate_call(self, call: _ToolCall) -> tuple[str, list[RuleHit], Any]:
        try:
            pre = self._pre_check(call.name, call.risk, call.arguments)
        except McpToolError as exc:
            return "blocked", [], _wrap_error_payload(exc.to_dict())
        except Exception as exc:
            if call.risk is ToolRisk.READ:
                return "fail_closed", [], None
            error = McpToolError(
                code="MCP_GUARDRAIL_ERROR",
                message=f"Guardrail engine error while evaluating tool '{call.name}': {exc}",
                hint="Fix the guardrails configuration (HUAWEICLOUD_MCP_GUARDRAILS_CONFIG).",
            )
            return "fail_closed", [], _wrap_error_payload(error.to_dict())

        if pre is None:
            return "allowed", [], None
        action, hits = pre
        if action == "block":
            strictest = strictest_hit(hits)
            message = strictest.rule.message if strictest else "Blocked by guardrail rule."
            rule_ids = ", ".join(hit.rule.id for hit in hits)
            error = McpToolError(
                code="MCP_GUARDRAIL_BLOCKED",
                message=message,
                hint=(
                    f"Blocked by rule(s): {rule_ids}. Request an exemption "
                    "or adjust the protection list."
                ),
            )
            return "blocked", hits, _wrap_error_payload(error.to_dict())
        if action == "confirm":
            return "confirm_required", hits, _confirm_result(hits)
        return "allowed", hits, None

    async def _run_tool(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
        decision: str,
        warn_hits: list[RuleHit],
    ) -> tuple[str, Any]:
        if not self._capacity.acquire(blocking=False):
            error = McpToolError("MCP_BUSY", "Tool concurrency limit reached; retry later.")
            return "blocked", _wrap_error_payload(error.to_dict())
        try:
            result = await call_next(ctx)
        except McpToolError as exc:
            return "blocked", _wrap_error_payload(exc.to_dict())
        except Exception as exc:
            error = McpToolError("MCP_SDK_ERROR", str(exc))
            return "failed", _wrap_error_payload(error.to_dict())
        finally:
            self._capacity.release()
        return ("warned" if warn_hits else decision), self._post_process(result, warn_hits)

    def _pre_check(
        self,
        tool_name: str,
        risk: ToolRisk | None,
        arguments: dict[str, Any],
    ) -> tuple[str, list[RuleHit]] | None:
        if risk is None:
            raise McpToolError(
                code="MCP_GUARDRAIL_ERROR",
                message=f"Tool '{tool_name}' has no @guard(risk=...) declaration.",
                hint="Every tool must declare ToolRisk; see spec section 7.2.",
            )
        if self._read_only and risk is not ToolRisk.READ:
            raise McpToolError(
                code="MCP_READ_ONLY",
                message=(
                    f"Tool '{tool_name}' ({risk.value}) is blocked: read-only mode is enabled "
                    "(HUAWEICLOUD_MCP_READ_ONLY=true)."
                ),
                hint="Unset HUAWEICLOUD_MCP_READ_ONLY to allow write operations.",
            )
        hits = evaluate_rules(self._rules, tool_name, risk, arguments)
        strictest = strictest_hit(hits)
        action = strictest.rule.action if strictest else "allow"
        confirmed = arguments.get("confirm") is True
        if action == "confirm":
            if not tool_supports_confirm(tool_name):
                return "block", hits
            if confirmed:
                return None
        if risk is ToolRisk.DANGEROUS and not confirmed and action != "block":
            if not hits and not tool_supports_confirm(tool_name):
                raise McpToolError(
                    "MCP_GUARDRAIL_BLOCKED",
                    "Confirmation is required but this tool has no confirm parameter.",
                )
            return "confirm", hits
        return (action, hits) if hits else None

    def _post_process(self, result: Any, warn_hits: list[RuleHit]) -> Any:
        # The MCP SDK can return a wire envelope before giving us a structured result.
        if (
            isinstance(result, dict)
            and isinstance(result.get("content"), list)
            and ("isError" in result or "structuredContent" in result)
        ):
            result = CallToolResult.model_validate(result)
        if isinstance(result, dict):
            return self._mask_payload(result, warn_hits)
        if not isinstance(result, CallToolResult):
            return result
        content = [
            TextContent(type="text", text=self._mask_text(block.text, warn_hits))
            if isinstance(block, TextContent)
            else block
            for block in result.content
        ]
        structured = result.structured_content
        if isinstance(structured, dict):
            structured = self._mask_payload(structured, warn_hits)
        return result.model_copy(update={"content": content, "structured_content": structured})

    def _mask_payload(self, payload: dict[str, Any], warn_hits: list[RuleHit]) -> dict[str, Any]:
        masked: dict[str, Any] = self._masking.mask(payload)
        if warn_hits:
            warnings = [{"rule_id": hit.rule.id, "message": hit.rule.message} for hit in warn_hits]
            masked.setdefault("warnings", warnings)
        return masked

    def _mask_text(self, text: str, warn_hits: list[RuleHit]) -> str:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return self._masking.mask_text(text)
        if isinstance(payload, dict):
            masked = self._mask_payload(payload, warn_hits)
            return json.dumps(masked, ensure_ascii=False, default=str)
        return self._masking.mask_text(text)

    def _finish(self, call: _ToolCall, decision: str, hits: list[RuleHit], result: Any) -> Any:
        # Mask every return path, including thrown errors and guardrail warnings.
        result = self._post_process(result, [])
        result, decision, error_code, request_id = _classify_result(result, decision)
        self._audit.emit(
            tool=call.name,
            risk=call.risk.value if call.risk else "UNDECLARED",
            decision=decision,
            rules_hit=[hit.rule.id for hit in hits],
            action_taken=decision,
            params=call.arguments,
            duration_ms=int((time.monotonic() - call.started) * 1000),
            error_code=error_code,
            request_id=request_id,
            outcome="failed"
            if error_code
            else "confirmation_required"
            if decision == "confirm_required"
            else "succeeded",
        )
        return result


def _classify_result(result: Any, decision: str) -> tuple[Any, str, str | None, Any]:
    payload = _result_payload(result)
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        error_code = str(error.get("code") or "MCP_SDK_ERROR")
        if decision in {"allowed", "warned"}:
            decision = "failed"
        if isinstance(result, CallToolResult):
            result.is_error = True
        else:
            result = _wrap_error_payload(payload)
        return result, decision, error_code, error.get("request_id")
    if isinstance(result, CallToolResult) and result.is_error:
        return result, "failed", "MCP_SDK_ERROR", None
    if isinstance(payload, dict) and payload.get("confirmation_required") is True:
        decision = "confirm_required"
    return result, decision, None, None


def _result_payload(result: Any) -> Any:
    if not isinstance(result, CallToolResult):
        return result
    if result.structured_content is not None:
        return result.structured_content
    for block in result.content:
        if isinstance(block, TextContent):
            try:
                return json.loads(block.text)
            except json.JSONDecodeError:
                return None
    return None


def _wrap_error_payload(payload: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=True,
    )


def _confirm_result(hits: list[RuleHit]) -> CallToolResult:
    strictest = strictest_hit(hits)
    message = strictest.rule.message if strictest else "Confirmation required."
    payload = {
        "confirmation_required": True,
        "rules_hit": [hit.rule.id for hit in hits],
        "message": f"{message} Call again with confirm=true to proceed.",
    }
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=False,
    )
