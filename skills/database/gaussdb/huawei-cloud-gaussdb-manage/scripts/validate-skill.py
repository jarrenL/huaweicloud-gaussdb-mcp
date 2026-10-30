#!/usr/bin/env python3
"""Validate this self-contained Skill package.

Arguments: none.
Returns: exit code 0 when structure, links, metadata, size, and secret checks pass;
exit code 1 with one message per failed check otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SKILL_NAME = "huawei-cloud-gaussdb-manage"
REQUIRED_SECTIONS = (
    "概述",
    "能力边界与路由",
    "前置条件",
    "工作流",
    "购买前选型与询价",
    "主备切换与容灾",
    "核心命令（MCP 工具）",  # noqa: RUF001 - match the required Chinese heading exactly.
    "参数确认",
    "输出格式",
    "验证方法",
    "最佳实践",
    "参考文档",
)
SECRET_PATTERN = re.compile(
    r"(?i)(?:ak|sk|access[_-]?key|secret[_-]?key|securitytoken)"
    r"\s*[:=]\s*[A-Za-z0-9/+_-]{12,}"
)


def frontmatter(text: str) -> str | None:
    """Return the YAML frontmatter text without requiring a YAML package."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    return None if end < 0 else text[4:end]


def main() -> int:
    """Run deterministic package checks and return a process exit code."""
    root = Path(__file__).resolve().parents[1]
    skill_file = root / "SKILL.md"
    errors: list[str] = []

    if root.name != SKILL_NAME:
        errors.append(f"directory must be named {SKILL_NAME}")
    if not skill_file.is_file():
        errors.append("SKILL.md is missing")
        return report(errors)

    text = skill_file.read_text(encoding="utf-8")
    meta = frontmatter(text)
    if meta is None:
        errors.append("SKILL.md must start with YAML frontmatter")
    else:
        if not re.search(rf"(?m)^name:\s*{re.escape(SKILL_NAME)}\s*$", meta):
            errors.append("frontmatter name must match the directory")
        if not re.search(r"(?m)^description:\s*[|>]\s*$", meta):
            errors.append("frontmatter description must be a multiline string")
        if not re.search(r"(?m)^metadata:\s*$", meta):
            errors.append("frontmatter metadata is missing")
        if not re.search(r"(?m)^\s+version:\s*[\"']?1\.4\.0[\"']?\s*$", meta):
            errors.append("metadata.version must be 1.4.0")
        tags_match = re.search(r"(?m)^\s+tags:\s*\[([^]]*)\]\s*$", meta)
        if not tags_match:
            errors.append("metadata.tags is missing")
        elif len([tag for tag in tags_match.group(1).split(",") if tag.strip()]) > 5:
            errors.append("metadata.tags must contain no more than five tags")

    for section in REQUIRED_SECTIONS:
        if not re.search(rf"(?m)^##+ {re.escape(section)}\s*$", text):
            errors.append(f"missing required section: {section}")

    if len(text.splitlines()) >= 500:
        errors.append("SKILL.md must be fewer than 500 lines")

    total_size = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    if total_size >= 5 * 1024 * 1024:
        errors.append("Skill package must be smaller than 5 MiB")

    for link in re.findall(r"\]\(([^)]+)\)", text):
        if "://" in link or link.startswith("#"):
            continue
        if not (root / link).is_file():
            errors.append(f"broken local link: {link}")

    for reference in sorted((root / "references").glob("*.md")):
        reference_text = reference.read_text(encoding="utf-8")
        if not reference_text.startswith("# "):
            errors.append(f"reference must start with H1: {reference.name}")

    smoke_script = root / "scripts" / "smoke.py"
    if not smoke_script.is_file():
        errors.append("scripts/smoke.py is missing")
    else:
        try:
            compile(smoke_script.read_text(encoding="utf-8"), str(smoke_script), "exec")
        except SyntaxError as exc:
            errors.append(f"scripts/smoke.py has invalid Python syntax: {exc}")
        if not (smoke_script.stat().st_mode & 0o111):
            errors.append("scripts/smoke.py must be executable")

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in {".md", ".py", ".json", ".yaml", ".yml"}:
            continue
        content = path.read_text(encoding="utf-8")
        if SECRET_PATTERN.search(content):
            errors.append(f"possible embedded secret: {path.relative_to(root)}")

    return report(errors)


def report(errors: list[str]) -> int:
    """Print a compact result and return its exit code."""
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: Huawei Cloud GaussDB Skill package is valid")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(f"FAIL: unable to read Skill package: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
