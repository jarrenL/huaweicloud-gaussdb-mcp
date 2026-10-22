# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""GuardrailsMiddleware: the single interception point for every tool call."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.context import ServerRequestContext
from mcp.types import CallToolResult, TextContent

from huaweicloud_mcp_core.errors import McpToolError
from huaweicloud_mcp_core.guardrails.audit import AuditLogger
from huaweicloud_mcp_core.guardrails.masking import MaskingEngine
from huaweicloud_mcp_core.guardrails.rules import Rule, RuleHit, evaluate_rules, strictest_hit
from huaweicloud_mcp_core.security import ToolRisk, get_tool_risk, tool_supports_confirm

CallNext = Callable[[ServerRequestContext[Any, Any]], Awaitable[Any]]


class GuardrailsMiddleware:
    """Pre-call checks (read-only, declaration, protection rules) plus post-call
    masking, warning injection and structured audit. Installed by build_server()."""

    def __init__(
        self,
        *,
        read_only: bool = False,
        rules: list[Rule] | None = None,
        masking: MaskingEngine | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._read_only = read_only
        self._rules = rules if rules is not None else []
        self._masking = masking or MaskingEngine()
        self._audit = audit or AuditLogger()

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
        params_value = ctx.params
        if params_value is None or isinstance(params_value, dict):
            params = dict(params_value or {})
        else:
            params = {
                "name": getattr(params_value, "name", ""),
                "arguments": getattr(params_value, "arguments", None),
            }
        tool_name = str(params.get("name") or "")
        arguments: dict[str, Any] = dict(params.get("arguments") or {})
        risk = get_tool_risk(tool_name)
        started = time.monotonic()
        decision = "allowed"
        rules_hit: list[str] = []
        error_code: str | None = None

        try:
            pre = self._pre_check(tool_name, risk, arguments)
        except McpToolError as exc:
            decision = "blocked"
            error_code = exc.code
            return self._finish(
                started,
                tool_name,
                risk,
                decision,
                rules_hit,
                error_code,
                arguments,
                self._error_result(exc),
            )
        except Exception as exc:
            decision = "fail_closed"
            if risk is ToolRisk.READ:
                pre = None
            else:
                error = McpToolError(
                    code="MCP_GUARDRAIL_ERROR",
                    message=f"Guardrail engine error while evaluating tool '{tool_name}': {exc}",
                    hint="Fix the guardrails configuration (HUAWEICLOUD_MCP_GUARDRAILS_CONFIG).",
                )
                error_code = error.code
                return self._finish(
                    started,
                    tool_name,
                    risk,
                    decision,
                    rules_hit,
                    error_code,
                    arguments,
                    self._error_result(error),
                )

        warn_hits: list[RuleHit] = []
        if pre is not None:
            action, hits = pre
            rules_hit = [hit.rule.id for hit in hits]
            if action == "block":
                decision = "blocked"
                strictest = strictest_hit(hits)
                message = strictest.rule.message if strictest else "Blocked by guardrail rule."
                error = McpToolError(
                    code="MCP_GUARDRAIL_BLOCKED",
                    message=message,
                    hint=(
                        f"Blocked by rule(s): {', '.join(rules_hit)}. Request an exemption "
                        "or adjust the protection list."
                    ),
                )
                error_code = error.code
                return self._finish(
                    started,
                    tool_name,
                    risk,
                    decision,
                    rules_hit,
                    error_code,
                    arguments,
                    self._error_result(error),
                )
            if action == "confirm":
                decision = "confirm_required"
                return self._finish(
                    started,
                    tool_name,
                    risk,
                    decision,
                    rules_hit,
                    error_code,
                    arguments,
                    self._confirm_result(hits),
                )
            warn_hits = hits

        try:
            result = await call_next(ctx)
        except McpToolError as exc:
            decision = "blocked"
            error_code = exc.code
            return self._finish(
                started,
                tool_name,
                risk,
                decision,
                rules_hit,
                error_code,
                arguments,
                self._error_result(exc),
            )
        except Exception as exc:
            error = McpToolError("MCP_SDK_ERROR", str(exc))
            error_code = error.code
            return self._finish(
                started,
                tool_name,
                risk,
                decision,
                rules_hit,
                error_code,
                arguments,
                self._error_result(error),
            )

        if warn_hits:
            decision = "warned"
        result = self._post_process(result, warn_hits)
        return self._finish(
            started, tool_name, risk, decision, rules_hit, error_code, arguments, result
        )

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
        if not hits:
            if risk is ToolRisk.DANGEROUS and arguments.get("confirm") is not True:
                if not tool_supports_confirm(tool_name):
                    raise McpToolError(
                        "MCP_GUARDRAIL_BLOCKED",
                        "Confirmation is required but this tool has no confirm parameter.",
                    )
                return "confirm", []
            return None
        strictest = strictest_hit(hits)
        assert strictest is not None
        action = strictest.rule.action
        if action == "confirm":
            if not tool_supports_confirm(tool_name):
                action = "block"
            elif arguments.get("confirm") is True:
                return None
        if (
            risk is ToolRisk.DANGEROUS
            and arguments.get("confirm") is not True
            and action != "block"
        ):
            return "confirm", hits
        return action, hits

    def _post_process(self, result: Any, warn_hits: list[RuleHit]) -> Any:
        if isinstance(result, dict):
            masked = self._masking.mask(result)
            if warn_hits:
                masked.setdefault("warnings", _warnings_payload(warn_hits))
            return masked
        if not isinstance(result, CallToolResult):
            return result
        new_content: list[Any] = []
        for block in result.content:
            if isinstance(block, TextContent):
                new_content.append(
                    TextContent(
                        type="text",
                        text=self._mask_text(block.text, warn_hits),
                    )
                )
            else:
                new_content.append(block)
        structured = getattr(result, "structured_content", None)
        if isinstance(structured, dict):
            structured = self._masking.mask(structured)
            if warn_hits:
                structured.setdefault("warnings", _warnings_payload(warn_hits))
        return CallToolResult(
            content=new_content,
            structured_content=structured,
            is_error=result.is_error,
        )

    def _mask_text(self, text: str, warn_hits: list[RuleHit]) -> str:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return self._masking.mask_text(text)
        if isinstance(payload, dict):
            payload = self._masking.mask(payload)
            if warn_hits:
                payload.setdefault("warnings", _warnings_payload(warn_hits))
            return json.dumps(payload, ensure_ascii=False, default=str)
        return self._masking.mask_text(text)

    def _error_result(self, error: McpToolError) -> CallToolResult:
        payload = error.to_dict()
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
            structured_content=payload,
            is_error=False,
        )

    def _confirm_result(self, hits: list[RuleHit]) -> CallToolResult:
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

    def _finish(
        self,
        started: float,
        tool_name: str,
        risk: ToolRisk | None,
        decision: str,
        rules_hit: list[str],
        error_code: str | None,
        arguments: dict[str, Any],
        result: Any,
    ) -> Any:
        self._audit.emit(
            tool=tool_name,
            risk=risk.value if risk else "UNDECLARED",
            decision=decision,
            rules_hit=rules_hit,
            action_taken=decision,
            params=arguments,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code=error_code,
        )
        return result


def _warnings_payload(warn_hits: list[RuleHit]) -> list[dict[str, str]]:
    return [{"rule_id": hit.rule.id, "message": hit.rule.message} for hit in warn_hits]
