"""COMPLETE 21 min features + feature-pipeline permanent DEFER guard (W49 T6–T7)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import features
from data_contracts import PermanentDeferHistoryError, PERMANENT_DEFER_DATASETS
from features import (
    COMPLETE_21_DATASETS,
    compute,
    filter_feature_datasets,
    get,
    list_features,
    require_feature_dataset,
    require_feature_datasets,
)
from features.complete21_min import (
    disclosure_flag_from_count,
    simple_return_from_closes,
    topix_relative_from_returns,
    volume_change_from_pairs,
)
from features.runtime import FeatureContext

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from _coreseed import CODES, close_iso, seed_db


# ---------------------------------------------------------------------------
# T7 — dataset guard / DEFER exclusion
# ---------------------------------------------------------------------------

def test_complete_21_count_and_no_overlap_with_defer():
    assert len(COMPLETE_21_DATASETS) == 21
    assert COMPLETE_21_DATASETS.isdisjoint(PERMANENT_DEFER_DATASETS)
    assert "equities_bars_daily" in COMPLETE_21_DATASETS
    assert "equities_master" not in COMPLETE_21_DATASETS


def test_require_feature_dataset_rejects_all_permanent_defer():
    for ds in sorted(PERMANENT_DEFER_DATASETS):
        with pytest.raises(PermanentDeferHistoryError):
            require_feature_dataset(ds, context="test")
    assert require_feature_dataset("equities_bars_daily") == "equities_bars_daily"


def test_require_feature_datasets_and_filter():
    require_feature_datasets(["equities_bars_daily", "fins_summary"])
    with pytest.raises(PermanentDeferHistoryError, match="PD-MX-EARN-TIP"):
        require_feature_datasets(
            ["equities_bars_daily", "fins_earnings_date"],
            context="feature test",
        )
    assert filter_feature_datasets(
        ["equities_bars_daily", "equities_master", "markets_calendar"]
    ) == ["equities_bars_daily", "markets_calendar"]


def test_feature_context_jquants_records_rejects_defer():
    def _never_read(resource, kwargs):
        raise AssertionError(f"PIT read must not run for DEFER: {resource} {kwargs}")

    ctx = FeatureContext(
        as_of="2026-08-01T15:30:00+09:00",
        _input_values={},
        _pit_reader=_never_read,
    )
    with pytest.raises(PermanentDeferHistoryError, match="PD-D4-BARS-AM"):
        ctx.get_jquants_records(dataset="equities_bars_daily_am")
    with pytest.raises(PermanentDeferHistoryError, match="PD-D2-MASTER"):
        ctx.get_equity_master()


def test_feature_context_jquants_records_allows_complete_dataset():
    calls: list[tuple[str, dict]] = []

    def _reader(resource, kwargs):
        calls.append((resource, dict(kwargs)))
        return SimpleNamespace(rows=[])

    ctx = FeatureContext(
        as_of="2026-08-01T15:30:00+09:00",
        _input_values={},
        _pit_reader=_reader,
    )
    ctx.get_jquants_records(dataset="fins_summary", code="8697")
    assert calls == [
        ("jquants_records", {"dataset": "fins_summary", "code": "8697"})
    ]
    ctx.get_equity_bars_daily(code="8697")
    assert calls[-1][0] == "equity_bars_daily"


# ---------------------------------------------------------------------------
# T6 — pure helpers (data-free)
# ---------------------------------------------------------------------------

def test_volume_change_from_pairs_data_free():
    value, meta = volume_change_from_pairs(
        [("2025-04-01", 1000.0), ("2025-04-02", 1500.0)]
    )
    assert value == pytest.approx(0.5)
    assert meta["prior_volume"] == 1000.0
    assert meta["last_volume"] == 1500.0

    none_v, none_m = volume_change_from_pairs([("2025-04-01", 10.0)])
    assert none_v is None
    assert "insufficient" in none_m["reason"]

    zero_v, zero_m = volume_change_from_pairs(
        [("2025-04-01", 0.0), ("2025-04-02", 10.0)]
    )
    assert zero_v is None
    assert "zero prior" in zero_m["reason"]


def test_topix_relative_and_disclosure_helpers_data_free():
    eq, _ = simple_return_from_closes(
        [("2025-04-01", 100.0), ("2025-04-02", 110.0)]
    )
    tx, _ = simple_return_from_closes(
        [("2025-04-01", 2000.0), ("2025-04-02", 2020.0)]
    )
    rel, meta = topix_relative_from_returns(eq, tx)
    assert eq == pytest.approx(0.10)
    assert tx == pytest.approx(0.01)
    assert rel == pytest.approx(0.09)
    assert meta["equity_ret"] == pytest.approx(0.10)

    missing, m2 = topix_relative_from_returns(0.1, None)
    assert missing is None
    assert "missing" in m2["reason"]

    flag, fmeta = disclosure_flag_from_count(3)
    assert flag == 1.0
    assert fmeta["rows_seen"] == 3
    flag0, _ = disclosure_flag_from_count(0)
    assert flag0 == 0.0


# ---------------------------------------------------------------------------
# T6 — registered features + simple computation on seeded bars
# ---------------------------------------------------------------------------

def test_complete21_min_features_registered():
    ids = {f.id for f in list_features()}
    assert {
        "volume_change_1d",
        "topix_relative_1d",
        "disclosure_flag_fins",
    }.issubset(ids)
    for fid in ("volume_change_1d", "topix_relative_1d", "disclosure_flag_fins"):
        feat = get(fid)
        assert feat.status == "candidate"
        assert "complete21" in feat.tags


def test_volume_change_1d_on_seeded_bars(tmp_path):
    """Seed volumes are constant 1000 → change 0.0 with >=2 sessions."""
    days = ["2025-04-01", "2025-04-02", "2025-04-03"]
    prices = {CODES[0]: {d: 100.0 + i for i, d in enumerate(days)}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "volume_change_1d",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx(0.0)
    assert out.metadata["feature_id"] == "volume_change_1d"
    assert out.metadata["datasets"] == ["equities_bars_daily"]
    assert out.metadata["rows_seen"] >= 2


def test_volume_change_1d_insufficient_history(tmp_path):
    day = "2025-04-01"
    db = seed_db(
        tmp_path,
        days=[day],
        prices={CODES[0]: {day: 100.0}},
    )
    out = compute(
        "volume_change_1d",
        as_of=close_iso(day),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is None
    assert "insufficient" in out.metadata["reason"]


def test_topix_relative_1d_rejects_if_internal_datasets_were_defer(monkeypatch):
    """Feature preflight uses require_feature_datasets — DEFER list must fail closed."""
    from features import complete21_min as mod

    with pytest.raises(PermanentDeferHistoryError):
        # Direct call of the guard with a poisoned list (simulates misdeclaration).
        require_feature_datasets(
            ["equities_bars_daily", "equities_bars_daily_am"],
            context="feature topix_relative_1d",
        )
    # Module constant must stay COMPLETE-only.
    for ds in mod._TOPIX_REL_DATASETS:
        assert ds in COMPLETE_21_DATASETS
        assert ds not in PERMANENT_DEFER_DATASETS


def test_disclosure_flag_fins_empty_db_is_zero(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    prices = {CODES[0]: {d: 100.0 for d in days}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "disclosure_flag_fins",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    # No fins_summary rows in coreseed → flag 0.0
    assert out.value == 0.0
    assert out.metadata["rows_seen"] == 0
    assert out.metadata["datasets"] == ["fins_summary"]


def test_v0_return_1d_still_works_with_guard(tmp_path):
    """Pipeline DEFER guard must not break existing COMPLETE bars features."""
    days = ["2025-04-01", "2025-04-02", "2025-04-03"]
    prices = {CODES[0]: {d: 100.0 + i for i, d in enumerate(days)}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "return_1d",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx((102.0 - 101.0) / 101.0)
