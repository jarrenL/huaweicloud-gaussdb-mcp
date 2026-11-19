"""Guarded access to the complete public GaussDB SDK operation surface."""

from typing import Any

from huaweicloud_mcp_core import McpToolError, ToolRisk, page_result, single_result
from huaweicloud_mcp_core.guardrails.rules import Rule
from huaweicloud_mcp_core.output import clamp_limit

from ..client.gaussdb_client import GaussDBClient
from ..compat.guardrails.protect import extract_tag_set, load_rules, match_resource
from ..openapi_catalog import get_operation, operation_schema, operations
from .write_safety import require_manual_payment

_DEDICATED_TOOL_ONLY = {
    "update_instance_configuration": "update_instance_parameters",
    **dict.fromkeys(
        (
            "create_database_instance",
            "create_db_instance",
            "create_gauss_db_instance",
            "create_instance",
        ),
        "create_instance",
    ),
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
    "attach_eip": {
        "prerequisite_note": (
            "This GaussDB operation only binds or unbinds an existing EIP. If no EIP is "
            "available, create one through the Huawei Cloud VPC/EIP service first "
            "(CreatePublicip; for example, hcloud EIP CreatePublicip)."
        ),
        "request_example": {
            "instance_id": "<instance-id>",
            "node_id": "<node-id>",
            "body": {
                "action": "BIND",
                "public_ip": "<public-ip-address>",
                "public_ip_id": "<public-ip-id>",
            },
        },
    },
}


def _with_invocation_guidance(summary: dict[str, Any]) -> dict[str, Any]:
    operation = str(summary["operation"])
    dedicated_tool = _DEDICATED_TOOL_ONLY.get(operation)
    metadata = get_operation(operation)
    return {
        **summary,
        "operation_naming": "snake_case",
        "reviewed": bool(metadata and metadata.reviewed),
        "direct_invoke_supported": dedicated_tool is None and bool(metadata and metadata.reviewed),
        **({"dedicated_tool": dedicated_tool} if dedicated_tool else {}),
        **_REQUEST_SHAPE_GUIDANCE.get(operation, {}),
    }


def _target_instances(request: dict[str, Any]) -> set[str]:
    targets: set[str] = set()

    def visit(value: Any, parent: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = str(key).replace("-", "_").lower()
                if normalized in {
                    "instance_id",
                    "instanceid",
                    "instance_ids",
                    "instanceids",
                    "source_instance_id",
                    "target_instance_id",
                }:
                    if isinstance(item, str):
                        targets.add(item)
                    elif isinstance(item, list) and all(isinstance(i, str) for i in item):
                        targets.update(item)
                    else:
                        raise McpToolError("MCP_INVALID_ARGS", "Instance IDs must be strings.")
                elif (
                    normalized == "id"
                    and parent in {"instances", "instance"}
                    and isinstance(item, str)
                ):
                    targets.add(item)
                visit(item, normalized)
        elif isinstance(value, list):
            for item in value:
                visit(item, parent)

    visit(request)
    return targets


def _apply_resource_rule(rule: Rule, confirm: bool, warnings: list[dict[str, str]]) -> None:
    if rule.action == "warn":
        warnings.append({"rule_id": rule.id, "message": rule.message or rule.id})
    elif rule.action == "confirm" and confirm:
        return
    else:
        raise McpToolError(
            "MCP_CONFIRMATION_REQUIRED" if rule.action == "confirm" else "MCP_GUARDRAIL_BLOCKED",
            rule.message or f"Target matches resource rule '{rule.id}'.",
            hint="Review the actual resource and call with confirm=true."
            if rule.action == "confirm"
            else "Request a protection-rule exemption.",
        )


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
        self,
        *,
        operation: str,
        request: dict[str, Any],
        required_risk: ToolRisk,
        confirm: bool = False,
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
        if not metadata.reviewed:
            raise McpToolError(
                "MCP_UNREVIEWED_OPERATION",
                "This SDK operation has not passed the MCP risk-policy review.",
                hint="Install a release whose reviewed policy includes this operation.",
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
        warnings: list[dict[str, str]] = []
        if required_risk is not ToolRisk.READ:
            require_manual_payment(request)
            warnings = await self._protect_targets(request, required_risk, confirm, operation)
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
        hints: list[str] = []
        if required_risk is not ToolRisk.READ:
            hints.append("Cloud writes can be asynchronous; inspect returned job_id or task_id.")
        if operation == "attach_eip":
            hints.append(
                "GaussDB only binds or unbinds an existing EIP. Create an EIP through the "
                "Huawei Cloud VPC/EIP service first when needed, then verify the binding with "
                "list_binded_eips."
            )
        result = single_result(
            {"operation": operation, "risk": metadata.risk.value, "result": response},
            hints,
        )
        if warnings:
            result["warnings"] = warnings
        return result

    async def _protect_targets(
        self, request: dict[str, Any], risk: ToolRisk, confirm: bool = False, operation: str = ""
    ) -> list[dict[str, str]]:
        targets = _target_instances(request)
        if len(targets) > 100:
            raise McpToolError("MCP_INVALID_ARGS", "At most 100 target instances are allowed.")
        tool_name = f"invoke_{risk.value.lower()}_openapi"
        rules = [
            rule
            for rule in load_rules()
            if rule.matches_tool(tool_name, risk)
            or (operation and rule.matches_tool(operation, risk))
        ]
        warnings: list[dict[str, str]] = []

        for rule in rules:
            if rule.resources.is_empty():
                _apply_resource_rule(rule, confirm, warnings)
        if not targets and any(
            not rule.resources.is_empty() and rule.action != "warn" for rule in rules
        ):
            raise McpToolError(
                "MCP_GUARDRAIL_BLOCKED",
                "Cannot verify live name/tag protection without a resolvable instance target.",
                hint="Use a dedicated scenario tool or an operation with explicit instance IDs.",
            )
        for instance_id in sorted(targets):
            lookup = await self._client.list_database_instances(
                limit=1, offset=0, instance_id=instance_id, name=None
            )
            instances = lookup.get("instances") or []
            if not instances or instances[0].get("id") != instance_id:
                raise McpToolError(
                    "MCP_NOT_FOUND", "Cannot verify the target instance before writing."
                )
            resource = instances[0]
            for rule in rules:
                if not match_resource(
                    rule.resources,
                    resource_id=instance_id,
                    name=resource.get("name"),
                    tags=extract_tag_set(resource.get("tags") or {}),
                ):
                    continue
                _apply_resource_rule(rule, confirm, warnings)
        return warnings
