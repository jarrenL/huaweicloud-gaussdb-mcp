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
    start_time: int | str,
    end_time: int | str,
    threshold: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """Query and rank GaussDB slow SQL records by average execution time.

    Scenario: investigate performance degradation across selected nodes and return a compact ranked
    view. SQL text is cloud-provided data and may contain business-sensitive information.

    Args:
        instance_id: Target GaussDB instance ID.
        node_ids: One to 100 node IDs from get_instance.node_ids.
        start_time: Query start as Unix epoch milliseconds or timezone-aware ISO 8601, for example
            1761046200000, 2026-10-21T15:30:00+08:00, or 2026-10-21T07:30:00Z.
        end_time: Query end in the same formats, later than start_time.
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


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def wait_job(
    job_id: str,
    timeout_seconds: int = 300,
    poll_interval_seconds: int = 10,
) -> dict[str, Any]:
    """Wait for a GaussDB management job to reach a terminal status.

    Scenario: track a long-running create, backup, resize, expansion, restart, parameter, or
    switchover job without requiring the Agent to issue many individual get_job calls.

    Args:
        job_id: Job ID returned by a GaussDB write tool.
        timeout_seconds: Maximum local wait, from 1 to 1800 seconds; default 300.
        poll_interval_seconds: Poll interval, from 1 to 60 seconds; default 10.

    Returns:
        Latest job state, terminal/success flags, timeout flag, poll count and elapsed time.
    """
    return await GaussDBService().wait_job(
        job_id=job_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
