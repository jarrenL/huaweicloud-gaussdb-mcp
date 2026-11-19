"""Console entry point tests."""

import sys
from typing import Any

import pytest
from starlette.applications import Starlette

from mcp_huaweicloud_gaussdb import main as main_module
from mcp_huaweicloud_gaussdb.server import mcp


def test_main_runs_standard_server(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = []

    def record(server, *, service_name: str) -> None:  # type: ignore[no-untyped-def]
        calls.append((server, service_name))

    monkeypatch.setattr(main_module, "run_standard", record)
    main_module.main()
    assert calls == [(mcp, "gaussdb")]


def test_default_transport_is_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sys, "argv", ["mcp_huaweicloud_gaussdb"])
    monkeypatch.setattr(mcp, "run", lambda **kwargs: calls.append(kwargs))

    main_module.main()

    assert calls == [{"transport": "stdio"}]


def test_http_transport_starts_secure_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Starlette, dict[str, Any]]] = []
    monkeypatch.setattr(sys, "argv", ["mcp_huaweicloud_gaussdb", "-t", "streamable-http"])
    monkeypatch.setenv("MCP_SERVER_PORT", "8088")
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append((app, kwargs)))

    main_module.main()

    app, options = calls.pop()
    assert isinstance(app, Starlette)
    assert options == {"host": "127.0.0.1", "port": 8088, "proxy_headers": False}
