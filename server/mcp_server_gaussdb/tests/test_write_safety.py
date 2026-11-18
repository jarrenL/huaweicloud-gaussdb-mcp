"""Regression tests for generic write lanes, protection and payment bypasses."""

from dataclasses import replace
from typing import Any

import pytest
from huaweicloud_mcp_core import McpToolError, ToolRisk

from mcp_huaweicloud_gaussdb.openapi_catalog import classify_risk, operations
from mcp_huaweicloud_gaussdb.service.openapi_service import OpenApiService
from mcp_huaweicloud_gaussdb.service.write_safety import require_manual_payment


class Client:
    def __init__(self) -> None:
        self.lookups: list[str] = []
        self.writes: list[str] = []
        self.missing = False

    async def list_database_instances(self, **arguments: Any) -> dict[str, Any]:
        instance_id = arguments["instance_id"]
        self.lookups.append(instance_id)
        return {
            "instances": []
            if self.missing
            else [
                {"id": instance_id, "name": "production", "tags": [{"key": "env", "value": "prod"}]}
            ]
        }

    async def invoke_openapi(self, *, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(operation)
        return {"ok": True}


@pytest.mark.parametrize(
    "name", ["reset_pwd", "set_db_user_pwd", "run_instance_action", "restart_instance"]
)
def test_disruptive_operations_require_dangerous_lane(name: str) -> None:
    assert classify_risk(name) is ToolRisk.DANGEROUS


async def test_new_sdk_operation_is_not_implicitly_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    metadata = replace(operations()["update_instance_name"], name="future_update_instance")
    monkeypatch.setitem(operations(), metadata.name, metadata)
    client = Client()
    with pytest.raises(McpToolError) as error:
        service = OpenApiService(client)  # type: ignore[arg-type]
        await service.invoke(operation=metadata.name, request={}, required_risk=ToolRisk.WRITE)
    assert error.value.code == "MCP_UNREVIEWED_OPERATION" and not client.writes


@pytest.mark.parametrize(
    "operation",
    [
        "create_database_instance",
        "create_db_instance",
        "create_gauss_db_instance",
        "create_instance",
    ],
)
async def test_creation_aliases_cannot_bypass_dedicated_validation(operation: str) -> None:
    client = Client()
    with pytest.raises(McpToolError) as error:
        service = OpenApiService(client)  # type: ignore[arg-type]
        await service.invoke(operation=operation, request={}, required_risk=ToolRisk.WRITE)
    assert error.value.code == "MCP_DEDICATED_TOOL_REQUIRED" and not client.writes


async def test_nested_batch_targets_are_all_checked_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = Client()
    service = OpenApiService(client)  # type: ignore[arg-type]
    await service._protect_targets({"body": {"instance_ids": ["b", "a"]}}, ToolRisk.WRITE)
    assert client.lookups == ["a", "b"]
    monkeypatch.setenv("HUAWEICLOUD_MCP_PROTECTED_TAGS", "env=prod")
    with pytest.raises(McpToolError) as error:
        await service.invoke(
            operation="update_instance_name",
            request={"instance_id": "a", "body": {"name": "new"}},
            required_risk=ToolRisk.WRITE,
        )
    assert error.value.code == "MCP_GUARDRAIL_BLOCKED" and not client.writes
    with pytest.raises(McpToolError, match="Cannot verify"):
        await service._protect_targets({"backup_id": "unknown-parent"}, ToolRisk.DANGEROUS)
    monkeypatch.delenv("HUAWEICLOUD_MCP_PROTECTED_TAGS")
    client.missing = True
    with pytest.raises(McpToolError, match="Cannot verify"):
        await service._protect_targets({"instance_id": "missing"}, ToolRisk.DANGEROUS)


@pytest.mark.parametrize("value", [True, "true", "True", "yes", "1", 1, {}])
def test_automatic_payment_and_renewal_are_rejected(value: Any) -> None:
    for key in ("is_auto_pay", "is_auto_renew"):
        with pytest.raises(McpToolError, match="Automatic"):
            require_manual_payment({"body": [{"charge_info": {key: value}}]})
    require_manual_payment({"body": {"is_auto_pay": "false", "is_auto_renew": False}})


async def test_dedicated_changes_cannot_auto_pay(settings: Any, fake_client: Any) -> None:
    from mcp_huaweicloud_gaussdb.service.gaussdb_service import GaussDBService

    service = GaussDBService(client=fake_client, settings=settings)
    for method, arguments in (
        (service.create_instance, {"configuration": {"charge_info": {"is_auto_pay": True}}}),
        (service.resize_instance, {"instance_id": "i", "flavor_ref": "f", "is_auto_pay": True}),
        (
            service.expand_instance,
            {"instance_id": "i", "new_volume_size_gb": 80, "is_auto_pay": True},
        ),
    ):
        with pytest.raises(McpToolError, match="Automatic"):
            await method(**arguments)
    assert not fake_client.calls


async def test_cloud_resource_warn_and_confirm_actions_preserve_semantics(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "rules.yaml"
    monkeypatch.setenv("HUAWEICLOUD_MCP_GUARDRAILS_CONFIG", str(config))
    service = OpenApiService(Client())  # type: ignore[arg-type]
    for action in ("warn", "confirm"):
        config.write_text(
            f"rules:\n  - id: cloud-tag\n    action: {action}\n"
            "    match:\n      resources:\n        tags: [env=prod]\n"
        )
        if action == "warn":
            result = await service.invoke(
                operation="update_instance_name",
                request={"instance_id": "i"},
                required_risk=ToolRisk.WRITE,
            )

            assert result["warnings"][0]["rule_id"] == "cloud-tag"
        else:
            with pytest.raises(McpToolError) as error:
                await service._protect_targets({"instance_id": "i"}, ToolRisk.WRITE)
            assert error.value.code == "MCP_CONFIRMATION_REQUIRED"
            assert (
                await service._protect_targets({"instance_id": "i"}, ToolRisk.WRITE, confirm=True)
                == []
            )


async def test_operation_scoped_rule_cannot_be_bypassed_by_generic_tool(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "rules.yaml"
    config.write_text(
        "rules:\n  - id: stop-rename\n    action: block\n"
        "    match:\n      tools: [update_instance_name]\n"
    )
    monkeypatch.setenv("HUAWEICLOUD_MCP_GUARDRAILS_CONFIG", str(config))
    client = Client()
    with pytest.raises(McpToolError, match="stop-rename"):
        await OpenApiService(client).invoke(  # type: ignore[arg-type]
            operation="update_instance_name",
            request={"instance_id": "i"},
            required_risk=ToolRisk.WRITE,
        )
    assert not client.writes and not client.lookups
