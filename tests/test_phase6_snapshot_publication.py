"""Strong invariants for coverage and immutable READY publication."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3

import pytest
import pit

from data_contracts import all_contracts, all_coverage_contracts
from paper_runtime import (
    SnapshotRejected,
    data_snapshot_id,
    latest_ready_snapshot,
    list_ready_snapshots,
    open_ready_snapshot,
    publish_ready_snapshot,
)
from storage.coverage_ledger import refresh_coverage_ledger
from storage.sqlite_store import SqliteStore


def _generic_row(dataset: str, key: str, date: str, **payload):
    body = {"Date": date, **payload}
    raw = json.dumps(body, sort_keys=True)
    instant = date + "T15:30:00+09:00"
    return (
        "jquants", dataset, key, instant, instant,
        date + "T16:00:00+09:00", raw, raw,
    )


def _seed_control(conn, datasets: tuple[str, ...], today: str) -> int:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ingestion_validation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER, dataset TEXT, started_at TEXT, finished_at TEXT,
            status TEXT, rows_seen INTEGER, rows_inserted INTEGER,
            rows_revisions INTEGER, available_at_min TEXT,
            available_at_max TEXT, detail TEXT
        );
        CREATE TABLE IF NOT EXISTS ingestion_watermarks (
            dataset TEXT PRIMARY KEY, last_event_date TEXT,
            last_ingested_at TEXT NOT NULL, last_export_cursor INTEGER
        );
        """
    )
    detail = json.dumps({
        "datasetCount": len(datasets), "passed": len(datasets), "failed": 0,
        "startedAt": today + "T00:00:00Z",
        "finishedAt": today + "T01:00:00Z",
    })
    run_id = conn.execute(
        "INSERT INTO ingestion_run_log "
        "(ran_at, source, runtime, status, detail) VALUES (?, ?, ?, ?, ?)",
        (today, "jquants", "test", "pass", detail),
    ).lastrowid
    for dataset in datasets:
        count = conn.execute(
            "SELECT COUNT(*) FROM jquants_records WHERE dataset=?", (dataset,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO ingestion_validation "
            "(run_id,dataset,started_at,finished_at,status,rows_seen,"
            " rows_inserted,rows_revisions,available_at_min,available_at_max) "
            "VALUES (?, ?, ?, ?, 'pass', ?, ?, 0, ?, ?)",
            (run_id, dataset, today, today, count, count, today, today),
        )
        conn.execute(
            "INSERT INTO ingestion_watermarks "
            "(dataset,last_event_date,last_ingested_at) VALUES (?, ?, ?)",
            (dataset, today, today + "T16:00:00Z"),
        )
    conn.commit()
    return int(run_id)


def _seed_publishable_db(path) -> tuple[str, ...]:
    store = SqliteStore(path)
    conn = store._conn  # noqa: SLF001
    today = datetime.now(timezone.utc).date().isoformat()
    policies = all_coverage_contracts()
    required = tuple(policy.dataset_id for policy in policies)
    rows = []
    for policy in policies:
        extra = {"HolidayDivision": "1"} if policy.dataset_id == "markets_calendar" else {}
        rows.append(_generic_row(
            policy.dataset_id, "history-start", policy.history_target_start,
            **extra,
        ))
        rows.append(_generic_row(policy.dataset_id, "latest", today, **extra))
    # The bar and calendar checks share exactly the same observed trading days.
    rows.append(_generic_row(
        "equities_bars_daily", "calendar-policy-start", "2008-01-01"
    ))
    rows.append(_generic_row(
        "markets_calendar", "bars-policy-start", "2004-01-05",
        HolidayDivision="1",
    ))
    for dataset in ("equities_master", "equities_bars_daily"):
        rows.extend(
            _generic_row(dataset, f"{dataset}-{index}", today, Code=f"{index:04d}")
            for index in range(3000)
        )
    conn.executemany(
        "INSERT INTO jquants_records "
        "(source,dataset,natural_key,event_time,available_at,ingested_at,"
        " payload,raw_payload) VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    run_id = _seed_control(conn, required, today)
    conn.executemany(
        "INSERT INTO raw_retention_manifests "
        "(dataset,run_id,manifest_key,page_count,row_count,raw_bytes,"
        "data_digest,completeness,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (
                dataset, run_id, f"raw/{dataset}/{run_id}/manifest.json",
                1, 1, 100, "sha256:" + "0" * 64, "COMPLETE",
                today + "T16:00:00Z",
            )
            for dataset in required
        ],
    )
    conn.commit()
    store.close()
    return required


def test_collection_contract_covers_canonical_set_without_event_row_guesses():
    policies = {row.dataset_id: row for row in all_coverage_contracts()}
    assert set(policies) == {row.dataset_id for row in all_contracts()}
    assert all(row.governance_tier in {"governed", "experimental"} for row in policies.values())
    assert policies["fins_summary"].coverage_mode == "event_reconciled"
    assert policies["fins_summary"].expected_frequency == "event_driven"


def test_irregular_empty_pass_is_partial_not_fake_complete_or_failed(tmp_path):
    path = tmp_path / "coverage.sqlite"
    store = SqliteStore(path)
    today = datetime.now(timezone.utc).date().isoformat()
    _seed_control(store._conn, ("fins_summary",), today)  # noqa: SLF001

    rows = refresh_coverage_ledger(
        store._conn, path, datasets=("fins_summary",), today=today  # noqa: SLF001
    )
    assert rows[0]["status"] == "PARTIAL"
    assert rows[0]["row_count"] == 0
    store.close()


def test_fact_mutation_invalidates_an_in_place_generation(tmp_path):
    path = tmp_path / "invalidate.sqlite"
    store = SqliteStore(path)
    conn = store._conn  # noqa: SLF001
    conn.execute(
        "INSERT INTO local_snapshot_policy "
        "(singleton,require_manifest,snapshot_ready,publication_state) "
        "VALUES (1,1,1,'READY')"
    )
    conn.execute(
        "INSERT INTO jquants_daily_bars "
        "(source,code,date,event_time,available_at,ingested_at) "
        "VALUES ('jquants','8697','2026-08-11','2026-08-11T15:30:00+09:00',"
        "'2026-08-11T15:30:00+09:00','2026-08-11T16:00:00+09:00')"
    )
    conn.commit()
    policy = conn.execute(
        "SELECT snapshot_ready,last_error FROM local_snapshot_policy WHERE singleton=1"
    ).fetchone()
    assert policy[0] == 0
    assert "fact mutation invalidated" in policy[1]
    store.close()


def test_publish_gate_rejects_partial_coverage_and_exposes_no_ready(tmp_path):
    path = tmp_path / "partial.sqlite"
    store = SqliteStore(path)
    today = datetime.now(timezone.utc).date().isoformat()
    dataset = "fins_summary"
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO jquants_records "
        "(source,dataset,natural_key,event_time,available_at,ingested_at) "
        "VALUES ('jquants',?,?,?, ?, ?)",
        (
            dataset, "recent-only", today + "T00:00:00+09:00",
            today + "T00:00:00+09:00", today + "T01:00:00+09:00",
        ),
    )
    _seed_control(store._conn, (dataset,), today)  # noqa: SLF001
    store.close()

    snapshots = tmp_path / "snapshots"
    with pytest.raises(SnapshotRejected):
        publish_ready_snapshot(path, snapshots, required_datasets=(dataset,))
    with pytest.raises(FileNotFoundError, match="no READY"):
        latest_ready_snapshot(snapshots)


def test_ready_publication_is_atomic_content_addressed_and_read_only(tmp_path):
    path = tmp_path / "staging.sqlite"
    required = _seed_publishable_db(path)
    snapshot_dir = tmp_path / "snapshots"

    ready = publish_ready_snapshot(
        path, snapshot_dir, required_datasets=required
    )
    assert ready.snapshot_id == ready.manifest["snapshot_id"]
    assert ready.manifest["state"] == "READY"
    assert ready.manifest["quality"]["status"] == "PASS"
    assert {row["status"] for row in ready.manifest["coverage"]} == {"COMPLETE"}
    assert set(ready.manifest["raw_manifests"]) == set(required)
    assert latest_ready_snapshot(snapshot_dir).snapshot_id == ready.snapshot_id
    assert data_snapshot_id(ready.db_path) == ready.snapshot_id
    with pytest.raises(RuntimeError, match="not committed"):
        data_snapshot_id(path)
    as_of = datetime.now(timezone.utc).date().isoformat() + "T23:59:59+09:00"
    with pytest.raises(pit.SnapshotNotReady):
        pit.get_jquants_records(
            as_of=as_of,
            dataset="equities_bars_daily",
            db_path=path,
        )

    assert pit.get_jquants_records(
        as_of=as_of,
        dataset="equities_bars_daily",
        db_path=ready.db_path,
    ).rows

    with open_ready_snapshot(snapshot_dir) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM dataset_coverage WHERE status='COMPLETE'"
        ).fetchone()[0] == len(required)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM jquants_records")

    repeated = publish_ready_snapshot(
        path, snapshot_dir, required_datasets=required
    )
    assert repeated.snapshot_id == ready.snapshot_id
    assert len(list_ready_snapshots(snapshot_dir)) == 1
