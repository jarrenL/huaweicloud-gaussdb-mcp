"""Console entry point tests."""

from mcp_server_gaussdb import main as main_module
from mcp_server_gaussdb.server import mcp


def test_main_runs_standard_server(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = []

    def record(server, *, service_name: str) -> None:  # type: ignore[no-untyped-def]
        calls.append((server, service_name))

    monkeypatch.setattr(main_module, "run_standard", record)
    main_module.main()
    assert calls == [(mcp, "gaussdb")]
