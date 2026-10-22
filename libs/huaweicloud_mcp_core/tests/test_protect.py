# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Tests for parameter-level protection matching."""

from __future__ import annotations

import pytest

from huaweicloud_mcp_core.errors import McpToolError
from huaweicloud_mcp_core.guardrails.protect import (
    assert_not_protected,
    extract_tag_set,
    match_arguments,
    match_resource,
)
from huaweicloud_mcp_core.guardrails.rules import ResourceSpec, Rule


def test_cloud_tag_arrays_keep_key_and_value_protection() -> None:
    tags = extract_tag_set([{"key": "env", "value": "prod"}, {"key": "locked"}])
    assert {"env", "env=prod", "locked"} <= tags
    assert match_resource(ResourceSpec(tags=("env=prod",)), tags=tags) == "tag:env=prod"


SPEC = ResourceSpec(
    ids=("stack-123",),
    id_prefixes=("prod-",),
    name_patterns=(r"^prod-.*$",),
    tags=("env=prod", "critical"),
)


def test_match_resource_by_id() -> None:
    assert match_resource(SPEC, resource_id="stack-123") == "id"


def test_match_resource_by_prefix() -> None:
    assert match_resource(SPEC, resource_id="prod-abc") == "prefix:prod-"


def test_match_resource_by_name_regex() -> None:
    assert match_resource(SPEC, name="prod-web") is not None


def test_match_resource_by_tag_key_value() -> None:
    assert match_resource(SPEC, tags={"env=prod", "app=web"}) is not None


def test_match_resource_by_bare_tag_key() -> None:
    assert match_resource(SPEC, tags={"critical"}) is not None


def test_match_resource_no_hit() -> None:
    assert match_resource(SPEC, resource_id="stack-9", name="dev-web", tags={"env=dev"}) is None


def test_match_arguments_id_in_params() -> None:
    assert match_arguments(SPEC, {"stack_id": "stack-123"}) == "id"


def test_match_arguments_prefix_in_nested_list() -> None:
    args = {"resources": [{"id": "prod-xyz"}, {"id": "dev-1"}]}
    assert match_arguments(SPEC, args) == "prefix:prod-"


def test_match_arguments_name_like_key() -> None:
    assert match_arguments(SPEC, {"stack_name": "prod-web"}) is not None


def test_match_arguments_tags_param() -> None:
    assert match_arguments(SPEC, {"tags": {"env": "prod"}}) is not None


def test_match_arguments_no_match() -> None:
    assert match_arguments(SPEC, {"stack_name": "dev-web", "tags": {"env": "dev"}}) is None


def test_extract_tag_set_variants() -> None:
    assert extract_tag_set({"env": "prod"}) == {"env=prod"}
    assert extract_tag_set(["env=prod", "critical"]) == {"env=prod", "critical"}
    assert extract_tag_set({"key": None}) == {"key"}
    assert extract_tag_set("not-a-tag") == set()


def test_assert_not_protected_blocks_matching_resource() -> None:
    rules = [
        Rule(
            id="protect-prod",
            action="block",
            tools=("delete_*",),
            resources=ResourceSpec(name_patterns=(r"^prod-",)),
        )
    ]
    with pytest.raises(McpToolError) as excinfo:
        assert_not_protected(
            {"id": "sid-1", "name": "prod-web", "tags": {}}, rules, tool_name="delete_stack"
        )
    assert excinfo.value.code == "MCP_GUARDRAIL_BLOCKED"
    assert "protect-prod" in (excinfo.value.hint or "")


def test_assert_not_protected_ignores_other_tools() -> None:
    rules = [
        Rule(
            id="protect-prod",
            action="block",
            tools=("delete_*",),
            resources=ResourceSpec(name_patterns=(r"^prod-",)),
        )
    ]
    assert_not_protected(
        {"id": "sid-1", "name": "prod-web", "tags": {}}, rules, tool_name="deploy_stack"
    )


def test_assert_not_protected_passes_unprotected_resource() -> None:
    rules = [Rule(id="protect-prod", action="block", resources=ResourceSpec(ids=("other",)))]
    assert_not_protected(
        {"id": "sid-1", "name": "dev-web", "tags": {}}, rules, tool_name="delete_stack"
    )
