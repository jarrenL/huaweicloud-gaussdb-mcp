"""Service orchestration, validation, output and token-budget tests."""

from copy import deepcopy
from typing import Any

import pytest
from huaweicloud_mcp_core import McpToolError, ProjectContext

from mcp_server_gaussdb.service import gaussdb_service as service_module
from mcp_server_gaussdb.service.gaussdb_service import (
    GaussDBService,
    _parameter_risk_reasons,
    _validate_parameter_value,
)


@pytest.fixture
def service(fake_client, settings):  # type: ignore[no-untyped-def]
    return GaussDBService(client=fake_client, settings=settings)


async def test_list_instances_paginates_and_crops(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    fake_client.responses["list_database_instances"] = {
        "instances": [{"id": "i1", "name": "db", "status": "ACTIVE", "ignored": "x"}],
        "total_count": 3,
    }
    result = await service.list_instances(limit=5000, marker="1")
    assert result["items"] == [{"id": "i1", "name": "db", "status": "ACTIVE"}]
    assert result["marker"] == "2"
    assert fake_client.calls[-1][1]["limit"] == 100


async def test_get_instance_found_and_missing(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    fake_client.responses["list_database_instances"] = {"instances": [{"id": "i1", "name": "db"}]}
    fake_client.responses["invoke_openapi"] = {
        "nodes": [{"id": "n1", "name": "node-1", "status": "normal", "ignored": "x"}],
        "total_count": 1,
    }
    instance = await service.get_instance(instance_id="i1")
    assert instance["name"] == "db"
    assert instance["node_ids"] == ["n1"]
    assert instance["nodes"] == [{"id": "n1", "name": "node-1", "status": "normal"}]
    fake_client.responses["list_database_instances"] = {"instances": []}
    with pytest.raises(McpToolError, match="not found"):
        await service.get_instance(instance_id="none")


async def test_get_instance_keeps_instance_when_node_discovery_fails(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    fake_client.responses["list_database_instances"] = {
        "instances": [{"id": "i1", "name": "db", "status": "ACTIVE"}]
    }

    async def deny_components(*, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        raise McpToolError("MCP_SDK_ERROR", "component permission denied")

    fake_client.invoke_openapi = deny_components
    result = await service.get_instance(instance_id="i1")
    assert result["id"] == "i1"
    assert result["node_ids"] == []
    assert result["node_discovery_error"] == {
        "code": "MCP_SDK_ERROR",
        "message": "component permission denied",
    }
    assert "node discovery failed" in result["hints"][0]


async def test_list_flavors_validates_and_pages(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(McpToolError):
        await service.list_flavors(ha_mode="bad")
    fake_client.responses["list_flavors_details"] = {
        "flavors": [{"spec_code": "gauss.x", "vcpus": "4", "ram": "32", "internal": 1}],
        "total": 1,
    }
    result = await service.list_flavors(ha_mode="enterprise")
    assert result["items"][0] == {"vcpus": "4", "ram": "32", "spec_code": "gauss.x"}


async def test_create_instance_validation_and_region(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(McpToolError, match="Missing"):
        await service.create_instance(configuration={"name": "x"})
    config: dict[str, Any] = {
        "name": "db",
        "datastore": {},
        "ha": {"mode": "enterprise", "consistency": "strong", "replication_mode": "sync"},
        "password": "secret",
        "flavor_ref": "f",
        "volume": {"type": "ULTRAHIGH", "size": 40},
        "availability_zone": "az1",
        "vpc_id": "v",
        "subnet_id": "s",
        "security_group_id": "g",
        "sharding_num": 1,
        "coordinator_num": 1,
    }
    fake_client.responses["create_database_instance"] = {"job_id": "j1", "other": "x"}
    result = await service.create_instance(configuration=config)
    assert result["job_id"] == "j1"
    assert fake_client.calls[-1][1]["body"]["region"] == "cn-north-4"

    config["ha"] = {
        "mode": "centralization_standard",
        "consistency": "strong",
        "replication_mode": "sync",
    }
    config.pop("sharding_num")
    config.pop("coordinator_num")
    fake_client.responses["create_database_instance"] = {
        "job_id": "j2",
        "instance": {"id": "i2"},
    }
    result = await service.create_instance(configuration=config)
    body = fake_client.calls[-1][1]["body"]
    assert body["availability_zone"] == "az1,az1,az1"
    assert body["replica_num"] == 3
    assert result["instance_id"] == "i2"

    config["replica_num"] = 1
    result = await service.create_instance(configuration=config)
    body = fake_client.calls[-1][1]["body"]
    assert body["availability_zone"] == "az1"
    assert body["replica_num"] == 1

    config["replica_num"] = 2
    with pytest.raises(McpToolError, match="replica_num"):
        await service.create_instance(configuration=config)

    config["replica_num"] = 3
    config["deployment_solution"] = "single"
    with pytest.raises(McpToolError, match="requires replica_num=1"):
        await service.create_instance(configuration=config)

    config["deployment_solution"] = "logger"
    with pytest.raises(McpToolError, match="does not expose"):
        await service.create_instance(configuration=config)


async def test_discover_create_options(
    fake_client: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeNetwork:
        async def list_vpcs(self, *, limit: int) -> dict[str, Any]:
            return {"vpcs": [{"id": "v1", "name": "vpc-default", "status": "OK"}]}

        async def list_subnets(self, *, limit: int) -> dict[str, Any]:
            return {
                "subnets": [
                    {
                        "id": "s1",
                        "neutron_network_id": "network-1",
                        "name": "subnet-default",
                        "vpc_id": "v1",
                        "status": "ACTIVE",
                    }
                ]
            }

        async def list_security_groups(self, *, limit: int) -> dict[str, Any]:
            return {"security_groups": [{"id": "g1", "name": "Sys-default"}]}

    fake_client.responses["list_datastores"] = {"versions": ["10.0.0"]}
    fake_client.responses["list_flavors_details"] = {
        "flavors": [
            {
                "spec_code": "gaussdb.bs.f1",
                "vcpus": "4",
                "ram": "16",
                "az_status": {"az1": "normal", "az2": "sellout"},
            }
        ]
    }
    fake_client.responses["list_storage_types"] = {
        "storage_type": [{"name": "ULTRAHIGH", "az_status": {"az1": "normal"}}]
    }

    async def show_deployment_form(*, solution: str, engine_version: str) -> dict[str, Any]:
        fake_client.calls.append(
            ("show_deployment_form", {"solution": solution, "engine_version": engine_version})
        )
        return {
            "solution": solution,
            "initial_node_num": {"single": 1, "triset": 3, "logger": 3}[solution],
            "replica_num": {"single": 1, "triset": 3, "logger": 3}[solution],
            "shard_num": 1,
        }

    fake_client.show_deployment_form = show_deployment_form
    monkeypatch.setattr(
        "mcp_server_gaussdb.service.gaussdb_service.resolve_project_context",
        lambda value: ProjectContext("project", "domain"),
    )
    service = GaussDBService(
        client=fake_client,
        settings=settings,
        network_client=FakeNetwork(),  # type: ignore[arg-type]
    )
    result = await service.discover_create_options()
    assert result["project"]["domain_id"] == "domain"
    assert result["recommended_configuration"]["availability_zone"] == "az1"
    assert result["recommended_configuration"]["replica_num"] == 1
    assert result["recommended_configuration"]["ha"]["instance_mode"] == "basic"
    assert result["recommended_configuration"]["subnet_id"] == "network-1"
    assert result["recommended_configuration"]["volume"] == {
        "type": "ULTRAHIGH",
        "size": 40,
    }
    assert [option["value"] for option in result["deployment_options"]] == [
        "single",
        "triset",
        "logger",
    ]
    assert result["deployment_options"][2]["direct_create_supported"] is False
    assert result["create_field_options"]["ha.consistency"][1]["value"] == "eventual"
    assert result["create_field_options"]["charge_info.charge_mode"] == [
        "postPaid",
        "prePaid",
    ]
    assert result["create_field_options"]["volume.type"]["values"] == ["ULTRAHIGH"]
    assert result["available_flavor_count"] == 1
    flavor_calls = [values for name, values in fake_client.calls if name == "list_flavors_details"]
    assert flavor_calls[-1]["limit"] == 100

    result = await service.discover_create_options(deployment_mode="triset")
    assert result["recommended_configuration"]["availability_zone"] == "az1,az1,az1"
    assert result["recommended_configuration"]["replica_num"] == 3

    result = await service.discover_create_options(deployment_mode="logger")
    assert result["recommended_configuration"] is None

    # Legacy aliases remain accepted by the service for existing MCP clients.
    result = await service.discover_create_options(deployment_mode="single_replica")
    assert result["selection"]["deployment_mode"] == "single"

    result = await service.discover_create_options(ha_mode="enterprise", product_type="basic")
    assert result["selection"]["deployment_mode"] == "combined"
    assert result["selection"]["flavor_query_ha_mode"] == "combined"
    assert result["deployment_options"][0]["value"] == "combined"
    assert result["deployment_options"][0]["available_flavor_count"] == 1
    assert result["deployment_options"][0]["availability_semantics"] == "catalog_candidate"
    assert result["deployment_options"][0]["create_compatibility"] == (
        "cloud_final_validation_required"
    )
    assert result["recommended_configuration_status"] == (
        "catalog_candidate_cloud_final_validation_required"
    )
    flavor_calls = [values for name, values in fake_client.calls if name == "list_flavors_details"]
    assert flavor_calls[-1]["ha_mode"] == "combined"

    fake_client.responses["list_flavors_details"]["flavors"][0]["spec_code"] = (
        "gaussdb.opengauss.ee.dn.f1"
    )
    result = await service.discover_create_options(ha_mode="enterprise", product_type="enterprise")
    assert result["selection"]["deployment_mode"] == "hws"
    assert result["selection"]["flavor_query_ha_mode"] == "enterprise"
    assert result["deployment_options"][0]["value"] == "hws"

    with pytest.raises(McpToolError, match="deployment_mode"):
        await service.discover_create_options(deployment_mode="invalid")
    with pytest.raises(McpToolError, match="product_type"):
        await service.discover_create_options(product_type="invalid")


async def test_distributed_create_binding_error_has_actionable_hint(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    async def reject_create(*, body: dict[str, Any]) -> dict[str, Any]:
        raise McpToolError("DBS.200054", "The selected flavor is invalid.", request_id="req")

    fake_client.create_database_instance = reject_create
    configuration = {
        "name": "db",
        "datastore": {"type": "GaussDB", "version": "10.0.0"},
        "ha": {
            "mode": "enterprise",
            "instance_mode": "basic",
            "consistency": "strong",
            "replication_mode": "sync",
        },
        "deployment_solution": "combined",
        "password": "secret",
        "flavor_ref": "candidate",
        "volume": {"type": "ULTRAHIGH", "size": 40},
        "availability_zone": "az1",
        "vpc_id": "v",
        "subnet_id": "s",
        "security_group_id": "g",
        "sharding_num": 1,
        "coordinator_num": 1,
    }
    with pytest.raises(McpToolError) as excinfo:
        await service.create_instance(configuration=configuration)
    assert excinfo.value.code == "DBS.200054"
    assert excinfo.value.request_id == "req"
    assert "catalog" in (excinfo.value.hint or "")
    assert "another returned flavor, product edition, or region" in (excinfo.value.hint or "")


async def test_create_instance_rejects_invalid_cloud_combinations(service) -> None:  # type: ignore[no-untyped-def]
    centralized: dict[str, Any] = {
        "name": "db",
        "datastore": {"type": "GaussDB", "version": "10.0.0"},
        "ha": {
            "mode": "centralization_standard",
            "consistency": "strong",
            "replication_mode": "sync",
        },
        "password": "secret",
        "flavor_ref": "f",
        "volume": {"type": "ULTRAHIGH", "size": 40},
        "availability_zone": "az1",
        "vpc_id": "v",
        "subnet_id": "s",
        "security_group_id": "g",
    }
    distributed = deepcopy(centralized)
    distributed.update(
        {
            "ha": {
                "mode": "enterprise",
                "instance_mode": "basic",
                "consistency": "strong",
                "replication_mode": "sync",
            },
            "deployment_solution": "combined",
            "sharding_num": 1,
            "coordinator_num": 1,
            "replica_num": 3,
        }
    )

    invalid_cases: list[tuple[dict[str, Any], str]] = []

    def changed(base: dict[str, Any], **values: Any) -> dict[str, Any]:
        result = deepcopy(base)
        result.update(values)
        return result

    for field, value, expected in (
        ("instance_mode", "invalid", "instance_mode"),
        ("consistency", "invalid", "consistency"),
        ("replication_mode", "async", "replication_mode"),
    ):
        config = deepcopy(centralized)
        config["ha"][field] = value
        invalid_cases.append((config, expected))
    invalid_cases.extend(
        [
            (changed(centralized, deployment_solution="combined"), "distributed-only"),
            (changed(centralized, sharding_num=1), "distributed-only fields"),
            (changed(centralized, replica_num=3, availability_zone="az1,az2"), "availability_zone"),
            (
                changed(distributed, deployment_solution="hws"),
                "require deployment_solution=combined",
            ),
            (
                changed(
                    distributed,
                    ha={**distributed["ha"], "instance_mode": "enterprise"},
                    deployment_solution="combined",
                ),
                "require deployment_solution=hws",
            ),
            (changed(distributed, enable_single_float_ip=True), "centralized-only"),
            (changed(distributed, sharding_num=0), "sharding_num"),
            (changed(distributed, coordinator_num=3), "coordinator_num"),
            (changed(distributed, replica_num=1), "distributed replica_num"),
            (changed(distributed, availability_zone="az1,az2"), "availability_zone"),
            (changed(centralized, ha={**centralized["ha"], "mode": "invalid"}), "ha.mode"),
            (changed(centralized, volume={"type": "SATA", "size": 40}), "volume.type"),
            (changed(centralized, volume={"type": "ULTRAHIGH", "size": 20}), "volume.size"),
            (changed(centralized, volume={"type": "ULTRAHIGH", "size": 42}), "multiple"),
            (changed(centralized, port=2379), "port"),
            (changed(centralized, time_zone="UTC+13:00"), "time_zone"),
            (
                changed(
                    centralized,
                    backup_strategy={"keep_days": 36501, "start_time": "21:00-22:00"},
                ),
                "keep_days",
            ),
            (
                changed(
                    centralized,
                    backup_strategy={"keep_days": 7, "start_time": "bad"},
                ),
                "start_time",
            ),
            (
                changed(
                    centralized,
                    backup_strategy={"keep_days": 7, "start_time": "21:00-23:00"},
                ),
                "exactly one hour",
            ),
            (changed(centralized, charge_info={"charge_mode": "free"}), "charge_mode"),
            (
                changed(
                    centralized,
                    charge_info={
                        "charge_mode": "prePaid",
                        "period_type": "month",
                        "period_num": 10,
                    },
                ),
                "prePaid requires",
            ),
        ]
    )

    for configuration, expected in invalid_cases:
        with pytest.raises(McpToolError, match=expected):
            await service.create_instance(configuration=configuration)


async def test_create_instance_preserves_unrelated_cloud_error(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    async def reject_create(*, body: dict[str, Any]) -> dict[str, Any]:
        raise McpToolError("DBS.OTHER", "service unavailable", request_id="req")

    fake_client.create_database_instance = reject_create
    configuration = {
        "name": "db",
        "datastore": {},
        "ha": {
            "mode": "centralization_standard",
            "consistency": "strong",
            "replication_mode": "sync",
        },
        "password": "secret",
        "flavor_ref": "f",
        "volume": {"type": "ULTRAHIGH", "size": 40},
        "availability_zone": "az1",
        "vpc_id": "v",
        "subnet_id": "s",
        "security_group_id": "g",
    }
    with pytest.raises(McpToolError) as excinfo:
        await service.create_instance(configuration=configuration)
    assert excinfo.value.code == "DBS.OTHER"
    assert excinfo.value.request_id == "req"


async def test_delete_instance_rechecks_resource(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    fake_client.responses["list_database_instances"] = {
        "instances": [{"id": "i1", "name": "temporary", "status": "ACTIVE"}]
    }
    fake_client.responses["delete_instance"] = {"job_id": "jd"}
    result = await service.delete_instance(instance_id="i1")
    assert result["instance_id"] == "i1"
    assert result["instance_name"] == "temporary"
    assert result["job_id"] == "jd"
    assert [name for name, _ in fake_client.calls[-2:]] == [
        "list_database_instances",
        "delete_instance",
    ]

    fake_client.responses["list_database_instances"] = {"instances": []}
    with pytest.raises(McpToolError, match="not found"):
        await service.delete_instance(instance_id="missing")


async def test_backups_and_manual_backup(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    fake_client.responses["list_backups_details"] = {
        "backups": [{"id": "b1", "status": "COMPLETED", "secret": "x"}],
        "total_count": 2,
    }
    result = await service.list_backups(instance_id="i1", limit=999)
    assert result["items"] == [{"id": "b1", "status": "COMPLETED"}]
    assert fake_client.calls[-1][1]["limit"] == 100
    with pytest.raises(McpToolError):
        await service.create_manual_backup(instance_id="i1", name="1bad")
    fake_client.responses["create_manual_backup"] = {"backup_id": "b2"}
    assert (await service.create_manual_backup(instance_id="i1", name="Good_backup"))[
        "backup_id"
    ] == "b2"


async def test_resize_restart_and_jobs(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    fake_client.responses["resize_instances_flavor"] = {"job_id": "jr"}
    assert (await service.resize_instance(instance_id="i", flavor_ref="f"))["job_id"] == "jr"
    fake_client.responses["restart_instance"] = {"job_id": "jj"}
    assert (await service.restart_instance(instance_id="i"))["instance_id"] == "i"
    fake_client.responses["show_job_detail"] = {"job": {"id": "jj", "status": "RUNNING", "x": 1}}
    assert await service.get_job(job_id="jj") == {"id": "jj", "status": "RUNNING"}
    fake_client.responses["show_job_detail"] = {
        "job": {"id": "jj", "name": "SWITCHDN", "status": "COMPLETED"}
    }
    switched = await service.get_job(job_id="jj")
    assert "BACKING UP" in switched["hints"][0]


async def test_job_waiting_and_switchover_hint(
    service, fake_client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    clock = [0.0]
    states = iter(
        [
            {"job": {"id": "j", "name": "SWITCHDN", "status": "RUNNING"}},
            {"job": {"id": "j", "name": "SWITCHDN", "status": "COMPLETED"}},
        ]
    )

    async def show_job_detail(*, job_id: str) -> dict[str, Any]:
        assert job_id == "j"
        return next(states)

    async def advance(seconds: float) -> None:
        clock[0] += seconds

    fake_client.show_job_detail = show_job_detail
    monkeypatch.setattr(service_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(service_module.asyncio, "sleep", advance)
    result = await service.wait_job(job_id="j", timeout_seconds=10, poll_interval_seconds=2)
    assert result["terminal"] is True
    assert result["successful"] is True
    assert result["timed_out"] is False
    assert result["poll_attempts"] == 2
    assert result["elapsed_seconds"] == 2
    assert "BACKING UP" in result["hints"][0]


async def test_job_wait_timeout_and_validation(
    service, fake_client, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    clock = [0.0]

    async def advance(seconds: float) -> None:
        clock[0] += seconds

    fake_client.responses["show_job_detail"] = {"job": {"id": "j", "status": "RUNNING"}}
    monkeypatch.setattr(service_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(service_module.asyncio, "sleep", advance)
    result = await service.wait_job(job_id="j", timeout_seconds=2, poll_interval_seconds=1)
    assert result["terminal"] is False
    assert result["timed_out"] is True
    assert result["poll_attempts"] == 3
    assert "do not resubmit" in result["hints"][0]
    with pytest.raises(McpToolError, match="timeout_seconds"):
        await service.wait_job(job_id="j", timeout_seconds=0)
    with pytest.raises(McpToolError, match="poll_interval_seconds"):
        await service.wait_job(job_id="j", poll_interval_seconds=61)

    fake_client.responses["show_job_detail"] = {
        "job": {"id": "j", "status": "FAILED", "fail_reason": "cloud rejected operation"}
    }
    failed = await service.wait_job(job_id="j")
    assert failed["terminal"] is True
    assert failed["successful"] is False
    assert failed["fail_reason"] == "cloud rejected operation"


async def test_expand_all_modes_and_invalid(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(McpToolError, match="exactly one"):
        await service.expand_instance(instance_id="i")
    with pytest.raises(McpToolError, match="exactly one"):
        await service.expand_instance(instance_id="i", new_volume_size_gb=100, dn_shard_count=1)
    with pytest.raises(McpToolError, match="positive"):
        await service.expand_instance(instance_id="i", new_volume_size_gb=0)
    with pytest.raises(McpToolError, match="positive"):
        await service.expand_instance(instance_id="i", dn_shard_count=0)
    await service.expand_instance(instance_id="i", new_volume_size_gb=400)
    assert fake_client.calls[-1][1]["body"]["enlarge_volume"] == {"size": 400}
    await service.expand_instance(instance_id="i", coordinator_az_codes=["az1", "az2"])
    assert len(fake_client.calls[-1][1]["body"]["expand_cluster"]["coordinators"]) == 2
    await service.expand_instance(instance_id="i", dn_shard_count=2)
    assert fake_client.calls[-1][1]["body"]["expand_cluster"]["shard"] == {"count": 2}


async def test_parameters_filter_update_and_validation(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    fake_client.responses["show_instance_configuration"] = {
        "configuration_parameters": [
            {
                "name": "max_connections",
                "value": "100",
                "restart_required": True,
                "readonly": False,
                "value_range": "10-1000",
                "type": "integer",
                "internal": 1,
            },
            {
                "name": "log_min_duration_statement",
                "value": "100",
                "restart_required": False,
                "readonly": False,
                "value_range": "-1-2147483647",
                "type": "integer",
            },
            {
                "name": "audit_system_object",
                "value": "1",
                "restart_required": False,
                "readonly": True,
                "value_range": "0-3",
                "type": "integer",
            },
        ]
    }
    result = await service.get_instance_parameters(instance_id="i", name="max", limit=1)
    assert result["items"][0]["name"] == "max_connections"
    assert result["items"][0]["readonly"] is False
    assert result["items"][0]["risk_level"] == "high"
    assert "restart_required" in result["items"][0]["risk_reasons"]
    result = await service.get_instance_parameters(instance_id="i", modifiable_only=True)
    assert [item["name"] for item in result["items"]] == [
        "max_connections",
        "log_min_duration_statement",
    ]
    assert result["parameter_metadata"]["modifiable"] == 2
    for values in ({}, {str(i): "x" for i in range(101)}):
        with pytest.raises(McpToolError):
            await service.update_instance_parameters(instance_id="i", values=values)
    with pytest.raises(McpToolError, match="Unknown"):
        await service.update_instance_parameters(instance_id="i", values={"max_connection": "5"})
    with pytest.raises(McpToolError, match="read-only"):
        await service.update_instance_parameters(
            instance_id="i", values={"audit_system_object": "2"}
        )
    with pytest.raises(McpToolError, match="failed local validation"):
        await service.update_instance_parameters(instance_id="i", values={"max_connections": "x"})

    fake_client.responses["update_instance_configuration"] = {"job_id": "jp"}
    updated = await service.update_instance_parameters(
        instance_id="i", values={"log_min_duration_statement": "200"}
    )
    assert updated["updated_parameters"] == ["log_min_duration_statement"]
    assert [name for name, _ in fake_client.calls[-2:]] == [
        "show_instance_configuration",
        "update_instance_configuration",
    ]

    preview = await service.update_instance_parameters(
        instance_id="i", values={"max_connections": "200"}
    )
    assert preview["confirmation_required"] is True
    assert preview["high_risk_parameters"] == ["max_connections"]
    assert fake_client.calls[-1][0] == "show_instance_configuration"
    updated = await service.update_instance_parameters(
        instance_id="i", values={"max_connections": "200"}, confirm=True
    )
    assert updated["updated_parameters"] == ["max_connections"]

    no_op = await service.update_instance_parameters(
        instance_id="i", values={"max_connections": "100"}
    )
    assert no_op["no_op"] is True


def test_parameter_value_validation_and_description_risk_markers() -> None:
    assert _parameter_risk_reasons(
        {"name": "safe_parameter", "description": "May cause data loss"}
    ) == ["risk_warning_in_cloud_description"]
    assert _validate_parameter_value({"type": "integer", "value_range": "1-10"}, "default") is None
    assert "boolean" in (_validate_parameter_value({"type": "boolean"}, "maybe") or "")
    assert "integer" in (_validate_parameter_value({"type": "integer"}, "1.5") or "")
    assert "within" in (
        _validate_parameter_value({"type": "float", "value_range": "0.5-1.5"}, "2") or ""
    )
    assert "one of" in (
        _validate_parameter_value({"type": "string", "value_range": "on|off"}, "other") or ""
    )
    assert "outside" in (
        _validate_parameter_value({"type": "stringlist", "value_range": "read,write"}, "read,admin")
        or ""
    )
    assert (
        _validate_parameter_value({"type": "stringlist", "value_range": "read,write"}, "read,write")
        is None
    )


async def test_parameter_metadata_unknown_fails_closed(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    fake_client.responses["show_instance_configuration"] = {
        "_metadata_api_version": "v3.2",
        "configuration_parameters": [
            {
                "name": "autoanalyze_timeout",
                "value": "300",
                "readonly": None,
                "restart_required": False,
                "value_range": "0-86400",
                "type": "integer",
            }
        ],
    }
    result = await service.get_instance_parameters(instance_id="i")
    assert result["items"][0]["readonly"] is None
    assert result["items"][0]["modifiability"] == "unknown"
    assert result["parameter_metadata"] == {
        "source_api_version": "v3.2",
        "modifiable": 0,
        "read_only": 0,
        "unknown": 1,
    }
    filtered = await service.get_instance_parameters(instance_id="i", modifiable_only=True)
    assert filtered["items"] == []
    with pytest.raises(McpToolError) as excinfo:
        await service.update_instance_parameters(
            instance_id="i", values={"autoanalyze_timeout": "301"}
        )
    assert excinfo.value.code == "MCP_PARAMETER_MODIFIABILITY_UNKNOWN"


async def test_analyze_slow_sql_validation_and_sort(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(McpToolError):
        await service.analyze_slow_sql(instance_id="i", node_ids=["n"], start_time=2, end_time=1)
    with pytest.raises(McpToolError):
        await service.analyze_slow_sql(instance_id="i", node_ids=[], start_time=1, end_time=2)
    with pytest.raises(McpToolError, match="threshold"):
        await service.analyze_slow_sql(
            instance_id="i", node_ids=["n"], start_time=1, end_time=2, threshold=0
        )
    fake_client.responses["list_slow_sqls"] = {
        "total": 2,
        "slow_sql_infos": [
            {"sql_id": "s1", "avg_exec_time": "bad", "query_plan": "hidden"},
            {"sql_id": "s2", "avg_exec_time": "9.5", "sql_text": "select ?"},
        ],
    }
    result = await service.analyze_slow_sql(
        instance_id="i", node_ids=["n"], start_time=1, end_time=2, limit=1
    )
    assert result["items"][0]["sql_id"] == "s2"
    assert result["analysis"]["highest_avg_exec_time"] == "9.5"
    assert result["analysis"]["query_window"] == {"start_time_ms": 1, "end_time_ms": 2}

    await service.analyze_slow_sql(
        instance_id="i",
        node_ids=["n"],
        start_time="2026-10-21T15:30:00+08:00",
        end_time="2026-10-21T08:30:00Z",
    )
    call = fake_client.calls[-1][1]
    assert call["end_time"] - call["start_time"] == 3_600_000
    await service.analyze_slow_sql(
        instance_id="i", node_ids=["n"], start_time="1", end_time="2"
    )
    assert fake_client.calls[-1][1]["start_time"] == 1
    with pytest.raises(McpToolError, match="ISO 8601"):
        await service.analyze_slow_sql(
            instance_id="i",
            node_ids=["n"],
            start_time="2026-10-21T15:30:00",
            end_time="2026-10-21T16:30:00+08:00",
        )


async def test_backup_policy(service, fake_client) -> None:  # type: ignore[no-untyped-def]
    fake_client.responses["show_backup_policy"] = {
        "backup_policy": {
            "keep_days": 7,
            "differential_period": 30,
            "differential_priod": None,
        }
    }
    policy = (await service.get_backup_policy(instance_id="i"))["backup_policy"]
    assert policy["keep_days"] == 7
    assert policy["differential_period"] == 30
    assert "differential_priod" not in policy

    fake_client.responses["show_backup_policy"] = {
        "backup_policy": {"keep_days": 7, "differential_priod": "60"}
    }
    policy = (await service.get_backup_policy(instance_id="i"))["backup_policy"]
    assert policy["differential_period"] == 60
    fake_client.responses["show_backup_policy"] = {
        "backup_policy": {"keep_days": 7, "differential_period": "cloud-unknown"}
    }
    policy = (await service.get_backup_policy(instance_id="i"))["backup_policy"]
    assert policy["differential_period"] == "cloud-unknown"
    with pytest.raises(McpToolError):
        await service.configure_backup_policy(
            instance_id="i", keep_days=0, start_time="21:00-22:00", period="1"
        )
    with pytest.raises(McpToolError):
        await service.configure_backup_policy(
            instance_id="i", keep_days=7, start_time="bad", period="1"
        )
    with pytest.raises(McpToolError, match="weekday"):
        await service.configure_backup_policy(
            instance_id="i", keep_days=7, start_time="21:00-22:00", period="monday"
        )
    for invalid_interval in (14, 45, 1441, "monday"):
        with pytest.raises(McpToolError, match="differential_period"):
            await service.configure_backup_policy(
                instance_id="i",
                keep_days=7,
                start_time="21:00-22:00",
                period="1",
                differential_period=invalid_interval,  # type: ignore[arg-type]
            )
    result = await service.configure_backup_policy(
        instance_id="i",
        keep_days=7,
        start_time="21:00-22:00",
        period="1,3,5",
        differential_period=60,
    )
    assert result["backup_policy_updated"] is True
    assert result["differential_period_source"] == "request"
    assert fake_client.calls[-1][1]["policy"]["differential_period"] == "60"

    fake_client.responses["show_backup_policy"] = {
        "backup_policy": {"keep_days": 7, "differential_period": 30}
    }
    result = await service.configure_backup_policy(
        instance_id="i",
        keep_days=7,
        start_time="21:00-22:00",
        period="1,3,5",
    )
    assert result["differential_period"] == 30
    assert result["differential_period_source"] == "current_policy"
    assert [name for name, _ in fake_client.calls[-2:]] == [
        "show_backup_policy",
        "set_new_backup_policy",
    ]
    assert fake_client.calls[-1][1]["policy"]["differential_period"] == "30"

    fake_client.responses["show_backup_policy"] = {"backup_policy": {"keep_days": 7}}
    with pytest.raises(McpToolError) as excinfo:
        await service.configure_backup_policy(
            instance_id="i",
            keep_days=7,
            start_time="21:00-22:00",
            period="1,3,5",
        )
    assert excinfo.value.code == "MCP_BACKUP_POLICY_INCOMPLETE"
