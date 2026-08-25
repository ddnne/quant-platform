"""Phase 3.5 — daily-tier coverage runner on bars / calendar / master.

Fixtures built via the real :class:`storage.sqlite_store.SqliteStore` exercise
every daily-tier check. Includes C12 addon-leak failure and X4 sidecar
pass/fail paths. Shared builders: ``tests/phase35_matrix_util.py``.

Offline-only: no network, no Cloudflare, no API keys.
"""

from __future__ import annotations

import pytest

from cf_platform.ingest_premium import matrix
from cf_platform.ingest_premium.coverage import (
    CheckResult,
    _ADDON_IDS,
    has_failures,
    run_coverage,
    summarize,
)
from cf_platform.ingest_premium.validate import PREMIUM_CORE_DATASETS
from ingestion.jquants.catalog import list_datasets
from ingestion.jquants.normalize import (
    normalize_daily_bars,
    normalize_generic,
    normalize_market_calendar,
)
from storage.sqlite_store import SqliteStore

from tests.phase35_matrix_util import (
    INGESTED,
    _bars_rows,
    _results_by_id,
    matrix_db,
    specialized_db,
)


def test_daily_runner_returns_only_daily_ids(matrix_db):
    out = run_coverage(matrix_db, tier="daily")
    ids = {r.check_id for r in out}
    # Daily-tier runner emits only daily-tier ids.
    assert ids <= matrix.DAILY_IDS


def test_daily_runner_passes_on_complete_fixture(matrix_db):
    """Scoped to the three datasets the fixture actually populates.

    The full 23-dataset iteration is exercised in
    :func:`test_unreadable_db_emits_failures` and friends; here we want a
    clean all-pass on a complete-but-narrow fixture.
    """
    out = run_coverage(matrix_db, tier="daily",
                       datasets=["equities_bars_daily", "equities_master",
                                 "markets_calendar"])
    failures = [r for r in out if r.status == "fail"]
    assert not failures, (
        f"expected no failures on a complete fixture; failed: "
        f"{[(r.check_id, r.dataset, r.detail) for r in failures]}"
    )


def test_daily_runner_emits_per_dataset_for_C1_C5(matrix_db):
    """C1–C5 fan out per dataset; we should see one row per dataset."""
    out = run_coverage(matrix_db, tier="daily", datasets=["equities_bars_daily"])
    for cid in ("C1", "C2", "C3", "C4", "C5", "C8"):
        rows = _results_by_id(out, cid)
        assert rows, f"no {cid} row emitted"
        # When scoped to one dataset, every C1-C8 row is for that dataset.
        assert all(r.dataset == "equities_bars_daily" for r in rows), cid


# ---------------------------------------------------------------------------
# C12 — addon leak detection
# ---------------------------------------------------------------------------
# Catalog addon group (minute / tick / TDnet). Freeze so C12 cannot silently
# diverge from ingestion.jquants.catalog — same pattern as DATEMODE_EXPECTED.
C12_ADDON_EXPECTED = frozenset({
    "equities_bars_minute", "equities_trades",
    "td_list", "td_files", "td_bulk",
})


def test_C12_guarded_ids_match_catalog_addon_group():
    """C12 addon ids are the catalog addon group, not a second hardcoded list."""
    catalog_addons = frozenset(list_datasets("addon"))
    assert catalog_addons == C12_ADDON_EXPECTED
    assert _ADDON_IDS == catalog_addons
    assert not catalog_addons & set(PREMIUM_CORE_DATASETS)


def test_C12_passes_when_no_addon_present(specialized_db):
    out = run_coverage(specialized_db, tier="daily")
    c12 = _results_by_id(out, "C12")
    assert len(c12) == 1
    assert c12[0].status == "pass"
    assert c12[0].dataset is None  # cross-cutting


def test_C12_fails_when_minute_dataset_present(tmp_path):
    """If the synced data contains an addon dataset, C12 must fail."""
    p = tmp_path / "leak.sqlite"
    store = SqliteStore(p)
    # Build a clean base, then inject a leaked addon dataset.
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"Code": "8697", "Date": "2025-04-01",
              "DateTime": "2025-04-01T09:00:00", "Time": "09:00",
              "Close": 100.0}],
            dataset="equities_bars_minute",
            ingested_at=INGESTED,
        ),
    )
    store.close()
    out = run_coverage(p, tier="daily")
    c12 = _results_by_id(out, "C12")
    assert len(c12) == 1
    assert c12[0].status == "fail"
    assert "equities_bars_minute" in c12[0].detail
    assert c12[0].metrics["addon_ids_seen"] == ["equities_bars_minute"]


def test_C12_fails_when_td_dataset_present(tmp_path):
    p = tmp_path / "td.sqlite"
    store = SqliteStore(p)
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"DiscDate": "2025-04-01", "DiscNo": "1", "Title": "x"}],
            dataset="td_list",
            ingested_at=INGESTED,
        ),
    )
    store.close()
    out = run_coverage(p, tier="daily")
    c12 = _results_by_id(out, "C12")
    assert c12[0].status == "fail"
    assert "td_list" in c12[0].detail


# ---------------------------------------------------------------------------
# C8 — freshness
# ---------------------------------------------------------------------------
def test_C8_fails_on_stale_data(tmp_path):
    """Even with a recent ``today`` arg, an old event_time must fail."""
    p = tmp_path / "stale.sqlite"
    store = SqliteStore(p)
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"Code": "8697", "Date": "2024-01-01", "Close": 100.0}],
            dataset="equities_bars_daily",
            ingested_at="2024-01-01T15:30:00+09:00",
        ),
    )
    store.close()
    out = run_coverage(
        p, tier="daily", today="2025-04-04T15:30:00+09:00",
        datasets=["equities_bars_daily"],
    )
    c8 = _results_by_id(out, "C8")
    assert len(c8) == 1
    assert c8[0].status == "fail"
    assert c8[0].metrics["days_lag"] > 7


def test_C8_passes_with_generous_freshness_window(tmp_path):
    p = tmp_path / "ok.sqlite"
    store = SqliteStore(p)
    store.upsert(
        "jquants_records",
        normalize_generic(
            [{"Code": "8697", "Date": "2024-01-01", "Close": 100.0}],
            dataset="equities_bars_daily",
            ingested_at="2024-01-01T15:30:00+09:00",
        ),
    )
    store.close()
    # 500-day window tolerates the year-plus gap.
    out = run_coverage(
        p, tier="daily", today="2025-04-04T15:30:00+09:00",
        freshness_days=500,
        datasets=["equities_bars_daily"],
    )
    c8 = _results_by_id(out, "C8")
    assert c8[0].status == "pass"


# ---------------------------------------------------------------------------
# C2/C3/C5 — empty DB and missing available_at
# ---------------------------------------------------------------------------
def test_C2_C3_fail_when_dataset_empty(tmp_path):
    """An empty DB has no rows for any dataset — C2/C3 fail loudly."""
    p = tmp_path / "empty.sqlite"
    store = SqliteStore(p)
    store.close()
    out = run_coverage(p, tier="daily", datasets=["fins_dividend"])
    c2 = _results_by_id(out, "C2")
    c3 = _results_by_id(out, "C3")
    assert c2[0].status == "fail"
    assert c3[0].status == "fail"


def test_C5_passes_with_full_available_at(matrix_db):
    out = run_coverage(matrix_db, tier="daily")
    c5 = _results_by_id(out, "C5")
    # Every emitted C5 row should be a pass (SqliteStore enforces available_at).
    assert c5
    assert all(r.status == "pass" for r in c5), (
        [(r.dataset, r.detail) for r in c5 if r.status != "pass"]
    )


# ---------------------------------------------------------------------------
# B2 — universe coverage
# ---------------------------------------------------------------------------
def test_B2_passes_with_full_universe(matrix_db):
    out = run_coverage(matrix_db, tier="daily")
    b2 = _results_by_id(out, "B2")
    assert len(b2) == 1
    assert b2[0].status == "pass"
    assert b2[0].metrics["master_count"] == 2
    assert b2[0].metrics["covered_count"] == 2
    assert b2[0].metrics["coverage"] == 1.0


def test_B2_fails_when_no_master(tmp_path):
    p = tmp_path / "bars_only.sqlite"
    store = SqliteStore(p)
    store.upsert(
        "jquants_records",
        normalize_generic(_bars_rows(), dataset="equities_bars_daily",
                          ingested_at=INGESTED),
    )
    store.close()
    out = run_coverage(p, tier="daily")
    b2 = _results_by_id(out, "B2")
    assert b2[0].status == "fail"


# ---------------------------------------------------------------------------
# B4 / K3 — calendar gaps
# ---------------------------------------------------------------------------
def test_B4_K3_pass_on_complete_fixture(matrix_db):
    out = run_coverage(matrix_db, tier="daily")
    b4 = _results_by_id(out, "B4")
    k3 = _results_by_id(out, "K3")
    assert b4[0].status == "pass", b4[0].detail
    assert k3[0].status == "pass", k3[0].detail


def test_B4_fails_when_trading_day_missing_bars(tmp_path):
    """Drop one trading day's bars → B4 should detect the gap."""
    p = tmp_path / "gappy.sqlite"
    store = SqliteStore(p)
    # All 4 calendar days are trading days, but only 3 of them have bars.
    store.upsert(
        "jquants_market_calendar",
        normalize_market_calendar(
            [{"Date": "2025-04-01", "HolidayDivision": "1"},
             {"Date": "2025-04-02", "HolidayDivision": "1"},
             {"Date": "2025-04-03", "HolidayDivision": "1"},
             {"Date": "2025-04-04", "HolidayDivision": "1"}],
            ingested_at=INGESTED,
        ),
    )
    # Bars for 8697 on 04-01, 04-02, 04-04 — 04-03 missing.
    bars = [
        {"Code": "8697", "Date": "2025-04-01", "Close": 100.0, "Open": 100.0,
         "High": 100.0, "Low": 100.0, "Volume": 1.0, "TurnoverValue": 1.0},
        {"Code": "8697", "Date": "2025-04-02", "Close": 101.0, "Open": 101.0,
         "High": 101.0, "Low": 101.0, "Volume": 1.0, "TurnoverValue": 1.0},
        {"Code": "8697", "Date": "2025-04-04", "Close": 103.0, "Open": 103.0,
         "High": 103.0, "Low": 103.0, "Volume": 1.0, "TurnoverValue": 1.0},
    ]
    store.upsert("jquants_daily_bars", normalize_daily_bars(bars, ingested_at=INGESTED))
    store.close()
    out = run_coverage(p, tier="daily")
    b4 = _results_by_id(out, "B4")
    assert b4[0].status == "fail"
    assert "2025-04-03" in b4[0].metrics["missing_days"]


def test_K3_fails_when_bar_date_not_in_calendar(tmp_path):
    """A bar date that the calendar doesn't mention at all is unexplained."""
    p = tmp_path / "xtra.sqlite"
    store = SqliteStore(p)
    store.upsert(
        "jquants_market_calendar",
        normalize_market_calendar(
            [{"Date": "2025-04-01", "HolidayDivision": "1"},
             {"Date": "2025-04-02", "HolidayDivision": "1"}],
            ingested_at=INGESTED,
        ),
    )
    # 04-03 is a bar date but not in calendar at all.
    bars = [
        {"Code": "8697", "Date": "2025-04-01", "Close": 100.0, "Open": 100.0,
         "High": 100.0, "Low": 100.0, "Volume": 1.0, "TurnoverValue": 1.0},
        {"Code": "8697", "Date": "2025-04-02", "Close": 101.0, "Open": 101.0,
         "High": 101.0, "Low": 101.0, "Volume": 1.0, "TurnoverValue": 1.0},
        {"Code": "8697", "Date": "2025-04-03", "Close": 102.0, "Open": 102.0,
         "High": 102.0, "Low": 102.0, "Volume": 1.0, "TurnoverValue": 1.0},
    ]
    store.upsert("jquants_daily_bars", normalize_daily_bars(bars, ingested_at=INGESTED))
    store.close()
    out = run_coverage(p, tier="daily")
    k3 = _results_by_id(out, "K3")
    assert k3[0].status == "fail"
    assert "2025-04-03" in k3[0].metrics["unexplained_bar_dates"]


# ---------------------------------------------------------------------------
# X4 — sidecar comparison
# ---------------------------------------------------------------------------
def test_X4_skips_without_sidecar(matrix_db):
    out = run_coverage(matrix_db, tier="daily")
    x4 = _results_by_id(out, "X4")
    assert len(x4) == 1
    assert x4[0].status == "skip"


def test_X4_passes_with_matching_sidecar(matrix_db):
    # Fixture: 8 bars (4 days × 2 codes) + 2 master rows + 6 calendar rows.
    # Both DB layouts report the same row counts because the runner unions
    # generic + specialized tables.
    sidecar = {"equities_bars_daily": 8, "equities_master": 2,
               "markets_calendar": 6}
    out = run_coverage(matrix_db, tier="daily", validation_sidecar=sidecar)
    x4 = _results_by_id(out, "X4")
    assert x4[0].status == "pass", x4[0].detail


def test_X4_fails_on_mismatch(matrix_db):
    sidecar = {"equities_bars_daily": 999}
    out = run_coverage(matrix_db, tier="daily", validation_sidecar=sidecar)
    x4 = _results_by_id(out, "X4")
    assert x4[0].status == "fail"
    mismatches = x4[0].metrics["mismatches"]
    assert any(m["dataset"] == "equities_bars_daily" for m in mismatches)


# ---------------------------------------------------------------------------
# Runner-level helpers
# ---------------------------------------------------------------------------
def test_has_failures_and_summarize():
    rs = [
        CheckResult("C1", "x", "pass", "ok"),
        CheckResult("C2", "x", "fail", "bad"),
        CheckResult("C3", "x", "skip", "n/a"),
        CheckResult("C4", "x", "warn", "hmm"),
    ]
    assert has_failures(rs)
    counts = summarize(rs)
    assert counts == {"pass": 1, "fail": 1, "skip": 1, "warn": 1}


def test_unreadable_db_emits_failures(tmp_path):
    """A non-existent DB path surfaces as a failure, not a crash."""
    missing = tmp_path / "absent.sqlite"
    out = run_coverage(missing, tier="daily")
    assert out  # something was emitted
    assert all(r.status == "fail" for r in out)
    assert any("cannot open DB" in r.detail for r in out)


def test_invalid_tier_raises(tmp_path):
    p = tmp_path / "x.sqlite"
    SqliteStore(p).close()
    with pytest.raises(ValueError):
        run_coverage(p, tier="monthly")
