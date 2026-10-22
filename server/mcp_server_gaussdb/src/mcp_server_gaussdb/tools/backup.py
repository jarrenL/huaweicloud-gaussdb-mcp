"""GaussDB backup policy and manual-backup tools."""

from typing import Any

from huaweicloud_mcp_core import ToolRisk, guard

from ..server import mcp
from ..service.gaussdb_service import GaussDBService


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def list_backups(
    instance_id: str,
    backup_type: str | None = None,
    begin_time: str | None = None,
    end_time: str | None = None,
    limit: int = 20,
    marker: str | None = None,
) -> dict[str, Any]:
    """List backups for a GaussDB instance.

    Scenario: verify recovery points before maintenance, resize, expansion, or parameter changes.

    Args:
        instance_id: Target GaussDB instance ID.
        backup_type: Optional backup type filter.
        begin_time: Optional ISO 8601 range start accepted by the GaussDB API.
        end_time: Optional ISO 8601 range end accepted by the GaussDB API.
        limit: Page size, clamped to 1-100; default 20.
        marker: Offset marker returned by the previous call.

    Returns:
        A paginated backup list with status, type, size and timestamps.
    """
    return await GaussDBService().list_backups(
        instance_id=instance_id,
        backup_type=backup_type,
        begin_time=begin_time,
        end_time=end_time,
        limit=limit,
        marker=marker,
    )


@mcp.tool()
@guard(risk=ToolRisk.WRITE)
async def create_manual_backup(
    instance_id: str,
    name: str,
    description: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a manual backup for a GaussDB instance.

    Scenario: establish a named recovery point before an approved change. Backup creation is
    asynchronous.

    Args:
        instance_id: Target GaussDB instance ID.
        name: Unique 4-64 character name beginning with a letter.
        description: Optional description, up to the cloud API limit.
        confirm: Set true when a guardrail rule requests explicit confirmation.

    Returns:
        Backup or job identifiers and verification guidance.
    """
    return await GaussDBService().create_manual_backup(
        instance_id=instance_id, name=name, description=description
    )


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def get_backup_policy(instance_id: str) -> dict[str, Any]:
    """Get the automatic backup policy of a GaussDB instance.

    Scenario: inspect retention and the UTC schedule before changing backup policy.

    Args:
        instance_id: Target GaussDB instance ID.

    Returns:
        The effective automatic backup policy.
    """
    return await GaussDBService().get_backup_policy(instance_id=instance_id)


@mcp.tool()
@guard(risk=ToolRisk.WRITE)
async def configure_backup_policy(
    instance_id: str,
    keep_days: int,
    start_time: str,
    period: str,
    differential_period: int | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Configure the automatic backup retention and UTC schedule.

    Scenario: change automatic backup timing after get_backup_policy confirms the current policy.

    Args:
        instance_id: Target GaussDB instance ID.
        keep_days: Retention in days, 1-732.
        start_time: One-hour UTC window in HH:00-HH:00 format, for example 21:00-22:00.
        period: Comma-separated weekday numbers 1-7.
        differential_period: Optional differential-backup interval in minutes. Allowed values are
            15, 30, 60, 180, 360, 720, and 1440. If omitted, the server reads the current backup
            policy and preserves its value automatically because distributed instances require it.
            get_backup_policy returns this as an integer; this is unrelated to weekday period.
        confirm: Set true when a guardrail rule requests explicit confirmation.

    Returns:
        Update status and guidance to verify the effective policy.
    """
    return await GaussDBService().configure_backup_policy(
        instance_id=instance_id,
        keep_days=keep_days,
        start_time=start_time,
        period=period,
        differential_period=differential_period,
    )
