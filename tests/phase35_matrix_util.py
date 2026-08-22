"""Shared offline fixtures for Phase 3.5 coverage-matrix tests.

Not collected by pytest (no ``test_`` prefix). Builders use the real
:class:`storage.sqlite_store.SqliteStore` so the coverage runner sees the
same specialized / generic layouts as local ingest and CF sync.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cf_platform.ingest_premium.coverage import CheckResult
from ingestion.jquants.normalize import (
    normalize_daily_bars,
    normalize_generic,
    normalize_listed_info,
    normalize_market_calendar,
)
from storage.sqlite_store import SqliteStore

_REPO = Path(__file__).resolve().parents[1]
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


def _results_by_id(results: list[CheckResult], check_id: str) -> list[CheckResult]:
    return [r for r in results if r.check_id == check_id]


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
