"""Guarded access to the complete public GaussDB SDK operation surface."""

from typing import Any

from huaweicloud_mcp_core import McpToolError, ToolRisk, clamp_limit, page_result, single_result
from huaweicloud_mcp_core.guardrails.protect import assert_not_protected

from ..client.gaussdb_client import GaussDBClient
from ..openapi_catalog import get_operation, operation_schema, operations

_DEDICATED_TOOL_ONLY = {
    "update_instance_configuration": "update_instance_parameters",
}
_REQUEST_SHAPE_GUIDANCE: dict[str, dict[str, Any]] = {
    "add_instance_tags": {
        "request_shape_note": "Tags are supplied in body.tags as an array.",
        "request_example": {
            "instance_id": "<instance-id>",
            "body": {"tags": [{"key": "environment", "value": "test"}]},
        },
    },
    "delete_instance_tag": {
        "request_shape_note": (
            "key is a top-level query parameter beside instance_id; this operation has no body."
        ),
        "request_example": {"instance_id": "<instance-id>", "key": "environment"},
    },
}


def _with_invocation_guidance(summary: dict[str, Any]) -> dict[str, Any]:
    operation = str(summary["operation"])
    dedicated_tool = _DEDICATED_TOOL_ONLY.get(operation)
    return {
        **summary,
        "operation_naming": "snake_case",
        "direct_invoke_supported": dedicated_tool is None,
        **({"dedicated_tool": dedicated_tool} if dedicated_tool else {}),
        **_REQUEST_SHAPE_GUIDANCE.get(operation, {}),
    }


class OpenApiService:
    def __init__(self, client: GaussDBClient | None = None) -> None:
        self._client = client or GaussDBClient()

    async def list_operations(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        risk: str | None = None,
        limit: int = 20,
        marker: str | None = None,
    ) -> dict[str, Any]:
        normalized_risk = risk.upper() if risk else None
        if normalized_risk and normalized_risk not in {item.value for item in ToolRisk}:
            raise McpToolError("MCP_INVALID_ARGS", "risk must be READ, WRITE, or DANGEROUS.")
        needle = (query or "").casefold()
        items = [
            _with_invocation_guidance(item.summary())
            for item in operations().values()
            if (not category or item.category == category)
            and (not normalized_risk or item.risk.value == normalized_risk)
            and (
                not needle
                or needle in item.name.casefold()
                or needle in item.title.casefold()
                or needle in item.description.casefold()
            )
        ]
        items.sort(key=lambda value: (value["category"], value["operation"]))
        page_size = clamp_limit(limit)
        offset = int(marker or 0)
        selected = items[offset : offset + page_size]
        next_marker = str(offset + len(selected)) if offset + len(selected) < len(items) else None
        result = page_result(selected, total=len(items), marker=next_marker)
        result["operation_naming"] = "snake_case"
        result["invoke_arguments"] = {
            "operation": "exact operation value returned in items",
            "request": "object matching describe_openapi_operation.request_schema",
        }
        return result

    async def describe_operation(self, *, operation: str) -> dict[str, Any]:
        metadata = get_operation(operation)
        if metadata is None:
            raise McpToolError(
                "MCP_NOT_FOUND",
                f"GaussDB OpenAPI operation '{operation}' was not found in the installed SDK.",
                hint=(
                    "Use list_openapi_operations and pass its exact snake_case operation value in "
                    "the operation field."
                ),
            )
        return single_result(
            {
                **_with_invocation_guidance(metadata.summary()),
                "request_schema": operation_schema(metadata),
                "invoke_arguments": {"operation": metadata.name, "request": {}},
            }
        )

    async def invoke(
        self, *, operation: str, request: dict[str, Any], required_risk: ToolRisk
    ) -> dict[str, Any]:
        metadata = get_operation(operation)
        if metadata is None:
            raise McpToolError(
                "MCP_NOT_FOUND",
                f"GaussDB OpenAPI operation '{operation}' was not found in the installed SDK.",
                hint=(
                    "Use list_openapi_operations and pass its exact snake_case operation value in "
                    "the operation field."
                ),
            )
        if operation in _DEDICATED_TOOL_ONLY:
            dedicated_tool = _DEDICATED_TOOL_ONLY[operation]
            raise McpToolError(
                "MCP_DEDICATED_TOOL_REQUIRED",
                f"Operation '{operation}' is only available through {dedicated_tool}.",
                hint=(
                    f"Call {dedicated_tool} so live modifiability metadata, value ranges, restart "
                    "impact, high-risk confirmation, and audit controls cannot be bypassed."
                ),
            )
        if operation == "delete_instance_tag" and "body" in request:
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "delete_instance_tag does not accept body. Its key is a top-level query field.",
                hint=(
                    'Use request={"instance_id": "<instance-id>", '
                    '"key": "<tag-key>"}. add_instance_tags is different and uses '
                    "request.body.tags."
                ),
            )
        if metadata.risk is not required_risk:
            raise McpToolError(
                "MCP_RISK_MISMATCH",
                f"Operation '{operation}' is classified as {metadata.risk.value}, not "
                f"{required_risk.value}.",
                hint=f"Use invoke_{metadata.risk.value.lower()}_openapi for this operation.",
            )
        if required_risk is ToolRisk.DANGEROUS and request.get("instance_id"):
            lookup = await self._client.list_database_instances(
                limit=1,
                offset=0,
                instance_id=str(request["instance_id"]),
                name=None,
            )
            instances = lookup.get("instances") or []
            if instances:
                assert_not_protected(instances[0], tool_name="invoke_dangerous_openapi")
        try:
            response = await self._client.invoke_openapi(operation=operation, request=request)
        except ValueError as exc:
            raise McpToolError(
                "MCP_INVALID_ARGS",
                str(exc),
                hint=(
                    "The tool arguments are operation and request. "
                    f"Call describe_openapi_operation(operation='{operation}') and put the "
                    "documented request fields inside request."
                ),
            ) from exc
        hints = (
            ["Cloud writes can be asynchronous; inspect returned job_id or task_id."]
            if required_risk is not ToolRisk.READ
            else None
        )
        return single_result(
            {"operation": operation, "risk": metadata.risk.value, "result": response}, hints
        )
