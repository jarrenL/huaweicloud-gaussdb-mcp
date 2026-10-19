"""Security, configuration and output-contract tests for the shared runtime."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.types import CallToolResult, TextContent

from huaweicloud_mcp_core import (
    McpSettings,
    McpToolError,
    ToolRisk,
    build_server,
    clamp_limit,
    guard,
    page_result,
    single_result,
)
from huaweicloud_mcp_core.config import _env_bool
from huaweicloud_mcp_core.credentials import (
    CredentialScope,
    ProjectContext,
    build_credentials,
    reset_project_cache,
    resolve_project_context,
    resolve_project_id,
)
from huaweicloud_mcp_core.errors import wrap_sdk_error
from huaweicloud_mcp_core.guardrails.audit import AuditLogger
from huaweicloud_mcp_core.guardrails.masking import MASK, MaskingEngine
from huaweicloud_mcp_core.guardrails.middleware import GuardrailsMiddleware
from huaweicloud_mcp_core.guardrails.protect import assert_not_protected
from huaweicloud_mcp_core.guardrails.rules import (
    ResourceSpec,
    Rule,
    RuleHit,
    evaluate_rules,
    extract_tag_set,
    load_rules,
    match_arguments,
    match_resource,
    strictest_hit,
)
from huaweicloud_mcp_core.server import run_standard


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("HUAWEICLOUD_") or key.startswith("MCP_SERVER_"):
            monkeypatch.delenv(key, raising=False)
    # Keep tests independent from a developer's real devkit account.
    monkeypatch.setenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "1")


def _write_credentials(path: Path, access_key: str) -> None:
    path.write_text(
        json.dumps(
            {
                "access_key": access_key,
                "secret_key": "secret",
                "region": "cn-north-4",
                "project_id": "project",
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def test_credential_file_is_hot_reloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "credentials.json"
    _write_credentials(path, "first")
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(path))
    assert McpSettings.from_env().access_key == "first"
    replacement = tmp_path / "credentials.next"
    _write_credentials(replacement, "second")
    replacement.replace(path)
    assert McpSettings.from_env().access_key == "second"


def test_credential_file_permissions_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "credentials.json"
    _write_credentials(path, "first")
    path.chmod(0o644)
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(path))
    with pytest.raises(McpToolError, match="credential file") as caught:
        McpSettings.from_env()
    assert caught.value.code == "MCP_CREDENTIAL_ERROR"


def _write_devkit_credentials(path: Path, access_key: str = "devkit-ak") -> None:
    path.write_text(
        json.dumps(
            {
                "ak": access_key,
                "sk": "devkit-sk",
                "securityToken": "devkit-token",
                "region": "cn-southwest-2",
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o644)


def test_devkit_credentials_are_used_as_permissive_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "devkit.json"
    _write_devkit_credentials(path)
    monkeypatch.delenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS")
    monkeypatch.setenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE", str(path))

    settings = McpSettings.from_env()

    assert settings.access_key == "devkit-ak"
    assert settings.secret_key == "devkit-sk"
    assert settings.security_token == "devkit-token"
    assert settings.region == "cn-southwest-2"


def test_default_devkit_path_is_hot_reloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".config" / "huaweicloud" / "credentials.json"
    path.parent.mkdir(parents=True)
    _write_devkit_credentials(path, "first")
    monkeypatch.delenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS")
    monkeypatch.setenv("HOME", str(tmp_path))

    assert McpSettings.from_env().access_key == "first"
    replacement = path.with_suffix(".next")
    _write_devkit_credentials(replacement, "second")
    replacement.replace(path)
    assert McpSettings.from_env().access_key == "second"


def test_environment_and_mcp_file_override_devkit_by_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mcp_path = tmp_path / "mcp.json"
    _write_credentials(mcp_path, "mcp-ak")
    devkit_path = tmp_path / "devkit.json"
    _write_devkit_credentials(devkit_path)
    monkeypatch.delenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS")
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(mcp_path))
    monkeypatch.setenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE", str(devkit_path))
    monkeypatch.setenv("HUAWEICLOUD_ACCESS_KEY", "env-ak")
    monkeypatch.setenv("HUAWEICLOUD_REGION", "cn-north-4")

    settings = McpSettings.from_env()

    assert settings.access_key == "env-ak"
    assert settings.secret_key == "secret"
    assert settings.region == "cn-north-4"
    assert settings.project_id == "project"
    assert settings.security_token is None


def test_devkit_fills_only_missing_explicit_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "devkit.json"
    _write_devkit_credentials(path)
    monkeypatch.delenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS")
    monkeypatch.setenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE", str(path))
    monkeypatch.setenv("HUAWEICLOUD_ACCESS_KEY", "env-ak")
    monkeypatch.setenv("HUAWEICLOUD_REGION", "cn-north-4")

    settings = McpSettings.from_env()

    assert settings.access_key == "env-ak"
    assert settings.secret_key == "devkit-sk"
    assert settings.region == "cn-north-4"
    assert settings.security_token == "devkit-token"


def test_devkit_fallback_can_be_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "devkit.json"
    _write_devkit_credentials(path)
    monkeypatch.setenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE", str(path))

    with pytest.raises(McpToolError, match="Missing required configuration"):
        McpSettings.from_env()


def test_explicit_invalid_devkit_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "devkit.json"
    path.write_text("[]", encoding="utf-8")
    path.chmod(0o644)
    monkeypatch.delenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS")
    monkeypatch.setenv("HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE", str(path))

    with pytest.raises(McpToolError, match="huaweicloud-devkit") as caught:
        McpSettings.from_env()
    assert caught.value.code == "MCP_CREDENTIAL_ERROR"


def test_configuration_rejects_invalid_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HUAWEICLOUD_MCP_READ_ONLY", "sometimes")
    with pytest.raises(McpToolError, match="must be true or false"):
        _env_bool("HUAWEICLOUD_MCP_READ_ONLY")

    monkeypatch.setenv("HUAWEICLOUD_MCP_READ_ONLY", "false")
    monkeypatch.setenv("MCP_SERVER_PORT", "70000")
    with pytest.raises(McpToolError, match=r"1\.\.65535"):
        McpSettings.from_env(require_credentials=False)

    monkeypatch.setenv("MCP_SERVER_PORT", "8000")
    with pytest.raises(McpToolError, match="Missing required configuration"):
        McpSettings.from_env()

    path = tmp_path / "credentials.json"
    path.write_text("[]", encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(path))
    with pytest.raises(McpToolError, match="JSON object"):
        McpSettings.from_env()


def test_masking_and_page_contract() -> None:
    masked = MaskingEngine().mask(
        {"access_key": "123", "nested": {"authorization": "Bearer token-value"}}
    )
    assert masked["access_key"] == MASK
    assert masked["nested"]["authorization"] == MASK
    page = page_result([{"value": "x" * 2100}], total=2, marker="next")
    assert len(page["items"][0]["value"]) == 2000
    assert page["items"][0]["_truncated"] is True
    assert page["truncated"] is True
    assert clamp_limit(0) == 1 and clamp_limit(200) == 100
    assert single_result({"value": "x"}, ["hint"])["hints"] == ["hint"]


def test_credentials_errors_protection_audit_and_server(tmp_path: Path) -> None:
    settings = McpSettings(
        access_key="ak",
        secret_key="sk",
        region="cn-north-4",
        project_id="project-id",
        security_token="token",
    )
    assert resolve_project_id(settings) == "project-id"
    assert build_credentials(CredentialScope.PROJECT, settings) is not None
    assert build_credentials(CredentialScope.GLOBAL, settings) is not None

    class SdkError(Exception):
        status_code = 403
        error_code = "IAM.403"
        error_msg = "denied"
        request_id = "request-id"

    sdk_error = SdkError()
    wrapped = wrap_sdk_error(sdk_error)
    assert wrapped.to_dict()["error"]["request_id"] == "request-id"
    documented = McpToolError("CODE", "message", doc_url="https://example.test/error")
    assert documented.to_dict()["error"]["doc_url"] == "https://example.test/error"

    protected = Rule("protect", "block", resources=ResourceSpec(ids=("prod-1",)))
    with pytest.raises(McpToolError, match="protection rule"):
        assert_not_protected({"id": "prod-1"}, [protected], "delete_instance")

    audit_path = tmp_path / "audit.jsonl"
    AuditLogger(str(audit_path)).emit({"params": {"secret": "value"}})
    assert json.loads(audit_path.read_text(encoding="utf-8"))["params"]["secret"] == MASK
    server = build_server("test", settings, version="1.2.3")
    assert server.name == "huaweicloud-test"
    assert server.version == "1.2.3"


def test_project_discovery_uses_configured_iam_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from huaweicloudsdkiam.v3 import IamClient

    class Builder:
        endpoint = ""

        def with_credentials(self, credentials: object) -> "Builder":
            return self

        def with_endpoint(self, endpoint: str) -> "Builder":
            self.endpoint = endpoint
            return self

        def build(self) -> "Builder":
            return self

        def keystone_list_projects(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(
                projects=[SimpleNamespace(id="discovered-project", domain_id="domain-id")]
            )

    builder = Builder()
    monkeypatch.setattr(IamClient, "new_builder", lambda: builder)
    reset_project_cache()
    settings = McpSettings(
        access_key="ak",
        secret_key="sk",
        region="cn-north-4",
        iam_endpoint="https://iam.example.test",
    )
    assert resolve_project_id(settings) == "discovered-project"
    assert builder.endpoint == "https://iam.example.test"
    assert resolve_project_context(settings) == ProjectContext("discovered-project", "domain-id")


def test_project_context_direct_and_discovery_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from huaweicloudsdkiam.v3 import IamClient

    direct = McpSettings(
        access_key="ak",
        secret_key="sk",
        region="cn-north-4",
        project_id="project",
        domain_id="domain",
    )
    assert resolve_project_context(direct) == ProjectContext("project", "domain")

    class EmptyBuilder:
        def with_credentials(self, credentials: object) -> "EmptyBuilder":
            return self

        def with_endpoint(self, endpoint: str) -> "EmptyBuilder":
            return self

        def build(self) -> "EmptyBuilder":
            return self

        def keystone_list_projects(self, request: object) -> SimpleNamespace:
            return SimpleNamespace(projects=[])

    monkeypatch.setattr(IamClient, "new_builder", lambda: EmptyBuilder())
    reset_project_cache()
    discovery = McpSettings(access_key="empty", secret_key="sk", region="cn-north-4")
    with pytest.raises(McpToolError) as excinfo:
        resolve_project_context(discovery)
    assert excinfo.value.code == "MCP_PROJECT_NOT_FOUND"

    class BrokenBuilder(EmptyBuilder):
        def keystone_list_projects(self, request: object) -> SimpleNamespace:
            raise RuntimeError("private IAM failure")

    monkeypatch.setattr(IamClient, "new_builder", lambda: BrokenBuilder())
    reset_project_cache()
    broken = McpSettings(access_key="broken", secret_key="sk", region="cn-north-4")
    with pytest.raises(McpToolError, match="Could not discover"):
        resolve_project_context(broken)


def test_rules_load_match_and_reject_duplicate_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "guardrails.yaml"
    path.write_text(
        """rules:
  - id: protect-prod
    action: block
    match:
      tools: [restart_*]
      risks: [WRITE]
      resources:
        id_prefixes: [prod-]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HUAWEICLOUD_MCP_GUARDRAILS_CONFIG", str(path))
    rules = load_rules()
    hits = evaluate_rules(rules, "restart_instance", ToolRisk.WRITE, {"instance_id": "prod-1"})
    assert [hit.rule.id for hit in hits] == ["protect-prod"]
    path.write_text(
        """rules:
  - {id: duplicate, action: warn}
  - {id: duplicate, action: block}
""",
        encoding="utf-8",
    )
    with pytest.raises(McpToolError, match="unique"):
        load_rules()


def test_environment_protection_rules_and_resource_matching() -> None:
    settings = McpSettings(
        protected_ids=("id-1",),
        protected_names=("production",),
        protected_tags=("environment=prod",),
    )
    rules = load_rules(settings)
    assert [rule.id for rule in rules] == [
        "env-protected-ids",
        "env-protected-names",
        "env-protected-tags",
    ]
    assert match_resource(rules[0].resources, resource_id="id-1") == "id"
    assert match_resource(rules[1].resources, name="production") == "name:^production$"
    assert (
        match_resource(rules[2].resources, tags=extract_tag_set({"environment": "prod"}))
        == "tag:environment=prod"
    )
    nested = {"resource": {"id": "prefix-123"}, "tags": ["team=db"]}
    assert match_arguments(ResourceSpec(id_prefixes=("prefix-",)), nested) == "prefix:prefix-"
    assert match_arguments(ResourceSpec(tags=("team=db",)), nested) == "tag:team=db"

    unrelated = Rule("unrelated", "warn", tools=("list_*",))
    assert evaluate_rules([unrelated], "delete_instance", ToolRisk.DANGEROUS, {}) == []
    hits = [RuleHit(Rule("warn", "warn"), "all"), RuleHit(Rule("block", "block"), "all")]
    assert strictest_hit(hits).rule.id == "block"  # type: ignore[union-attr]
    assert strictest_hit([]) is None


def test_invalid_guardrail_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "guardrails.yaml"
    path.write_text("rules:\n  - {id: bad, action: unsupported}\n", encoding="utf-8")
    monkeypatch.setenv("HUAWEICLOUD_MCP_GUARDRAILS_CONFIG", str(path))
    with pytest.raises(McpToolError) as excinfo:
        load_rules()
    assert excinfo.value.code == "MCP_GUARDRAIL_ERROR"


@guard(risk=ToolRisk.DANGEROUS)
async def _dangerous_test_tool(confirm: bool = False) -> dict[str, bool]:
    return {"confirm": confirm}


@guard(risk=ToolRisk.WRITE)
async def _write_test_tool() -> dict[str, bool]:
    return {"ok": True}


@guard(risk=ToolRisk.DANGEROUS)
async def _dangerous_without_confirm() -> dict[str, bool]:
    return {"ok": True}


@guard(risk=ToolRisk.READ)
async def _read_error_tool() -> dict[str, bool]:
    raise McpToolError("EXPECTED", "read failed")


async def _run_middleware(
    tool_name: str,
    arguments: dict[str, Any],
    rules: list[Rule],
    result: Any | None = None,
) -> tuple[Any, bool]:
    middleware = GuardrailsMiddleware(read_only=False, rules=rules, audit=AuditLogger())
    context = SimpleNamespace(
        method="tools/call", params={"name": tool_name, "arguments": arguments}
    )
    called = False

    async def next_call(ctx: Any) -> Any:
        nonlocal called
        called = True
        return result if result is not None else {"ok": True}

    return await middleware(context, next_call), called  # type: ignore[arg-type]


async def test_middleware_block_confirm_and_warn() -> None:
    block = Rule("block-prod", "block", resources=ResourceSpec(ids=("prod-1",)))
    blocked, called = await _run_middleware("_write_test_tool", {"instance_id": "prod-1"}, [block])
    assert blocked.structured_content["error"]["code"] == "MCP_GUARDRAIL_BLOCKED"
    assert called is False

    confirm = Rule("confirm-change", "confirm")
    required, called = await _run_middleware("_dangerous_test_tool", {"confirm": False}, [confirm])
    assert required.structured_content["confirmation_required"] is True
    assert called is False
    approved, called = await _run_middleware("_dangerous_test_tool", {"confirm": True}, [confirm])
    assert approved == {"ok": True}
    assert called is True

    warn = Rule("warn-change", "warn", message="maintenance window recommended")
    warned, called = await _run_middleware(
        "_write_test_tool",
        {},
        [warn],
        result=CallToolResult(
            content=[TextContent(type="text", text='{"ok":true}')],
            structured_content={"ok": True},
        ),
    )
    assert called is True
    assert warned.structured_content["warnings"] == [
        {"rule_id": "warn-change", "message": "maintenance window recommended"}
    ]


async def test_guard_wrapper_and_middleware_failure_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await _read_error_tool() == {
        "error": {
            "code": "EXPECTED",
            "message": "read failed",
            "hint": "Inspect the error message and adjust the tool call.",
        }
    }

    unknown, called = await _run_middleware("unregistered", {}, [])
    assert unknown.structured_content["error"]["code"] == "MCP_GUARDRAIL_ERROR"
    assert called is False

    middleware = GuardrailsMiddleware(read_only=True, rules=[], audit=AuditLogger())
    context = SimpleNamespace(
        method="tools/call", params=SimpleNamespace(name="_write_test_tool", arguments={})
    )
    called = False

    async def next_call(ctx: Any) -> Any:
        nonlocal called
        called = True
        return {"secret_key": "must-mask"}

    blocked = await middleware(context, next_call)  # type: ignore[arg-type]
    assert blocked.structured_content["error"]["code"] == "MCP_READ_ONLY"
    assert called is False

    passthrough_context = SimpleNamespace(method="resources/list", params={})
    passed = await middleware(passthrough_context, next_call)  # type: ignore[arg-type]
    assert passed["secret_key"] == "must-mask"

    no_confirm, _ = await _run_middleware("_dangerous_without_confirm", {}, [])
    assert no_confirm.structured_content["error"]["code"] == "MCP_GUARDRAIL_BLOCKED"

    def fail_rules(*args: Any, **kwargs: Any) -> list[RuleHit]:
        raise RuntimeError("rule engine failed")

    monkeypatch.setattr("huaweicloud_mcp_core.guardrails.middleware.evaluate_rules", fail_rules)
    read_result, called = await _run_middleware(
        "_read_error_tool", {}, [], result={"secret_key": "value"}
    )
    assert read_result["secret_key"] == MASK
    assert called is True
    write_result, called = await _run_middleware("_write_test_tool", {}, [])
    assert write_result.structured_content["error"]["code"] == "MCP_GUARDRAIL_ERROR"
    assert called is False


async def test_middleware_maps_unexpected_tool_failure() -> None:
    middleware = GuardrailsMiddleware(read_only=False, rules=[], audit=AuditLogger())
    context = SimpleNamespace(
        method="tools/call", params={"name": "_write_test_tool", "arguments": {}}
    )

    async def fail(ctx: Any) -> Any:
        raise RuntimeError("private failure")

    result = await middleware(context, fail)  # type: ignore[arg-type]
    assert result.structured_content["error"]["code"] == "MCP_SDK_ERROR"


@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
def test_standard_runner_selects_transport(transport: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    server = SimpleNamespace(run=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr("sys.argv", ["server", "--transport", transport])
    monkeypatch.setenv("MCP_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_SERVER_PORT", "9000")
    run_standard(server, "gaussdb")  # type: ignore[arg-type]
    expected = (
        {"transport": "stdio"}
        if transport == "stdio"
        else {"transport": "streamable-http", "host": "127.0.0.1", "port": 9000}
    )
    assert calls == [expected]
