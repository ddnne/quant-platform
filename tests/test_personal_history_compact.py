"""Compact-v7 SQLite contract: one classifier, no consumer copies."""

from __future__ import annotations

import sqlite3

from data_contracts.identity import session_close_jst
from data_contracts.personal_history_compact import (
    DEFAULT_MIN_OBSERVED_BAR_RATIO,
    DEFAULT_TINY_MISSING_BAR_RATIO,
    DEFAULT_TINY_MISSING_OBSERVED_BARS,
    PERSONAL_HISTORY_COMPACT_BARS_CREATE_SQL,
    PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    PERSONAL_HISTORY_COMPACT_COMPLETE_STATUS,
    PERSONAL_HISTORY_COMPACT_CREATE_SQL,
    PERSONAL_HISTORY_COMPACT_FORMAT,
    PERSONAL_HISTORY_COMPACT_MASTER_COLUMNS,
    PERSONAL_HISTORY_COMPACT_MASTER_CREATE_SQL,
    PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
    allowed_missing_observed_bars,
    compact_history_state,
)
from personal_history_compact_support import (
    create_compact_reader_tables,
    create_compact_tables,
    insert_compact_bar,
    install_compact_schema,
    stamp_compact_manifest,
)


def _state(build) -> str:
    connection = sqlite3.connect(":memory:")
    try:
        build(connection)
        connection.commit()
        return compact_history_state(connection)
    finally:
        connection.close()


def test_empty_database_is_legacy() -> None:
    assert _state(lambda _conn: None) == "legacy"


def test_v6_marker_without_compact_objects_is_legacy() -> None:
    def build(connection: sqlite3.Connection) -> None:
        stamp_compact_manifest(connection, "personal-draft-history/v6")

    assert _state(build) == "legacy"


def test_exact_v7_schema_is_compact() -> None:
    assert _state(install_compact_schema) == "compact"


def _create_reordered_production_tables(connection: sqlite3.Connection) -> None:
    probe = sqlite3.connect(":memory:")
    try:
        for table, create_sql in PERSONAL_HISTORY_COMPACT_CREATE_SQL:
            probe.execute(create_sql)
            infos = list(probe.execute(f"PRAGMA table_info({table})"))
            infos.reverse()
            col_defs: list[str] = []
            pk: list[tuple[int, str]] = []
            for row in infos:
                spec = f"{row[1]} {row[2]}"
                if int(row[3]):
                    spec += " NOT NULL"
                col_defs.append(spec)
                if int(row[5]):
                    pk.append((int(row[5]), str(row[1])))
            pk_sql = ", ".join(name for _ordinal, name in sorted(pk))
            connection.execute(
                f"CREATE TABLE {table} ("
                + ", ".join(col_defs)
                + f", PRIMARY KEY ({pk_sql})) WITHOUT ROWID"
            )
    finally:
        probe.close()


def test_extra_columns_and_reordered_columns_are_compact() -> None:
    def extra(connection: sqlite3.Connection) -> None:
        install_compact_schema(connection)
        connection.execute(
            f"ALTER TABLE {PERSONAL_HISTORY_COMPACT_MASTER_TABLE} ADD COLUMN extra TEXT"
        )
        connection.execute(
            f"ALTER TABLE {PERSONAL_HISTORY_COMPACT_BARS_TABLE} ADD COLUMN extra TEXT"
        )

    def reordered(connection: sqlite3.Connection) -> None:
        stamp_compact_manifest(connection)
        _create_reordered_production_tables(connection)

    assert _state(extra) == "compact"
    assert _state(reordered) == "compact"


def test_missing_table_or_column_is_invalid() -> None:
    def missing_bars(connection: sqlite3.Connection) -> None:
        stamp_compact_manifest(connection)
        create_compact_reader_tables(connection)
        connection.execute(f"DROP TABLE {PERSONAL_HISTORY_COMPACT_BARS_TABLE}")

    def missing_column(connection: sqlite3.Connection) -> None:
        stamp_compact_manifest(connection)
        create_compact_reader_tables(
            connection,
            master_columns=tuple(
                name
                for name in PERSONAL_HISTORY_COMPACT_MASTER_COLUMNS
                if name != "source_scale_category"
            ),
        )

    assert _state(missing_bars) == "invalid"
    assert _state(missing_column) == "invalid"


def test_view_under_compact_name_is_invalid() -> None:
    def build(connection: sqlite3.Connection) -> None:
        stamp_compact_manifest(connection)
        create_compact_reader_tables(connection)
        connection.execute(
            f"ALTER TABLE {PERSONAL_HISTORY_COMPACT_MASTER_TABLE} "
            "RENAME TO lookalike_master"
        )
        connection.execute(
            f"CREATE VIEW {PERSONAL_HISTORY_COMPACT_MASTER_TABLE} AS "
            "SELECT * FROM lookalike_master"
        )

    assert _state(build) == "invalid"


def test_wrong_marker_with_compact_tables_is_invalid() -> None:
    def build(connection: sqlite3.Connection) -> None:
        install_compact_schema(
            connection, format_name="personal-draft-history/v6"
        )

    assert _state(build) == "invalid"


def test_v7_marker_without_compact_objects_is_invalid() -> None:
    def build(connection: sqlite3.Connection) -> None:
        stamp_compact_manifest(connection)

    assert _state(build) == "invalid"


def test_probe_error_is_invalid() -> None:
    closed = sqlite3.connect(":memory:")
    closed.close()
    assert compact_history_state(closed) == "invalid"

    def missing_format(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE personal_history_manifest ("
            "singleton INTEGER PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO personal_history_manifest(singleton) VALUES (1)"
        )

    assert _state(missing_format) == "invalid"


def test_mixed_typed_equity_rows() -> None:
    def build(connection: sqlite3.Connection) -> None:
        install_compact_schema(connection)
        connection.execute(
            "CREATE TABLE jquants_listed_info (code TEXT, snapshot_date TEXT)"
        )
        connection.execute(
            "INSERT INTO jquants_listed_info VALUES ('1301', '2024-01-02')"
        )

    assert _state(build) == "mixed"


def test_mixed_generic_equity_rows() -> None:
    def build(connection: sqlite3.Connection) -> None:
        install_compact_schema(connection)
        connection.execute(
            "CREATE TABLE jquants_records (source TEXT, dataset TEXT)"
        )
        connection.execute(
            "INSERT INTO jquants_records VALUES ('jquants', 'equities_bars_daily')"
        )

    assert _state(build) == "mixed"


def test_building_or_validating_manifest_is_invalid() -> None:
    def building(connection: sqlite3.Connection) -> None:
        install_compact_schema(connection)
        connection.execute(
            "UPDATE personal_history_manifest SET status='BUILDING' "
            "WHERE singleton=1"
        )

    def validating(connection: sqlite3.Connection) -> None:
        install_compact_schema(connection)
        connection.execute(
            "UPDATE personal_history_manifest SET status='VALIDATING' "
            "WHERE singleton=1"
        )

    assert _state(building) == "invalid"
    assert _state(validating) == "invalid"


def test_integer_available_at_nullable_and_no_pk_lookalikes_are_invalid() -> None:
    integer_available_at = PERSONAL_HISTORY_COMPACT_MASTER_CREATE_SQL.replace(
        "available_at TEXT NOT NULL", "available_at INTEGER NOT NULL", 1
    )
    nullable_available_at = PERSONAL_HISTORY_COMPACT_BARS_CREATE_SQL.replace(
        "available_at TEXT NOT NULL", "available_at TEXT", 1
    )
    no_pk = PERSONAL_HISTORY_COMPACT_MASTER_CREATE_SQL.replace(
        ",\n    PRIMARY KEY (snapshot_date, code)\n) WITHOUT ROWID",
        "\n)",
        1,
    )
    wrong_pk = PERSONAL_HISTORY_COMPACT_MASTER_CREATE_SQL.replace(
        "PRIMARY KEY (snapshot_date, code)",
        "PRIMARY KEY (code, snapshot_date)",
        1,
    )

    def integer_master(connection: sqlite3.Connection) -> None:
        stamp_compact_manifest(connection)
        connection.execute(integer_available_at)
        connection.execute(PERSONAL_HISTORY_COMPACT_BARS_CREATE_SQL)

    def nullable_bars(connection: sqlite3.Connection) -> None:
        stamp_compact_manifest(connection)
        connection.execute(PERSONAL_HISTORY_COMPACT_MASTER_CREATE_SQL)
        connection.execute(nullable_available_at)

    def missing_pk(connection: sqlite3.Connection) -> None:
        stamp_compact_manifest(connection)
        connection.execute(no_pk)
        connection.execute(PERSONAL_HISTORY_COMPACT_BARS_CREATE_SQL)

    def swapped_pk(connection: sqlite3.Connection) -> None:
        stamp_compact_manifest(connection)
        connection.execute(wrong_pk)
        connection.execute(PERSONAL_HISTORY_COMPACT_BARS_CREATE_SQL)

    assert _state(integer_master) == "invalid"
    assert _state(nullable_bars) == "invalid"
    assert _state(missing_pk) == "invalid"
    assert _state(swapped_pk) == "invalid"


def test_v7_tables_without_manifest_status_are_invalid() -> None:
    def build(connection: sqlite3.Connection) -> None:
        create_compact_tables(connection)
        connection.execute(
            "CREATE TABLE personal_history_manifest ("
            "singleton INTEGER PRIMARY KEY, format TEXT)"
        )
        connection.execute(
            "INSERT INTO personal_history_manifest(singleton, format) VALUES (1, ?)",
            (PERSONAL_HISTORY_COMPACT_FORMAT,),
        )

    assert _state(build) == "invalid"


def test_complete_status_constant_matches_production() -> None:
    assert PERSONAL_HISTORY_COMPACT_COMPLETE_STATUS == "COMPLETE_DRAFT"


def test_generic_calendar_and_fins_are_allowed() -> None:
    def build(connection: sqlite3.Connection) -> None:
        install_compact_schema(connection)
        connection.execute(
            "CREATE TABLE jquants_records (source TEXT, dataset TEXT)"
        )
        connection.execute(
            "INSERT INTO jquants_records VALUES ('jquants', 'markets_calendar')"
        )
        connection.execute(
            "INSERT INTO jquants_records VALUES ('jquants', 'fins_summary')"
        )
        connection.execute(
            "CREATE TABLE jquants_daily_bars (source TEXT, code TEXT, date TEXT)"
        )

    assert _state(build) == "compact"


def test_compact_format_constant_is_v7() -> None:
    assert PERSONAL_HISTORY_COMPACT_FORMAT == "personal-draft-history/v7"


def test_insert_compact_bar_defaults_to_official_session_close() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        install_compact_schema(connection)
        insert_compact_bar(connection, day="2024-11-04")
        insert_compact_bar(connection, day="2024-11-05")
        rows = connection.execute(
            f"SELECT date, event_time, available_at, ingested_at"
            f" FROM {PERSONAL_HISTORY_COMPACT_BARS_TABLE} ORDER BY date"
        ).fetchall()
    finally:
        connection.close()
    pre = session_close_jst("2024-11-04")
    post = session_close_jst("2024-11-05")
    assert pre == "2024-11-04T15:00:00+09:00"
    assert post == "2024-11-05T15:30:00+09:00"
    assert rows == [
        ("2024-11-04", pre, pre, pre),
        ("2024-11-05", post, post, post),
    ]


def test_allowed_missing_observed_bars_is_shared_tiny_absolute_plus_ratio() -> None:
    assert DEFAULT_TINY_MISSING_OBSERVED_BARS == 2
    assert DEFAULT_TINY_MISSING_BAR_RATIO == 0.99
    ratio = DEFAULT_MIN_OBSERVED_BAR_RATIO
    assert allowed_missing_observed_bars(357, ratio) == 2
    assert allowed_missing_observed_bars(6, ratio) == 1
    assert allowed_missing_observed_bars(199, ratio) == 1
    assert allowed_missing_observed_bars(200, ratio) == 2
    assert allowed_missing_observed_bars(400, ratio) == 2
    assert allowed_missing_observed_bars(600, ratio) == 3
    assert allowed_missing_observed_bars(357, 1.0) == 0
