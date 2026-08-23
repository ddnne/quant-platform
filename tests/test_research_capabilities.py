"""Research capabilities deny-by-default. Not GO."""
from __future__ import annotations

from research.candidate_policy import job_candidate_grade
from research.research_capabilities import (
    research_capabilities,
    require_capability,
)


def test_research_capabilities_deny_without_readiness() -> None:
    caps = research_capabilities(
        {
            "MASS_RESEARCH": "NO-GO",
            "READY_DECLARED": "false",
            "PHASE7": "OFF",
        }
    )
    assert caps["mass_screen"] is False
    assert caps["generation"] is False
    assert caps["data_ready"] is False
    assert "mass_research_no_go" in caps["reasons"]
    assert "verified_readiness_missing" in caps["reasons"]
    gate = require_capability("mass_screen", caps)
    assert gate["allowed"] is False
    assert gate["go"] is False


def test_job_candidate_grade_false_on_partial() -> None:
    assert job_candidate_grade(n_expected=0, n_cells=0, n_complete=0) is False
    assert job_candidate_grade(n_expected=4, n_cells=4, n_complete=3) is False
    assert (
        job_candidate_grade(
            n_expected=4, n_cells=4, n_complete=4, n_collapsed=1
        )
        is False
    )
    assert job_candidate_grade(n_expected=4, n_cells=4, n_complete=4) is True
