"""Coverage V2 proof evidence for paper data snapshots.

READY stays fail-closed. Empty DB and PARTIAL coverage cannot publish READY.
This module verifies receipts and bounded proof digests; it does not decide READY.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from data_contracts.coverage import POLICY_VERSION as COVERAGE_POLICY_VERSION


def _coverage_v2_proof(
    conn: sqlite3.Connection,
    required: tuple[str, ...],
    coverage_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify governed segment receipts; return a bounded manifest proof."""
    from paper_runtime.snapshot import (
        SnapshotRejected,
        _canonical_digest,
        all_coverage_contracts,
    )

    if COVERAGE_POLICY_VERSION != "collection-coverage/v2":
        raise SnapshotRejected(
            "READY publication requires collection-coverage/v2"
        )
    policies = {policy.dataset_id: policy for policy in all_coverage_contracts()}
    governed = tuple(
        dataset for dataset in required
        if policies[dataset].governance_tier == "governed"
    )
    by_dataset = {str(row["dataset"]): row for row in coverage_rows}
    invalid_ledger = sorted(
        dataset for dataset in governed
        if dataset not in by_dataset
        or by_dataset[dataset].get("policy_version") != COVERAGE_POLICY_VERSION
        or by_dataset[dataset].get("status") != "COMPLETE"
    )
    if invalid_ledger:
        raise SnapshotRejected(
            f"Coverage V2 aggregate proof incomplete={invalid_ledger}"
        )

    placeholders = ",".join("?" for _ in governed)
    rows = conn.execute(
        """
        SELECT
            s.source, s.dataset, s.segment_id, s.policy_version,
            s.segment_start, s.segment_end, s.expected_scope,
            s.expected_items, s.status AS segment_status,
            s.receipt_run_id,
            r.segment_start AS receipt_start,
            r.segment_end AS receipt_end,
            r.expected_scope AS receipt_scope,
            r.expected_items AS receipt_expected_items,
            r.observed_items, r.raw_page_count, r.raw_row_count,
            r.structured_row_count, r.pagination_exhausted,
            r.digests_json, r.status AS receipt_status, r.error,
            r.checked_at
        FROM coverage_segments AS s
        LEFT JOIN collection_receipts AS r
          ON r.source = s.source
         AND r.dataset = s.dataset
         AND r.segment_id = s.segment_id
         AND r.run_id = s.receipt_run_id
        WHERE s.policy_version = ?
        """
        + f" AND s.dataset IN ({placeholders})"
        + " ORDER BY s.dataset, s.segment_start, s.segment_id",
        (COVERAGE_POLICY_VERSION, *governed),
    ).fetchall()
    segments_by_dataset: dict[str, list[sqlite3.Row]] = {
        dataset: [] for dataset in governed
    }
    proof_entries: list[dict[str, Any]] = []
    invalid_segments: list[tuple[str, str, str]] = []
    for row in rows:
        dataset = str(row["dataset"])
        segments_by_dataset[dataset].append(row)
        reason: str | None = None
        try:
            expected_scope = json.loads(str(row["expected_scope"]))
            receipt_scope = json.loads(str(row["receipt_scope"]))
            digests = json.loads(str(row["digests_json"]))
        except (TypeError, json.JSONDecodeError):
            expected_scope, receipt_scope, digests = None, None, None
            reason = "malformed receipt evidence"
        policy = policies[dataset]
        if row["segment_status"] != "COMPLETE":
            reason = "segment not COMPLETE"
        elif row["receipt_run_id"] is None or row["receipt_status"] != "SUCCESS":
            reason = "successful receipt missing"
        elif row["error"] not in (None, ""):
            reason = "receipt has error"
        elif (
            row["receipt_start"] != row["segment_start"]
            or row["receipt_end"] != row["segment_end"]
            or receipt_scope != expected_scope
            or row["receipt_expected_items"] != row["expected_items"]
        ):
            reason = "receipt scope mismatch"
        elif int(row["pagination_exhausted"] or 0) != 1:
            reason = "pagination not exhausted"
        elif (
            policy.expected_frequency != "event_driven"
            and row["expected_items"] is None
        ):
            reason = "non-event expected items missing"
        elif (
            row["expected_items"] is not None
            and int(row["observed_items"] or 0) != int(row["expected_items"])
        ):
            reason = "expected scope incomplete"
        elif int(row["raw_page_count"] or 0) < 1 or not isinstance(
            digests, dict
        ) or not isinstance(digests.get("raw"), str) or not digests.get("raw"):
            reason = "raw retention proof missing"
        elif (
            policy.structured_reconciliation_required
            and int(row["raw_row_count"] or 0)
            != int(row["structured_row_count"] or 0)
        ):
            reason = "raw/structured mismatch"
        elif (
            policy.expected_frequency != "event_driven"
            and int(row["observed_items"] or 0) == 0
        ):
            reason = "non-event receipt is empty"
        if reason is not None:
            invalid_segments.append((dataset, str(row["segment_id"]), reason))
            continue
        proof_entries.append({
            "source": row["source"],
            "dataset": dataset,
            "segment_id": row["segment_id"],
            "segment_start": row["segment_start"],
            "segment_end": row["segment_end"],
            "expected_scope": expected_scope,
            "expected_items": row["expected_items"],
            "receipt_run_id": row["receipt_run_id"],
            "observed_items": row["observed_items"],
            "raw_page_count": row["raw_page_count"],
            "raw_row_count": row["raw_row_count"],
            "structured_row_count": row["structured_row_count"],
            "pagination_exhausted": row["pagination_exhausted"],
            "digests": digests,
            "checked_at": row["checked_at"],
        })

    missing_inventory = sorted(
        dataset for dataset, segments in segments_by_dataset.items()
        if not segments
    )
    if missing_inventory or invalid_segments:
        raise SnapshotRejected(
            "Coverage V2 segment proof rejected: "
            f"missing_inventory={missing_inventory}, "
            f"invalid={invalid_segments[:20]}"
        )
    dataset_summary = [
        {
            "dataset": dataset,
            "required_segments": len(segments),
            "complete_segments": len(segments),
            "first_segment": str(segments[0]["segment_id"]),
            "last_segment": str(segments[-1]["segment_id"]),
        }
        for dataset, segments in segments_by_dataset.items()
    ]
    return {
        "format": "coverage-v2-proof/v1",
        "status": "COMPLETE",
        "policy_version": COVERAGE_POLICY_VERSION,
        "dataset_count": len(governed),
        "segment_count": len(proof_entries),
        "receipt_count": len(proof_entries),
        "proof_digest": _canonical_digest(proof_entries),
        "datasets": dataset_summary,
    }


def _verify_coverage_v2_manifest(
    conn: sqlite3.Connection, manifest: dict[str, Any]
) -> None:
    """Recompute the embedded Coverage V2 proof before accepting a READY DB."""
    from paper_runtime.snapshot import SnapshotRejected, all_coverage_contracts

    if manifest.get("coverage_policy_version") != COVERAGE_POLICY_VERSION:
        raise RuntimeError("READY snapshot does not use Coverage V2")
    required_raw = manifest.get("required_datasets")
    if not isinstance(required_raw, list) or not all(
        isinstance(item, str) for item in required_raw
    ):
        raise RuntimeError("READY snapshot required datasets are malformed")
    required = tuple(sorted(set(required_raw)))
    policies = {policy.dataset_id: policy for policy in all_coverage_contracts()}
    governed = {
        dataset for dataset, policy in policies.items()
        if policy.governance_tier == "governed"
    }
    if not governed <= set(required) or not set(required) <= set(policies):
        raise RuntimeError("READY snapshot omits governed Coverage V2 datasets")
    rows = [
        dict(row) for row in conn.execute(
            "SELECT * FROM dataset_coverage ORDER BY dataset"
        )
        if str(row["dataset"]) in required
    ]
    try:
        computed = _coverage_v2_proof(conn, required, rows)
    except (SnapshotRejected, sqlite3.Error) as exc:
        raise RuntimeError(f"READY Coverage V2 proof is invalid: {exc}") from exc
    if manifest.get("coverage_v2_proof") != computed:
        raise RuntimeError("READY Coverage V2 manifest proof mismatch")
