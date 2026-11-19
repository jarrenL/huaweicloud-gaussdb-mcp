"""Validate live parameter metadata and plan changes without issuing a write."""

import difflib
import re
from typing import Any

from huaweicloud_mcp_core import McpToolError

from .create_common import _pick

_HIGH_RISK_PARAMETER_RE = re.compile(
    r"^(?:audit_|ssl(?:_|$)|password_encryption$|fsync$|full_page_writes$|"
    r"synchronous_commit$|wal_|archive_|max_connections$|shared_buffers$|work_mem$|"
    r"maintenance_work_mem$|temp_buffers$|enable_thread_pool$|use_workload_manager$|"
    r"enable_slot_log$|most_available_sync$|replconninfo)",
    re.IGNORECASE,
)


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

    numeric_error = _numeric_parameter_error(parameter_type, value, value_range)
    if numeric_error:
        return numeric_error

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


def _numeric_parameter_error(parameter_type: str, value: str, value_range: str) -> str | None:
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

    return None


def _validate_parameter_metadata(
    parameter_map: dict[str, dict[str, Any]], values: dict[str, str], current: dict[str, Any]
) -> None:
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


def _plan_parameter_changes(
    parameter_map: dict[str, dict[str, Any]], values: dict[str, str]
) -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
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
    return effective_values, changes, high_risk_parameters


def parameter_detail(item: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "name",
        "value",
        "restart_required",
        "readonly",
        "value_range",
        "type",
        "description",
    )
    risk_reasons = _parameter_risk_reasons(item)
    return {
        **_pick(item, fields),
        "readonly": item.get("readonly"),
        "modifiability": _parameter_modifiability(item),
        "risk_level": "high" if risk_reasons else "normal",
        "risk_reasons": risk_reasons,
    }
