"""COMPLETE 21 min features + feature-pipeline permanent DEFER guard (W49–W53).

W51 / w0815ar_g2:

* T5 — strengthen tests for existing 7 candidates (missing inputs, PIT gates,
  DEFER rejection).
* T6 — +3 candidates: return_1d_c21, margin_alert_flag, futures_activity_proxy.
* T7 criteria doc is separate; no candidate → approved promotion that wave.

W52 / w0815as_g1:

* Promote: ``is_trading_day`` + ``volume_change_1d`` → approved (v1.0.0).

W53 / w0815at_g1 O2:

* Promote after feature-level CF tip E2E: ``topix_relative_1d``,
  ``disclosure_flag_fins``, ``margin_interest_change_1d`` → approved (v1.0.0).
* Remaining 5 stay candidate. No READY / Mass / Phase7.
"""

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
    get_for_strategy,
    list_features,
    require_feature_dataset,
    require_feature_datasets,
)
from features.registry import FeatureGovernanceError
from features.complete21_min import (
    disclosure_flag_from_count,
    futures_activity_from_volume_pairs,
    is_trading_day_from_division,
    margin_alert_flag_from_count,
    margin_interest_change_from_pairs,
    repo_rate_level_from_rows,
    short_ratio_level_from_components,
    simple_return_from_closes,
    topix_relative_from_returns,
    volume_change_from_pairs,
)
from features.runtime import AsOfRequired, FeatureContext, MissingInput
from storage.sqlite_store import SqliteStore

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from _coreseed import CODES, close_iso, seed_db


# W49–W50 held (7) + W51 expand (+3) = 10 complete21 min features.
COMPLETE21_MIN_IDS = (
    "volume_change_1d",
    "topix_relative_1d",
    "disclosure_flag_fins",
    "margin_interest_change_1d",
    "short_ratio_level",
    "is_trading_day",
    "repo_rate_level",
    "return_1d_c21",
    "margin_alert_flag",
    "futures_activity_proxy",
)

# W52 + W53 O2 promotions; version pin remains 1.0.0.
COMPLETE21_MIN_APPROVED_IDS = (
    "is_trading_day",
    "volume_change_1d",
    "topix_relative_1d",
    "disclosure_flag_fins",
    "margin_interest_change_1d",
)
COMPLETE21_MIN_CANDIDATE_IDS = tuple(
    fid for fid in COMPLETE21_MIN_IDS if fid not in COMPLETE21_MIN_APPROVED_IDS
)

# Features that require a specific kwargs at the runtime gate.
_REQUIRED_INPUT_CASES = (
    ("volume_change_1d", ("code",)),
    ("topix_relative_1d", ("code",)),
    ("disclosure_flag_fins", ("code",)),
    ("margin_interest_change_1d", ("code",)),
    ("short_ratio_level", ("section",)),
    ("return_1d_c21", ("code",)),
    ("margin_alert_flag", ("code",)),
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
        mod._RETURN_C21_DATASETS,
        mod._MARGIN_ALERT_DATASETS,
        mod._FUTURES_DATASETS,
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


def test_margin_alert_and_futures_helpers_data_free():
    flag, meta = margin_alert_flag_from_count(2)
    assert flag == 1.0
    assert meta["rows_seen"] == 2
    flag0, _ = margin_alert_flag_from_count(0)
    assert flag0 == 0.0

    activity, ameta = futures_activity_from_volume_pairs(
        [
            ("2025-04-01", 100.0),
            ("2025-04-02", 50.0),
            ("2025-04-02", 75.0),
        ]
    )
    assert activity == pytest.approx(125.0)
    assert ameta["activity_date"] == "2025-04-02"
    assert ameta["contracts_on_date"] == 2

    none_v, none_m = futures_activity_from_volume_pairs([])
    assert none_v is None
    assert "no futures" in none_m["reason"]


# ---------------------------------------------------------------------------
# T5 — missing inputs / as_of / DEFER rejection / PIT gates (all candidates)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fid,required", _REQUIRED_INPUT_CASES)
def test_complete21_min_missing_required_inputs(tmp_path, fid, required):
    """Runtime MissingInput before compute when required kwargs are absent."""
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    with pytest.raises(MissingInput) as exc:
        compute(fid, as_of=close_iso(days[-1]), db_path=db)
    msg = str(exc.value)
    for key in required:
        assert key in msg


def test_complete21_min_requires_as_of(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    with pytest.raises(AsOfRequired):
        compute("volume_change_1d", as_of=None, code=CODES[0], db_path=db)
    with pytest.raises(AsOfRequired):
        compute("return_1d_c21", as_of=None, code=CODES[0], db_path=db)
    with pytest.raises(AsOfRequired):
        compute("margin_alert_flag", as_of=None, code=CODES[0], db_path=db)


def test_complete21_min_w53_promotion_status_and_version_pin():
    """W52+W53: 5 approved (pinned 1.0.0); remaining 5 stay candidate."""
    for fid in COMPLETE21_MIN_APPROVED_IDS:
        feat = get(fid)
        assert feat.status == "approved", fid
        assert str(feat.version) == "1.0.0", fid
    for fid in COMPLETE21_MIN_CANDIDATE_IDS:
        feat = get(fid)
        assert feat.status == "candidate", fid
        assert feat.status != "approved", fid
    assert len(COMPLETE21_MIN_APPROVED_IDS) == 5
    assert len(COMPLETE21_MIN_CANDIDATE_IDS) == 5


def test_get_for_strategy_admits_approved_signal_not_utility_or_candidate():
    """Contract: get_for_strategy admits approved strategy-facing roles only."""
    # volume_change_1d: approved + signal → admitted
    vol = get_for_strategy("volume_change_1d", version="1.0.0")
    assert vol.status == "approved"
    assert vol.intended_role == "signal"
    assert str(vol.version) == "1.0.0"

    # W53 O2 promotes: topix / disclosure / margin also admitted as signal
    topix = get_for_strategy("topix_relative_1d", version="1.0.0")
    assert topix.status == "approved"
    assert topix.intended_role == "signal"
    disc = get_for_strategy("disclosure_flag_fins", version="1.0.0")
    assert disc.status == "approved"
    margin = get_for_strategy("margin_interest_change_1d", version="1.0.0")
    assert margin.status == "approved"

    # is_trading_day: approved but utility → role gate rejects by default
    with pytest.raises(FeatureGovernanceError, match="utility"):
        get_for_strategy("is_trading_day", version="1.0.0")
    util = get_for_strategy(
        "is_trading_day",
        version="1.0.0",
        allowed_roles=("utility", "signal", "state", "structural"),
    )
    assert util.status == "approved"
    assert util.intended_role == "utility"

    # remaining complete21 min stay candidate → status gate rejects
    with pytest.raises(FeatureGovernanceError, match="candidate"):
        get_for_strategy("return_1d_c21")
    with pytest.raises(FeatureGovernanceError, match="candidate"):
        get_for_strategy("short_ratio_level")


def test_complete21_min_declared_datasets_reject_each_permanent_defer():
    """Every declared feature dataset list fails closed when any DEFER is mixed in."""
    from features import complete21_min as mod

    groups = (
        mod._VOLUME_DATASETS,
        mod._TOPIX_REL_DATASETS,
        mod._DISC_DATASETS,
        mod._MARGIN_DATASETS,
        mod._SHORT_RATIO_DATASETS,
        mod._CALENDAR_DATASETS,
        mod._REPO_DATASETS,
        mod._RETURN_C21_DATASETS,
        mod._MARGIN_ALERT_DATASETS,
        mod._FUTURES_DATASETS,
    )
    for group in groups:
        for defer_ds in sorted(PERMANENT_DEFER_DATASETS):
            poisoned = list(group) + [defer_ds]
            with pytest.raises(PermanentDeferHistoryError):
                require_feature_datasets(poisoned, context="feature T5 DEFER")


def test_pit_gate_hides_future_available_at_margin_and_disclosure(tmp_path):
    """PIT: rows with available_at > as_of must not affect feature values."""
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    store = SqliteStore(db)
    # D1 margin obs: published at D1 close (visible at as_of=D1).
    # D2 margin obs: published at D2 close only (hidden at as_of=D1).
    store.upsert(
        "jquants_records",
        [
            {
                "source": "jquants",
                "dataset": "markets_margin_interest",
                "natural_key": json.dumps(
                    {"Code": CODES[0], "Date": "2025-04-01"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-01T00:00:00+09:00",
                "available_at": close_iso("2025-04-01"),
                "ingested_at": close_iso("2025-04-01"),
                "payload": json.dumps(
                    {
                        "Date": "2025-04-01",
                        "Code": CODES[0],
                        "LongVol": 100.0,
                        "ShrtVol": 0.0,
                    },
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {
                        "Date": "2025-04-01",
                        "Code": CODES[0],
                        "LongVol": 100.0,
                        "ShrtVol": 0.0,
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "source": "jquants",
                "dataset": "markets_margin_interest",
                "natural_key": json.dumps(
                    {"Code": CODES[0], "Date": "2025-04-02"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-02T00:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "Code": CODES[0],
                        "LongVol": 200.0,
                        "ShrtVol": 0.0,
                    },
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "Code": CODES[0],
                        "LongVol": 200.0,
                        "ShrtVol": 0.0,
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "source": "jquants",
                "dataset": "fins_summary",
                "natural_key": json.dumps(
                    {"Code": CODES[0], "Date": "2025-04-02"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-02T00:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "payload": json.dumps(
                    {"Code": CODES[0], "Date": "2025-04-02", "NetSales": 1},
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {"Code": CODES[0], "Date": "2025-04-02", "NetSales": 1},
                    ensure_ascii=False,
                ),
            },
        ],
    )
    store.close()

    # At D1 close: only one margin obs → insufficient; disclosure flag 0.
    margin_early = compute(
        "margin_interest_change_1d",
        as_of=close_iso("2025-04-01"),
        code=CODES[0],
        db_path=db,
    )
    assert margin_early.value is None
    assert "insufficient" in margin_early.metadata["reason"]

    disc_early = compute(
        "disclosure_flag_fins",
        as_of=close_iso("2025-04-01"),
        code=CODES[0],
        db_path=db,
    )
    assert disc_early.value == 0.0

    # At D2 close: both margin obs + disclosure visible.
    margin_late = compute(
        "margin_interest_change_1d",
        as_of=close_iso("2025-04-02"),
        code=CODES[0],
        db_path=db,
    )
    assert margin_late.value == pytest.approx(1.0)  # 100 → 200

    disc_late = compute(
        "disclosure_flag_fins",
        as_of=close_iso("2025-04-02"),
        code=CODES[0],
        db_path=db,
    )
    assert disc_late.value == 1.0


def test_pit_gate_hides_future_short_ratio_and_margin_alert(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    store = SqliteStore(db)
    # Short ratio published only at D2 close.
    store.upsert(
        "jquants_records",
        [
            {
                "source": "jquants",
                "dataset": "markets_short_ratio",
                "natural_key": json.dumps(
                    {"Date": "2025-04-02", "S33": "0050"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-02T00:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "S33": "0050",
                        "SellExShortVa": 200.0,
                        "ShrtWithResVa": 40.0,
                        "ShrtNoResVa": 10.0,
                    },
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "S33": "0050",
                        "SellExShortVa": 200.0,
                        "ShrtWithResVa": 40.0,
                        "ShrtNoResVa": 10.0,
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "source": "jquants",
                "dataset": "markets_margin_alert",
                "natural_key": json.dumps(
                    {
                        "Code": CODES[0],
                        "PubDate": "2025-04-02",
                        "AppDate": "2025-04-02",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-02T00:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "payload": json.dumps(
                    {
                        "Code": CODES[0],
                        "PubDate": "2025-04-02",
                        "AppDate": "2025-04-02",
                    },
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {
                        "Code": CODES[0],
                        "PubDate": "2025-04-02",
                        "AppDate": "2025-04-02",
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    store.close()

    short_early = compute(
        "short_ratio_level",
        as_of=close_iso("2025-04-01"),
        section="0050",
        db_path=db,
    )
    assert short_early.value is None

    alert_early = compute(
        "margin_alert_flag",
        as_of=close_iso("2025-04-01"),
        code=CODES[0],
        db_path=db,
    )
    assert alert_early.value == 0.0

    short_late = compute(
        "short_ratio_level",
        as_of=close_iso("2025-04-02"),
        section="0050",
        db_path=db,
    )
    assert short_late.value == pytest.approx(0.25)

    alert_late = compute(
        "margin_alert_flag",
        as_of=close_iso("2025-04-02"),
        code=CODES[0],
        db_path=db,
    )
    assert alert_late.value == 1.0


def test_pit_gate_hides_future_futures_activity(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    store = SqliteStore(db)
    store.upsert(
        "jquants_records",
        [
            {
                "source": "jquants",
                "dataset": "derivatives_bars_daily_futures",
                "natural_key": json.dumps(
                    {"Date": "2025-04-02", "Code": "160060019"},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "event_time": "2025-04-02T00:00:00+09:00",
                "available_at": close_iso("2025-04-02"),
                "ingested_at": close_iso("2025-04-02"),
                "payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "Code": "160060019",
                        "Volume": 500.0,
                        "Close": 28000.0,
                    },
                    ensure_ascii=False,
                ),
                "raw_payload": json.dumps(
                    {
                        "Date": "2025-04-02",
                        "Code": "160060019",
                        "Volume": 500.0,
                        "Close": 28000.0,
                    },
                    ensure_ascii=False,
                ),
            }
        ],
    )
    store.close()

    early = compute(
        "futures_activity_proxy",
        as_of=close_iso("2025-04-01"),
        db_path=db,
    )
    assert early.value is None

    late = compute(
        "futures_activity_proxy",
        as_of=close_iso("2025-04-02"),
        db_path=db,
    )
    assert late.value == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# T5/T6 — registered features + computation
# ---------------------------------------------------------------------------

def test_complete21_min_features_registered():
    ids = {f.id for f in list_features()}
    assert set(COMPLETE21_MIN_IDS).issubset(ids)
    for fid in COMPLETE21_MIN_IDS:
        feat = get(fid)
        assert "complete21" in feat.tags
        if fid in COMPLETE21_MIN_APPROVED_IDS:
            assert feat.status == "approved", fid
        else:
            assert feat.status == "candidate", fid


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


def test_topix_relative_1d_seeded_dual_leg(tmp_path):
    """W53: dual-leg integration — equity return minus TOPIX return on seeded DB."""
    days = ["2025-04-01", "2025-04-02"]
    # Equity: 100 → 110 = +10%; TOPIX: 3000 → 3030 = +1% → relative +9%.
    prices = {CODES[0]: {"2025-04-01": 100.0, "2025-04-02": 110.0}}
    db = seed_db(tmp_path, days=days, prices=prices)
    _upsert_jquants_records(
        db,
        dataset="indices_bars_daily_topix",
        payloads=[
            {"Date": "2025-04-01", "Close": 3000.0},
            {"Date": "2025-04-02", "Close": 3030.0},
        ],
    )
    out = compute(
        "topix_relative_1d",
        as_of=close_iso("2025-04-02"),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx(0.09)
    assert out.metadata["feature_id"] == "topix_relative_1d"
    assert out.metadata["datasets"] == [
        "equities_bars_daily",
        "indices_bars_daily_topix",
    ]
    assert out.metadata["equity_ret"] == pytest.approx(0.10)
    assert out.metadata["topix_ret"] == pytest.approx(0.01)


def test_topix_relative_1d_insufficient_missing_topix_leg(tmp_path):
    """Missing TOPIX leg → None (not raise)."""
    days = ["2025-04-01", "2025-04-02"]
    prices = {CODES[0]: {d: 100.0 + i for i, d in enumerate(days)}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "topix_relative_1d",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is None
    assert "missing" in out.metadata["reason"]


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


def test_disclosure_flag_fins_seeded_positive(tmp_path):
    """W53: positive path — any PIT-visible fins_summary row → 1.0."""
    days = ["2025-04-01", "2025-04-02"]
    prices = {CODES[0]: {d: 100.0 for d in days}}
    db = seed_db(tmp_path, days=days, prices=prices)
    _upsert_jquants_records(
        db,
        dataset="fins_summary",
        payloads=[
            {"Code": CODES[0], "Date": "2025-04-02", "NetSales": 123},
        ],
    )
    out = compute(
        "disclosure_flag_fins",
        as_of=close_iso("2025-04-02"),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == 1.0
    assert out.metadata["rows_seen"] >= 1
    assert out.metadata["feature_id"] == "disclosure_flag_fins"


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
        ["equities_bars_daily", "equities_bars_daily_am"],  # return_1d_c21 path
        ["markets_margin_alert", "equities_master"],
        ["derivatives_bars_daily_futures", "equities_earnings_calendar"],
    ):
        with pytest.raises(PermanentDeferHistoryError):
            require_feature_datasets(poisoned, context="feature test")


# ---------------------------------------------------------------------------
# T6 — W51 expand: return_1d_c21, margin_alert_flag, futures_activity_proxy
# ---------------------------------------------------------------------------

def test_return_1d_c21_matches_simple_return_on_seeded_bars(tmp_path):
    days = ["2025-04-01", "2025-04-02", "2025-04-03"]
    prices = {CODES[0]: {d: 100.0 + i for i, d in enumerate(days)}}
    db = seed_db(tmp_path, days=days, prices=prices)
    out = compute(
        "return_1d_c21",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx((102.0 - 101.0) / 101.0)
    assert out.metadata["feature_id"] == "return_1d_c21"
    assert out.metadata["datasets"] == ["equities_bars_daily"]
    assert out.metadata["export_of"] == "return_1d"
    assert out.metadata["path"] == "complete21_min"
    # Parity with approved v0 return_1d (same formula, different id/status).
    v0 = compute(
        "return_1d",
        as_of=close_iso(days[-1]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == pytest.approx(v0.value)
    assert get("return_1d_c21").status == "candidate"
    assert get("return_1d").status == "approved"


def test_return_1d_c21_insufficient_history(tmp_path):
    day = "2025-04-01"
    db = seed_db(
        tmp_path,
        days=[day],
        prices={CODES[0]: {day: 100.0}},
    )
    out = compute(
        "return_1d_c21",
        as_of=close_iso(day),
        code=CODES[0],
        db_path=db,
    )
    assert out.value is None
    assert "insufficient" in out.metadata["reason"]


def test_margin_alert_flag_on_seeded_records(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    _upsert_jquants_records(
        db,
        dataset="markets_margin_alert",
        payloads=[
            {
                "Code": CODES[0],
                "PubDate": "2025-04-01",
                "AppDate": "2025-04-01",
                "Date": "2025-04-01",
            },
        ],
    )
    out = compute(
        "margin_alert_flag",
        as_of=close_iso("2025-04-01"),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == 1.0
    assert out.metadata["datasets"] == ["markets_margin_alert"]
    assert out.metadata["feature_id"] == "margin_alert_flag"
    assert out.metadata["rows_seen"] >= 1


def test_margin_alert_flag_empty_is_zero(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    out = compute(
        "margin_alert_flag",
        as_of=close_iso(days[0]),
        code=CODES[0],
        db_path=db,
    )
    assert out.value == 0.0
    assert out.metadata["rows_seen"] == 0


def test_futures_activity_proxy_on_seeded_records(tmp_path):
    days = ["2025-04-01", "2025-04-02"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {d: 100.0 for d in days}},
    )
    _upsert_jquants_records(
        db,
        dataset="derivatives_bars_daily_futures",
        payloads=[
            {
                "Date": "2025-04-01",
                "Code": "160060019",
                "Volume": 100.0,
                "Close": 27000.0,
            },
            {
                "Date": "2025-04-02",
                "Code": "160060019",
                "Volume": 200.0,
                "Close": 27100.0,
            },
            {
                "Date": "2025-04-02",
                "Code": "160060020",
                "Volume": 50.0,
                "Close": 100.0,
            },
        ],
    )
    # All contracts: latest date sum = 200 + 50 = 250
    out = compute(
        "futures_activity_proxy",
        as_of=close_iso("2025-04-02"),
        db_path=db,
    )
    assert out.value == pytest.approx(250.0)
    assert out.metadata["datasets"] == ["derivatives_bars_daily_futures"]
    assert out.metadata["activity_date"] == "2025-04-02"
    assert out.metadata["contracts_on_date"] == 2

    # Optional code filter
    out_one = compute(
        "futures_activity_proxy",
        as_of=close_iso("2025-04-02"),
        code="160060019",
        db_path=db,
    )
    assert out_one.value == pytest.approx(200.0)


def test_futures_activity_proxy_empty_is_none(tmp_path):
    days = ["2025-04-01"]
    db = seed_db(
        tmp_path,
        days=days,
        prices={CODES[0]: {days[0]: 100.0}},
    )
    out = compute(
        "futures_activity_proxy",
        as_of=close_iso(days[0]),
        db_path=db,
    )
    assert out.value is None
    assert "no futures" in out.metadata["reason"]
