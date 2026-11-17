"""Gate GaussDB source complexity and Pylint errors/structural diagnostics.

The full Pylint scan still runs; convention-only diagnostics remain visible in
its issue count, but do not replace the repository's existing Ruff style checks.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from radon.complexity import cc_visit

MAX_COMPLEXITY = 19
PYLINT_GATED_SYMBOLS = {
    "too-many-boolean-expressions",
    "too-many-branches",
    "too-many-statements",
    "too-many-locals",
    "unused-import",
    "cyclic-import",
}


def _functions(blocks: list[Any]) -> Iterator[Any]:
    for block in blocks:
        if hasattr(block, "is_method"):
            yield block
        yield from _functions(getattr(block, "methods", []))
        yield from _functions(getattr(block, "closures", []))


def complexity_results(root: Path) -> list[tuple[int, str, int, str]]:
    results = set()
    for path in sorted(root.rglob("*.py")):
        for block in _functions(cc_visit(path.read_text(encoding="utf-8"))):
            results.add((block.complexity, str(path), block.lineno, block.name))
    return sorted(results, reverse=True)


def pylint_results(root: Path) -> tuple[list[dict[str, Any]], int]:
    scan = subprocess.run(
        [sys.executable, "-m", "pylint", str(root), "--output-format=json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if scan.returncode & 32:
        raise RuntimeError(f"Pylint could not run: {scan.stderr.strip()}")
    messages = json.loads(scan.stdout)
    if not isinstance(messages, list):
        raise RuntimeError("Pylint did not return a diagnostic list.")
    blocked = [
        message
        for message in messages
        if message["type"] in {"error", "fatal"} or message["symbol"] in PYLINT_GATED_SYMBOLS
    ]
    return blocked, len(messages)


def main() -> int:
    root = Path(__file__).resolve().parents[1] / "src"
    scores = complexity_results(root)
    violations = [item for item in scores if item[0] > MAX_COMPLEXITY]
    issues, total = pylint_results(root)
    print(f"Complexity: max={scores[0][0] if scores else 0}; required <20")
    for score, path, line, name in violations:
        print(f"FAIL: {path}:{line} {name} complexity={score}")
    print(f"Pylint: {len(issues)} gated issues; {total} total diagnostics")
    for issue in issues:
        print(f"FAIL: {issue['path']}:{issue['line']} {issue['message-id']} {issue['message']}")
    return int(bool(violations or issues))


if __name__ == "__main__":
    raise SystemExit(main())
