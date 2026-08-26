"""Per-dataset governed Coverage proof for paper data snapshots.

READY stays fail-closed. Empty DB and PARTIAL coverage cannot publish READY.
This module verifies receipts and bounded proof digests; it does not decide READY.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from data_contracts.coverage import (
    coverage_policy_binding,
    coverage_policy_set_binding,
)


LOCAL_COVERAGE_PROOF_FORMAT = "local-coverage-proof/v1"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class CoverageProofVerificationError(RuntimeError):
    """Persisted Coverage proof is absent, stale, or not reproducible."""


@dataclass(frozen=True, slots=True)
class VerifiedCoverageProof:
    """Value returned only after the caller invokes full live verification.

    This object is not itself an authority and is never accepted as policy
    input.  Production evidence retains the DB coordinates and re-runs
    :func:`require_persisted_coverage_proof` when converted to a policy item,
    avoiding any same-process seal or registry as a trust boundary.
    """

    proof_id: str
    _proof_json: str
    required_datasets: tuple[str, ...]
    source_generation: int
    applied_generation: int

    @property
    def proof(self) -> dict[str, Any]:
        return json.loads(self._proof_json)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_required(required: Iterable[str]) -> tuple[str, ...]:
    observed = tuple(required)
    if not observed or not all(isinstance(item, str) and item for item in observed):
        raise CoverageProofVerificationError(
            "Coverage proof membership must contain non-empty dataset ids"
        )
    expected = tuple(sorted(set(observed)))
    if observed != expected:
        raise CoverageProofVerificationError(
            "Coverage proof membership must be exact, sorted, and duplicate-free"
        )
    return observed


def _coverage_rows_for(
    conn: sqlite3.Connection,
    required: tuple[str, ...],
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in required)
    try:
        cursor = conn.execute(
            "SELECT * FROM dataset_coverage "
            f"WHERE dataset IN ({placeholders}) ORDER BY dataset",
            required,
        )
        columns = tuple(item[0] for item in cursor.description or ())
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    except sqlite3.Error as exc:
        raise CoverageProofVerificationError(
            "Coverage aggregate ledger is unavailable"
        ) from exc


def _current_generations(conn: sqlite3.Connection) -> tuple[int, int]:
    try:
        source_row = conn.execute(
            "SELECT COALESCE(MAX(change_seq), 0) FROM ingestion_change_log"
        ).fetchone()
        applied_row = conn.execute(
            "SELECT last_applied_change_seq FROM sync_change_state "
            "WHERE feed='jquants_records'"
        ).fetchone()
    except sqlite3.Error as exc:
        raise CoverageProofVerificationError(
            "Coverage proof source/applied generation ledgers are unavailable"
        ) from exc
    source_generation = int(source_row[0]) if source_row is not None else 0
    applied_generation = int(applied_row[0]) if applied_row is not None else 0
    if (
        source_generation <= 0
        or applied_generation <= 0
        or source_generation != applied_generation
    ):
        raise CoverageProofVerificationError(
            "Coverage proof source/applied generations are not current"
        )
    return source_generation, applied_generation


def _proof_record_body(
    *,
    required: tuple[str, ...],
    proof: dict[str, Any],
    source_generation: int,
    applied_generation: int,
) -> dict[str, Any]:
    return {
        "format": LOCAL_COVERAGE_PROOF_FORMAT,
        "required_datasets": list(required),
        "coverage_proof": proof,
        "coverage_policy_version": proof.get("policy_version"),
        "coverage_policy_digest": proof.get("policy_digest"),
        "source_generation": source_generation,
        "applied_generation": applied_generation,
    }


def persist_coverage_proof(
    conn: sqlite3.Connection,
    required_datasets: Iterable[str],
) -> str:
    """Recompute and durably persist one immutable, content-addressed proof."""
    from paper_runtime.snapshot import SnapshotRejected

    required = _canonical_required(required_datasets)
    coverage_rows = _coverage_rows_for(conn, required)
    try:
        proof = _coverage_proof(conn, required, coverage_rows)
    except (SnapshotRejected, sqlite3.Error, ValueError, TypeError) as exc:
        raise CoverageProofVerificationError(
            f"Coverage proof cannot be persisted: {exc}"
        ) from exc
    source_generation, applied_generation = _current_generations(conn)
    body = _proof_record_body(
        required=required,
        proof=proof,
        source_generation=source_generation,
        applied_generation=applied_generation,
    )
    proof_id = _canonical_digest(body)
    persisted_at = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO local_coverage_proofs (
                proof_id, format, required_datasets_json, coverage_proof_json,
                coverage_policy_version, coverage_policy_digest,
                source_generation, applied_generation, persisted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proof_id,
                LOCAL_COVERAGE_PROOF_FORMAT,
                _canonical_json(list(required)),
                _canonical_json(proof),
                str(proof["policy_version"]),
                str(proof["policy_digest"]),
                source_generation,
                applied_generation,
                persisted_at,
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise CoverageProofVerificationError(
            "Coverage proof ledger persistence failed"
        ) from exc

    # INSERT OR IGNORE is safe only when an existing content-addressed row is
    # byte-for-byte the record just recomputed.  The publication policy then
    # performs the independent full ledger recomputation before PASS.
    row = conn.execute(
        """
        SELECT format, required_datasets_json, coverage_proof_json,
               coverage_policy_version, coverage_policy_digest,
               source_generation, applied_generation
        FROM local_coverage_proofs WHERE proof_id=?
        """,
        (proof_id,),
    ).fetchone()
    expected = (
        LOCAL_COVERAGE_PROOF_FORMAT,
        _canonical_json(list(required)),
        _canonical_json(proof),
        str(proof["policy_version"]),
        str(proof["policy_digest"]),
        source_generation,
        applied_generation,
    )
    if row is None or tuple(row) != expected:
        raise CoverageProofVerificationError(
            "Coverage proof id collides with a different persisted record"
        )
    return proof_id


def require_persisted_coverage_proof(
    conn: sqlite3.Connection,
    required_datasets: Iterable[str],
    proof_id: object,
) -> VerifiedCoverageProof:
    """Recompute every authority-bound field and return verified values."""
    from paper_runtime.snapshot import SnapshotRejected

    required = _canonical_required(required_datasets)
    if not isinstance(proof_id, str) or _SHA256_RE.fullmatch(proof_id) is None:
        raise CoverageProofVerificationError("Coverage proof id is invalid")
    try:
        row = conn.execute(
            """
            SELECT format, required_datasets_json, coverage_proof_json,
                   coverage_policy_version, coverage_policy_digest,
                   source_generation, applied_generation
            FROM local_coverage_proofs WHERE proof_id=?
            """,
            (proof_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise CoverageProofVerificationError(
            "Coverage proof ledger is unavailable"
        ) from exc
    if row is None:
        raise CoverageProofVerificationError("Coverage proof id is unknown")
    try:
        stored_required = json.loads(str(row[1]))
        stored_proof = json.loads(str(row[2]))
        source_generation = int(row[5])
        applied_generation = int(row[6])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CoverageProofVerificationError(
            "Persisted Coverage proof record is malformed"
        ) from exc
    if (
        row[0] != LOCAL_COVERAGE_PROOF_FORMAT
        or stored_required != list(required)
        or not isinstance(stored_proof, dict)
        or row[3] != stored_proof.get("policy_version")
        or row[4] != stored_proof.get("policy_digest")
    ):
        raise CoverageProofVerificationError(
            "Persisted Coverage proof record binding is invalid"
        )

    coverage_rows = _coverage_rows_for(conn, required)
    try:
        recomputed = _coverage_proof(conn, required, coverage_rows)
    except (SnapshotRejected, sqlite3.Error, ValueError, TypeError) as exc:
        raise CoverageProofVerificationError(
            f"Persisted Coverage proof cannot be reproduced: {exc}"
        ) from exc
    if recomputed != stored_proof:
        raise CoverageProofVerificationError(
            "Persisted Coverage proof does not match the current ledgers"
        )
    current_source, current_applied = _current_generations(conn)
    if (
        source_generation != current_source
        or applied_generation != current_applied
    ):
        raise CoverageProofVerificationError(
            "Persisted Coverage proof generation is stale"
        )
    body = _proof_record_body(
        required=required,
        proof=recomputed,
        source_generation=current_source,
        applied_generation=current_applied,
    )
    if _canonical_digest(body) != proof_id:
        raise CoverageProofVerificationError(
            "Persisted Coverage proof content address is invalid"
        )
    return VerifiedCoverageProof(
        proof_id=proof_id,
        _proof_json=_canonical_json(recomputed),
        required_datasets=required,
        source_generation=current_source,
        applied_generation=current_applied,
    )


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


def _coverage_proof(
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
    from storage.verified_receipt import (
        ReceiptVerificationError,
        require_verified_collection_closure,
    )

    policies = {policy.dataset_id: policy for policy in all_coverage_contracts()}
    governed = tuple(
        dataset for dataset in required
        if policies[dataset].governance_tier == "governed"
    )
    by_dataset = {str(row["dataset"]): row for row in coverage_rows}
    invalid_ledger = sorted(
        dataset
        for dataset in governed
        if dataset not in by_dataset
        or by_dataset[dataset].get("policy_version")
        != coverage_policy_binding(dataset)["policy_version"]
        or by_dataset[dataset].get("status") != "COMPLETE"
    )
    if invalid_ledger:
        raise SnapshotRejected(
            f"governed Coverage aggregate proof incomplete={invalid_ledger}"
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
        WHERE s.dataset IN ("""
        + placeholders
        + ")"
        + " ORDER BY s.dataset, s.segment_start, s.segment_id",
        governed,
    ).fetchall()
    segments_by_dataset: dict[str, list[sqlite3.Row]] = {
        dataset: [] for dataset in governed
    }
    proof_entries: list[dict[str, Any]] = []
    invalid_segments: list[tuple[str, str, str]] = []
    for row in rows:
        dataset = str(row["dataset"])
        expected_policy = coverage_policy_binding(dataset)
        # Older policy rows remain immutable audit history. Only the currently
        # governed per-dataset version is eligible for this proof.
        if row["policy_version"] != expected_policy["policy_version"]:
            continue
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
                    expected_policy_version=expected_policy["policy_version"],
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
            "governed Coverage segment proof rejected: "
            f"missing_inventory={missing_inventory}, "
            f"invalid={invalid_segments[:20]}"
        )
    dataset_summary = [
        {
            "dataset": dataset,
            **dict(coverage_policy_binding(dataset)),
            "required_segments": len(segments),
            "complete_segments": len(segments),
            "first_segment": str(segments[0]["segment_id"]),
            "last_segment": str(segments[-1]["segment_id"]),
        }
        for dataset, segments in segments_by_dataset.items()
    ]
    policy_set = coverage_policy_set_binding(list(governed))
    return {
        "format": "coverage-proof/v1",
        "status": "COMPLETE",
        "policy_version": policy_set["policy_version"],
        "policy_digest": policy_set["policy_digest"],
        "dataset_count": len(governed),
        "segment_count": len(proof_entries),
        "receipt_count": len(proof_entries),
        "proof_digest": _canonical_digest(proof_entries),
        "datasets": dataset_summary,
    }


def _verify_coverage_manifest(
    conn: sqlite3.Connection, manifest: dict[str, Any]
) -> None:
    """Recompute the persisted proof before accepting an embedded READY manifest."""
    from paper_runtime.snapshot import all_coverage_contracts

    required_raw = manifest.get("required_datasets")
    if not isinstance(required_raw, list) or not all(
        isinstance(item, str) for item in required_raw
    ):
        raise RuntimeError("READY snapshot required datasets are malformed")
    required = tuple(required_raw)
    if required != tuple(sorted(set(required))):
        raise RuntimeError(
            "READY snapshot required datasets are not exact sorted membership"
        )
    policies = {policy.dataset_id: policy for policy in all_coverage_contracts()}
    governed = {
        dataset for dataset, policy in policies.items()
        if policy.governance_tier == "governed"
    }
    required_set = set(required)
    if not required_set <= set(policies):
        raise RuntimeError("READY snapshot includes unknown Coverage datasets")
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
                "READY snapshot omits governed Coverage datasets without "
                "an exact profile-bound ReadyManifest"
            )
    try:
        capability = require_persisted_coverage_proof(
            conn,
            required,
            manifest.get("coverage_proof_id"),
        )
    except CoverageProofVerificationError as exc:
        raise RuntimeError(f"READY Coverage proof is invalid: {exc}") from exc
    computed = capability.proof
    if manifest.get("coverage_policy_version") != computed["policy_version"]:
        raise RuntimeError("READY Coverage policy-set version mismatch")
    if manifest.get("coverage_policy_digest") != computed["policy_digest"]:
        raise RuntimeError("READY Coverage policy-set digest mismatch")
    if manifest.get("coverage_proof") != computed:
        raise RuntimeError("READY Coverage manifest proof mismatch")
