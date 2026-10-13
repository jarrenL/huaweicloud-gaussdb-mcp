"""Cloud-property protection check for irreversible operations."""

from typing import Any

from ..errors import McpToolError
from ..security import ToolRisk
from .rules import extract_tag_set, load_rules, match_resource


def assert_not_protected(
    resource: dict[str, Any], rules: list[Any] | None = None, tool_name: str = ""
) -> None:
    for rule in rules if rules is not None else load_rules():
        if not rule.matches_tool(tool_name, ToolRisk.DANGEROUS):
            continue
        hit = match_resource(
            rule.resources,
            resource_id=str(resource.get("id") or "") or None,
            name=str(resource.get("name") or "") or None,
            tags=extract_tag_set(resource.get("tags") or {}),
        )
        if hit:
            raise McpToolError(
                "MCP_GUARDRAIL_BLOCKED",
                rule.message or f"Resource matches protection rule '{rule.id}' ({hit}).",
                hint=f"Request an exemption for rule '{rule.id}'.",
            )
