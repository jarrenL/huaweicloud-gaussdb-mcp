"""Complete, catalog-driven access to Huawei Cloud GaussDB public OpenAPI operations."""

from typing import Any, Literal

from huaweicloud_mcp_core import ToolRisk, guard

from ..server import mcp
from ..service.openapi_service import OpenApiService


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def list_openapi_operations(
    query: str | None = None,
    category: str | None = None,
    risk: Literal["READ", "WRITE", "DANGEROUS"] | None = None,
    limit: int = 20,
    marker: str | None = None,
) -> dict[str, Any]:
    """List public GaussDB OpenAPI operations available through the installed Huawei SDK.

    Scenario: discover an API capability that does not have a dedicated scenario tool.

    Args:
        query: Optional snake_case operation-name or Chinese/English description substring.
        category: Optional category returned by this tool, such as backup_restore.
        risk: Optional READ, WRITE, or DANGEROUS filter.
        limit: Page size, clamped to 1-100.
        marker: Offset marker from the previous response.

    Returns:
        Paginated snake_case operation names, request models, descriptions, categories, risk
        levels, exact invocation argument names, and dedicated-tool restrictions.
    """
    return await OpenApiService().list_operations(
        query=query, category=category, risk=risk, limit=limit, marker=marker
    )


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def describe_openapi_operation(operation: str) -> dict[str, Any]:
    """Describe the exact nested request structure for one public GaussDB OpenAPI operation.

    Scenario: inspect field names and types before using a generic OpenAPI invocation tool.

    Args:
        operation: Exact snake_case SDK operation value returned by list_openapi_operations.

    Returns:
        Operation metadata and a recursive JSON-schema-like SDK request model.
    """
    return await OpenApiService().describe_operation(operation=operation)


@mcp.tool()
@guard(risk=ToolRisk.READ)
async def invoke_read_openapi(operation: str, request: dict[str, Any]) -> dict[str, Any]:
    """Invoke a catalog-classified READ GaussDB OpenAPI operation.

    Scenario: query any supported public GaussDB API after describing its request model.

    Args:
        operation: Exact snake_case READ operation value returned by list_openapi_operations.
        request: Object containing the fields described by describe_openapi_operation. The exact
            MCP argument object is {"operation": "...", "request": {...}}.

    Returns:
        The operation name, risk classification, and recursively converted SDK response.
    """
    return await OpenApiService().invoke(
        operation=operation, request=request, required_risk=ToolRisk.READ
    )


@mcp.tool()
@guard(risk=ToolRisk.WRITE)
async def invoke_write_openapi(
    operation: str, request: dict[str, Any], confirm: bool = False
) -> dict[str, Any]:
    """Invoke a catalog-classified WRITE GaussDB OpenAPI operation.

    Scenario: execute a reversible or additive operation without a dedicated scenario tool.

    Args:
        operation: Exact snake_case WRITE operation value returned by list_openapi_operations.
        request: Object containing the fields described by describe_openapi_operation. The exact
            MCP argument object is {"operation": "...", "request": {...}}. Operations marked
            direct_invoke_supported=false must use their dedicated safer tool.
        confirm: Set true when a configured guardrail rule requests confirmation.

    Returns:
        The operation name, risk classification, and recursively converted SDK response.
    """
    return await OpenApiService().invoke(
        operation=operation, request=request, required_risk=ToolRisk.WRITE
    )


@mcp.tool()
@guard(risk=ToolRisk.DANGEROUS)
async def invoke_dangerous_openapi(
    operation: str, request: dict[str, Any], confirm: bool = False
) -> dict[str, Any]:
    """Invoke a destructive, disruptive, or billing-sensitive GaussDB OpenAPI operation.

    Scenario: run a reviewed dangerous operation when no dedicated scenario tool exists.
    The global guardrail always requires confirm=true and applies protected-resource rules.

    Args:
        operation: Exact snake_case DANGEROUS operation value from list_openapi_operations.
        request: Object containing the fields described by describe_openapi_operation. The exact
            MCP argument object is {"operation": "...", "request": {...}}.
        confirm: Must be true after reviewing resource identity and impact.

    Returns:
        The operation name, risk classification, and recursively converted SDK response.
    """
    return await OpenApiService().invoke(
        operation=operation, request=request, required_risk=ToolRisk.DANGEROUS
    )
