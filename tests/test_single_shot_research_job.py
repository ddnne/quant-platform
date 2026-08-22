"""Single-shot job: COMPLETE 21, DEFER reject, features/signals, multiday/nextday.

Phase7/Mass OFF freeze + AST bans stay; no READY mint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.mass_research import start_mass_research
from data_contracts.permanent_defer import (
    PERMANENT_DEFER_DATASETS,
    PermanentDeferHistoryError,
)
from tests.research_eval_util import (
    MINIMAL_SIGNAL_DOCS_PATH,
    MINIMAL_SIGNAL_PATH,
    SINGLE_SHOT_PATH,
    _assert_mass_ready_off,
    _boom_d1,
    _c21_d1_tables,
    _close_index,
    _close_px,
    _injected_multiday,
    _injected_single_shot,
    _put_json,
    _single_shot_kw,
    _tip_bar,
    _tip_cal_row,
    _tip_topix_row,
    assert_ast_bans_mass_ready_orders,
)
from research.single_shot_job import (
    COMPLETE_21_DATASETS,
    COMPLETE_21_DATASET_SET,
    DEFAULT_CANDIDATE_FEATURES,
    DEFAULT_SIGNAL_ID,
    NEXTDAY_LOOKAHEAD_POLICY,
    RESEARCH_ARTIFACT_BUCKET,
    RESEARCH_ARTIFACT_PREFIX,
    SIGNAL_CANDIDATE_ONLY,
    SingleShotJobError,
    attach_next_day_returns,
    build_equity_close_index,
    build_single_shot_job_spec,
    build_tip_feature_context,
    compute_tip_candidate_features,
    design_artifact_paths,
    discover_tip_trading_days,
    execute_multiday_nextday_return_eval,
    execute_multiday_signal_eval,
    execute_single_shot_job,
    extract_d1_tip_feature_rows,
    extract_d1_tip_summaries,
    freeze_status,
    next_trading_day_map,
    require_complete_21_only,
    session_close_as_of,
    summarize_nextday_by_sign,
    summarize_signal_day,
)
from selection.budget_ledger import MassResearchDisabledError, ResearchBudgetCapability
from selection.screen import ExperimentBudget

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


def test_require_complete_21_only_rejects_all_permanent_defer():
    """Every permanent DEFER id fails closed; mixed COMPLETE+DEFER does too."""
    assert len(PERMANENT_DEFER_DATASETS) == 4
    for defer_id in sorted(PERMANENT_DEFER_DATASETS):
        with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER"):
            require_complete_21_only([defer_id])
    with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER|PD-D2-MASTER"):
        require_complete_21_only(["equities_bars_daily", "equities_master"])
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
    assert "{content_hash}" in paths["features_r2_key_template"]
    assert "{content_hash}" in paths["signals_r2_key_template"]
    assert paths["signals_r2_key_template"].startswith(
        "research/single_shot/job=job-demo-1/signals/"
    )
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
    _assert_mass_ready_off(body)
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
    calls, boom_d1 = _boom_d1()
    with pytest.raises(PermanentDeferHistoryError, match="permanent DEFER"):
        execute_single_shot_job(
            **_single_shot_kw(
                job_id="defer-reject-demo",
                dataset_ids=["equities_master", "equities_bars_daily"],
                d1_execute=boom_d1,
            )
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

    puts, kw = _injected_single_shot(
        tmp_path,
        job_id="w0815aq-unit-demo",
        d1_execute=fake_d1,
        dataset_ids=["equities_bars_daily", "markets_calendar"],
    )
    ex = execute_single_shot_job(**kw)
    assert ex.job_id == "w0815aq-unit-demo"
    _assert_mass_ready_off(ex)
    assert ex.content_hash.startswith("sha256:")
    assert ex.result_r2_key.startswith("research/single_shot/job=w0815aq-unit-demo/")
    assert len(puts) == 3
    assert all(b == "quant-structured" for b in kw["r2_put"].buckets)
    assert {ex.manifest_r2_key, ex.input_plan_r2_key, ex.result_r2_key} <= set(puts)
    assert ex.tip_extracts["extracts"]["equities_bars_daily"]["row_count"] == 3
    assert ex.tip_extracts["extracts"]["markets_calendar"]["row_count"] == 2
    _assert_mass_ready_off(ex.to_dict())


def test_extract_d1_tip_summaries_rejects_defer():
    with pytest.raises(PermanentDeferHistoryError):
        extract_d1_tip_summaries(
            ["equities_earnings_calendar"],
            period_start="2026-08-01",
            period_end="2026-08-15",
            d1_execute=_boom_d1()[1],
        )


def test_extract_d1_tip_feature_rows_rejects_defer():
    with pytest.raises(PermanentDeferHistoryError):
        extract_d1_tip_feature_rows(
            ["equities_master"],
            period_start="2026-08-01",
            period_end="2026-08-15",
            d1_execute=_boom_d1()[1],
        )


def test_tip_short_ratio_level_with_section():
    tip_rows = {
        "markets_short_ratio": [
            {
                "date": "2026-08-04",
                "S33": "0050",
                "section": "0050",
                "available_at": "2026-08-04T15:30:00+09:00",
                "event_time": "2026-08-04T09:00:00+09:00",
                "payload": {
                    "Date": "2026-08-04",
                    "S33": "0050",
                    "SellExShortVa": 200.0,
                    "ShrtWithResVa": 40.0,
                    "ShrtNoResVa": 10.0,
                },
            },
            {
                "date": "2026-08-04",
                "S33": "1050",
                "section": "1050",
                "available_at": "2026-08-04T15:30:00+09:00",
                "event_time": "2026-08-04T09:00:00+09:00",
                "payload": {
                    "Date": "2026-08-04",
                    "S33": "1050",
                    "SellExShortVa": 100.0,
                    "ShrtWithResVa": 10.0,
                    "ShrtNoResVa": 0.0,
                },
            },
        ],
    }
    as_of = "2026-08-04T15:30:00+09:00"
    # Explicit sections
    result = compute_tip_candidate_features(
        tip_rows,
        as_of=as_of,
        feature_ids=["short_ratio_level"],
        sections=["0050", "1050"],
    )
    assert result["sections"] == ["0050", "1050"]
    by_id = {f["feature_id"]: f for f in result["features"]}
    block = by_id["short_ratio_level"]
    assert block["row_counts"]["computed"] == 2
    assert block["row_counts"]["non_null"] == 2
    assert block["null_counts"] == 0
    samples = {sv["section"]: sv["value"] for sv in block["sample_values"]}
    assert samples["0050"] == pytest.approx(0.25)  # (40+10)/200
    assert samples["1050"] == pytest.approx(0.10)  # (10+0)/100

    # Auto-discover from tip when sections omitted
    discovered = compute_tip_candidate_features(
        tip_rows,
        as_of=as_of,
        feature_ids=["short_ratio_level"],
    )
    assert "0050" in discovered["sections"]
    assert discovered["features"][0]["row_counts"]["non_null"] >= 1


def test_tip_feature_context_and_candidate_compute():
    tip_rows = {
        "equities_bars_daily": [
            _tip_bar("13010", "2026-08-03", 100.0, 100.0),
            _tip_bar("13010", "2026-08-04", 110.0, 150.0),
        ],
        "markets_calendar": [
            _tip_cal_row(d) for d in ("2026-08-03", "2026-08-04")
        ],
        "indices_bars_daily_topix": [
            _tip_topix_row(d, c)
            for d, c in (("2026-08-03", 3000.0), ("2026-08-04", 3030.0))
        ],
    }
    as_of = "2026-08-04T15:30:00+09:00"
    ctx = build_tip_feature_context(
        tip_rows, as_of=as_of, inputs={"code": "13010"}
    )
    assert ctx.as_of == as_of
    bars = ctx.get_equity_bars_daily(code="13010")
    assert len(bars.rows) == 2
    assert bars.metadata["source"] == "cloudflare_d1_tip"

    result = compute_tip_candidate_features(
        tip_rows,
        as_of=as_of,
        feature_ids=DEFAULT_CANDIDATE_FEATURES,
        codes=["13010"],
        dates=["2026-08-03", "2026-08-04"],
    )
    by_id = {f["feature_id"]: f for f in result["features"]}
    assert set(by_id) == set(DEFAULT_CANDIDATE_FEATURES)
    # volume: (150-100)/100 = 0.5
    vol = by_id["volume_change_1d"]
    assert vol["version"] == "1.0.0"
    assert vol["row_counts"]["computed"] == 1
    assert vol["null_counts"] == 0
    assert vol["sample_values"][0]["value"] == pytest.approx(0.5)
    # calendar trading days
    cal = by_id["is_trading_day"]
    assert cal["row_counts"]["computed"] == 2
    assert cal["null_counts"] == 0
    assert all(sv["value"] == 1.0 for sv in cal["sample_values"])
    # topix relative: equity ret 0.10 - topix ret 0.01 = 0.09
    rel = by_id["topix_relative_1d"]
    assert rel["row_counts"]["computed"] == 1
    assert rel["null_counts"] == 0
    assert rel["sample_values"][0]["value"] == pytest.approx(0.09)


def test_execute_with_features_writes_manifest_feature_stats(tmp_path: Path):
    puts, kw = _injected_single_shot(
        tmp_path,
        job_id="w0815ar-unit-feat",
        tables=_c21_d1_tables(
            bars=(("2026-08-03", 100, 100), ("2026-08-04", 110, 150)),
            topix=(("2026-08-03", 3000.0), ("2026-08-04", 3030.0)),
            cal_days=("2026-08-03", "2026-08-04"),
            hol_key="HolDiv",
            cal_aa="T09:00:00+09:00",
        ),
        compute_features=True,
        feature_codes=["13010"],
    )
    ex = execute_single_shot_job(**kw)
    _assert_mass_ready_off(ex)
    assert ex.features_r2_key is not None
    assert ex.features_r2_key.startswith(
        "research/single_shot/job=w0815ar-unit-feat/features/"
    )
    assert ex.feature_result is not None
    assert set(ex.feature_result["feature_ids"]) == set(DEFAULT_CANDIDATE_FEATURES)
    # 4 puts: input_plan, result, features, manifest
    assert len(puts) == 4
    assert ex.manifest_r2_key in puts
    assert ex.features_r2_key in puts
    manifest = _put_json(puts, ex.manifest_r2_key)
    assert manifest["compute_features"] is True
    assert "features" in manifest
    for block in manifest["features"]:
        assert "feature_id" in block
        assert "version" in block
        assert "row_counts" in block
        assert "null_counts" in block
    feat_body = _put_json(puts, ex.features_r2_key)
    assert feat_body["status"] in ("mixed", "approved", "candidate")
    assert feat_body["ready_declared"] is False
    assert feat_body.get("local_sot") is False
    by_fid = {b["feature_id"]: b for b in feat_body["features"]}
    assert by_fid["volume_change_1d"]["status"] == "approved"
    assert by_fid["is_trading_day"]["status"] == "approved"
    assert by_fid["topix_relative_1d"]["status"] == "approved"


def test_execute_features_rejects_defer_before_d1():
    calls, boom_d1 = _boom_d1()
    with pytest.raises(PermanentDeferHistoryError):
        execute_single_shot_job(
            **_single_shot_kw(
                job_id="defer-feat",
                dataset_ids=["equities_bars_daily_am"],
                compute_features=True,
                d1_execute=boom_d1,
            )
        )
    assert calls == []


def test_minimal_signal_pure_helpers():
    from features.minimal_signal import (
        compute_topix_relative_sign_signal,
        sign_from_topix_relative,
    )

    assert sign_from_topix_relative(0.01) == 1.0
    assert sign_from_topix_relative(-0.02) == -1.0
    assert sign_from_topix_relative(0.0) == 0.0
    assert sign_from_topix_relative(None) is None

    long = compute_topix_relative_sign_signal(
        topix_relative=0.005, is_trading_day=1.0, code="13010"
    )
    assert long["value"] == 1.0
    assert long["signal_id"] == DEFAULT_SIGNAL_ID
    assert long["candidate_only"] is False
    _assert_mass_ready_off(long["metadata"])

    non_td = compute_topix_relative_sign_signal(
        topix_relative=0.005, is_trading_day=0.0, code="13010"
    )
    assert non_td["value"] is None

    gated = compute_topix_relative_sign_signal(
        topix_relative=0.005,
        is_trading_day=1.0,
        volume_change=0.01,
        volume_change_abs_min=0.05,
        code="13010",
    )
    assert gated["value"] is None  # |0.01| < 0.05


def test_execute_compute_signals_writes_signals_artifact(tmp_path: Path):
    puts, kw = _injected_single_shot(
        tmp_path,
        job_id="w0815as-unit-signal",
        tables=_c21_d1_tables(
            bars=(("2026-08-01", 1000.0, 100.0), ("2026-08-04", 1020.0, 150.0)),
            topix=(("2026-08-01", 3000.0), ("2026-08-04", 3010.0)),
            cal_days=("2026-08-04",),
            cal_event_time=True,
        ),
        compute_signals=True,
        feature_codes=["13010"],
    )
    ex = execute_single_shot_job(**kw)
    _assert_mass_ready_off(ex)
    assert ex.signals_r2_key is not None
    assert ex.signals_r2_key.startswith(
        "research/single_shot/job=w0815as-unit-signal/signals/"
    )
    assert ex.features_r2_key is not None
    assert ex.signal_result is not None
    assert ex.signal_result["signal_id"] == DEFAULT_SIGNAL_ID
    assert ex.signal_result["candidate_only"] is False
    assert SIGNAL_CANDIDATE_ONLY is False
    _assert_mass_ready_off(ex.signal_result)
    # 5 puts: input_plan, result, features, signals, manifest
    assert len(puts) == 5
    assert ex.signals_r2_key in puts
    manifest = _put_json(puts, ex.manifest_r2_key)
    assert manifest["compute_signals"] is True
    assert manifest["order_execution"] is False
    assert manifest["signal"]["signal_id"] == DEFAULT_SIGNAL_ID
    assert manifest["signal"]["candidate_only"] is False
    assert "signals" in manifest["keys"]
    sig_body = _put_json(puts, ex.signals_r2_key)
    assert sig_body["signal_id"] == DEFAULT_SIGNAL_ID
    assert sig_body["candidate_only"] is False
    assert sig_body["order_execution"] is False
    assert sig_body["local_sot"] is False
    # equity +2% vs topix +0.33% → positive relative → long
    assert any(o.get("value") == 1.0 for o in sig_body.get("observations") or [])


def test_freeze_status_matches_constants():
    status = freeze_status()
    assert status["complete_21_count"] == 21
    assert status["permanent_defer_count"] == 4
    assert status["artifact_bucket"] == "quant-structured"
    _assert_mass_ready_off(status)


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


def test_t7_signal_and_single_shot_no_mass_ready_or_orders():
    """Hard AST/comment — no mass import, no READY mint, no order exec."""
    for path in (SINGLE_SHOT_PATH, MINIMAL_SIGNAL_PATH, MINIMAL_SIGNAL_DOCS_PATH):
        assert_ast_bans_mass_ready_orders(path, extra_banned_imports=("execution",))


def test_no_phase7_or_mass_env_arming_switches_in_skeleton_source():
    src = assert_ast_bans_mass_ready_orders(
        SINGLE_SHOT_PATH, extra_banned_imports=("execution",)
    )
    assert "os.environ" not in src
    assert "order_execution" in src


def test_discover_tip_trading_days_filters_non_trading():
    tip = {
        "markets_calendar": [
            {"date": "2026-08-07", "holiday_division": "1"},
            {"date": "2026-08-08", "holiday_division": "0"},
            {"date": "2026-08-10", "holiday_division": "1"},
        ]
    }
    days = discover_tip_trading_days(tip, period_start="2026-08-01", period_end="2026-08-14")
    assert days == ["2026-08-07", "2026-08-10"]


def test_summarize_signal_day_sign_distribution():
    payload = {
        "signal_id": DEFAULT_SIGNAL_ID,
        "candidate_only": False,
        "row_counts": {
            "computed": 3,
            "non_null": 2,
            "null": 1,
            "long": 1,
            "short": 1,
            "flat": 0,
        },
        "sample_values": [{"code": "13010", "value": 1.0}],
    }
    s = summarize_signal_day(payload, as_of="2026-08-07T15:30:00+09:00")
    assert s["signal_count"] == 3
    assert s["non_null"] == 2
    assert abs(s["non_null_rate"] - 2 / 3) < 1e-9
    assert s["sign_distribution"] == {"+1": 1, "0": 0, "-1": 1, "null": 1}
    _assert_mass_ready_off(s)


def test_execute_multiday_signal_eval_batch_summary(tmp_path: Path):
    puts, kw = _injected_multiday(tmp_path, job_id="w0815au-g1-multiday-unit")
    eval_result = execute_multiday_signal_eval(**kw)

    assert eval_result.n_days == 7
    _assert_mass_ready_off(eval_result)
    assert eval_result.batch_summary_r2_key == (
        "research/single_shot/job=w0815au-g1-multiday-unit/batch_summary.json"
    )
    assert eval_result.batch_summary_r2_key in puts
    body = _put_json(puts, eval_result.batch_summary_r2_key)
    assert body["n_days"] == 7
    assert body["candidate_only"] is False
    assert body["approved_legs_only"] is True
    assert body["signal_id"] == DEFAULT_SIGNAL_ID
    _assert_mass_ready_off(body)
    assert "aggregate" in body
    assert "sign_distribution" in body["aggregate"]
    assert len(body["per_day"]) == 7
    # Per-day artifacts + batch_summary + manifest
    day_keys = [k for k in puts if "/days/date=" in k and k.endswith("/signals.json")]
    assert len(day_keys) == 7
    assert any(k.endswith("/manifest.json") for k in puts)
    # Each day has signal_count / non_null_rate / sign_distribution
    for day in body["per_day"]:
        assert "signal_count" in day
        assert "non_null_rate" in day
        assert set(day["sign_distribution"].keys()) == {"+1", "0", "-1", "null"}
    # Aggregate non-null should be positive with synthetic rising bars vs topix.
    assert body["aggregate"]["signal_count"] >= 7
    assert SIGNAL_CANDIDATE_ONLY is False


def test_multiday_reject_permanent_defer_before_d1():
    """Multiday uses DEFAULT_SIGNAL_DATASETS only; DEFER never enters the path."""
    # If a caller tried to force DEFER via wrong datasets, require_complete_21_only
    # still fail-closes — exercise via discover/require surface.
    with pytest.raises((SingleShotJobError, PermanentDeferHistoryError)):
        require_complete_21_only(
            ["equities_master"], context="multiday signal eval datasets"
        )


def test_nextday_lookahead_policy_documented():
    p = dict(NEXTDAY_LOOKAHEAD_POLICY)
    assert p["no_feature_lookahead"] is True
    assert p["feature_as_of"] == "signal_day_T_session_close"
    assert p["evaluation_as_of"] == "next_trading_day_T1_session_close"
    assert "close(T+1)/close(T)" in p["return_definition"]
    _assert_mass_ready_off(p)
    assert p["label"] == "小サンプル / 研究用・未宣言"
    assert session_close_as_of("2026-08-07") == "2026-08-07T15:30:00+09:00"


def test_build_equity_close_index_and_next_trading_day_map():
    tip = {
        "equities_bars_daily": [
            {"code": "13010", "date": "2026-08-06", **_close_px("2026-08-06", 100.0)},
            {"code": "13010", "date": "2026-08-07", **_close_px("2026-08-07", 110.0)},
        ]
    }
    idx = build_equity_close_index(tip)
    assert idx[("13010", "2026-08-06")]["close"] == 100.0
    assert next_trading_day_map(["2026-08-07", "2026-08-06", "2026-08-10"]) == {
        "2026-08-06": "2026-08-07",
        "2026-08-07": "2026-08-10",
        "2026-08-10": None,
    }


def test_attach_next_day_returns_pit_and_formula():
    close_index = _close_index(
        ("13010", "2026-08-06", 100.0),
        ("13010", "2026-08-07", 105.0),
        ("72030", "2026-08-06", 200.0),
        # 72030 missing T+1 → null return
    )
    obs = [
        {"code": "13010", "value": 1.0},
        {"code": "72030", "value": -1.0},
    ]
    aligned = attach_next_day_returns(
        obs,
        signal_date="2026-08-06",
        next_date="2026-08-07",
        close_index=close_index,
        # evaluation_as_of = T+1 close (research convention)
        evaluation_as_of="2026-08-07T15:30:00+09:00",
        feature_as_of="2026-08-06T15:30:00+09:00",
    )
    assert aligned[0]["next_day_return"] == pytest.approx(0.05)
    assert aligned[0]["feature_as_of"] == "2026-08-06T15:30:00+09:00"
    assert aligned[0]["evaluation_as_of"] == "2026-08-07T15:30:00+09:00"
    assert aligned[0]["next_day_return_pit_ok"] is True
    assert aligned[1]["next_day_return"] is None
    assert aligned[1]["next_day_return_null_reason"] == "missing_close_T1"

    # PIT fail: T+1 bar available_at after evaluation_as_of → null (no look-ahead)
    late = _close_index(
        ("13010", "2026-08-06", 100.0),
        ("13010", "2026-08-07", 105.0, "2026-08-08T00:00:00+09:00"),
    )
    pit_fail = attach_next_day_returns(
        [{"code": "13010", "value": 1.0}],
        signal_date="2026-08-06",
        next_date="2026-08-07",
        close_index=late,
        evaluation_as_of="2026-08-07T15:30:00+09:00",
    )
    assert pit_fail[0]["next_day_return"] is None
    assert pit_fail[0]["next_day_return_null_reason"] == "pit_fail_T1"

    # No next trading day → null
    edge = attach_next_day_returns(
        [{"code": "13010", "value": 1.0}],
        signal_date="2026-08-12",
        next_date=None,
        close_index=close_index,
    )
    assert edge[0]["next_day_return"] is None
    assert edge[0]["next_day_return_null_reason"] == "no_next_trading_day"


def test_summarize_nextday_by_sign_means_and_null_rates():
    rows = [
        {"value": 1.0, "next_day_return": 0.02},
        {"value": 1.0, "next_day_return": 0.04},
        {"value": 1.0, "next_day_return": 0.06},
        {"value": -1.0, "next_day_return": -0.01},
        {"value": -1.0, "next_day_return": None},
        {"value": 0.0, "next_day_return": 0.0},
        {"value": None, "next_day_return": 0.10},
    ]
    s = summarize_nextday_by_sign(rows)
    assert s["label"] == "小サンプル / 研究用・未宣言"
    _assert_mass_ready_off(s)
    assert s["by_sign"]["+1"]["count"] == 3
    assert s["by_sign"]["+1"]["mean_next_day_return"] == pytest.approx(0.04)
    assert s["by_sign"]["+1"]["median_next_day_return"] == pytest.approx(0.04)
    assert s["by_sign"]["+1"]["null_return_count"] == 0
    assert s["by_sign"]["-1"]["count"] == 2
    assert s["by_sign"]["-1"]["null_return_count"] == 1
    assert s["by_sign"]["-1"]["null_return_rate"] == pytest.approx(0.5)
    assert s["by_sign"]["-1"]["mean_next_day_return"] == pytest.approx(-0.01)
    assert s["by_sign"]["-1"]["median_next_day_return"] == pytest.approx(-0.01)
    assert s["by_sign"]["0"]["mean_next_day_return"] == pytest.approx(0.0)
    assert s["by_sign"]["0"]["median_next_day_return"] == pytest.approx(0.0)
    assert s["by_sign"]["null_signal"]["count"] == 1
    assert "look_ahead_policy" in s
    assert s["look_ahead_policy"]["no_feature_lookahead"] is True
    assert "median_next_day_return" in s["overall"]


def test_execute_multiday_nextday_return_eval_batch(tmp_path: Path):
    puts, kw = _injected_multiday(
        tmp_path, job_id="w0815av-g1-nextday-unit", n_asof=6
    )
    eval_result = execute_multiday_nextday_return_eval(**kw)

    assert eval_result.attach_nextday_returns is True
    assert eval_result.n_days == 6
    _assert_mass_ready_off(eval_result)
    assert eval_result.batch_summary_r2_key == (
        "research/single_shot/job=w0815av-g1-nextday-unit/batch_summary.json"
    )
    assert eval_result.batch_summary_r2_key in puts
    body = _put_json(puts, eval_result.batch_summary_r2_key)
    assert body["attach_nextday_returns"] is True
    assert body["label"] == "小サンプル / 研究用・未宣言"
    _assert_mass_ready_off(body)
    assert "nextday_return" in body
    nr = body["nextday_return"]
    assert nr["label"] == "小サンプル / 研究用・未宣言"
    assert set(nr["by_sign"].keys()) == {"+1", "0", "-1", "null_signal"}
    # Synthetic rising bars → non-null next-day returns for days with T+1.
    assert nr["overall"]["non_null_return_count"] >= 1
    assert "median_next_day_return" in nr["overall"]
    assert nr["look_ahead_policy"]["no_feature_lookahead"] is True
    # Per-day: feature_as_of is T close; evaluation_as_of is T+1 close when present.
    for day in body["per_day"]:
        d = day["date"]
        assert day["feature_as_of"] == f"{d}T15:30:00+09:00"
        if day.get("next_day_date"):
            assert day["evaluation_as_of"] == (
                f"{day['next_day_date']}T15:30:00+09:00"
            )
        # Sample carries next_day_return field when attached.
        for sample in day.get("sample_values") or []:
            assert "next_day_return" in sample
    # R2 path prefix for this job.
    assert body["artifact"]["batch_summary_r2_key"].startswith(
        "research/single_shot/job=w0815av-g1-nextday-unit/"
    )
    day_keys = [k for k in puts if "/days/date=" in k and k.endswith("/signals.json")]
    assert len(day_keys) == 6


def test_nextday_flag_off_preserves_w54_shape(tmp_path: Path):
    """attach_nextday_returns=False keeps batch shape (no nextday_return)."""
    puts, kw = _injected_multiday(
        tmp_path,
        job_id="w0815au-g1-multiday-unit-compat",
        n_asof=5,
        attach_nextday_returns=False,
    )
    eval_result = execute_multiday_signal_eval(**kw)
    assert eval_result.attach_nextday_returns is False
    body = _put_json(puts, eval_result.batch_summary_r2_key)
    assert "nextday_return" not in body
    assert body["version"] == "multiday-signal-batch/v1"
