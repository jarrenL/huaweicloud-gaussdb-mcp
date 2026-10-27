"""Read-only GaussDB monitoring tools backed by Cloud Eye (CES)."""

from typing import Any

from huaweicloud_mcp_core import ToolRisk, guard

from ..server import mcp
from ..service.monitoring_service import MonitoringService


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def list_monitoring_metrics(
    instance_id: str,
    metric_name: str | None = None,
    node_id: str | None = None,
    component_id: str | None = None,
    limit: int = 20,
    marker: str | None = None,
) -> dict[str, Any]:
    """Discover live CES monitoring metrics for a GaussDB instance.

    Scenario: find CPU, memory, disk, session or transaction metrics actually reported by the
    selected instance, including centralized/distributed node and component dimensions.

    Args:
        instance_id: GaussDB instance ID obtained from list_instances.
        metric_name: Optional exact metric ID, e.g. rds001_cpu_util; discover availability first.
        node_id: Optional node ID from get_instance or previous metric discovery.
        component_id: Optional component ID; requires node_id.
        limit: Page size, clamped to 1-100; default 20.
        marker: CES marker from the preceding response; omitted for the first page.

    Returns:
        Live metric IDs, units, complete ordered dimensions, and pagination metadata. Reuse the
        returned metric objects in query_monitoring_metrics. Requires ces:metrics:list permission.
    """
    return await MonitoringService().list_metrics(
        instance_id=instance_id,
        metric_name=metric_name,
        node_id=node_id,
        component_id=component_id,
        limit=limit,
        marker=marker,
    )


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def query_monitoring_metrics(
    instance_id: str,
    metrics: list[dict[str, Any]],
    start_time: int | str,
    end_time: int | str,
    period: int = 300,
    aggregation: str = "average",
    max_points: int = 20,
) -> dict[str, Any]:
    """Batch-query GaussDB monitoring time series and summaries through CES.

    Scenario: investigate CPU, memory, storage, connection or transaction trends. First discover
    current metrics with list_monitoring_metrics; never treat missing samples as zero.

    Args:
        instance_id: Target instance ID; all metric dimensions must belong to this instance.
        metrics: 1-20 objects from list_monitoring_metrics.items, including metric_name and
            complete ordered dimensions; namespace/unit may be retained from discovery.
        start_time: Epoch milliseconds or ISO 8601 with a timezone, e.g. 2026-10-27T10:00:00+08:00.
        end_time: Query end in the same formats, later than start_time.
        period: CES aggregation seconds: 1 (raw), 60, 300, 1200, 3600, 14400 or 86400; default 300.
        aggregation: average, variance, min, max or sum; period=1 always uses average.
        max_points: Most recent displayed points per series, from 1-100; default 20. Summaries use
            all received in-window points. Oversized CES windows are rejected before a cloud call.

    Returns:
        Time series, units, per-series no_data flags and summaries. Requires ces:metricData:list.
    """
    return await MonitoringService().query_metrics(
        instance_id=instance_id,
        metrics=metrics,
        start_time=start_time,
        end_time=end_time,
        period=period,
        aggregation=aggregation,
        max_points=max_points,
    )
