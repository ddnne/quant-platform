"""READY publication coherence gates.

A READY snapshot can only be published when all coherence gates pass.
This module implements the comprehensive checks that must be satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data_contracts import all_coverage_contracts
from data_contracts.coverage import coverage_policy_binding
from pit.ready_evidence import LedgerTableMissing, ReadyLedgerSession


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
    session: ReadyLedgerSession,
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

    Interprets market-ledger facts from ReadyLedgerSession. Does not open SQLite.
    """
    if type(session) is not ReadyLedgerSession:
        raise TypeError("READY coherence requires ReadyLedgerSession")
    if not required_datasets:
        raise ValueError("required_datasets must not be empty")

    results: list[CoherenceGateResult] = []
    results.append(_check_coverage_completeness(session, required_datasets))
    results.append(_check_receipts_with_raw_retention(session, required_datasets))
    if run_id is not None:
        results.append(_check_validation_passing(session, required_datasets, run_id))
    else:
        results.append(_check_latest_validation_passing(session, required_datasets))
    results.append(_check_natural_key_migration_ready(session))
    results.append(_check_b0_quality_status(session))
    results.append(_check_change_sequence_advancing(session))
    return results


def _check_coverage_completeness(
    session: ReadyLedgerSession,
    required_datasets: tuple[str, ...],
) -> CoherenceGateResult:
    """Gate 1: All required governed datasets have COMPLETE coverage segments."""
    # Only check datasets that are both governed AND in required_datasets
    policies = {contract.dataset_id: contract for contract in all_coverage_contracts()}
    unknown_datasets = sorted(set(required_datasets) - set(policies))
    governed_datasets = {
        contract.dataset_id
        for contract in policies.values()
        if contract.governance_tier == "governed"
        and contract.dataset_id in required_datasets
    }
    if unknown_datasets:
        return CoherenceGateResult(
            gate_name="coverage_completeness",
            passed=False,
            reason=f"Unknown governed Coverage datasets: {unknown_datasets}",
            detail={"unknown_datasets": unknown_datasets},
        )

    try:
        segments = list(session.coverage_segments())
    except LedgerTableMissing:
        return CoherenceGateResult(
            gate_name="coverage_completeness",
            passed=False,
            reason="coverage_segments table does not exist",
            detail={"governed_count": len(governed_datasets)},
        )
    coverage_by_dataset = {
        dataset: [
            row
            for row in segments
            if row["dataset"] == dataset
            and row["policy_version"]
            == coverage_policy_binding(dataset)["policy_version"]
        ]
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
    session: ReadyLedgerSession,
    required_datasets: tuple[str, ...],
) -> CoherenceGateResult:
    """Gate 2: All COMPLETE segments have successful receipts with raw retention."""
    policies = {contract.dataset_id: contract for contract in all_coverage_contracts()}
    governed = tuple(
        dataset
        for dataset in required_datasets
        if dataset in policies and policies[dataset].governance_tier == "governed"
    )
    try:
        all_segments = list(session.complete_coverage_segments())
    except LedgerTableMissing:
        return CoherenceGateResult(
            gate_name="receipts_with_raw_retention",
            passed=False,
            reason="coverage_segments table does not exist",
            detail={"complete_segments_checked": 0},
        )
    segments = [
        row
        for row in all_segments
        if row["dataset"] in governed
        and row["policy_version"]
        == coverage_policy_binding(str(row["dataset"]))["policy_version"]
    ]

    receipts_by_dataset = {}
    try:
        for dataset in governed:
            receipts_by_dataset[dataset] = list(
                session.collection_receipts_for_dataset(dataset)
            )
    except LedgerTableMissing:
        return CoherenceGateResult(
            gate_name="receipts_with_raw_retention",
            passed=False,
            reason="collection_receipts table does not exist",
            detail={"complete_segments_checked": len(segments)},
        )

    current_segment_datasets = {str(row["dataset"]) for row in segments}
    issues = [
        f"{dataset} (no COMPLETE segments for governed policy)"
        for dataset in governed
        if dataset not in current_segment_datasets
    ]
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

        receipt = segment_receipts[0]  # ORDER BY checked_at DESC → latest first

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
    session: ReadyLedgerSession,
    required_datasets: tuple[str, ...],
    run_id: int,
) -> CoherenceGateResult:
    """Gate 3: All required datasets have passing validation for the given run."""
    try:
        rows = session.ingestion_validation_status_rows(run_id)
    except LedgerTableMissing:
        return CoherenceGateResult(
            gate_name="validation_passing",
            passed=False,
            reason="ingestion_validation table does not exist",
            detail={"run_id": run_id},
        )

    validation_by_dataset = {dataset: status for dataset, status in rows}

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
    session: ReadyLedgerSession,
    required_datasets: tuple[str, ...],
) -> CoherenceGateResult:
    """Gate 3: All required datasets have passing latest validation."""
    try:
        latest_run_id = session.max_ingestion_validation_run_id()
    except LedgerTableMissing:
        return CoherenceGateResult(
            gate_name="validation_passing",
            passed=False,
            reason="ingestion_validation table does not exist",
            detail={"run_id": None},
        )

    if latest_run_id is None:
        return CoherenceGateResult(
            gate_name="validation_passing",
            passed=False,
            reason="No validation runs found",
            detail={"run_id": None},
        )

    return _check_validation_passing(session, required_datasets, latest_run_id)


def _check_natural_key_migration_ready(
    session: ReadyLedgerSession,
) -> CoherenceGateResult:
    """Gate 4: Natural key migration is READY (schema-aligned)."""
    probed = session.natural_key_migration_probe()
    if probed is not None:
        state, source = probed
        passed = str(state).upper() == "READY"
        return CoherenceGateResult(
            gate_name="natural_key_migration_ready",
            passed=passed,
            reason=(
                "Natural key migration is READY"
                if passed
                else f"Natural key migration state: {state}"
            ),
            detail={"state": state, "source": source},
        )

    return CoherenceGateResult(
        gate_name="natural_key_migration_ready",
        passed=False,
        reason="No natural key migration evidence found",
        detail={"state": None},
    )


def _check_b0_quality_status(
    session: ReadyLedgerSession,
) -> CoherenceGateResult:
    """Gate 5: B0 quality checks pass."""
    try:
        row = session.latest_snapshot_quality()
    except LedgerTableMissing:
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
            "evaluated_at": row["evaluated_at"],
            "summary": row["summary"],
        },
    )


def _check_change_sequence_advancing(
    session: ReadyLedgerSession,
) -> CoherenceGateResult:
    """Gate 6: Change sequence is advancing (schema-aligned)."""
    best: int | None = None
    for max_seq in session.change_sequence_maxima():
        if best is None or max_seq > best:
            best = max_seq
        if max_seq > 0:
            return CoherenceGateResult(
                gate_name="change_sequence_advancing",
                passed=True,
                reason=f"Change sequence advancing (max_seq={max_seq})",
                detail={"max_change_seq": max_seq},
            )

    return CoherenceGateResult(
        gate_name="change_sequence_advancing",
        passed=False,
        reason=(
            f"Change sequence not advancing (max_seq={best})"
            if best is not None
            else "No change sequence table/evidence found"
        ),
        detail={"max_change_seq": best},
    )


__all__ = [
    "CoherenceGateResult",
    "check_ready_coherence",
]
