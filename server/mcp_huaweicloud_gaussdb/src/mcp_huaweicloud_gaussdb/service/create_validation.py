"""Validate and normalize instance creation without making cloud calls."""

import re
from typing import Any

from huaweicloud_mcp_core import McpToolError

from .create_common import _DEPLOYMENT_ALIASES, _RESERVED_PORTS
from .write_safety import require_manual_payment


def _require_create_fields(configuration: dict[str, Any]) -> None:
    require_manual_payment(configuration)
    required = {
        "name",
        "datastore",
        "ha",
        "password",
        "flavor_ref",
        "volume",
        "availability_zone",
        "vpc_id",
        "subnet_id",
        "security_group_id",
    }
    missing = sorted(required - configuration.keys())
    if missing:
        raise McpToolError(
            "MCP_INVALID_ARGS",
            f"Missing create configuration fields: {', '.join(missing)}.",
            hint=("Run list_flavors first and supply network, storage, datastore and HA settings."),
        )


def _normalize_deployment(body: dict[str, Any]) -> str | None:
    deployment_solution: str | None = body.pop("deployment_solution", None)
    if deployment_solution is not None:
        deployment_solution = _DEPLOYMENT_ALIASES.get(deployment_solution, deployment_solution)
    if deployment_solution == "logger":
        raise McpToolError(
            "MCP_UNSUPPORTED_OPERATION",
            "The public GaussDB v3.2 create API does not expose a deployment-solution "
            "selector for logger. Refusing to silently create a 1-primary/2-standby instance.",
            hint=(
                "Use discover_create_options to review the live logger template and ask the "
                "GaussDB API owner for the supported direct-create mapping, or create a "
                "single instance and separately review change_deployment_solution."
            ),
        )
    return deployment_solution


def _validate_ha(body: dict[str, Any]) -> dict[str, Any]:
    ha = body.get("ha") or {}
    if ha.get("instance_mode") not in {None, "basic", "enterprise", "ecology"}:
        raise McpToolError(
            "MCP_INVALID_ARGS", "ha.instance_mode must be basic, enterprise, or ecology."
        )
    if ha.get("consistency") not in {"strong", "eventual"}:
        raise McpToolError("MCP_INVALID_ARGS", "ha.consistency must be strong or eventual.")
    if ha.get("replication_mode") != "sync":
        raise McpToolError("MCP_INVALID_ARGS", "ha.replication_mode must be sync.")
    return ha


def _normalize_centralized(body: dict[str, Any], deployment_solution: str | None) -> None:
    if deployment_solution in {"combined", "hws"}:
        raise McpToolError(
            "MCP_INVALID_ARGS",
            f"deployment_solution={deployment_solution} is distributed-only.",
        )
    if body.get("sharding_num") is not None or body.get("coordinator_num") is not None:
        raise McpToolError(
            "MCP_INVALID_ARGS",
            "sharding_num and coordinator_num are distributed-only fields.",
        )
    replica_num = int(body.get("replica_num") or 3)
    if replica_num not in {1, 3}:
        raise McpToolError(
            "MCP_INVALID_ARGS",
            "centralized replica_num must be 1 (single replica) or 3 (HA).",
        )
    expected_replica_num = {"single": 1, "triset": 3}.get(deployment_solution or "")
    if expected_replica_num is not None and replica_num != expected_replica_num:
        raise McpToolError(
            "MCP_INVALID_ARGS",
            f"deployment_solution={deployment_solution} requires "
            f"replica_num={expected_replica_num}.",
        )
    _normalize_zones(
        body,
        replica_num,
        "availability_zone must contain one AZ or one AZ entry per centralized replica.",
    )


def _normalize_distributed(
    body: dict[str, Any], ha: dict[str, Any], deployment_solution: str | None
) -> None:
    product_type = ha.get("instance_mode") or "enterprise"
    if deployment_solution is None:
        deployment_solution = "combined" if product_type == "basic" else "hws"
    if product_type == "basic" and deployment_solution != "combined":
        raise McpToolError(
            "MCP_INVALID_ARGS",
            "distributed basic instances require deployment_solution=combined.",
        )
    if product_type in {"enterprise", "ecology"} and deployment_solution != "hws":
        raise McpToolError(
            "MCP_INVALID_ARGS",
            "distributed enterprise/ecology instances require deployment_solution=hws.",
        )
    if body.get("enable_single_float_ip") is not None:
        raise McpToolError("MCP_INVALID_ARGS", "enable_single_float_ip is centralized-only.")
    sharding_num = int(body.get("sharding_num") or 0)
    coordinator_num = int(body.get("coordinator_num") or 0)
    if not 1 <= sharding_num <= 256:
        raise McpToolError(
            "MCP_INVALID_ARGS", "distributed sharding_num must be between 1 and 256."
        )
    if not 1 <= coordinator_num <= min(256, sharding_num * 2):
        raise McpToolError(
            "MCP_INVALID_ARGS",
            "distributed coordinator_num must be between 1 and 256 and no more than "
            "twice sharding_num.",
        )
    replica_num = int(body.get("replica_num") or 3)
    if replica_num != 3:
        raise McpToolError("MCP_INVALID_ARGS", "distributed replica_num must be 3.")
    _normalize_zones(
        body,
        replica_num,
        "availability_zone must contain one AZ or three AZ entries for a distributed instance.",
    )


def _normalize_zones(body: dict[str, Any], replica_num: int, message: str) -> None:
    zones = [zone.strip() for zone in str(body["availability_zone"]).split(",")]
    if len(zones) == 1:
        zones *= replica_num
    if len(zones) != replica_num:
        raise McpToolError("MCP_INVALID_ARGS", message)
    body["availability_zone"] = ",".join(zones)
    body["replica_num"] = replica_num


def _validate_volume(body: dict[str, Any]) -> None:
    volume = body.get("volume") or {}
    if volume.get("type") not in {"ULTRAHIGH", "ESSD"}:
        raise McpToolError("MCP_INVALID_ARGS", "volume.type must be ULTRAHIGH or ESSD.")
    volume_size = int(volume.get("size") or 0)
    shard_factor = int(body.get("sharding_num") or 1)
    if not shard_factor * 40 <= volume_size <= shard_factor * 24000:
        raise McpToolError(
            "MCP_INVALID_ARGS",
            "volume.size must be between sharding_num*40 and sharding_num*24000 GiB.",
        )
    if volume_size % (shard_factor * 4) != 0:
        raise McpToolError(
            "MCP_INVALID_ARGS", "volume.size must be a multiple of sharding_num*4 GiB."
        )


def _validate_connection(body: dict[str, Any]) -> None:
    port = int(body.get("port") or 8000)
    if not 1024 <= port <= 39998 or port in _RESERVED_PORTS:
        raise McpToolError("MCP_INVALID_ARGS", "port must be 1024-39998 and must not be reserved.")
    if body.get("time_zone") is not None and not re.fullmatch(
        r"UTC(?:[+-](?:0\d|1[0-2]):00)", str(body["time_zone"])
    ):
        raise McpToolError(
            "MCP_INVALID_ARGS",
            "time_zone must be a full-hour value from UTC-12:00 to UTC+12:00.",
        )


def _validate_backup(body: dict[str, Any]) -> None:
    backup = body.get("backup_strategy")
    if backup:
        keep_days = int(backup.get("keep_days") or 7)
        if not 1 <= keep_days <= 36500:
            raise McpToolError(
                "MCP_INVALID_ARGS", "backup_strategy.keep_days must be between 1 and 36500."
            )
        start_time = backup.get("start_time")
        if not isinstance(start_time, str) or not re.fullmatch(
            r"(?:[01]\d|2[0-3]):00-(?:[01]\d|2[0-3]):00", start_time
        ):
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "backup_strategy.start_time must use HH:00-HH:00 UTC format.",
            )
        start_hour, end_hour = (int(value[:2]) for value in start_time.split("-"))
        if end_hour != (start_hour + 1) % 24:
            raise McpToolError("MCP_INVALID_ARGS", "backup window must span exactly one hour.")


def _validate_charge(body: dict[str, Any]) -> None:
    charge = body.get("charge_info")
    if charge:
        charge = dict(charge)
        body["charge_info"] = charge
        charge_mode = charge.get("charge_mode")
        if charge_mode not in {"postPaid", "prePaid"}:
            raise McpToolError(
                "MCP_INVALID_ARGS", "charge_info.charge_mode must be postPaid or prePaid."
            )
        if charge_mode == "prePaid":
            charge.setdefault("is_auto_pay", "false")
            charge.setdefault("is_auto_renew", "false")
            period_type = charge.get("period_type")
            period_num = int(charge.get("period_num") or 0)
            valid_period = (period_type == "month" and 1 <= period_num <= 9) or (
                period_type == "year" and 1 <= period_num <= 3
            )
            if not valid_period:
                raise McpToolError(
                    "MCP_INVALID_ARGS",
                    "prePaid requires period_type month with period_num 1-9, or year with "
                    "period_num 1-3.",
                )


def prepare_create_body(configuration: dict[str, Any], region: str) -> dict[str, Any]:
    """Apply existing topology, storage, network, backup and billing checks in order."""
    _require_create_fields(configuration)
    body = {**configuration, "region": configuration.get("region") or region}
    deployment_solution = _normalize_deployment(body)
    ha = _validate_ha(body)
    if ha.get("mode") == "centralization_standard":
        _normalize_centralized(body, deployment_solution)
    elif ha.get("mode") == "enterprise":
        _normalize_distributed(body, ha, deployment_solution)
    else:
        raise McpToolError(
            "MCP_INVALID_ARGS", "ha.mode must be centralization_standard or enterprise."
        )
    _validate_volume(body)
    _validate_connection(body)
    _validate_backup(body)
    _validate_charge(body)
    return body
