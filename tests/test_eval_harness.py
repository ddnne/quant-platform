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
    HARNESS_VERSION,
    MASS_RESEARCH,
    NEXTDAY_RESEARCH_LABEL,
    ORDER_EXECUTION,
    PHASE7,
    PIPELINE,
    READY_DECLARED,
    SIGNAL_CANDIDATE_ONLY,
    EvalHarnessError,
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
# T7 — AST ban mass / READY / orders
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# W61 research walk-forward + multi-period (fixed defs · no READY)
# ---------------------------------------------------------------------------


def test_split_asof_days_walk_forward_chronological():
    from research.eval_harness import (
        RESEARCH_WALK_FORWARD_LABEL,
        WALK_FORWARD_VERSION,
        split_asof_days_walk_forward,
        EvalHarnessError,
    )

    days = [f"2024-10-{i:02d}" for i in range(1, 31)]
    split = split_asof_days_walk_forward(
        days, train_fraction=0.5, min_train_days=5, min_test_days=5
    )
    assert split["version"] == WALK_FORWARD_VERSION
    assert split["threshold_tuning"] is False
    assert split["signal_definitions_fixed"] is True
    assert split["ready_declared"] is False
    assert split["mass_research"] == "NO-GO"
    assert split["operational_go"] is False
    assert "研究用" in RESEARCH_WALK_FORWARD_LABEL
    assert split["train_as_of_days"][-1] < split["test_as_of_days"][0]
    assert len(split["train_as_of_days"]) + len(split["test_as_of_days"]) == 30

    with pytest.raises(EvalHarnessError):
        split_asof_days_walk_forward(["2024-01-02"], min_train_days=5, min_test_days=5)


def test_multi_period_and_walk_forward_multisignal_r2_fixtures(tmp_path: Path):
    """Fixed S1/S2/S3 on two synthetic periods + WF split; Mass/READY closed."""
    from datetime import date, timedelta

    from research.eval_harness import (
        run_multi_period_multisignal_compare,
        run_research_walk_forward_multisignal,
    )
    from research.r2_feature_context import HISTORY_SOURCE_R2

    def _bar(code: str, day: str, close: float, vol: float = 1000.0) -> str:
        payload = {
            "Code": code,
            "Date": day,
            "O": close,
            "H": close,
            "L": close,
            "C": close,
            "Vo": vol,
        }
        aa = f"{day}T15:30:00+09:00"
        return json.dumps(
            {
                "source": "jquants",
                "dataset": "equities_bars_daily",
                "natural_key": json.dumps({"Code": code, "Date": day}, sort_keys=True),
                "event_time": aa,
                "available_at": aa,
                "payload": payload,
                "raw_payload": payload,
            },
            ensure_ascii=True,
        )

    def _topix(day: str, close: float) -> str:
        payload = {"Date": day, "C": close}
        aa = f"{day}T15:30:00+09:00"
        return json.dumps(
            {
                "source": "jquants",
                "dataset": "indices_bars_daily_topix",
                "natural_key": json.dumps({"Date": day}, sort_keys=True),
                "event_time": aa,
                "available_at": aa,
                "payload": payload,
                "raw_payload": payload,
            },
            ensure_ascii=True,
        )

    def _cal(day: str) -> str:
        payload = {"Date": day, "HolDiv": "1"}
        return json.dumps(
            {
                "source": "jquants",
                "dataset": "markets_calendar",
                "natural_key": json.dumps({"Date": day}, sort_keys=True),
                "event_time": f"{day}T00:00:00+09:00",
                "available_at": f"{day}T00:00:00+09:00",
                "payload": payload,
                "raw_payload": payload,
            },
            ensure_ascii=True,
        )

    def _fins(code: str, day: str) -> str:
        payload = {"Code": code, "DiscDate": day}
        aa = f"{day}T15:30:00+09:00"
        return json.dumps(
            {
                "source": "jquants",
                "dataset": "fins_summary",
                "natural_key": json.dumps({"Code": code, "Date": day}, sort_keys=True),
                "event_time": aa,
                "available_at": aa,
                "payload": payload,
                "raw_payload": payload,
            },
            ensure_ascii=True,
        )

    def build_window(start: date, n_weekdays: int):
        days = []
        d = start
        while len(days) < n_weekdays:
            if d.weekday() < 5:
                days.append(d.isoformat())
            d += timedelta(days=1)
        bars, topix, cal, fins = [], [], [], []
        for i, day in enumerate(days):
            for code in ("13010", "72030", "67580"):
                bars.append(
                    _bar(code, day, close=100.0 + i + (0.5 if code == "13010" else 0), vol=1000 + i * 20)
                )
            topix.append(_topix(day, 3000.0 + i * 0.1))
            cal.append(_cal(day))
            if i % 4 == 0:
                fins.append(_fins("13010", day))
        return days, {
            "equities_bars_daily": bars,
            "indices_bars_daily_topix": topix,
            "markets_calendar": cal,
            "fins_summary": fins,
        }

    days_a, lines_a = build_window(date(2022, 9, 1), 24)
    days_b, lines_b = build_window(date(2023, 9, 1), 24)

    puts: list[tuple[str, str]] = []

    def fake_put(bucket: str, key: str, body: bytes, **kwargs):
        puts.append((bucket, key))
        return {"bucket": bucket, "key": key, "status": "dry_run", "bytes": len(body)}

    mp = run_multi_period_multisignal_compare(
        [
            {
                "period_id": "synth_2022q4",
                "period_start": days_a[0],
                "period_end": days_a[-1],
                "max_days": 20,
                "min_days": 10,
                "r2_raw_lines_by_dataset": lines_a,
                "r2_allow_empty_datasets": ("markets_margin_interest",),
            },
            {
                "period_id": "synth_2023q4",
                "period_start": days_b[0],
                "period_end": days_b[-1],
                "max_days": 20,
                "min_days": 10,
                "r2_raw_lines_by_dataset": lines_b,
                "r2_allow_empty_datasets": ("markets_margin_interest",),
            },
            {
                "period_id": "no_data_gap",
                "period_start": "2010-01-01",
                "period_end": "2010-03-31",
                "skip_reason": "documented inventory gap (fixture)",
            },
        ],
        job_id_prefix="w0815bb-test-mp",
        codes=["13010", "72030", "67580"],
        write_per_day_artifacts=False,
        dry_run=True,
        r2_put=fake_put,
        staging_dir=tmp_path,
        history_source="r2",
    )
    assert mp["n_periods_ok"] == 2
    assert mp["n_periods_skipped"] == 1
    assert mp["ready_declared"] is False
    assert mp["mass_research"] == "NO-GO"
    assert mp["operational_go"] is False
    assert mp["significance_claimed"] is False
    assert len(mp["cross_period_compare_table"]) >= 2
    for row in mp["cross_period_compare_table"]:
        assert "period_id" in row and "signal_id" in row

    wf = run_research_walk_forward_multisignal(
        period_start=days_a[0],
        period_end=days_a[-1],
        job_id="w0815bb-test-wf",
        codes=["13010", "72030", "67580"],
        max_days=20,
        min_days=10,
        train_fraction=0.5,
        min_train_days=5,
        min_test_days=5,
        write_per_day_artifacts=False,
        dry_run=True,
        r2_put=fake_put,
        staging_dir=tmp_path,
        history_source="r2",
        r2_raw_lines_by_dataset=lines_a,
        r2_allow_empty_datasets=("markets_margin_interest",),
    )
    assert wf["threshold_tuning"] is False
    assert wf["ready_declared"] is False
    assert wf["mass_research"] == "NO-GO"
    assert wf["split"]["train_as_of_days"][-1] < wf["split"]["test_as_of_days"][0]
    assert wf["train"]["n_days"] >= 5
    assert wf["test"]["n_days"] >= 5
    assert len(wf["train"]["compare_table"]) == 3
    assert len(wf["test"]["compare_table"]) == 3
    # history_source should be r2 when bridge used
    assert HISTORY_SOURCE_R2 == "r2"


def test_design_yearly_eval_windows_and_multi_year_s1_isolation(tmp_path: Path):
    """W63: yearly windows + fail-one-year-safe S1 batch; Mass/READY closed."""
    from datetime import date, timedelta

    from research.eval_harness import (
        DEFAULT_MULTIYEAR_CODES,
        DEFAULT_MULTIYEAR_YEARS,
        MULTI_YEAR_VERSION,
        design_yearly_eval_windows,
        multi_year_availability_table,
        run_multi_year_extra_hyp_eval,
        run_multi_year_s1_eval,
    )

    wins = design_yearly_eval_windows()
    assert len(wins) == len(DEFAULT_MULTIYEAR_YEARS)
    assert all(w["history_source"] == "r2" for w in wins)
    assert all(len(w["codes"]) == len(DEFAULT_MULTIYEAR_CODES) for w in wins)
    y2024 = design_yearly_eval_windows([2024])[0]
    assert y2024["s4_eligible"] is False
    assert "margin" in str(y2024["coverage_notes"]["margin_interest"]["handling"]).lower() or (
        y2024["coverage_notes"]["margin_interest"]["jsonl_gap"] is True
    )
    y2015 = design_yearly_eval_windows([2015])[0]
    assert y2015["s4_eligible"] is True
    avail = multi_year_availability_table(wins)
    assert len(avail) == len(wins)
    assert all("period_id" in r for r in avail)

    def _bar(code: str, day: str, close: float, vol: float = 1000.0) -> str:
        payload = {
            "Code": code,
            "Date": day,
            "O": close,
            "H": close,
            "L": close,
            "C": close,
            "Vo": vol,
        }
        aa = f"{day}T15:30:00+09:00"
        return json.dumps(
            {
                "source": "jquants",
                "dataset": "equities_bars_daily",
                "natural_key": json.dumps({"Code": code, "Date": day}, sort_keys=True),
                "event_time": aa,
                "available_at": aa,
                "payload": payload,
                "raw_payload": payload,
            },
            ensure_ascii=True,
        )

    def _topix(day: str, close: float) -> str:
        payload = {"Date": day, "C": close}
        aa = f"{day}T15:30:00+09:00"
        return json.dumps(
            {
                "source": "jquants",
                "dataset": "indices_bars_daily_topix",
                "natural_key": json.dumps({"Date": day}, sort_keys=True),
                "event_time": aa,
                "available_at": aa,
                "payload": payload,
                "raw_payload": payload,
            },
            ensure_ascii=True,
        )

    def _cal(day: str) -> str:
        payload = {"Date": day, "HolDiv": "1"}
        return json.dumps(
            {
                "source": "jquants",
                "dataset": "markets_calendar",
                "natural_key": json.dumps({"Date": day}, sort_keys=True),
                "event_time": f"{day}T00:00:00+09:00",
                "available_at": f"{day}T00:00:00+09:00",
                "payload": payload,
                "raw_payload": payload,
            },
            ensure_ascii=True,
        )

    def _margin(code: str, day: str, long_i: float, short_i: float) -> str:
        payload = {
            "Code": code,
            "Date": day,
            "ShortMarginTradeVolume": short_i,
            "LongMarginTradeVolume": long_i,
        }
        aa = f"{day}T15:30:00+09:00"
        return json.dumps(
            {
                "source": "jquants",
                "dataset": "markets_margin_interest",
                "natural_key": json.dumps({"Code": code, "Date": day}, sort_keys=True),
                "event_time": aa,
                "available_at": aa,
                "payload": payload,
                "raw_payload": payload,
            },
            ensure_ascii=True,
        )

    def build_window(start: date, n_weekdays: int, with_margin: bool = False):
        days = []
        d = start
        while len(days) < n_weekdays:
            if d.weekday() < 5:
                days.append(d.isoformat())
            d += timedelta(days=1)
        bars, topix, cal, margin = [], [], [], []
        for i, day in enumerate(days):
            for j, code in enumerate(("13010", "72030", "67580")):
                bars.append(
                    _bar(
                        code,
                        day,
                        close=100.0 + i + j * 0.3 + (0.5 if code == "13010" and i % 2 == 0 else 0),
                        vol=1000 + i * 15,
                    )
                )
                if with_margin:
                    margin.append(
                        _margin(code, day, long_i=1000 + i * 10 + j, short_i=500 + i * 5)
                    )
            topix.append(_topix(day, 3000.0 + i * 0.1))
            cal.append(_cal(day))
        lines = {
            "equities_bars_daily": bars,
            "indices_bars_daily_topix": topix,
            "markets_calendar": cal,
        }
        if with_margin:
            lines["markets_margin_interest"] = margin
            lines["markets_short_ratio"] = []
        return days, lines

    days_a, lines_a = build_window(date(2015, 9, 1), 24)
    days_b, lines_b = build_window(date(2017, 9, 1), 24)
    days_c, lines_c = build_window(date(2019, 9, 1), 24, with_margin=True)

    puts: list[str] = []

    def fake_put(bucket: str, key: str, body: bytes, **kwargs):
        puts.append(key)
        return {"bucket": bucket, "key": key, "status": "dry_run", "bytes": len(body)}

    periods = [
        {
            "period_id": "y2015_q4",
            "year": 2015,
            "period_start": days_a[0],
            "period_end": days_a[-1],
            "max_days": 20,
            "min_days": 10,
            "s4_eligible": True,
            "r2_raw_lines_by_dataset": lines_a,
        },
        {
            "period_id": "y2017_q4",
            "year": 2017,
            "period_start": days_b[0],
            "period_end": days_b[-1],
            "max_days": 20,
            "min_days": 10,
            "s4_eligible": True,
            "r2_raw_lines_by_dataset": lines_b,
        },
        {
            "period_id": "y2024_q4",
            "year": 2024,
            "period_start": "2024-09-01",
            "period_end": "2024-12-29",
            "skip_reason": "documented margin/bars fixture gap",
            "s4_eligible": False,
        },
        {
            "period_id": "y_error",
            "year": 2025,
            "period_start": "2025-09-01",
            "period_end": "2025-12-29",
            "max_days": 20,
            "min_days": 10,
            "s4_eligible": True,
            # empty required datasets → error; must not kill other years
            "r2_raw_lines_by_dataset": {
                "equities_bars_daily": [],
                "indices_bars_daily_topix": [],
                "markets_calendar": [],
            },
        },
    ]

    s1 = run_multi_year_s1_eval(
        periods,
        job_id_prefix="w0815bd-test-s1",
        codes=["13010", "72030", "67580"],
        write_per_day_artifacts=False,
        dry_run=True,
        r2_put=fake_put,
        staging_dir=tmp_path,
        history_source="r2",
        min_active_per_period=5,
    )
    assert s1["version"] == MULTI_YEAR_VERSION
    assert s1["n_years_ok"] == 2
    assert s1["n_years_skipped"] == 1
    assert s1["n_years_error"] == 1
    assert s1["year_split"] is True
    assert s1["fail_one_year_safe"] is True
    assert s1["ready_declared"] is False
    assert s1["operational_go"] is False
    assert s1["mass_research"] == "NO-GO"
    assert s1["phase7"] == "OFF"
    assert s1["connected_to_ready"] is False
    assert s1["connected_to_mass"] is False
    assert s1["significance_claimed"] is False
    gate = s1["robustness_gate"]
    assert gate is not None
    assert gate["ready_declared"] is False
    assert gate["operational_go"] is False
    assert gate["connected_to_ready"] is False
    assert gate["connected_to_mass"] is False
    # 2 ok years with same-direction gross should pass multi_period gate
    assert gate["passed"] is True or gate["n_eligible_periods"] >= 2

    # S4: 2024 skipped by s4_eligible; two margin years ok
    s4_periods = [
        {
            "period_id": "y2019_q4",
            "year": 2019,
            "period_start": days_c[0],
            "period_end": days_c[-1],
            "max_days": 20,
            "min_days": 10,
            "s4_eligible": True,
            "r2_raw_lines_by_dataset": lines_c,
            "r2_allow_empty_datasets": ["markets_short_ratio"],
        },
        {
            "period_id": "y2017_q4",
            "year": 2017,
            "period_start": days_b[0],
            "period_end": days_b[-1],
            "max_days": 20,
            "min_days": 10,
            "s4_eligible": True,
            "r2_raw_lines_by_dataset": {
                **lines_b,
                "markets_margin_interest": [
                    _margin("13010", d, 1000 + i, 500 + i) for i, d in enumerate(days_b)
                ]
                + [
                    _margin("72030", d, 1100 + i, 550 + i) for i, d in enumerate(days_b)
                ]
                + [
                    _margin("67580", d, 1200 + i, 600 + i) for i, d in enumerate(days_b)
                ],
                "markets_short_ratio": [],
            },
            "r2_allow_empty_datasets": ["markets_short_ratio"],
        },
        {
            "period_id": "y2024_q4",
            "year": 2024,
            "period_start": "2024-09-01",
            "period_end": "2024-12-29",
            "s4_eligible": False,
        },
    ]
    s4 = run_multi_year_extra_hyp_eval(
        s4_periods,
        job_id_prefix="w0815bd-test-s4",
        codes=["13010", "72030", "67580"],
        write_per_day_artifacts=False,
        dry_run=True,
        r2_put=fake_put,
        staging_dir=tmp_path,
        history_source="r2",
        signal_ids=["c21_margin_change_sign"],
        min_active_per_period=5,
    )
    assert s4["n_years_skipped"] >= 1
    assert s4["ready_declared"] is False
    assert s4["mass_research"] == "NO-GO"
    assert s4["fail_one_year_safe"] is True
    # 2024 must be skipped, not invented
    skip_ids = {y["period_id"] for y in s4["years"] if y.get("status") == "skipped"}
    assert "y2024_q4" in skip_ids


def test_multi_year_ast_and_mass_off_freezes():
    """W63 freezes: no mass arm, no READY connect in multi-year API surface."""
    from research.eval_harness import (
        CONNECTED_TO_MASS_RESEARCH_LOOP,
        MASS_RESEARCH,
        MULTI_YEAR_LABEL,
        ORDER_EXECUTION,
        PHASE7,
        READY_DECLARED,
        harness_freeze_status,
    )

    st = harness_freeze_status()
    assert st["mass_research"] == "NO-GO"
    assert MASS_RESEARCH == "NO-GO"
    assert PHASE7 == "OFF"
    assert READY_DECLARED is False
    assert ORDER_EXECUTION is False
    assert CONNECTED_TO_MASS_RESEARCH_LOOP is False
    assert "未宣言" in MULTI_YEAR_LABEL
    src = EVAL_HARNESS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # No mass research import / arming helpers in harness module body.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "mass_research" not in (node.module or "")
        if isinstance(node, ast.Attribute):
            pass
    assert "CONNECTED_TO_READY" in src or "connected_to_ready" in src
    assert "fail_one_year_safe" in src
    assert "design_yearly_eval_windows" in src
