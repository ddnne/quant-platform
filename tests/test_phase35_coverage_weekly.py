"""Phase 3.5 — weekly-tier coverage on bars / calendar / master.

C6/C7/B1 span, X1 universe overlap, and weekly emit/X2/X3/X5. Shared
builders: ``tests/phase35_matrix_util.py``.

Offline-only: no network, no Cloudflare, no API keys.
"""

from __future__ import annotations

from cf_platform.ingest_premium import matrix
from cf_platform.ingest_premium.coverage import run_coverage
from ingestion.jquants.normalize import (
    normalize_daily_bars,
    normalize_listed_info,
)
from storage.sqlite_store import SqliteStore

from tests.phase35_matrix_util import (
    INGESTED,
    _build_year_span_db,
    _results_by_id,
    matrix_db,
    specialized_db,
)


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
    # expected_start for equities_bars_daily is 2008-05-01 (observed floor);
    # a ~2y observed window pinned near start gives fill_rate ≈ 1.0.
    p = _build_year_span_db(
        tmp_path, days=("2008-05-01", "2010-04-30"),
    )
    out = run_coverage(p, tier="weekly", datasets=["equities_bars_daily"],
                       today="2010-04-30T15:30:00+09:00")
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
