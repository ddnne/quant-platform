"""Shared compact-v8 SQLite fixtures. Prefer production CREATE SQL."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from data_contracts.identity import session_close_jst
from data_contracts.personal_history_compact import (
    PERSONAL_HISTORY_COMPACT_BARS_COLUMNS,
    PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    PERSONAL_HISTORY_COMPACT_COMPLETE_STATUS,
    PERSONAL_HISTORY_COMPACT_CREATE_SQL,
    PERSONAL_HISTORY_COMPACT_FORMAT,
    PERSONAL_HISTORY_COMPACT_MASTER_COLUMNS,
    PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
    PERSONAL_HISTORY_MANIFEST_TABLE,
)

_UNSET = object()


def stamp_compact_manifest(
    connection: sqlite3.Connection,
    format_name: str = PERSONAL_HISTORY_COMPACT_FORMAT,
    *,
    status: str = PERSONAL_HISTORY_COMPACT_COMPLETE_STATUS,
    observed_through: str | None = "2099-01-01T00:00:00+09:00",
    revision_window_calendar_days: int = 40,
    revision_coverage: str = "WINDOW_COMPLETE",
) -> None:
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {PERSONAL_HISTORY_MANIFEST_TABLE} ("
        "singleton INTEGER PRIMARY KEY, format TEXT, status TEXT, "
        "observed_through TEXT, revision_window_calendar_days INTEGER, "
        "revision_coverage TEXT)"
    )
    columns = {
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({PERSONAL_HISTORY_MANIFEST_TABLE})"
        )
    }
    if "observed_through" not in columns:
        connection.execute(
            f"ALTER TABLE {PERSONAL_HISTORY_MANIFEST_TABLE} "
            "ADD COLUMN observed_through TEXT"
        )
    if "revision_window_calendar_days" not in columns:
        connection.execute(
            f"ALTER TABLE {PERSONAL_HISTORY_MANIFEST_TABLE} "
            "ADD COLUMN revision_window_calendar_days INTEGER"
        )
    if "revision_coverage" not in columns:
        connection.execute(
            f"ALTER TABLE {PERSONAL_HISTORY_MANIFEST_TABLE} "
            "ADD COLUMN revision_coverage TEXT"
        )
    connection.execute(
        f"INSERT OR REPLACE INTO {PERSONAL_HISTORY_MANIFEST_TABLE}"
        "(singleton, format, status, observed_through, "
        "revision_window_calendar_days, revision_coverage) VALUES (1, ?, ?, ?, ?, ?)",
        (
            format_name,
            status,
            observed_through,
            revision_window_calendar_days,
            revision_coverage,
        ),
    )


def create_compact_tables(connection: sqlite3.Connection) -> None:
    for _table, create_sql in PERSONAL_HISTORY_COMPACT_CREATE_SQL:
        connection.execute(create_sql)


def create_compact_reader_tables(
    connection: sqlite3.Connection,
    *,
    master_columns: tuple[str, ...] = PERSONAL_HISTORY_COMPACT_MASTER_COLUMNS,
    bars_columns: tuple[str, ...] = PERSONAL_HISTORY_COMPACT_BARS_COLUMNS,
) -> None:
    connection.execute(
        f"CREATE TABLE {PERSONAL_HISTORY_COMPACT_MASTER_TABLE} ("
        + ", ".join(f"{name} TEXT" for name in master_columns)
        + ")"
    )
    connection.execute(
        f"CREATE TABLE {PERSONAL_HISTORY_COMPACT_BARS_TABLE} ("
        + ", ".join(f"{name} TEXT" for name in bars_columns)
        + ")"
    )


def install_compact_schema(
    connection: sqlite3.Connection,
    *,
    format_name: str = PERSONAL_HISTORY_COMPACT_FORMAT,
    strict: bool = True,
    master_columns: tuple[str, ...] = PERSONAL_HISTORY_COMPACT_MASTER_COLUMNS,
    bars_columns: tuple[str, ...] = PERSONAL_HISTORY_COMPACT_BARS_COLUMNS,
) -> None:
    stamp_compact_manifest(connection, format_name)
    if strict:
        create_compact_tables(connection)
        return
    create_compact_reader_tables(
        connection, master_columns=master_columns, bars_columns=bars_columns
    )


def insert_compact_master(
    connection: sqlite3.Connection,
    *,
    snapshot_date: str,
    code: str = "1301",
    available_at: Any = _UNSET,
    event_time: Any = _UNSET,
    ingested_at: Any = _UNSET,
    market_code: str = "0111",
    sector_17_code: str = "1",
    sector_33_code: str = "50",
    scale_category: str = "TOPIX Mid400",
    source_scale_category: str = "Mid400",
    extra: Mapping[str, Any] | None = None,
) -> None:
    stamp = f"{snapshot_date}T08:00:00+09:00"
    values: dict[str, Any] = {
        "snapshot_date": snapshot_date,
        "code": code,
        "event_time": stamp if event_time is _UNSET else event_time,
        "available_at": stamp if available_at is _UNSET else available_at,
        "ingested_at": stamp if ingested_at is _UNSET else ingested_at,
        "market_code": market_code,
        "sector_17_code": sector_17_code,
        "sector_33_code": sector_33_code,
        "scale_category": scale_category,
        "source_scale_category": source_scale_category,
    }
    if extra:
        values.update(extra)
    present = tuple(
        column
        for row in connection.execute(
            f"PRAGMA table_info({PERSONAL_HISTORY_COMPACT_MASTER_TABLE})"
        )
        if (column := str(row[1])) in values
    )
    connection.execute(
        f"INSERT INTO {PERSONAL_HISTORY_COMPACT_MASTER_TABLE} ("
        + ",".join(present)
        + ") VALUES ("
        + ",".join("?" for _ in present)
        + ")",
        tuple(values[name] for name in present),
    )


def insert_compact_bar(
    connection: sqlite3.Connection,
    *,
    day: str,
    code: str = "1301",
    close: float = 100.0,
    available_at: Any = _UNSET,
    event_time: Any = _UNSET,
    ingested_at: Any = _UNSET,
    volume: float = 1000.0,
    turnover_value: float = 10000.0,
    adjustment_close: Any = _UNSET,
    adjustment_volume: Any = _UNSET,
    morning_adjustment_close: Any = _UNSET,
    afternoon_adjustment_close: Any = _UNSET,
    morning_turnover_value: Any = _UNSET,
    afternoon_turnover_value: Any = _UNSET,
    morning_adjustment_volume: Any = _UNSET,
    afternoon_adjustment_volume: Any = _UNSET,
    market_cap: float = 1.0,
    extra: Mapping[str, Any] | None = None,
) -> None:
    stamp = session_close_jst(day)
    values: dict[str, Any] = {
        "code": code,
        "date": day,
        "event_time": stamp if event_time is _UNSET else event_time,
        "available_at": stamp if available_at is _UNSET else available_at,
        "ingested_at": stamp if ingested_at is _UNSET else ingested_at,
        "close": close,
        "volume": volume,
        "turnover_value": turnover_value,
        "adjustment_close": close if adjustment_close is _UNSET else adjustment_close,
        "adjustment_volume": (
            volume if adjustment_volume is _UNSET else adjustment_volume
        ),
        "morning_adjustment_close": (
            close if morning_adjustment_close is _UNSET else morning_adjustment_close
        ),
        "afternoon_adjustment_close": (
            close if afternoon_adjustment_close is _UNSET else afternoon_adjustment_close
        ),
        "morning_turnover_value": (
            5000.0 if morning_turnover_value is _UNSET else morning_turnover_value
        ),
        "afternoon_turnover_value": (
            5000.0 if afternoon_turnover_value is _UNSET else afternoon_turnover_value
        ),
        "morning_adjustment_volume": (
            500.0 if morning_adjustment_volume is _UNSET else morning_adjustment_volume
        ),
        "afternoon_adjustment_volume": (
            500.0 if afternoon_adjustment_volume is _UNSET else afternoon_adjustment_volume
        ),
        "market_cap": market_cap,
    }
    if extra:
        values.update(extra)
    present = tuple(
        column
        for row in connection.execute(
            f"PRAGMA table_info({PERSONAL_HISTORY_COMPACT_BARS_TABLE})"
        )
        if (column := str(row[1])) in values
    )
    connection.execute(
        f"INSERT INTO {PERSONAL_HISTORY_COMPACT_BARS_TABLE} ("
        + ",".join(present)
        + ") VALUES ("
        + ",".join("?" for _ in present)
        + ")",
        tuple(values[name] for name in present),
    )
