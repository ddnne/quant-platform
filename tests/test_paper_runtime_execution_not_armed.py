"""Importing paper_runtime.execution does not arm paper.

ADR §8.2: this module is the paper-runtime DTO adapter, not
execution.paper_service.PaperExecutionService. It must not call run_paper.
"""

from __future__ import annotations


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
