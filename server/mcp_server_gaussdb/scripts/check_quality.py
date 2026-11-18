"""Gate GaussDB source complexity and Pylint errors/structural diagnostics.

The full Pylint scan still runs; convention-only diagnostics remain visible in
its issue count, but do not replace the repository's existing Ruff style checks.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from typing import Any

from pylint.lint import Run
from pylint.reporters.json_reporter import JSONReporter
from radon.complexity import cc_visit

MAX_COMPLEXITY = 19
PYLINT_GATED_SYMBOLS = {
    "too-many-boolean-expressions",
    "too-many-branches",
    "too-many-statements",
    "too-many-locals",
    "unused-import",
    "cyclic-import",
    "unidiomatic-typecheck",
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
    output = StringIO()
    scan = Run(
        [str(root), "--reports=n", "--score=n"],
        reporter=JSONReporter(output),
        exit=False,
    )
    if scan.linter.msg_status & 32:
        raise RuntimeError("Pylint could not run.")
    messages = json.loads(output.getvalue())
    if not isinstance(messages, list):
        raise RuntimeError("Pylint did not return a diagnostic list.")
    blocked = [
        message
        for message in messages
        if message["type"] in {"error", "fatal"} or message["symbol"] in PYLINT_GATED_SYMBOLS
    ]
    return blocked, len(messages)


def main() -> int:
    package = Path(__file__).resolve().parents[1]
    skill_scripts = (
        package.parents[1] / "skills/database/gaussdb/huawei-cloud-gaussdb-manage/scripts"
    )
    roots = [package / "src", package / "tests", package / "scripts", skill_scripts]
    scores = sorted(
        (item for root in roots for item in complexity_results(root)),
        reverse=True,
    )
    violations = [item for item in scores if item[0] > MAX_COMPLEXITY]
    issues, total = pylint_results(package / "src")
    print(f"Complexity: max={scores[0][0] if scores else 0}; required <20")
    for score, path, line, name in violations:
        print(f"FAIL: {path}:{line} {name} complexity={score}")
    print(f"Pylint: {len(issues)} gated issues; {total} total diagnostics")
    for issue in issues:
        print(f"FAIL: {issue['path']}:{issue['line']} {issue['message-id']} {issue['message']}")
    return int(bool(violations or issues))


if __name__ == "__main__":
    raise SystemExit(main())
