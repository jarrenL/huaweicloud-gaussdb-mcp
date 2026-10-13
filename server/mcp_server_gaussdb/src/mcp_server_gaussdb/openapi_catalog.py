"""Discover and describe the public operations shipped by the Huawei Cloud GaussDB SDK."""

import ast
import inspect
import re
import textwrap
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from huaweicloud_mcp_core import ToolRisk

_READ_PREFIXES = ("get_", "list_", "show_", "search_", "validate_", "export_", "download_")
_DANGEROUS_PREFIXES = ("delete_", "shrink_", "stop_")
_DANGEROUS_OPERATIONS = {
    "attach_eip",
    "batch_delete_instance_tag",
    "bind_d_nat",
    "cancel_schedule_task",
    "change_demand2_period",
    "change_deployment_solution",
    "confirm_restored_data",
    "create_restore_instance",
    "execute_cross_cloud_disaster_end_simulation",
    "execute_cross_cloud_disaster_recovery_failover",
    "execute_cross_cloud_disaster_restore",
    "execute_cross_cloud_disaster_switchover",
    "execute_cross_cloud_release_disaster",
    "modify_instance_port",
    "modify_security_group",
    "reset_configuration",
    "reset_dr_config",
    "restore_instance",
    "restore_node_roles",
    "switch_logger_replica",
    "switch_logger_replica_availability_zones",
    "switch_configuration",
    "switch_kms_tde",
    "switch_replica",
    "switch_shard",
    "unbind_lts_config",
    "upgrade_instance_version",
    "upgrade_instances_version",
    "update_instance_versions",
}
_READ_OPERATIONS = {"batch_show_upgrade_candidate_versions"}


@dataclass(frozen=True)
class OpenApiOperation:
    name: str
    request_model: str
    title: str
    description: str
    category: str
    risk: ToolRisk

    def summary(self) -> dict[str, str]:
        return {
            "operation": self.name,
            "request_model": self.request_model,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "risk": self.risk.value,
        }


def request_model_name(operation: str) -> str:
    return "".join(part.capitalize() for part in operation.split("_")) + "Request"


def classify_risk(operation: str) -> ToolRisk:
    if operation in _READ_OPERATIONS:
        return ToolRisk.READ
    if operation in _DANGEROUS_OPERATIONS or operation.startswith(_DANGEROUS_PREFIXES):
        return ToolRisk.DANGEROUS
    if operation.startswith(_READ_PREFIXES):
        return ToolRisk.READ
    return ToolRisk.WRITE


def classify_category(operation: str) -> str:
    checks = (
        ("disaster_recovery", ("disaster", "_dr_")),
        ("backup_restore", ("backup", "restore")),
        ("database_identity", ("database", "db_user", "db_role", "schema", "privilege")),
        ("sql_diagnostics", ("sql", "session", "transaction", "wait_event", "wdr", "asp")),
        ("parameters", ("configuration", "parameter", "hba")),
        ("network_security", ("eip", "nat", "security_group", "ssl", "kms", "tde")),
        ("tags", ("tag",)),
        ("quota_billing", ("quota", "demand2_period")),
        ("tasks_events", ("job", "task", "event")),
        ("recycle", ("recycle",)),
        ("observability", ("metric", "alarm", "error_log", "lts", "volume")),
        ("plugins", ("plugin",)),
        (
            "instance_lifecycle",
            (
                "instance",
                "flavor",
                "datastore",
                "deployment",
                "shard",
                "readonly",
                "replica",
                "expansion",
                "redistribution",
            ),
        ),
    )
    for category, tokens in checks:
        if any(token in operation for token in tokens):
            return category
    return "other"


def _doc_parts(function: Any) -> tuple[str, str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", inspect.getdoc(function) or "")]
    paragraphs = [
        part for part in paragraphs if part and not part.startswith((":param", ":type", ":rtype"))
    ]
    title = paragraphs[0] if paragraphs else function.__name__
    description = paragraphs[1] if len(paragraphs) > 1 else title
    if "Please refer" in description:
        description = title
    return title[:200], description[:1000]


@lru_cache(maxsize=1)
def operations() -> dict[str, OpenApiOperation]:
    import huaweicloudsdkgaussdbforopengauss.v3 as sdk

    client = sdk.GaussDBforopenGaussClient
    found: dict[str, OpenApiOperation] = {}
    for name in dir(client):
        if name.startswith("_") or name.endswith(("_async", "_invoker")):
            continue
        function = getattr(client, name)
        if not callable(function):
            continue
        try:
            parameters = list(inspect.signature(function).parameters)
        except (TypeError, ValueError):
            continue
        model_name = request_model_name(name)
        if parameters[:2] != ["self", "request"] or not hasattr(sdk, model_name):
            continue
        title, description = _doc_parts(function)
        found[name] = OpenApiOperation(
            name=name,
            request_model=model_name,
            title=title,
            description=description,
            category=classify_category(name),
            risk=classify_risk(name),
        )
    return found


def get_operation(name: str) -> OpenApiOperation | None:
    return operations().get(name)


def _type_schema(type_name: str, seen: set[str], depth: int) -> dict[str, Any]:
    primitive: dict[str, dict[str, Any]] = {
        "str": {"type": "string"},
        "int": {"type": "integer"},
        "float": {"type": "number"},
        "bool": {"type": "boolean"},
        "date": {"type": "string", "format": "date"},
        "datetime": {"type": "string", "format": "date-time"},
        "object": {},
    }
    if type_name in primitive:
        return primitive[type_name]
    if type_name.startswith("list["):
        return {"type": "array", "items": _type_schema(type_name[5:-1], seen, depth + 1)}
    if type_name.startswith("dict("):
        parts = type_name[5:-1].split(",", 1)
        value_type = parts[1].strip() if len(parts) == 2 else "object"
        return {"type": "object", "additionalProperties": _type_schema(value_type, seen, depth + 1)}
    if depth >= 8 or type_name in seen:
        return {"type": "object", "x-sdk-model": type_name}
    import huaweicloudsdkgaussdbforopengauss.v3 as sdk

    model = getattr(sdk, type_name, None)
    if model is None or not hasattr(model, "openapi_types"):
        return {"type": "object", "x-sdk-model": type_name}
    next_seen = {*seen, type_name}
    init_doc = inspect.getdoc(model.__init__) or ""

    def description(attr: str) -> str | None:
        match = re.search(
            rf":param {re.escape(attr)}:\s*(.*?)(?=\n\s*:type|\n\s*:param|\Z)", init_doc, re.S
        )
        if not match:
            return None
        return " ".join(match.group(1).split())[:1000]

    properties = {
        attr: {
            **_type_schema(field_type, next_seen, depth + 1),
            "x-wire-name": model.attribute_map.get(attr, attr),
            **(
                {"description": field_description}
                if (field_description := description(attr))
                else {}
            ),
        }
        for attr, field_type in model.openapi_types.items()
    }
    required: list[str] = []
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(model.__init__)))
        function = tree.body[0]
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for statement in function.body:
                if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                    continue
                target, value = statement.targets[0], statement.value
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr in model.openapi_types
                    and isinstance(value, ast.Name)
                    and value.id == target.attr
                ):
                    required.append(target.attr)
    except (OSError, TypeError, SyntaxError):
        pass
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "x-sdk-model": type_name,
    }
    if required:
        schema["required"] = required
    return schema


def operation_schema(operation: OpenApiOperation) -> dict[str, Any]:
    schema = _type_schema(operation.request_model, set(), 0)
    # Huawei Cloud's generated request constructors leave JSON bodies optional so
    # callers can instantiate a model incrementally.  The corresponding HTTP APIs
    # require the body whenever the request model exposes one, so surface that
    # requirement to MCP clients instead of letting an omitted body fail remotely.
    if "body" in schema.get("properties", {}):
        required = schema.setdefault("required", [])
        if "body" not in required:
            required.append("body")
    return schema
