"""Preserve GaussDB's safety checks with the published shared core."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from huaweicloud_mcp_core.errors import McpToolError
from huaweicloud_mcp_core.guardrails.rules import ResourceSpec, Rule
from mcp.types import CallToolResult

from mcp_huaweicloud_gaussdb.compat.guardrails import middleware as middleware_module
from mcp_huaweicloud_gaussdb.compat.guardrails.audit import AuditLogger
from mcp_huaweicloud_gaussdb.compat.guardrails.masking import MaskingEngine
from mcp_huaweicloud_gaussdb.compat.guardrails.middleware import GuardrailsMiddleware
from mcp_huaweicloud_gaussdb.compat.guardrails.protect import assert_not_protected


def _context(name: str, **arguments: Any) -> Any:
    return SimpleNamespace(
        method="tools/call", params=SimpleNamespace(name=name, arguments=arguments)
    )


async def _ok(_: Any) -> dict[str, bool]:
    return {"ok": True}


async def test_masks_thrown_and_returned_errors_and_tracks_outcome() -> None:
    audit = AuditLogger()
    middleware = GuardrailsMiddleware(audit=audit)
    context = _context("get_instance", instance_id="test")
    error = McpToolError("MCP_TEST", "Bearer example-secret", request_id="request-1")

    async def throw(_: Any) -> Any:
        raise error

    async def return_envelope(_: Any) -> Any:
        return {
            "content": [{"type": "text", "text": json.dumps(error.to_dict())}],
            "structuredContent": error.to_dict(),
            "isError": False,
        }

    for callback in (throw, return_envelope):
        result = await middleware(context, callback)
        assert isinstance(result, CallToolResult) and result.is_error
        assert "example-secret" not in str(result)
        record = audit.events[-1]
        assert record["outcome"] == "failed" and record["error_code"] == "MCP_TEST"
        assert record["request_id"] == "request-1"


async def test_capacity_is_released_for_next_call() -> None:
    middleware = GuardrailsMiddleware(max_concurrent=1)
    context = _context("get_instance", instance_id="test")
    entered, release = asyncio.Event(), asyncio.Event()

    async def block(_: Any) -> dict[str, bool]:
        entered.set()
        await release.wait()
        return {"ok": True}

    task = asyncio.create_task(middleware(context, block))
    await entered.wait()
    try:
        result = await middleware(context, _ok)
        assert result.is_error
        assert result.structured_content["error"]["code"] == "MCP_BUSY"
    finally:
        release.set()
        await task
    assert await middleware(context, _ok) == {"ok": True}


async def test_guardrail_failure_allows_reads_and_blocks_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_: Any) -> Any:
        raise RuntimeError("Bearer example-secret")

    monkeypatch.setattr(middleware_module, "evaluate_rules", fail)
    middleware = GuardrailsMiddleware()
    assert await middleware(_context("get_instance"), _ok) == {"ok": True}
    result = await middleware(_context("restart_instance"), _ok)
    assert result.is_error and "example-secret" not in str(result)
    assert result.structured_content["error"]["code"] == "MCP_GUARDRAIL_ERROR"


async def test_matches_gaussdb_resource_tags_before_dispatch() -> None:
    rules = [
        Rule(
            id="protected-db",
            action="block",
            message="Protected database",
            resources=ResourceSpec(tags=("environment=production",)),
        )
    ]
    middleware = GuardrailsMiddleware(rules=rules)
    production = [{"key": "environment", "value": "production"}]
    sandbox = [{"key": "environment", "value": "sandbox"}]
    result = await middleware(_context("create_instance", request={"tags": production}), _ok)
    assert result.is_error
    assert result.structured_content["error"]["code"] == "MCP_GUARDRAIL_BLOCKED"
    assert await middleware(_context("create_instance", tags=sandbox), _ok) == {"ok": True}
    with pytest.raises(McpToolError, match="Protected database"):
        assert_not_protected({"id": "db", "tags": production}, rules)
    assert_not_protected({"id": "db", "tags": sandbox}, rules)


async def test_masks_warning_text_before_returning_it() -> None:
    middleware = GuardrailsMiddleware(
        rules=[Rule(id="check-db", action="warn", message="Bearer example-secret")]
    )
    result = await middleware(_context("get_instance"), _ok)
    assert result["warnings"] == [{"rule_id": "check-db", "message": "***"}]


def test_audit_history_rotation_permissions_and_masking(tmp_path: Path) -> None:
    target = tmp_path / "audit.jsonl"
    audit = AuditLogger(str(target), history_limit=2, max_bytes=160, backup_count=2)
    for index in range(8):
        audit.emit(
            tool=f"t{index}", params={"sk": "s" * 40 + "tail"}, detail="Bearer private-token"
        )
    assert len(audit.events) == 2
    assert len(list(tmp_path.glob("audit.jsonl*"))) == 3
    assert audit.events[-1]["detail"] == "***"
    for file in tmp_path.iterdir():
        output = file.read_text()
        assert "private-token" not in output and ("s" * 40 + "tail") not in output
        if os.name != "nt":
            assert file.stat().st_mode & 0o077 == 0
    if os.name != "nt":
        target.chmod(0o644)
        audit.emit(tool="denied")
        assert audit.file_errors == 1


def test_audit_rejects_symlinks_and_large_records_are_bounded(tmp_path: Path) -> None:
    if os.name != "nt":
        target = tmp_path / "target"
        target.write_text("unchanged")
        link = tmp_path / "audit"
        link.symlink_to(target)
        audit = AuditLogger(str(link))
        audit.emit(tool="test")
        assert target.read_text() == "unchanged" and audit.file_errors == 1

    audit = AuditLogger()
    audit.emit(tool="large", params={str(i): ["x" * 200] * 100 for i in range(100)})
    record = audit.events[-1]
    assert len(json.dumps(record).encode()) < 16 * 1024
    assert record["params"]["_truncated"] is True


def test_masking_covers_gaussdb_credentials_and_is_idempotent() -> None:
    engine = MaskingEngine()
    access_key = "A" * 20
    masked = engine.mask({"password": "value", "ak": "example", "sk": "example", "msg": access_key})
    assert "example" not in str(masked) and access_key not in str(masked)
    assert engine.mask(masked) == masked
