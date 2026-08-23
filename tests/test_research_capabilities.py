"""Research capabilities deny-by-default. Not GO."""
from __future__ import annotations

import urllib.request

from research.candidate_policy import job_candidate_grade
from research.research_capabilities import (
    research_capabilities,
    require_capability,
)


def _boom(*_a, **_k):
    raise AssertionError("must not contact network")


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


def test_mass_eval_driver_refuses_without_http(monkeypatch) -> None:
    from research.cf_mass_eval_job import (
        invoke_cf_mass_eval_worker,
        run_cf_mass_eval_job,
    )

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    out = invoke_cf_mass_eval_worker({"job_id": "cap-deny"}, http_post=_boom)
    assert out["ok"] is False
    assert out["error"] == "capability_missing"
    assert out["capability"] == "mass_screen"
    assert out["go"] is False
    job = run_cf_mass_eval_job(
        job_id="cap-deny-job",
        logic_ids=["nky_vol_abs_level"],
        mode="synthetic",
        stage_panels=False,
        deploy_if_needed=False,
        http_post=_boom,
    )
    assert job["ok"] is False
    assert job["error"] == "capability_missing"
    assert job["go"] is False


def test_daily_path_driver_refuses_without_http(monkeypatch) -> None:
    from research.cf_daily_path_job import (
        invoke_cf_daily_path,
        run_cf_daily_path_fanout,
    )

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    out = invoke_cf_daily_path({"job_id": "cap-deny-dp"}, http_post=_boom)
    assert out["ok"] is False
    assert out["error"] == "capability_missing"
    assert out["capability"] == "mass_screen"
    assert out["go"] is False
    pack = run_cf_daily_path_fanout(
        job_id="cap-deny-fan",
        logic_ids=["nky_vol_abs_level"],
        skip_stage=True,
        mode="synthetic",
        http_post=_boom,
        max_workers=1,
        periods=[
            {
                "period_id": "y2015_full",
                "period_start": "2015-01-05",
                "period_end": "2015-03-01",
            }
        ],
    )
    assert pack["ok"] is False
    assert pack["error"] == "capability_missing"
    assert pack["go"] is False


def test_propose_driver_refuses_without_http(monkeypatch) -> None:
    from research.cf_propose_thesis import invoke_cf_propose_thesis

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    out = invoke_cf_propose_thesis(n=1, http_post=_boom)
    assert out["ok"] is False
    assert out["error"] == "capability_missing"
    assert out["capability"] == "generation"
    assert out["go"] is False


def test_driver_env_flags_cannot_grant(monkeypatch) -> None:
    from research.cf_mass_eval_job import invoke_cf_mass_eval_worker
    from research.cf_propose_thesis import invoke_cf_propose_thesis

    monkeypatch.setenv("MASS_RESEARCH", "GO")
    monkeypatch.setenv("PHASE7", "ON")
    monkeypatch.setenv("READY_DECLARED", "true")
    monkeypatch.setenv("OPERATIONAL_GO", "true")
    monkeypatch.setenv("CONTINUOUS_PAPER", "ARMED")
    monkeypatch.setenv("MASS_EVAL_TOKEN", "x")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    mass = invoke_cf_mass_eval_worker({"job_id": "cap-env"}, http_post=_boom)
    assert mass["ok"] is False
    assert mass["error"] == "capability_missing"
    assert mass["go"] is False
    gen = invoke_cf_propose_thesis(n=1, http_post=_boom)
    assert gen["ok"] is False
    assert gen["error"] == "capability_missing"
    assert gen["capability"] == "generation"
    assert gen["go"] is False
