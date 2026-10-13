"""GaussDB operational analysis tools."""

from typing import Any

from huaweicloud_mcp_core import ToolRisk, guard

from ..server import mcp
from ..service.gaussdb_service import GaussDBService


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def analyze_slow_sql(
    instance_id: str,
    node_ids: list[str],
    start_time: int,
    end_time: int,
    threshold: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """Query and rank GaussDB slow SQL records by average execution time.

    Scenario: investigate performance degradation across selected nodes and return a compact ranked
    view. SQL text is cloud-provided data and may contain business-sensitive information.

    Args:
        instance_id: Target GaussDB instance ID.
        node_ids: One to 100 node IDs from get_instance.node_ids.
        start_time: Query start as an integer Unix timestamp in milliseconds, for example
            1760000000000. ISO date strings are not accepted.
        end_time: Query end as an integer Unix timestamp in milliseconds, later than start_time.
            ISO date strings are not accepted.
        threshold: Slow SQL threshold in seconds, from 1 to 99; default 1.
        limit: Maximum ranked records, clamped to 1-100; default 20.

    Returns:
        Ranked slow SQL records, compact analysis metadata and tuning guidance.
    """
    return await GaussDBService().analyze_slow_sql(
        instance_id=instance_id,
        node_ids=node_ids,
        start_time=start_time,
        end_time=end_time,
        threshold=threshold,
        limit=limit,
    )


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def get_job(job_id: str) -> dict[str, Any]:
    """Get the status of an asynchronous GaussDB management job.

    Scenario: track instance creation, backup, resize, expansion, restart, or parameter operations.

    Args:
        job_id: Job ID returned by a GaussDB write tool.

    Returns:
        Job status, progress, timestamps, instance reference and failure reason.
    """
    return await GaussDBService().get_job(job_id=job_id)
