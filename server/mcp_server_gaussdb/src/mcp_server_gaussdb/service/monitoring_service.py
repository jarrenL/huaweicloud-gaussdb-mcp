"""Discover GaussDB monitoring series and query bounded CES time windows."""

import math
import re
from typing import Any

from huaweicloud_mcp_core import McpToolError, clamp_limit, page_result

from ..client.ces_client import CesMonitoringClient
from .time_utils import normalize_time_ms

GAUSSDB_NAMESPACE = "SYS.GAUSSDBV5"
_INSTANCE_DIMENSION = "gaussdbv5_instance_id"
_NODE_DIMENSION = "gaussdbv5_node_id"
_COMPONENT_DIMENSION = "gaussdbv5_component_id"
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")
_PERIODS = {1, 60, 300, 1200, 3600, 14400, 86400}
_AGGREGATIONS = {"average", "variance", "min", "max", "sum"}
_METRIC_FIELDS = ("namespace", "metric_name", "dimensions", "unit")


def _invalid(message: str) -> McpToolError:
    return McpToolError(
        "MCP_INVALID_ARGS",
        message,
        hint="Call list_monitoring_metrics and reuse its metric_name and complete dimensions.",
    )


def _resource_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or "," in value:
        raise _invalid(f"{field} must be a nonempty resource ID of at most 256 characters.")
    return value


def _metric_name(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 96 or not _NAME.fullmatch(value):
        raise _invalid(
            "metric_name must start with a letter and contain only letters, digits, _ or -."
        )
    return value


def _descriptor(item: dict[str, Any], instance_id: str) -> dict[str, Any]:
    if not isinstance(item, dict) or set(item) - set(_METRIC_FIELDS):
        raise _invalid(
            "Each metric must contain metric_name and dimensions, with optional namespace/unit."
        )
    if item.get("namespace", GAUSSDB_NAMESPACE) != GAUSSDB_NAMESPACE:
        raise _invalid(f"This GaussDB tool only queries {GAUSSDB_NAMESPACE}.")
    metric_name = _metric_name(item.get("metric_name"))
    dimensions = item.get("dimensions")
    if not isinstance(dimensions, list) or not 1 <= len(dimensions) <= 4:
        raise _invalid("Each metric must include 1-4 ordered dimensions from CES discovery.")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, dimension in enumerate(dimensions):
        if not isinstance(dimension, dict) or set(dimension) != {"name", "value"}:
            raise _invalid("Every dimension must contain exactly name and value.")
        name, value = dimension["name"], dimension["value"]
        if not isinstance(name, str) or len(name) > 32 or not _NAME.fullmatch(name) or name in seen:
            raise _invalid(
                "Dimension names must be valid, unique CES names of at most 32 characters."
            )
        if name == _NODE_DIMENSION and index != 1:
            raise _invalid("The node dimension must follow the instance dimension.")
        if name == _COMPONENT_DIMENSION and (
            index != 2 or normalized[1]["name"] != _NODE_DIMENSION
        ):
            raise _invalid("The component dimension must follow the instance and node dimensions.")
        seen.add(name)
        normalized.append({"name": name, "value": _resource_id(value, "dimension.value")})
    if normalized[0] != {"name": _INSTANCE_DIMENSION, "value": instance_id}:
        raise _invalid(
            "Every metric must start with the selected GaussDB instance dimension and ID."
        )
    return {"namespace": GAUSSDB_NAMESPACE, "metric_name": metric_name, "dimensions": normalized}


def _key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("namespace"),
        item.get("metric_name"),
        tuple(sorted((dim["name"], dim["value"]) for dim in item.get("dimensions") or [])),
    )


class MonitoringService:
    def __init__(self, client: CesMonitoringClient | None = None) -> None:
        # Delay client construction until after argument validation.
        self._client = client

    def _ces(self) -> CesMonitoringClient:
        if self._client is None:
            self._client = CesMonitoringClient()
        return self._client

    async def list_metrics(
        self,
        *,
        instance_id: str,
        metric_name: str | None = None,
        node_id: str | None = None,
        component_id: str | None = None,
        limit: int = 20,
        marker: str | None = None,
    ) -> dict[str, Any]:
        dimensions = [
            {"name": _INSTANCE_DIMENSION, "value": _resource_id(instance_id, "instance_id")}
        ]
        if component_id is not None and node_id is None:
            raise _invalid("component_id requires node_id to preserve the dimension hierarchy.")
        for name, value in ((_NODE_DIMENSION, node_id), (_COMPONENT_DIMENSION, component_id)):
            if value is not None:
                dimensions.append({"name": name, "value": _resource_id(value, name)})
        if metric_name is not None:
            _metric_name(metric_name)
        response = await self._ces().list_metrics(
            namespace=GAUSSDB_NAMESPACE,
            dimensions=dimensions,
            metric_name=metric_name,
            limit=clamp_limit(limit),
            marker=marker,
        )
        items = [
            {key: metric[key] for key in _METRIC_FIELDS if metric.get(key) is not None}
            for metric in response.get("metrics") or []
        ]
        meta = response.get("meta_data") or {}
        next_marker = meta.get("marker") if items else None
        return {
            **page_result(items, total=meta.get("total"), marker=next_marker),
            "namespace": GAUSSDB_NAMESPACE,
            "instance_id": instance_id,
            "hints": [
                "Reuse each metric's complete ordered dimensions in query_monitoring_metrics; "
                "instance, node, and component metrics have different dimensions.",
                "Availability depends on region, topology, version and collection state. "
                "CES may retain discovery entries for three hours after a resource is deleted.",
            ],
        }

    async def query_metrics(
        self,
        *,
        instance_id: str,
        metrics: list[dict[str, Any]],
        start_time: int | str,
        end_time: int | str,
        period: int = 300,
        aggregation: str = "average",
        max_points: int = 20,
    ) -> dict[str, Any]:
        _resource_id(instance_id, "instance_id")
        if not isinstance(metrics, list) or not 1 <= len(metrics) <= 20:
            raise _invalid("metrics must contain 1-20 discovered series per tool call.")
        selected = [_descriptor(metric, instance_id) for metric in metrics]
        if len({_key(metric) for metric in selected}) != len(selected):
            raise _invalid("Duplicate metric/dimension combinations must be removed.")
        if isinstance(period, bool) or not isinstance(period, int) or period not in _PERIODS:
            raise _invalid("period must be 1, 60, 300, 1200, 3600, 14400 or 86400 seconds.")
        if not isinstance(aggregation, str) or aggregation not in _AGGREGATIONS:
            raise _invalid("aggregation must be average, variance, min, max or sum.")
        if (
            isinstance(max_points, bool)
            or not isinstance(max_points, int)
            or not 1 <= max_points <= 100
        ):
            raise _invalid("max_points must be between 1 and 100 per series.")
        start_ms = normalize_time_ms(start_time, "start_time")
        end_ms = normalize_time_ms(end_time, "end_time")
        if not 1111111111111 <= start_ms < end_ms <= 9999999999999:
            raise _invalid(
                "Use an increasing time range within CES's supported millisecond timestamps."
            )
        # CES interprets period=1 as raw points collected every 60 seconds for GaussDB.
        effective_period = 60 if period == 1 else period
        upper_bound = len(selected) * (
            math.ceil((end_ms - start_ms) / (effective_period * 1000)) + 1
        )
        if upper_bound > 3000:
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "The query could exceed CES's 3000-point batch limit.",
                hint="Shorten the time range, increase period, or split the metric list. "
                "The tool does not silently allow CES to shorten the requested time window.",
            )
        effective_aggregation = "average" if period == 1 else aggregation
        response = await self._ces().batch_list_metric_data(
            metrics=selected,
            start_time=start_ms,
            end_time=end_ms,
            period=period,
            aggregation=effective_aggregation,
        )
        returned = {_key(item): item for item in response.get("metrics") or []}
        items = []
        for metric in selected:
            cloud = returned.get(_key(metric), {})
            points = []
            for point in cloud.get("datapoints") or []:
                timestamp, value = point.get("timestamp"), point.get(effective_aggregation)
                if (
                    isinstance(timestamp, int)
                    and not isinstance(timestamp, bool)
                    and start_ms <= timestamp <= end_ms
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                ):
                    points.append({"timestamp": timestamp, "value": value})
            points.sort(key=lambda point: point["timestamp"])
            values = [point["value"] for point in points]
            items.append(
                {
                    **metric,
                    "unit": cloud.get("unit"),
                    "status": "ok" if points else "no_data",
                    "datapoint_count": len(points),
                    "datapoints": points[-max_points:],
                    "datapoints_truncated": len(points) > max_points,
                    "summary": {
                        "minimum": min(values) if values else None,
                        "maximum": max(values) if values else None,
                        "aggregation_values_mean": math.fsum(values) / len(values)
                        if values
                        else None,
                        "latest_value": points[-1]["value"] if points else None,
                        "latest_timestamp": points[-1]["timestamp"] if points else None,
                    },
                    "observed_window": {
                        "first_timestamp": points[0]["timestamp"] if points else None,
                        "last_timestamp": points[-1]["timestamp"] if points else None,
                    },
                }
            )
        hints = [
            "Summaries use all received aggregation values within the requested time window, "
            "not only the displayed points. aggregation_values_mean is not a raw-sample mean.",
            "Retention, collection periods and delay can leave gaps. observed_window reports "
            "actual received coverage, not guaranteed full coverage.",
        ]
        if any(item["status"] == "no_data" for item in items):
            hints.append(
                "No data is not zero or proof of health. Check the discovered dimensions, "
                "time range/retention, instance version, standby role, and collection delay."
            )
        if period == 1:
            hints.append("CES period=1 uses raw values; aggregation is forced to average.")
        return {
            **page_result(items, total=len(items)),
            "instance_id": instance_id,
            "namespace": GAUSSDB_NAMESPACE,
            "query_window": {"start_time_ms": start_ms, "end_time_ms": end_ms},
            "period": period,
            "aggregation": effective_aggregation,
            "max_points": max_points,
            "hints": hints,
        }
