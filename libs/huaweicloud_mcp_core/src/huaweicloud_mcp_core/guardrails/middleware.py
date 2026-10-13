"""Global MCP 2.x guardrail pipeline."""

import json
import time
from typing import Any

from mcp.server.context import CallNext, ServerRequestContext
from mcp.types import CallToolResult, TextContent

from ..errors import McpToolError
from ..security import ToolRisk, get_tool_risk, tool_supports_confirm
from .audit import AuditLogger
from .masking import MaskingEngine
from .rules import Rule, evaluate_rules, strictest_hit


class GuardrailsMiddleware:
    def __init__(self, *, read_only: bool, rules: list[Rule], audit: AuditLogger) -> None:
        self.read_only, self.rules, self.audit = read_only, rules, audit
        self.masking = MaskingEngine()

    @staticmethod
    def _tool_call(ctx: ServerRequestContext[Any, Any]) -> tuple[str, dict[str, Any]]:
        params = ctx.params
        if isinstance(params, dict):
            return str(params.get("name") or ""), dict(params.get("arguments") or {})
        return str(getattr(params, "name", "")), dict(getattr(params, "arguments", None) or {})

    def _result(self, payload: dict[str, Any]) -> CallToolResult:
        masked = self.masking.mask(payload)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(masked, ensure_ascii=False))],
            structured_content=masked,
            is_error=False,
        )

    def _error(self, error: McpToolError) -> CallToolResult:
        return self._result(error.to_dict())

    def _mask_result(self, result: Any) -> Any:
        if isinstance(result, CallToolResult):
            content = [
                TextContent(type="text", text=self.masking.mask_text(item.text))
                if isinstance(item, TextContent)
                else item
                for item in result.content
            ]
            return result.model_copy(
                update={
                    "content": content,
                    "structured_content": self.masking.mask(result.structured_content),
                }
            )
        return self.masking.mask(result)

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> Any:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        tool_name, arguments = self._tool_call(ctx)
        start = time.monotonic()
        decision, action, rules_hit, error_code = "allowed", None, [], None
        risk = get_tool_risk(tool_name)
        try:
            if risk is None:
                raise McpToolError(
                    "MCP_GUARDRAIL_ERROR",
                    f"Tool '{tool_name}' has no @guard risk declaration.",
                    hint="Declare every tool with @guard(risk=ToolRisk.X).",
                )
            if self.read_only and risk in {ToolRisk.WRITE, ToolRisk.DANGEROUS}:
                raise McpToolError(
                    "MCP_READ_ONLY",
                    f"Tool '{tool_name}' is blocked in read-only mode.",
                    hint="Unset HUAWEICLOUD_MCP_READ_ONLY only in an approved write environment.",
                )
            try:
                hits = evaluate_rules(self.rules, tool_name, risk, arguments)
            except Exception:
                decision, error_code = "fail_closed", "MCP_GUARDRAIL_ERROR"
                if risk is ToolRisk.READ:
                    return self._mask_result(await call_next(ctx))
                return self._error(
                    McpToolError(
                        "MCP_GUARDRAIL_ERROR",
                        "Guardrail evaluation failed and the write was blocked.",
                        hint="Fix HUAWEICLOUD_MCP_GUARDRAILS_CONFIG and retry.",
                    )
                )
            rules_hit = [hit.rule.id for hit in hits]
            strictest = strictest_hit(hits)
            if strictest and strictest.rule.action == "block":
                action, decision = "block", "blocked"
                raise McpToolError(
                    "MCP_GUARDRAIL_BLOCKED",
                    strictest.rule.message or f"Blocked by guardrail rule '{strictest.rule.id}'.",
                    hint=f"Request an exemption for: {', '.join(rules_hit)}.",
                )
            needs_confirm = risk is ToolRisk.DANGEROUS or (
                strictest is not None and strictest.rule.action == "confirm"
            )
            if needs_confirm and not arguments.get("confirm", False):
                if not tool_supports_confirm(tool_name):
                    raise McpToolError(
                        "MCP_GUARDRAIL_BLOCKED",
                        "Confirmation is required but this tool has no confirm parameter.",
                    )
                decision, action = "confirm_required", "confirm"
                return self._result(
                    {
                        "confirmation_required": True,
                        "rules_hit": rules_hit,
                        "message": (
                            "Review the affected resource, then call again with confirm=true."
                        ),
                    }
                )
            result = self._mask_result(await call_next(ctx))
            if strictest and strictest.rule.action == "warn":
                decision, action = "warned", "warn"
                warnings = [
                    {"rule_id": hit.rule.id, "message": hit.rule.message}
                    for hit in hits
                    if hit.rule.action == "warn"
                ]
                if isinstance(result, CallToolResult) and isinstance(
                    result.structured_content, dict
                ):
                    payload = {**result.structured_content, "warnings": warnings}
                    result = self._result(payload)
            return result
        except McpToolError as exc:
            decision, error_code = "blocked", exc.code
            return self._error(exc)
        except Exception:
            decision, error_code = "blocked", "MCP_SDK_ERROR"
            return self._error(
                McpToolError(
                    "MCP_SDK_ERROR",
                    "The tool failed unexpectedly.",
                    hint="Check the audit log and Huawei Cloud request ID, then adjust the call.",
                )
            )
        finally:
            self.audit.emit(
                {
                    "tool": tool_name,
                    "risk": risk.value if risk else None,
                    "decision": decision,
                    "rules_hit": rules_hit,
                    "action_taken": action,
                    "params": arguments,
                    "duration_ms": round((time.monotonic() - start) * 1000),
                    "error_code": error_code,
                }
            )
