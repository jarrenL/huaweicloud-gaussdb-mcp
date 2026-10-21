"""Scenario-oriented GaussDB management service."""

import asyncio
import difflib
import re
import time
from datetime import datetime
from typing import Any

from huaweicloud_mcp_core import (
    McpSettings,
    McpToolError,
    clamp_limit,
    page_result,
    resolve_project_context,
    single_result,
)
from huaweicloud_mcp_core.guardrails.protect import assert_not_protected

from ..client.gaussdb_client import GaussDBClient
from ..client.vpc_client import VpcResourceClient

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
_FLAVOR_FIELDS = (
    "vcpus",
    "ram",
    "spec_code",
    "az_status",
    "availability_zone",
    "version",
    "name",
    "group_type",
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

_DEPLOYMENT_FORMS = {
    "single": {
        "label": "单副本",
        "node_layout": "单节点",
        "intended_use": "development_and_functional_testing",
        "high_availability": False,
        "direct_create_supported": True,
    },
    "triset": {
        "label": "1主2备",
        "node_layout": "1 primary + 2 standby",
        "intended_use": "production",
        "high_availability": True,
        "direct_create_supported": True,
    },
    "logger": {
        "label": "1主1备1日志",
        "node_layout": "1 primary + 1 standby + 1 logger",
        "intended_use": "production",
        # The public v3.2 create model has no solution selector. Returning a triset-shaped
        # request for logger would silently create the wrong topology.
        "direct_create_supported": False,
    },
}
_DEPLOYMENT_ALIASES = {"single_replica": "single", "ha": "triset"}
_DISTRIBUTED_CREATE_BINDING_ERRORS = {"DBS.200054", "DBS.06280045"}
_RESERVED_PORTS = [
    2378,
    2379,
    2380,
    4999,
    5000,
    5999,
    6000,
    6001,
    8097,
    8098,
    12016,
    12017,
    20049,
    20050,
    21731,
    21732,
    32122,
    32123,
    32124,
]

_HIGH_RISK_PARAMETER_RE = re.compile(
    r"^(?:audit_|ssl(?:_|$)|password_encryption$|fsync$|full_page_writes$|"
    r"synchronous_commit$|wal_|archive_|max_connections$|shared_buffers$|work_mem$|"
    r"maintenance_work_mem$|temp_buffers$|enable_thread_pool$|use_workload_manager$|"
    r"enable_slot_log$|most_available_sync$|replconninfo)",
    re.IGNORECASE,
)


def _normalize_time_ms(value: int | str, field_name: str) -> int:
    """Normalize an epoch-millisecond or timezone-aware ISO 8601 value."""
    if isinstance(value, bool):
        normalized: int | None = None
    elif isinstance(value, int):
        normalized = value
    elif isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            normalized = int(text)
        else:
            try:
                iso_value = f"{text[:-1]}+00:00" if text.upper().endswith("Z") else text
                parsed = datetime.fromisoformat(iso_value)
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError("timezone required")
                normalized = int(parsed.timestamp() * 1000)
            except (OverflowError, ValueError):
                normalized = None
    else:
        normalized = None
    if normalized is None:
        raise McpToolError(
            "MCP_INVALID_ARGS",
            f"{field_name} must be Unix epoch milliseconds or ISO 8601 with a timezone.",
            hint=(
                f"Use an integer such as 1761046200000 or a value such as "
                f"2026-10-21T15:30:00+08:00 / 2026-10-21T07:30:00Z for {field_name}."
            ),
        )
    return normalized


def _job_hints(job: dict[str, Any]) -> list[str]:
    if str(job.get("name") or "").upper() == "SWITCHDN":
        return [
            "After a completed SWITCHDN job, the instance can temporarily enter BACKING UP "
            "while an automatic backup runs. Call get_instance until status is ACTIVE before "
            "starting another write operation."
        ]
    return []


_HIGH_RISK_DESCRIPTION_MARKERS = (
    "数据丢失",
    "丢失审计",
    "谨慎评估",
    "强制选主",
    "实例不可用",
    "业务异常",
    "data loss",
    "loss of audit",
    "service unavailable",
    "security risk",
)
_DIFFERENTIAL_BACKUP_INTERVALS = {15, 30, 60, 180, 360, 720, 1440}


def _pick(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in fields if source.get(key) is not None}


def _next_marker(offset: int, count: int, total: int | None) -> str | None:
    next_offset = offset + count
    return str(next_offset) if total is not None and next_offset < total else None


def _parameter_risk_reasons(parameter: dict[str, Any]) -> list[str]:
    reasons = []
    name = str(parameter.get("name") or "").split(":")[-1]
    description = str(parameter.get("description") or "").lower()
    if parameter.get("restart_required") is True:
        reasons.append("restart_required")
    if _HIGH_RISK_PARAMETER_RE.search(name):
        reasons.append("sensitive_parameter_family")
    if any(marker in description for marker in _HIGH_RISK_DESCRIPTION_MARKERS):
        reasons.append("risk_warning_in_cloud_description")
    return reasons


def _parameter_modifiability(parameter: dict[str, Any]) -> str:
    if parameter.get("readonly") is False:
        return "modifiable"
    if parameter.get("readonly") is True:
        return "read_only"
    return "unknown"


def _validate_parameter_value(parameter: dict[str, Any], value: str) -> str | None:
    if value.lower() == "default":
        return None
    parameter_type = str(parameter.get("type") or "").lower()
    value_range = str(parameter.get("value_range") or "").strip()
    if parameter_type == "boolean" and value.lower() not in {
        "on",
        "off",
        "true",
        "false",
        "0",
        "1",
    }:
        return "must be a boolean value (on/off, true/false, or 0/1)"

    numeric_value: float | None = None
    if parameter_type in {"integer", "float"}:
        try:
            numeric_value = int(value) if parameter_type == "integer" else float(value)
        except ValueError:
            return f"must be a valid {parameter_type}"

    numeric_range = re.fullmatch(r"(-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)", value_range)
    if numeric_value is not None and numeric_range:
        minimum, maximum = (float(item) for item in numeric_range.groups())
        if not minimum <= numeric_value <= maximum:
            return f"must be within {value_range}"

    if "|" in value_range and parameter_type not in {"list", "stringlist"}:
        allowed = {item.lower() for item in value_range.split("|")}
        if value.lower() not in allowed:
            return f"must be one of {value_range}"

    if parameter_type in {"list", "stringlist"} and "," in value_range:
        allowed = {item.strip().lower() for item in value_range.split(",")}
        selected = {item.strip().lower() for item in value.split(",")}
        if not selected <= allowed:
            return "contains an item outside the cloud-reported value_range"
    return None


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
        if ha_mode not in {"enterprise", "centralization_standard"}:
            raise McpToolError(
                "MCP_INVALID_ARGS", "ha_mode must be enterprise or centralization_standard."
            )
        if product_type not in {"basic", "enterprise", "ecology"}:
            raise McpToolError(
                "MCP_INVALID_ARGS", "product_type must be basic, enterprise, or ecology."
            )
        if deployment_mode == "ha":
            deployment_mode = (
                "triset"
                if ha_mode == "centralization_standard"
                else "combined"
                if product_type == "basic"
                else "hws"
            )
        elif deployment_mode is not None:
            deployment_mode = _DEPLOYMENT_ALIASES.get(deployment_mode, deployment_mode)
        if deployment_mode is None:
            deployment_mode = (
                "single"
                if ha_mode == "centralization_standard"
                else "combined"
                if product_type == "basic"
                else "hws"
            )
        valid_deployments = set(_DEPLOYMENT_FORMS)
        if ha_mode == "enterprise":
            valid_deployments = {"combined"} if product_type == "basic" else {"hws"}
        if deployment_mode not in valid_deployments:
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "deployment_mode must be single, triset, or logger for centralized instances; "
                "distributed basic uses combined, and distributed enterprise/ecology uses hws.",
            )
        flavor_ha_mode = "combined" if deployment_mode == "combined" else ha_mode
        storage_ha_mode = "enterprise" if deployment_mode == "combined" else ha_mode
        page_size = clamp_limit(limit)
        network = self._network_client or VpcResourceClient(self._settings)
        context, datastores, flavors, vpcs, subnets, security_groups = await asyncio.gather(
            asyncio.to_thread(resolve_project_context, self._settings),
            self._client.list_datastores(),
            self._client.list_flavors_details(
                # Fetch the full API page for availability decisions. The caller's limit only
                # controls how many choices are returned, not whether an edition looks sellable.
                version=version,
                ha_mode=flavor_ha_mode,
                limit=100,
                offset=0,
            ),
            network.list_vpcs(limit=100),
            network.list_subnets(limit=100),
            network.list_security_groups(limit=100),
        )
        engine_versions = datastores.get("versions") or []
        selected_version = version or (engine_versions[0] if engine_versions else None)
        all_flavors = list(flavors.get("flavors") or [])
        flavor_total = int(flavors.get("total") or len(all_flavors))
        if flavor_total > len(all_flavors):
            remaining_pages = await asyncio.gather(
                *(
                    self._client.list_flavors_details(
                        version=version,
                        ha_mode=flavor_ha_mode,
                        limit=100,
                        offset=offset,
                    )
                    for offset in range(100, flavor_total, 100)
                )
            )
            for page in remaining_pages:
                all_flavors.extend(page.get("flavors") or [])

        deployment_options: list[dict[str, Any]] = []
        storage_types: list[dict[str, Any]] = []
        if selected_version:
            if ha_mode == "centralization_standard":
                candidates = list(_DEPLOYMENT_FORMS)
                queries = [
                    self._client.show_deployment_form(
                        solution=solution, engine_version=selected_version
                    )
                    for solution in candidates
                ]
                responses = await asyncio.gather(*queries, return_exceptions=True)
                for solution, response in zip(candidates, responses, strict=True):
                    if isinstance(response, BaseException):
                        continue
                    definition = _DEPLOYMENT_FORMS[solution]
                    deployment_options.append(
                        {
                            "value": solution,
                            **definition,
                            "initial_node_num": response.get("initial_node_num"),
                            "replica_num": response.get("replica_num"),
                            "shard_num": response.get("shard_num"),
                            "availability_zone_entries": response.get("initial_node_num")
                            or response.get("replica_num"),
                            "source": "live_show_deployment_form",
                        }
                    )
            else:
                if product_type == "basic":
                    deployment_options = [
                        {
                            "value": "combined",
                            "label": "分布式混合部署",
                            "node_layout": "distributed combined deployment",
                            "replica_num": 3,
                            "availability_zone_entries": 3,
                            "intended_use": "production",
                            "high_availability": True,
                            "direct_create_supported": True,
                            "flavor_query_ha_mode": "combined",
                            "source": "live_combined_flavors_and_public_create_api",
                        }
                    ]
                else:
                    deployment_options = [
                        {
                            "value": "hws",
                            "label": "分布式独立部署",
                            "node_layout": "distributed independent deployment",
                            "replica_num": 3,
                            "availability_zone_entries": 3,
                            "intended_use": "production",
                            "high_availability": True,
                            "direct_create_supported": True,
                            "flavor_query_ha_mode": "enterprise",
                            "source": "live_enterprise_flavors_and_public_create_api",
                        }
                    ]

            storage_result = await asyncio.gather(
                self._client.list_storage_types(
                    version=selected_version,
                    # The storage API rejects "combined" even though the flavor API returns
                    # combined specs. The create request still uses mode=enterprise.
                    ha_mode=storage_ha_mode,
                ),
                return_exceptions=True,
            )
            if not isinstance(storage_result[0], BaseException):
                storage_types = [
                    _pick(item, ("name", "az_status", "support_compute_group_type"))
                    for item in storage_result[0].get("storage_type") or []
                ]

        flavor_items = []
        for item in all_flavors:
            spec_code = str(item.get("spec_code") or "")
            group_type = str(item.get("group_type") or "")
            is_basic = spec_code.startswith("gaussdb.bs.") or group_type in {
                "exclusive",
                "armExclusive",
            }
            is_ecology = any(
                marker in spec_code
                for marker in (".ecology.", "gaussdb.ec.", "gaussdb.opengauss.xe.")
            )
            matches_product = {
                "basic": is_basic,
                "ecology": is_ecology,
                "enterprise": not is_basic and not is_ecology,
            }[product_type]
            if not matches_product:
                continue
            available_zones = [
                zone for zone, status in (item.get("az_status") or {}).items() if status == "normal"
            ]
            if available_zones:
                flavor_items.append(
                    {**_pick(item, _FLAVOR_FIELDS), "available_zones": available_zones}
                )

        def number(value: Any) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return float("inf")

        flavor_items.sort(key=lambda item: (number(item.get("vcpus")), number(item.get("ram"))))
        for option in deployment_options:
            catalog_available = bool(flavor_items and storage_types)
            option["available"] = catalog_available
            option["available_flavor_count"] = len(flavor_items)
            option["availability_source"] = (
                "live_flavors_and_storage_types"
                if ha_mode == "enterprise"
                else "live_deployment_form_flavors_and_storage_types"
            )
            option["availability_semantics"] = (
                "catalog_candidate" if ha_mode == "enterprise" else "deployment_form_validated"
            )
            option["create_compatibility"] = (
                "cloud_final_validation_required"
                if ha_mode == "enterprise" and catalog_available
                else "not_applicable"
                if ha_mode == "enterprise"
                else "deployment_form_and_catalog_validated"
            )
        vpc_items = [
            _pick(item, ("id", "name", "cidr", "status"))
            for item in vpcs.get("vpcs") or []
            if item.get("status") in {None, "OK"}
        ]
        subnet_items = [
            _pick(
                item,
                (
                    "id",
                    "name",
                    "vpc_id",
                    "neutron_network_id",
                    "cidr",
                    "gateway_ip",
                    "availability_zone",
                    "status",
                ),
            )
            for item in subnets.get("subnets") or []
            if item.get("status") in {None, "ACTIVE"}
        ]
        group_items = [
            _pick(item, ("id", "name", "description"))
            for item in security_groups.get("security_groups") or []
        ]
        recommended: dict[str, Any] | None = None
        selected_deployment = next(
            (item for item in deployment_options if item["value"] == deployment_mode), None
        )
        if (
            flavor_items
            and vpc_items
            and subnet_items
            and group_items
            and storage_types
            and selected_deployment
            and selected_deployment["direct_create_supported"]
        ):
            flavor = flavor_items[0]
            vpc = vpc_items[0]
            subnet = next(
                (item for item in subnet_items if item.get("vpc_id") == vpc.get("id")),
                subnet_items[0],
            )
            group = next(
                (item for item in group_items if item.get("name") == "Sys-default"),
                group_items[0],
            )
            zone = flavor["available_zones"][0]
            replica_num = int(selected_deployment.get("replica_num") or 3)
            shard_num = 3 if ha_mode == "enterprise" else 1
            recommended = {
                "datastore": {
                    "type": "GaussDB",
                    "version": selected_version,
                },
                "ha": {
                    "mode": ha_mode,
                    "consistency": "strong",
                    "replication_mode": "sync",
                    "instance_mode": product_type,
                },
                "deployment_solution": deployment_mode,
                "flavor_ref": flavor.get("spec_code"),
                "volume": {
                    "type": storage_types[0].get("name"),
                    "size": shard_num * 40,
                },
                "availability_zone": ",".join([zone] * replica_num),
                "replica_num": replica_num,
                "vpc_id": vpc.get("id"),
                "subnet_id": subnet.get("neutron_network_id") or subnet.get("id"),
                "security_group_id": group.get("id"),
                "region": self._settings.region,
                "port": 8000,
                "time_zone": "UTC+08:00",
                "backup_strategy": {"start_time": "02:00-03:00", "keep_days": 7},
                "charge_info": {"charge_mode": "postPaid"},
            }
            if ha_mode == "enterprise":
                recommended.update({"sharding_num": shard_num, "coordinator_num": 3})
        return single_result(
            {
                "project": {
                    "project_id": context.project_id,
                    "domain_id": context.domain_id,
                    "region": self._settings.region,
                },
                "engine_versions": engine_versions,
                "flavors": flavor_items[:page_size],
                "available_flavor_count": len(flavor_items),
                "flavors_truncated": len(flavor_items) > page_size,
                "storage_types": storage_types,
                "vpcs": vpc_items,
                "subnets": subnet_items,
                "security_groups": group_items,
                "recommended_configuration": recommended,
                "recommended_configuration_status": (
                    "catalog_candidate_cloud_final_validation_required"
                    if recommended is not None and ha_mode == "enterprise"
                    else "deployment_form_and_catalog_validated"
                    if recommended is not None
                    else "unavailable"
                ),
                "deployment_options": deployment_options,
                "product_type_options": [
                    {
                        "value": "basic",
                        "label": "基础版",
                        "documented_centralized_compatibility": ["single", "triset", "logger"],
                        "documented_distributed_compatibility": ["combined"],
                        "availability_source": "live_flavor_query",
                    },
                    {
                        "value": "enterprise",
                        "label": "企业版",
                        "documented_centralized_compatibility": ["single", "triset", "logger"],
                        "documented_distributed_compatibility": ["hws"],
                        "availability_source": "live_flavor_query",
                    },
                    {
                        "value": "ecology",
                        "label": "生态版",
                        "availability": "requires_matching_live_flavor",
                        "documented_centralized_compatibility": ["single", "triset", "logger"],
                        "documented_distributed_compatibility": ["hws"],
                        "availability_source": "live_flavor_query",
                    },
                ],
                "create_field_options": {
                    "ha.mode": [
                        {"value": "centralization_standard", "label": "集中式"},
                        {"value": "enterprise", "label": "分布式"},
                    ],
                    "ha.consistency": [
                        {"value": "strong", "label": "强一致性"},
                        {"value": "eventual", "label": "最终一致性"},
                    ],
                    "ha.replication_mode": {
                        "values": ["sync"],
                        "single_value_reason": (
                            "The public create API supports synchronous replication only."
                        ),
                    },
                    "volume.type": {
                        "values": [item.get("name") for item in storage_types if item.get("name")],
                        "source": "live_list_storage_types",
                    },
                    "volume.size_gb": {
                        "minimum": "sharding_num * 40",
                        "maximum": "sharding_num * 24000",
                        "multiple_of": "sharding_num * 4",
                    },
                    "charge_info.charge_mode": ["postPaid", "prePaid"],
                    "charge_info.period_type": ["month", "year"],
                    "charge_info.period_num": {
                        "month": {"minimum": 1, "maximum": 9},
                        "year": {"minimum": 1, "maximum": 3},
                    },
                    "availability_zone": {
                        "values": sorted(
                            {
                                zone
                                for flavor in flavor_items
                                for zone in flavor.get("available_zones") or []
                            }
                        ),
                        "placement_modes": ["same_az", "multi_az"],
                        "entry_count": (
                            selected_deployment.get("availability_zone_entries")
                            if selected_deployment
                            else None
                        ),
                    },
                    "port": {
                        "minimum": 1024,
                        "maximum": 39998,
                        "default": 8000,
                        "reserved": _RESERVED_PORTS,
                    },
                    "time_zone": {
                        "values": [
                            f"UTC{offset:+03d}:00" if offset else "UTC+00:00"
                            for offset in range(-12, 13)
                        ]
                    },
                    "backup_strategy.start_time": {
                        "format": "HH:00-(HH+1):00 UTC",
                        "default": "02:00-03:00",
                    },
                    "backup_strategy.keep_days": {
                        "minimum": 1,
                        "maximum": 36500,
                        "default": 7,
                    },
                    "sharding_num": {
                        "applies_to": "distributed",
                        "minimum": 1,
                        "maximum": 256,
                    },
                    "coordinator_num": {
                        "applies_to": "distributed",
                        "minimum": 1,
                        "maximum": 256,
                        "constraint": "coordinator_num <= 2 * sharding_num",
                    },
                    "enable_force_switch": [False, True],
                    "enable_single_float_ip": {
                        "values": [False, True],
                        "applies_to": "centralized V2.0-3.207 or later",
                    },
                },
                "create_parameter_groups": {
                    "common": {
                        "required": [
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
                        ],
                        "optional": [
                            "configuration_id",
                            "port",
                            "backup_strategy",
                            "enterprise_project_id",
                            "disk_encryption_id",
                            "charge_info",
                            "time_zone",
                            "enable_force_switch",
                        ],
                    },
                    "centralized_only": {
                        "deployment_solutions": ["single", "triset", "logger"],
                        "fields": ["replica_num", "enable_single_float_ip"],
                        "forbidden": ["sharding_num", "coordinator_num"],
                        "replica_num_by_solution": {
                            "single": 1,
                            "triset": 3,
                            "logger": 3,
                        },
                    },
                    "distributed_only": {
                        "deployment_solutions_by_product": {
                            "basic": ["combined"],
                            "enterprise": ["hws"],
                            "ecology": ["hws"],
                        },
                        "required": ["sharding_num", "coordinator_num"],
                        "forbidden": ["enable_single_float_ip"],
                        "derived_defaults": {"replica_num": 3},
                        "volume_size_rule": {
                            "minimum": "sharding_num * 40",
                            "maximum": "sharding_num * 24000",
                            "multiple_of": "sharding_num * 4",
                        },
                    },
                },
                "selection": {
                    "ha_mode": ha_mode,
                    "deployment_mode": deployment_mode,
                    "product_type": product_type,
                    "flavor_query_ha_mode": flavor_ha_mode,
                    "storage_query_ha_mode": storage_ha_mode,
                },
            },
            [
                "Supply a new strong database password and review storage, network, placement, "
                "backup, and billing settings before creation.",
                (
                    "Single-replica instances have no HA or SLA and are intended only for "
                    "development and functional testing."
                    if deployment_mode == "single"
                    else "The public v3.2 create request has no deployment-solution field, so "
                    "logger is discoverable but is not passed to create_instance as triset."
                    if deployment_mode == "logger"
                    else "availability_zone contains one comma-separated entry per replica; "
                    "entries may repeat for same-AZ placement."
                ),
                (
                    "For distributed creation, live flavor and storage results are catalog "
                    "candidates, not proof that the current region, tenant, engine version, and "
                    "product edition are bound for creation. Huawei Cloud performs the final "
                    "compatibility check when create_instance runs."
                    if ha_mode == "enterprise"
                    else "Centralized deployment forms were validated through the live deployment "
                    "form API."
                ),
            ],
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
                hint=(
                    "Run list_flavors first and supply network, storage, datastore and HA settings."
                ),
            )
        body = {**configuration, "region": configuration.get("region") or self._settings.region}
        deployment_solution = body.pop("deployment_solution", None)
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
        ha = body.get("ha") or {}
        if ha.get("instance_mode") not in {None, "basic", "enterprise", "ecology"}:
            raise McpToolError(
                "MCP_INVALID_ARGS", "ha.instance_mode must be basic, enterprise, or ecology."
            )
        if ha.get("consistency") not in {"strong", "eventual"}:
            raise McpToolError("MCP_INVALID_ARGS", "ha.consistency must be strong or eventual.")
        if ha.get("replication_mode") != "sync":
            raise McpToolError("MCP_INVALID_ARGS", "ha.replication_mode must be sync.")
        if ha.get("mode") == "centralization_standard":
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
            expected_replica_num = {"single": 1, "triset": 3}.get(deployment_solution)
            if expected_replica_num is not None and replica_num != expected_replica_num:
                raise McpToolError(
                    "MCP_INVALID_ARGS",
                    f"deployment_solution={deployment_solution} requires "
                    f"replica_num={expected_replica_num}.",
                )
            zones = [zone.strip() for zone in str(body["availability_zone"]).split(",")]
            if len(zones) == 1:
                zones *= replica_num
            if len(zones) != replica_num:
                raise McpToolError(
                    "MCP_INVALID_ARGS",
                    "availability_zone must contain one AZ or one AZ entry per "
                    "centralized replica.",
                )
            body["availability_zone"] = ",".join(zones)
            body["replica_num"] = replica_num
        elif ha.get("mode") == "enterprise":
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
                raise McpToolError(
                    "MCP_INVALID_ARGS", "enable_single_float_ip is centralized-only."
                )
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
            zones = [zone.strip() for zone in str(body["availability_zone"]).split(",")]
            if len(zones) == 1:
                zones *= replica_num
            if len(zones) != replica_num:
                raise McpToolError(
                    "MCP_INVALID_ARGS",
                    "availability_zone must contain one AZ or three AZ entries for a "
                    "distributed instance.",
                )
            body["availability_zone"] = ",".join(zones)
            body["replica_num"] = replica_num
        else:
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "ha.mode must be centralization_standard or enterprise.",
            )

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

        port = int(body.get("port") or 8000)
        if not 1024 <= port <= 39998 or port in _RESERVED_PORTS:
            raise McpToolError(
                "MCP_INVALID_ARGS", "port must be 1024-39998 and must not be reserved."
            )
        if body.get("time_zone") is not None and not re.fullmatch(
            r"UTC(?:[+-](?:0\d|1[0-2]):00)", str(body["time_zone"])
        ):
            raise McpToolError(
                "MCP_INVALID_ARGS",
                "time_zone must be a full-hour value from UTC-12:00 to UTC+12:00.",
            )

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

        charge = body.get("charge_info")
        if charge:
            charge_mode = charge.get("charge_mode")
            if charge_mode not in {"postPaid", "prePaid"}:
                raise McpToolError(
                    "MCP_INVALID_ARGS", "charge_info.charge_mode must be postPaid or prePaid."
                )
            if charge_mode == "prePaid":
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
        return single_result(
            payload,
            [
                "Creation is asynchronous; call get_job with job_id until it reaches "
                "a terminal state.",
            ],
        )

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
        fields = (
            "name",
            "value",
            "restart_required",
            "readonly",
            "value_range",
            "type",
            "description",
        )
        items = []
        for item in parameters[offset : offset + limit]:
            risk_reasons = _parameter_risk_reasons(item)
            items.append(
                {
                    **_pick(item, fields),
                    "readonly": item.get("readonly"),
                    "modifiability": _parameter_modifiability(item),
                    "risk_level": "high" if risk_reasons else "normal",
                    "risk_reasons": risk_reasons,
                }
            )
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
        unknown = sorted(set(values) - parameter_map.keys())
        if unknown:
            suggestions = {
                name: difflib.get_close_matches(name, parameter_map.keys(), n=3, cutoff=0.6)
                for name in unknown
            }
            raise McpToolError(
                "MCP_INVALID_ARGS",
                f"Unknown instance parameters: {', '.join(unknown)}.",
                hint=f"Query get_instance_parameters first. Similar names: {suggestions}",
            )

        readonly = sorted(name for name in values if parameter_map[name].get("readonly") is True)
        unknown_modifiability = sorted(
            name
            for name in values
            if parameter_map[name].get("readonly") is not True
            and parameter_map[name].get("readonly") is not False
        )
        if readonly:
            raise McpToolError(
                "MCP_PARAMETER_READ_ONLY",
                f"Parameters are explicitly read-only: {', '.join(readonly)}.",
                hint="Choose parameters returned with modifiability=modifiable.",
            )
        if unknown_modifiability:
            source = current.get("_metadata_api_version", "unknown")
            raise McpToolError(
                "MCP_PARAMETER_MODIFIABILITY_UNKNOWN",
                "Huawei Cloud did not return readonly metadata for: "
                f"{', '.join(unknown_modifiability)}.",
                hint=(
                    f"Metadata source was {source}. Retry get_instance_parameters and only change "
                    "parameters returned with modifiability=modifiable. The generic OpenAPI "
                    "update path is intentionally blocked for this operation."
                ),
            )

        validation_errors = {}
        changes = []
        effective_values = {}
        high_risk_parameters = []
        for name, new_value in values.items():
            parameter = parameter_map[name]
            error = _validate_parameter_value(parameter, new_value)
            if error:
                validation_errors[name] = {
                    "message": error,
                    "value": new_value,
                    "value_range": parameter.get("value_range"),
                    "type": parameter.get("type"),
                }
                continue
            if str(parameter.get("value")) == new_value:
                continue
            risk_reasons = _parameter_risk_reasons(parameter)
            change = {
                "name": name,
                "old_value": parameter.get("value"),
                "new_value": new_value,
                "value_range": parameter.get("value_range"),
                "type": parameter.get("type"),
                "restart_required": bool(parameter.get("restart_required")),
                "risk_level": "high" if risk_reasons else "normal",
                "risk_reasons": risk_reasons,
            }
            changes.append(change)
            effective_values[name] = new_value
            if risk_reasons:
                high_risk_parameters.append(name)

        if validation_errors:
            raise McpToolError(
                "MCP_INVALID_ARGS",
                f"Parameter values failed local validation: {validation_errors}",
                hint="Use the cloud-reported type and value_range from get_instance_parameters.",
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
        start_time_ms = _normalize_time_ms(start_time, "start_time")
        end_time_ms = _normalize_time_ms(end_time, "end_time")
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
            raise McpToolError(
                "MCP_INVALID_ARGS", "timeout_seconds must be between 1 and 1800."
            )
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
