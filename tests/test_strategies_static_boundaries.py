"""Static dependency boundary for every strategy-package module.

Strategy and paper-orchestration code must consume trusted public runtime
interfaces.  It must not reach around those interfaces to raw facts, storage,
network clients, secrets, or arbitrary process/code execution.
"""

from __future__ import annotations

import ast
from pathlib import Path


STRATEGIES_DIR = Path(__file__).resolve().parents[1] / "strategies"

FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "cf_platform",
        "httpx",
        "ingestion",
        "pit",
        "requests",
        "secrets",
        "socket",
        "sqlite3",
        "storage",
        "subprocess",
        "urllib",
    }
)


def _is_test_module(path: Path) -> bool:
    relative = path.relative_to(STRATEGIES_DIR)
    return (
        any(part in {"test", "tests"} for part in relative.parts[:-1])
        or path.name == "conftest.py"
        or path.stem.startswith("test_")
        or path.stem.endswith("_test")
    )


def _strategy_python_files() -> list[Path]:
    """Include current and future strategy subpackages, excluding their tests."""
    return sorted(
        path
        for path in STRATEGIES_DIR.rglob("*.py")
        if not _is_test_module(path)
    )


def _root(module: str) -> str:
    return module.split(".", 1)[0]


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    relative = path.relative_to(STRATEGIES_DIR.parent)
    violations: list[str] = []

    os_aliases: set[str] = set()
    os_system_aliases: set[str] = set()
    builtins_aliases: set[str] = set()
    dynamic_call_aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _root(alias.name)
                if root in FORBIDDEN_IMPORT_ROOTS:
                    violations.append(
                        f"{relative}:{node.lineno}: forbidden import {alias.name!r}"
                    )
                if root == "os":
                    os_aliases.add(alias.asname or "os")
                elif root == "builtins":
                    builtins_aliases.add(alias.asname or "builtins")

        elif isinstance(node, ast.ImportFrom):
            # Relative imports are within the strategy package and do not name
            # an external dependency root.
            if node.level == 0 and node.module:
                root = _root(node.module)
                if root in FORBIDDEN_IMPORT_ROOTS:
                    violations.append(
                        f"{relative}:{node.lineno}: forbidden import "
                        f"{node.module!r}"
                    )
                if root == "os":
                    for alias in node.names:
                        if alias.name == "system":
                            os_system_aliases.add(alias.asname or alias.name)
                elif root == "builtins":
                    for alias in node.names:
                        if alias.name in {"eval", "exec"}:
                            dynamic_call_aliases[alias.asname or alias.name] = alias.name

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            call_name = dynamic_call_aliases.get(function.id, function.id)
            if function.id in os_system_aliases:
                call_name = "os.system"
            if call_name in {"eval", "exec", "os.system"}:
                violations.append(
                    f"{relative}:{node.lineno}: forbidden call {call_name}()"
                )
        elif isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
            owner = function.value.id
            if owner in os_aliases and function.attr == "system":
                call_name = "os.system"
            elif owner in builtins_aliases and function.attr in {"eval", "exec"}:
                call_name = f"builtins.{function.attr}"
            else:
                continue
            violations.append(
                f"{relative}:{node.lineno}: forbidden call {call_name}()"
            )

    return violations


def test_strategy_modules_respect_trusted_runtime_boundary():
    modules = _strategy_python_files()
    assert modules, f"no strategy modules found under {STRATEGIES_DIR}"

    violations = [
        violation
        for path in modules
        for violation in _violations(path)
    ]
    assert not violations, "forbidden strategy boundary violations:\n" + "\n".join(
        violations
    )
