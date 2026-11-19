"""Shared creation metadata and response field selection."""

from typing import Any

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


def _pick(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in fields if source.get(key) is not None}
