"""Compose live creation options without embedding credentials or regional catalogs."""

import asyncio
from dataclasses import dataclass
from typing import Any

from huaweicloud_mcp_core import McpToolError, single_result
from huaweicloud_mcp_core.output import clamp_limit

from ..client.gaussdb_client import GaussDBClient
from ..client.vpc_client import VpcResourceClient
from ..compat.credentials import ProjectContext, resolve_project_context
from ..compat.runtime import run_sdk_call
from ..compat.settings import McpSettings
from .create_common import (
    _DEPLOYMENT_ALIASES,
    _DEPLOYMENT_FORMS,
    _FLAVOR_FIELDS,
    _RESERVED_PORTS,
    _pick,
)


@dataclass(frozen=True)
class _Selection:
    ha_mode: str
    deployment_mode: str
    product_type: str
    version: str | None

    @property
    def flavor_ha_mode(self) -> str:
        return "combined" if self.deployment_mode == "combined" else self.ha_mode

    @property
    def storage_ha_mode(self) -> str:
        return "enterprise" if self.deployment_mode == "combined" else self.ha_mode


@dataclass
class _Catalog:
    context: ProjectContext
    engine_versions: list[str]
    version: str | None
    flavors: list[dict[str, Any]]
    network: dict[str, list[dict[str, Any]]]


def _select_deployment(ha_mode: str, deployment_mode: str | None, product_type: str) -> str:
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
    return deployment_mode


def _available_flavors(
    all_flavors: list[dict[str, Any]], product_type: str
) -> list[dict[str, Any]]:
    flavor_items = []
    for item in all_flavors:
        spec_code = str(item.get("spec_code") or "")
        group_type = str(item.get("group_type") or "")
        is_basic = spec_code.startswith("gaussdb.bs.") or group_type in {
            "exclusive",
            "armExclusive",
        }
        is_ecology = any(
            marker in spec_code for marker in (".ecology.", "gaussdb.ec.", "gaussdb.opengauss.xe.")
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
            flavor_items.append({**_pick(item, _FLAVOR_FIELDS), "available_zones": available_zones})

    def number(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("inf")

    flavor_items.sort(key=lambda item: (number(item.get("vcpus")), number(item.get("ram"))))
    return flavor_items


def _mark_availability(
    deployment_options: list[dict[str, Any]],
    flavor_items: list[dict[str, Any]],
    storage_types: list[dict[str, Any]],
    ha_mode: str,
) -> None:
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


def _network_options(
    vpcs: dict[str, Any], subnets: dict[str, Any], security_groups: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
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
    return {"vpcs": vpc_items, "subnets": subnet_items, "security_groups": group_items}


def _select_network(network: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    vpc = network["vpcs"][0]
    subnet = next(
        (item for item in network["subnets"] if item.get("vpc_id") == vpc.get("id")),
        network["subnets"][0],
    )
    group = next(
        (item for item in network["security_groups"] if item.get("name") == "Sys-default"),
        network["security_groups"][0],
    )
    return {"vpc": vpc, "subnet": subnet, "group": group}


def _product_options() -> list[dict[str, Any]]:
    return [
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
    ]


def _field_options(
    storage_types: list[dict[str, Any]],
    flavor_items: list[dict[str, Any]],
    selected_deployment: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
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
            "single_value_reason": ("The public create API supports synchronous replication only."),
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
                {zone for flavor in flavor_items for zone in flavor.get("available_zones") or []}
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
                f"UTC{offset:+03d}:00" if offset else "UTC+00:00" for offset in range(-12, 13)
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
    }


def _parameter_groups() -> dict[str, Any]:
    return {
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
    }


def _discovery_result(
    selection: _Selection,
    catalog: _Catalog,
    flavor_items: list[dict[str, Any]],
    storage_types: list[dict[str, Any]],
    deployment_options: list[dict[str, Any]],
    recommended: dict[str, Any] | None,
    limit: int,
    region: str,
) -> dict[str, Any]:
    page_size = clamp_limit(limit)
    selected_deployment = next(
        (item for item in deployment_options if item["value"] == selection.deployment_mode), None
    )
    return single_result(
        {
            "project": {
                "project_id": catalog.context.project_id,
                "domain_id": catalog.context.domain_id,
                "region": region,
            },
            "engine_versions": catalog.engine_versions,
            "flavors": flavor_items[:page_size],
            "available_flavor_count": len(flavor_items),
            "flavors_truncated": len(flavor_items) > page_size,
            "storage_types": storage_types,
            "vpcs": catalog.network["vpcs"],
            "subnets": catalog.network["subnets"],
            "security_groups": catalog.network["security_groups"],
            "recommended_configuration": recommended,
            "recommended_configuration_status": (
                "catalog_candidate_cloud_final_validation_required"
                if recommended is not None and selection.ha_mode == "enterprise"
                else "deployment_form_and_catalog_validated"
                if recommended is not None
                else "unavailable"
            ),
            "deployment_options": deployment_options,
            "product_type_options": _product_options(),
            "create_field_options": _field_options(
                storage_types, flavor_items, selected_deployment
            ),
            "create_parameter_groups": _parameter_groups(),
            "selection": {
                "ha_mode": selection.ha_mode,
                "deployment_mode": selection.deployment_mode,
                "product_type": selection.product_type,
                "flavor_query_ha_mode": selection.flavor_ha_mode,
                "storage_query_ha_mode": selection.storage_ha_mode,
            },
        },
        [
            "Supply a new strong database password and review storage, network, placement, "
            "backup, and billing settings before creation.",
            (
                "Single-replica instances have no HA or SLA and are intended only for "
                "development and functional testing."
                if selection.deployment_mode == "single"
                else "The public v3.2 create request has no deployment-solution field, so "
                "logger is discoverable but is not passed to create_instance as triset."
                if selection.deployment_mode == "logger"
                else "availability_zone contains one comma-separated entry per replica; "
                "entries may repeat for same-AZ placement."
            ),
            (
                "For distributed creation, live flavor and storage results are catalog "
                "candidates, not proof that the current region, tenant, engine version, and "
                "product edition are bound for creation. Huawei Cloud performs the final "
                "compatibility check when create_instance runs."
                if selection.ha_mode == "enterprise"
                else "Centralized deployment forms were validated through the live deployment "
                "form API."
            ),
        ],
    )


class CreateOptionsService:
    def __init__(
        self,
        client: GaussDBClient,
        settings: McpSettings,
        network_client: VpcResourceClient | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._network_client = network_client

    async def discover_create_options(
        self,
        *,
        ha_mode: str,
        deployment_mode: str | None,
        product_type: str,
        version: str | None,
        limit: int,
    ) -> dict[str, Any]:
        deployment_mode = _select_deployment(ha_mode, deployment_mode, product_type)
        limit = clamp_limit(limit)
        selection = _Selection(ha_mode, deployment_mode, product_type, version)
        catalog = await self._load_catalog(selection)
        deployment_options, storage_types = await self._load_deployments(selection, catalog.version)
        flavor_items = _available_flavors(catalog.flavors, product_type)
        _mark_availability(deployment_options, flavor_items, storage_types, ha_mode)
        recommended = self._recommend_configuration(
            selection, catalog, flavor_items, storage_types, deployment_options
        )
        return _discovery_result(
            selection,
            catalog,
            flavor_items,
            storage_types,
            deployment_options,
            recommended,
            limit,
            self._settings.region,
        )

    async def _load_catalog(self, selection: _Selection) -> _Catalog:
        network = self._network_client or VpcResourceClient(self._settings)
        context, datastores, flavors, vpcs, subnets, security_groups = await asyncio.gather(
            run_sdk_call(lambda: resolve_project_context(self._settings), read_only=True),
            self._client.list_datastores(),
            self._client.list_flavors_details(
                # Fetch the full API page for availability decisions. The caller's limit only
                # controls how many choices are returned, not whether an edition looks sellable.
                version=selection.version,
                ha_mode=selection.flavor_ha_mode,
                limit=100,
                offset=0,
            ),
            network.list_vpcs(limit=100),
            network.list_subnets(limit=100),
            network.list_security_groups(limit=100),
        )
        engine_versions = datastores.get("versions") or []
        selected_version = selection.version or (engine_versions[0] if engine_versions else None)
        all_flavors = await self._list_all_flavors(flavors, selection)
        return _Catalog(
            context,
            engine_versions,
            selected_version,
            all_flavors,
            _network_options(vpcs, subnets, security_groups),
        )

    async def _list_all_flavors(
        self, initial: dict[str, Any], selection: _Selection
    ) -> list[dict[str, Any]]:
        all_flavors = list(initial.get("flavors") or [])
        flavor_total = int(initial.get("total") or len(all_flavors))
        if flavor_total > len(all_flavors):
            remaining_pages = await asyncio.gather(
                *(
                    self._client.list_flavors_details(
                        version=selection.version,
                        ha_mode=selection.flavor_ha_mode,
                        limit=100,
                        offset=offset,
                    )
                    for offset in range(100, flavor_total, 100)
                )
            )
            for page in remaining_pages:
                all_flavors.extend(page.get("flavors") or [])

        return all_flavors

    async def _load_deployments(
        self, selection: _Selection, selected_version: str | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        deployment_options: list[dict[str, Any]] = []
        storage_types: list[dict[str, Any]] = []
        if selected_version:
            if selection.ha_mode == "centralization_standard":
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
                if selection.product_type == "basic":
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
                    ha_mode=selection.storage_ha_mode,
                ),
                return_exceptions=True,
            )
            if not isinstance(storage_result[0], BaseException):
                storage_types = [
                    _pick(item, ("name", "az_status", "support_compute_group_type"))
                    for item in storage_result[0].get("storage_type") or []
                ]

        return deployment_options, storage_types

    def _recommend_configuration(
        self,
        selection: _Selection,
        catalog: _Catalog,
        flavor_items: list[dict[str, Any]],
        storage_types: list[dict[str, Any]],
        deployment_options: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        recommended: dict[str, Any] | None = None
        selected_deployment = next(
            (item for item in deployment_options if item["value"] == selection.deployment_mode),
            None,
        )
        if not all(
            (
                flavor_items,
                catalog.network["vpcs"],
                catalog.network["subnets"],
                catalog.network["security_groups"],
                storage_types,
            )
        ):
            return None
        if not selected_deployment or not selected_deployment["direct_create_supported"]:
            return None
        flavor = flavor_items[0]
        chosen_network = _select_network(catalog.network)
        zone = flavor["available_zones"][0]
        replica_num = int(selected_deployment.get("replica_num") or 3)
        shard_num = 3 if selection.ha_mode == "enterprise" else 1
        recommended = {
            "datastore": {
                "type": "GaussDB",
                "version": catalog.version,
            },
            "ha": {
                "mode": selection.ha_mode,
                "consistency": "strong",
                "replication_mode": "sync",
                "instance_mode": selection.product_type,
            },
            "deployment_solution": selection.deployment_mode,
            "flavor_ref": flavor.get("spec_code"),
            "volume": {
                "type": storage_types[0].get("name"),
                "size": shard_num * 40,
            },
            "availability_zone": ",".join([zone] * replica_num),
            "replica_num": replica_num,
            "vpc_id": chosen_network["vpc"].get("id"),
            "subnet_id": chosen_network["subnet"].get("neutron_network_id")
            or chosen_network["subnet"].get("id"),
            "security_group_id": chosen_network["group"].get("id"),
            "region": self._settings.region,
            "port": 8000,
            "time_zone": "UTC+08:00",
            "backup_strategy": {"start_time": "02:00-03:00", "keep_days": 7},
            "charge_info": {"charge_mode": "postPaid"},
        }
        if selection.ha_mode == "enterprise":
            recommended.update({"sharding_num": shard_num, "coordinator_num": 3})
        return recommended
