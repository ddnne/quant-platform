"""Strong invariants for coverage and immutable READY publication."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import sqlite3

import pytest
import pit
import paper_runtime.snapshot as snapshot_module

from data_contracts import all_contracts, all_coverage_contracts
from data_contracts.coverage import SNAPSHOT_SEGMENT_GRANULARITIES
from paper_runtime import (
    SnapshotRejected,
    data_snapshot_id,
    latest_ready_snapshot,
    list_ready_snapshots,
    open_ready_snapshot,
    publish_ready_snapshot,
)
from storage.coverage_ledger import (
    CollectionReceipt,
    plan_required_segments,
    record_collection_receipt,
    record_required_segments,
    refresh_coverage_ledger,
)
from storage.sqlite_store import SqliteStore
from tests.test_phase61_coverage_v2 import _signed_digests


def _jquants_coverage_contracts():
    """JQ Premium-core only. index_text omitted; OTC would be empty, not weekend COMPLETE."""
    canonical = {contract.dataset_id for contract in all_contracts()}
    policies = tuple(
        policy for policy in all_coverage_contracts()
        if policy.dataset_id in canonical
    )
    assert all(
        policy.segment_granularity != "official_archive_index_day"
        and "official_archive_index" not in (policy.coverage_mode or "")
        and policy.history_mode != "official_archive_index"
        for policy in policies
    ), "JQ READY fixture must not plan OTC; missing index_text is empty, not weekend COMPLETE"
    return policies


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
    policies = _jquants_coverage_contracts()
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
    # Bars floor is 2008-05-01 (w0815ae); calendar remains 2008-01-01.
    rows.append(_generic_row(
        "equities_bars_daily", "calendar-policy-start", "2008-05-01"
    ))
    rows.append(_generic_row(
        "markets_calendar", "bars-policy-start", "2008-05-01",
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
    for policy in policies:
        # Tip snapshots stay PARTIAL on empty receipts; event-zero COMPLETE
        # is only for genuine event_driven historical windows.
        tip_snapshot = (
            policy.segment_granularity in SNAPSHOT_SEGMENT_GRANULARITIES
            or "snapshot" in (policy.coverage_mode or "")
            or "snapshot" in (policy.history_mode or "")
        )
        observed = 0 if (
            policy.expected_frequency == "event_driven" and not tip_snapshot
        ) else 1
        # JQ-only (see _jquants_coverage_contracts). index_text omitted:
        # OTC would be empty required set, never invented weekend COMPLETE.
        planned = tuple(
            segment
            if policy.expected_frequency == "event_driven" and not tip_snapshot
            else replace(segment, expected_items=observed)
            for segment in plan_required_segments(policy, today)
        )
        record_required_segments(conn, planned)
        from storage.trusted_receipt import open_signed_receipt_authority

        try:
            authority = open_signed_receipt_authority()
        except RuntimeError:
            # Fall back to test keypair registered into public key registry.
            authority = None
            from tests.test_phase61_coverage_v2 import _signed_digests as _sd
        for segment in planned:
            raw = b'{"data":[{"ok":true}]}'
            if authority is not None:
                receipt = authority.issue(
                    required=segment,
                    run_id=run_id,
                    raw=raw,
                    observed_items=observed,
                    structured_row_count=observed,
                    raw_row_count=observed,
                    pagination_exhausted=True,
                    checked_at=today + "T16:00:00Z",
                )
            else:
                receipt = CollectionReceipt(
                    source=segment.source,
                    dataset=segment.dataset,
                    segment_id=segment.segment_id,
                    segment_start=segment.segment_start,
                    segment_end=segment.segment_end,
                    expected_scope=segment.expected_scope,
                    expected_items=segment.expected_items,
                    observed_items=observed,
                    raw_page_count=1,
                    raw_row_count=observed,
                    structured_row_count=observed,
                    pagination_exhausted=True,
                    digests=_sd(
                        dataset=segment.dataset,
                        segment_id=segment.segment_id,
                        source=segment.source,
                        run_id=run_id,
                        raw_digest="sha256:" + "1" * 64,
                        raw_count=observed,
                        structured_count=observed,
                        pagination_exhausted=True,
                        segment_start=segment.segment_start,
                        segment_end=segment.segment_end,
                        checked_at=today + "T16:00:00Z",
                    ),
                    run_id=run_id,
                    status="SUCCESS",
                    error=None,
                    checked_at=today + "T16:00:00Z",
                )
            record_collection_receipt(conn, receipt)
    # Generation pin for READY coherence (must be > 0, not mere table presence).
    try:
        conn.execute(
            "INSERT INTO sync_change_state (feed, last_applied_change_seq, updated_at) "
            "VALUES ('jquants_records', 1, ?) "
            "ON CONFLICT(feed) DO UPDATE SET last_applied_change_seq=1",
            (today + "T16:00:00Z",),
        )
    except Exception:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sync_change_state ("
            "feed TEXT PRIMARY KEY, last_applied_change_seq INTEGER, updated_at TEXT)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO sync_change_state "
            "(feed, last_applied_change_seq, updated_at) VALUES (?, ?, ?)",
            ("jquants_records", 1, today + "T16:00:00Z"),
        )
    conn.commit()
    store.close()
    return required


def test_collection_contract_covers_canonical_set_without_event_row_guesses():
    policies = {row.dataset_id: row for row in all_coverage_contracts()}
    assert {row.dataset_id for row in all_contracts()} <= set(policies)
    assert all(row.governance_tier in {"governed", "experimental"} for row in policies.values())
    assert policies["fins_summary"].coverage_mode == "event_reconciled"
    assert policies["fins_summary"].expected_frequency == "event_driven"


def test_ready_source_run_stays_jquants_and_jsda_watermark_comes_from_receipts(
    tmp_path,
):
    path = tmp_path / "mixed-sources.sqlite"
    store = SqliteStore(path)
    today = datetime.now(timezone.utc).date().isoformat()
    run_id = _seed_control(store._conn, ("equities_bars_daily",), today)  # noqa: SLF001
    store._conn.execute(  # noqa: SLF001
        "INSERT INTO ingestion_run_log (ran_at,source,runtime,status,detail) "
        "VALUES (?,'jsda','local','pass','{}')",
        (today,),
    )
    selected, _, validations = snapshot_module._latest_complete_run(  # noqa: SLF001
        store._conn, ("equities_bars_daily",)  # noqa: SLF001
    )
    assert selected == run_id and len(validations) == 1

    watermarks = snapshot_module._watermarks_for(  # noqa: SLF001
        store._conn,  # noqa: SLF001
        ("equities_bars_daily", "jsda_tokyo_repo_rates"),
        [{
            "dataset": "jsda_tokyo_repo_rates",
            "status": "COMPLETE",
            "observed_end": "2025-04-02",
            "evaluated_at": "2026-08-11T00:00:00Z",
        }],
    )
    assert watermarks[-1] == {
        "dataset": "jsda_tokyo_repo_rates",
        "last_event_date": "2025-04-02",
        "last_ingested_at": "2026-08-11T00:00:00Z",
        "derived_from": "coverage_v2_receipts",
    }
    store.close()


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


def test_ready_rejects_missing_middle_segment_and_writes_no_artifact(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        snapshot_module, "all_coverage_contracts", _jquants_coverage_contracts
    )
    path = tmp_path / "middle-gap.sqlite"
    required = _seed_publishable_db(path)
    conn = sqlite3.connect(path)
    victim = conn.execute(
        "SELECT segment_id FROM collection_receipts "
        "WHERE dataset='fins_summary' ORDER BY segment_start LIMIT 1 OFFSET 1"
    ).fetchone()
    assert victim is not None
    conn.execute(
        "DELETE FROM collection_receipts "
        "WHERE source='jquants' AND dataset='fins_summary' AND segment_id=?",
        (victim[0],),
    )
    conn.commit()
    conn.close()

    snapshot_dir = tmp_path / "snapshots"
    with pytest.raises(SnapshotRejected, match="coverage not COMPLETE|Coverage V2"):
        publish_ready_snapshot(
            path, snapshot_dir, required_datasets=required
        )

    assert not list(snapshot_dir.glob("sha256_*"))
    with pytest.raises(FileNotFoundError, match="no READY"):
        latest_ready_snapshot(snapshot_dir)
    conn = sqlite3.connect(path)
    assert conn.execute(
        "SELECT snapshot_ready FROM local_snapshot_policy WHERE singleton=1"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT state FROM snapshot_publications ORDER BY created_at DESC LIMIT 1"
    ).fetchone()[0] == "REJECTED"
    conn.close()


def test_ready_publication_is_atomic_content_addressed_and_read_only(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        snapshot_module, "all_coverage_contracts", _jquants_coverage_contracts
    )
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
    proof = ready.manifest["coverage_v2_proof"]
    assert proof["format"] == "coverage-v2-proof/v1"
    assert proof["status"] == "COMPLETE"
    assert proof["policy_version"] == "collection-coverage/v2"
    assert proof["dataset_count"] == len(required)
    assert proof["segment_count"] == proof["receipt_count"] > len(required)
    assert proof["proof_digest"].startswith("sha256:")
    assert len(proof["proof_digest"]) == 71
    assert len(proof["datasets"]) == len(required)
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
        assert conn.execute(
            "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
        ).fetchone()[0] == proof["segment_count"]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM jquants_records")

    repeated = publish_ready_snapshot(
        path, snapshot_dir, required_datasets=required
    )
    assert repeated.snapshot_id == ready.snapshot_id
    assert len(list_ready_snapshots(snapshot_dir)) == 1
