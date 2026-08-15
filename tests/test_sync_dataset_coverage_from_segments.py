"""Unit tests for surgical dataset_coverage re-aggregate from segments."""

from __future__ import annotations

import json
import sqlite3

import pytest

from storage.coverage_ledger import (
    aggregate_status_from_segment_counts,
    build_surgical_reagg_detail,
    honest_status_counts,
    sync_dataset_coverage_from_segments,
)


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


def test_aggregate_all_complete_is_complete():
    assert (
        aggregate_status_from_segment_counts({"COMPLETE": 104}) == "COMPLETE"
    )
    assert (
        aggregate_status_from_segment_counts({"COMPLETE": 164, "PARTIAL": 0})
        == "COMPLETE"
    )


def test_aggregate_any_partial_stays_partial():
    assert (
        aggregate_status_from_segment_counts({"COMPLETE": 100, "PARTIAL": 4})
        == "PARTIAL"
    )
    assert (
        aggregate_status_from_segment_counts({"PARTIAL": 3}) == "PARTIAL"
    )
    assert (
        aggregate_status_from_segment_counts(
            {"COMPLETE": 10, "STALE": 1}
        )
        == "PARTIAL"
    )


def test_aggregate_any_failed_is_failed():
    assert (
        aggregate_status_from_segment_counts(
            {"COMPLETE": 99, "FAILED": 1}
        )
        == "FAILED"
    )
    assert aggregate_status_from_segment_counts({"FAILED": 2}) == "FAILED"


def test_aggregate_empty_inventory_is_unknown_never_complete():
    assert aggregate_status_from_segment_counts({}) == "UNKNOWN"
    assert aggregate_status_from_segment_counts({"COMPLETE": 0}) == "UNKNOWN"


def test_honest_status_counts_drops_zeros():
    assert honest_status_counts({"COMPLETE": 104, "PARTIAL": 0}) == {
        "COMPLETE": 104
    }
    assert honest_status_counts({"COMPLETE": 100, "PARTIAL": 4}) == {
        "COMPLETE": 100,
        "PARTIAL": 4,
    }


def test_build_surgical_reagg_detail_merges_counts():
    existing = {
        "checks": [{"id": "C8", "status": "pass"}],
        "coverage_v2": {
            "required_segments": 104,
            "status_counts": {"COMPLETE": 100, "PARTIAL": 4},
        },
    }
    detail = build_surgical_reagg_detail(
        existing,
        status_counts={"COMPLETE": 104},
        required_segments=104,
        audit={"wave": "W70", "at": "2026-08-16T00:00:00+00:00"},
    )
    assert detail["aggregate_source"] == "surgical_reagg_from_coverage_segments"
    assert detail["coverage_v2"]["status_counts"] == {"COMPLETE": 104}
    assert detail["coverage_v2"]["required_segments"] == 104
    assert detail["coverage_v2"]["surgical_reagg"]["wave"] == "W70"
    assert detail["coverage_v2"]["surgical_reagg"]["prev_status_counts"] == {
        "COMPLETE": 100,
        "PARTIAL": 4,
    }
    # Preserve unrelated checks.
    assert detail["checks"] == [{"id": "C8", "status": "pass"}]


# ---------------------------------------------------------------------------
# DB integration (in-memory; never invents segments)
# ---------------------------------------------------------------------------


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE coverage_segments (
            source TEXT NOT NULL,
            dataset TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            segment_start TEXT,
            segment_end TEXT,
            expected_scope TEXT,
            expected_items INTEGER,
            status TEXT NOT NULL,
            receipt_run_id INTEGER,
            evaluated_at TEXT,
            detail_json TEXT,
            PRIMARY KEY (source, dataset, segment_id, policy_version)
        );
        CREATE TABLE dataset_coverage (
            dataset TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            policy_version TEXT,
            collection_scope TEXT,
            history_target_start TEXT,
            history_target_end_rule TEXT,
            coverage_mode TEXT,
            expected_frequency TEXT,
            universe_rule TEXT,
            raw_retention_required INTEGER,
            structured_reconciliation_required INTEGER,
            governance_tier TEXT,
            observed_start TEXT,
            observed_end TEXT,
            row_count INTEGER,
            source_run_id INTEGER,
            evaluated_at TEXT,
            detail_json TEXT
        );
        """
    )
    return conn


def _seed_dataset(
    conn: sqlite3.Connection,
    *,
    dataset: str,
    seg_statuses: list[tuple[str, int | None]],
    dc_status: str,
    prev_counts: dict[str, int],
    checks: list[dict] | None = None,
) -> None:
    for i, (status, receipt_run_id) in enumerate(seg_statuses):
        conn.execute(
            """
            INSERT INTO coverage_segments (
                source, dataset, segment_id, policy_version,
                segment_start, segment_end, expected_scope, expected_items,
                status, receipt_run_id, evaluated_at, detail_json
            ) VALUES (?, ?, ?, 'collection-coverage/v2',
                      ?, ?, '{}', 1, ?, ?, '2026-08-01T00:00:00+00:00', '{}')
            """,
            (
                "jquants",
                dataset,
                f"2020-{i+1:02d}",
                f"2020-{i+1:02d}-01",
                f"2020-{i+1:02d}-28",
                status,
                receipt_run_id,
            ),
        )
    detail = {
        "checks": checks or [{"id": "C8", "status": "pass"}],
        "coverage_v2": {
            "required_segments": len(seg_statuses),
            "status_counts": prev_counts,
        },
    }
    conn.execute(
        """
        INSERT INTO dataset_coverage (
            dataset, status, policy_version, governance_tier, detail_json
        ) VALUES (?, ?, 'collection-coverage/v2', 'governed', ?)
        """,
        (dataset, dc_status, json.dumps(detail)),
    )
    conn.commit()


def test_sync_promotes_when_all_segments_complete():
    conn = _make_conn()
    _seed_dataset(
        conn,
        dataset="fins_earnings_date",
        seg_statuses=[
            ("COMPLETE", 9001),
            ("COMPLETE", 9002),
            ("COMPLETE", 9003),
        ],
        dc_status="PARTIAL",
        prev_counts={"COMPLETE": 2, "PARTIAL": 1},
    )
    pre_segs = conn.execute(
        "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
    ).fetchone()[0]

    results = sync_dataset_coverage_from_segments(
        conn, datasets=["fins_earnings_date"], wave="test"
    )

    assert len(results) == 1
    assert results[0]["action"] == "promoted"
    assert results[0]["from"] == "PARTIAL"
    assert results[0]["to"] == "COMPLETE"
    assert results[0]["status_counts"] == {"COMPLETE": 3}

    row = conn.execute(
        "SELECT status, detail_json FROM dataset_coverage WHERE dataset=?",
        ("fins_earnings_date",),
    ).fetchone()
    assert row["status"] == "COMPLETE"
    detail = json.loads(row["detail_json"])
    assert detail["coverage_v2"]["status_counts"] == {"COMPLETE": 3}
    assert detail["aggregate_source"] == "surgical_reagg_from_coverage_segments"

    post_segs = conn.execute(
        "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
    ).fetchone()[0]
    assert post_segs == pre_segs  # segments untouched


def test_sync_stays_partial_when_any_segment_partial():
    conn = _make_conn()
    _seed_dataset(
        conn,
        dataset="equities_master",
        seg_statuses=[
            ("COMPLETE", 1),
            ("PARTIAL", None),
            ("COMPLETE", 2),
        ],
        dc_status="PARTIAL",
        prev_counts={"COMPLETE": 1, "PARTIAL": 2},
    )

    results = sync_dataset_coverage_from_segments(
        conn, datasets=["equities_master"]
    )

    assert results[0]["derived_status"] == "PARTIAL"
    assert results[0]["action"] in {"counts_refreshed", "verify_only"}
    row = conn.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?",
        ("equities_master",),
    ).fetchone()
    assert row["status"] == "PARTIAL"
    # Never invented COMPLETE.
    assert results[0].get("to", "PARTIAL") != "COMPLETE" or results[0][
        "action"
    ] == "verify_only"


def test_sync_refuses_empty_complete_segments():
    conn = _make_conn()
    _seed_dataset(
        conn,
        dataset="bad_empty",
        seg_statuses=[
            ("COMPLETE", None),  # empty-raw COMPLETE — forbidden
            ("COMPLETE", 0),
        ],
        dc_status="PARTIAL",
        prev_counts={"PARTIAL": 2},
    )

    results = sync_dataset_coverage_from_segments(
        conn, datasets=["bad_empty"]
    )

    assert results[0]["action"] == "skip_empty_complete_segments"
    row = conn.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?",
        ("bad_empty",),
    ).fetchone()
    assert row["status"] == "PARTIAL"  # not promoted


def test_sync_refuses_failing_checks_for_complete_promote():
    conn = _make_conn()
    _seed_dataset(
        conn,
        dataset="stale_c8",
        seg_statuses=[("COMPLETE", 10), ("COMPLETE", 11)],
        dc_status="PARTIAL",
        prev_counts={"COMPLETE": 1, "PARTIAL": 1},
        checks=[{"id": "C8", "status": "fail"}],
    )

    results = sync_dataset_coverage_from_segments(
        conn, datasets=["stale_c8"]
    )

    assert results[0]["action"] == "skip_failing_checks"
    row = conn.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?",
        ("stale_c8",),
    ).fetchone()
    assert row["status"] == "PARTIAL"


def test_sync_holds_already_complete_despite_historical_failing_checks():
    """Do not demote COMPLETE solely for stale C* fail noise (hold COMPLETE N)."""
    conn = _make_conn()
    _seed_dataset(
        conn,
        dataset="equities_bars_daily",
        seg_statuses=[("COMPLETE", 10), ("COMPLETE", 11)],
        dc_status="COMPLETE",
        prev_counts={"COMPLETE": 2},
        checks=[{"id": "C1", "status": "fail"}],
    )

    results = sync_dataset_coverage_from_segments(
        conn, datasets=["equities_bars_daily"]
    )

    assert results[0]["action"] == "verify_only"
    assert results[0]["status"] == "COMPLETE"
    row = conn.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?",
        ("equities_bars_daily",),
    ).fetchone()
    assert row["status"] == "COMPLETE"


def test_sync_verify_only_when_already_aligned():
    conn = _make_conn()
    _seed_dataset(
        conn,
        dataset="already_ok",
        seg_statuses=[("COMPLETE", 1), ("COMPLETE", 2)],
        dc_status="COMPLETE",
        prev_counts={"COMPLETE": 2},
    )

    results = sync_dataset_coverage_from_segments(
        conn, datasets=["already_ok"]
    )

    assert results[0]["action"] == "verify_only"
    assert results[0]["status"] == "COMPLETE"


def test_sync_dry_run_does_not_write():
    conn = _make_conn()
    _seed_dataset(
        conn,
        dataset="dry",
        seg_statuses=[("COMPLETE", 1), ("COMPLETE", 2)],
        dc_status="PARTIAL",
        prev_counts={"COMPLETE": 1, "PARTIAL": 1},
    )

    results = sync_dataset_coverage_from_segments(
        conn, datasets=["dry"], dry_run=True
    )

    assert results[0]["action"] == "promoted"
    assert results[0]["dry_run"] is True
    row = conn.execute(
        "SELECT status FROM dataset_coverage WHERE dataset=?",
        ("dry",),
    ).fetchone()
    assert row["status"] == "PARTIAL"  # not written


def test_sync_skip_missing_dataset_coverage():
    conn = _make_conn()
    # segments only — no dataset_coverage row (must not invent aggregate)
    conn.execute(
        """
        INSERT INTO coverage_segments (
            source, dataset, segment_id, policy_version,
            segment_start, segment_end, expected_scope, expected_items,
            status, receipt_run_id, evaluated_at, detail_json
        ) VALUES (
            'jquants', 'orphan', '2020-01', 'collection-coverage/v2',
            '2020-01-01', '2020-01-31', '{}', 1,
            'COMPLETE', 1, '2026-08-01T00:00:00+00:00', '{}'
        )
        """
    )
    conn.commit()

    results = sync_dataset_coverage_from_segments(
        conn, datasets=["orphan"]
    )

    assert results[0]["action"] == "skip_missing_dataset_coverage"
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM dataset_coverage WHERE dataset='orphan'"
        ).fetchone()[0]
        == 0
    )


def test_sync_demotes_when_segments_partial_after_stale_complete():
    """Honest SoT: if segs are PARTIAL, do not leave dataset COMPLETE."""
    conn = _make_conn()
    _seed_dataset(
        conn,
        dataset="stale_complete",
        seg_statuses=[("COMPLETE", 1), ("PARTIAL", None)],
        dc_status="COMPLETE",
        prev_counts={"COMPLETE": 2},
    )

    results = sync_dataset_coverage_from_segments(
        conn, datasets=["stale_complete"]
    )

    assert results[0]["action"] == "demoted"
    assert results[0]["to"] == "PARTIAL"
    row = conn.execute(
        "SELECT status, detail_json FROM dataset_coverage WHERE dataset=?",
        ("stale_complete",),
    ).fetchone()
    assert row["status"] == "PARTIAL"
    detail = json.loads(row["detail_json"])
    assert detail["coverage_v2"]["status_counts"] == {
        "COMPLETE": 1,
        "PARTIAL": 1,
    }
