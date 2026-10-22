"""GaussDB instance lifecycle tools."""

from typing import Any, Literal

from huaweicloud_mcp_core import ToolRisk, guard

from ..server import mcp
from ..service.gaussdb_service import GaussDBService


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def list_instances(
    name: str | None = None, limit: int = 20, marker: str | None = None
) -> dict[str, Any]:
    """List GaussDB instances in the configured region.

    Scenario: discover instances before inspecting, backing up, resizing, expanding, or
    restarting one.

    Args:
        name: Optional exact instance-name filter.
        limit: Page size, clamped to 1-100; default 20.
        marker: Offset marker returned by the previous call.

    Returns:
        A paginated, field-whitelisted instance list.
    """
    return await GaussDBService().list_instances(name=name, limit=limit, marker=marker)


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def get_instance(instance_id: str) -> dict[str, Any]:
    """Get one GaussDB instance and its management-relevant details.

    Scenario: inspect status, topology, network, storage, flavor and tags before a change.

    Args:
        instance_id: GaussDB instance ID obtained from list_instances.

    Returns:
        The field-whitelisted instance object, node summaries and node_ids for analyze_slow_sql,
        or an MCP_NOT_FOUND envelope.
    """
    return await GaussDBService().get_instance(instance_id=instance_id)


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def list_flavors(
    version: str | None = None,
    ha_mode: Literal["centralization_standard", "enterprise", "combined"] | None = None,
    limit: int = 20,
    marker: str | None = None,
) -> dict[str, Any]:
    """List available GaussDB specifications before creation or resize.

    Scenario: find a valid spec_code and check availability-zone sales status.

    Args:
        version: Optional database engine version filter.
        ha_mode: enterprise (distributed independent), combined (distributed basic mixed), or
            centralization_standard. discover_create_options derives combined automatically for
            distributed basic instances.
        limit: Page size, clamped to 1-100; default 20.
        marker: Offset marker returned by the previous call.

    Returns:
        A paginated list of vCPU, RAM, spec codes and AZ availability.
    """
    return await GaussDBService().list_flavors(
        version=version, ha_mode=ha_mode, limit=limit, marker=marker
    )


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def discover_create_options(
    ha_mode: Literal["centralization_standard", "enterprise"] = "centralization_standard",
    deployment_mode: Literal["single", "triset", "logger", "combined", "hws"] | None = None,
    product_type: Literal["basic", "enterprise", "ecology"] = "basic",
    version: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Discover every cloud-side prerequisite for creating a GaussDB instance.

    Scenario: prepare a valid create_instance call without asking the user to manually find
    project, domain, engine, flavor, availability-zone, VPC, subnet, or security-group IDs.

    Args:
        ha_mode: centralization_standard for centralized creation, or enterprise for distributed
            creation. For product_type=basic, distributed availability is queried from the
            combined flavor family automatically.
        deployment_mode: For centralized instances, single, triset (1 primary + 2 standby),
            or logger (1 primary + 1 standby + 1 logger). Distributed basic uses combined;
            distributed enterprise/ecology uses hws. When omitted, the service derives the
            correct default from ha_mode and product_type.
        product_type: basic, enterprise, or ecology. Product/deployment compatibility and a
            matching live flavor are both checked.
        version: Optional engine-version filter.
        limit: Maximum available flavors to return, clamped to 1-100.

    Returns:
        Project context, live deployment and storage options, all public create-field choices and
        constraints, engine versions, sellable flavor candidates and AZs, network resources, and
        a recommended configuration without a password. For distributed instances, catalog
        visibility still requires the cloud's final region/tenant/engine/product binding check.
        Defaults to basic + single replica.
    """
    return await GaussDBService().discover_create_options(
        ha_mode=ha_mode,
        deployment_mode=deployment_mode,
        product_type=product_type,
        version=version,
        limit=limit,
    )


@mcp.tool()
@guard(risk=ToolRisk.WRITE)
async def create_instance(configuration: dict[str, Any], confirm: bool = False) -> dict[str, Any]:
    """Create a Huawei Cloud GaussDB instance.

    Scenario: provision one instance after selecting a flavor and preparing VPC resources. Creation
    can incur charges and runs asynchronously.

    Args:
        configuration: Creation settings. Required keys are name, datastore, ha, password,
            flavor_ref, volume, availability_zone, vpc_id, subnet_id and security_group_id.
            Optional keys follow CreateDatabaseInstanceRequestBody, including backup_strategy,
            charge_info, replica_num, sharding_num, coordinator_num and enterprise_project_id.
            deployment_solution may be single or triset and is validated locally, then removed
            before calling the cloud API. logger is rejected because the public v3.2 request has
            no solution selector and must never be silently converted to triset.
        confirm: Set true when a guardrail rule requests explicit confirmation.

    Returns:
        The job, instance or order identifiers needed to track provisioning.
    """
    return await GaussDBService().create_instance(configuration=configuration)


@mcp.tool()
@guard(risk=ToolRisk.DANGEROUS)
async def delete_instance(instance_id: str, confirm: bool = False) -> dict[str, Any]:
    """Permanently delete a Huawei Cloud GaussDB instance.

    Scenario: remove a reviewed instance that is no longer needed and stop its ongoing charges.
    The operation is irreversible and always requires confirm=true. The service re-reads the
    cloud resource and applies protected-ID, name, and tag rules before deletion.

    Args:
        instance_id: Exact GaussDB instance ID obtained from list_instances or get_instance.
        confirm: Must be true after reviewing the instance identity and deletion impact.

    Returns:
        The deleted instance identity and asynchronous job or order identifier.
    """
    return await GaussDBService().delete_instance(instance_id=instance_id)


@mcp.tool()
@guard(risk=ToolRisk.WRITE)
async def resize_instance(
    instance_id: str,
    flavor_ref: str,
    is_auto_pay: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Change the vCPU and memory specification of a GaussDB instance.

    Scenario: resize an instance after list_flavors returns the target flavor_ref. This may affect
    connections and billing.

    Args:
        instance_id: Target GaussDB instance ID.
        flavor_ref: Target spec_code from list_flavors.
        is_auto_pay: Automatically pay a periodic-instance order; default false.
        confirm: Set true when a guardrail rule requests explicit confirmation.

    Returns:
        The asynchronous job or order identifier and tracking guidance.
    """
    return await GaussDBService().resize_instance(
        instance_id=instance_id, flavor_ref=flavor_ref, is_auto_pay=is_auto_pay
    )


@mcp.tool()
@guard(risk=ToolRisk.WRITE)
async def expand_instance(
    instance_id: str,
    new_volume_size_gb: int | None = None,
    coordinator_az_codes: list[str] | None = None,
    dn_shard_count: int | None = None,
    is_auto_pay: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Expand GaussDB storage, coordinator nodes, or DN shards.

    Scenario: increase one capacity dimension after checking instance status and GaussDB expansion
    constraints. Exactly one expansion input must be supplied.

    Args:
        instance_id: Target GaussDB instance ID.
        new_volume_size_gb: Target total storage size in GiB for storage expansion.
        coordinator_az_codes: One AZ code per new coordinator node for CN expansion.
        dn_shard_count: Number of new DN shards for shard expansion.
        is_auto_pay: Automatically pay a periodic-instance order; default false.
        confirm: Set true when a guardrail rule requests explicit confirmation.

    Returns:
        The asynchronous job or order identifier and tracking guidance.
    """
    return await GaussDBService().expand_instance(
        instance_id=instance_id,
        new_volume_size_gb=new_volume_size_gb,
        coordinator_az_codes=coordinator_az_codes,
        dn_shard_count=dn_shard_count,
        is_auto_pay=is_auto_pay,
    )


@mcp.tool()
@guard(risk=ToolRisk.WRITE)
async def restart_instance(instance_id: str, confirm: bool = False) -> dict[str, Any]:
    """Restart a GaussDB instance.

    Scenario: apply a restart-required parameter or recover an instance during an approved
    maintenance window. Existing connections may be interrupted.

    Args:
        instance_id: Target GaussDB instance ID; inspect it with get_instance first.
        confirm: Set true when a guardrail rule requests explicit confirmation.

    Returns:
        The target instance and asynchronous job identifier.
    """
    return await GaussDBService().restart_instance(instance_id=instance_id)


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def get_instance_parameters(
    instance_id: str,
    name: str | None = None,
    modifiable_only: bool = False,
    limit: int = 20,
    marker: str | None = None,
) -> dict[str, Any]:
    """List the current parameter configuration of a GaussDB instance.

    Scenario: inspect values, valid ranges, read-only status, and restart requirements
    before tuning.

    Args:
        instance_id: Target GaussDB instance ID.
        name: Optional case-insensitive parameter-name substring.
        modifiable_only: Return only parameters whose v3.2 live metadata has readonly=false.
        limit: Page size, clamped to 1-100; default 20.
        marker: Offset marker returned by the previous call.

    Returns:
        A paginated parameter list including readonly, explicit modifiability state,
        restart_required, value_range, risk level, metadata source/counts, and reasons for
        high-risk classification.
    """
    return await GaussDBService().get_instance_parameters(
        instance_id=instance_id,
        name=name,
        modifiable_only=modifiable_only,
        limit=limit,
        marker=marker,
    )


@mcp.tool()
@guard(risk=ToolRisk.WRITE)
async def update_instance_parameters(
    instance_id: str, values: dict[str, str], confirm: bool = False
) -> dict[str, Any]:
    """Update up to 100 GaussDB instance parameters.

    Scenario: apply reviewed parameter values. The tool always refreshes the live parameter
    metadata, rejects unknown and read-only names, validates clear type/range rules, and identifies
    restart or sensitive changes before writing.

    Args:
        instance_id: Target GaussDB instance ID.
        values: Mapping of parameter names to string values; 1-100 entries. The exact MCP argument
            object is {"instance_id": "...", "values": {"parameter_name": "new_value"}}.
        confirm: Required for parameters that need restart or are classified as sensitive for
            durability, security, replication, auditing, or resource exhaustion.

    Returns:
        Updated parameter names, job metadata, and verification guidance.
    """
    return await GaussDBService().update_instance_parameters(
        instance_id=instance_id, values=values, confirm=confirm
    )
