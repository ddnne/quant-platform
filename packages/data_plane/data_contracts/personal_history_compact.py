"""Closed compact-v7 SQLite surface for personal DRAFT history.

Readers classify a connection as ``legacy``, ``compact``, ``invalid``, or
``mixed``.  Extra columns and column order are tolerated; required columns
must still match production-declared type, NOT NULL, and PK ordinal by
name, and both compact objects must be real WITHOUT ROWID tables.  The
trusted builder still stamps v7 only after its DDL shape matches exactly.
"""

from __future__ import annotations

import sqlite3
from typing import Literal


CompactHistoryState = Literal["legacy", "compact", "invalid", "mixed"]

PERSONAL_HISTORY_COMPACT_FORMAT = "personal-draft-history/v7"
PERSONAL_HISTORY_COMPACT_COMPLETE_STATUS = "COMPLETE_DRAFT"
PERSONAL_HISTORY_MANIFEST_TABLE = "personal_history_manifest"
PERSONAL_HISTORY_COMPACT_MASTER_TABLE = "personal_history_compact_master"
PERSONAL_HISTORY_COMPACT_BARS_TABLE = "personal_history_compact_bars"
PERSONAL_HISTORY_COMPACT_TABLES: tuple[str, ...] = (
    PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
    PERSONAL_HISTORY_COMPACT_BARS_TABLE,
)
PERSONAL_HISTORY_COMPACT_MASTER_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS personal_history_compact_master (
    snapshot_date TEXT NOT NULL,
    code TEXT NOT NULL,
    event_time TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    market_code TEXT,
    sector_17_code TEXT,
    sector_33_code TEXT,
    scale_category TEXT,
    source_scale_category TEXT,
    PRIMARY KEY (snapshot_date, code)
) WITHOUT ROWID
"""
PERSONAL_HISTORY_COMPACT_BARS_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS personal_history_compact_bars (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    event_time TEXT NOT NULL,
    available_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    turnover_value REAL,
    adjustment_close REAL,
    adjustment_volume REAL,
    morning_adjustment_close REAL,
    afternoon_adjustment_close REAL,
    morning_turnover_value REAL,
    afternoon_turnover_value REAL,
    morning_adjustment_volume REAL,
    afternoon_adjustment_volume REAL,
    market_cap REAL,
    PRIMARY KEY (code, date)
) WITHOUT ROWID
"""
PERSONAL_HISTORY_COMPACT_CREATE_SQL: tuple[tuple[str, str], ...] = (
    (
        PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
        PERSONAL_HISTORY_COMPACT_MASTER_CREATE_SQL,
    ),
    (
        PERSONAL_HISTORY_COMPACT_BARS_TABLE,
        PERSONAL_HISTORY_COMPACT_BARS_CREATE_SQL,
    ),
)
# name, declared type, NOT NULL flag, PK ordinal (0 if not in the PK)
_ColumnContract = tuple[str, str, int, int]


def _column_contracts_from_create_sql(
    create_sql: str, table: str
) -> tuple[_ColumnContract, ...]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(create_sql)
        return tuple(
            (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
            for row in connection.execute(f"PRAGMA table_info({table})")
        )
    finally:
        connection.close()


PERSONAL_HISTORY_COMPACT_MASTER_COLUMN_CONTRACT: tuple[_ColumnContract, ...] = (
    _column_contracts_from_create_sql(
        PERSONAL_HISTORY_COMPACT_MASTER_CREATE_SQL,
        PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
    )
)
PERSONAL_HISTORY_COMPACT_BARS_COLUMN_CONTRACT: tuple[_ColumnContract, ...] = (
    _column_contracts_from_create_sql(
        PERSONAL_HISTORY_COMPACT_BARS_CREATE_SQL,
        PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    )
)
PERSONAL_HISTORY_COMPACT_MASTER_COLUMNS: tuple[str, ...] = tuple(
    name for name, _typ, _notnull, _pk in PERSONAL_HISTORY_COMPACT_MASTER_COLUMN_CONTRACT
)
PERSONAL_HISTORY_COMPACT_BARS_COLUMNS: tuple[str, ...] = tuple(
    name for name, _typ, _notnull, _pk in PERSONAL_HISTORY_COMPACT_BARS_COLUMN_CONTRACT
)

_TYPED_EQUITY_TABLES: tuple[str, ...] = (
    "jquants_listed_info",
    "jquants_listed_info_revisions",
    "jquants_daily_bars",
    "jquants_daily_bars_revisions",
)
_GENERIC_EQUITY_TABLES: tuple[str, ...] = (
    "jquants_records",
    "jquants_records_revisions",
)
_GENERIC_EQUITY_DATASETS: tuple[str, ...] = (
    "equities_master",
    "equities_bars_daily",
)


def compact_history_state(connection: sqlite3.Connection) -> CompactHistoryState:
    """Classify one SQLite connection's compact-v7 representation."""

    try:
        return _compact_history_state(connection)
    except sqlite3.Error:
        return "invalid"


def _compact_history_state(connection: sqlite3.Connection) -> CompactHistoryState:
    objects = _compact_named_objects(connection)
    marker, status = _singleton_manifest(connection)
    if marker != PERSONAL_HISTORY_COMPACT_FORMAT and not objects:
        return "legacy"
    if not _is_readable_compact_schema(
        connection, marker=marker, status=status, objects=objects
    ):
        return "invalid"
    if _has_legacy_equity_facts(connection):
        return "mixed"
    return "compact"


def _compact_named_objects(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        "SELECT name, type FROM sqlite_master WHERE name IN (?, ?)",
        PERSONAL_HISTORY_COMPACT_TABLES,
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _singleton_manifest(
    connection: sqlite3.Connection,
) -> tuple[str | None, str | None]:
    listing = connection.execute(
        "SELECT type FROM sqlite_master WHERE name = ?",
        (PERSONAL_HISTORY_MANIFEST_TABLE,),
    ).fetchone()
    if listing is None or str(listing[0]) != "table":
        return None, None
    columns = {
        str(info[1])
        for info in connection.execute(
            f"PRAGMA table_info({PERSONAL_HISTORY_MANIFEST_TABLE})"
        )
    }
    if "format" not in columns:
        raise sqlite3.Error("personal_history_manifest is missing format")
    row = connection.execute(
        "SELECT format FROM personal_history_manifest WHERE singleton = 1"
    ).fetchone()
    if row is None or row[0] is None:
        return None, None
    marker = str(row[0])
    if "status" not in columns:
        return marker, None
    status_row = connection.execute(
        "SELECT status FROM personal_history_manifest WHERE singleton = 1"
    ).fetchone()
    if status_row is None or status_row[0] is None:
        return marker, None
    return marker, str(status_row[0])


def _is_readable_compact_schema(
    connection: sqlite3.Connection,
    *,
    marker: str | None,
    status: str | None,
    objects: dict[str, str],
) -> bool:
    if (
        marker != PERSONAL_HISTORY_COMPACT_FORMAT
        or status != PERSONAL_HISTORY_COMPACT_COMPLETE_STATUS
    ):
        return False
    if any(
        objects.get(table) != "table" for table in PERSONAL_HISTORY_COMPACT_TABLES
    ):
        return False
    return _required_columns_match_production(
        connection,
        PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
        PERSONAL_HISTORY_COMPACT_MASTER_COLUMN_CONTRACT,
    ) and _required_columns_match_production(
        connection,
        PERSONAL_HISTORY_COMPACT_BARS_TABLE,
        PERSONAL_HISTORY_COMPACT_BARS_COLUMN_CONTRACT,
    )


def _real_table_columns(
    connection: sqlite3.Connection, name: str
) -> tuple[str, ...] | None:
    listing = connection.execute(
        "SELECT type FROM sqlite_master WHERE name = ?",
        (name,),
    ).fetchone()
    if listing is None or str(listing[0]) != "table":
        return None
    return tuple(
        str(info[1]) for info in connection.execute(f"PRAGMA table_info({name})")
    )


def _required_columns_match_production(
    connection: sqlite3.Connection,
    table: str,
    required: tuple[_ColumnContract, ...],
) -> bool:
    listing = connection.execute(
        "SELECT type, wr FROM pragma_table_list WHERE schema='main' AND name=?",
        (table,),
    ).fetchone()
    if listing is None or str(listing[0]) != "table" or int(listing[1]) != 1:
        return False
    by_name = {
        str(info[1]): (str(info[2]), int(info[3]), int(info[5]))
        for info in connection.execute(f"PRAGMA table_info({table})")
    }
    return all(
        by_name.get(name) == (declared_type, notnull, pk)
        for name, declared_type, notnull, pk in required
    )


def _has_legacy_equity_facts(connection: sqlite3.Connection) -> bool:
    for table in _TYPED_EQUITY_TABLES:
        if _real_table_columns(connection, table) is None:
            continue
        if connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
            return True
    datasets = ",".join("?" for _ in _GENERIC_EQUITY_DATASETS)
    for table in _GENERIC_EQUITY_TABLES:
        if _real_table_columns(connection, table) is None:
            continue
        found = connection.execute(
            f"SELECT 1 FROM {table} WHERE dataset IN ({datasets}) LIMIT 1",
            _GENERIC_EQUITY_DATASETS,
        ).fetchone()
        if found is not None:
            return True
    return False
