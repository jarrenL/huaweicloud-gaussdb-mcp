"""Scenario-oriented GaussDB management service."""

import asyncio
import re
import time
from typing import Any

from huaweicloud_mcp_core import McpToolError, page_result, single_result
from huaweicloud_mcp_core.output import clamp_limit

from ..client.gaussdb_client import GaussDBClient
from ..client.vpc_client import VpcResourceClient
from ..compat.guardrails.protect import assert_not_protected
from ..compat.settings import McpSettings
from .create_common import (
    _FLAVOR_FIELDS,
    _pick,
)
from .create_options import CreateOptionsService
from .create_validation import prepare_create_body
from .parameter_validation import (
    _parameter_modifiability,
    _plan_parameter_changes,
    _validate_parameter_metadata,
    parameter_detail,
)
from .parameter_validation import (
    _parameter_risk_reasons as _parameter_risk_reasons,
)
from .parameter_validation import (
    _validate_parameter_value as _validate_parameter_value,
)
from .time_utils import normalize_time_ms
from .write_safety import require_manual_payment

_INSTANCE_FIELDS = (
    "id",
    "name",
    "status",
    "private_ips",
    "public_ips",
    "port",
    "type",
    "ha",
    "replica_num",
    "region",
    "datastore",
    "created",
    "updated",
    "vpc_id",
    "subnet_id",
    "security_group_id",
    "flavor_ref",
    "flavor_info",
    "volume",
    "maintenance_window",
    "enterprise_project_id",
    "instance_mode",
    "charge_info",
    "time_zone",
    "tags",
    "disk_usage",
)
_BACKUP_FIELDS = (
    "id",
    "name",
    "description",
    "begin_time",
    "end_time",
    "status",
    "size",
    "type",
    "datastore",
    "instance_id",
)
_SLOW_SQL_FIELDS = (
    "db_name",
    "schema_name",
    "sql_id",
    "user_name",
    "sql_text",
    "calls",
    "avg_exec_time",
    "avg_cpu_time",
    "avg_io_time",
    "avg_returned_rows",
    "avg_fetched_rows",
    "buffer_hit_ratio",
    "sql_hit_ratio",
    "node_id",
    "node_name",
)
_JOB_FIELDS = ("id", "name", "status", "created", "ended", "progress", "instance", "fail_reason")
_JOB_SUCCESS_STATUSES = {"COMPLETED", "SUCCESS", "SUCCEEDED", "FINISHED"}
_JOB_FAILURE_STATUSES = {"FAILED", "FAIL", "ERROR", "CANCELLED", "CANCELED"}
_JOB_TERMINAL_STATUSES = _JOB_SUCCESS_STATUSES | _JOB_FAILURE_STATUSES
_NODE_FIELDS = ("id", "name", "availability_zone_id", "status", "description", "components")

_DISTRIBUTED_CREATE_BINDING_ERRORS = {"DBS.200054", "DBS.06280045"}


def _job_hints(job: dict[str, Any]) -> list[str]:
    if str(job.get("name") or "").upper() == "SWITCHDN":
        return [
            "After a completed SWITCHDN job, the instance can temporarily enter BACKING UP "
            "while an automatic backup runs. Call get_instance until status is ACTIVE before "
            "starting another write operation."
        ]
    return []


_DIFFERENTIAL_BACKUP_INTERVALS = {15, 30, 60, 180, 360, 720, 1440}


def _next_marker(offset: int, count: int, total: int | None) -> str | None:
    next_offset = offset + count
    return str(next_offset) if total is not None and next_offset < total else None


class GaussDBService:
    def __init__(
        self,
        client: GaussDBClient | None = None,
        settings: McpSettings | None = None,
        network_client: VpcResourceClient | None = None,
    ) -> None:
        self._settings = settings or McpSettings.from_env()
        self._client = client or GaussDBClient(self._settings)
        self._network_client = network_client

    async def discover_create_options(
        self,
        *,
        ha_mode: str = "centralization_standard",
        deployment_mode: str | None = None,
        product_type: str = "basic",
        version: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return await CreateOptionsService(
            self._client, self._settings, self._network_client
        ).discover_create_options(
            ha_mode=ha_mode,
            deployment_mode=deployment_mode,
            product_type=product_type,
            version=version,
            limit=limit,
        )

    async def list_instances(
        self, *, name: str | None = None, limit: int = 20, marker: str | None = None
    ) -> dict[str, Any]:
        limit, offset = clamp_limit(limit), int(marker or 0)
        response = await self._client.list_database_instances(
            limit=limit, offset=offset, instance_id=None, name=name
        )
        items = [_pick(item, _INSTANCE_FIELDS) for item in response.get("instances") or []]
        total = response.get("total_count")
        return page_result(items, total=total, marker=_next_marker(offset, len(items), total))

    async def get_instance(self, *, instance_id: str) -> dict[str, Any]:
        response = await self._client.list_database_instances(
            limit=1, offset=0, instance_id=instance_id, name=None
        )
        instances = response.get("instances") or []
        if not instances:
            raise McpToolError(
                "MCP_NOT_FOUND",
                f"GaussDB instance '{instance_id}' was not found.",
                hint="Run list_instances to retrieve an instance ID in the configured region.",
            )
        result = _pick(instances[0], _INSTANCE_FIELDS)
        hints: list[str] = []
        try:
            components = await self._client.invoke_openapi(
                operation="list_component_infos",
                request={"instance_id": instance_id, "limit": 100},
            )
            nodes = [_pick(node, _NODE_FIELDS) for node in components.get("nodes") or []]
            result["nodes"] = nodes
            result["node_ids"] = [node["id"] for node in nodes if node.get("id")]
            result["nodes_total"] = components.get("total_count", len(nodes))
        except McpToolError as exc:
            result["node_ids"] = []
            result["node_discovery_error"] = {"code": exc.code, "message": exc.message}
            hints.append(
                "Instance details were returned, but node discovery failed. Grant the component "
                "list permission before calling analyze_slow_sql."
            )
        return single_result(result, hints or None)

    async def list_flavors(
        self,
        *,
        version: str | None = None,
        ha_mode: str | None = None,
        limit: int = 20,
        marker: str | None = None,
    ) -> dict[str, Any]:
        if ha_mode not in {None, "enterprise", "centralization_standard", "combined"}:
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "ha_mode must be enterprise, combined, or centralization_standard.",
            )
        limit, offset = clamp_limit(limit), int(marker or 0)
        response = await self._client.list_flavors_details(
            version=version, ha_mode=ha_mode, limit=limit, offset=offset
        )
        items = [_pick(item, _FLAVOR_FIELDS) for item in response.get("flavors") or []]
        total = response.get("total")
        return page_result(items, total=total, marker=_next_marker(offset, len(items), total))

    async def create_instance(self, *, configuration: dict[str, Any]) -> dict[str, Any]:
        body = prepare_create_body(configuration, self._settings.region)
        ha = body.get("ha") or {}
        try:
            response = await self._client.create_database_instance(body=body)
        except McpToolError as exc:
            if exc.code in _DISTRIBUTED_CREATE_BINDING_ERRORS and ha.get("mode") == "enterprise":
                raise McpToolError(
                    exc.code,
                    exc.message,
                    request_id=exc.request_id,
                    doc_url=exc.doc_url,
                    hint=(
                        "The flavor was visible in the regional catalog, but Huawei Cloud rejected "
                        "the distributed region/tenant/engine/product binding. Run "
                        "discover_create_options again and choose another returned flavor, product "
                        "edition, or region. Do not hard-code availability from another region."
                    ),
                ) from None
            raise
        instance = response.get("instance") or {}
        payload = {
            **_pick(response, ("job_id", "instance_id", "order_id")),
            **({"instance_id": instance["id"]} if instance.get("id") else {}),
        }
        hints = []
        if payload.get("order_id"):
            hints.append(
                "Call get_order with order_id to check billing status and the actual amount. "
                "An unpaid order does not mean an instance has been provisioned. "
                "After approval for the exact amount and currency, use pay_order. "
                "To abandon an unpaid order, use cancel_order after confirmation."
            )
        if payload.get("job_id"):
            hints.append("Creation is asynchronous; call wait_job with job_id to track completion.")
        hints.append("Verify the final instance state with get_instance after provisioning.")
        return single_result(payload, hints)

    async def delete_instance(self, *, instance_id: str) -> dict[str, Any]:
        response = await self._client.list_database_instances(
            limit=1, offset=0, instance_id=instance_id, name=None
        )
        instances = response.get("instances") or []
        if not instances:
            raise McpToolError(
                "MCP_NOT_FOUND",
                f"GaussDB instance '{instance_id}' was not found.",
                hint="Run list_instances to verify whether it has already been deleted.",
            )
        instance = _pick(instances[0], _INSTANCE_FIELDS)
        assert_not_protected(instance, tool_name="delete_instance")
        result = await self._client.delete_instance(instance_id=instance_id)
        return single_result(
            {
                "instance_id": instance_id,
                "instance_name": instance.get("name"),
                **_pick(result, ("job_id", "order_id")),
            },
            [
                "Deletion is asynchronous; call get_job when job_id is returned, then verify "
                "with list_instances.",
            ],
        )

    async def list_backups(
        self,
        *,
        instance_id: str,
        backup_type: str | None = None,
        begin_time: str | None = None,
        end_time: str | None = None,
        limit: int = 20,
        marker: str | None = None,
    ) -> dict[str, Any]:
        limit, offset = clamp_limit(limit), int(marker or 0)
        response = await self._client.list_backups_details(
            instance_id=instance_id,
            backup_type=backup_type,
            begin_time=begin_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
        items = [_pick(item, _BACKUP_FIELDS) for item in response.get("backups") or []]
        total = response.get("total_count")
        return page_result(items, total=total, marker=_next_marker(offset, len(items), total))

    async def create_manual_backup(
        self, *, instance_id: str, name: str, description: str | None = None
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{3,63}", name):
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "Backup name must be 4-64 characters and start with a letter.",
            )
        response = await self._client.create_manual_backup(
            instance_id=instance_id, name=name, description=description
        )
        return single_result(
            _pick(response, ("backup_id", "job_id")),
            [
                "Backup creation is asynchronous; query list_backups and get_job "
                "before relying on it.",
            ],
        )

    async def resize_instance(
        self, *, instance_id: str, flavor_ref: str, is_auto_pay: bool = False
    ) -> dict[str, Any]:
        require_manual_payment({"is_auto_pay": is_auto_pay})
        response = await self._client.resize_instances_flavor(
            instance_id=instance_id, flavor_ref=flavor_ref, is_auto_pay=is_auto_pay
        )
        return single_result(
            _pick(response, ("job_id", "order_id")),
            [
                "Specification changes can interrupt connections; track job_id with get_job.",
            ],
        )

    async def expand_instance(
        self,
        *,
        instance_id: str,
        new_volume_size_gb: int | None = None,
        coordinator_az_codes: list[str] | None = None,
        dn_shard_count: int | None = None,
        is_auto_pay: bool = False,
    ) -> dict[str, Any]:
        require_manual_payment({"is_auto_pay": is_auto_pay})
        selected = sum(
            value is not None and value != []
            for value in (new_volume_size_gb, coordinator_az_codes, dn_shard_count)
        )
        if selected != 1:
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "Choose exactly one expansion type: volume, coordinator nodes, or DN shards.",
            )
        body: dict[str, Any] = {"is_auto_pay": str(is_auto_pay).lower()}
        if new_volume_size_gb is not None:
            if new_volume_size_gb <= 0:
                raise McpToolError("MCP_INVALID_ARGS", "new_volume_size_gb must be positive.")
            body["enlarge_volume"] = {"size": new_volume_size_gb}
        elif coordinator_az_codes:
            body["expand_cluster"] = {
                "coordinators": [{"az_code": zone} for zone in coordinator_az_codes]
            }
        else:
            if not dn_shard_count or dn_shard_count <= 0:
                raise McpToolError("MCP_INVALID_ARGS", "dn_shard_count must be positive.")
            body["expand_cluster"] = {"shard": {"count": dn_shard_count}}
        response = await self._client.run_instance_action(instance_id=instance_id, body=body)
        return single_result(
            _pick(response, ("job_id", "order_id")),
            [
                "Expansion is asynchronous and can take a long time; use get_job to track it.",
            ],
        )

    async def restart_instance(self, *, instance_id: str) -> dict[str, Any]:
        response = await self._client.restart_instance(instance_id=instance_id)
        return single_result(
            {"instance_id": instance_id, **_pick(response, ("job_id",))},
            [
                "Existing database connections can be interrupted; track job_id with get_job.",
            ],
        )

    async def get_instance_parameters(
        self,
        *,
        instance_id: str,
        name: str | None = None,
        modifiable_only: bool = False,
        limit: int = 20,
        marker: str | None = None,
    ) -> dict[str, Any]:
        response = await self._client.show_instance_configuration(instance_id=instance_id)
        parameters = response.get("configuration_parameters") or []
        if name:
            parameters = [
                item for item in parameters if name.lower() in str(item.get("name", "")).lower()
            ]
        modifiability_counts = {
            state: sum(_parameter_modifiability(item) == state for item in parameters)
            for state in ("modifiable", "read_only", "unknown")
        }
        if modifiable_only:
            parameters = [
                item for item in parameters if _parameter_modifiability(item) == "modifiable"
            ]
        offset, limit = int(marker or 0), clamp_limit(limit)
        items = [parameter_detail(item) for item in parameters[offset : offset + limit]]
        total = len(parameters)
        result = page_result(items, total=total, marker=_next_marker(offset, len(items), total))
        result["parameter_metadata"] = {
            "source_api_version": response.get("_metadata_api_version", "unknown"),
            **modifiability_counts,
        }
        if modifiability_counts["unknown"]:
            result["hints"] = [
                "Some parameters do not include readonly metadata. They are reported as "
                "modifiability=unknown and cannot be changed through the safe scenario tool."
            ]
        return result

    async def update_instance_parameters(
        self, *, instance_id: str, values: dict[str, str], confirm: bool = False
    ) -> dict[str, Any]:
        if not values or len(values) > 100:
            raise McpToolError("MCP_INVALID_ARGS", "values must contain 1-100 parameter changes.")
        current = await self._client.show_instance_configuration(instance_id=instance_id)
        parameters = current.get("configuration_parameters") or []
        parameter_map = {str(item.get("name") or ""): item for item in parameters}
        _validate_parameter_metadata(parameter_map, values, current)
        effective_values, changes, high_risk_parameters = _plan_parameter_changes(
            parameter_map, values
        )
        if not effective_values:
            return single_result(
                {
                    "instance_id": instance_id,
                    "updated_parameters": [],
                    "no_op": True,
                    "changes": [],
                },
                ["All requested values already match the current instance configuration."],
            )
        if high_risk_parameters and not confirm:
            return single_result(
                {
                    "confirmation_required": True,
                    "instance_id": instance_id,
                    "high_risk_parameters": sorted(high_risk_parameters),
                    "changes": changes,
                },
                [
                    "Review the old and new values, restart impact, and risk reasons, then call "
                    "update_instance_parameters again with confirm=true."
                ],
            )
        response = await self._client.update_instance_configuration(
            instance_id=instance_id, values=effective_values
        )
        return single_result(
            {
                "instance_id": instance_id,
                "updated_parameters": sorted(effective_values),
                "changes": changes,
                **_pick(response, ("job_id", "restart_required")),
            },
            [
                "Call get_instance_parameters to verify values and check whether a "
                "restart is required.",
            ],
        )

    async def analyze_slow_sql(
        self,
        *,
        instance_id: str,
        node_ids: list[str],
        start_time: int | str,
        end_time: int | str,
        threshold: int = 1,
        limit: int = 20,
    ) -> dict[str, Any]:
        start_time_ms = normalize_time_ms(start_time, "start_time")
        end_time_ms = normalize_time_ms(end_time, "end_time")
        if start_time_ms >= end_time_ms:
            raise McpToolError("MCP_INVALID_ARGS", "start_time must be earlier than end_time.")
        if not node_ids or len(node_ids) > 100:
            raise McpToolError("MCP_INVALID_ARGS", "node_ids must contain 1-100 node IDs.")
        if not 1 <= threshold <= 99:
            raise McpToolError("MCP_INVALID_ARGS", "threshold must be between 1 and 99 seconds.")
        response = await self._client.list_slow_sqls(
            instance_id=instance_id,
            node_ids=node_ids,
            start_time=start_time_ms,
            end_time=end_time_ms,
            threshold=threshold,
        )
        raw = response.get("slow_sql_infos") or []

        def duration(item: dict[str, Any]) -> float:
            try:
                return float(item.get("avg_exec_time") or 0)
            except (TypeError, ValueError):
                return 0.0

        raw.sort(key=duration, reverse=True)
        items = [_pick(item, _SLOW_SQL_FIELDS) for item in raw[: clamp_limit(limit)]]
        hints = []
        if items:
            hints.append(
                "Review the highest avg_exec_time entries and validate indexes and execution plans."
            )
        return {
            **page_result(items, total=response.get("total"), marker=None),
            "analysis": {
                "sort": "avg_exec_time_desc",
                "time_unit": "microseconds",
                "highest_avg_exec_time": items[0].get("avg_exec_time") if items else None,
                "query_window": {"start_time_ms": start_time_ms, "end_time_ms": end_time_ms},
            },
            "hints": hints,
        }

    async def get_job(self, *, job_id: str) -> dict[str, Any]:
        response = await self._client.show_job_detail(job_id=job_id)
        job = response.get("job") or response
        compact = _pick(job, _JOB_FIELDS)
        return single_result(compact, _job_hints(compact))

    async def wait_job(
        self,
        *,
        job_id: str,
        timeout_seconds: int = 300,
        poll_interval_seconds: int = 10,
    ) -> dict[str, Any]:
        if not 1 <= timeout_seconds <= 1800:
            raise McpToolError("MCP_INVALID_ARGS", "timeout_seconds must be between 1 and 1800.")
        if not 1 <= poll_interval_seconds <= 60:
            raise McpToolError(
                "MCP_INVALID_ARGS", "poll_interval_seconds must be between 1 and 60."
            )

        started = time.monotonic()
        deadline = started + timeout_seconds
        attempts = 0
        while True:
            attempts += 1
            response = await self._client.show_job_detail(job_id=job_id)
            job = response.get("job") or response
            compact = _pick(job, _JOB_FIELDS)
            status = str(compact.get("status") or "").upper()
            elapsed = max(0.0, time.monotonic() - started)
            if status in _JOB_TERMINAL_STATUSES:
                return single_result(
                    {
                        **compact,
                        "terminal": True,
                        "successful": status in _JOB_SUCCESS_STATUSES,
                        "timed_out": False,
                        "poll_attempts": attempts,
                        "elapsed_seconds": round(elapsed, 3),
                    },
                    _job_hints(compact),
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return single_result(
                    {
                        **compact,
                        "terminal": False,
                        "successful": None,
                        "timed_out": True,
                        "poll_attempts": attempts,
                        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
                    },
                    [
                        "The local wait timed out while the cloud job remained non-terminal. "
                        "Call wait_job again with the same job_id; do not resubmit the write."
                    ],
                )
            await asyncio.sleep(min(poll_interval_seconds, remaining))

    async def get_backup_policy(self, *, instance_id: str) -> dict[str, Any]:
        response = await self._client.show_backup_policy(instance_id=instance_id)
        policy = dict(response.get("backup_policy") or {})
        legacy_period = policy.pop("differential_priod", None)
        differential_period = policy.get("differential_period")
        if differential_period is None and legacy_period is not None:
            differential_period = legacy_period
        if differential_period is not None:
            try:
                policy["differential_period"] = int(differential_period)
            except (TypeError, ValueError):
                policy["differential_period"] = differential_period
        return single_result(
            {"instance_id": instance_id, "backup_policy": policy},
            [
                "differential_period is a minute interval. Pass its integer value directly to "
                "configure_backup_policy; the deprecated differential_priod spelling is "
                "normalized automatically."
            ],
        )

    async def configure_backup_policy(
        self,
        *,
        instance_id: str,
        keep_days: int,
        start_time: str,
        period: str,
        differential_period: int | str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= keep_days <= 732:
            raise McpToolError("MCP_INVALID_ARGS", "keep_days must be between 1 and 732.")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):00-(?:[01]\d|2[0-3]):00", start_time):
            raise McpToolError(
                "MCP_INVALID_ARGS", "start_time must use the UTC HH:00-HH:00 format."
            )
        if not re.fullmatch(r"[1-7](?:,[1-7])*", period):
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "period must be comma-separated weekday numbers from 1 to 7, for example 1,3,5.",
            )
        policy: dict[str, Any] = {
            "keep_days": keep_days,
            "start_time": start_time,
            "period": period,
        }
        interval_source = "request"
        if differential_period is None:
            current = await self._client.show_backup_policy(instance_id=instance_id)
            current_policy = current.get("backup_policy") or {}
            differential_period = current_policy.get("differential_period")
            if differential_period is None:
                differential_period = current_policy.get("differential_priod")
            interval_source = "current_policy"
        if differential_period is None:
            raise McpToolError(
                "MCP_BACKUP_POLICY_INCOMPLETE",
                "Huawei Cloud did not return the current differential backup interval.",
                hint=(
                    "Pass differential_period explicitly as one of 15, 30, 60, 180, 360, 720, "
                    "or 1440 minutes. Distributed instances require this field."
                ),
            )
        try:
            normalized_interval = int(differential_period)
        except (TypeError, ValueError) as exc:
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "differential_period must be a minute interval: "
                "15, 30, 60, 180, 360, 720, or 1440.",
            ) from exc
        if normalized_interval not in _DIFFERENTIAL_BACKUP_INTERVALS:
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "differential_period must be one of 15, 30, 60, 180, 360, 720, or 1440 minutes.",
            )
        # The read API returns an integer, while the generated write SDK model declares str.
        policy["differential_period"] = str(normalized_interval)
        response = await self._client.set_new_backup_policy(instance_id=instance_id, policy=policy)
        return single_result(
            {
                "instance_id": instance_id,
                "backup_policy_updated": True,
                "differential_period": normalized_interval,
                "differential_period_source": interval_source,
                **_pick(response, ("job_id",)),
            },
            [
                "Call get_backup_policy to verify the effective UTC schedule. When omitted, "
                "differential_period is read from the current policy and preserved automatically.",
            ],
        )
