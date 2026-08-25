"""Coverage V2 proof evidence for paper data snapshots.

READY stays fail-closed. Empty DB and PARTIAL coverage cannot publish READY.
This module verifies receipts and bounded proof digests; it does not decide READY.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from data_contracts.coverage import POLICY_VERSION as COVERAGE_POLICY_VERSION


def _required_segment_from_row(row: sqlite3.Row):
    """Rebuild the trusted inventory value from the coverage-segment row."""
    from storage.coverage_ledger import RequiredCoverageSegment

    scope = json.loads(str(row["expected_scope"]))
    if not isinstance(scope, dict):
        raise ValueError("coverage segment expected_scope must be an object")
    expected_items = row["expected_items"]
    return RequiredCoverageSegment(
        source=str(row["source"]),
        dataset=str(row["dataset"]),
        segment_id=str(row["segment_id"]),
        segment_start=str(row["segment_start"]),
        segment_end=str(row["segment_end"]),
        expected_scope=scope,
        expected_items=(
            None if expected_items is None else int(expected_items)
        ),
    )


def _untrusted_receipt_from_row(row: sqlite3.Row):
    """Rebuild the persisted receipt DTO without granting it any trust."""
    from storage.coverage_ledger import CollectionReceipt

    scope = json.loads(str(row["receipt_scope"]))
    digests = json.loads(str(row["digests_json"]))
    if not isinstance(scope, dict):
        raise ValueError("collection receipt expected_scope must be an object")
    if not isinstance(digests, dict):
        raise ValueError("collection receipt digests must be an object")
    expected_items = row["receipt_expected_items"]
    return CollectionReceipt(
        source=str(row["receipt_source"]),
        dataset=str(row["receipt_dataset"]),
        segment_id=str(row["receipt_segment_id"]),
        segment_start=str(row["receipt_start"]),
        segment_end=str(row["receipt_end"]),
        expected_scope=scope,
        expected_items=(
            None if expected_items is None else int(expected_items)
        ),
        observed_items=int(row["observed_items"]),
        raw_page_count=int(row["raw_page_count"]),
        raw_row_count=int(row["raw_row_count"]),
        structured_row_count=int(row["structured_row_count"]),
        pagination_exhausted=bool(row["pagination_exhausted"]),
        digests=digests,
        run_id=int(row["receipt_run_id"]),
        status=str(row["receipt_status"]),
        error=row["error"],
        checked_at=str(row["checked_at"]),
    )


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
    from storage.receipt_crypto import load_verify_keys
    from storage.verified_receipt import (
        ReceiptVerificationError,
        require_verified_collection_closure,
    )

    if COVERAGE_POLICY_VERSION != "collection-coverage/v2":
        raise SnapshotRejected(
            "READY publication requires collection-coverage/v2"
        )
    policies = {policy.dataset_id: policy for policy in all_coverage_contracts()}
    verify_keys = load_verify_keys()
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
            s.receipt_run_id AS selected_receipt_run_id,
            r.source AS receipt_source,
            r.dataset AS receipt_dataset,
            r.segment_id AS receipt_segment_id,
            r.run_id AS receipt_run_id,
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
        policy = policies[dataset]
        if row["segment_status"] != "COMPLETE":
            reason = "segment not COMPLETE"
        elif (
            row["selected_receipt_run_id"] is None
            or row["receipt_run_id"] is None
        ):
            reason = "successful receipt missing"
        else:
            try:
                required_segment = _required_segment_from_row(row)
                untrusted_receipt = _untrusted_receipt_from_row(row)
                closure = require_verified_collection_closure(
                    untrusted_receipt,
                    required=required_segment,
                    expected_policy_version=policy.policy_version,
                    verify_keys=verify_keys,
                )
            except (
                ReceiptVerificationError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                reason = f"receipt closure invalid: {exc}"

        # From this point forward, no persisted receipt field is consulted.
        # Every COMPLETE input and every proof field comes from the opaque,
        # signature-bound v2 closure returned above.
        if reason is None and (
            closure.status != "SUCCESS" or closure.error is not None
        ):
            reason = "successful receipt missing"
        elif reason is None and (
            not closure.pagination_exhausted
            or not closure.discovery_exhausted
        ):
            reason = "pagination not exhausted"
        elif reason is None and (
            policy.expected_frequency != "event_driven"
            and closure.expected_items is None
        ):
            reason = "non-event expected items missing"
        elif reason is None and (
            closure.expected_items is not None
            and closure.observed_items != closure.expected_items
        ):
            reason = "expected scope incomplete"
        elif reason is None and (
            closure.raw_page_count < 1 or not closure.raw_digest
        ):
            reason = "raw retention proof missing"
        elif reason is None and (
            policy.structured_reconciliation_required
            and closure.raw_row_count != closure.structured_row_count
        ):
            reason = "raw/structured mismatch"
        elif reason is None and (
            policy.expected_frequency != "event_driven"
            and closure.observed_items == 0
        ):
            reason = "non-event receipt is empty"
        if reason is not None:
            invalid_segments.append((dataset, str(row["segment_id"]), reason))
            continue
        proof_entries.append(closure.to_proof_dict())

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
    required_set = set(required)
    if not required_set <= set(policies):
        raise RuntimeError("READY snapshot includes unknown Coverage V2 datasets")
    if not governed <= required_set:
        # A profile-bound snapshot may intentionally be narrower than the
        # legacy all-governed set, but only when the publisher embedded a
        # structurally bound ReadyManifest. Product-layer profile/digest
        # authority is rechecked before minting VerifiedResearchReadiness.
        profile_manifest = manifest.get("ready_manifest")
        if (
            not isinstance(profile_manifest, dict)
            or profile_manifest.get("format") != "ready-manifest/v1"
            or profile_manifest.get("snapshot_id") != manifest.get("snapshot_id")
            or profile_manifest.get("published_at") != manifest.get("committed_at")
            or set(profile_manifest.get("dataset_ids") or ()) != required_set
            or len(profile_manifest.get("dataset_ids") or ()) != len(required)
        ):
            raise RuntimeError(
                "READY snapshot omits governed Coverage V2 datasets without "
                "an exact profile-bound ReadyManifest"
            )
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
