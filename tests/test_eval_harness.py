"""W56 / w0815aw_g2 T5–T7: reusable eval harness (single_shot only).

T5 — stable public API for:
  signal (approved legs) → multiday → next_day_return eval → R2 batch_summary
T6 — COMPLETE 21 only + approved feature legs (permanent_defer reject)
T7 — AST + freezes ban mass_research / READY / order execution
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from agents.mass_research import start_mass_research
from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
)
from research.eval_harness import (
    APPROVED_SIGNAL_LEGS,
    COMPLETE_21_DATASET_SET,
    CONNECTED_TO_MASS_RESEARCH_LOOP,
    DEFAULT_SIGNAL_DATASETS,
    DEFAULT_SIGNAL_ID,
    DENSIFY,
    HARNESS_VERSION,
    LOCAL_SOT,
    MASS_RESEARCH,
    MASS_RESEARCH_ENV_ARMING_SWITCHES,
    NEXTDAY_LOOKAHEAD_POLICY,
    NEXTDAY_RESEARCH_LABEL,
    ORDER_EXECUTION,
    PHASE7,
    PHASE7_ENV_ARMING_SWITCHES,
    PIPELINE,
    READY_DECLARED,
    READY_PUBLICATION,
    SIGNAL_CANDIDATE_ONLY,
    EvalHarnessError,
    assert_harness_closed,
    harness_freeze_status,
    require_approved_signal_legs,
    require_harness_datasets,
    run_full_pipeline,
    run_multiday_signal_eval,
    run_nextday_return_eval,
)
from selection.budget_ledger import MassResearchDisabledError

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_HARNESS_PATH = (
    REPO_ROOT / "packages" / "product" / "research" / "eval_harness.py"
)
SINGLE_SHOT_PATH = (
    REPO_ROOT / "packages" / "product" / "research" / "single_shot_job.py"
)


# ---------------------------------------------------------------------------
# Shared synthetic tip D1 (same shape as multiday unit fixtures)
# ---------------------------------------------------------------------------


def _fake_d1_multiday(sql: str):
    s = sql.lower()
    if "count(*)" in s:
        return [
            {
                "n": 12,
                "min_event_time": "2026-08-03",
                "max_event_time": "2026-08-12",
            }
        ]

    bar_days = [
        ("2026-08-03", 1000.0, 100.0),
        ("2026-08-04", 1010.0, 110.0),
        ("2026-08-05", 1005.0, 120.0),
        ("2026-08-06", 1020.0, 130.0),
        ("2026-08-07", 1015.0, 140.0),
        ("2026-08-10", 1030.0, 150.0),
        ("2026-08-11", 1025.0, 160.0),
        ("2026-08-12", 1040.0, 170.0),
    ]
    topix = [
        ("2026-08-03", 3000.0),
        ("2026-08-04", 3005.0),
        ("2026-08-05", 3010.0),
        ("2026-08-06", 3000.0),
        ("2026-08-07", 3015.0),
        ("2026-08-10", 3020.0),
        ("2026-08-11", 3010.0),
        ("2026-08-12", 3030.0),
    ]
    cal_days = [
        "2026-08-03",
        "2026-08-04",
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
        "2026-08-08",
        "2026-08-09",
        "2026-08-10",
        "2026-08-11",
        "2026-08-12",
    ]

    if "payload" in s and "equities_bars_daily" in s:
        rows = []
        for code, base in (("13010", 0.0), ("72030", 50.0)):
            for d, c, vo in bar_days:
                rows.append(
                    {
                        "natural_key": json.dumps({"Code": code, "Date": d}),
                        "event_time": f"{d}T09:00:00+09:00",
                        "available_at": f"{d}T15:30:00+09:00",
                        "payload": json.dumps(
                            {"Code": code, "Date": d, "C": c + base, "Vo": vo}
                        ),
                    }
                )
        return rows
    if "payload" in s and "indices_bars_daily_topix" in s:
        return [
            {
                "natural_key": json.dumps({"Date": d}),
                "event_time": f"{d}T09:00:00+09:00",
                "available_at": f"{d}T15:30:00+09:00",
                "payload": json.dumps({"Date": d, "C": c}),
            }
            for d, c in topix
        ]
    if "payload" in s and "markets_calendar" in s:
        rows = []
        for d in cal_days:
            hol = "0" if d in ("2026-08-08", "2026-08-09") else "1"
            rows.append(
                {
                    "natural_key": json.dumps({"Date": d}),
                    "event_time": d,
                    "available_at": f"{d}T00:00:00+09:00",
                    "payload": json.dumps({"Date": d, "HolidayDivision": hol}),
                }
            )
        return rows
    if "equities_bars_daily" in s:
        return [
            {
                "natural_key": json.dumps({"Code": "13010", "Date": d}),
                "event_time": f"{d}T09:00:00+09:00",
                "available_at": f"{d}T15:30:00+09:00",
            }
            for d, _, _ in bar_days
        ]
    return [
        {
            "natural_key": json.dumps({"Date": "2026-08-04"}),
            "event_time": "2026-08-04",
            "available_at": "2026-08-04",
        }
    ]


# ---------------------------------------------------------------------------
# T5 — stable public API / pipeline shape
# ---------------------------------------------------------------------------


def test_pipeline_constant_and_harness_version():
    assert HARNESS_VERSION == "research-eval-harness/v1"
    assert PIPELINE == (
        "approved_leg_signal",
        "multiday_as_of",
        "next_day_return_eval",
        "r2_batch_summary",
    )
    assert DEFAULT_SIGNAL_ID == "c21_topix_relative_sign"
    assert SIGNAL_CANDIDATE_ONLY is False
    assert set(APPROVED_SIGNAL_LEGS) == {
        "topix_relative_1d",
        "is_trading_day",
        "volume_change_1d",
    }


def test_run_nextday_return_eval_full_pipeline(tmp_path: Path):
    """T5: harness entry → multiday + nextday → R2 batch_summary."""
    puts: dict[str, bytes] = {}

    def fake_put(bucket: str, key: str, body: bytes):
        puts[key] = body
        return {"bucket": bucket, "key": key, "bytes": len(body), "status": "injected"}

    result = run_nextday_return_eval(
        period_start="2026-08-01",
        period_end="2026-08-14",
        job_id="w0815aw-g2-harness-unit",
        codes=["13010", "72030"],
        as_of_days=[
            "2026-08-04",
            "2026-08-05",
            "2026-08-06",
            "2026-08-07",
            "2026-08-10",
            "2026-08-11",
        ],
        max_days=10,
        min_days=5,
        dry_run=True,
        d1_execute=_fake_d1_multiday,
        r2_put=fake_put,
        staging_dir=tmp_path,
    )

    assert result.attach_nextday_returns is True
    assert result.n_days == 6
    assert result.mass_research == "NO-GO"
    assert result.phase7 == "OFF"
    assert result.ready_declared is False
    assert result.local_sot is False
    assert result.batch_summary_r2_key == (
        "research/single_shot/job=w0815aw-g2-harness-unit/batch_summary.json"
    )
    assert result.batch_summary_r2_key in puts
    body = json.loads(puts[result.batch_summary_r2_key].decode("utf-8"))
    assert body["attach_nextday_returns"] is True
    assert body["approved_legs_only"] is True
    assert body["signal_id"] == DEFAULT_SIGNAL_ID
    assert body["mass_research"] == "NO-GO"
    assert body["order_execution"] is False
    assert body["ready_declared"] is False
    assert body["connected_to_mass_research_loop"] is False
    assert body["label"] == NEXTDAY_RESEARCH_LABEL
    assert "研究用・未宣言" in body["label"]
    assert "小サンプル" in body["label"]
    assert "nextday_return" in body
    assert body["nextday_return"]["label"] == NEXTDAY_RESEARCH_LABEL
    assert body["nextday_return"]["look_ahead_policy"]["no_feature_lookahead"] is True
    assert set(body["dataset_ids"]).issubset(COMPLETE_21_DATASET_SET)


def test_run_full_pipeline_alias(tmp_path: Path):
    puts: dict[str, bytes] = {}

    def fake_put(bucket: str, key: str, body: bytes):
        puts[key] = body
        return {"bucket": bucket, "key": key, "bytes": len(body), "status": "injected"}

    result = run_full_pipeline(
        period_start="2026-08-01",
        period_end="2026-08-14",
        job_id="w0815aw-g2-full-alias",
        codes=["13010", "72030"],
        as_of_days=["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10"],
        max_days=10,
        min_days=5,
        dry_run=True,
        d1_execute=_fake_d1_multiday,
        r2_put=fake_put,
        staging_dir=tmp_path,
    )
    assert result.attach_nextday_returns is True
    assert result.n_days == 5


def test_run_multiday_without_nextday(tmp_path: Path):
    puts: dict[str, bytes] = {}

    def fake_put(bucket: str, key: str, body: bytes):
        puts[key] = body
        return {"bucket": bucket, "key": key, "bytes": len(body), "status": "injected"}

    result = run_multiday_signal_eval(
        period_start="2026-08-01",
        period_end="2026-08-14",
        job_id="w0815aw-g2-multiday-only",
        codes=["13010", "72030"],
        as_of_days=["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10"],
        attach_nextday_returns=False,
        dry_run=True,
        d1_execute=_fake_d1_multiday,
        r2_put=fake_put,
        staging_dir=tmp_path,
    )
    assert result.attach_nextday_returns is False
    body = json.loads(puts[result.batch_summary_r2_key].decode("utf-8"))
    assert "nextday_return" not in body
    assert body["approved_legs_only"] is True


# ---------------------------------------------------------------------------
# T6 — COMPLETE 21 only + approved legs (permanent_defer reject)
# ---------------------------------------------------------------------------


def test_require_harness_datasets_complete_21_only():
    ids = require_harness_datasets()
    assert ids == tuple(DEFAULT_SIGNAL_DATASETS)
    assert set(ids).issubset(COMPLETE_21_DATASET_SET)
    assert set(ids).isdisjoint(PERMANENT_DEFER_DATASETS)


def test_require_harness_datasets_rejects_permanent_defer():
    for defer_id in sorted(PERMANENT_DEFER_DATASETS):
        with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER"):
            require_harness_datasets([defer_id])
    with pytest.raises(PermanentDeferHistoryError):
        require_harness_datasets(["equities_bars_daily", "equities_master"])


def test_require_harness_datasets_rejects_unknown():
    from research.eval_harness import SingleShotJobError

    with pytest.raises(SingleShotJobError, match="not in COMPLETE 21"):
        require_harness_datasets(["equities_bars_daily", "not_a_real_dataset"])


def test_require_approved_signal_legs_default():
    legs = require_approved_signal_legs()
    assert legs == tuple(APPROVED_SIGNAL_LEGS)
    for fid in legs:
        from features.registry import get as get_feature

        assert get_feature(fid).status == "approved"


def test_require_approved_signal_legs_rejects_unknown():
    with pytest.raises(EvalHarnessError, match="unknown feature"):
        require_approved_signal_legs(["topix_relative_1d", "not_a_feature_xyz"])


def test_require_approved_signal_legs_rejects_empty():
    with pytest.raises(EvalHarnessError, match="at least one approved"):
        require_approved_signal_legs([])


# ---------------------------------------------------------------------------
# T7 — freeze + AST ban mass / READY / orders
# ---------------------------------------------------------------------------


def test_harness_freeze_constants():
    assert MASS_RESEARCH == "NO-GO"
    assert PHASE7 == "OFF"
    assert READY_PUBLICATION == "OFF"
    assert READY_DECLARED is False
    assert ORDER_EXECUTION is False
    assert CONNECTED_TO_MASS_RESEARCH_LOOP is False
    assert DENSIFY is False
    assert LOCAL_SOT is False
    assert PHASE7_ENV_ARMING_SWITCHES == frozenset()
    assert MASS_RESEARCH_ENV_ARMING_SWITCHES == frozenset()
    status = assert_harness_closed()
    assert status["mass_research"] == "NO-GO"
    assert status["phase7"] == "OFF"
    assert status["ready_declared"] is False
    fs = harness_freeze_status()
    assert fs["harness_version"] == HARNESS_VERSION
    assert fs["pipeline"] == list(PIPELINE)
    assert fs["densify"] is False
    assert fs["order_execution"] is False
    assert dict(NEXTDAY_LOOKAHEAD_POLICY)["no_feature_lookahead"] is True


def test_mass_research_still_hard_reject():
    """Harness must not bypass mass fail-closed gate."""
    with pytest.raises(MassResearchDisabledError):
        start_mass_research(budget=None, readiness=None)


def _ast_imports_and_calls(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
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
    return imported, called


def test_eval_harness_ast_bans_mass_ready_orders():
    """T7: harness module must not import/call mass, READY mint, or orders."""
    for path in (EVAL_HARNESS_PATH, SINGLE_SHOT_PATH):
        imported, called = _ast_imports_and_calls(path)
        src = path.read_text(encoding="utf-8")
        assert "agents" not in imported, path.name
        assert "mass_research" not in imported, path.name
        assert "start_mass_research" not in imported, path.name
        assert "require_mass_research_start" not in imported, path.name
        assert "VerifiedResearchReadiness" not in imported, path.name
        assert "ResearchReadinessService" not in imported, path.name
        assert "OrderIntent" not in imported, path.name
        assert "paper_service" not in imported, path.name
        assert "start_mass_research" not in called, path.name
        assert "place_order" not in called, path.name
        assert "submit_order" not in called, path.name
        assert "mint_ready" not in called, path.name
        assert "MASS_RESEARCH_ENABLE" not in src
        assert "PHASE7_ENABLE" not in src
        assert 'MASS_RESEARCH_STATUS: str = "GO"' not in src
        assert 'PHASE7_STATUS: str = "ON"' not in src
        assert "READY_DECLARED: bool = True" not in src
        assert "ORDER_EXECUTION: bool = True" not in src


def test_eval_harness_source_freeze_literals():
    src = EVAL_HARNESS_PATH.read_text(encoding="utf-8")
    assert "MASS_RESEARCH" in src
    assert "NO-GO" in src
    assert "ORDER_EXECUTION: bool = False" in src
    assert "CONNECTED_TO_MASS_RESEARCH_LOOP: bool = False" in src
    assert "DENSIFY: bool = False" in src
    assert "研究用・未宣言" in src
    assert "小サンプル" in src or "NEXTDAY_RESEARCH_LABEL" in src
    assert "os.environ" not in src
    assert "MASS_RESEARCH_ENABLE" not in src
    assert "PHASE7_ENABLE" not in src
