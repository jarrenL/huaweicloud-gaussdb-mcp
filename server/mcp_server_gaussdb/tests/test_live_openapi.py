"""Opt-in Huawei Cloud contract tests; the billed test always deletes its temporary instance."""

import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from huaweicloud_mcp_core import McpSettings, ToolRisk

from mcp_server_gaussdb.client.gaussdb_client import GaussDBClient
from mcp_server_gaussdb.service.gaussdb_service import GaussDBService
from mcp_server_gaussdb.service.openapi_service import OpenApiService

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("HUAWEICLOUD_MCP_LIVE_TEST") != "1",
        reason="set HUAWEICLOUD_MCP_LIVE_TEST=1 to run Huawei Cloud contract tests",
    ),
]


async def _wait_job(service: GaussDBService, job_id: str, timeout: int = 1500) -> dict[str, Any]:
    job = await service.wait_job(
        job_id=job_id,
        timeout_seconds=min(timeout, 1800),
        poll_interval_seconds=10,
    )
    if job["timed_out"]:
        raise TimeoutError(f"job {job_id} did not finish within {timeout} seconds")
    return job


@pytest.mark.parametrize(
    ("operation", "request_data"),
    [
        ("list_datastores", {}),
        ("list_flavors_details", {"ha_mode": "centralization_standard", "limit": 5}),
        ("show_project_quotas", {}),
        ("list_enterprise_projects", {}),
        ("list_project_tags", {}),
        ("list_predefined_tags", {}),
        ("list_recycle_instances", {"limit": 5}),
        ("list_configurations", {"limit": 5}),
        ("list_tasks", {"limit": 5}),
        ("list_events", {"limit": 5}),
        ("list_storage_types", {"version": "10.0.0", "ha_mode": "centralization_standard"}),
        ("list_kms_tde_key", {"kms_project_name": "cn-north-4"}),
    ],
)
async def test_live_project_read_operations(operation: str, request_data: dict[str, Any]) -> None:
    result = await OpenApiService().invoke(
        operation=operation, request=request_data, required_risk=ToolRisk.READ
    )
    assert result["operation"] == operation
    assert "error" not in result


@pytest.mark.skipif(
    os.getenv("HUAWEICLOUD_MCP_LIVE_ALLOW_BILLING") != "1",
    reason="set HUAWEICLOUD_MCP_LIVE_ALLOW_BILLING=1 to create a temporary single replica",
)
async def test_live_basic_single_replica_lifecycle() -> None:
    settings = McpSettings.from_env()
    service = GaussDBService(settings=settings)
    openapi = OpenApiService(client=GaussDBClient(settings))
    created_id: str | None = None
    try:
        options = await service.discover_create_options()
        config = options["recommended_configuration"]
        assert config["replica_num"] == 1
        assert config["ha"]["instance_mode"] == "basic"
        alphabet = string.ascii_letters + string.digits + "!@#%"
        password = "G8!" + "".join(secrets.choice(alphabet) for _ in range(21))
        config.update(
            {
                "name": f"mcp-live-{datetime.now(timezone.utc):%Y%m%d%H%M%S}",
                "password": password,
                "volume": {"type": "ULTRAHIGH", "size": 40},
                "charge_info": {"charge_mode": "postPaid"},
                "port": "8000",
            }
        )
        created = await service.create_instance(configuration=config)
        created_id = created["instance_id"]
        create_job = await _wait_job(service, created["job_id"])
        assert str(create_job["status"]).upper() in {"COMPLETED", "SUCCESS", "SUCCEEDED"}

        read_results: dict[str, dict[str, Any]] = {}
        for operation, request in (
            ("show_deployment_form", {"instance_id": created_id}),
            ("list_component_infos", {"instance_id": created_id, "limit": 20}),
            ("list_instance_tags", {"instance_id": created_id}),
            ("search_auto_enlarge_policy", {"instance_id": created_id}),
            ("show_ssl_cert_download_link", {"instance_id": created_id}),
        ):
            response = await openapi.invoke(
                operation=operation, request=request, required_risk=ToolRisk.READ
            )
            assert response["operation"] == operation
            read_results[operation] = response

        node_id = read_results["list_component_infos"]["result"]["nodes"][0]["id"]
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        slow_sql = await service.analyze_slow_sql(
            instance_id=created_id,
            node_ids=[node_id],
            start_time=now_ms - 3_600_000,
            end_time=now_ms,
        )
        assert "items" in slow_sql

        cn_time = datetime.now(timezone(timedelta(hours=8)))
        start_time = (cn_time - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S%z")
        end_time = cn_time.strftime("%Y-%m-%dT%H:%M:%S%z")
        for operation, request in (
            (
                "list_instance_error_logs",
                {
                    "instance_id": created_id,
                    "start_time": start_time,
                    "end_time": end_time,
                    "limit": 10,
                },
            ),
            ("show_alarm_statistics", {"start_time": start_time, "top_num": 5}),
        ):
            response = await openapi.invoke(
                operation=operation, request=request, required_risk=ToolRisk.READ
            )
            assert response["operation"] == operation

        await openapi.invoke(
            operation="add_instance_tags",
            request={
                "instance_id": created_id,
                "body": {"tags": [{"key": "mcp-validation", "value": "temporary"}]},
            },
            required_risk=ToolRisk.WRITE,
        )
        await openapi.invoke(
            operation="update_instance_alias",
            request={"instance_id": created_id, "body": {"alias": "mcp-live-validation"}},
            required_risk=ToolRisk.WRITE,
        )
        user_password = "U9!" + "".join(secrets.choice(alphabet) for _ in range(17))
        for operation, request in (
            (
                "create_db_user",
                {
                    "instance_id": created_id,
                    "body": {
                        "name": "mcp_test_user",
                        "password": user_password,
                        "is_login_only": False,
                    },
                },
            ),
            (
                "create_database",
                {
                    "instance_id": created_id,
                    "body": {"name": "mcp_test_db", "owner": "mcp_test_user"},
                },
            ),
            (
                "create_database_schemas",
                {
                    "instance_id": created_id,
                    "body": {
                        "db_name": "mcp_test_db",
                        "schemas": [{"name": "mcp_test_schema", "owner": "mcp_test_user"}],
                    },
                },
            ),
            (
                "allow_db_privileges",
                {
                    "instance_id": created_id,
                    "body": {
                        "db_name": "mcp_test_db",
                        "users": [
                            {
                                "name": "mcp_test_user",
                                "readonly": False,
                                "schema_name": "mcp_test_schema",
                            }
                        ],
                    },
                },
            ),
        ):
            await openapi.invoke(operation=operation, request=request, required_risk=ToolRisk.WRITE)

        schemas = await openapi.invoke(
            operation="list_database_schemas",
            request={"instance_id": created_id, "db_name": "mcp_test_db", "limit": 100},
            required_risk=ToolRisk.READ,
        )
        assert any(
            item.get("schema_name") == "mcp_test_schema"
            for item in schemas["result"]["database_schemas"]
        )
        for operation, request in (
            (
                "delete_database_schema",
                {
                    "instance_id": created_id,
                    "body": {"db_name": "mcp_test_db", "schema": "mcp_test_schema"},
                },
            ),
            (
                "delete_database",
                {"instance_id": created_id, "database_name": "mcp_test_db"},
            ),
            (
                "delete_instance_tag",
                {"instance_id": created_id, "key": "mcp-validation"},
            ),
        ):
            await openapi.invoke(
                operation=operation, request=request, required_risk=ToolRisk.DANGEROUS
            )
    finally:
        if created_id:
            deleted = await service.delete_instance(instance_id=created_id)
            if deleted.get("job_id"):
                delete_job = await _wait_job(service, deleted["job_id"])
                assert str(delete_job["status"]).upper() in {
                    "COMPLETED",
                    "SUCCESS",
                    "SUCCEEDED",
                }
