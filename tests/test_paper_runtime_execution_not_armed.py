"""Importing paper_runtime.execution does not arm paper.

ADR §8.2: this module is the paper-runtime DTO adapter, not
execution.paper_service.PaperExecutionService. It must not call run_paper.
"""

from __future__ import annotations

import ast
from pathlib import Path


def test_import_paper_runtime_execution_does_not_arm_and_is_not_live_service() -> None:
    import paper_runtime
    import paper_runtime.execution as helper
    import agents  # noqa: F401 — complete agents↔execution cycle
    from execution.paper_service import PaperExecutionService
    from features.research_freezes import (
        CONTINUOUS_PAPER,
        MASS_RESEARCH,
        PAPER_SCHEDULER_ARMED,
        READY_DECLARED,
    )

    assert CONTINUOUS_PAPER == "UNARMED"
    assert PAPER_SCHEDULER_ARMED is False
    assert READY_DECLARED is False
    assert MASS_RESEARCH == "NO-GO"
    assert helper.__name__ == "paper_runtime.execution"
    assert helper.PaperExecutionService is not PaperExecutionService
    assert PaperExecutionService.__module__ == "execution.paper_service"
    assert "execution" not in paper_runtime.__all__
    assert not hasattr(paper_runtime, "PaperExecutionService")


def test_paper_runtime_execution_is_dto_adapter_not_run_paper_caller() -> None:
    """The helper may import the strong service; it must not import run_paper."""
    import paper_runtime.execution as helper

    path = Path(helper.__file__).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            for alias in node.names:
                imported.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)

    assert "run_paper" not in imported
    assert "strategies.paper.run_paper" not in imported
    assert "run_paper" not in called
    assert "execution.paper_service" in imported
    assert "execute_runtime_dto" in called or "execute" in called
