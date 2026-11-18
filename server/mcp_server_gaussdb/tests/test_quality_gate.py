"""Verify that the quality gate actually rejects over-complex and invalid code."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def quality() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts/check_quality.py"
    spec = importlib.util.spec_from_file_location("gaussdb_quality_gate", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_complexity_includes_methods_and_closures(quality: ModuleType, tmp_path: Path) -> None:
    branches = "".join(
        f"        if value == {index}:\n            value += 1\n" for index in range(20)
    )
    (tmp_path / "nested.py").write_text(
        "class Sample:\n    def method(self, value):\n"
        + branches
        + "        def nested(value):\n"
        + "            return value\n"
        + "        return nested(value)\n"
    )
    scores = quality.complexity_results(tmp_path)
    assert any(score > quality.MAX_COMPLEXITY and name == "method" for score, _, _, name in scores)
    assert any(name == "nested" for _, _, _, name in scores)


def test_pylint_gate_rejects_long_boolean_conditions(quality: ModuleType, tmp_path: Path) -> None:
    source = tmp_path / "boolean_sample.py"
    source.write_text(
        "def sample(a, b, c, d, e, f):\n"
        "    if a and b and c and d and e and f:\n"
        "        return True\n"
        "    return False\n"
    )
    issues, total = quality.pylint_results(source)
    assert total > 0
    assert any(issue["symbol"] == "too-many-boolean-expressions" for issue in issues)


def test_pylint_gate_rejects_undefined_names(quality: ModuleType, tmp_path: Path) -> None:
    source = tmp_path / "undefined_sample.py"
    source.write_text("def sample():\n    return undefined_name\n")
    issues, _ = quality.pylint_results(source)
    assert any(issue["message-id"] == "E0602" for issue in issues)
