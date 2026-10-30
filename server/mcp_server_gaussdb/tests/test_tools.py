"""Tool registration, risk declarations, pass-through and middleware tests."""

from types import SimpleNamespace
from typing import Any

from huaweicloud_mcp_core.errors import McpToolError
from huaweicloud_mcp_core.guardrails.audit import AuditLogger
from huaweicloud_mcp_core.guardrails.middleware import GuardrailsMiddleware
from huaweicloud_mcp_core.security import ToolRisk, get_tool_risk, tool_supports_confirm

from mcp_server_gaussdb.server import mcp
from mcp_server_gaussdb.tools import backup, billing, instance, monitoring, observability, openapi

EXPECTED = {
    "get_order": ToolRisk.READ,
    "cancel_order": ToolRisk.DANGEROUS,
    "list_instances": ToolRisk.READ,
    "get_instance": ToolRisk.READ,
    "list_flavors": ToolRisk.READ,
    "discover_create_options": ToolRisk.READ,
    "create_instance": ToolRisk.WRITE,
    "delete_instance": ToolRisk.DANGEROUS,
    "resize_instance": ToolRisk.WRITE,
    "expand_instance": ToolRisk.WRITE,
    "restart_instance": ToolRisk.WRITE,
    "get_instance_parameters": ToolRisk.READ,
    "update_instance_parameters": ToolRisk.WRITE,
    "list_backups": ToolRisk.READ,
    "create_manual_backup": ToolRisk.WRITE,
    "get_backup_policy": ToolRisk.READ,
    "configure_backup_policy": ToolRisk.WRITE,
    "analyze_slow_sql": ToolRisk.READ,
    "get_job": ToolRisk.READ,
    "wait_job": ToolRisk.READ,
    "list_monitoring_metrics": ToolRisk.READ,
    "query_monitoring_metrics": ToolRisk.READ,
    "list_openapi_operations": ToolRisk.READ,
    "describe_openapi_operation": ToolRisk.READ,
    "invoke_read_openapi": ToolRisk.READ,
    "invoke_write_openapi": ToolRisk.WRITE,
    "invoke_dangerous_openapi": ToolRisk.DANGEROUS,
}


async def test_tools_registered_and_guarded() -> None:
    tools = await mcp.list_tools()
    assert mcp.version == "0.6.0"
    assert {tool.name for tool in tools} == set(EXPECTED)
    assert {name: get_tool_risk(name) for name in EXPECTED} == EXPECTED
    assert all(
        tool_supports_confirm(name)
        for name, risk in EXPECTED.items()
        if risk in {ToolRisk.WRITE, ToolRisk.DANGEROUS}
    )
    assert all(tool.description and "Scenario:" in tool.description for tool in tools)


class StubService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        async def call(**kwargs: Any) -> dict[str, Any]:
            self.calls.append((name, kwargs))
            return {"called": name}

        return call


async def test_all_tools_pass_arguments(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    stub = StubService()
    for module in (backup, instance, observability):
        monkeypatch.setattr(module, "GaussDBService", lambda: stub)
    monkeypatch.setattr(openapi, "OpenApiService", lambda: stub)
    monkeypatch.setattr(monitoring, "MonitoringService", lambda: stub)
    monkeypatch.setattr(billing, "BillingService", lambda: stub)
    await billing.get_order("ORDER")
    await billing.cancel_order("ORDER", confirm=True)
    assert await instance.list_instances() == {"called": "list_instances"}
    await instance.get_instance("i")
    await instance.list_flavors()
    await instance.discover_create_options()
    await instance.create_instance({})
    await instance.delete_instance("i", confirm=True)
    await instance.resize_instance("i", "f")
    await instance.expand_instance("i", new_volume_size_gb=400)
    await instance.restart_instance("i")
    await instance.get_instance_parameters("i")
    await instance.update_instance_parameters("i", {"a": "b"})
    await backup.list_backups("i")
    await backup.create_manual_backup("i", "Backup1")
    await backup.get_backup_policy("i")
    await backup.configure_backup_policy("i", 7, "21:00-22:00", "1")
    await observability.analyze_slow_sql("i", ["n"], 1, 2)
    await monitoring.list_monitoring_metrics("i")
    await monitoring.query_monitoring_metrics("i", [], 1, 2)
    await observability.get_job("j")
    await observability.wait_job("j", timeout_seconds=30, poll_interval_seconds=2)
    await openapi.list_openapi_operations()
    await openapi.describe_openapi_operation("show_deployment_form")
    await openapi.invoke_read_openapi("show_deployment_form", {})
    await openapi.invoke_write_openapi("update_instance_name", {}, confirm=True)
    await openapi.invoke_dangerous_openapi("delete_manual_backup", {}, confirm=True)
    openapi_tools = {
        "list_openapi_operations",
        "describe_openapi_operation",
        "invoke_read_openapi",
        "invoke_write_openapi",
        "invoke_dangerous_openapi",
    }
    assert {name for name, _ in stub.calls} == (
        set(EXPECTED) - openapi_tools - {"list_monitoring_metrics", "query_monitoring_metrics"}
    ) | {
        "list_metrics",
        "query_metrics",
        "list_operations",
        "describe_operation",
        "invoke",
    }


async def test_guard_converts_tool_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Failing:
        async def get_instance(self, **kwargs: Any) -> dict[str, Any]:
            raise McpToolError("MCP_NOT_FOUND", "missing", hint="run list_instances")

    monkeypatch.setattr(instance, "GaussDBService", Failing)
    result = await instance.get_instance("none")
    assert result["error"]["code"] == "MCP_NOT_FOUND"


async def test_read_only_middleware_blocks_write() -> None:
    middleware = GuardrailsMiddleware(read_only=True, rules=[], audit=AuditLogger())
    context = SimpleNamespace(
        method="tools/call",
        params={"name": "restart_instance", "arguments": {"instance_id": "i"}},
    )
    called = False

    async def next_call(ctx):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        return {"ok": True}

    result = await middleware(context, next_call)  # type: ignore[arg-type]
    assert result.structured_content["error"]["code"] == "MCP_READ_ONLY"
    assert called is False


async def test_dangerous_tool_requires_confirmation() -> None:
    middleware = GuardrailsMiddleware(read_only=False, rules=[], audit=AuditLogger())
    context = SimpleNamespace(
        method="tools/call",
        params={"name": "delete_instance", "arguments": {"instance_id": "i"}},
    )
    called = False

    async def next_call(ctx):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        return {"ok": True}

    result = await middleware(context, next_call)  # type: ignore[arg-type]
    assert result.structured_content["confirmation_required"] is True
    assert called is False

    context.params["arguments"]["confirm"] = True
    assert await middleware(context, next_call) == {"ok": True}  # type: ignore[arg-type]
    assert called is True
