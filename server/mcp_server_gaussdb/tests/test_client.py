"""SDK request construction and response conversion tests."""

from typing import Any

import pytest
from huaweicloud_mcp_core import McpSettings, McpToolError

from mcp_server_gaussdb.client.gaussdb_client import GaussDBClient, _model_from_dict, sdk_to_dict
from mcp_server_gaussdb.client.vpc_client import VpcResourceClient


class RecordingSdkClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, Any]] = []

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        def call(request: Any) -> dict[str, Any]:
            self.requests.append((name, request))
            return {"recorded": name}

        return call


def client(settings: McpSettings) -> tuple[GaussDBClient, RecordingSdkClient]:
    sdk = RecordingSdkClient()
    return GaussDBClient(settings=settings, sdk_client=sdk), sdk


def test_sdk_to_dict_recurses_and_strips_prefixes() -> None:
    class Inner:
        def __init__(self) -> None:
            self._value = "v"

    class Outer:
        def __init__(self) -> None:
            self._name = "db"
            self._items = [Inner()]
            self.discriminator = "skip"

    class SdkResponse:
        def to_dict(self) -> dict[str, Any]:
            return {"items": [{"count": 1}], "total_count": 1}

    assert sdk_to_dict(Outer()) == {"name": "db", "items": [{"value": "v"}]}
    assert sdk_to_dict({"a": (1, True, None)}) == {"a": [1, True, None]}
    assert sdk_to_dict(SdkResponse())["total_count"] == 1


def test_model_from_dict_nested_and_unknown() -> None:
    import huaweicloudsdkgaussdbforopengauss.v3 as sdk

    model = _model_from_dict(
        sdk,
        sdk.OpenGaussInstanceActionRequest,
        {
            "expand_cluster": {"coordinators": [{"az_code": "az1"}]},
            "is_auto_pay": "false",
        },
    )
    assert model.expand_cluster.coordinators[0].az_code == "az1"
    with pytest.raises(ValueError, match="Unknown"):
        _model_from_dict(sdk, sdk.OpenGaussInstanceActionRequest, {"bad": 1})


async def test_query_requests(settings) -> None:  # type: ignore[no-untyped-def]
    target, sdk = client(settings)
    await target.list_database_instances(limit=20, offset=3, instance_id="i", name="db")
    method, request = sdk.requests[-1]
    assert method == "list_database_instances" and request.limit == 20 and request.id == "i"
    await target.list_flavors_details(version="3.3", ha_mode="enterprise", limit=10, offset=2)
    assert sdk.requests[-1][1].ha_mode == "enterprise"
    await target.list_backups_details(
        instance_id="i", backup_type="manual", begin_time="a", end_time="b", limit=5, offset=1
    )
    assert sdk.requests[-1][1].backup_type == "manual"
    await target.show_instance_configuration(instance_id="i")
    assert sdk.requests[-1][1].instance_id == "i"
    await target.show_job_detail(job_id="j")
    assert sdk.requests[-1][1].id == "j"
    await target.show_backup_policy(instance_id="i")
    assert sdk.requests[-1][1].instance_id == "i"
    await target.list_datastores()
    assert sdk.requests[-1][0] == "list_datastores"
    await target.show_deployment_form(solution="logger", engine_version="10.0.0")
    assert sdk.requests[-1][0] == "show_deployment_form"
    assert sdk.requests[-1][1].solution == "logger"
    assert sdk.requests[-1][1].engine_version == "10.0.0"
    await target.list_storage_types(version="10.0.0", ha_mode="centralization_standard")
    assert sdk.requests[-1][0] == "list_storage_types"
    assert sdk.requests[-1][1].ha_mode == "centralization_standard"


async def test_instance_configuration_uses_current_v32_endpoint(settings) -> None:  # type: ignore[no-untyped-def]
    from huaweicloudsdkgaussdbforopengauss.v3 import GaussDBforopenGaussClient

    class V32SdkClient(GaussDBforopenGaussClient):
        def __init__(self) -> None:
            self.resource_path = ""

        def _show_instance_configuration_http_info(self, request):  # type: ignore[no-untyped-def]
            return {"resource_path": "/v3/{project_id}/instances/{instance_id}/configurations"}

        def _call_api(self, **http_info):  # type: ignore[no-untyped-def]
            self.resource_path = http_info["resource_path"]
            return {"configuration_parameters": [{"name": "work_mem", "readonly": False}]}

    sdk = V32SdkClient()
    target = GaussDBClient(settings=settings, sdk_client=sdk)
    result = await target.show_instance_configuration(instance_id="i")
    assert sdk.resource_path.startswith("/v3.2/")
    assert result["_metadata_api_version"] == "v3.2"
    assert result["configuration_parameters"][0]["readonly"] is False


async def test_instance_configuration_v32_error_is_wrapped(settings) -> None:  # type: ignore[no-untyped-def]
    from huaweicloudsdkgaussdbforopengauss.v3 import GaussDBforopenGaussClient

    class BrokenV32SdkClient(GaussDBforopenGaussClient):
        def __init__(self) -> None:
            pass

        def _show_instance_configuration_http_info(self, request):  # type: ignore[no-untyped-def]
            return {"resource_path": "/v3/{project_id}/instances/{instance_id}/configurations"}

        def _call_api(self, **http_info):  # type: ignore[no-untyped-def]
            raise RuntimeError("private configuration failure")

    target = GaussDBClient(settings=settings, sdk_client=BrokenV32SdkClient())
    with pytest.raises(McpToolError) as excinfo:
        await target.show_instance_configuration(instance_id="i")
    assert excinfo.value.code == "MCP_SDK_ERROR"


async def test_generic_openapi_request(settings) -> None:  # type: ignore[no-untyped-def]
    target, sdk = client(settings)
    result = await target.invoke_openapi(
        operation="show_deployment_form",
        request={"solution": "triset", "engine_version": None},
    )
    method, request = sdk.requests[-1]
    assert method == "show_deployment_form"
    assert request.solution == "triset"
    assert request.x_language == "zh-cn"
    assert result == {"recorded": "show_deployment_form"}

    with pytest.raises(ValueError, match="Unknown GaussDB OpenAPI"):
        await target.invoke_openapi(operation="not_real", request={})


async def test_vpc_resource_requests(settings) -> None:  # type: ignore[no-untyped-def]
    sdk = RecordingSdkClient()
    target = VpcResourceClient(settings=settings, sdk_client=sdk)
    await target.list_vpcs(limit=10)
    await target.list_subnets(limit=11)
    await target.list_security_groups(limit=12)
    assert [name for name, _ in sdk.requests] == [
        "list_vpcs",
        "list_subnets",
        "list_security_groups",
    ]
    assert sdk.requests[-1][1].limit == 12


async def test_vpc_sdk_error_is_wrapped(settings) -> None:  # type: ignore[no-untyped-def]
    class Broken:
        def list_vpcs(self, request):  # type: ignore[no-untyped-def]
            raise RuntimeError("private VPC failure")

    target = VpcResourceClient(settings=settings, sdk_client=Broken())
    with pytest.raises(McpToolError) as excinfo:
        await target.list_vpcs(limit=10)
    assert excinfo.value.code == "MCP_SDK_ERROR"


async def test_create_instance_request(settings) -> None:  # type: ignore[no-untyped-def]
    target, sdk = client(settings)
    body = {
        "name": "db",
        "datastore": {"type": "GaussDB", "version": "3.3"},
        "ha": {"mode": "enterprise", "replication_mode": "sync", "consistency": "strong"},
        "password": "Password1!",
        "flavor_ref": "f",
        "volume": {"type": "ULTRAHIGH", "size": 120},
        "region": "cn-north-4",
        "availability_zone": "az1",
        "vpc_id": "v",
        "subnet_id": "s",
        "security_group_id": "g",
    }
    await target.create_database_instance(body=body)
    request = sdk.requests[-1][1]
    assert request.body.name == "db" and request.body.datastore.version == "3.3"


async def test_backup_and_lifecycle_requests(settings) -> None:  # type: ignore[no-untyped-def]
    target, sdk = client(settings)
    await target.delete_instance(instance_id="i")
    assert sdk.requests[-1][1].instance_id == "i"
    await target.create_manual_backup(instance_id="i", name="Backup1", description="d")
    assert sdk.requests[-1][1].body.instance_id == "i"
    await target.resize_instances_flavor(instance_id="i", flavor_ref="f2", is_auto_pay=True)
    assert sdk.requests[-1][1].body.flavor_ref == "f2"
    await target.run_instance_action(instance_id="i", body={"enlarge_volume": {"size": 400}})
    assert sdk.requests[-1][1].body.enlarge_volume.size == 400
    await target.restart_instance(instance_id="i")
    assert sdk.requests[-1][0] == "restart_instance"


async def test_parameters_slow_sql_and_policy_requests(settings) -> None:  # type: ignore[no-untyped-def]
    target, sdk = client(settings)
    await target.update_instance_configuration(instance_id="i", values={"work_mem": "4MB"})
    assert sdk.requests[-1][1].body.values == {"work_mem": "4MB"}
    await target.list_slow_sqls(
        instance_id="i", node_ids=["n"], start_time=1, end_time=2, threshold=5
    )
    assert sdk.requests[-1][1].body.threshold == 5
    await target.set_new_backup_policy(
        instance_id="i", policy={"keep_days": 7, "start_time": "21:00-22:00", "period": "1"}
    )
    assert sdk.requests[-1][1].body.backup_policy.keep_days == 7


async def test_sdk_error_is_wrapped(settings) -> None:  # type: ignore[no-untyped-def]
    class Broken:
        def restart_instance(self, request):  # type: ignore[no-untyped-def]
            raise RuntimeError("private failure")

    target = GaussDBClient(settings=settings, sdk_client=Broken())
    with pytest.raises(McpToolError) as excinfo:
        await target.restart_instance(instance_id="i")
    assert excinfo.value.code == "MCP_SDK_ERROR"
