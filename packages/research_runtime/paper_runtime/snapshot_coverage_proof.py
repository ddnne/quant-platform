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
from pathlib import Path
from typing import Any, Iterable

from data_contracts.coverage import (
    coverage_policy_binding,
    coverage_policy_set_binding,
)
from storage.coverage_ledger import (
    CoverageInventoryAuthorityUnavailable,
    CoveragePublicationCutoffError,
    validation_coverage_cutoff_for_build,
    verify_exact_coverage_complete,
)


LOCAL_COVERAGE_PROOF_FORMAT = "local-coverage-proof/v2"
COVERAGE_PROOF_FORMAT = "coverage-proof/v2"
COVERAGE_INVENTORY_FORMAT = "coverage-required-inventory/v1"
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
    build_id: str
    publication_cutoff: str
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


def _publication_cutoff_for_build_impl(
    conn: sqlite3.Connection,
    build_id: object,
    *,
    proof_id: object | None = None,
    require_quality_pass: bool,
) -> str:
    """Return the cutoff only for the active build or its exact READY manifest."""
    if not isinstance(build_id, str) or not build_id:
        raise CoverageProofVerificationError(
            "Coverage proof requires a publisher-owned build id"
        )
    try:
        rows = conn.execute(
            "SELECT state,staging_path,artifact_path,snapshot_id,created_at,"
            "manifest_json FROM snapshot_publications WHERE build_id=?",
            (build_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise CoverageProofVerificationError(
            "Coverage proof publication ledger is unavailable"
        ) from exc
    if len(rows) != 1:
        raise CoverageProofVerificationError(
            "Coverage proof build has no exact publication row"
        )
    state = str(rows[0][0])
    staging_path = str(rows[0][1])
    artifact_path = None if rows[0][2] is None else str(rows[0][2])
    snapshot_id = None if rows[0][3] is None else str(rows[0][3])
    created_at = str(rows[0][4])
    manifest_raw = rows[0][5]
    try:
        policy_rows = conn.execute(
            "SELECT publication_state,snapshot_ready,active_build_id,"
            "active_snapshot_id FROM local_snapshot_policy WHERE singleton=1"
        ).fetchall()
    except sqlite3.Error as exc:
        raise CoverageProofVerificationError(
            "Coverage proof active publication policy is unavailable"
        ) from exc
    if len(policy_rows) != 1:
        raise CoverageProofVerificationError(
            "Coverage proof has no unique active publication policy"
        )
    policy_state = str(policy_rows[0][0])
    snapshot_ready = int(policy_rows[0][1])
    active_build_id = policy_rows[0][2]
    active_snapshot_id = policy_rows[0][3]

    main_path = next(
        (
            str(row[2])
            for row in conn.execute("PRAGMA database_list").fetchall()
            if str(row[1]) == "main"
        ),
        "",
    )
    if state == "VALIDATING":
        if (
            policy_state != "VALIDATING"
            or active_build_id != build_id
            or not main_path
            or Path(main_path).resolve() != Path(staging_path).resolve()
        ):
            raise CoverageProofVerificationError(
                "Coverage proof build is not the unique active VALIDATING build"
            )
        if require_quality_pass:
            quality_rows = conn.execute(
                "SELECT status FROM snapshot_quality_results WHERE build_id=?",
                (build_id,),
            ).fetchall()
            if len(quality_rows) != 1 or quality_rows[0][0] != "PASS":
                raise CoverageProofVerificationError(
                    "Coverage proof VALIDATING build has no authoritative PASS"
                )
    elif state == "READY":
        if (
            policy_state != "READY"
            or snapshot_ready != 1
            or snapshot_id is None
            or active_snapshot_id != snapshot_id
            or not isinstance(proof_id, str)
            or _SHA256_RE.fullmatch(proof_id) is None
        ):
            raise CoverageProofVerificationError(
                "Coverage proof is not linked to the active READY publication"
            )
        try:
            manifest = json.loads(str(manifest_raw))
        except (TypeError, json.JSONDecodeError) as exc:
            raise CoverageProofVerificationError(
                "Coverage proof READY manifest is malformed"
            ) from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("state") != "READY"
            or manifest.get("build_id") != build_id
            or manifest.get("snapshot_id") != snapshot_id
            or manifest.get("created_at") != created_at
            or manifest.get("coverage_proof_id") != proof_id
        ):
            raise CoverageProofVerificationError(
                "Coverage proof READY manifest linkage is invalid"
            )
        if (
            not main_path
            or not artifact_path
            or Path(main_path).resolve() != Path(artifact_path).resolve()
        ):
            raise CoverageProofVerificationError(
                "Coverage proof READY database is not the immutable artifact"
            )
        embedded_rows = conn.execute(
            "SELECT manifest_json FROM local_snapshot_manifests "
            "WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchall()
        if len(embedded_rows) != 1 or str(embedded_rows[0][0]) != str(manifest_raw):
            raise CoverageProofVerificationError(
                "Coverage proof READY embedded manifest linkage is invalid"
            )
    else:
        raise CoverageProofVerificationError(
            f"Coverage proof build state {state!r} is not authoritative"
        )
    try:
        instant = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CoverageProofVerificationError(
            "Coverage proof publication timestamp is malformed"
        ) from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise CoverageProofVerificationError(
            "Coverage proof publication timestamp must be timezone-aware"
        )
    return instant.astimezone(timezone.utc).date().isoformat()


def _publication_cutoff_for_build(
    conn: sqlite3.Connection,
    build_id: object,
    *,
    proof_id: object | None = None,
) -> str:
    """Proof cutoff for a scored active build or exact READY artifact."""
    return _publication_cutoff_for_build_impl(
        conn,
        build_id,
        proof_id=proof_id,
        require_quality_pass=True,
    )


def _validation_cutoff_for_build(
    conn: sqlite3.Connection,
    build_id: object,
) -> str:
    """Internal pre-quality cutoff for the active publisher VALIDATING build."""
    main_path = next(
        (
            str(row[2])
            for row in conn.execute("PRAGMA database_list").fetchall()
            if str(row[1]) == "main"
        ),
        "",
    )
    try:
        return validation_coverage_cutoff_for_build(
            conn,
            main_path,
            build_id,
        )
    except CoveragePublicationCutoffError as exc:
        raise CoverageProofVerificationError(str(exc)) from exc


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
    build_id: str,
    publication_cutoff: str,
    source_generation: int,
    applied_generation: int,
) -> dict[str, Any]:
    return {
        "format": LOCAL_COVERAGE_PROOF_FORMAT,
        "build_id": build_id,
        "publication_cutoff": publication_cutoff,
        "required_datasets": list(required),
        "coverage_proof": proof,
        "coverage_policy_version": proof.get("policy_version"),
        "coverage_policy_digest": proof.get("policy_digest"),
        "inventory_set_digest": proof.get("inventory_set_digest"),
        "source_generation": source_generation,
        "applied_generation": applied_generation,
    }


def _persist_coverage_proof_in_transaction(
    conn: sqlite3.Connection,
    required_datasets: Iterable[str],
    *,
    build_id: object,
) -> str:
    """Recompute and durably persist one immutable, content-addressed proof."""
    from paper_runtime.snapshot import SnapshotRejected

    required = _canonical_required(required_datasets)
    if not isinstance(build_id, str) or not build_id:
        raise CoverageProofVerificationError(
            "Coverage proof requires a publisher-owned build id"
        )
    publication_cutoff = _publication_cutoff_for_build(conn, build_id)
    coverage_rows = _coverage_rows_for(conn, required)
    try:
        proof = _coverage_proof(
            conn,
            required,
            coverage_rows,
            publication_cutoff=publication_cutoff,
        )
    except (
        CoverageProofVerificationError,
        SnapshotRejected,
        sqlite3.Error,
        ValueError,
        TypeError,
    ) as exc:
        raise CoverageProofVerificationError(
            f"Coverage proof cannot be persisted: {exc}"
        ) from exc
    source_generation, applied_generation = _current_generations(conn)
    body = _proof_record_body(
        required=required,
        proof=proof,
        build_id=build_id,
        publication_cutoff=publication_cutoff,
        source_generation=source_generation,
        applied_generation=applied_generation,
    )
    proof_id = _canonical_digest(body)
    persisted_at = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO local_coverage_proofs_v2 (
                proof_id, format, build_id, publication_cutoff,
                required_datasets_json, coverage_proof_json,
                coverage_policy_version, coverage_policy_digest,
                inventory_set_digest, source_generation, applied_generation,
                persisted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proof_id,
                LOCAL_COVERAGE_PROOF_FORMAT,
                build_id,
                publication_cutoff,
                _canonical_json(list(required)),
                _canonical_json(proof),
                str(proof["policy_version"]),
                str(proof["policy_digest"]),
                str(proof["inventory_set_digest"]),
                source_generation,
                applied_generation,
                persisted_at,
            ),
        )
    except sqlite3.Error as exc:
        raise CoverageProofVerificationError(
            "Coverage proof ledger persistence failed"
        ) from exc

    # INSERT OR IGNORE is safe only when an existing content-addressed row is
    # byte-for-byte the record just recomputed.  The publication policy then
    # performs the independent full ledger recomputation before PASS.
    row = conn.execute(
        """
        SELECT format, build_id, publication_cutoff, required_datasets_json,
               coverage_proof_json,
               coverage_policy_version, coverage_policy_digest,
               inventory_set_digest, source_generation, applied_generation
        FROM local_coverage_proofs_v2 WHERE proof_id=?
        """,
        (proof_id,),
    ).fetchone()
    expected = (
        LOCAL_COVERAGE_PROOF_FORMAT,
        build_id,
        publication_cutoff,
        _canonical_json(list(required)),
        _canonical_json(proof),
        str(proof["policy_version"]),
        str(proof["policy_digest"]),
        str(proof["inventory_set_digest"]),
        source_generation,
        applied_generation,
    )
    if row is None or tuple(row) != expected:
        raise CoverageProofVerificationError(
            "Coverage proof id collides with a different persisted record"
        )
    return proof_id


def persist_coverage_proof(
    conn: sqlite3.Connection,
    required_datasets: Iterable[str],
    *,
    build_id: object,
) -> str:
    """Persist proof atomically with build/cutoff/inventory verification."""
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        proof_id = _persist_coverage_proof_in_transaction(
            conn,
            required_datasets,
            build_id=build_id,
        )
        if owns_transaction:
            conn.commit()
        return proof_id
    except BaseException:
        if owns_transaction:
            conn.rollback()
        raise


def _require_persisted_coverage_proof_in_snapshot(
    conn: sqlite3.Connection,
    required_datasets: Iterable[str],
    proof_id: object,
    *,
    build_id: object,
) -> VerifiedCoverageProof:
    """Recompute every authority-bound field and return verified values."""
    from paper_runtime.snapshot import SnapshotRejected

    required = _canonical_required(required_datasets)
    if not isinstance(proof_id, str) or _SHA256_RE.fullmatch(proof_id) is None:
        raise CoverageProofVerificationError("Coverage proof id is invalid")
    if not isinstance(build_id, str) or not build_id:
        raise CoverageProofVerificationError(
            "Coverage proof requires its publisher-owned build id"
        )
    try:
        row = conn.execute(
            """
            SELECT format, build_id, publication_cutoff,
                   required_datasets_json, coverage_proof_json,
                   coverage_policy_version, coverage_policy_digest,
                   inventory_set_digest, source_generation, applied_generation
            FROM local_coverage_proofs_v2 WHERE proof_id=?
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
        stored_build_id = str(row[1])
        stored_cutoff = str(row[2])
        stored_required = json.loads(str(row[3]))
        stored_proof = json.loads(str(row[4]))
        source_generation = int(row[8])
        applied_generation = int(row[9])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CoverageProofVerificationError(
            "Persisted Coverage proof record is malformed"
        ) from exc
    if (
        row[0] != LOCAL_COVERAGE_PROOF_FORMAT
        or stored_build_id != build_id
        or stored_cutoff != _publication_cutoff_for_build(
            conn,
            build_id,
            proof_id=proof_id,
        )
        or stored_required != list(required)
        or not isinstance(stored_proof, dict)
        or row[5] != stored_proof.get("policy_version")
        or row[6] != stored_proof.get("policy_digest")
        or row[7] != stored_proof.get("inventory_set_digest")
        or stored_proof.get("inventory_cutoff") != stored_cutoff
    ):
        raise CoverageProofVerificationError(
            "Persisted Coverage proof record binding is invalid"
        )

    coverage_rows = _coverage_rows_for(conn, required)
    try:
        recomputed = _coverage_proof(
            conn,
            required,
            coverage_rows,
            publication_cutoff=stored_cutoff,
        )
    except (
        CoverageProofVerificationError,
        SnapshotRejected,
        sqlite3.Error,
        ValueError,
        TypeError,
    ) as exc:
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
        build_id=stored_build_id,
        publication_cutoff=stored_cutoff,
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
        build_id=stored_build_id,
        publication_cutoff=stored_cutoff,
        source_generation=current_source,
        applied_generation=current_applied,
    )


def require_persisted_coverage_proof(
    conn: sqlite3.Connection,
    required_datasets: Iterable[str],
    proof_id: object,
    *,
    build_id: object,
) -> VerifiedCoverageProof:
    """Reopen proof under one pinned SQLite read snapshot."""
    owns_snapshot = not conn.in_transaction
    if owns_snapshot:
        conn.execute("BEGIN")
    try:
        return _require_persisted_coverage_proof_in_snapshot(
            conn,
            required_datasets,
            proof_id,
            build_id=build_id,
        )
    finally:
        if owns_snapshot:
            conn.rollback()


def _coverage_proof(
    conn: sqlite3.Connection,
    required: tuple[str, ...],
    coverage_rows: list[dict[str, Any]],
    *,
    publication_cutoff: str,
) -> dict[str, Any]:
    """Verify exact canonical inventory and every selected signed receipt."""
    from paper_runtime.snapshot import (
        SnapshotRejected,
        all_coverage_contracts,
    )
    policies = {policy.dataset_id: policy for policy in all_coverage_contracts()}
    governed = tuple(
        dataset for dataset in required
        if policies[dataset].governance_tier == "governed"
    )
    try:
        complete_verification = verify_exact_coverage_complete(
            conn,
            governed,
            target_end=publication_cutoff,
        )
    except CoverageInventoryAuthorityUnavailable as exc:
        raise SnapshotRejected(str(exc)) from exc
    inventory = complete_verification.inventory
    if not inventory.exact:
        raise SnapshotRejected(
            "governed Coverage exact inventory rejected: "
            + _canonical_json(inventory.detail())
        )
    if not complete_verification.complete_eligible:
        raise SnapshotRejected(
            "governed Coverage segment proof rejected: invalid="
            f"{list(complete_verification.invalid_segments[:20])}"
        )
    expected_by_dataset = {
        dataset: inventory.segments_for(dataset) for dataset in governed
    }
    expected_identity_dicts = [
        identity.to_dict() for identity in inventory.expected_identities
    ]
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

    proof_entries = [
        closure.to_proof_dict()
        for closure in complete_verification.closures
    ]
    dataset_summary = [
        {
            "dataset": dataset,
            **dict(coverage_policy_binding(dataset)),
            "required_segments": len(segments),
            "complete_segments": len(segments),
            "inventory_digest": _canonical_digest([
                identity.to_dict()
                for identity in inventory.expected_identities
                if identity.dataset == dataset
            ]),
            "first_segment": segments[0].segment_id,
            "last_segment": segments[-1].segment_id,
        }
        for dataset, segments in expected_by_dataset.items()
    ]
    policy_set = coverage_policy_set_binding(list(governed))
    inventory_set_digest = _canonical_digest(expected_identity_dicts)
    return {
        "format": COVERAGE_PROOF_FORMAT,
        "status": "COMPLETE",
        "policy_version": policy_set["policy_version"],
        "policy_digest": policy_set["policy_digest"],
        "inventory_format": COVERAGE_INVENTORY_FORMAT,
        "inventory_cutoff": publication_cutoff,
        "inventory_set_digest": inventory_set_digest,
        "dataset_count": len(governed),
        "segment_count": len(proof_entries),
        "receipt_count": len(proof_entries),
        "proof_digest": _canonical_digest({
            "inventory_set_digest": inventory_set_digest,
            "receipts": proof_entries,
        }),
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
            build_id=manifest.get("build_id"),
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
