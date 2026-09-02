"""Shared fixtures for core-engine tests: build a tiny PIT DB offline.

Not collected by pytest (no ``test_`` prefix). Provides helpers to seed a
structured SQLite with a market calendar, equity master and daily bars using
``storage.sqlite_store.SqliteStore`` (the writer), so the engine can then read
them back exclusively through ``pit``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from data_contracts.identity import natural_key
from ops.receipt_product import (
    canonical_product_artifact_bytes,
    product_artifact_digest,
)
from storage.sqlite_store import SqliteStore

# Four consecutive weekdays in April 2025 (post 2024-11-05 close-time change).
TRADING_DAYS = ["2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04"]
CODES = ["8697", "1332"]


def close_iso(date: str) -> str:
    """Engine's session-close ``as_of`` for ``date`` (2025 -> 15:30 JST)."""
    return f"{date}T15:30:00+09:00"


def morning_iso(date: str) -> str:
    return f"{date}T11:30:00+09:00"


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
    adjustment_prices: dict[str, dict[str, float]] | None = None,
    morning_adjustment_prices: dict[str, dict[str, float]] | None = None,
    afternoon_adjustment_prices: dict[str, dict[str, float]] | None = None,
    morning_adjustment_volumes: dict[str, dict[str, float]] | None = None,
    afternoon_adjustment_volumes: dict[str, dict[str, float]] | None = None,
    morning_turnover_values: dict[str, dict[str, float]] | None = None,
    turnover_values: dict[str, dict[str, float]] | None = None,
    market_caps: dict[str, dict[str, float]] | None = None,
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
                    "adjustment_close": (
                        adjustment_prices.get(code, {}).get(d)
                        if adjustment_prices is not None
                        else None
                    ),
                    "volume": 1000.0,
                    "turnover_value": (
                        turnover_values.get(code, {}).get(d)
                        if turnover_values is not None
                        else None
                    ),
                    "market_cap": (
                        market_caps.get(code, {}).get(d)
                        if market_caps is not None
                        else None
                    ),
                    "morning_adjustment_close": (
                        morning_adjustment_prices.get(code, {}).get(d)
                        if morning_adjustment_prices is not None
                        else None
                    ),
                    "afternoon_adjustment_close": (
                        afternoon_adjustment_prices.get(code, {}).get(d)
                        if afternoon_adjustment_prices is not None
                        else None
                    ),
                    "morning_adjustment_volume": (
                        morning_adjustment_volumes.get(code, {}).get(d)
                        if morning_adjustment_volumes is not None
                        else None
                    ),
                    "afternoon_adjustment_volume": (
                        afternoon_adjustment_volumes.get(code, {}).get(d)
                        if afternoon_adjustment_volumes is not None
                        else None
                    ),
                    "morning_turnover_value": (
                        morning_turnover_values.get(code, {}).get(d)
                        if morning_turnover_values is not None
                        else None
                    ),
                }
            )
    return rows


def rising_prices(codes: list[str], days: list[str], start: float = 100.0) -> dict:
    """Deterministic rising closes: +1.0 JPY per code per day."""
    prices: dict[str, dict[str, float]] = {}
    for ci, c in enumerate(codes):
        prices[c] = {d: start + ci + i for i, d in enumerate(days)}
    return prices



def write_snapshot_observation_clock(store: SqliteStore, observed_through: str) -> None:
    from pit.query import normalize_as_of

    canonical = normalize_as_of(observed_through)
    store._conn.execute("DROP TABLE IF EXISTS snapshot_observation_clock")
    store._conn.execute(
        "CREATE TABLE snapshot_observation_clock ("
        "singleton INTEGER NOT NULL PRIMARY KEY CHECK (singleton = 1), "
        "observed_through TEXT NOT NULL CHECK (length(observed_through) >= 25))"
    )
    store._conn.execute(
        "INSERT INTO snapshot_observation_clock(singleton, observed_through) "
        "VALUES (1, ?)",
        (canonical,),
    )
    store._conn.commit()

def seed_db(
    tmp_path: Path,
    *,
    codes: list[str] | None = None,
    days: list[str] | None = None,
    prices: dict | None = None,
    bar_available_at_for: dict[str, str] | None = None,
    adjustment_prices: dict | None = None,
    morning_adjustment_prices: dict | None = None,
    afternoon_adjustment_prices: dict | None = None,
    morning_adjustment_volumes: dict | None = None,
    afternoon_adjustment_volumes: dict | None = None,
    morning_turnover_values: dict | None = None,
    turnover_values: dict | None = None,
    market_caps: dict | None = None,
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
        _bar_rows(
            prices,
            available_at_for=bar_available_at_for,
            adjustment_prices=adjustment_prices,
            morning_adjustment_prices=morning_adjustment_prices,
            afternoon_adjustment_prices=afternoon_adjustment_prices,
            morning_adjustment_volumes=morning_adjustment_volumes,
            afternoon_adjustment_volumes=afternoon_adjustment_volumes,
            morning_turnover_values=morning_turnover_values,
            turnover_values=turnover_values,
            market_caps=market_caps,
        ),
    )
    last = (days or TRADING_DAYS)[-1]
    write_snapshot_observation_clock(store, close_iso(last))
    store.close()
    return path


def seed_governed_am_pm_session_db(
    tmp_path: Path,
    *,
    codes: list[str] | None = None,
    days: list[str] | None = None,
    morning_prices: dict | None = None,
    afternoon_prices: dict | None = None,
) -> Path:
    """Positive Controlled fixture: AM row at 11:30, PM revision at close."""

    codes = codes or CODES
    days = days or TRADING_DAYS
    morning_prices = morning_prices or rising_prices(codes, days, start=100.0)
    afternoon_prices = afternoon_prices or rising_prices(codes, days, start=100.0)
    path = tmp_path / "ing.sqlite"
    store = SqliteStore(path)
    store.upsert("jquants_market_calendar", _calendar_rows(days))
    store.upsert("jquants_listed_info", _master_rows(codes))
    am_rows: list[dict] = []
    pm_rows: list[dict] = []
    for code in codes:
        for day in days:
            morning = float(morning_prices[code][day])
            afternoon = float(afternoon_prices[code][day])
            am_rows.append(
                {
                    "source": "jquants",
                    "code": code,
                    "date": day,
                    "event_time": morning_iso(day),
                    "available_at": morning_iso(day),
                    "ingested_at": morning_iso(day),
                    "open": morning,
                    "high": morning,
                    "low": morning,
                    "close": morning,
                    "volume": 1000.0,
                    "morning_adjustment_close": morning,
                    "morning_adjustment_volume": 500.0,
                    "afternoon_adjustment_close": None,
                }
            )
            pm_rows.append(
                {
                    "source": "jquants",
                    "code": code,
                    "date": day,
                    "event_time": close_iso(day),
                    "available_at": close_iso(day),
                    "ingested_at": close_iso(day),
                    "open": morning,
                    "high": afternoon,
                    "low": morning,
                    "close": afternoon,
                    "volume": 1000.0,
                    "morning_adjustment_close": morning,
                    "morning_adjustment_volume": 500.0,
                    "afternoon_adjustment_close": afternoon,
                    "afternoon_adjustment_volume": 1000.0,
                }
            )
    store.upsert("jquants_daily_bars", am_rows)
    store.upsert("jquants_daily_bars", pm_rows)
    am_catalog: list[dict] = []
    for code in codes:
        for day in days:
            morning = float(morning_prices[code][day])
            event = morning_iso(day)
            payload = {
                "Code": code,
                "Date": day,
                "MAdjC": morning,
            }
            payload_text = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            am_catalog.append(
                {
                    "source": "jquants",
                    "dataset": "equities_bars_daily_am",
                    "natural_key": natural_key(payload, "equities_bars_daily_am"),
                    "event_time": event,
                    "available_at": event,
                    "ingested_at": event,
                    "payload": payload_text,
                    "raw_payload": "",
                }
            )
    store.upsert("jquants_records", am_catalog)
    daily_catalog: list[dict] = []
    for code in codes:
        for day in days:
            payload = {
                "Code": code,
                "Date": day,
                "MAdjC": float(morning_prices[code][day]),
                "AAdjC": float(afternoon_prices[code][day]),
            }
            event = close_iso(day)
            daily_catalog.append(
                {
                    "source": "jquants",
                    "dataset": "equities_bars_daily",
                    "natural_key": natural_key(payload, "equities_bars_daily"),
                    "event_time": event,
                    "available_at": event,
                    "ingested_at": event,
                    "payload": json.dumps(
                        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    ),
                    "raw_payload": "",
                }
            )
    store.upsert("jquants_records", daily_catalog)
    for run_id, dataset_id, suffix in (
        (1, "equities_bars_daily", "daily"),
        (2, "equities_bars_daily_am", "am"),
    ):
        stored = store._conn.execute(
            "SELECT source, dataset, natural_key, event_time, available_at, "
            "ingested_at, payload, COALESCE(raw_payload, '') AS raw_payload "
            "FROM jquants_records WHERE dataset=? ORDER BY natural_key",
            (dataset_id,),
        ).fetchall()
        product_rows: list[dict[str, str]] = []
        for row in stored:
            payload_raw = row["payload"]
            payload_obj = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
            product_rows.append(
                {
                    "source": str(row["source"]),
                    "dataset": str(row["dataset"]),
                    "natural_key": str(row["natural_key"]),
                    "event_time": str(row["event_time"]),
                    "available_at": str(row["available_at"]),
                    "ingested_at": str(row["ingested_at"]),
                    "payload": json.dumps(
                        payload_obj,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                    "raw_payload": str(row["raw_payload"] or ""),
                }
            )
        artifact_body = canonical_product_artifact_bytes(product_rows).decode("utf-8")
        artifact_digest = product_artifact_digest(product_rows)
        # Offline fixture seal only. This is not a READY/promotable snapshot.
        store._conn.execute(
            "INSERT INTO receipt_product_materializations ("
            "operation_id, run_id, source, dataset, segment_id, artifact_key, "
            "artifact_digest, artifact_body, row_count, byte_count, manifest_key, "
            "manifest_digest, raw_manifest_key, raw_manifest_digest, raw_page_count, "
            "raw_row_count, raw_bytes, committed_at"
            ") VALUES (?, ?, 'jquants', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 1, ?)",
            (
                f"offline-fixture-{suffix}-product",
                run_id,
                dataset_id,
                f"offline-fixture-{suffix}",
                f"offline-fixture-{suffix}-artifact",
                artifact_digest,
                artifact_body,
                len(product_rows),
                len(artifact_body.encode("utf-8")),
                f"offline-fixture-{suffix}-manifest",
                artifact_digest,
                f"offline-fixture-{suffix}-raw-manifest",
                artifact_digest,
                close_iso((days or TRADING_DAYS)[-1]),
            ),
        )
    last = (days or TRADING_DAYS)[-1]
    write_snapshot_observation_clock(store, close_iso(last))
    store.close()
    return path
