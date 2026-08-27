"""Phase 6 F0-F/I/J/P/Q history, sync, and snapshot hardening."""

from __future__ import annotations

import json
import sqlite3
from urllib.parse import parse_qs, urlparse

import pytest

from paper_runtime import (
    begin_snapshot_sync,
    data_snapshot_id,
)
from storage.sqlite_store import SqliteStore
from tests.ready_snapshot_test_support import commit_snapshot_manifest_fixture


def _record(
    value: int,
    *,
    ingested_at: str,
    available_at: str = "2025-04-01T15:30:00+09:00",
) -> dict:
    payload = {"Code": "8697", "Date": "2025-04-01", "Close": value}
    return {
        "source": "jquants",
        "dataset": "equities_bars_daily",
        "natural_key": '{"Code":"8697","Date":"2025-04-01"}',
        "event_time": "2025-04-01T15:30:00+09:00",
        "available_at": available_at,
        "ingested_at": ingested_at,
        "payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
        "raw_payload": json.dumps(payload),
    }


def test_multiple_amendments_with_same_available_at_are_all_preserved(tmp_path):
    store = SqliteStore(tmp_path / "history.sqlite")
    store.upsert(
        "jquants_records",
        [_record(100, ingested_at="2025-04-02T01:00:00+09:00")],
    )
    store.upsert(
        "jquants_records",
        [_record(101, ingested_at="2025-04-02T02:00:00+09:00")],
    )
    store.upsert(
        "jquants_records",
        [_record(102, ingested_at="2025-04-02T03:00:00+09:00")],
    )

    revisions = store.fetch_all("jquants_records_revisions")
    assert [json.loads(row["payload"])["Close"] for row in revisions] == [100, 101]
    assert [row["available_at"] for row in revisions] == [
        "2025-04-01T15:30:00+09:00",
        "2025-04-02T02:00:00+09:00",
    ]
    assert json.loads(store.fetch_all("jquants_records")[0]["payload"])["Close"] == 102
    store.close()


def test_local_schema_migrations_are_formal_and_idempotent(tmp_path):
    path = tmp_path / "migrations.sqlite"
    first = SqliteStore(path)
    rows = first._conn.execute(  # noqa: SLF001
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        (1, "phase6_sync_and_snapshot_control"),
        (2, "revision_identity_includes_ingestion_time"),
        (3, "phase6_ready_snapshot_and_coverage_ledger"),
        (4, "phase6_raw_retention_attestations"),
        (5, "phase61_collection_coverage_v2"),
        (6, "phase61_jsda_otc_bond_reference_archive"),
        (7, "phase61_jsda_correction_provenance"),
        (8, "phase62_jsda_corporate_bond_transactions"),
        (9, "phase632_raw_acquisition_status"),
        (10, "phase633_immutable_local_coverage_proofs"),
        (11, "phase631_exact_coverage_inventory_proofs"),
        (12, "phase631_coverage_complete_transition_tombstones"),
        (13, "phase631_receipt_product_materializations"),
    ]
    first.close()

    second = SqliteStore(path)
    assert second._conn.execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM schema_migrations"
    ).fetchone()[0] == 13
    second.close()


def test_raw_retention_completeness_accepts_acquired_not_as_coverage(
    tmp_path,
):
    """Raw-plane ACQUIRED is allowed; COMPLETE remains a historical label only."""
    store = SqliteStore(tmp_path / "raw-acq.sqlite")
    conn = store._conn  # noqa: SLF001
    conn.execute(
        """
        INSERT INTO raw_retention_manifests (
            dataset, run_id, manifest_key, page_count, row_count, raw_bytes,
            data_digest, completeness, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "equities_bars_daily",
            1,
            "raw/equities_bars_daily/1/manifest.json",
            1,
            0,
            0,
            "sha256:" + "a" * 64,
            "ACQUIRED",
            "2026-08-23T00:00:00+00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO raw_retention_manifests (
            dataset, run_id, manifest_key, page_count, row_count, raw_bytes,
            data_digest, completeness, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "equities_bars_daily",
            2,
            "raw/equities_bars_daily/2/manifest.json",
            1,
            0,
            0,
            "sha256:" + "b" * 64,
            "COMPLETE",
            "2026-08-21T00:00:00+00:00",
        ),
    )
    rows = conn.execute(
        "SELECT run_id, completeness FROM raw_retention_manifests ORDER BY run_id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [(1, "ACQUIRED"), (2, "COMPLETE")]
    store.close()


def test_change_feed_resumes_by_server_side_sequence(
    tmp_path, monkeypatch, sync_module
):
    store = SqliteStore(tmp_path / "feed.sqlite")
    calls: list[int] = []
    versions = [
        {"change_seq": 1, "table_name": "jquants_records", **_record(
            100, ingested_at="2025-04-02T01:00:00+09:00"
        )},
        {"change_seq": 2, "table_name": "jquants_records", **_record(
            101, ingested_at="2025-04-02T02:00:00+09:00"
        )},
    ]

    def fake_get(client, url: str, token: str) -> dict:
        query = parse_qs(urlparse(url).query)
        after = int(query["after_seq"][0])
        calls.append(after)
        page = [row for row in versions if row["change_seq"] > after][:1]
        next_seq = page[-1]["change_seq"] if page else after
        return {
            "format": "jquants-change-feed/v1",
            "after_seq": after,
            "rows": page,
            "next_seq": next_seq,
            "has_more": next_seq < 2,
            "limit": 1,
        }

    monkeypatch.setattr(sync_module, "_http_get_json", fake_get)
    result = sync_module._sync_changes(
        store, object(), "https://fixture.invalid", "token", page_limit=1
    )
    assert result == (2, 2, 2, 2)
    assert calls == [0, 1]
    assert store.count("jquants_records") == 1
    assert store.count("jquants_records_revisions") == 1

    calls.clear()
    result = sync_module._sync_changes(
        store, object(), "https://fixture.invalid", "token", page_limit=1
    )
    assert result == (1, 0, 0, 2)
    assert calls == [2]
    store.close()


def test_change_feed_rejects_non_monotonic_sequence(
    tmp_path, monkeypatch, sync_module
):
    store = SqliteStore(tmp_path / "bad-feed.sqlite")
    monkeypatch.setattr(
        sync_module,
        "_http_get_json",
        lambda *_: {
            "format": "jquants-change-feed/v1",
            "rows": [
                {"change_seq": 1, "table_name": "jquants_records", **_record(
                    100, ingested_at="2025-04-02T01:00:00+09:00"
                )},
                {"change_seq": 1, "table_name": "jquants_records", **_record(
                    101, ingested_at="2025-04-02T02:00:00+09:00"
                )},
            ],
            "next_seq": 1,
            "has_more": False,
        },
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        sync_module._sync_changes(
            store, object(), "https://fixture.invalid", "token", page_limit=10
        )
    assert sync_module._last_change_seq(store) == 0
    store.close()


def test_export_max_pages_guard(tmp_path, monkeypatch, sync_module):
    store = SqliteStore(tmp_path / "pages.sqlite")

    def endless(client, url: str, token: str) -> dict:
        query = parse_qs(urlparse(url).query)
        cursor = int(query.get("cursor", ["0"])[0])
        return {
            "table": "jquants_records",
            "rows": [],
            "has_more": True,
            "next_cursor": cursor + 1,
        }

    monkeypatch.setattr(sync_module, "_http_get_json", endless)
    with pytest.raises(ValueError, match="max_pages=2"):
        sync_module._sync_table(
            store, object(), "https://fixture.invalid", "token",
            "jquants_records", page_limit=10, since=None, max_pages=2,
        )
    store.close()


def _seed_snapshot_control(store: SqliteStore, datasets: tuple[str, ...]) -> None:
    conn = store._conn  # noqa: SLF001
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ingestion_validation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            dataset TEXT,
            started_at TEXT,
            finished_at TEXT,
            status TEXT,
            rows_seen INTEGER,
            rows_inserted INTEGER,
            rows_revisions INTEGER,
            available_at_min TEXT,
            available_at_max TEXT,
            detail TEXT
        );
        CREATE TABLE IF NOT EXISTS ingestion_watermarks (
            dataset TEXT PRIMARY KEY,
            last_event_date TEXT,
            last_ingested_at TEXT NOT NULL,
            last_export_cursor INTEGER
        );
        """
    )
    detail = json.dumps({
        "datasetCount": len(datasets), "passed": len(datasets), "failed": 0,
        "startedAt": "2025-04-02T00:00:00Z",
        "finishedAt": "2025-04-02T01:00:00Z",
    })
    cursor = conn.execute(
        "INSERT INTO ingestion_run_log "
        "(ran_at, source, runtime, status, detail) VALUES (?, ?, ?, ?, ?)",
        ("2025-04-02T00:00:00Z", "jquants", "cloudflare", "pass", detail),
    )
    run_id = cursor.lastrowid
    for dataset in datasets:
        conn.execute(
            "INSERT INTO ingestion_validation "
            "(run_id, dataset, started_at, finished_at, status, rows_seen, "
            "rows_inserted, rows_revisions) VALUES (?, ?, ?, ?, 'pass', 1, 1, 0)",
            (run_id, dataset, "2025-04-02T00:00:00Z", "2025-04-02T01:00:00Z"),
        )
        conn.execute(
            "INSERT INTO ingestion_watermarks "
            "(dataset, last_event_date, last_ingested_at) VALUES (?, ?, ?)",
            (dataset, "2025-04-01", "2025-04-02T01:00:00Z"),
        )
    conn.execute(
        "INSERT INTO sync_change_state "
        "(feed, last_applied_change_seq, updated_at) VALUES (?, ?, ?)",
        ("jquants_records", 42, "2025-04-02T01:00:00Z"),
    )
    conn.commit()


def test_manifest_commit_gates_and_identifies_research_snapshot(tmp_path):
    path = tmp_path / "snapshot.sqlite"
    store = SqliteStore(path)
    datasets = ("dataset_a", "dataset_b")
    _seed_snapshot_control(store, datasets)
    begin_snapshot_sync(store._conn, started_at="2025-04-02T02:00:00Z")  # noqa: SLF001

    with pytest.raises(RuntimeError, match="not committed"):
        data_snapshot_id(path)

    manifest_id = commit_snapshot_manifest_fixture(
        store._conn, required_datasets=datasets  # noqa: SLF001
    )
    assert manifest_id.startswith("sha256:")
    first = data_snapshot_id(path)
    assert first.startswith("sha256:")
    assert data_snapshot_id(path) == first

    store._conn.execute(  # noqa: SLF001
        "UPDATE ingestion_watermarks SET last_event_date = '2025-04-02' "
        "WHERE dataset = 'dataset_a'"
    )
    store._conn.commit()  # noqa: SLF001
    with pytest.raises(RuntimeError, match="no longer match"):
        data_snapshot_id(path)
    store.close()


def test_manifest_rejects_partial_latest_run(tmp_path):
    store = SqliteStore(tmp_path / "partial.sqlite")
    _seed_snapshot_control(store, ("dataset_a",))
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_run_log "
        "(ran_at, source, runtime, status, detail) VALUES (?, ?, ?, ?, ?)",
        ("2025-04-03", "jquants", "cloudflare", "partial", "{}"),
    )
    store._conn.commit()  # noqa: SLF001
    begin_snapshot_sync(store._conn, started_at="2025-04-03T01:00:00Z")  # noqa: SLF001
    with pytest.raises(RuntimeError, match="not a complete pass"):
        commit_snapshot_manifest_fixture(
            store._conn, required_datasets=("dataset_a",)  # noqa: SLF001
        )
    store.close()


def test_d1_migrations_keep_same_publication_time_revisions_distinct():
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    migrations = repo / "platform/workers/ingestion-premium/migrations"
    conn = sqlite3.connect(":memory:")
    for name in (
        "0001_init.sql", "0002_watermarks.sql", "0003_change_feed.sql",
        "0004_revision_identity_v2.sql",
    ):
        conn.executescript((migrations / name).read_text(encoding="utf-8"))
    row = _record(100, ingested_at="2025-04-02T01:00:00+09:00")
    columns = tuple(row)
    sql = (
        "INSERT INTO jquants_records_revisions ("
        + ",".join(columns)
        + ") VALUES ("
        + ",".join("?" for _ in columns)
        + ")"
    )
    conn.execute(sql, tuple(row[column] for column in columns))
    second = _record(101, ingested_at="2025-04-02T02:00:00+09:00")
    conn.execute(sql, tuple(second[column] for column in columns))
    assert conn.execute(
        "SELECT COUNT(*) FROM jquants_records_revisions"
    ).fetchone()[0] == 2
