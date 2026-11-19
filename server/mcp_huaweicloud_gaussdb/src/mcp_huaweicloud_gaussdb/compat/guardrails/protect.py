# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""GaussDB tag normalization for the shared resource protection rules."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any

from huaweicloud_mcp_core.guardrails.protect import (
    assert_not_protected as _core_assert_not_protected,
)
from huaweicloud_mcp_core.guardrails.protect import (
    extract_tag_set as _core_extract_tag_set,
)
from huaweicloud_mcp_core.guardrails.protect import (
    match_arguments as _core_match_arguments,
)
from huaweicloud_mcp_core.guardrails.protect import (
    match_resource as _core_match_resource,
)
from huaweicloud_mcp_core.guardrails.rules import ResourceSpec, Rule, RuleHit
from huaweicloud_mcp_core.guardrails.rules import load_rules as _core_load_rules
from huaweicloud_mcp_core.security import ToolRisk

from ..settings import McpSettings


def load_rules(settings: McpSettings | None = None) -> list[Rule]:
    return _core_load_rules(settings or McpSettings.from_env(require_credentials=False))


def extract_tag_set(value: Any) -> set[str]:
    """Accept the core tag formats and GaussDB's list of key/value objects."""
    if not isinstance(value, (list, tuple)):
        return _core_extract_tag_set(value)
    tags: set[str] = set()
    for item in value:
        if isinstance(item, dict) and "key" in item:
            key = str(item["key"])
            tags.add(key)
            if item.get("value") is not None:
                tags.add(f"{key}={item['value']}")
        else:
            tags.update(_core_extract_tag_set([item]))
    return tags


def _tag_mapping(tags: set[str]) -> dict[str, str | None]:
    # A key/value tag must take precedence over the same key without a value.
    # Normalize it before handing it to the shared core resource matcher.
    actual: dict[str, str | None] = {}
    for tag in tags:
        key, separator, value = tag.partition("=")
        if separator:
            actual[key] = value
        else:
            actual.setdefault(key, None)
    return actual


def match_resource(
    spec: ResourceSpec,
    *,
    resource_id: str | None = None,
    name: str | None = None,
    tags: set[str] | None = None,
) -> str | None:
    normalized = _core_extract_tag_set(_tag_mapping(tags)) if tags else None
    return _core_match_resource(spec, resource_id=resource_id, name=name, tags=normalized)


def _argument_tags(arguments: dict[str, Any]) -> Iterator[set[str]]:
    for key, value in arguments.items():
        if "tag" in key.lower():
            yield extract_tag_set(value)
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if "tag" in sub_key.lower():
                    yield extract_tag_set(sub_value)


def _match_arguments(spec: ResourceSpec, arguments: dict[str, Any]) -> str | None:
    hit = _core_match_arguments(replace(spec, tags=()), arguments)
    if hit or not spec.tags:
        return hit
    for tags in _argument_tags(arguments):
        hit = match_resource(spec, tags=tags)
        if hit:
            return hit
    return None


def evaluate_rules(
    rules: list[Rule],
    tool_name: str,
    risk: ToolRisk,
    arguments: dict[str, Any],
) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for rule in rules:
        if not rule.matches_tool(tool_name, risk):
            continue
        via = (
            "no-resource-filter"
            if rule.resources.is_empty()
            else _match_arguments(rule.resources, arguments)
        )
        if via:
            hits.append(RuleHit(rule=rule, matched_via=via))
    return hits


def assert_not_protected(
    resource: dict[str, Any],
    rules: list[Rule] | None = None,
    tool_name: str = "",
) -> None:
    tags = _tag_mapping(extract_tag_set(resource.get("tags") or {}))
    effective_rules = rules if rules is not None else load_rules()
    _core_assert_not_protected({**resource, "tags": tags}, effective_rules, tool_name)
