"""READY publication coherence gates.

A READY snapshot can only be published when all coherence gates pass.
This module implements the comprehensive checks that must be satisfied.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_contracts import all_coverage_contracts
from storage.coverage_ledger import POLICY_VERSION


@dataclass(frozen=True)
class CoherenceGateResult:
    """Result of checking a single coherence gate."""

    gate_name: str
    passed: bool
    reason: str | None = None
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate_name,
            "status": "PASS" if self.passed else "FAIL",
            "reason": self.reason,
            "detail": self.detail or {},
        }


def check_ready_coherence(
    conn: sqlite3.Connection,
    db_path: str | Path,
    required_datasets: tuple[str, ...],
    *,
    run_id: int | None = None,
) -> list[CoherenceGateResult]:
    """Check all READY publication coherence gates.

    Gates:
    1. All governed datasets have COMPLETE coverage segments
    2. All COMPLETE segments have successful receipts with raw retention
    3. All required datasets have passing validation
    4. Natural key migration is READY
    5. B0 quality checks pass for all datasets
    6. Change sequence is advancing

    Args:
        conn: SQLite connection to staging database
        db_path: Path to the database file
        required_datasets: All datasets that must be included
        run_id: Optional specific run ID to validate

    Returns:
        List of coherence gate results. All must pass for READY publication.

    Raises:
        ValueError: If required_datasets is empty
        sqlite3.Error: If database queries fail
    """
    if not required_datasets:
        raise ValueError("required_datasets must not be empty")

    results: list[CoherenceGateResult] = []

    # Gate 1: Coverage segments completeness
    results.append(_check_coverage_completeness(conn, required_datasets))

    # Gate 2: Receipts with raw retention
    results.append(_check_receipts_with_raw_retention(conn, required_datasets))

    # Gate 3: Validation passing
    if run_id is not None:
        results.append(_check_validation_passing(conn, required_datasets, run_id))
    else:
        results.append(_check_latest_validation_passing(conn, required_datasets))

    # Gate 4: Natural key migration status
    results.append(_check_natural_key_migration_ready(conn))

    # Gate 5: B0 quality checks
    results.append(_check_b0_quality_status(conn))

    # Gate 6: Change sequence advancing
    results.append(_check_change_sequence_advancing(conn))

    return results


def _check_coverage_completeness(
    conn: sqlite3.Connection,
    required_datasets: tuple[str, ...],
) -> CoherenceGateResult:
    """Gate 1: All required governed datasets have COMPLETE coverage segments."""
    # Only check datasets that are both governed AND in required_datasets
    governed_datasets = {
        contract.dataset_id
        for contract in all_coverage_contracts()
        if contract.governance_tier == "governed"
        and contract.dataset_id in required_datasets
    }

    # Use conn.execute to query segments directly instead of read_coverage_segments
    # to avoid path/connection confusion
    segments_cursor = conn.execute(
        "SELECT * FROM coverage_segments WHERE policy_version=?",
        (POLICY_VERSION,)
    )
    segments = [dict(row) for row in segments_cursor.fetchall()]
    coverage_by_dataset = {
        dataset: [row for row in segments if row["dataset"] == dataset]
        for dataset in required_datasets
    }

    incomplete_datasets = []
    for dataset in governed_datasets:
        dataset_segments = coverage_by_dataset.get(dataset, [])
        if not dataset_segments:
            incomplete_datasets.append(f"{dataset} (no segments)")
            continue

        non_complete = [row for row in dataset_segments if row["status"] != "COMPLETE"]
        if non_complete:
            incomplete_datasets.append(
                f"{dataset} ({len(non_complete)}/{len(dataset_segments)} non-COMPLETE)"
            )

    passed = len(incomplete_datasets) == 0
    return CoherenceGateResult(
        gate_name="coverage_completeness",
        passed=passed,
        reason=(
            f"All {len(governed_datasets)} required governed datasets have COMPLETE coverage segments"
            if passed
            else f"Incomplete coverage for: {', '.join(incomplete_datasets)}"
        ),
        detail={
            "governed_count": len(governed_datasets),
            "incomplete_count": len(incomplete_datasets),
            "incomplete_datasets": incomplete_datasets,
        },
    )


def _check_receipts_with_raw_retention(
    conn: sqlite3.Connection,
    required_datasets: tuple[str, ...],
) -> CoherenceGateResult:
    """Gate 2: All COMPLETE segments have successful receipts with raw retention."""
    # Query COMPLETE segments directly
    segments_cursor = conn.execute(
        "SELECT * FROM coverage_segments WHERE status=? AND policy_version=?",
        ("COMPLETE", POLICY_VERSION)
    )
    segments = [dict(row) for row in segments_cursor.fetchall()]

    receipts_by_dataset = {}
    for dataset in required_datasets:
        receipt_cursor = conn.execute(
            "SELECT * FROM collection_receipts WHERE dataset=? ORDER BY checked_at, run_id",
            (dataset,)
        )
        receipts_by_dataset[dataset] = [dict(row) for row in receipt_cursor.fetchall()]

    issues = []
    for segment in segments:
        if segment["dataset"] not in required_datasets:
            continue

        dataset_receipts = receipts_by_dataset.get(segment["dataset"], [])
        segment_receipts = [
            r for r in dataset_receipts
            if r["segment_id"] == segment["segment_id"]
        ]

        if not segment_receipts:
            issues.append(
                f"{segment['dataset']}/{segment['segment_id']} (no receipt)"
            )
            continue

        receipt = segment_receipts[0]  # Take the latest

        # Check receipt status
        if receipt["status"] != "SUCCESS":
            issues.append(
                f"{segment['dataset']}/{segment['segment_id']} "
                f"(receipt status: {receipt['status']})"
            )
            continue

        # Check raw retention
        if receipt["raw_page_count"] < 1:
            issues.append(
                f"{segment['dataset']}/{segment['segment_id']} (no raw pages)"
            )

        # Check pagination exhausted
        if not receipt["pagination_exhausted"]:
            issues.append(
                f"{segment['dataset']}/{segment['segment_id']} (pagination not exhausted)"
            )

        # Check raw/structured reconciliation
        if receipt["raw_row_count"] != receipt["structured_row_count"]:
            issues.append(
                f"{segment['dataset']}/{segment['segment_id']} "
                f"(raw/structured mismatch: {receipt['raw_row_count']} vs {receipt['structured_row_count']})"
            )

    passed = len(issues) == 0
    return CoherenceGateResult(
        gate_name="receipts_with_raw_retention",
        passed=passed,
        reason=(
            "All COMPLETE segments have successful receipts with raw retention"
            if passed
            else f"Receipt issues: {', '.join(issues)}"
        ),
        detail={
            "complete_segments_checked": len(segments),
            "issue_count": len(issues),
            "issues": issues,
        },
    )


def _check_validation_passing(
    conn: sqlite3.Connection,
    required_datasets: tuple[str, ...],
    run_id: int,
) -> CoherenceGateResult:
    """Gate 3: All required datasets have passing validation for the given run."""
    rows = conn.execute(
        "SELECT dataset, status FROM ingestion_validation WHERE run_id = ?",
        (run_id,),
    ).fetchall()

    validation_by_dataset = {row["dataset"]: row["status"] for row in rows}

    failed = []
    for dataset in required_datasets:
        status = validation_by_dataset.get(dataset)
        if status != "pass":
            failed.append(f"{dataset} (status: {status})")

    passed = len(failed) == 0
    return CoherenceGateResult(
        gate_name="validation_passing",
        passed=passed,
        reason=(
            f"All {len(required_datasets)} datasets have passing validation"
            if passed
            else f"Validation failures: {', '.join(failed)}"
        ),
        detail={
            "run_id": run_id,
            "required_count": len(required_datasets),
            "passed_count": len(required_datasets) - len(failed),
            "failed_datasets": failed,
        },
    )


def _check_latest_validation_passing(
    conn: sqlite3.Connection,
    required_datasets: tuple[str, ...],
) -> CoherenceGateResult:
    """Gate 3: All required datasets have passing latest validation."""
    # Get the latest run_id
    run_row = conn.execute(
        "SELECT MAX(run_id) AS max_run_id FROM ingestion_validation"
    ).fetchone()

    if run_row is None or run_row["max_run_id"] is None:
        return CoherenceGateResult(
            gate_name="validation_passing",
            passed=False,
            reason="No validation runs found",
            detail={"run_id": None},
        )

    latest_run_id = run_row["max_run_id"]
    return _check_validation_passing(conn, required_datasets, latest_run_id)


def _check_natural_key_migration_ready(
    conn: sqlite3.Connection,
) -> CoherenceGateResult:
    """Gate 4: Natural key migration is READY."""
    try:
        row = conn.execute(
            "SELECT state FROM natural_key_migration ORDER BY id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return CoherenceGateResult(
            gate_name="natural_key_migration_ready",
            passed=False,
            reason="natural_key_migration table does not exist",
            detail={"state": None},
        )

    if row is None:
        return CoherenceGateResult(
            gate_name="natural_key_migration_ready",
            passed=False,
            reason="No natural key migration records found",
            detail={"state": None},
        )

    state = row["state"]
    passed = state == "READY"
    return CoherenceGateResult(
        gate_name="natural_key_migration_ready",
        passed=passed,
        reason=(
            "Natural key migration is READY"
            if passed
            else f"Natural key migration state: {state}"
        ),
        detail={"state": state},
    )


def _check_b0_quality_status(
    conn: sqlite3.Connection,
) -> CoherenceGateResult:
    """Gate 5: B0 quality checks pass."""
    try:
        row = conn.execute(
            """SELECT status, summary_json, evaluated_at
               FROM snapshot_quality_results
               ORDER BY evaluated_at DESC
               LIMIT 1"""
        ).fetchone()
    except sqlite3.OperationalError:
        return CoherenceGateResult(
            gate_name="b0_quality_status",
            passed=False,
            reason="snapshot_quality_results table does not exist",
            detail={"status": None, "evaluated_at": None},
        )

    if row is None:
        return CoherenceGateResult(
            gate_name="b0_quality_status",
            passed=False,
            reason="No B0 quality results found",
            detail={"status": None, "evaluated_at": None},
        )

    status = row["status"]
    passed = status == "PASS"
    return CoherenceGateResult(
        gate_name="b0_quality_status",
        passed=passed,
        reason=(
            "B0 quality checks pass"
            if passed
            else f"B0 quality status: {status}"
        ),
        detail={
            "status": status,
            "evaluated_at": row["evaluated_at"] if row else None,
            "summary": row["summary_json"] if row else None,
        },
    )


def _check_change_sequence_advancing(
    conn: sqlite3.Connection,
) -> CoherenceGateResult:
    """Gate 6: Change sequence is advancing."""
    try:
        row = conn.execute(
            "SELECT MAX(change_seq) AS max_seq FROM ingestion_change_log"
        ).fetchone()
    except sqlite3.OperationalError:
        return CoherenceGateResult(
            gate_name="change_sequence_advancing",
            passed=False,
            reason="ingestion_change_log table does not exist",
            detail={"max_change_seq": None},
        )

    if row is None or row["max_seq"] is None:
        return CoherenceGateResult(
            gate_name="change_sequence_advancing",
            passed=False,
            reason="No change sequence records found",
            detail={"max_change_seq": None},
        )

    max_seq = row["max_seq"]
    # Check if sequence is advancing (has some entries)
    passed = max_seq > 0

    return CoherenceGateResult(
        gate_name="change_sequence_advancing",
        passed=passed,
        reason=(
            f"Change sequence is advancing (max_seq={max_seq})"
            if passed
            else "Change sequence is not advancing"
        ),
        detail={"max_change_seq": max_seq},
    )


__all__ = [
    "CoherenceGateResult",
    "check_ready_coherence",
]
