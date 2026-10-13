"""Guardrail rule parsing and evaluation."""

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..config import McpSettings
from ..errors import McpToolError
from ..security import ToolRisk

VALID_ACTIONS = ("block", "confirm", "warn")
ACTION_ORDER = {"warn": 0, "confirm": 1, "block": 2}


@dataclass(frozen=True)
class ResourceSpec:
    ids: tuple[str, ...] = ()
    id_prefixes: tuple[str, ...] = ()
    name_patterns: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @property
    def regexes(self) -> tuple[re.Pattern[str], ...]:
        return tuple(re.compile(item) for item in self.name_patterns)

    def is_empty(self) -> bool:
        return not (self.ids or self.id_prefixes or self.name_patterns or self.tags)


@dataclass(frozen=True)
class Rule:
    id: str
    action: str
    message: str = ""
    tools: tuple[str, ...] = ()
    risks: tuple[ToolRisk, ...] = ()
    resources: ResourceSpec = field(default_factory=ResourceSpec)

    def matches_tool(self, tool_name: str, risk: ToolRisk) -> bool:
        return (not self.tools or any(fnmatch.fnmatchcase(tool_name, p) for p in self.tools)) and (
            not self.risks or risk in self.risks
        )


@dataclass(frozen=True)
class RuleHit:
    rule: Rule
    matched_via: str


def _rule_from_dict(item: dict[str, Any]) -> Rule:
    match = item.get("match") or {}
    resources = match.get("resources") or {}
    action = str(item.get("action", ""))
    if action not in VALID_ACTIONS:
        raise ValueError(f"invalid action {action!r}")
    risks = tuple(ToolRisk[str(value)] for value in match.get("risks") or [])
    spec = ResourceSpec(
        ids=tuple(str(x) for x in resources.get("ids") or []),
        id_prefixes=tuple(str(x) for x in resources.get("id_prefixes") or []),
        name_patterns=tuple(str(x) for x in resources.get("name_patterns") or []),
        tags=tuple(str(x) for x in resources.get("tags") or []),
    )
    _ = spec.regexes  # Compile at load time so malformed patterns fail fast.
    return Rule(
        id=str(item["id"]),
        action=action,
        message=str(item.get("message") or ""),
        tools=tuple(str(x) for x in match.get("tools") or []),
        risks=risks,
        resources=spec,
    )


def load_rules(settings: McpSettings | None = None) -> list[Rule]:
    settings = settings or McpSettings.from_env(require_credentials=False)
    rules: list[Rule] = []
    if settings.protected_ids:
        rules.append(
            Rule(
                "env-protected-ids",
                "block",
                resources=ResourceSpec(ids=settings.protected_ids),
            )
        )
    if settings.protected_names:
        patterns = tuple(f"^{re.escape(name)}$" for name in settings.protected_names)
        rules.append(
            Rule(
                "env-protected-names",
                "block",
                resources=ResourceSpec(name_patterns=patterns),
            )
        )
    if settings.protected_tags:
        rules.append(
            Rule(
                "env-protected-tags",
                "block",
                resources=ResourceSpec(tags=settings.protected_tags),
            )
        )
    if settings.guardrails_config_path:
        try:
            raw = (
                yaml.safe_load(Path(settings.guardrails_config_path).read_text(encoding="utf-8"))
                or {}
            )
            rules.extend(_rule_from_dict(item) for item in raw.get("rules") or [])
        except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise McpToolError(
                "MCP_GUARDRAIL_ERROR",
                "Invalid guardrails configuration.",
                hint=f"Fix HUAWEICLOUD_MCP_GUARDRAILS_CONFIG: {exc}",
            ) from None
    ids = [rule.id for rule in rules]
    if len(ids) != len(set(ids)):
        raise McpToolError("MCP_GUARDRAIL_ERROR", "Guardrail rule IDs must be unique.")
    return rules


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _strings(child)]
    return []


def extract_tag_set(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {f"{key}={item}" for key, item in value.items()}
    return set(_strings(value))


def match_resource(
    spec: ResourceSpec,
    *,
    resource_id: str | None = None,
    name: str | None = None,
    tags: set[str] | None = None,
) -> str | None:
    if resource_id in spec.ids:
        return "id"
    for prefix in spec.id_prefixes:
        if resource_id and resource_id.startswith(prefix):
            return f"prefix:{prefix}"
    for pattern in spec.regexes:
        if name and pattern.search(name):
            return f"name:{pattern.pattern}"
    for tag in spec.tags:
        if tags and tag in tags:
            return f"tag:{tag}"
    return None


def match_arguments(spec: ResourceSpec, arguments: dict[str, Any]) -> str | None:
    for key, value in arguments.items():
        strings = _strings(value)
        for text in strings:
            hit = match_resource(
                spec, resource_id=text, name=text if "name" in key.lower() else None
            )
            if hit:
                return hit
        if "tag" in key.lower():
            hit = match_resource(spec, tags=extract_tag_set(value))
            if hit:
                return hit
    return None


def evaluate_rules(
    rules: list[Rule], tool_name: str, risk: ToolRisk, arguments: dict[str, Any]
) -> list[RuleHit]:
    hits = []
    for rule in rules:
        if not rule.matches_tool(tool_name, risk):
            continue
        matched = (
            "no-resource-filter"
            if rule.resources.is_empty()
            else match_arguments(rule.resources, arguments)
        )
        if matched:
            hits.append(RuleHit(rule, matched))
    return hits


def strictest_hit(hits: list[RuleHit]) -> RuleHit | None:
    return max(hits, key=lambda hit: ACTION_ORDER[hit.rule.action]) if hits else None
