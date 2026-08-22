"""Eval harness: approved-leg signal → multiday → nextday → R2.

COMPLETE 21 + approved legs; AST/freezes ban mass / READY / orders.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from agents.mass_research import start_mass_research
from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
)
from tests.research_eval_util import (
    _assert_mass_ready_off,
    _capture_puts,
    _injected_multiday,
    assert_ast_bans_mass_ready_orders,
)
from research.eval_harness import (
    APPROVED_SIGNAL_LEGS,
    COMPLETE_21_DATASET_SET,
    DEFAULT_SIGNAL_DATASETS,
    DEFAULT_SIGNAL_ID,
    HARNESS_VERSION,
    NEXTDAY_RESEARCH_LABEL,
    PIPELINE,
    SIGNAL_CANDIDATE_ONLY,
    EvalHarnessError,
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
EVAL_HARNESS_MULTIYEAR_PATH = (
    REPO_ROOT / "packages" / "product" / "research" / "eval_harness_multiyear.py"
)
SINGLE_SHOT_PATH = (
    REPO_ROOT / "packages" / "product" / "research" / "single_shot_job.py"
)
HARNESS_AST_PATHS = (
    EVAL_HARNESS_PATH,
    EVAL_HARNESS_MULTIYEAR_PATH,
    SINGLE_SHOT_PATH,
)

_CODES = ("13010", "72030", "67580")


def _r2_jsonl(
    dataset: str,
    day: str,
    payload: dict,
    *,
    code: str | None = None,
    aa_time: str = "15:30:00",
) -> str:
    nk: dict = {"Date": day}
    if code is not None:
        nk["Code"] = code
    aa = f"{day}T{aa_time}+09:00"
    return json.dumps(
        {
            "source": "jquants",
            "dataset": dataset,
            "natural_key": json.dumps(nk, sort_keys=True),
            "event_time": aa,
            "available_at": aa,
            "payload": payload,
            "raw_payload": payload,
        },
        ensure_ascii=True,
    )


def _weekdays(start: date, n: int) -> list[str]:
    days: list[str] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def _synth_window(
    start: date,
    n_weekdays: int,
    *,
    with_fins: bool = False,
    with_margin: bool = False,
    close_fn=None,
    vol_fn=None,
):
    days = _weekdays(start, n_weekdays)
    bars, topix, cal, fins, margin = [], [], [], [], []
    for i, day in enumerate(days):
        for j, code in enumerate(_CODES):
            close = (
                close_fn(i, j, code)
                if close_fn
                else 100.0 + i + (0.5 if code == "13010" else 0)
            )
            vol = vol_fn(i) if vol_fn else 1000 + i * 20
            bars.append(
                _r2_jsonl(
                    "equities_bars_daily",
                    day,
                    {"Code": code, "Date": day, "O": close, "H": close, "L": close, "C": close, "Vo": vol},
                    code=code,
                )
            )
            if with_margin:
                margin.append(
                    _r2_jsonl(
                        "markets_margin_interest",
                        day,
                        {
                            "Code": code,
                            "Date": day,
                            "ShortMarginTradeVolume": 500 + i * 5,
                            "LongMarginTradeVolume": 1000 + i * 10 + j,
                        },
                        code=code,
                    )
                )
        topix.append(_r2_jsonl("indices_bars_daily_topix", day, {"Date": day, "C": 3000.0 + i * 0.1}))
        cal.append(
            _r2_jsonl(
                "markets_calendar",
                day,
                {"Date": day, "HolDiv": "1"},
                aa_time="00:00:00",
            )
        )
        if with_fins and i % 4 == 0:
            fins.append(
                _r2_jsonl("fins_summary", day, {"Code": "13010", "DiscDate": day}, code="13010")
            )
    lines = {
        "equities_bars_daily": bars,
        "indices_bars_daily_topix": topix,
        "markets_calendar": cal,
    }
    if with_fins:
        lines["fins_summary"] = fins
    if with_margin:
        lines["markets_margin_interest"] = margin
        lines["markets_short_ratio"] = []
    return days, lines


def _r2_period(
    period_id: str,
    days: list[str],
    lines: dict,
    *,
    year: int | None = None,
    s4_eligible: bool | None = None,
    allow_empty=(),
    extra=None,
):
    row = {
        "period_id": period_id,
        "period_start": days[0],
        "period_end": days[-1],
        "max_days": 20,
        "min_days": 10,
        "r2_raw_lines_by_dataset": lines,
    }
    if year is not None:
        row["year"] = year
    if s4_eligible is not None:
        row["s4_eligible"] = s4_eligible
    if allow_empty:
        row["r2_allow_empty_datasets"] = list(allow_empty)
    if extra:
        row.update(extra)
    return row


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
    puts, kw = _injected_multiday(
        tmp_path, job_id="w0815aw-g2-harness-unit", n_asof=6
    )
    result = run_nextday_return_eval(**kw)

    assert result.attach_nextday_returns is True
    assert result.n_days == 6
    _assert_mass_ready_off(result)
    assert result.phase7 == "OFF"
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
    puts, kw = _injected_multiday(tmp_path, job_id="w0815aw-g2-full-alias", n_asof=5)
    result = run_full_pipeline(**kw)
    assert result.attach_nextday_returns is True
    assert result.n_days == 5


def test_run_multiday_without_nextday(tmp_path: Path):
    puts, kw = _injected_multiday(
        tmp_path,
        job_id="w0815aw-g2-multiday-only",
        n_asof=5,
        attach_nextday_returns=False,
    )
    result = run_multiday_signal_eval(**kw)
    assert result.attach_nextday_returns is False
    body = json.loads(puts[result.batch_summary_r2_key].decode("utf-8"))
    assert "nextday_return" not in body
    assert body["approved_legs_only"] is True


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


def test_mass_research_still_hard_reject():
    """Harness must not bypass mass fail-closed gate."""
    with pytest.raises(MassResearchDisabledError):
        start_mass_research(budget=None, readiness=None)


def test_eval_harness_ast_bans_mass_ready_orders():
    """T7: harness module must not import/call mass, READY mint, or orders."""
    for path in HARNESS_AST_PATHS:
        assert_ast_bans_mass_ready_orders(path)


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
    from research.eval_harness import (
        run_multi_period_multisignal_compare,
        run_research_walk_forward_multisignal,
    )

    days_a, lines_a = _synth_window(date(2022, 9, 1), 24, with_fins=True)
    days_b, lines_b = _synth_window(date(2023, 9, 1), 24, with_fins=True)
    puts, fake_put = _capture_puts()

    empty_margin = ("markets_margin_interest",)
    mp = run_multi_period_multisignal_compare(
        [
            _r2_period("synth_2022q4", days_a, lines_a, allow_empty=empty_margin),
            _r2_period("synth_2023q4", days_b, lines_b, allow_empty=empty_margin),
            {
                "period_id": "no_data_gap",
                "period_start": "2010-01-01",
                "period_end": "2010-03-31",
                "skip_reason": "documented inventory gap (fixture)",
            },
        ],
        job_id_prefix="w0815bb-test-mp",
        codes=list(_CODES),
        write_per_day_artifacts=False,
        dry_run=True,
        r2_put=fake_put,
        staging_dir=tmp_path,
        history_source="r2",
    )
    assert mp["n_periods_ok"] == 2
    assert mp["n_periods_skipped"] == 1
    _assert_mass_ready_off(mp)
    assert mp["operational_go"] is False
    assert mp["significance_claimed"] is False
    assert len(mp["cross_period_compare_table"]) >= 2
    for row in mp["cross_period_compare_table"]:
        assert "period_id" in row and "signal_id" in row

    wf = run_research_walk_forward_multisignal(
        period_start=days_a[0],
        period_end=days_a[-1],
        job_id="w0815bb-test-wf",
        codes=list(_CODES),
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
        r2_allow_empty_datasets=empty_margin,
    )
    assert wf["threshold_tuning"] is False
    _assert_mass_ready_off(wf)
    assert wf["split"]["train_as_of_days"][-1] < wf["split"]["test_as_of_days"][0]
    assert wf["train"]["n_days"] >= 5
    assert wf["test"]["n_days"] >= 5
    assert len(wf["train"]["compare_table"]) == 3
    assert len(wf["test"]["compare_table"]) == 3


def test_design_yearly_eval_windows_and_multi_year_s1_isolation(tmp_path: Path):
    """Yearly windows + fail-one-year-safe S1 batch; Mass/READY closed."""
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

    def _close(i, j, code):
        return 100.0 + i + j * 0.3 + (0.5 if code == "13010" and i % 2 == 0 else 0)

    days_a, lines_a = _synth_window(date(2015, 9, 1), 24, close_fn=_close, vol_fn=lambda i: 1000 + i * 15)
    days_b, lines_b = _synth_window(date(2017, 9, 1), 24, close_fn=_close, vol_fn=lambda i: 1000 + i * 15)
    days_c, lines_c = _synth_window(
        date(2019, 9, 1), 24, with_margin=True, close_fn=_close, vol_fn=lambda i: 1000 + i * 15
    )

    puts, fake_put = _capture_puts()

    periods = [
        _r2_period("y2015_q4", days_a, lines_a, year=2015, s4_eligible=True),
        _r2_period("y2017_q4", days_b, lines_b, year=2017, s4_eligible=True),
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
        codes=list(_CODES),
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
    _assert_mass_ready_off(s1)
    assert s1["operational_go"] is False
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
    assert gate["passed"] is True or gate["n_eligible_periods"] >= 2

    def _margin_line(code: str, day: str, long_i: float, short_i: float) -> str:
        return _r2_jsonl(
            "markets_margin_interest",
            day,
            {
                "Code": code,
                "Date": day,
                "ShortMarginTradeVolume": short_i,
                "LongMarginTradeVolume": long_i,
            },
            code=code,
        )

    s4_periods = [
        _r2_period(
            "y2019_q4",
            days_c,
            lines_c,
            year=2019,
            s4_eligible=True,
            allow_empty=["markets_short_ratio"],
        ),
        _r2_period(
            "y2017_q4",
            days_b,
            {
                **lines_b,
                "markets_margin_interest": [
                    _margin_line(code, d, base + i, base // 2 + i)
                    for code, base in (("13010", 1000), ("72030", 1100), ("67580", 1200))
                    for i, d in enumerate(days_b)
                ],
                "markets_short_ratio": [],
            },
            year=2017,
            s4_eligible=True,
            allow_empty=["markets_short_ratio"],
        ),
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
        codes=list(_CODES),
        write_per_day_artifacts=False,
        dry_run=True,
        r2_put=fake_put,
        staging_dir=tmp_path,
        history_source="r2",
        signal_ids=["c21_margin_change_sign"],
        min_active_per_period=5,
    )
    assert s4["n_years_skipped"] >= 1
    _assert_mass_ready_off(s4)
    assert s4["fail_one_year_safe"] is True
    skip_ids = {y["period_id"] for y in s4["years"] if y.get("status") == "skipped"}
    assert "y2024_q4" in skip_ids


def test_multi_year_ast_and_mass_off_freezes():
    """No mass arm, no READY connect in multi-year API surface."""
    from research.eval_harness import (
        CONNECTED_TO_MASS_RESEARCH_LOOP,
        MULTI_YEAR_LABEL,
        ORDER_EXECUTION,
        harness_freeze_status,
    )

    st = harness_freeze_status()
    assert st["mass_research"] == "NO-GO"
    assert ORDER_EXECUTION is False
    assert CONNECTED_TO_MASS_RESEARCH_LOOP is False
    assert "未宣言" in MULTI_YEAR_LABEL
    src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (EVAL_HARNESS_PATH, EVAL_HARNESS_MULTIYEAR_PATH)
    )
    for path in (EVAL_HARNESS_PATH, EVAL_HARNESS_MULTIYEAR_PATH):
        assert_ast_bans_mass_ready_orders(path)
    assert "CONNECTED_TO_READY" in src or "connected_to_ready" in src
    assert "fail_one_year_safe" in src
    assert "design_yearly_eval_windows" in src
