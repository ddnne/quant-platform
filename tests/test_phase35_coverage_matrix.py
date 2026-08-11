"""Phase 3.5 — validation matrix catalog + coverage runner.

Three concerns:

1. **Catalog completeness** — every id mentioned in
   ``docs/phase35_validation_matrix.md`` exists in
   ``cf_platform.ingest_premium.matrix.CHECKS``.
2. **Daily tier matches the doc** — exactly C1–C5, C8, C12, B2, B4, K3, X4.
3. **Coverage runner behavior** — fixtures built via the real
   :class:`storage.sqlite_store.SqliteStore` exercise every daily-tier
   check. Includes C12 addon-leak failure and X4 sidecar pass/fail paths.

Offline-only: no network, no Cloudflare, no API keys.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from cf_platform.ingest_premium import matrix
from cf_platform.ingest_premium.coverage import (
    CheckResult,
    has_failures,
    run_coverage,
    summarize,
)
from ingestion.jquants.normalize import (
    normalize_daily_bars,
    normalize_generic,
    normalize_listed_info,
    normalize_market_calendar,
)
from storage.sqlite_store import SqliteStore

_REPO = Path(__file__).resolve().parents[1]
MATRIX_DOC = _REPO / "docs" / "phase35_validation_matrix.md"


# ---------------------------------------------------------------------------
# Fixture builders — minimal real DBs the runner can chew on.
# ---------------------------------------------------------------------------
INGESTED = "2025-04-04T15:30:00+09:00"


def _bars_rows():
    """4 trading days × 2 codes, deterministic closes."""
    out = []
    for code, base in (("8697", 100.0), ("7203", 8000.0)):
        for i, day in enumerate(
            ("2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04")
        ):
            close = base + i
            out.append({
                "Code": code, "Date": day,
                "Open": close, "High": close, "Low": close,
                "Close": close, "Volume": 1000.0, "TurnoverValue": close * 1000,
            })
    return out


def _master_rows():
    return [
        {"Code": "8697", "Date": "2025-03-31", "CompanyName": "JACR",
         "MarketCode": "0111"},
        {"Code": "7203", "Date": "2025-03-31", "CompanyName": "Toyota",
         "MarketCode": "0111"},
    ]


def _calendar_rows():
    """April 2025 with 4 weekday trading days + one weekend (Apr 5 Sat)."""
    return [
        {"Date": "2025-04-01", "HolidayDivision": "1"},
        {"Date": "2025-04-02", "HolidayDivision": "1"},
        {"Date": "2025-04-03", "HolidayDivision": "1"},
        {"Date": "2025-04-04", "HolidayDivision": "1"},
        {"Date": "2025-04-05", "HolidayDivision": "0"},  # Saturday
        {"Date": "2025-04-06", "HolidayDivision": "0"},  # Sunday
    ]


def _build_specialized_db(path: Path) -> Path:
    """DB that uses the Phase-1 specialized tables only (no jquants_records).

    This is the layout the local ingestion pipeline produces; the runner
    needs to find bars / master / calendar here too.
    """
    store = SqliteStore(path)
    store.upsert(
        "jquants_daily_bars",
        normalize_daily_bars(_bars_rows(), ingested_at=INGESTED),
    )
    store.upsert(
        "jquants_listed_info",
        normalize_listed_info(
            _master_rows(), ingested_at=INGESTED, snapshot_date="2025-03-31"
        ),
    )
    store.upsert(
        "jquants_market_calendar",
        normalize_market_calendar(_calendar_rows(), ingested_at=INGESTED),
    )
    store.close()
    return path


def _build_generic_db(path: Path) -> Path:
    """DB that mirrors the CF sync output (everything in jquants_records).

    This is the layout ``sync_d1_to_sqlite.py`` produces; the runner needs
    to find the same data through the generic table.
    """
    store = SqliteStore(path)
    store.upsert(
        "jquants_records",
        normalize_generic(_bars_rows(), dataset="equities_bars_daily",
                          ingested_at=INGESTED),
    )
    store.upsert(
        "jquants_records",
        normalize_generic(_master_rows(), dataset="equities_master",
                          ingested_at=INGESTED),
    )
    store.upsert(
        "jquants_records",
        normalize_generic(_calendar_rows(), dataset="markets_calendar",
                          ingested_at=INGESTED),
    )
    store.close()
    return path


@pytest.fixture
def specialized_db(tmp_path) -> Path:
    return _build_specialized_db(tmp_path / "specialized.sqlite")


@pytest.fixture
def generic_db(tmp_path) -> Path:
    return _build_generic_db(tmp_path / "generic.sqlite")


@pytest.fixture(params=["specialized", "generic"])
def matrix_db(request, tmp_path) -> Path:
    """Parametrized: run every coverage test against both DB layouts."""
    p = tmp_path / f"{request.param}.sqlite"
    if request.param == "specialized":
        return _build_specialized_db(p)
    return _build_generic_db(p)


# ---------------------------------------------------------------------------
# 1. Catalog completeness — every id in the doc must be in matrix.CHECKS
# ---------------------------------------------------------------------------
def _doc_check_ids() -> set[str]:
    """Parse the markdown tables for check IDs (C1, M3, X4, etc.)."""
    text = MATRIX_DOC.read_text(encoding="utf-8")
    # IDs are uppercase letter(s) + digits, used as the first column of
    # doc tables. Pull every match in the right-hand tables; ignore stray
    # mentions in prose by requiring a leading ``|`` (table cell) on the
    # same logical line.
    ids: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        # First cell after the leading ``|``.
        first = line[1:].split("|", 1)[0].strip()
        m = re.fullmatch(r"([A-Z]+)(\d+)", first)
        if m:
            ids.add(first)
    return ids


def test_matrix_doc_exists():
    assert MATRIX_DOC.exists(), f"missing {MATRIX_DOC}"


def test_every_doc_id_is_in_matrix():
    doc_ids = _doc_check_ids()
    code_ids = {c.id for c in matrix.CHECKS}
    missing = doc_ids - code_ids
    assert not missing, f"ids in doc but not in matrix.CHECKS: {sorted(missing)}"


def test_every_matrix_id_is_in_doc():
    doc_ids = _doc_check_ids()
    code_ids = {c.id for c in matrix.CHECKS}
    extra = code_ids - doc_ids
    assert not extra, f"ids in matrix.CHECKS but not in doc: {sorted(extra)}"


def test_check_ids_unique():
    ids = [c.id for c in matrix.CHECKS]
    assert len(ids) == len(set(ids)), "duplicate check ids"


# ---------------------------------------------------------------------------
# 2. Tier membership matches the doc's daily/weekly tables exactly
# ---------------------------------------------------------------------------
EXPECTED_DAILY = frozenset(
    {"C1", "C2", "C3", "C4", "C5", "C8", "C12", "B2", "B4", "K3", "X4"}
)


def test_daily_tier_matches_doc():
    assert matrix.DAILY_IDS == EXPECTED_DAILY


def test_weekly_tier_is_complement_of_daily():
    all_ids = {c.id for c in matrix.CHECKS}
    assert matrix.DAILY_IDS | matrix.WEEKLY_IDS == all_ids
    assert matrix.DAILY_IDS & matrix.WEEKLY_IDS == set()


def test_list_checks_filter():
    daily = matrix.list_checks("daily")
    weekly = matrix.list_checks("weekly")
    all_ = matrix.list_checks()
    assert {c.id for c in daily} == matrix.DAILY_IDS
    assert {c.id for c in weekly} == matrix.WEEKLY_IDS
    assert len(daily) + len(weekly) == len(all_)


def test_list_checks_invalid_tier_raises():
    with pytest.raises(ValueError):
        matrix.list_checks("monthly")


def test_get_check_known_and_unknown():
    c = matrix.get_check("C12")
    assert c.id == "C12"
    assert c.tier == "daily"
    assert c.title == "No addon leak"
    with pytest.raises(KeyError):
        matrix.get_check("ZZ9")


def test_premium_core_datasets_count():
    assert len(matrix.premium_core_datasets()) == 23


# ---------------------------------------------------------------------------
# 3. Coverage runner — daily tier on a real fixture DB
# ---------------------------------------------------------------------------
def _results_by_id(results: list[CheckResult], check_id: str) -> list[CheckResult]:
    return [r for r in results if r.check_id == check_id]


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


# ---------------------------------------------------------------------------
# Weekly tier — structurally complete, X2/X3 logic, others skip-or-warn
# ---------------------------------------------------------------------------
def test_weekly_emits_every_weekly_id(specialized_db):
    out = run_coverage(specialized_db, tier="weekly")
    ids = {r.check_id for r in out}
    # Every weekly id has at least one row in the output.
    assert ids == matrix.WEEKLY_IDS


def test_weekly_X2_passes_on_complete_fixture(specialized_db):
    out = run_coverage(specialized_db, tier="weekly")
    x2 = _results_by_id(out, "X2")
    assert x2[0].status == "pass", x2[0].detail


def test_weekly_X3_passes_delegated_to_pit(specialized_db):
    out = run_coverage(specialized_db, tier="weekly")
    x3 = _results_by_id(out, "X3")
    assert x3[0].status == "pass"


def test_weekly_X5_skipped_without_sidecar(specialized_db):
    out = run_coverage(specialized_db, tier="weekly")
    x5 = _results_by_id(out, "X5")
    assert x5[0].status == "skip"


# ---------------------------------------------------------------------------
# Weekly tier — C6/C7/B1/X1 real logic (Phase 3.5-4 follow-up)
# ---------------------------------------------------------------------------
def _build_year_span_db(tmp_path, *, days=("2024-01-01", "2025-06-30")):
    """Two-code fixture with an explicit event_time window for C6/C7/B1."""
    p = tmp_path / "span.sqlite"
    store = SqliteStore(p)
    rows = []
    for code, base in (("8697", 100.0), ("7203", 8000.0)):
        for i, d in enumerate(days):
            close = base + i
            rows.append({
                "Code": code, "Date": d,
                "Open": close, "High": close, "Low": close,
                "Close": close, "Volume": 1000.0, "TurnoverValue": close * 1000,
            })
    store.upsert(
        "jquants_daily_bars",
        normalize_daily_bars(rows, ingested_at=INGESTED),
    )
    store.upsert(
        "jquants_listed_info",
        normalize_listed_info(
            [{"Code": "8697", "Date": "2024-01-01",
              "CompanyName": "JACR", "MarketCode": "0111"},
             {"Code": "7203", "Date": "2024-01-01",
              "CompanyName": "Toyota", "MarketCode": "0111"}],
            ingested_at=INGESTED, snapshot_date="2024-01-01",
        ),
    )
    store.close()
    return p


def test_C6_C7_warn_on_short_span_offline(tmp_path):
    """Days-of-data fixture: offline soft mode warns (does not fail)."""
    p = _build_year_span_db(tmp_path, days=("2025-04-01", "2025-04-04"))
    out = run_coverage(p, tier="weekly", datasets=["equities_bars_daily"])
    c6 = _results_by_id(out, "C6")
    c7 = _results_by_id(out, "C7")
    assert c6 and c7
    # Offline (strict=False) we must not hard-fail even on tiny spans.
    assert all(r.status != "fail" for r in c6), [r.detail for r in c6]
    assert all(r.status != "fail" for r in c7), [r.detail for r in c7]
    # Metrics present so consumers can judge for themselves.
    assert "fill_rate" in c7[0].metrics
    assert "expected_start" in c7[0].metrics


def test_C6_C7_fail_on_short_span_when_strict(tmp_path):
    """Strict mode (live): a days-of-data span is a hard failure."""
    p = _build_year_span_db(tmp_path, days=("2025-04-01", "2025-04-04"))
    out = run_coverage(
        p, tier="weekly", datasets=["equities_bars_daily"],
        strict_live_gates=True,
    )
    c7 = _results_by_id(out, "C7")
    assert c7
    assert c7[0].status == "fail", c7[0].detail
    assert c7[0].metrics["fill_rate"] < 0.2


def test_C6_C7_pass_on_multi_year_span(tmp_path):
    """A near-complete span vs the expected window should pass even offline.

    Trick the fill-rate by pinning ``today`` close to ``expected_start``
    so a modest observed span covers the full expected window.
    """
    # expected_start for equities_bars_daily is 2004-01-05; a two-year
    # observed window with today=2006-01-01 gives fill_rate ≈ 1.0.
    p = _build_year_span_db(
        tmp_path, days=("2004-01-05", "2005-12-31"),
    )
    out = run_coverage(p, tier="weekly", datasets=["equities_bars_daily"],
                       today="2005-12-31T15:30:00+09:00")
    c6 = _results_by_id(out, "C6")
    c7 = _results_by_id(out, "C7")
    assert c6[0].status == "pass", (c6[0].detail, c6[0].metrics)
    assert c7[0].status == "pass", (c7[0].detail, c7[0].metrics)
    assert c7[0].metrics["fill_rate"] >= 0.9


def test_B1_warns_on_short_span_offline(tmp_path):
    p = _build_year_span_db(tmp_path, days=("2025-04-01", "2025-04-04"))
    out = run_coverage(p, tier="weekly")
    b1 = _results_by_id(out, "B1")
    assert len(b1) == 1
    assert b1[0].status == "warn"  # < 1 year span, offline soft
    assert b1[0].dataset == "equities_bars_daily"
    assert b1[0].metrics["observed_years"] < 1.0


def test_B1_fails_on_short_span_when_strict(tmp_path):
    p = _build_year_span_db(tmp_path, days=("2025-04-01", "2025-04-04"))
    out = run_coverage(p, tier="weekly", strict_live_gates=True)
    b1 = _results_by_id(out, "B1")
    assert b1[0].status == "fail"


def test_B1_passes_on_multi_year_span(tmp_path):
    p = _build_year_span_db(
        tmp_path, days=("2024-01-01", "2025-12-31"),
    )
    out = run_coverage(p, tier="weekly")
    b1 = _results_by_id(out, "B1")
    assert b1[0].status == "pass"
    assert b1[0].metrics["observed_years"] >= 1.0


def test_X1_passes_when_bars_match_master(matrix_db):
    """The default fixture has master={8697,7203} and bars cover both."""
    out = run_coverage(matrix_db, tier="weekly")
    x1 = _results_by_id(out, "X1")
    assert len(x1) == 1
    assert x1[0].status == "pass", x1[0].detail
    assert x1[0].metrics["master_count"] == 2
    assert x1[0].metrics["bar_issuer_count"] == 2
    assert x1[0].metrics["common_count"] == 2
    assert x1[0].metrics["coverage"] == 1.0


def test_X1_warns_when_bar_coverage_low(tmp_path):
    """master has 3 codes, only 1 has bars → coverage 0.33 → warn offline."""
    p = tmp_path / "skew.sqlite"
    store = SqliteStore(p)
    store.upsert(
        "jquants_listed_info",
        normalize_listed_info(
            [
                {"Code": "8697", "Date": "2025-03-31",
                 "CompanyName": "A", "MarketCode": "0111"},
                {"Code": "7203", "Date": "2025-03-31",
                 "CompanyName": "B", "MarketCode": "0111"},
                {"Code": "9984", "Date": "2025-03-31",
                 "CompanyName": "C", "MarketCode": "0111"},
            ],
            ingested_at=INGESTED, snapshot_date="2025-03-31",
        ),
    )
    store.upsert(
        "jquants_daily_bars",
        normalize_daily_bars(
            [{"Code": "8697", "Date": "2025-04-01",
              "Open": 100.0, "High": 100.0, "Low": 100.0,
              "Close": 100.0, "Volume": 1.0, "TurnoverValue": 100.0}],
            ingested_at=INGESTED,
        ),
    )
    store.close()
    out = run_coverage(p, tier="weekly")
    x1 = _results_by_id(out, "X1")
    assert x1[0].status == "warn", x1[0].detail
    assert x1[0].metrics["coverage"] < 0.5


def test_X1_does_not_fail_strict_on_tiny_master(tmp_path):
    """Strict bar is meaningless on a 3-code fixture: stays warn."""
    p = tmp_path / "skew.sqlite"
    store = SqliteStore(p)
    store.upsert(
        "jquants_listed_info",
        normalize_listed_info(
            [{"Code": c, "Date": "2025-03-31",
              "CompanyName": c, "MarketCode": "0111"}
             for c in ("8697", "7203", "9984")],
            ingested_at=INGESTED, snapshot_date="2025-03-31",
        ),
    )
    store.upsert(
        "jquants_daily_bars",
        normalize_daily_bars(
            [{"Code": "8697", "Date": "2025-04-01",
              "Open": 100.0, "High": 100.0, "Low": 100.0,
              "Close": 100.0, "Volume": 1.0, "TurnoverValue": 100.0}],
            ingested_at=INGESTED,
        ),
    )
    store.close()
    out = run_coverage(p, tier="weekly", strict_live_gates=True)
    x1 = _results_by_id(out, "X1")
    # master has 3 codes (< 1000), so even strict must NOT hard-fail.
    assert x1[0].status == "warn", x1[0].detail


# ---------------------------------------------------------------------------
# Daily tier — strict-live-gates emits B0 rows on real-data scale
# ---------------------------------------------------------------------------
def test_strict_live_gates_emits_B0_rows_on_daily(specialized_db):
    """When strict_live_gates=True the daily tier surfaces B0 gate rows.

    These rows use ``check_id="B0"`` (Phase-4 shared gate; not part of the
    formal catalog which starts at B1). Each gate emits one row whose
    status mirrors ``cf_platform.live_gates.measure_b0``.
    """
    out = run_coverage(specialized_db, tier="daily", strict_live_gates=True)
    b0 = _results_by_id(out, "B0")
    # Three gates: master, bars issuers, latest-day rows.
    assert len(b0) == 3
    names = {r.dataset for r in b0}
    assert names == {"B0_master", "B0_bars_issuers", "B0_bars_latest_day"}
    # The tiny fixture (2 codes, 4 days) misses every gate → fail.
    assert all(r.status == "fail" for r in b0)


def test_strict_live_gates_off_by_default_daily(specialized_db):
    """Without strict_live_gates, no B0 rows are emitted on the daily tier."""
    out = run_coverage(specialized_db, tier="daily")
    b0 = _results_by_id(out, "B0")
    assert b0 == []


# ---------------------------------------------------------------------------
# b0_pass strict resolution — QP_LIVE=1 implies strict
# ---------------------------------------------------------------------------
def test_b0_pass_treats_qp_live_as_strict(monkeypatch, tmp_path):
    """``b0_pass(db, strict=None)`` reads QP_LIVE=1 as strict=True."""
    from cf_platform.live_gates import b0_pass
    p = _build_year_span_db(tmp_path, days=("2025-04-01", "2025-04-04"))
    monkeypatch.setenv("QP_LIVE", "1")
    ok, results = b0_pass(p)  # strict defaults to None → env lookup
    # Fixture-scale DB misses gates, so under strict it must fail.
    assert ok is False
    assert all(r.name.startswith("B0_") for r in results)


def test_b0_pass_no_qp_live_is_soft(monkeypatch, tmp_path):
    """Without QP_LIVE=1 the same call returns ok=True (soft path)."""
    from cf_platform.live_gates import b0_pass
    p = _build_year_span_db(tmp_path, days=("2025-04-01", "2025-04-04"))
    monkeypatch.delenv("QP_LIVE", raising=False)
    ok, _ = b0_pass(p)
    assert ok is True


# ---------------------------------------------------------------------------
# CLI parser — QP_LIVE=1 default for --strict-live-gates
# ---------------------------------------------------------------------------
def test_cli_strict_live_gates_defaults_off_without_qp_live(monkeypatch):
    """Without QP_LIVE the flag defaults to False (offline green path)."""
    import importlib.util
    monkeypatch.delenv("QP_LIVE", raising=False)
    cli_path = _REPO / "scripts" / "run_phase35_validation.py"
    spec = importlib.util.spec_from_file_location("run_phase35_validation", cli_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    args = mod._build_parser().parse_args(["--db", "x.sqlite"])
    # main() resolves None → False when QP_LIVE unset; the parser itself
    # surfaces None so the env check happens at call time.
    assert args.strict_live_gates is None


def test_cli_strict_live_gates_defaults_on_with_qp_live(monkeypatch, tmp_path):
    """When QP_LIVE=1, main() resolves strict=True even without the flag."""
    import importlib.util
    cli_path = _REPO / "scripts" / "run_phase35_validation.py"
    spec = importlib.util.spec_from_file_location("run_phase35_validation", cli_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    # Build an empty DB so run_coverage emits failures (not a crash).
    p = tmp_path / "empty.sqlite"
    SqliteStore(p).close()
    monkeypatch.setenv("QP_LIVE", "1")

    # Spy on the resolved flag by patching run_coverage.
    captured: dict = {}

    def fake_run(db_path, **kw):
        captured["strict_live_gates"] = kw.get("strict_live_gates")
        return []

    monkeypatch.setattr(mod, "run_coverage", fake_run)
    rc = mod.main(["--db", str(p), "--tier", "daily"])
    assert rc == 0
    assert captured["strict_live_gates"] is True


def test_cli_no_strict_flag_overrides_qp_live(monkeypatch, tmp_path):
    """``--no-strict-live-gates`` overrides QP_LIVE=1."""
    import importlib.util
    cli_path = _REPO / "scripts" / "run_phase35_validation.py"
    spec = importlib.util.spec_from_file_location("run_phase35_validation", cli_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)

    p = tmp_path / "empty.sqlite"
    SqliteStore(p).close()
    monkeypatch.setenv("QP_LIVE", "1")

    captured: dict = {}

    def fake_run(db_path, **kw):
        captured["strict_live_gates"] = kw.get("strict_live_gates")
        return []

    monkeypatch.setattr(mod, "run_coverage", fake_run)
    rc = mod.main(["--db", str(p), "--tier", "daily",
                   "--no-strict-live-gates"])
    assert rc == 0
    assert captured["strict_live_gates"] is False
