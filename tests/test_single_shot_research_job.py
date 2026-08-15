"""T8 single-shot job + T9 Phase7/Mass OFF freeze + W50 execute/DEFER + W51 features."""

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
from research.single_shot_job import (
    COMPLETE_21_DATASETS,
    COMPLETE_21_DATASET_SET,
    DEFAULT_CANDIDATE_FEATURES,
    DEFAULT_SIGNAL_ID,
    MASS_RESEARCH_ENV_ARMING_SWITCHES,
    MASS_RESEARCH_STATUS,
    PHASE7_ENV_ARMING_SWITCHES,
    PHASE7_STATUS,
    READY_DECLARED,
    READY_PUBLICATION_STATUS,
    RESEARCH_ARTIFACT_BUCKET,
    RESEARCH_ARTIFACT_PREFIX,
    SIGNAL_CANDIDATE_ONLY,
    SingleShotJobError,
    assert_mass_and_phase7_off,
    build_single_shot_job_spec,
    build_tip_feature_context,
    compute_tip_candidate_features,
    design_artifact_paths,
    execute_single_shot_job,
    extract_d1_tip_feature_rows,
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
MINIMAL_SIGNAL_PATH = (
    REPO_ROOT / "packages" / "research_runtime" / "features" / "minimal_signal.py"
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


def test_extract_d1_tip_feature_rows_rejects_defer():
    with pytest.raises(PermanentDeferHistoryError):
        extract_d1_tip_feature_rows(
            ["equities_master"],
            period_start="2026-08-01",
            period_end="2026-08-15",
            d1_execute=lambda sql: (_ for _ in ()).throw(AssertionError("no d1")),
        )


def test_tip_feature_context_and_candidate_compute():
    """W51: tip FeatureContext (not local SoT) computes candidate features."""
    tip_rows = {
        "equities_bars_daily": [
            {
                "code": "13010",
                "date": "2026-08-03",
                "volume": 100.0,
                "close": 100.0,
                "available_at": "2026-08-03T15:30:00+09:00",
                "event_time": "2026-08-03T09:00:00+09:00",
            },
            {
                "code": "13010",
                "date": "2026-08-04",
                "volume": 150.0,
                "close": 110.0,
                "available_at": "2026-08-04T15:30:00+09:00",
                "event_time": "2026-08-04T09:00:00+09:00",
            },
        ],
        "markets_calendar": [
            {
                "date": "2026-08-03",
                "holiday_division": "1",
                "available_at": "2026-08-03T09:00:00+09:00",
                "event_time": "2026-08-03T09:00:00+09:00",
            },
            {
                "date": "2026-08-04",
                "holiday_division": "1",
                "available_at": "2026-08-04T09:00:00+09:00",
                "event_time": "2026-08-04T09:00:00+09:00",
            },
        ],
        "indices_bars_daily_topix": [
            {
                "date": "2026-08-03",
                "close": 3000.0,
                "available_at": "2026-08-03T15:30:00+09:00",
                "event_time": "2026-08-03T09:00:00+09:00",
                "payload": {"Date": "2026-08-03", "C": 3000.0},
            },
            {
                "date": "2026-08-04",
                "close": 3030.0,
                "available_at": "2026-08-04T15:30:00+09:00",
                "event_time": "2026-08-04T09:00:00+09:00",
                "payload": {"Date": "2026-08-04", "C": 3030.0},
            },
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
    assert result["ready_declared"] is False
    assert result["local_sot"] is False
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
    """W51 T1/T3: execute path computes candidates + manifest feature_id/version/row_counts."""

    def fake_d1(sql: str):
        s = sql
        # COUNT queries
        if "COUNT(*)" in s and "payload" not in s.lower():
            if "equities_bars_daily" in s and "LIKE" in s:
                return [{"n": 2}]
            if "equities_bars_daily" in s:
                return [
                    {
                        "n": 2,
                        "min_event_time": "2026-08-03T09:00:00+09:00",
                        "max_event_time": "2026-08-04T09:00:00+09:00",
                    }
                ]
            if "markets_calendar" in s:
                return [
                    {
                        "n": 2,
                        "min_event_time": "2026-08-03",
                        "max_event_time": "2026-08-04",
                    }
                ]
            if "indices_bars_daily_topix" in s:
                return [
                    {
                        "n": 2,
                        "min_event_time": "2026-08-03",
                        "max_event_time": "2026-08-04",
                    }
                ]
            return [{"n": 0}]
        # natural_key discovery samples
        if "SELECT natural_key FROM" in s:
            return [
                {"natural_key": json.dumps({"Code": "13010", "Date": "2026-08-03"})},
                {"natural_key": json.dumps({"Code": "13010", "Date": "2026-08-04"})},
            ]
        # payload extracts
        if "payload" in s and "equities_bars_daily" in s:
            return [
                {
                    "natural_key": json.dumps({"Code": "13010", "Date": "2026-08-03"}),
                    "event_time": "2026-08-03T09:00:00+09:00",
                    "available_at": "2026-08-03T15:30:00+09:00",
                    "payload": json.dumps(
                        {"Code": "13010", "Date": "2026-08-03", "C": 100, "Vo": 100}
                    ),
                },
                {
                    "natural_key": json.dumps({"Code": "13010", "Date": "2026-08-04"}),
                    "event_time": "2026-08-04T09:00:00+09:00",
                    "available_at": "2026-08-04T15:30:00+09:00",
                    "payload": json.dumps(
                        {"Code": "13010", "Date": "2026-08-04", "C": 110, "Vo": 150}
                    ),
                },
            ]
        if "payload" in s and "markets_calendar" in s:
            return [
                {
                    "natural_key": json.dumps({"Date": "2026-08-03"}),
                    "event_time": "2026-08-03T09:00:00+09:00",
                    "available_at": "2026-08-03T09:00:00+09:00",
                    "payload": json.dumps({"Date": "2026-08-03", "HolDiv": "1"}),
                },
                {
                    "natural_key": json.dumps({"Date": "2026-08-04"}),
                    "event_time": "2026-08-04T09:00:00+09:00",
                    "available_at": "2026-08-04T09:00:00+09:00",
                    "payload": json.dumps({"Date": "2026-08-04", "HolDiv": "1"}),
                },
            ]
        if "payload" in s and "indices_bars_daily_topix" in s:
            return [
                {
                    "natural_key": json.dumps({"Date": "2026-08-03"}),
                    "event_time": "2026-08-03T09:00:00+09:00",
                    "available_at": "2026-08-03T15:30:00+09:00",
                    "payload": json.dumps({"Date": "2026-08-03", "C": 3000.0}),
                },
                {
                    "natural_key": json.dumps({"Date": "2026-08-04"}),
                    "event_time": "2026-08-04T09:00:00+09:00",
                    "available_at": "2026-08-04T15:30:00+09:00",
                    "payload": json.dumps({"Date": "2026-08-04", "C": 3030.0}),
                },
            ]
        # summary sample rows (no payload)
        if "equities_bars_daily" in s:
            return [
                {
                    "natural_key": json.dumps({"Code": "13010", "Date": "2026-08-03"}),
                    "event_time": "2026-08-03T09:00:00+09:00",
                    "available_at": "2026-08-03T15:30:00+09:00",
                }
            ]
        return [
            {
                "natural_key": json.dumps({"Date": "2026-08-03"}),
                "event_time": "2026-08-03",
                "available_at": "2026-08-03",
            }
        ]

    puts: dict[str, bytes] = {}

    def fake_put(bucket: str, key: str, body: bytes):
        puts[key] = body
        return {"bucket": bucket, "key": key, "bytes": len(body), "status": "injected"}

    ex = execute_single_shot_job(
        dataset_ids=[
            "equities_bars_daily",
            "markets_calendar",
            "indices_bars_daily_topix",
        ],
        period_start="2026-08-01",
        period_end="2026-08-15",
        job_id="w0815ar-unit-feat",
        dry_run=True,
        compute_features=True,
        feature_codes=["13010"],
        d1_execute=fake_d1,
        r2_put=fake_put,
        staging_dir=tmp_path,
    )
    assert ex.ready_declared is False
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
    manifest = json.loads(puts[ex.manifest_r2_key].decode("utf-8"))
    assert manifest["compute_features"] is True
    assert "features" in manifest
    for block in manifest["features"]:
        assert "feature_id" in block
        assert "version" in block
        assert "row_counts" in block
        assert "null_counts" in block
    feat_body = json.loads(puts[ex.features_r2_key].decode("utf-8"))
    # W53: default tip set is all approved (volume/calendar/topix)
    assert feat_body["status"] in ("mixed", "approved", "candidate")
    assert feat_body["ready_declared"] is False
    assert feat_body["local_sot"] is False
    by_fid = {b["feature_id"]: b for b in feat_body["features"]}
    assert by_fid["volume_change_1d"]["status"] == "approved"
    assert by_fid["is_trading_day"]["status"] == "approved"
    assert by_fid["topix_relative_1d"]["status"] == "approved"


def test_execute_features_rejects_defer_before_d1():
    calls: list[str] = []

    def boom_d1(sql: str):
        calls.append(sql)
        raise AssertionError("d1 must not be called for permanent DEFER input")

    with pytest.raises(PermanentDeferHistoryError):
        execute_single_shot_job(
            dataset_ids=["equities_bars_daily_am"],
            period_start="2026-08-01",
            period_end="2026-08-15",
            job_id="defer-feat",
            dry_run=True,
            compute_features=True,
            d1_execute=boom_d1,
        )
    assert calls == []


# ---------------------------------------------------------------------------
# W52 / T5–T7 — minimal signal (candidate_only) + R2 signals path
# ---------------------------------------------------------------------------


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
    assert long["metadata"]["order_execution"] is False
    assert long["metadata"]["ready_declared"] is False

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
    """W52 T6 unit: compute_signals → R2 signals key + candidate_only metadata."""

    def fake_d1(sql: str):
        s = sql.lower()
        if "count(*)" in s:
            return [
                {
                    "n": 4,
                    "min_event_time": "2026-08-01",
                    "max_event_time": "2026-08-04",
                }
            ]
        if "payload" in s and "equities_bars_daily" in s:
            return [
                {
                    "natural_key": json.dumps({"Code": "13010", "Date": "2026-08-01"}),
                    "event_time": "2026-08-01T09:00:00+09:00",
                    "available_at": "2026-08-01T15:30:00+09:00",
                    "payload": json.dumps(
                        {"Code": "13010", "Date": "2026-08-01", "C": 1000.0, "Vo": 100.0}
                    ),
                },
                {
                    "natural_key": json.dumps({"Code": "13010", "Date": "2026-08-04"}),
                    "event_time": "2026-08-04T09:00:00+09:00",
                    "available_at": "2026-08-04T15:30:00+09:00",
                    "payload": json.dumps(
                        {"Code": "13010", "Date": "2026-08-04", "C": 1020.0, "Vo": 150.0}
                    ),
                },
            ]
        if "payload" in s and "indices_bars_daily_topix" in s:
            return [
                {
                    "natural_key": json.dumps({"Date": "2026-08-01"}),
                    "event_time": "2026-08-01T09:00:00+09:00",
                    "available_at": "2026-08-01T15:30:00+09:00",
                    "payload": json.dumps({"Date": "2026-08-01", "C": 3000.0}),
                },
                {
                    "natural_key": json.dumps({"Date": "2026-08-04"}),
                    "event_time": "2026-08-04T09:00:00+09:00",
                    "available_at": "2026-08-04T15:30:00+09:00",
                    "payload": json.dumps({"Date": "2026-08-04", "C": 3010.0}),
                },
            ]
        if "payload" in s and "markets_calendar" in s:
            return [
                {
                    "natural_key": json.dumps({"Date": "2026-08-04"}),
                    "event_time": "2026-08-04",
                    "available_at": "2026-08-04T00:00:00+09:00",
                    "payload": json.dumps(
                        {"Date": "2026-08-04", "HolidayDivision": "1"}
                    ),
                }
            ]
        if "equities_bars_daily" in s:
            return [
                {
                    "natural_key": json.dumps({"Code": "13010", "Date": "2026-08-04"}),
                    "event_time": "2026-08-04T09:00:00+09:00",
                    "available_at": "2026-08-04T15:30:00+09:00",
                }
            ]
        return [
            {
                "natural_key": json.dumps({"Date": "2026-08-04"}),
                "event_time": "2026-08-04",
                "available_at": "2026-08-04",
            }
        ]

    puts: dict[str, bytes] = {}

    def fake_put(bucket: str, key: str, body: bytes):
        puts[key] = body
        return {"bucket": bucket, "key": key, "bytes": len(body), "status": "injected"}

    ex = execute_single_shot_job(
        dataset_ids=[
            "equities_bars_daily",
            "markets_calendar",
            "indices_bars_daily_topix",
        ],
        period_start="2026-08-01",
        period_end="2026-08-15",
        job_id="w0815as-unit-signal",
        dry_run=True,
        compute_signals=True,
        feature_codes=["13010"],
        d1_execute=fake_d1,
        r2_put=fake_put,
        staging_dir=tmp_path,
    )
    assert ex.ready_declared is False
    assert ex.mass_research == "NO-GO"
    assert ex.phase7 == "OFF"
    assert ex.signals_r2_key is not None
    assert ex.signals_r2_key.startswith(
        "research/single_shot/job=w0815as-unit-signal/signals/"
    )
    assert ex.features_r2_key is not None
    assert ex.signal_result is not None
    assert ex.signal_result["signal_id"] == DEFAULT_SIGNAL_ID
    assert ex.signal_result["candidate_only"] is False
    assert SIGNAL_CANDIDATE_ONLY is False
    assert ex.signal_result["order_execution"] is False
    assert ex.signal_result["ready_declared"] is False
    # 5 puts: input_plan, result, features, signals, manifest
    assert len(puts) == 5
    assert ex.signals_r2_key in puts
    manifest = json.loads(puts[ex.manifest_r2_key].decode("utf-8"))
    assert manifest["compute_signals"] is True
    assert manifest["order_execution"] is False
    assert manifest["signal"]["signal_id"] == DEFAULT_SIGNAL_ID
    assert manifest["signal"]["candidate_only"] is False
    assert "signals" in manifest["keys"]
    sig_body = json.loads(puts[ex.signals_r2_key].decode("utf-8"))
    assert sig_body["signal_id"] == DEFAULT_SIGNAL_ID
    assert sig_body["candidate_only"] is False
    assert sig_body["order_execution"] is False
    assert sig_body["local_sot"] is False
    # equity +2% vs topix +0.33% → positive relative → long
    assert any(o.get("value") == 1.0 for o in sig_body.get("observations") or [])


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


def test_single_shot_module_does_not_import_mass_research_loop():
    """AST guard: skeleton must not call into agents.mass_research."""
    imported, called = _ast_imports_and_calls(SINGLE_SHOT_PATH)
    assert "agents" not in imported
    assert "mass_research" not in imported
    assert "start_mass_research" not in imported
    assert "require_mass_research_start" not in imported
    assert "VerifiedResearchReadiness" not in imported
    assert "start_mass_research" not in called
    assert "require_mass_research_start" not in called


def test_t7_signal_and_single_shot_no_mass_ready_or_orders():
    """W52 T7: hard AST/comment — no mass import, no READY mint, no order exec."""
    for path in (SINGLE_SHOT_PATH, MINIMAL_SIGNAL_PATH):
        imported, called = _ast_imports_and_calls(path)
        src = path.read_text(encoding="utf-8")
        assert "agents" not in imported, path.name
        assert "mass_research" not in imported, path.name
        assert "start_mass_research" not in imported, path.name
        assert "require_mass_research_start" not in imported, path.name
        assert "VerifiedResearchReadiness" not in imported, path.name
        assert "ResearchReadinessService" not in imported, path.name
        # No order / paper execution surface.
        assert "OrderIntent" not in imported, path.name
        assert "paper_service" not in imported, path.name
        assert "execution" not in imported, path.name
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


def test_no_phase7_or_mass_env_arming_switches_in_skeleton_source():
    src = SINGLE_SHOT_PATH.read_text(encoding="utf-8")
    # Must not define or enable arming flags.
    assert "MASS_RESEARCH_ENABLE" not in src
    assert "os.environ" not in src
    assert "PHASE7_ENABLE" not in src
    assert 'PHASE7_STATUS: str = "ON"' not in src
    assert 'MASS_RESEARCH_STATUS: str = "GO"' not in src
    assert "order_execution" in src  # freeze field must remain False
    assert "ORDER_EXECUTION" not in src or "ORDER_EXECUTION: bool = True" not in src
