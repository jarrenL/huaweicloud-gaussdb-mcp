"""Fault-injection tests for identity, response handling and bounded audit logs."""

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.types import CallToolResult

from huaweicloud_mcp_core import McpSettings, McpToolError, ToolRisk, guard
from huaweicloud_mcp_core.guardrails.audit import AuditLogger
from huaweicloud_mcp_core.guardrails.masking import MaskingEngine
from huaweicloud_mcp_core.guardrails.middleware import GuardrailsMiddleware


def test_env_identity_does_not_inherit_old_file_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "credentials.json"
    file.write_text(
        json.dumps(
            {"access_key": "old", "secret_key": "old", "security_token": "old-sts", "region": "r"}
        )
    )
    file.chmod(0o600)
    monkeypatch.setenv("HUAWEICLOUD_MCP_CREDENTIALS_FILE", str(file))
    monkeypatch.setenv("HUAWEICLOUD_ACCESS_KEY", "new-a")
    monkeypatch.setenv("HUAWEICLOUD_SECRET_KEY", "new-s")
    settings = McpSettings.from_env()
    assert settings.region == "r" and settings.security_token is None
    monkeypatch.setenv("HUAWEICLOUD_REGION", "explicit-r")
    file.write_text("invalid")
    assert McpSettings.from_env().region == "explicit-r"


@guard(risk=ToolRisk.READ)
async def hardened_reader() -> dict[str, Any]:
    raise McpToolError("MCP_TEST_FAILURE", "Bearer example-secret", request_id="request-1")


async def test_thrown_and_returned_errors_are_masked_and_audited() -> None:
    audit = AuditLogger()
    middleware = GuardrailsMiddleware(audit=audit)
    ctx: Any = SimpleNamespace(
        method="tools/call", params={"name": "hardened_reader", "arguments": {}}
    )

    async def throw(_: Any) -> Any:
        raise McpToolError("MCP_TEST_FAILURE", "Bearer example-secret", request_id="request-1")

    async def returned(_: Any) -> Any:
        return await hardened_reader()

    for callback in (throw, returned):
        result = await middleware(ctx, callback)
        assert "example-secret" not in str(result)
        if isinstance(result, CallToolResult):
            assert result.is_error
        record = audit.events[-1]
        assert record["outcome"] == "failed" and record["error_code"] == "MCP_TEST_FAILURE"
        assert record["request_id"] == "request-1"


async def test_busy_tool_is_not_executed_and_capacity_is_released() -> None:
    middleware = GuardrailsMiddleware(max_concurrent=1)
    ctx: Any = SimpleNamespace(
        method="tools/call", params={"name": "hardened_reader", "arguments": {}}
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def block(_: Any) -> Any:
        entered.set()
        await release.wait()
        return {"ok": True}

    task = asyncio.create_task(middleware(ctx, block))
    await entered.wait()
    result = await middleware(ctx, block)
    assert result.structured_content["error"]["code"] == "MCP_BUSY"
    release.set()
    await task
    assert await middleware(ctx, block) == {"ok": True}


def test_audit_history_rotation_permissions_and_full_record_masking(tmp_path: Path) -> None:
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
        assert (
            "private-token" not in file.read_text() and ("s" * 40 + "tail") not in file.read_text()
        )
        if os.name != "nt":
            assert file.stat().st_mode & 0o077 == 0
    if os.name != "nt":
        target.chmod(0o644)
        audit.emit(tool="denied")
        assert audit.file_errors == 1


def test_audit_refuses_symlink_and_masking_is_idempotent(tmp_path: Path) -> None:
    if os.name != "nt":
        target = tmp_path / "target"
        target.write_text("unchanged")
        link = tmp_path / "audit"
        link.symlink_to(target)
        audit = AuditLogger(str(link))
        audit.emit(tool="test")
        assert target.read_text() == "unchanged" and audit.file_errors == 1
    engine = MaskingEngine()
    masked = engine.mask({"password": "value", "ak": "example", "sk": "example"})
    assert engine.mask(masked) == masked


def test_large_audit_record_is_bounded() -> None:
    audit = AuditLogger()
    record = audit._build_record(
        tool="large", params={str(i): ["x" * 200] * 100 for i in range(100)}
    )
    assert len(json.dumps(record).encode()) < 16 * 1024
    assert record["params"]["_truncated"] is True
