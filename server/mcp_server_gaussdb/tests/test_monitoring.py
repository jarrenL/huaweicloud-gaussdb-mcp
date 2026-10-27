"""CES request contracts, discovery, hierarchy, bounded queries and no-data semantics."""

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest
from huaweicloud_mcp_core import McpSettings, McpToolError
from mcp import Client

from mcp_server_gaussdb.client.ces_client import CesMonitoringClient
from mcp_server_gaussdb.service.monitoring_service import GAUSSDB_NAMESPACE, MonitoringService
from mcp_server_gaussdb.tools import monitoring

START = 1793066400000
END = START + 3_600_000
INSTANCE = {"name": "gaussdbv5_instance_id", "value": "i"}
NODE = {"name": "gaussdbv5_node_id", "value": "n"}
COMPONENT = {"name": "gaussdbv5_component_id", "value": "dn_6001"}
METRIC = {
    "namespace": GAUSSDB_NAMESPACE,
    "metric_name": "rds001_cpu_util",
    "dimensions": [INSTANCE, NODE],
    "unit": "%",
}


class FakeCesClient(CesMonitoringClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.list_response: dict[str, Any] = {}
        self.batch_response: dict[str, Any] = {}

    async def list_metrics(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list_metrics", kwargs))
        return self.list_response

    async def batch_list_metric_data(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("batch_list_metric_data", kwargs))
        return self.batch_response


async def test_discovery_returns_live_hierarchy_and_ces_pagination() -> None:
    client = FakeCesClient()
    client.list_response = {
        "metrics": [METRIC, {**METRIC, "dimensions": [INSTANCE, NODE, COMPONENT]}],
        "meta_data": {"count": 2, "total": 120, "marker": "ces-next"},
    }
    service = MonitoringService(client)
    result = await service.list_metrics(instance_id="i", limit=999, marker="ces-start")
    assert result["items"] == client.list_response["metrics"]
    assert result["marker"] == "ces-next"
    assert result["total"] == 120
    assert client.calls[0][1] == {
        "namespace": GAUSSDB_NAMESPACE,
        "dimensions": [INSTANCE],
        "metric_name": None,
        "limit": 100,
        "marker": "ces-start",
    }
    await service.list_metrics(
        instance_id="i",
        node_id="n",
        component_id="dn_6001",
        metric_name="rds010_disk_usage",
    )
    assert client.calls[-1][1]["dimensions"] == [INSTANCE, NODE, COMPONENT]
    client.list_response = {"metrics": [], "meta_data": {"marker": "stale"}}
    empty = await service.list_metrics(instance_id="i")
    assert empty["items"] == [] and empty["marker"] is None


async def test_ces_alphabetical_component_dimensions_round_trip_without_manual_reordering() -> None:
    client = FakeCesClient()
    component = {
        **METRIC,
        "metric_name": "rds053_online_session",
        "dimensions": [COMPONENT, INSTANCE, NODE],
    }
    client.list_response = {"metrics": [component]}
    client.batch_response = {
        "metrics": [{**component, "datapoints": [{"timestamp": START, "average": 5}]}]
    }
    service = MonitoringService(client)
    discovered = await service.list_metrics(instance_id="i", node_id="n", component_id="dn_6001")
    assert discovered["scope"] == "component"
    assert discovered["items"][0]["dimensions"] == [INSTANCE, NODE, COMPONENT]
    result = await service.query_metrics(
        instance_id="i", metrics=discovered["items"], start_time=START, end_time=END
    )
    assert result["items"][0]["summary"]["latest_value"] == 5
    # Also accept an unnormalized object captured directly from CES before this fix.
    await service.query_metrics(
        instance_id="i", metrics=[component], start_time=START, end_time=END
    )
    assert client.calls[-1][1]["metrics"][0]["dimensions"] == [INSTANCE, NODE, COMPONENT]


@pytest.mark.parametrize(
    "arguments",
    [
        {"instance_id": ""},
        {"instance_id": "i", "component_id": "dn_6001"},
        {"instance_id": "i", "node_id": "bad,node"},
        {"instance_id": "i", "metric_name": "invalid metric"},
    ],
)
async def test_invalid_discovery_does_not_construct_a_client(arguments: dict[str, Any]) -> None:
    with pytest.raises(McpToolError) as excinfo:
        await MonitoringService().list_metrics(**arguments)
    assert excinfo.value.code == "MCP_INVALID_ARGS"


async def test_queries_keep_all_dimensions_and_summary_before_display_truncation() -> None:
    client = FakeCesClient()
    component = {
        **METRIC,
        "metric_name": "rds053_online_session",
        "dimensions": [INSTANCE, NODE, COMPONENT],
    }
    client.batch_response = {
        "metrics": [
            {
                **component,
                "unit": "Count",
                "datapoints": [
                    {"timestamp": START + 300000, "average": 10, "hidden": "omit"},
                    {"timestamp": START - 1, "average": 999},
                    {"timestamp": START + 600000, "average": 20},
                    {"timestamp": START, "average": 0},
                    {"timestamp": START + 700000, "average": None},
                    {"timestamp": START + 800000, "average": float("nan")},
                ],
            }
        ]
    }
    result = await MonitoringService(client).query_metrics(
        instance_id="i",
        metrics=[component],
        start_time=START,
        end_time=END,
        max_points=1,
    )
    call = client.calls[-1][1]
    assert call["metrics"][0]["dimensions"] == [INSTANCE, NODE, COMPONENT]
    assert "unit" not in call["metrics"][0]
    series = result["items"][0]
    assert series["status"] == "ok"
    assert series["datapoint_count"] == 3
    assert series["datapoints_truncated"] is True
    assert series["datapoints"] == [{"timestamp": START + 600000, "value": 20}]
    assert series["summary"] == {
        "minimum": 0,
        "maximum": 20,
        "aggregation_values_mean": 10,
        "latest_value": 20,
        "latest_timestamp": START + 600000,
    }


async def test_iso_time_raw_period_and_empty_series_are_explicit() -> None:
    client = FakeCesClient()
    result = await MonitoringService(client).query_metrics(
        instance_id="i",
        metrics=[METRIC],
        start_time="2026-10-27T10:00:00+08:00",
        end_time="2026-10-27T03:00:00Z",
        period=1,
        aggregation="max",
    )
    assert client.calls[0][1]["end_time"] - client.calls[0][1]["start_time"] == 3_600_000
    assert client.calls[0][1]["aggregation"] == "average"
    assert result["aggregation"] == "average"
    assert result["items"][0]["status"] == "no_data"
    assert result["items"][0]["summary"]["latest_value"] is None
    assert any("not zero" in hint for hint in result["hints"])


async def test_mixed_series_match_reordered_cloud_dimensions_and_keep_missing_series() -> None:
    client = FakeCesClient()
    storage = {**METRIC, "metric_name": "rds007_instance_disk_usage", "dimensions": [INSTANCE]}
    client.batch_response = {
        "metrics": [
            {
                **METRIC,
                "dimensions": [NODE, INSTANCE],
                "datapoints": [{"timestamp": START, "max": 0}],
            }
        ]
    }
    result = await MonitoringService(client).query_metrics(
        instance_id="i",
        metrics=[METRIC, storage],
        start_time=START,
        end_time=END,
        aggregation="max",
    )
    assert [item["status"] for item in result["items"]] == ["ok", "no_data"]
    assert result["items"][0]["summary"]["maximum"] == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"metrics": []},
        {"metrics": [METRIC] * 21},
        {"metrics": [METRIC, METRIC]},
        {"period": 2},
        {"period": True},
        {"period": 300.0},
        {"aggregation": "p95"},
        {"max_points": 0},
        {"max_points": 101},
        {"max_points": 1.5},
        {"start_time": "2026-10-27T10:00:00"},
        {"start_time": True},
        {"start_time": END},
        {"start_time": 1},
        {"end_time": END + 7 * 86400000, "period": 1},
    ],
)
async def test_invalid_queries_fail_before_cloud_access(overrides: dict[str, Any]) -> None:
    arguments: dict[str, Any] = {
        "instance_id": "i",
        "metrics": [METRIC],
        "start_time": START,
        "end_time": END,
    }
    arguments.update(overrides)
    with pytest.raises(McpToolError) as excinfo:
        await MonitoringService().query_metrics(**arguments)
    assert excinfo.value.code == "MCP_INVALID_ARGS"


@pytest.mark.parametrize(
    "descriptor",
    [
        {**METRIC, "namespace": "SYS.RDS"},
        {**METRIC, "metric_name": None},
        {**METRIC, "unexpected": 1},
        {**METRIC, "dimensions": []},
        {**METRIC, "dimensions": [NODE]},
        {**METRIC, "dimensions": [INSTANCE, COMPONENT]},
        {**METRIC, "dimensions": [INSTANCE, NODE, NODE]},
        {**METRIC, "dimensions": [{"name": "gaussdbv5_instance_id", "value": "other"}]},
        {**METRIC, "dimensions": [INSTANCE, {"name": "node", "value": ""}]},
        {**METRIC, "dimensions": [INSTANCE, {"bad": "dimension"}]},
        {**METRIC, "dimensions": [INSTANCE, {"name": "bad dimension", "value": "v"}]},
    ],
)
async def test_invalid_or_cross_instance_dimensions_fail_closed(descriptor: dict[str, Any]) -> None:
    with pytest.raises(McpToolError) as excinfo:
        await MonitoringService().query_metrics(
            instance_id="i",
            metrics=[descriptor],
            start_time=START,
            end_time=END,
        )
    assert excinfo.value.code == "MCP_INVALID_ARGS"


class RecordingSdk:
    def __init__(self) -> None:
        self.requests: list[tuple[str, Any]] = []

    def list_metrics(self, request: Any) -> dict[str, Any]:
        self.requests.append(("list_metrics", request))
        return {"metrics": [METRIC]}

    def batch_list_metric_data(self, request: Any) -> dict[str, Any]:
        self.requests.append(("batch_list_metric_data", request))
        return {"metrics": []}


async def test_sdk_request_models_preserve_ces_wire_contract(settings: McpSettings) -> None:
    from huaweicloudsdkces.v1 import CesClient as SdkCesClient

    sdk = RecordingSdk()
    client = CesMonitoringClient(settings, sdk_client=sdk)
    await client.list_metrics(
        namespace=GAUSSDB_NAMESPACE,
        dimensions=[INSTANCE, NODE, COMPONENT],
        metric_name="rds053_online_session",
        limit=20,
        marker="next",
    )
    request = sdk.requests[0][1]
    assert request.dim_0 == "gaussdbv5_instance_id,i"
    assert request.dim_1 == "gaussdbv5_node_id,n"
    assert request.dim_2 == "gaussdbv5_component_id,dn_6001"
    assert request.start == "next" and request.limit == 20
    list_info = SdkCesClient._list_metrics_http_info(request)
    assert list_info["method"] == "GET"
    assert list_info["resource_path"] == "/V1.0/{project_id}/metrics"
    await client.batch_list_metric_data(
        metrics=[METRIC],
        start_time=START,
        end_time=END,
        period=300,
        aggregation="average",
    )
    body = sdk.requests[1][1].body
    assert body._from == START and body.to == END
    assert body.attribute_map["_from"] == "from"
    assert body.period == "300" and body.filter == "average"
    assert body.metrics[0].namespace == GAUSSDB_NAMESPACE
    assert body.metrics[0].dimensions[1].value == "n"
    batch_info = SdkCesClient._batch_list_metric_data_http_info(sdk.requests[1][1])
    assert batch_info["method"] == "POST"
    assert batch_info["resource_path"] == "/V1.0/{project_id}/batch-query-metric-data"


async def test_sdk_errors_preserve_cloud_code_request_id_and_ces_permission_hint(
    settings: McpSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Broken(RecordingSdk):
        def list_metrics(self, request: Any) -> dict[str, Any]:
            raise RuntimeError("denied")

    monkeypatch.setattr(
        "mcp_server_gaussdb.client.ces_client.wrap_sdk_error",
        lambda exc: McpToolError("CES.403", "permission denied", request_id="req-ces"),
    )
    with pytest.raises(McpToolError) as excinfo:
        await CesMonitoringClient(settings, Broken()).list_metrics(
            namespace=GAUSSDB_NAMESPACE,
            dimensions=[INSTANCE],
            metric_name=None,
            limit=20,
            marker=None,
        )
    assert excinfo.value.code == "CES.403"
    assert excinfo.value.request_id == "req-ces"
    assert "ces:metrics:list" in (excinfo.value.hint or "")


@pytest.mark.parametrize("endpoint", [None, "https://ces.example.invalid"])
def test_client_reuses_project_credentials_and_uses_a_separate_ces_endpoint(
    settings: McpSettings,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str | None,
) -> None:
    captured: dict[str, Any] = {}

    class Builder:
        def with_credentials(self, value: Any) -> "Builder":
            captured["credentials"] = value
            return self

        def with_endpoint(self, value: str) -> "Builder":
            captured["endpoint"] = value
            return self

        def with_region(self, region: Any) -> "Builder":
            captured["endpoint"] = region.endpoints[0]
            return self

        def with_http_config(self, value: Any) -> "Builder":
            captured["timeout"] = value.timeout
            return self

        def build(self) -> RecordingSdk:
            return RecordingSdk()

    monkeypatch.setattr("huaweicloudsdkces.v1.CesClient.new_builder", lambda: Builder())
    monkeypatch.setenv("HUAWEICLOUD_ENDPOINT", "https://gaussdb.example.invalid")
    if endpoint:
        monkeypatch.setenv("HUAWEICLOUD_CES_ENDPOINT", endpoint)
    CesMonitoringClient(replace(settings, security_token="sts-monitoring"))
    assert captured["endpoint"] == (endpoint or "https://ces.cn-north-4.myhuaweicloud.com")
    assert captured["credentials"].project_id == settings.project_id
    assert captured["credentials"].ak == settings.access_key
    assert captured["credentials"].security_token == "sts-monitoring"
    assert captured["timeout"] == 60


async def test_monitoring_client_is_lazy_and_default_uses_current_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeCesClient()
    created: list[bool] = []

    def construct() -> FakeCesClient:
        created.append(True)
        return fake

    monkeypatch.setattr(
        "mcp_server_gaussdb.service.monitoring_service.CesMonitoringClient", construct
    )
    service = MonitoringService()
    assert created == []
    await service.list_metrics(instance_id="i")
    await service.query_metrics(
        instance_id="i", metrics=[deepcopy(METRIC)], start_time=START, end_time=END
    )
    assert created == [True]


async def test_monitoring_tools_work_through_read_only_mcp_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from huaweicloud_mcp_core import build_server

    fake = FakeCesClient()
    fake.list_response = {"metrics": [METRIC]}
    fake.batch_response = {
        "metrics": [
            {
                **METRIC,
                "datapoints": [{"timestamp": START, "average": 12}],
            }
        ]
    }
    service = MonitoringService(fake)
    monkeypatch.setattr(monitoring, "MonitoringService", lambda: service)
    server = build_server("monitoring-test", McpSettings(read_only=True))
    server.tool()(monitoring.list_monitoring_metrics)
    server.tool()(monitoring.query_monitoring_metrics)
    async with Client(server) as client:
        discovered = await client.call_tool("list_monitoring_metrics", {"instance_id": "i"})
        assert discovered.structured_content["items"][0]["dimensions"] == [INSTANCE, NODE]
        queried = await client.call_tool(
            "query_monitoring_metrics",
            {
                "instance_id": "i",
                "metrics": discovered.structured_content["items"],
                "start_time": START,
                "end_time": END,
            },
        )
        assert queried.structured_content["items"][0]["summary"]["latest_value"] == 12
