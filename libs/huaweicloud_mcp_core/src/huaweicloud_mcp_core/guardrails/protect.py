# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Parameter-level resource protection matching."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterator
from typing import Any

from huaweicloud_mcp_core.errors import McpToolError
from huaweicloud_mcp_core.guardrails.rules import ResourceSpec, Rule, load_rules


def extract_tag_set(value: Any) -> set[str]:
    """Normalize a tags value (dict / list of 'k=v' / list of 'k') into a set."""
    tags: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            tags.add(f"{key}={item}" if item is not None else str(key))
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str):
                tags.add(item)
            elif isinstance(item, dict):
                if "key" in item:
                    tag_key = str(item["key"])
                    tags.add(tag_key)
                    if item.get("value") is not None:
                        tags.add(f"{tag_key}={item['value']}")
                else:
                    tags.update(extract_tag_set(item))
    return tags


def match_resource(
    spec: ResourceSpec,
    *,
    resource_id: str | None = None,
    name: str | None = None,
    tags: set[str] | None = None,
) -> str | None:
    """Match a concrete resource (id/name/tags) against a rule's resource spec."""
    if resource_id:
        if resource_id in spec.ids:
            return "id"
        for prefix in spec.id_prefixes:
            if resource_id.startswith(prefix):
                return f"prefix:{prefix}"
    if name:
        for pattern in spec.regexes:
            if pattern.search(name):
                return f"name:{pattern.pattern}"
    if tags:
        actual: dict[str, str | None] = {}
        for tag in tags:
            if "=" in tag:
                key, value = tag.split("=", 1)
                actual[key] = value
            else:
                actual.setdefault(tag, None)
        for wanted in spec.tags:
            if "=" in wanted:
                key, value = wanted.split("=", 1)
                if actual.get(key) == value:
                    return f"tag:{wanted}"
            elif wanted in actual:
                return f"tag:{wanted}"
    return None


def _iter_strings(key: str, value: Any) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(key, item)
    elif isinstance(value, dict):
        for sub_key, sub_value in value.items():
            yield from _iter_strings(sub_key, sub_value)


def match_arguments(spec: ResourceSpec, arguments: dict[str, Any]) -> str | None:
    """Parameter-level matching: ids, id prefixes, name-like params, tags params."""
    for key, value in arguments.items():
        for field_key, text in _iter_strings(key, value):
            if text in spec.ids:
                return "id"
            for prefix in spec.id_prefixes:
                if text.startswith(prefix):
                    return f"prefix:{prefix}"
            if "name" in field_key.lower():
                for pattern in spec.regexes:
                    if pattern.search(text):
                        return f"name:{pattern.pattern}"
    for key, value in arguments.items():
        if "tag" in key.lower():
            hit = match_resource(spec, tags=extract_tag_set(value))
            if hit:
                return hit
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if "tag" in sub_key.lower():
                    hit = match_resource(spec, tags=extract_tag_set(sub_value))
                    if hit:
                        return hit
    return None


def assert_not_protected(
    resource: dict[str, Any],
    rules: list[Rule] | None = None,
    tool_name: str = "",
) -> None:
    """Second defense line: check a resource's real cloud attributes (id/name/tags)."""
    rules = rules if rules is not None else load_rules()
    tags = extract_tag_set(resource.get("tags") or {})
    for rule in rules:
        if (
            rule.tools
            and tool_name
            and not any(fnmatch.fnmatchcase(tool_name, pattern) for pattern in rule.tools)
        ):
            continue
        hit = match_resource(
            rule.resources,
            resource_id=str(resource.get("id") or "") or None,
            name=str(resource.get("name") or "") or None,
            tags=tags or None,
        )
        if hit:
            raise McpToolError(
                code="MCP_GUARDRAIL_BLOCKED",
                message=rule.message or f"Resource matches protection rule '{rule.id}' ({hit}).",
                hint=(
                    f"Request an exemption for rule '{rule.id}' or remove the resource "
                    "from the protection list (HUAWEICLOUD_MCP_PROTECTED_* or "
                    "guardrails.yaml)."
                ),
            )
