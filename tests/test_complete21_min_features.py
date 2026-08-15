"""COMPLETE 21 min features + feature-pipeline permanent DEFER guard (W49–W50 T5–T7)."""

from __future__ import annotations

import json
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
    is_trading_day_from_division,
    margin_interest_change_from_pairs,
    repo_rate_level_from_rows,
    short_ratio_level_from_components,
    simple_return_from_closes,
    topix_relative_from_returns,
    volume_change_from_pairs,
)
from features.runtime import FeatureContext
from storage.sqlite_store import SqliteStore

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from _coreseed import CODES, close_iso, seed_db


COMPLETE21_MIN_IDS = (
    "volume_change_1d",
    "topix_relative_1d",
    "disclosure_flag_fins",
    "margin_interest_change_1d",
    "short_ratio_level",
    "is_trading_day",
    "repo_rate_level",
)


def _upsert_jquants_records(
    db_path: Path,
    *,
    dataset: str,
    payloads: list[dict],
    available_at: str | None = None,
) -> None:
    """Seed generic catalog rows for complete21 feature tests."""
    store = SqliteStore(db_path)
    rows = []
    for p in payloads:
        # Prefer Date/Code natural keys when present; else compact payload key.
        nk_obj: dict = {}
        if "Code" in p or "code" in p:
            nk_obj["Code"] = str(p.get("Code") or p.get("code"))
        if "Date" in p or "date" in p:
            nk_obj["Date"] = str(p.get("Date") or p.get("date"))[:10]
        if "S33" in p:
            nk_obj["S33"] = str(p["S33"])
        if not nk_obj:
            nk_obj = {"_row": json.dumps(p, sort_keys=True, separators=(",", ":"))}
        d = nk_obj.get("Date") or "2025-04-01"
        avail = available_at or close_iso(d)
        rows.append(
            {
                "source": "jquants",
                "dataset": dataset,
                "natural_key": json.dumps(nk_obj, sort_keys=True, separators=(",", ":")),
                "event_time": f"{d}T00:00:00+09:00",
                "available_at": avail,
                "ingested_at": avail,
                "payload": json.dumps(p, ensure_ascii=False),
                "raw_payload": json.dumps(p, ensure_ascii=False),
            }
        )
    store.upsert("jquants_records", rows)
    store.close()


def _upsert_repo_rates(
    db_path: Path,
    rows: list[dict],
) -> None:
    store = SqliteStore(db_path)
    store.upsert("jsda_repo_rates", rows)
    store.close()


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


def test_feature_context_jsda_repo_rates_guard_and_read():
    calls: list[tuple[str, dict]] = []

    def _reader(resource, kwargs):
        calls.append((resource, dict(kwargs)))
        return SimpleNamespace(rows=[])

    ctx = FeatureContext(
        as_of="2026-08-01T15:30:00+09:00",
        _input_values={},
        _pit_reader=_reader,
    )
    ctx.get_jsda_repo_rates(tenor="overnight")
    assert calls == [("jsda_repo_rates", {"tenor": "overnight"})]


def test_new_feature_dataset_constants_are_complete_only():
    """Every complete21_min declared dataset must be COMPLETE 21, never DEFER."""
    from features import complete21_min as mod

    constants = (
        mod._VOLUME_DATASETS,
        mod._TOPIX_REL_DATASETS,
        mod._DISC_DATASETS,
        mod._MARGIN_DATASETS,
        mod._SHORT_RATIO_DATASETS,
        mod._CALENDAR_DATASETS,
        mod._REPO_DATASETS,
    )
    for group in constants:
        for ds in group:
            assert ds in COMPLETE_21_DATASETS, ds
            assert ds not in PERMANENT_DEFER_DATASETS, ds


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


def test_margin_interest_change_helper_data_free():
    value, meta = margin_interest_change_from_pairs(
        [("2025-04-01", 100.0), ("2025-04-08", 120.0)]
    )
    assert value == pytest.approx(0.20)
    assert meta["prior_margin"] == 100.0
    assert meta["last_margin"] == 120.0

    none_v, none_m = margin_interest_change_from_pairs([("2025-04-01", 10.0)])
    assert none_v is None
    assert "insufficient" in none_m["reason"]

    zero_v, zero_m = margin_interest_change_from_pairs(
        [("2025-04-01", 0.0), ("2025-04-08", 10.0)]
    )
    assert zero_v is None
    assert "zero prior" in zero_m["reason"]


def test_short_ratio_level_helper_data_free():
    ratio, meta = short_ratio_level_from_components(40.0, 10.0, 200.0)
    assert ratio == pytest.approx(0.25)
    assert meta["sell_ex_short"] == 200.0

    none_v, none_m = short_ratio_level_from_components(1.0, 2.0, 0.0)
    assert none_v is None
    assert "denominator" in none_m["reason"]

    # Missing short legs treated as zero numerator.
    ratio0, _ = short_ratio_level_from_components(None, None, 100.0)
    assert ratio0 == pytest.approx(0.0)


def test_is_trading_day_helper_data_free():
    yes, m1 = is_trading_day_from_division("1")
    assert yes == 1.0
    no, m2 = is_trading_day_from_division("0")
    assert no == 0.0
    miss, m3 = is_trading_day_from_division(None)
    assert miss is None
    assert "no calendar" in m3["reason"]


def test_repo_rate_level_helper_data_free():
    rate, meta = repo_rate_level_from_rows(
        [
            {"as_of_date": "2025-04-01", "rate": 0.10, "tenor": "overnight"},
            {"as_of_date": "2025-04-02", "rate": 0.12, "tenor": "overnight"},
        ]
    )
    assert rate == pytest.approx(0.12)
    assert meta["as_of_date"] == "2025-04-02"

    none_v, none_m = repo_rate_level_from_rows([])
    assert none_v is None
    assert "no repo" in none_m["reason"]


# ---------------------------------------------------------------------------
# T5/T6 — registered features + computation
# ---------------------------------------------------------------------------

def test_complete21_min_features_registered():
    ids = {f.id for f in list_features()}
    assert set(COMPLETE21_MIN_IDS).issubset(ids)
    for fid in COMPLETE21_MIN_IDS:
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


def test_margin_interest_change_1d_on_seeded_records(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    _upsert_jquants_records(
        db,
        dataset="markets_margin_interest",
        payloads=[
            {
                "Date": "2025-04-01",
                "Code": CODES[0],
                "LongVol": 100.0,
                "ShrtVol": 50.0,
            },
            {
                "Date": "2025-04-08",
                "Code": CODES[0],
                "LongVol": 130.0,
                "ShrtVol": 50.0,
            },
        ],
    )
    # Total 150 → 180 = +20%
    out = compute(
        "margin_interest_change_1d",
        as_of=close_iso("2025-04-08"),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx(0.20)
    assert out.metadata["datasets"] == ["markets_margin_interest"]
    assert out.metadata["feature_id"] == "margin_interest_change_1d"
    assert out.metadata["rows_seen"] == 2


def test_margin_interest_change_1d_insufficient(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    _upsert_jquants_records(
        db,
        dataset="markets_margin_interest",
        payloads=[
            {
                "Date": "2025-04-01",
                "Code": CODES[0],
                "LongVol": 100.0,
                "ShrtVol": 0.0,
            },
        ],
    )
    out = compute(
        "margin_interest_change_1d",
        as_of=close_iso("2025-04-01"),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is None
    assert "insufficient" in out.metadata["reason"]


def test_short_ratio_level_on_seeded_records(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    _upsert_jquants_records(
        db,
        dataset="markets_short_ratio",
        payloads=[
            {
                "Date": "2025-04-01",
                "S33": "0050",
                "SellExShortVa": 1000.0,
                "ShrtWithResVa": 100.0,
                "ShrtNoResVa": 50.0,
            },
            {
                "Date": "2025-04-02",
                "S33": "0050",
                "SellExShortVa": 200.0,
                "ShrtWithResVa": 40.0,
                "ShrtNoResVa": 10.0,
            },
            {
                "Date": "2025-04-02",
                "S33": "1050",
                "SellExShortVa": 999.0,
                "ShrtWithResVa": 1.0,
                "ShrtNoResVa": 1.0,
            },
        ],
    )
    out = compute(
        "short_ratio_level",
        as_of=close_iso("2025-04-02"),
        section="0050",
        db_path=db,
    )
    # Latest for 0050: (40+10)/200 = 0.25
    assert out.value == pytest.approx(0.25)
    assert out.metadata["datasets"] == ["markets_short_ratio"]
    assert out.metadata["section"] == "0050"
    assert out.metadata["date"] == "2025-04-02"


def test_short_ratio_level_missing_section(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    out = compute(
        "short_ratio_level",
        as_of=close_iso(days[0]),
        section="9999",
        db_path=db,
    )
    assert out.value is None
    assert "no short_ratio" in out.metadata["reason"]


def test_is_trading_day_on_seeded_calendar(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    # coreseed marks seeded days as holiday_division == "1"
    out = compute(
        "is_trading_day",
        as_of=close_iso("2025-04-01"),
        db_path=db,
    )
    assert out.value == 1.0
    assert out.metadata["date"] == "2025-04-01"
    assert out.metadata["datasets"] == ["markets_calendar"]

    # Explicit non-trading date with no row → None
    out_miss = compute(
        "is_trading_day",
        as_of=close_iso("2025-04-01"),
        date="2099-01-01",
        db_path=db,
    )
    assert out_miss.value is None
    assert out_miss.metadata["date"] == "2099-01-01"


def test_is_trading_day_non_trading_division(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    # Override calendar row to non-trading.
    store = SqliteStore(db)
    store.upsert(
        "jquants_market_calendar",
        [
            {
                "source": "jquants",
                "date": "2025-04-06",
                "event_time": "2025-04-06T09:00:00+09:00",
                "available_at": "2025-01-01T00:00:00+09:00",
                "ingested_at": "2025-01-01T00:00:00+09:00",
                "holiday_division": "0",
            }
        ],
    )
    store.close()
    out = compute(
        "is_trading_day",
        as_of=close_iso("2025-04-06"),
        date="2025-04-06",
        db_path=db,
    )
    assert out.value == 0.0


def test_repo_rate_level_on_seeded_rates(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    _upsert_repo_rates(
        db,
        [
            {
                "source": "jsda",
                "as_of_date": "2025-04-01",
                "tenor": "overnight",
                "rate_type": "東京レポ・レート",
                "event_time": "2025-04-01T15:00:00+09:00",
                "available_at": close_iso("2025-04-01"),
                "ingested_at": close_iso("2025-04-01"),
                "rate": 0.10,
            },
            {
                "source": "jsda",
                "as_of_date": "2025-04-02",
                "tenor": "overnight",
                "rate_type": "東京レポ・レート",
                "event_time": "2025-04-02T15:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "rate": 0.15,
            },
        ],
    )
    out = compute(
        "repo_rate_level",
        as_of=close_iso("2025-04-02"),
        tenor="overnight",
        db_path=db,
    )
    assert out.value == pytest.approx(0.15)
    assert out.metadata["datasets"] == ["jsda_tokyo_repo_rates"]
    assert out.metadata["as_of_date"] == "2025-04-02"

    # PIT: earlier as_of hides the later rate.
    out_early = compute(
        "repo_rate_level",
        as_of=close_iso("2025-04-01"),
        tenor="overnight",
        db_path=db,
    )
    assert out_early.value == pytest.approx(0.10)


def test_repo_rate_level_empty_is_none(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    out = compute(
        "repo_rate_level",
        as_of=close_iso(days[0]),
        db_path=db,
    )
    assert out.value is None
    assert "no repo" in out.metadata["reason"]


def test_margin_short_calendar_repo_reject_defer_poison(monkeypatch):
    """Each new feature's declared datasets stay DEFER-free; poison fails closed."""
    for poisoned in (
        ["markets_margin_interest", "equities_master"],
        ["markets_short_ratio", "fins_earnings_date"],
        ["markets_calendar", "equities_bars_daily_am"],
        ["jsda_tokyo_repo_rates", "jsda_otc_bond_reference_prices"],
    ):
        with pytest.raises(PermanentDeferHistoryError):
            require_feature_datasets(poisoned, context="feature test")
