"""Test READY publication coherence gates with and without receipts.

This test proves that coherence fails without receipts but passes with
synthetic COMPLETE receipts in a fixture database.

Lane C Requirement: Unit test proves coherence fails without receipts;
passes with synthetic COMPLETE receipts only in fixture DB.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import tempfile

import pytest

from data_contracts import coverage_contract_for, all_coverage_contracts
from storage.coverage_ledger import POLICY_VERSION
from paper_runtime.coherence import check_ready_coherence, CoherenceGateResult
from storage import (
    CollectionReceipt,
    record_collection_receipt,
    record_required_segments,
)
from storage.coverage_ledger import plan_required_segments
from storage.sqlite_store import SqliteStore


@pytest.fixture
def fixture_db_with_schema():
    """Create a fixture database with all required tables but no data."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = Path(f.name)

    # Initialize database with schema
    store = SqliteStore(db_path)
    conn = store._conn

    # Create coverage tables
    migration = (
        Path(__file__).resolve().parents[1]
        / "platform" / "workers" / "ingestion-premium" / "migrations"
        / "0007_collection_coverage_v2.sql"
    )
    conn.executescript(migration.read_text(encoding="utf-8"))

    # Create additional tables needed for coherence checks
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_validation (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL,
            dataset TEXT NOT NULL,
            started_at TEXT NOT NULL,
            status TEXT NOT NULL,
            metrics_json TEXT,
            UNIQUE(run_id, dataset)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS natural_key_migration (
            id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            migrated_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS snapshot_quality_results (
            id INTEGER PRIMARY KEY,
            build_id TEXT NOT NULL UNIQUE,
            policy_version TEXT NOT NULL,
            status TEXT NOT NULL,
            evaluated_at TEXT,
            summary_json TEXT,
            results_json TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_change_log (
            id INTEGER PRIMARY KEY,
            change_seq INTEGER NOT NULL,
            dataset TEXT NOT NULL,
            change_type TEXT NOT NULL
        )
    """)

    conn.commit()
    store.close()

    yield db_path

    # Cleanup
    db_path.unlink()


@pytest.fixture
def fixture_db_with_coverage_without_receipts(fixture_db_with_schema):
    """Create fixture with coverage segments but no receipts (should fail coherence)."""
    store = SqliteStore(fixture_db_with_schema)
    conn = store._conn

    # Plan and record required segments for a governed dataset
    policy = coverage_contract_for("fins_summary")
    required_segments = plan_required_segments(policy, "2025-03-31")

    record_required_segments(conn, required_segments)
    conn.commit()
    store.close()

    return fixture_db_with_schema


@pytest.fixture
def fixture_db_with_complete_coverage_and_receipts(fixture_db_with_schema):
    """Create fixture with COMPLETE coverage and synthetic receipts (should pass coherence)."""
    store = SqliteStore(fixture_db_with_schema)
    conn = store._conn

    # Plan and record required segments for a governed dataset
    policy = coverage_contract_for("fins_summary")
    required_segments = plan_required_segments(policy, "2025-03-31")

    record_required_segments(conn, required_segments)

    # Create synthetic COMPLETE receipts for each segment
    checked_at = datetime.now(timezone.utc).isoformat()
    for i, segment in enumerate(required_segments):
        receipt = CollectionReceipt(
            source=segment.source,
            dataset=segment.dataset,
            segment_id=segment.segment_id,
            segment_start=segment.segment_start,
            segment_end=segment.segment_end,
            expected_scope=segment.expected_scope,
            expected_items=segment.expected_items,
            observed_items=1 if segment.expected_items != 0 else 0,  # Event-driven can be 0
            raw_page_count=1,  # Has raw retention
            raw_row_count=1 if segment.expected_items != 0 else 0,
            structured_row_count=1 if segment.expected_items != 0 else 0,
            pagination_exhausted=True,  # Pagination exhausted
            digests={
                "raw": "sha256:" + "a" * 64,
                "eligibility": "TRUSTED_COLLECTION",
                "issuer_class": "TrustedReceiptIssuer",
                "issuer_id": "jquants:run:1",
                "parser_normalizer_version": "coverage-receipt/v2",
            },
            run_id=1,
            status="SUCCESS",
            error=None,
            checked_at=checked_at,
        )
        record_collection_receipt(conn, receipt)

    # Update all coverage segments to COMPLETE status for this test
    conn.execute("""
        UPDATE coverage_segments
        SET status = ?, receipt_run_id = ?, evaluated_at = ?, detail_json = ?
        WHERE dataset = ? AND policy_version = ?
    """, (
        "COMPLETE", 1, datetime.now(timezone.utc).isoformat(),
        '{"reason": "synthetic COMPLETE receipts for test"}',
        "fins_summary", POLICY_VERSION
    ))

    # Add validation pass
    conn.execute("""
        INSERT INTO ingestion_validation (run_id, dataset, started_at, status, metrics_json)
        VALUES (?, ?, ?, ?, ?)
    """, (
        1,
        "fins_summary",
        datetime.now(timezone.utc).isoformat(),
        "pass",
        '{"validation_status": "pass", "source": "ingestion_validation"}'
    ))

    # Add natural key migration READY
    conn.execute("""
        INSERT INTO natural_key_migration (state, migrated_at)
        VALUES (?, ?)
    """, ("READY", datetime.now(timezone.utc).isoformat()))

    # Add B0 quality PASS
    conn.execute("""
        INSERT INTO snapshot_quality_results (build_id, policy_version, status, summary_json, results_json, evaluated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("test-build-1", "v1", "PASS", "{}", "{}", datetime.now(timezone.utc).isoformat()))

    # Add change sequence
    conn.execute("""
        INSERT INTO ingestion_change_log (change_seq, dataset, change_type)
        VALUES (?, ?, ?)
    """, (1, "fins_summary", "insert"))

    conn.commit()
    store.close()

    return fixture_db_with_schema


def test_coherence_fails_without_receipts(fixture_db_with_coverage_without_receipts):
    """Test that READY coherence fails when coverage segments exist but have no receipts."""
    store = SqliteStore(fixture_db_with_coverage_without_receipts)
    conn = store._conn

    # Get governed datasets
    governed_datasets = tuple(
        c.dataset_id
        for c in all_coverage_contracts()
        if c.governance_tier == "governed"
    )

    # Check coherence
    results = check_ready_coherence(
        conn, fixture_db_with_coverage_without_receipts, governed_datasets
    )

    store.close()

    # Coherence should fail
    assert len(results) > 0, "Coherence check should return results"

    # Find the coverage_completeness gate result - this should fail because
    # segments without receipts can't be COMPLETE
    coverage_gate = next(
        (r for r in results if r.gate_name == "coverage_completeness"),
        None
    )
    assert coverage_gate is not None, "Should have coverage_completeness gate"

    # The coverage gate should FAIL because segments without receipts aren't COMPLETE
    assert coverage_gate.passed is False, "Coverage gate should fail without COMPLETE segments"

    # The receipts gate should PASS because there are no COMPLETE segments to check
    receipts_gate = next(
        (r for r in results if r.gate_name == "receipts_with_raw_retention"),
        None
    )
    assert receipts_gate is not None, "Should have receipts_with_raw_retention gate"
    assert receipts_gate.passed is True, "Receipts gate should pass when no COMPLETE segments exist"


def test_coherence_passes_with_synthetic_complete_receipts(fixture_db_with_complete_coverage_and_receipts):
    """Test that READY coherence passes with synthetic COMPLETE receipts only."""
    store = SqliteStore(fixture_db_with_complete_coverage_and_receipts)
    conn = store._conn

    # Check coherence only for the specific dataset we've set up
    required_datasets = ("fins_summary",)

    # Check coherence
    results = check_ready_coherence(
        conn, fixture_db_with_complete_coverage_and_receipts, required_datasets
    )

    store.close()

    # All gates should pass
    assert len(results) > 0, "Coherence check should return results"

    failed_gates = [r for r in results if not r.passed]
    assert len(failed_gates) == 0, (
        f"All coherence gates should pass with synthetic COMPLETE receipts. "
        f"Failed gates: {[f'{r.gate_name}: {r.reason}' for r in failed_gates]}"
    )

    # Specifically check the receipts gate
    receipts_gate = next(
        (r for r in results if r.gate_name == "receipts_with_raw_retention"),
        None
    )
    assert receipts_gate is not None, "Should have receipts_with_raw_retention gate"
    assert receipts_gate.passed is True, "Receipts gate should pass with COMPLETE receipts"


def test_coverage_completeness_gate_requires_segments(fixture_db_with_schema):
    """Test that coverage_completeness gate requires COMPLETE segments."""
    store = SqliteStore(fixture_db_with_schema)
    conn = store._conn

    # No segments recorded
    governed_datasets = tuple(
        c.dataset_id
        for c in all_coverage_contracts()
        if c.governance_tier == "governed"
    )

    results = check_ready_coherence(
        conn, fixture_db_with_schema, governed_datasets
    )

    store.close()

    # Coverage completeness gate should fail
    coverage_gate = next(
        (r for r in results if r.gate_name == "coverage_completeness"),
        None
    )
    assert coverage_gate is not None, "Should have coverage_completeness gate"
    assert coverage_gate.passed is False, "Coverage completeness should fail without COMPLETE segments"


def test_receipts_gate_checks_all_requirements(fixture_db_with_schema):
    """Test that receipts gate checks all receipt requirements for COMPLETE segments."""
    store = SqliteStore(fixture_db_with_schema)
    conn = store._conn

    # Create a segment and make it COMPLETE manually
    policy = coverage_contract_for("fins_summary")
    required_segments = plan_required_segments(policy, "2025-01-31")
    segment = required_segments[0]

    # Record as COMPLETE (manually override the evaluation)
    conn.execute("""
        INSERT INTO coverage_segments
        (source, dataset, segment_id, policy_version, segment_start, segment_end,
         expected_scope, expected_items, status, receipt_run_id, evaluated_at, detail_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        segment.source, segment.dataset, segment.segment_id, POLICY_VERSION,
        segment.segment_start, segment.segment_end,
        '{"coverage_mode": "full", "expected_frequency": "event_driven"}',
        segment.expected_items, "COMPLETE", 1,
        datetime.now(timezone.utc).isoformat(),
        '{"reason": "manually set to COMPLETE for testing"}'
    ))

    # Create a receipt without raw retention (raw_page_count = 0)
    bad_receipt = CollectionReceipt(
        source=segment.source,
        dataset=segment.dataset,
        segment_id=segment.segment_id,
        segment_start=segment.segment_start,
        segment_end=segment.segment_end,
        expected_scope=segment.expected_scope,
        expected_items=segment.expected_items,
        observed_items=1,
        raw_page_count=0,  # Missing raw retention
        raw_row_count=1,
        structured_row_count=1,
        pagination_exhausted=True,
        digests={},  # No raw digest
        run_id=1,
        status="SUCCESS",
        error=None,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
    record_collection_receipt(conn, bad_receipt)
    conn.commit()

    governed_datasets = tuple(
        c.dataset_id
        for c in all_coverage_contracts()
        if c.governance_tier == "governed"
    )

    results = check_ready_coherence(
        conn, fixture_db_with_schema, governed_datasets
    )

    store.close()

    # Receipts gate should fail due to missing raw retention in COMPLETE segment
    receipts_gate = next(
        (r for r in results if r.gate_name == "receipts_with_raw_retention"),
        None
    )
    assert receipts_gate is not None, "Should have receipts_with_raw_retention gate"
    assert receipts_gate.passed is False, "Receipts gate should fail with missing raw retention in COMPLETE segment"
    assert "no raw" in receipts_gate.reason.lower() or "raw" in receipts_gate.reason.lower(), \
        f"Should mention raw retention issue, got: {receipts_gate.reason}"


def test_synthetic_receipts_must_match_required_scope(fixture_db_with_schema):
    """Test that synthetic receipts must exactly match required segment scope."""
    store = SqliteStore(fixture_db_with_schema)
    conn = store._conn

    policy = coverage_contract_for("fins_summary")
    required_segments = plan_required_segments(policy, "2025-01-31")
    segment = required_segments[0]

    record_required_segments(conn, [segment])

    # Create a receipt with mismatched scope
    mismatched_receipt = CollectionReceipt(
        source=segment.source,
        dataset=segment.dataset,
        segment_id=segment.segment_id,
        segment_start=segment.segment_start,
        segment_end=segment.segment_end,
        expected_scope={"wrong": "scope"},  # Mismatched scope
        expected_items=segment.expected_items,
        observed_items=1,
        raw_page_count=1,
        raw_row_count=1,
        structured_row_count=1,
        pagination_exhausted=True,
        digests={"raw": "sha256:" + "a" * 64},
        run_id=1,
        status="SUCCESS",
        error=None,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
    record_collection_receipt(conn, mismatched_receipt)
    conn.commit()

    # Read segments - the segment should not be COMPLETE
    from storage.coverage_ledger import read_coverage_segments
    segments = read_coverage_segments(fixture_db_with_schema, dataset="fins_summary")

    store.close()

    # The segment should not be COMPLETE due to scope mismatch
    assert len(segments) == 1, "Should have one segment"
    assert segments[0]["status"] != "COMPLETE", \
        "Segment should not be COMPLETE with mismatched receipt scope"
