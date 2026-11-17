"""Register GaussDB tools after constructing the shared server instance."""

from importlib import import_module

from .application import mcp

__all__ = ["mcp"]

for _module in ("backup", "billing", "instance", "monitoring", "observability", "openapi"):
    import_module(f"{__package__}.tools.{_module}")
