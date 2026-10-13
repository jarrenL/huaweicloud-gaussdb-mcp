"""GaussDB MCP server and tool registration."""

from huaweicloud_mcp_core import build_server

from . import __version__

mcp = build_server("gaussdb", version=__version__)

from .tools import backup, instance, observability, openapi  # noqa: E402,F401
