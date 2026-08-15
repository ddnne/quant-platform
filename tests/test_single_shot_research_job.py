"""T8 single-shot job + T9 Phase7/Mass OFF freeze + W50 execute/DEFER (w0815aq)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agents.mass_research import start_mass_research
from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
)
from research.single_shot_job import (
    COMPLETE_21_DATASETS,
    COMPLETE_21_DATASET_SET,
    MASS_RESEARCH_ENV_ARMING_SWITCHES,
    MASS_RESEARCH_STATUS,
    PHASE7_ENV_ARMING_SWITCHES,
    PHASE7_STATUS,
    READY_DECLARED,
    READY_PUBLICATION_STATUS,
    RESEARCH_ARTIFACT_BUCKET,
    RESEARCH_ARTIFACT_PREFIX,
    SingleShotJobError,
    assert_mass_and_phase7_off,
    build_single_shot_job_spec,
    design_artifact_paths,
    execute_single_shot_job,
    extract_d1_tip_summaries,
    freeze_status,
    require_complete_21_only,
)
from selection.budget_ledger import MassResearchDisabledError, ResearchBudgetCapability
from selection.screen import ExperimentBudget

REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_SHOT_PATH = (
    REPO_ROOT / "packages" / "product" / "research" / "single_shot_job.py"
)


# ---------------------------------------------------------------------------
# T8 — COMPLETE 21 inputs + R2 artifact design
# ---------------------------------------------------------------------------


def test_complete_21_is_exactly_twenty_one_and_excludes_permanent_defer():
    assert len(COMPLETE_21_DATASETS) == 21
    assert len(COMPLETE_21_DATASET_SET) == 21
    assert COMPLETE_21_DATASET_SET.isdisjoint(PERMANENT_DEFER_DATASETS)
    # Residual SoT held sample (includes markets_breakdown).
    assert "markets_breakdown" in COMPLETE_21_DATASET_SET
    assert "equities_bars_daily" in COMPLETE_21_DATASET_SET
    for defer in PERMANENT_DEFER_DATASETS:
        assert defer not in COMPLETE_21_DATASET_SET


def test_require_complete_21_only_accepts_subset():
    ids = require_complete_21_only(
        ["equities_bars_daily", "markets_calendar", "equities_bars_daily"]
    )
    assert ids == ("equities_bars_daily", "markets_calendar")


def test_require_complete_21_only_rejects_permanent_defer():
    with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER|PD-D2-MASTER"):
        require_complete_21_only(["equities_bars_daily", "equities_master"])


def test_require_complete_21_only_rejects_all_five_permanent_defer():
    """T3: every permanent DEFER id fails closed with PermanentDeferHistoryError."""
    for defer_id in sorted(PERMANENT_DEFER_DATASETS):
        with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER"):
            require_complete_21_only([defer_id])
    # Bundle of all 5 still fail-closed (never silently filtered).
    with pytest.raises(PermanentDeferHistoryError):
        require_complete_21_only(sorted(PERMANENT_DEFER_DATASETS))


def test_require_complete_21_only_rejects_unknown():
    with pytest.raises(SingleShotJobError, match="not in COMPLETE 21"):
        require_complete_21_only(["equities_bars_daily", "not_a_real_dataset"])


def test_design_artifact_paths_are_r2_not_local_sot():
    paths = design_artifact_paths("job-demo-1")
    assert paths["bucket"] == "quant-structured"
    assert paths["local_sot"] is False
    assert paths["prefix"].startswith("research/single_shot/job=")
    assert paths["manifest_r2_key"].endswith("/manifest.json")
    assert "{content_hash}" in paths["result_r2_key_template"]
    # No local filesystem SoT fields (authority keys are R2 only).
    assert "local_path" not in paths
    assert not any(str(k).startswith("/") for k in paths if isinstance(k, str) is False)
    for key in ("manifest_r2_key", "input_plan_r2_key", "prefix"):
        assert not str(paths[key]).startswith("/")
        assert not str(paths[key]).startswith("data/")


def test_build_single_shot_job_spec_skeleton():
    spec = build_single_shot_job_spec(
        dataset_ids=["equities_bars_daily", "fins_summary"],
        period_start="2024-01-01",
        period_end="2024-06-30",
        job_id="w0815ap-t8-demo",
    )
    body = spec.to_dict()
    assert body["job_id"] == "w0815ap-t8-demo"
    assert body["dataset_ids"] == ["equities_bars_daily", "fins_summary"]
    assert body["artifact"]["bucket"] == RESEARCH_ARTIFACT_BUCKET
    assert body["artifact"]["prefix"].startswith(RESEARCH_ARTIFACT_PREFIX)
    assert body["artifact"]["local_sot"] is False
    assert body["mass_research"] == "NO-GO"
    assert body["phase7"] == "OFF"
    assert body["ready_declared"] is False
    assert body["ready_publication"] == "OFF"


def test_build_rejects_empty_and_defer():
    with pytest.raises(SingleShotJobError, match="at least one"):
        build_single_shot_job_spec(
            dataset_ids=[],
            period_start="2024-01-01",
            period_end="2024-01-02",
        )
    with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER|PD-D4-BARS-AM"):
        build_single_shot_job_spec(
            dataset_ids=["equities_bars_daily_am"],
            period_start="2024-01-01",
            period_end="2024-01-02",
        )


def test_execute_rejects_permanent_defer_before_d1():
    """T3: execute path fail-closed on DEFER 5 — no D1 call."""
    calls: list[str] = []

    def boom_d1(sql: str):
        calls.append(sql)
        raise AssertionError("d1 must not be called for permanent DEFER input")

    with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER"):
        execute_single_shot_job(
            dataset_ids=["equities_master", "equities_bars_daily"],
            period_start="2026-08-01",
            period_end="2026-08-15",
            job_id="defer-reject-demo",
            dry_run=True,
            d1_execute=boom_d1,
        )
    assert calls == []


def test_execute_dry_run_with_injected_d1(tmp_path: Path):
    """Minimal execute path: injected tip rows → dry-run R2 staging."""

    def fake_d1(sql: str):
        if "COUNT(*)" in sql:
            if "equities_bars_daily" in sql:
                return [
                    {
                        "n": 3,
                        "min_event_time": "2026-08-01T15:00:00+09:00",
                        "max_event_time": "2026-08-05T15:00:00+09:00",
                    }
                ]
            return [
                {
                    "n": 2,
                    "min_event_time": "2026-08-01",
                    "max_event_time": "2026-08-04",
                }
            ]
        # sample rows
        if "equities_bars_daily" in sql:
            return [
                {
                    "natural_key": '{"Code":"13010","Date":"2026-08-01"}',
                    "event_time": "2026-08-01T15:00:00+09:00",
                    "available_at": "2026-08-01T16:00:00+09:00",
                }
            ]
        return [
            {
                "natural_key": '{"Date":"2026-08-01"}',
                "event_time": "2026-08-01",
                "available_at": "2026-08-01",
            }
        ]

    puts: list[tuple[str, str, int]] = []

    def fake_put(bucket: str, key: str, body: bytes):
        puts.append((bucket, key, len(body)))
        return {"bucket": bucket, "key": key, "bytes": len(body), "status": "injected"}

    ex = execute_single_shot_job(
        dataset_ids=["equities_bars_daily", "markets_calendar"],
        period_start="2026-08-01",
        period_end="2026-08-15",
        job_id="w0815aq-unit-demo",
        dry_run=True,
        d1_execute=fake_d1,
        r2_put=fake_put,
        staging_dir=tmp_path,
    )
    assert ex.job_id == "w0815aq-unit-demo"
    assert ex.ready_declared is False
    assert ex.mass_research == "NO-GO"
    assert ex.phase7 == "OFF"
    assert ex.content_hash.startswith("sha256:")
    assert ex.result_r2_key.startswith("research/single_shot/job=w0815aq-unit-demo/")
    assert len(puts) == 3
    assert all(p[0] == "quant-structured" for p in puts)
    keys = {p[1] for p in puts}
    assert ex.manifest_r2_key in keys
    assert ex.input_plan_r2_key in keys
    assert ex.result_r2_key in keys
    assert ex.tip_extracts["extracts"]["equities_bars_daily"]["row_count"] == 3
    assert ex.tip_extracts["extracts"]["markets_calendar"]["row_count"] == 2
    body = ex.to_dict()
    assert body["ready_declared"] is False
    assert body["local_sot"] is False


def test_extract_d1_tip_summaries_rejects_defer():
    with pytest.raises(PermanentDeferHistoryError):
        extract_d1_tip_summaries(
            ["fins_earnings_date"],
            period_start="2026-08-01",
            period_end="2026-08-15",
            d1_execute=lambda sql: (_ for _ in ()).throw(AssertionError("no d1")),
        )


# ---------------------------------------------------------------------------
# T9 — Phase7 / Mass OFF freeze + hard reject
# ---------------------------------------------------------------------------


def test_phase7_mass_ready_freeze_constants():
    assert MASS_RESEARCH_STATUS == "NO-GO"
    assert PHASE7_STATUS == "OFF"
    assert READY_PUBLICATION_STATUS == "OFF"
    assert READY_DECLARED is False
    assert PHASE7_ENV_ARMING_SWITCHES == frozenset()
    assert MASS_RESEARCH_ENV_ARMING_SWITCHES == frozenset()
    status = assert_mass_and_phase7_off()
    assert status["mass_research"] == "NO-GO"
    assert status["phase7"] == "OFF"
    assert status["ready_declared"] is False
    assert status["connected_to_mass_research_loop"] is False
    assert status["sets_ready"] is False


def test_freeze_status_matches_constants():
    status = freeze_status()
    assert status["complete_21_count"] == 21
    assert status["permanent_defer_count"] == 5
    assert status["artifact_bucket"] == "quant-structured"
    assert status["local_sot"] is False


def test_mass_research_still_hard_reject_without_readiness(tmp_path: Path):
    """Single-shot skeleton must not bypass mass fail-closed gate."""
    with pytest.raises(MassResearchDisabledError):
        start_mass_research(budget=None, readiness=None)
    cap = ResearchBudgetCapability(
        "b",
        tmp_path / "b.sqlite",
        ExperimentBudget(),
    )
    with pytest.raises(MassResearchDisabledError):
        start_mass_research(budget=cap, readiness=None)


def test_single_shot_module_does_not_import_mass_research_loop():
    """AST guard: skeleton must not call into agents.mass_research."""
    tree = ast.parse(SINGLE_SHOT_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
                for alias in node.names:
                    imported.add(alias.name)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    assert "agents" not in imported
    assert "mass_research" not in imported
    assert "start_mass_research" not in imported
    assert "require_mass_research_start" not in imported
    assert "VerifiedResearchReadiness" not in imported
    assert "start_mass_research" not in called
    assert "require_mass_research_start" not in called


def test_no_phase7_or_mass_env_arming_switches_in_skeleton_source():
    src = SINGLE_SHOT_PATH.read_text(encoding="utf-8")
    # Must not define or enable arming flags.
    assert "MASS_RESEARCH_ENABLE" not in src
    assert "os.environ" not in src
    assert "PHASE7_ENABLE" not in src
    assert 'PHASE7_STATUS: str = "ON"' not in src
    assert 'MASS_RESEARCH_STATUS: str = "GO"' not in src
