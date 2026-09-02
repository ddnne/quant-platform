"""Behavioral contracts for bounded personal-DRAFT PIT reads."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pit.api as api_module
import pit.query as query_module
import pytest
from core.universe import load_master
from ingestion.jquants.normalize import (
    normalize_daily_bars,
    normalize_generic,
    normalize_listed_info,
)
from pit import (
    PitError,
    first_invalid_adjusted_close,
    get_equity_bars_daily,
    get_equity_master,
    get_jquants_records,
    get_market_calendar,
)
from personal_history_compact_support import (
    insert_compact_bar,
    insert_compact_master,
    install_compact_schema,
    stamp_compact_manifest,
)
from storage.schema import CATALOG_CODE_SQL
from storage.sqlite_store import SqliteStore
from contextlib import contextmanager

AS_OF = "2025-04-10T15:30:00+09:00"
CODE = "8697"


def _observe(path: Path) -> None:
    connection = sqlite3.connect(path)
    stamp_compact_manifest(connection, format_name="unmanaged-catalog")
    connection.commit()
    connection.close()


@contextmanager
def _observed_store(path: Path):
    with SqliteStore(path) as store:
        yield store
    _observe(path)


def _bar(day: str, close: float | None) -> dict:
    return {
        "Code": CODE,
        "Date": day,
        "Open": close,
        "High": close,
        "Low": close,
        "Close": close,
        "Volume": 1_000,
    }


def _typed_bar(day: str, close: float, *, available_at: str | None = None) -> dict:
    published = available_at or f"{day}T15:30:00+09:00"
    return normalize_daily_bars(
        [_bar(day, close)],
        ingested_at=published,
        available_at=published,
    )[0]


def _generic_bar(day: str, close: float, *, available_at: str) -> dict:
    return normalize_generic(
        [_bar(day, close)],
        dataset="equities_bars_daily",
        ingested_at=available_at,
        available_at=available_at,
    )[0]


def test_empty_revision_table_uses_direct_path_without_window_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "direct.sqlite"
    with _observed_store(path) as store:
        store.upsert("jquants_daily_bars", [_typed_bar("2025-04-01", 100.0)])
        assert store.count("jquants_daily_bars_revisions") == 0

    real_connect = query_module.connect_readonly

    def connect_without_windows(db_path):
        connection = real_connect(db_path)

        def authorize(action, _arg1, arg2, _database, _trigger):
            if (
                action == sqlite3.SQLITE_FUNCTION
                and str(arg2).lower() == "row_number"
            ):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        return connection

    monkeypatch.setattr(query_module, "connect_readonly", connect_without_windows)
    rows = query_module.run_query(
        path,
        as_of=AS_OF,
        table="jquants_daily_bars",
        extra_where="code = ?",
        params=[CODE],
        order_by="date",
    )
    assert [(row["date"], row["close"]) for row in rows] == [
        ("2025-04-01", 100.0)
    ]


def test_revision_check_and_fact_read_share_one_sqlite_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "snapshot-race.sqlite"
    with _observed_store(path) as store:
        store.upsert("jquants_daily_bars", [_typed_bar("2025-04-01", 100.0)])

    writer_fired = False

    def publish_amendment() -> None:
        nonlocal writer_fired
        writer_fired = True
        with sqlite3.connect(path) as writer:
            writer.execute(
                "INSERT INTO jquants_daily_bars_revisions "
                "SELECT * FROM jquants_daily_bars"
            )
            writer.execute(
                "UPDATE jquants_daily_bars SET close = ?, available_at = ?, "
                "ingested_at = ? WHERE source = ? AND code = ? AND date = ?",
                (
                    999.0,
                    "2025-05-01T09:00:00+09:00",
                    "2025-05-01T09:00:00+09:00",
                    "jquants",
                    CODE,
                    "2025-04-01",
                ),
            )

    real_connect = query_module.connect_readonly

    class HookCursor:
        def __init__(self, inner) -> None:
            self.inner = inner

        def fetchone(self):
            row = self.inner.fetchone()
            # The first empty scalar read is the empty revision marker. Commit
            # an amendment immediately after that observation, before the fact
            # SELECT is prepared.
            if row is None and not writer_fired:
                publish_amendment()
            return row

        def fetchall(self):
            return self.inner.fetchall()

        def __iter__(self):
            return iter(self.inner)

    class HookConnection:
        def __init__(self, inner) -> None:
            self.inner = inner

        def execute(self, sql, params=()):
            return HookCursor(self.inner.execute(sql, params))

        def rollback(self) -> None:
            self.inner.rollback()

        def close(self) -> None:
            self.inner.close()

    monkeypatch.setattr(
        query_module,
        "connect_readonly",
        lambda db_path: HookConnection(real_connect(db_path)),
    )

    rows = query_module.run_query(
        path,
        as_of=AS_OF,
        table="jquants_daily_bars",
        extra_where="code = ?",
        params=[CODE],
        order_by="date",
    )

    assert writer_fired is True
    assert [(row["date"], row["close"]) for row in rows] == [
        ("2025-04-01", 100.0)
    ]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT close FROM jquants_daily_bars"
        ).fetchone()[0] == 999.0
        assert connection.execute(
            "SELECT COUNT(*) FROM jquants_daily_bars_revisions"
        ).fetchone()[0] == 1


def test_latest_n_ranks_visible_revision_before_sql_limit(tmp_path: Path) -> None:
    path = tmp_path / "revisions.sqlite"
    with _observed_store(path) as store:
        store.upsert(
            "jquants_daily_bars",
            [
                _typed_bar("2025-04-01", 101.0),
                _typed_bar("2025-04-02", 102.0),
                _typed_bar("2025-04-03", 103.0),
            ],
        )
        store.upsert(
            "jquants_daily_bars",
            [
                _typed_bar(
                    "2025-04-03",
                    999.0,
                    available_at="2025-05-01T09:00:00+09:00",
                )
            ],
        )
        store.upsert(
            "jquants_records",
            [
                _generic_bar(
                    "2025-04-04",
                    104.0,
                    available_at="2025-04-04T15:30:00+09:00",
                ),
                _generic_bar(
                    "2025-04-05",
                    105.0,
                    available_at="2025-05-01T09:00:00+09:00",
                ),
            ],
        )
        assert store.count("jquants_daily_bars_revisions") == 1

    result = get_equity_bars_daily(
        as_of=AS_OF,
        code=CODE,
        latest_n=2,
        db_path=path,
    )
    assert [(row["date"], row["close"]) for row in result.rows] == [
        ("2025-04-03", 103.0),
        ("2025-04-04", 104.0),
    ]
    assert result.metadata["latest_n"] == 2


def test_latest_n_is_exact_for_generic_only_compatibility_db(tmp_path: Path) -> None:
    path = tmp_path / "generic.sqlite"
    with _observed_store(path) as store:
        store.upsert(
            "jquants_records",
            [
                _generic_bar(
                    day,
                    float(100 + offset),
                    available_at=f"{day}T15:30:00+09:00",
                )
                for offset, day in enumerate(
                    ("2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04")
                )
            ],
        )

    result = get_equity_bars_daily(
        as_of=AS_OF,
        code=CODE,
        latest_n=2,
        db_path=path,
    )
    assert [(row["date"], row["close"]) for row in result.rows] == [
        ("2025-04-03", 102.0),
        ("2025-04-04", 103.0),
    ]


def test_latest_n_is_applied_as_sql_limit_on_catalog_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "catalog-limit.sqlite"
    days = [f"2025-03-{day:02d}" for day in range(1, 21)]
    with _observed_store(path) as store:
        store.upsert(
            "jquants_records",
            [
                _generic_bar(
                    day,
                    float(100 + offset),
                    available_at=f"{day}T15:30:00+09:00",
                )
                for offset, day in enumerate(days)
            ],
        )

    catalog_calls: list[dict] = []
    decoded_lengths: list[int] = []
    real_catalog = api_module._catalog_partition_rows
    real_decode = api_module._catalog_daily_bars

    def spy_catalog(*args, **kwargs):
        catalog_calls.append(dict(kwargs))
        return real_catalog(*args, **kwargs)

    def spy_decode(rows):
        decoded_lengths.append(len(rows))
        return real_decode(rows)

    monkeypatch.setattr(api_module, "_catalog_partition_rows", spy_catalog)
    monkeypatch.setattr(api_module, "_catalog_daily_bars", spy_decode)

    unbounded = get_equity_bars_daily(as_of=AS_OF, code=CODE, db_path=path)
    bounded = get_equity_bars_daily(
        as_of=AS_OF, code=CODE, latest_n=2, db_path=path
    )

    limited_calls = [
        call for call in catalog_calls if call.get("limit") is not None
    ]
    assert limited_calls
    assert all(call["limit"] == 2 for call in limited_calls)
    assert all(length <= 2 for length in decoded_lengths[-1:])
    assert [(row["date"], row["close"]) for row in bounded.rows] == [
        (row["date"], row["close"]) for row in unbounded.rows[-2:]
    ]
    assert [(row["date"], row["close"]) for row in bounded.rows] == [
        ("2025-03-19", 118.0),
        ("2025-03-20", 119.0),
    ]


@pytest.mark.parametrize("latest_n", [0, -1, True, 1.5, "2"])
def test_latest_n_rejects_non_positive_or_non_integer_values(
    tmp_path: Path,
    latest_n: object,
) -> None:
    path = tmp_path / "validation.sqlite"
    SqliteStore(path).close(); _observe(path)
    with pytest.raises(ValueError, match="positive integer"):
        get_equity_bars_daily(
            as_of=AS_OF,
            code=CODE,
            latest_n=latest_n,  # type: ignore[arg-type]
            db_path=path,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"codes": (CODE,)},
        {"code": ""},
    ],
)
def test_latest_n_requires_exactly_one_non_empty_code(
    tmp_path: Path,
    kwargs: dict,
) -> None:
    path = tmp_path / "single-code.sqlite"
    SqliteStore(path).close(); _observe(path)
    with pytest.raises(ValueError):
        get_equity_bars_daily(
            as_of=AS_OF,
            latest_n=1,
            db_path=path,
            **kwargs,
        )


def test_latest_master_snapshot_is_global_before_code_filter(tmp_path: Path) -> None:
    path = tmp_path / "master.sqlite"
    first = "2025-04-01"
    second = "2025-04-02"
    with _observed_store(path) as store:
        store.upsert(
            "jquants_listed_info",
            normalize_listed_info(
                [
                    {"Code": "1301", "CompanyName": "kept"},
                    {"Code": "1302", "CompanyName": "delisted"},
                ],
                snapshot_date=first,
                ingested_at=f"{first}T08:00:00+09:00",
                available_at=f"{first}T08:00:00+09:00",
            ),
        )
        store.upsert(
            "jquants_records",
            normalize_generic(
                [{"Code": "1301", "Date": second, "CompanyName": "kept"}],
                dataset="equities_master",
                ingested_at=f"{second}T08:00:00+09:00",
                available_at=f"{second}T08:00:00+09:00",
            ),
        )
        store.upsert(
            "jquants_records",
            normalize_generic(
                [{"Code": "1303", "Date": "2025-04-03"}],
                dataset="equities_master",
                ingested_at="2025-05-01T08:00:00+09:00",
                available_at="2025-05-01T08:00:00+09:00",
            ),
        )

    latest = get_equity_master(
        as_of=AS_OF,
        latest_snapshot=True,
        db_path=path,
    )
    delisted = get_equity_master(
        as_of=AS_OF,
        code="1302",
        latest_snapshot=True,
        db_path=path,
    )
    historical = get_equity_master(
        as_of=AS_OF,
        code="1302",
        db_path=path,
    )
    universe = load_master(AS_OF, db_path=path)

    assert [(row["snapshot_date"], row["code"]) for row in latest.rows] == [
        (second, "1301")
    ]
    assert latest.metadata["snapshot_date"] == second
    assert delisted.rows == []
    assert [row["snapshot_date"] for row in historical.rows] == [first]
    assert set(universe) == {"1301"}


def test_schema_indexes_match_bounded_pit_query_shapes(tmp_path: Path) -> None:
    path = tmp_path / "indexes.sqlite"
    with _observed_store(path) as store:
        store.upsert("jquants_daily_bars", [_typed_bar("2025-04-01", 100.0)])
        store.upsert(
            "jquants_records",
            [
                _generic_bar(
                    "2025-04-01",
                    100.0,
                    available_at="2025-04-01T15:30:00+09:00",
                )
            ],
        )

    with sqlite3.connect(path) as connection:
        connection.execute("ANALYZE")
        names = {
            row[1]
            for row in connection.execute("PRAGMA index_list(jquants_records)")
        }
        assert {
            "ix_records_dataset_event_pit",
            "ix_records_dataset_code_event_pit",
        } <= names

        bars_plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM jquants_daily_bars "
            "WHERE available_at <= ? AND code = ? "
            "ORDER BY date DESC, code DESC, source DESC LIMIT ?",
            (AS_OF, CODE, 2),
        ).fetchall()
        catalog_plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM jquants_records "
            f"WHERE available_at <= ? AND dataset = ? AND {CATALOG_CODE_SQL} = ? "
            "ORDER BY event_time DESC, natural_key DESC, source DESC",
            (AS_OF, "equities_bars_daily", CODE),
        ).fetchall()

    assert any("ix_bars_code_date_pit" in row[3] for row in bars_plan)
    assert any(
        "ix_records_dataset_code_event_pit" in row[3] for row in catalog_plan
    )


def _open_compact(path: Path) -> sqlite3.Connection:
    SqliteStore(path).close(); _observe(path)
    conn = sqlite3.connect(path)
    install_compact_schema(conn)
    return conn


def _seed_typed_equity(path: Path) -> None:
    with _observed_store(path) as store:
        store.upsert(
            "jquants_listed_info",
            normalize_listed_info(
                [{"Code": "1301", "CompanyName": "typed-fallback"}],
                snapshot_date="2025-04-02",
                ingested_at="2025-04-02T08:00:00+09:00",
                available_at="2025-04-02T08:00:00+09:00",
            ),
        )
        store.upsert("jquants_daily_bars", [_typed_bar("2025-04-02", 101.0)])


def _assert_equity_reads_fail_closed(path: Path, *, match: str) -> None:
    with pytest.raises(PitError, match=match):
        get_equity_master(as_of=AS_OF, db_path=path)
    with pytest.raises(PitError, match=match):
        get_equity_bars_daily(as_of=AS_OF, code=CODE, db_path=path)
    with pytest.raises(PitError, match=match):
        first_invalid_adjusted_close(as_of=AS_OF, codes=(CODE,), db_path=path)


def test_genuine_v6_legacy_keeps_typed_catalog_reads(tmp_path: Path) -> None:
    path = tmp_path / "genuine-v6.sqlite"
    _seed_typed_equity(path)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE IF EXISTS personal_history_manifest")
        conn.execute(
            "CREATE TABLE personal_history_manifest ("
            "singleton INTEGER PRIMARY KEY, format TEXT, observed_through TEXT)"
        )
        conn.execute(
            "INSERT INTO personal_history_manifest("
            "singleton, format, observed_through) "
            "VALUES (1, 'personal-draft-history/v6', '2099-01-01T00:00:00+09:00')"
        )
        conn.commit()

    master = get_equity_master(as_of=AS_OF, db_path=path)
    bars = get_equity_bars_daily(as_of=AS_OF, code=CODE, db_path=path)
    assert [(row["snapshot_date"], row["code"]) for row in master.rows] == [
        ("2025-04-02", "1301")
    ]
    assert [(row["date"], row["close"]) for row in bars.rows] == [
        ("2025-04-02", 101.0)
    ]
    assert "personal_history_format" not in master.metadata
    assert "personal_history_format" not in bars.metadata


def test_malformed_or_mixed_compact_v7_fail_closed(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed-typed-fallback.sqlite"
    _seed_typed_equity(malformed)
    with sqlite3.connect(malformed) as conn:
        stamp_compact_manifest(conn)
        conn.commit()
    _assert_equity_reads_fail_closed(malformed, match="rebuild as personal-draft-history/v8")

    mixed = tmp_path / "mixed-typed.sqlite"
    _seed_typed_equity(mixed)
    with sqlite3.connect(mixed) as conn:
        install_compact_schema(conn)
        conn.commit()
    _assert_equity_reads_fail_closed(mixed, match="cannot mix compact")


def test_compact_v7_latest_master_snapshot_does_not_resurrect_delisted(
    tmp_path: Path,
) -> None:
    path = tmp_path / "compact-master.sqlite"
    first = "2025-04-01"
    second = "2025-04-02"
    with _open_compact(path) as conn:
        for code in ("1301", "1302"):
            insert_compact_master(
                conn,
                snapshot_date=first,
                code=code,
                available_at=f"{first}T08:00:00+09:00",
            )
        insert_compact_master(
            conn,
            snapshot_date=second,
            code="1301",
            available_at=f"{second}T08:00:00+09:00",
        )
        insert_compact_master(
            conn,
            snapshot_date="2025-04-03",
            code="1303",
            available_at="2025-05-01T08:00:00+09:00",
        )
        conn.commit()

    latest = get_equity_master(
        as_of=AS_OF,
        latest_snapshot=True,
        db_path=path,
    )
    delisted = get_equity_master(
        as_of=AS_OF,
        code="1302",
        latest_snapshot=True,
        db_path=path,
    )
    historical = get_equity_master(
        as_of=AS_OF,
        code="1302",
        db_path=path,
    )
    universe = load_master(AS_OF, db_path=path)

    assert [(row["snapshot_date"], row["code"]) for row in latest.rows] == [
        (second, "1301")
    ]
    assert latest.metadata["table"] == "jquants_listed_info"
    assert latest.metadata["snapshot_date"] == second
    assert latest.metadata["personal_history_format"] == "personal-draft-history/v8"
    assert latest.rows[0]["source"] == "jquants"
    assert latest.rows[0]["raw_payload"] is None
    assert latest.rows[0]["company_name"] is None
    assert latest.rows[0]["sector_17_name"] is None
    assert "source_scale_category" not in latest.rows[0]
    assert delisted.rows == []
    assert [row["snapshot_date"] for row in historical.rows] == [first]
    assert set(universe) == {"1301"}


def test_compact_v7_bars_honor_codes_date_bounds_and_latest_n(
    tmp_path: Path,
) -> None:
    path = tmp_path / "compact-bars.sqlite"
    with _open_compact(path) as conn:
        for code, day, close in (
            ("1332", "2025-04-01", 10.0),
            ("1332", "2025-04-02", 11.0),
            ("1332", "2025-04-03", 12.0),
            ("7203", "2025-04-02", 20.0),
            ("8697", "2025-04-01", 30.0),
            ("8697", "2025-04-02", 31.0),
            ("8697", "2025-04-03", 32.0),
            ("8697", "2025-04-04", 33.0),
        ):
            insert_compact_bar(
                conn,
                code=code,
                day=day,
                available_at=f"{day}T15:30:00+09:00",
                close=close,
            )
        conn.commit()

    multi = get_equity_bars_daily(
        as_of=AS_OF,
        codes=("8697", "1332"),
        from_event="2025-04-02",
        to_event="2025-04-03",
        db_path=path,
    )
    bounded = get_equity_bars_daily(
        as_of=AS_OF,
        code=CODE,
        latest_n=2,
        db_path=path,
    )
    unbounded = get_equity_bars_daily(as_of=AS_OF, code=CODE, db_path=path)

    assert [(row["code"], row["date"], row["close"]) for row in multi.rows] == [
        ("1332", "2025-04-02", 11.0),
        ("1332", "2025-04-03", 12.0),
        ("8697", "2025-04-02", 31.0),
        ("8697", "2025-04-03", 32.0),
    ]
    assert [(row["date"], row["close"]) for row in bounded.rows] == [
        ("2025-04-03", 32.0),
        ("2025-04-04", 33.0),
    ]
    assert bounded.rows == unbounded.rows[-2:]
    assert bounded.metadata["table"] == "jquants_daily_bars"
    assert bounded.metadata["latest_n"] == 2
    assert bounded.metadata["personal_history_format"] == "personal-draft-history/v8"
    sample = multi.rows[0]
    assert sample["source"] == "jquants"
    assert sample["raw_payload"] is None
    assert sample["open"] is None
    assert sample["adjustment_open"] is None
    assert first_invalid_adjusted_close(
        as_of=AS_OF, codes=(CODE,), db_path=path
    ) is None
