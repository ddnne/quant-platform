"""Static enforcement of the Phase 5 Paper dependency boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

import strategies


STRATEGIES_DIR = Path(strategies.__file__).resolve().parent
EXAMPLES_DIR = STRATEGIES_DIR / "examples"
PAPER_DIR = STRATEGIES_DIR / "paper"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_example_strategies_do_not_import_raw_fact_or_network_modules():
    """Strategies receive context/use features; they never bypass either."""
    forbidden_roots = {
        "pit",
        "storage",
        "sqlite3",
        "httpx",
        "requests",
        "urllib",
        "socket",
        "secrets",
        "jquants",
        "ingestion",
    }
    offenders: list[str] = []
    for path in sorted(EXAMPLES_DIR.rglob("*.py")):
        for module in _imports(path):
            if module.split(".", 1)[0] in forbidden_roots:
                offenders.append(f"{path.relative_to(STRATEGIES_DIR)}: {module}")
    assert not offenders, "forbidden strategy imports:\n" + "\n".join(offenders)


def test_paper_layer_has_no_external_api_or_core_internal_imports():
    """Paper orchestration uses public core/features, never HTTP/J-Quants."""
    forbidden_roots = {
        "httpx",
        "requests",
        "urllib",
        "socket",
        "secrets",
        "jquants",
        "ingestion",
    }
    offenders: list[str] = []
    for path in sorted(PAPER_DIR.rglob("*.py")):
        for module in _imports(path):
            if module.startswith("core.") or module.split(".", 1)[0] in forbidden_roots:
                offenders.append(f"{path.relative_to(STRATEGIES_DIR)}: {module}")
    assert not offenders, "forbidden paper-layer imports:\n" + "\n".join(offenders)
