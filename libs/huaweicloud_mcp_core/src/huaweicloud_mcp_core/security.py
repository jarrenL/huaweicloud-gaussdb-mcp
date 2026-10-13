"""Static risk declarations used by the global guardrail middleware."""

import functools
import inspect
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, ParamSpec, TypeVar

from .errors import McpToolError


class ToolRisk(Enum):
    READ = "READ"
    WRITE = "WRITE"
    DANGEROUS = "DANGEROUS"


P = ParamSpec("P")
R = TypeVar("R")
_TOOL_RISK_REGISTRY: dict[str, ToolRisk] = {}
_TOOLS_WITH_CONFIRM: set[str] = set()


def guard(*, risk: ToolRisk) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[Any]]]:
    def decorate(function: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[Any]]:
        _TOOL_RISK_REGISTRY[function.__name__] = risk
        if "confirm" in inspect.signature(function).parameters:
            _TOOLS_WITH_CONFIRM.add(function.__name__)

        @functools.wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> Any:
            try:
                return await function(*args, **kwargs)
            except McpToolError as exc:
                return exc.to_dict()

        return wrapped

    return decorate


def get_tool_risk(tool_name: str) -> ToolRisk | None:
    return _TOOL_RISK_REGISTRY.get(tool_name)


def tool_supports_confirm(tool_name: str) -> bool:
    return tool_name in _TOOLS_WITH_CONFIRM


def reset_registries() -> None:
    _TOOL_RISK_REGISTRY.clear()
    _TOOLS_WITH_CONFIRM.clear()
