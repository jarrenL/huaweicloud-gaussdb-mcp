"""OpenAPI catalog completeness, schemas, paging, and risk-lane tests."""

from typing import Any

import pytest
from huaweicloud_mcp_core import McpToolError, ToolRisk

from mcp_server_gaussdb.openapi_catalog import (
    _type_schema,
    classify_risk,
    get_operation,
    operation_schema,
    operations,
)
from mcp_server_gaussdb.service.openapi_service import OpenApiService


def test_catalog_covers_sdk_request_operations() -> None:
    catalog = operations()
    assert len(catalog) >= 250
    assert all(item.request_model.endswith("Request") for item in catalog.values())
    assert {item.risk for item in catalog.values()} == set(ToolRisk)
    assert get_operation("show_deployment_form") is not None
    assert classify_risk("delete_instance") is ToolRisk.DANGEROUS
    assert classify_risk("list_instances") is ToolRisk.READ
    assert classify_risk("batch_show_upgrade_candidate_versions") is ToolRisk.READ
    assert classify_risk("update_instance_name") is ToolRisk.WRITE
    assert classify_risk("modify_security_group") is ToolRisk.DANGEROUS


def test_operation_schema_recurses_nested_models() -> None:
    operation = get_operation("create_database")
    assert operation is not None
    schema = operation_schema(operation)
    assert schema["x-sdk-model"] == "CreateDatabaseRequest"
    assert schema["properties"]["instance_id"]["type"] == "string"
    assert "instance_id" in schema["required"]
    assert "body" in schema["required"]
    assert "实例ID" in schema["properties"]["instance_id"]["description"]
    body = schema["properties"]["body"]
    assert body["x-sdk-model"] == "GaussDBforOpenDatabaseForCreation"
    assert "name" in body["properties"]


def test_type_schema_handles_collections_cycles_and_unknown_sdk_types() -> None:
    assert _type_schema("list[int]", set(), 0) == {
        "type": "array",
        "items": {"type": "integer"},
    }
    assert _type_schema("dict(str, float)", set(), 0) == {
        "type": "object",
        "additionalProperties": {"type": "number"},
    }
    assert _type_schema("dict(str)", set(), 0) == {
        "type": "object",
        "additionalProperties": {},
    }
    assert _type_schema("MissingSdkModel", set(), 0) == {
        "type": "object",
        "x-sdk-model": "MissingSdkModel",
    }
    assert _type_schema("RecursiveModel", {"RecursiveModel"}, 0) == {
        "type": "object",
        "x-sdk-model": "RecursiveModel",
    }


class FakeOpenApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def invoke_openapi(self, *, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((operation, request))
        return {"ok": True}

    async def list_database_instances(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_database_instances", kwargs))
        return {"instances": [{"id": kwargs["instance_id"], "name": "temporary"}]}


async def test_catalog_service_filters_pages_and_describes() -> None:
    service = OpenApiService(client=FakeOpenApiClient())  # type: ignore[arg-type]
    result = await service.list_operations(query="deployment", risk="READ", limit=1)
    assert result["count"] == 1
    assert result["items"][0]["risk"] == "READ"
    assert result["operation_naming"] == "snake_case"
    assert set(result["invoke_arguments"]) == {"operation", "request"}
    described = await service.describe_operation(operation="show_deployment_form")
    assert described["request_schema"]["properties"]["solution"]["type"] == "string"
    tag_delete = await service.describe_operation(operation="delete_instance_tag")
    assert tag_delete["request_example"] == {
        "instance_id": "<instance-id>",
        "key": "environment",
    }
    assert "no body" in tag_delete["request_shape_note"]
    attach_eip = await service.describe_operation(operation="attach_eip")
    assert "VPC/EIP" in attach_eip["prerequisite_note"]
    assert attach_eip["request_example"]["body"]["action"] == "BIND"
    with pytest.raises(McpToolError, match="risk"):
        await service.list_operations(risk="INVALID")
    with pytest.raises(McpToolError, match="not found"):
        await service.describe_operation(operation="not_real")


async def test_openapi_service_enforces_risk_lane() -> None:
    client = FakeOpenApiClient()
    service = OpenApiService(client=client)  # type: ignore[arg-type]
    result = await service.invoke(
        operation="show_deployment_form", request={}, required_risk=ToolRisk.READ
    )
    assert result["result"] == {"ok": True}
    with pytest.raises(McpToolError) as excinfo:
        await service.invoke(
            operation="delete_instance",
            request={"instance_id": "i"},
            required_risk=ToolRisk.WRITE,
        )
    assert excinfo.value.code == "MCP_RISK_MISMATCH"

    result = await service.invoke(
        operation="delete_instance",
        request={"instance_id": "i"},
        required_risk=ToolRisk.DANGEROUS,
    )
    assert result["risk"] == "DANGEROUS"
    assert [name for name, _ in client.calls[-2:]] == [
        "list_database_instances",
        "delete_instance",
    ]

    result = await service.invoke(
        operation="attach_eip",
        request={
            "instance_id": "i",
            "node_id": "n",
            "body": {"action": "BIND", "public_ip": "192.0.2.1", "public_ip_id": "eip"},
        },
        required_risk=ToolRisk.DANGEROUS,
    )
    assert any("VPC/EIP" in hint for hint in result["hints"])
    assert any("list_binded_eips" in hint for hint in result["hints"])

    with pytest.raises(McpToolError) as excinfo:
        await service.invoke(
            operation="update_instance_configuration",
            request={"instance_id": "i", "body": {"values": {"work_mem": "4MB"}}},
            required_risk=ToolRisk.WRITE,
        )
    assert excinfo.value.code == "MCP_DEDICATED_TOOL_REQUIRED"
    assert all(name != "update_instance_configuration" for name, _ in client.calls)

    with pytest.raises(McpToolError) as excinfo:
        await service.invoke(
            operation="delete_instance_tag",
            request={"instance_id": "i", "body": {"key": "environment"}},
            required_risk=ToolRisk.DANGEROUS,
        )
    assert excinfo.value.code == "MCP_INVALID_ARGS"
    assert "top-level query field" in excinfo.value.message

    with pytest.raises(McpToolError) as excinfo:
        await service.invoke(operation="not_real", request={}, required_risk=ToolRisk.READ)
    assert excinfo.value.code == "MCP_NOT_FOUND"


async def test_openapi_service_maps_request_shape_errors() -> None:
    class InvalidRequestClient(FakeOpenApiClient):
        async def invoke_openapi(
            self, *, operation: str, request: dict[str, Any]
        ) -> dict[str, Any]:
            raise ValueError("Unknown request field: body.bad")

    service = OpenApiService(client=InvalidRequestClient())  # type: ignore[arg-type]
    with pytest.raises(McpToolError) as excinfo:
        await service.invoke(
            operation="show_deployment_form",
            request={"bad": True},
            required_risk=ToolRisk.READ,
        )
    assert excinfo.value.code == "MCP_INVALID_ARGS"
    assert "describe_openapi_operation" in (excinfo.value.hint or "")
