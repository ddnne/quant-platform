"""Shared fixtures for core-engine tests: build a tiny PIT DB offline.

Not collected by pytest (no ``test_`` prefix). Provides helpers to seed a
structured SQLite with a market calendar, equity master and daily bars using
``storage.sqlite_store.SqliteStore`` (the writer), so the engine can then read
them back exclusively through ``pit``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from storage.sqlite_store import SqliteStore

# Four consecutive weekdays in April 2025 (post 2024-11-05 close-time change).
TRADING_DAYS = ["2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04"]
CODES = ["8697", "1332"]


def close_iso(date: str) -> str:
    """Engine's session-close ``as_of`` for ``date`` (2025 -> 15:30 JST)."""
    return f"{date}T15:30:00+09:00"


def open_iso(date: str) -> str:
    return f"{date}T09:00:00+09:00"


def _calendar_rows(days: Iterable[str], *, available_at: str | None = None) -> list[dict]:
    avail = available_at or "2025-01-01T00:00:00+09:00"
    return [
        {
            "source": "jquants",
            "date": d,
            "event_time": f"{d}T09:00:00+09:00",
            "available_at": avail,
            "ingested_at": avail,
            "holiday_division": "1",  # trading day
        }
        for d in days
    ]


def _master_rows(codes: Iterable[str], *, available_at: str | None = None) -> list[dict]:
    avail = available_at or "2025-01-01T00:00:00+09:00"
    return [
        {
            "source": "jquants",
            "code": c,
            "snapshot_date": "2025-03-31",
            "event_time": "2025-03-31T09:00:00+09:00",
            "available_at": avail,
            "ingested_at": avail,
            "company_name": f"Co-{c}",
            "sector_17_code": "1",
            "market_code": "1",
        }
        for c in codes
    ]


def _bar_rows(
    prices: dict[str, dict[str, float]],
    *,
    available_at_for: dict[str, str] | None = None,
) -> list[dict]:
    """``prices[code][date] = close``. ``available_at_for[date]`` overrides pub time."""
    rows: list[dict] = []
    for code, by_date in prices.items():
        for d, close in by_date.items():
            avail = (
                available_at_for.get(d, close_iso(d))
                if available_at_for
                else close_iso(d)
            )
            rows.append(
                {
                    "source": "jquants",
                    "code": code,
                    "date": d,
                    "event_time": close_iso(d),
                    "available_at": avail,
                    "ingested_at": avail,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000.0,
                }
            )
    return rows


def rising_prices(codes: list[str], days: list[str], start: float = 100.0) -> dict:
    """Deterministic rising closes: +1.0 JPY per code per day."""
    prices: dict[str, dict[str, float]] = {}
    for ci, c in enumerate(codes):
        prices[c] = {d: start + ci + i for i, d in enumerate(days)}
    return prices


def seed_db(
    tmp_path: Path,
    *,
    codes: list[str] | None = None,
    days: list[str] | None = None,
    prices: dict | None = None,
    bar_available_at_for: dict[str, str] | None = None,
    master_available_at: str | None = None,
) -> Path:
    """Create a structured DB with calendar + master + bars; return its path."""
    codes = codes or CODES
    days = days or TRADING_DAYS
    prices = prices or rising_prices(codes, days)
    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    store.upsert("jquants_market_calendar", _calendar_rows(days))
    store.upsert("jquants_listed_info", _master_rows(codes, available_at=master_available_at))
    store.upsert(
        "jquants_daily_bars",
        _bar_rows(prices, available_at_for=bar_available_at_for),
    )
    store.close()
    return path
