"""Cheap, control-plane-based identifiers for local SQLite data snapshots."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

from data_contracts.coverage import (
    all_coverage_contracts,
    coverage_policy_set_binding,
)
from data_contracts.jsda import JSDA_CONTRACT_VERSION
from data_contracts.loader import SCHEMA_VERSION as DATASET_CONTRACT_VERSION
from paper_runtime.snapshot_coverage_proof import (
    _coverage_proof,
)
from paper_runtime.snapshot_identity import (
    DATA_SNAPSHOT_FORMAT,
    RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
    _canonical_digest,
    _data_snapshot_id_from_open_connection,
    _immutable_data_snapshot_id,
    _research_manifest_digest,
    _research_manifest_id,
    data_snapshot_id,
)
from paper_runtime.snapshot_persist import (
    _atomic_bytes,
    _atomic_json,
    _copy_sqlite,
    _persist_building_publication,
    _persist_synced_publication,
    begin_snapshot_sync,
)
from paper_runtime.snapshot_publish_policy import (
    READY_MANIFEST_SCHEMA,
    _transition_policy,
    evaluate_ready_publication,
)
from paper_runtime.snapshot_read import (
    _describe_fixture_snapshot,
    describe_snapshot,
    latest_ready_snapshot,
    list_ready_snapshots,
)


LOCAL_SNAPSHOT_MANIFEST_FORMAT = "local-snapshot-manifest/v1"
RESEARCH_SNAPSHOT_PUBLICATION_FORMAT = "research-snapshot-publication/v1"
QUALITY_POLICY_VERSION = "b0+phase35-daily+coverage-set/v1"
SNAPSHOT_STATES = frozenset(
    {"BUILDING", "SYNCED", "VALIDATING", "READY", "REJECTED"}
)
_SNAPSHOT_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")

class SnapshotRejected(RuntimeError):
    """Raised when a staging DB cannot pass the publication gate."""


@dataclass(frozen=True)
class ReadySnapshot:
    """A verified, content-addressed READY snapshot artifact."""

    snapshot_id: str
    db_path: Path
    manifest_path: Path
    manifest: dict[str, Any]
    publication_path: Path | None = None
    readiness_path: Path | None = None
    readiness_digest: str | None = None
    readiness_attestation_id: str | None = None
    readiness_bytes: bytes | None = None
    artifact_digest: str | None = None
    artifact_identity: tuple[int, ...] | None = None
    manifest_identity: tuple[int, ...] | None = None
    publication_identity: tuple[int, ...] | None = None
    readiness_identity: tuple[int, ...] | None = None
    publication_digest: str | None = None

    @property
    def committed_at(self) -> str:
        return str(self.manifest["committed_at"])


@dataclass(frozen=True)
class _ReadyPublicationProductApi:
    """Product-plane operations required by the READY publication runner.

    ``paper_runtime`` owns the immutable snapshot transaction, while the
    product plane owns plan/profile/readiness policy.  Keeping those operations
    explicit prevents the reusable runtime from importing back into the
    product plane.
    """

    load_verified_pilot_readiness_bytes: Callable[..., Any]
    verified_publication_type: Callable[..., Any]
    verified_projection_evidence: Callable[..., Any]
    build_profile_bound_manifest: Callable[..., Any]
    load_exact_four_binding: Callable[..., Any]
    ready_manifest_from_document: Callable[..., Any]
    profile_ready: Callable[..., bool]
    verify_exact_four_pit_scope: Callable[..., Mapping[str, Any]]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def fail_snapshot_sync(conn: sqlite3.Connection, error: str) -> None:
    """Keep a partial local DB unavailable to paper research."""
    conn.execute(
        """
        INSERT INTO local_snapshot_policy
            (singleton, require_manifest, snapshot_ready, last_error,
             publication_state, active_snapshot_id)
        VALUES (1, 1, 0, ?, 'REJECTED', NULL)
        ON CONFLICT(singleton) DO UPDATE SET
            require_manifest = 1,
            snapshot_ready = 0,
            last_error = excluded.last_error,
            publication_state = 'REJECTED',
            active_snapshot_id = NULL
        """,
        (error[:2000],),
    )
    conn.commit()


def _latest_complete_run(
    conn: sqlite3.Connection, required: tuple[str, ...]
) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
    run = conn.execute(
        "SELECT id, status, detail FROM ingestion_run_log "
        "WHERE source='jquants' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if run is None:
        raise RuntimeError("no ingestion run is available for snapshot commit")
    status = str(run["status"] if isinstance(run, sqlite3.Row) else run[1])
    run_id = int(run["id"] if isinstance(run, sqlite3.Row) else run[0])
    detail_raw = run["detail"] if isinstance(run, sqlite3.Row) else run[2]
    try:
        detail = json.loads(detail_raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"ingestion run {run_id} has invalid detail JSON") from exc
    if not isinstance(detail, dict):
        raise RuntimeError(f"ingestion run {run_id} detail is not an object")
    if status != "pass":
        raise RuntimeError(
            f"latest ingestion run {run_id} is {status!r}, not a complete pass"
        )
    expected = len(required)
    if (
        int(detail.get("datasetCount", -1)) != expected
        or int(detail.get("passed", -1)) != expected
        or int(detail.get("failed", -1)) != 0
    ):
        raise RuntimeError(
            f"ingestion run {run_id} is not the complete {expected}-dataset run"
        )

    rows = conn.execute(
        "SELECT dataset, status, finished_at, rows_seen, rows_inserted, "
        "rows_revisions FROM ingestion_validation WHERE run_id = ? "
        "ORDER BY dataset, id",
        (run_id,),
    ).fetchall()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row) if isinstance(row, sqlite3.Row) else {
            "dataset": row[0], "status": row[1], "finished_at": row[2],
            "rows_seen": row[3], "rows_inserted": row[4],
            "rows_revisions": row[5],
        }
        latest[str(item["dataset"])] = item
    missing = sorted(set(required) - set(latest))
    failed = sorted(
        dataset for dataset in required
        if dataset in latest and latest[dataset].get("status") != "pass"
    )
    if missing or failed:
        raise RuntimeError(
            f"ingestion run {run_id} validation incomplete: "
            f"missing={missing}, failed={failed}"
        )
    return run_id, detail, [latest[dataset] for dataset in required]


def _artifact_stem(snapshot_id: str) -> str:
    if not _SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise ValueError(f"invalid snapshot_id: {snapshot_id!r}")
    return snapshot_id.replace(":", "_", 1)


def _watermarks_for(
    conn: sqlite3.Connection,
    required: tuple[str, ...],
    coverage_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in required)
    rows = conn.execute(
        "SELECT dataset, last_event_date, last_ingested_at "
        "FROM ingestion_watermarks "
        f"WHERE dataset IN ({placeholders}) ORDER BY dataset",
        required,
    ).fetchall()
    watermarks = [dict(row) for row in rows]
    present = {str(row["dataset"]) for row in watermarks}
    coverage = {
        str(row["dataset"]): row for row in (coverage_rows or [])
    }
    # JSDA has no D1 watermark; current governed Coverage observed_end is the bound.
    for dataset in sorted(set(required) - present):
        row = coverage.get(dataset)
        if (
            row is not None
            and row.get("status") == "COMPLETE"
            and row.get("observed_end")
            and row.get("evaluated_at")
        ):
            watermarks.append({
                "dataset": dataset,
                "last_event_date": row["observed_end"],
                "last_ingested_at": row["evaluated_at"],
                "derived_from": "governed_coverage_receipts",
            })
            present.add(dataset)
    watermarks.sort(key=lambda row: str(row["dataset"]))
    missing = sorted(set(required) - present)
    if missing:
        raise SnapshotRejected(f"required dataset watermarks missing: {missing}")
    return watermarks


def _publish_ready_snapshot(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    required_datasets: Iterable[str],
    _profile_coverage_evidence: Mapping[str, Any] | None = None,
    _dependency_scope_evidence: Mapping[str, Any] | None = None,
    _ready_manifest_builder: (
        Callable[[Mapping[str, Any]], Mapping[str, Any]] | None
    ) = None,
    _ready_attestation_builder: Callable[[ReadySnapshot], Path | None] | None = None,
) -> ReadySnapshot:
    """Reject generic local production publication before any mutation.

    Production snapshots are accepted only through the verify-only reader
    after an external READY authority has signed the exact immutable artifact.
    """
    del (
        staging_db,
        snapshot_dir,
        required_datasets,
        _profile_coverage_evidence,
        _dependency_scope_evidence,
        _ready_manifest_builder,
        _ready_attestation_builder,
    )
    raise SnapshotRejected("generic production READY authority is PENDING")


def _publish_ready_snapshot_impl(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    required_datasets: Iterable[str],
    _profile_coverage_evidence: Mapping[str, Any] | None = None,
    _dependency_scope_evidence: Mapping[str, Any] | None = None,
    _ready_manifest_builder: (
        Callable[[Mapping[str, Any]], Mapping[str, Any]] | None
    ) = None,
    _ready_attestation_builder: Callable[[ReadySnapshot], Path | None] | None = None,
    publication_gate: Callable[..., tuple[Any, ...]],
    fixture_compatibility: bool,
) -> ReadySnapshot:
    """Tests-only compatibility publisher; it cannot select production scope."""

    if fixture_compatibility is not True:
        raise SnapshotRejected(
            "local production READY publication is disabled; authority is PENDING"
        )
    return _publish_fixture_snapshot_candidate(
        staging_db,
        snapshot_dir,
        required_datasets=required_datasets,
        _profile_coverage_evidence=_profile_coverage_evidence,
        _dependency_scope_evidence=_dependency_scope_evidence,
        _ready_manifest_builder=_ready_manifest_builder,
        _ready_attestation_builder=_ready_attestation_builder,
        publication_gate=publication_gate,
    )


def _snapshot_candidate_engine(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    required_datasets: Iterable[str],
    _profile_coverage_evidence: Mapping[str, Any] | None = None,
    _dependency_scope_evidence: Mapping[str, Any] | None = None,
    _ready_manifest_builder: (
        Callable[[Mapping[str, Any]], Mapping[str, Any]] | None
    ) = None,
    _ready_attestation_builder: Callable[[ReadySnapshot], Path | None] | None = None,
    publication_gate: Callable[..., tuple[Any, ...]],
    fixture_compatibility: bool,
    publication_scope: str,
) -> ReadySnapshot:
    """Build one candidate; only the fixed product wrapper selects production.

    This core is not signing authority.  A production marker is usable only
    after the independently recomputing READY service returns a pinned signed
    attestation that the production metadata verifier accepts.
    """

    if (fixture_compatibility, publication_scope) not in {
        (True, "FIXTURE"),
        (False, "PRODUCTION"),
    }:
        raise SnapshotRejected("snapshot candidate scope is invalid")
    staging_path = Path(staging_db).resolve()
    if not staging_path.is_file():
        raise FileNotFoundError(f"staging database does not exist: {staging_path}")
    required = tuple(sorted(set(str(item) for item in required_datasets)))
    if not required:
        raise ValueError("required_datasets must not be empty")
    policies = {policy.dataset_id: policy for policy in all_coverage_contracts()}
    governed = {
        dataset_id for dataset_id, policy in policies.items()
        if policy.governance_tier == "governed"
    }
    required_set = set(required)
    profile_bound = _ready_manifest_builder is not None
    if profile_bound != (_profile_coverage_evidence is not None):
        raise SnapshotRejected(
            "profile coverage evidence and ReadyManifest builder must be supplied together"
        )
    if _ready_attestation_builder is not None and not profile_bound:
        raise SnapshotRejected(
            "READY attestation builder requires a profile-bound ReadyManifest"
        )
    if _dependency_scope_evidence is not None and not profile_bound:
        raise SnapshotRejected(
            "dependency scope evidence requires a profile-bound ReadyManifest"
        )
    if not profile_bound and not fixture_compatibility:
        raise SnapshotRejected(
            "production READY requires a profile/plan-bound ReadyManifest publisher"
        )
    if (
        profile_bound
        and not fixture_compatibility
        and _ready_attestation_builder is None
    ):
        raise SnapshotRejected(
            "production READY requires an atomic signed readiness attestation"
        )
    if (
        profile_bound
        and not fixture_compatibility
        and not isinstance(_dependency_scope_evidence, Mapping)
    ):
        raise SnapshotRejected(
            "production READY requires publisher-owned dependency scope evidence"
        )
    if not profile_bound and (
        not governed <= required_set or not required_set <= set(policies)
    ):
        raise SnapshotRejected(
            "READY publication must cover every governed dataset and only "
            "contracted datasets: "
            f"missing={sorted(governed - required_set)}, "
            f"unknown={sorted(required_set - set(policies))}"
        )
    destination = Path(snapshot_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(staging_path))
    conn.row_factory = sqlite3.Row
    build_id = "build-" + uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    contract = f"jquants-premium-core/v{DATASET_CONTRACT_VERSION}"
    governed_required = [
        dataset_id
        for dataset_id in required
        if policies[dataset_id].governance_tier == "governed"
    ]
    coverage_policy = coverage_policy_set_binding(governed_required)
    coverage_policy_version = str(coverage_policy["policy_version"])
    coverage_policy_digest = str(coverage_policy["policy_digest"])
    quality_policy_version = QUALITY_POLICY_VERSION
    readiness_sidecar_path: Path | None = None
    artifact_path: Path | None = None
    manifest_path: Path | None = None
    publication_marker_path: Path | None = None
    artifact_created = False
    manifest_attempted = False
    pointer_attempted = False
    publication_marker_attempted = False
    try:
        _persist_building_publication(
            conn,
            build_id=build_id,
            created_at=created_at,
            staging_path=str(staging_path),
            contract_version=contract,
            coverage_policy_version=coverage_policy_version,
            quality_policy_version=quality_policy_version,
        )
        _transition_policy(conn, "SYNCED")
        _persist_synced_publication(conn, build_id)
        _transition_policy(conn, "VALIDATING")
        conn.execute(
            "UPDATE snapshot_publications SET state='VALIDATING' WHERE build_id=?",
            (build_id,),
        )
        conn.commit()

        try:
            (
                run_id, run_detail, validations, coverage_rows,
                quality_summary, quality_failures, raw_manifests,
                coverage_proof, coverage_proof_id, ready_evidence,
            ) = publication_gate(
                conn,
                staging_path,
                build_id=build_id,
                required=required,
            )
            watermarks = _watermarks_for(conn, required, coverage_rows)
            if READY_MANIFEST_SCHEMA.get("$id") != "ready-manifest/v1":
                raise SnapshotRejected("ReadyManifest schema is not the publish gate")
        except Exception as exc:
            reason = str(exc)[:4000]
            conn.execute(
                "UPDATE snapshot_publications SET state='REJECTED', "
                "rejection_reason=? WHERE build_id=?",
                (reason, build_id),
            )
            conn.commit()
            _transition_policy(conn, "REJECTED", error=reason)
            if isinstance(exc, SnapshotRejected):
                raise
            raise SnapshotRejected(reason) from exc

        sync_items = [
            item
            for item in ready_evidence.get("items", [])
            if isinstance(item, Mapping)
            and item.get("name") == "SyncGenerationEvidence"
        ]
        if len(sync_items) != 1 or not isinstance(
            sync_items[0].get("detail"), Mapping
        ):
            raise SnapshotRejected("production READY sync evidence is missing")
        try:
            change_seq = int(
                sync_items[0]["detail"]["applied_sync_generation"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotRejected(
                "production READY applied generation is malformed"
            ) from exc
        if change_seq <= 0:
            raise SnapshotRejected("production READY applied generation is null")
        quality_row = conn.execute(
            "SELECT results_json FROM snapshot_quality_results WHERE build_id=?",
            (build_id,),
        ).fetchone()
        if quality_row is None:
            raise SnapshotRejected("production READY quality result ledger is missing")
        try:
            quality_results = json.loads(str(quality_row[0]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise SnapshotRejected(
                "production READY quality result ledger is malformed"
            ) from exc
        if not isinstance(quality_results, list) or not quality_results:
            raise SnapshotRejected("production READY quality results are empty")
        committed_at = datetime.now(timezone.utc).isoformat()
        manifest: dict[str, Any] = {
            "format": RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
            "state": "READY",
            "build_id": build_id,
            "contract_version": contract,
            "source_contract_versions": {
                "jquants": contract,
                "jsda": JSDA_CONTRACT_VERSION,
            },
            "source_run": {
                "id": run_id,
                "started_at": run_detail.get("startedAt"),
                "finished_at": run_detail.get("finishedAt"),
            },
            "change_seq": change_seq,
            "coverage_policy_version": coverage_policy_version,
            "coverage_policy_digest": coverage_policy_digest,
            "quality_policy_version": quality_policy_version,
            "required_datasets": list(required),
            "dataset_watermarks": watermarks,
            "coverage": [
                {
                    key: row[key]
                    for key in (
                        "dataset", "status", "history_target_start",
                        "history_target_end_rule", "coverage_mode",
                        "expected_frequency", "universe_rule",
                        "governance_tier", "observed_start", "observed_end",
                        "row_count",
                    )
                }
                for row in coverage_rows
            ],
            "coverage_proof": coverage_proof,
            "coverage_proof_id": coverage_proof_id,
            "quality": {
                "status": "PASS",
                "summary": quality_summary,
                "failures": quality_failures,
                "results": quality_results,
            },
            "ready_evidence": ready_evidence,
            "raw_manifests": raw_manifests,
            "validations": validations,
            "created_at": created_at,
            "committed_at": committed_at,
        }
        if profile_bound:
            manifest["profile_coverage_evidence"] = {
                str(dataset_id): dict(row)
                for dataset_id, row in _profile_coverage_evidence.items()
            }
        if _dependency_scope_evidence is not None:
            manifest["dependency_scope_evidence"] = dict(
                _dependency_scope_evidence
            )
        snapshot_id = _research_manifest_id(manifest)
        manifest["snapshot_id"] = snapshot_id
        if profile_bound:
            nested = _ready_manifest_builder(manifest)
            if not isinstance(nested, Mapping):
                raise SnapshotRejected("ReadyManifest builder did not return an object")
            manifest["ready_manifest"] = dict(nested)
        stem = _artifact_stem(snapshot_id)
        artifact_path = destination / f"{stem}.sqlite"
        manifest_path = destination / f"{stem}.manifest.json"
        publication_marker_path = destination / f"{stem}.publication.json"
        manifest["artifact"] = artifact_path.name
        manifest["manifest_digest"] = _research_manifest_digest(manifest)

        fd, raw_temp = tempfile.mkstemp(
            prefix=f".{stem}.", suffix=".sqlite.tmp", dir=destination
        )
        os.close(fd)
        temp_db = Path(raw_temp)
        try:
            _copy_sqlite(conn, temp_db)
            embedded = sqlite3.connect(str(temp_db))
            embedded.row_factory = sqlite3.Row
            try:
                manifest_json = json.dumps(
                    manifest, ensure_ascii=True, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                )
                embedded.execute(
                    """
                    INSERT OR REPLACE INTO local_snapshot_manifests
                        (snapshot_id, format, committed_at, source_run_id,
                         change_seq, manifest_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id, RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
                        committed_at, run_id, change_seq, manifest_json,
                    ),
                )
                embedded.execute(
                    "UPDATE local_snapshot_policy SET snapshot_ready=1, "
                    "publication_state='READY', active_snapshot_id=?, "
                    "last_error=NULL WHERE singleton=1",
                    (snapshot_id,),
                )
                embedded.execute(
                    "UPDATE snapshot_publications SET snapshot_id=?, state='READY', "
                    "artifact_path=?, manifest_path=?, source_run_id=?, change_seq=?, "
                    "committed_at=?, rejection_reason=NULL, manifest_json=? "
                    "WHERE build_id=?",
                    (
                        snapshot_id, str(artifact_path), str(manifest_path),
                        run_id, change_seq, committed_at, manifest_json, build_id,
                    ),
                )
                embedded.commit()
                integrity = embedded.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise RuntimeError(f"snapshot integrity check failed: {integrity}")
                embedded.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                embedded.close()
            os.chmod(temp_db, 0o444)
            if artifact_path.exists():
                existing = (
                    _describe_fixture_snapshot(destination, snapshot_id)
                    if fixture_compatibility
                    else describe_snapshot(destination, snapshot_id)
                )
                temp_db.unlink(missing_ok=True)
                ready = existing
                manifest = existing.manifest
                manifest_path = existing.manifest_path
                artifact_path = existing.db_path
                committed_at = existing.committed_at
            else:
                os.replace(temp_db, artifact_path)
                artifact_created = True
                manifest_attempted = True
                _atomic_json(manifest_path, manifest, mode=0o444)
                ready = ReadySnapshot(
                    snapshot_id, artifact_path, manifest_path, manifest
                )
        except Exception:
            temp_db.unlink(missing_ok=True)
            raise

        conn.execute(
            "UPDATE snapshot_publications SET snapshot_id=?, state='READY', "
            "artifact_path=?, manifest_path=?, source_run_id=?, change_seq=?, "
            "committed_at=?, rejection_reason=NULL, manifest_json=? "
            "WHERE build_id=?",
            (
                snapshot_id, str(artifact_path), str(manifest_path), run_id,
                change_seq, committed_at,
                json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                build_id,
            ),
        )
        conn.execute(
            "UPDATE local_snapshot_policy SET snapshot_ready=0, "
            "publication_state='READY', active_snapshot_id=?, last_error=NULL "
            "WHERE singleton=1",
            (snapshot_id,),
        )
        conn.commit()

        # Signing is deliberately after the authoritative source transaction:
        # a failed READY commit must never leave a usable signed capability.
        # If pointer finalization later fails, the returned sidecar path is
        # removed by the rejection handler below before control escapes.
        if _ready_attestation_builder is not None:
            readiness_sidecar_path = _ready_attestation_builder(ready)
            if (
                readiness_sidecar_path is None
                or not readiness_sidecar_path.is_file()
            ):
                raise SnapshotRejected(
                    "READY attestation builder did not publish an artifact"
                )
        artifact_digest = _file_sha256(artifact_path)
        readiness_attestation_id: str | None = None
        readiness_attestation_digest: str | None = None
        if readiness_sidecar_path is not None and publication_scope == "PRODUCTION":
            from paper_runtime.readiness_attestation import (
                ReadyAttestationVerificationError,
                decode_strict_ready_json,
            )

            try:
                readiness_bytes = readiness_sidecar_path.read_bytes()
                readiness_document = decode_strict_ready_json(readiness_bytes)
            except (OSError, ReadyAttestationVerificationError) as exc:
                raise SnapshotRejected(
                    "READY attestation is not strict immutable JSON"
                ) from exc
            if type(readiness_document) is not dict:
                raise SnapshotRejected("READY attestation must be an object")
            readiness_attestation_id = readiness_document.get("attestation_id")
            if (
                type(readiness_attestation_id) is not str
                or not readiness_attestation_id
                or Path(readiness_attestation_id).name
                != readiness_attestation_id
            ):
                raise SnapshotRejected("READY attestation id is invalid")
            expected_sidecar_name = (
                f"{artifact_path.stem}.{readiness_attestation_id}.readiness.json"
            )
            if readiness_sidecar_path.name != expected_sidecar_name:
                raise SnapshotRejected(
                    "READY attestation filename does not bind its exact id"
                )
            readiness_attestation_digest = (
                "sha256:" + hashlib.sha256(readiness_bytes).hexdigest()
            )
        elif readiness_sidecar_path is not None:
            readiness_attestation_digest = _file_sha256(readiness_sidecar_path)
        publication_body: dict[str, Any] = {
            "format": RESEARCH_SNAPSHOT_PUBLICATION_FORMAT,
            "snapshot_id": snapshot_id,
            "manifest_digest": manifest["manifest_digest"],
            "committed_at": committed_at,
            "change_seq": change_seq,
            "artifact_digest": artifact_digest,
            "publication_scope": publication_scope,
            "readiness_attestation": (
                readiness_sidecar_path.name
                if readiness_sidecar_path is not None
                else None
            ),
            "readiness_attestation_digest": readiness_attestation_digest,
            "readiness_attestation_id": readiness_attestation_id,
        }
        publication = {
            **publication_body,
            "publication_digest": _canonical_digest(publication_body),
        }
        # The mutable convenience pointer binds the complete marker and its
        # monotonic source generation.  The marker is written last, so a
        # pointer failure cannot leave a directly discoverable publication.
        pointer_attempted = True
        _atomic_json(
            destination / "latest-ready.json",
            {
                "format": "research-snapshot-pointer/v1",
                "snapshot_id": snapshot_id,
                "manifest": manifest_path.name,
                "committed_at": committed_at,
                "change_seq": change_seq,
                "publication_digest": publication["publication_digest"],
            },
            mode=0o444,
        )
        publication_marker_attempted = True
        _atomic_json(publication_marker_path, publication, mode=0o444)
        return ready
    except Exception as exc:
        original_exc = exc
        # A replace-last helper can be wrapped by a filesystem layer that
        # reports failure after the destination appeared.  Remove discovery
        # documents for every attempted finalization before cleaning signed
        # sidecars or quarantining immutable evidence.
        if publication_marker_attempted and publication_marker_path is not None:
            try:
                publication_marker_path.unlink(missing_ok=True)
            except OSError:
                pass
        if pointer_attempted:
            try:
                (destination / "latest-ready.json").unlink(missing_ok=True)
            except OSError:
                pass
        if readiness_sidecar_path is not None:
            try:
                readiness_sidecar_path.unlink(missing_ok=True)
            except OSError:
                # A retained signed capability would be unsafe even though the
                # source publication is rejected. Surface that cleanup failure
                # rather than reporting the original finalization error alone.
                exc = SnapshotRejected(
                    "READY publication rejected but readiness sidecar cleanup "
                    f"failed: {readiness_sidecar_path}"
                )
        created_paths = [
            path
            for path, created in (
                (artifact_path, artifact_created),
                (manifest_path, manifest_attempted),
            )
            if created and path is not None and path.exists()
        ]
        if created_paths:
            quarantine_path = destination / "rejected" / build_id
            try:
                quarantine_path.mkdir(parents=True, exist_ok=False)
                for path in created_paths:
                    os.replace(path, quarantine_path / path.name)
                exc = SnapshotRejected(
                    "READY publication finalization failed; rejected immutable "
                    f"evidence quarantined at {quarantine_path}: {exc}"
                )
            except OSError as cleanup_exc:
                # No publication marker exists, so even a failed quarantine is
                # outside every public READY read path. Surface the cleanup
                # problem for an operator rather than treating it as success.
                exc = SnapshotRejected(
                    "READY publication failed and rejected evidence quarantine "
                    f"failed: {cleanup_exc}; original error: {exc}"
                )
        try:
            conn.rollback()
            conn.execute(
                "UPDATE snapshot_publications SET state='REJECTED', "
                "rejection_reason=? WHERE build_id=?",
                (str(exc)[:4000], build_id),
            )
            conn.execute(
                "UPDATE local_snapshot_policy SET snapshot_ready=0, "
                "publication_state='REJECTED', active_snapshot_id=NULL, "
                "last_error=? WHERE singleton=1",
                (str(exc)[:4000],),
            )
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
        if exc is not original_exc:
            raise exc from original_exc
        raise
    finally:
        conn.close()


def _publish_exact_four_pilot_ready_snapshot_via_authority_impl(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    signed_projection_document: object,
    _candidate_engine: Callable[..., ReadySnapshot],
    _product_api: _ReadyPublicationProductApi,
) -> Any:
    """Publish the canonical pilot only through the isolated READY service.

    The public product callable accepts no caller-selected signer, registry,
    profile, dataset membership, manifest builder, or fixture policy.  Its
    internal product adapter is not an authority: this runner preflights the
    pinned local authority before inspecting caller evidence, creates an
    undiscoverable immutable candidate, and asks the authority to independently
    reopen and sign that exact snapshot.  Publication markers are written only
    after the returned signature has been verified and retained byte-for-byte.
    """

    from scripts.local_authority_clients import ReadyPublisherAuthorityClient
    from scripts.local_authority_service import LocalAuthorityError

    # Bind the exact production caller UID, active public registry, and launchd
    # socket before reading or mutating caller-provided publication material.
    client = ReadyPublisherAuthorityClient(environment="production")
    client.require_available()
    if type(signed_projection_document) is not bytes or not signed_projection_document:
        raise SnapshotRejected("signed Ops projection must be exact non-empty bytes")
    signed_projection = signed_projection_document
    governed = _product_api.load_exact_four_binding()
    evidence = _product_api.verified_projection_evidence(
        signed_projection,
        list(governed.required_datasets),
        expected_environment="production",
    )
    if set(evidence.rows) != set(governed.required_datasets):
        raise SnapshotRejected(
            "pilot READY evidence must exactly match the dependency closure"
        )
    for profile in governed.profiles:
        if not _product_api.profile_ready(profile, evidence.rows):
            raise SnapshotRejected(
                f"pilot READY evidence is incomplete for {profile.plan_id}"
            )
    for dataset_id in governed.required_datasets:
        row = evidence.rows[dataset_id]
        source = str(row.get("source_generation") or "").strip()
        exported = str(row.get("export_cursor") or "").strip()
        applied = str(
            row.get("applied_sync_generation") or row.get("applied_cursor") or ""
        ).strip()
        if not source or source != exported or exported != applied:
            raise SnapshotRejected(
                f"pilot READY cursor chain is missing or not current for {dataset_id}"
            )
        scopes = [
            dict(scope)
            for profile in governed.profiles
            for scope in profile.dataset_scopes
            if scope.get("dataset_id") == dataset_id
        ]
        required_start = min(str(scope["period_start"]) for scope in scopes)
        required_end = max(str(scope["period_end"]) for scope in scopes)
        observed_start = str(row.get("observed_start") or "")[:10]
        observed_end = str(row.get("observed_end") or "")[:10]
        if (
            not observed_start
            or not observed_end
            or observed_start > required_start
            or observed_end < required_end
        ):
            raise SnapshotRejected(
                "pilot READY Coverage does not span the dependency period for "
                f"{dataset_id}: observed={observed_start}..{observed_end}, "
                f"required={required_start}..{required_end}"
            )

    scope_proof = _product_api.verify_exact_four_pit_scope(staging_db, governed)

    def build_manifest(document: Mapping[str, Any]) -> Mapping[str, Any]:
        return _product_api.build_profile_bound_manifest(
            document, profile=governed
        ).to_dict()

    signed_result: dict[str, Any] = {}

    def request_attestation(ready: ReadySnapshot) -> Path:
        manifest = _product_api.ready_manifest_from_document(ready.manifest)
        immutable_scope = _product_api.verify_exact_four_pit_scope(
            ready.db_path, governed
        )
        if (
            manifest.pit_contract_digests.get("dependency_scope")
            != immutable_scope["proof_digest"]
        ):
            raise SnapshotRejected(
                "immutable snapshot PIT dependency scope drifted before authority call"
            )
        event_id = (
            "ready-publish:"
            + ready.snapshot_id
            + ":"
            + evidence.signed_document_digest
        )
        try:
            result = dict(
                client.publish_profile_plan_bound(
                    event_id=event_id,
                    snapshot_id=ready.snapshot_id,
                    signed_projection_document=signed_projection,
                )
            )
        except LocalAuthorityError as exc:
            raise SnapshotRejected("isolated READY authority rejected publication") from exc
        try:
            raw = base64.b64decode(result["attestation_base64"], validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotRejected("READY authority returned invalid attestation bytes") from exc
        if "sha256:" + hashlib.sha256(raw).hexdigest() != result.get(
            "attestation_digest"
        ):
            raise SnapshotRejected("READY authority attestation digest mismatch")
        path = ready.db_path.with_name(
            f"{ready.db_path.stem}.{result['attestation_id']}.readiness.json"
        )
        try:
            _atomic_bytes(path, raw, mode=0o444)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        signed_result.update(result=result, path=path)
        return path

    snapshot = _candidate_engine(
        staging_db,
        snapshot_dir,
        required_datasets=governed.required_datasets,
        _profile_coverage_evidence=evidence.rows,
        _dependency_scope_evidence=scope_proof,
        _ready_manifest_builder=build_manifest,
        _ready_attestation_builder=request_attestation,
        publication_gate=evaluate_ready_publication,
        fixture_compatibility=False,
        publication_scope="PRODUCTION",
    )
    if set(signed_result) != {"result", "path"}:
        raise SnapshotRejected("isolated READY authority produced no attestation")
    # Re-describe through the production metadata verifier after the
    # publication marker is durable. The result is not a database-read
    # capability.
    reopened = describe_snapshot(snapshot_dir, snapshot.snapshot_id)
    result = signed_result["result"]
    readiness_path = reopened.readiness_path
    readiness_bytes = reopened.readiness_bytes
    ready_manifest = _product_api.ready_manifest_from_document(reopened.manifest)
    if (
        not isinstance(readiness_path, Path)
        or type(readiness_bytes) is not bytes
        or not readiness_bytes
        or readiness_path != Path(signed_result["path"])
        or reopened.readiness_attestation_id != result.get("attestation_id")
        or reopened.readiness_digest != result.get("attestation_digest")
    ):
        raise SnapshotRejected(
            "published marker does not pin the authority's exact attestation"
        )
    readiness = _product_api.load_verified_pilot_readiness_bytes(
        readiness_bytes,
        expected_environment="production",
        expected_snapshot_id=reopened.snapshot_id,
        expected_ready_manifest_digest=ready_manifest.manifest_digest,
    )
    return _product_api.verified_publication_type(
        snapshot=reopened,
        readiness=readiness,
        readiness_path=readiness_path,
    )


def _bind_snapshot_candidate_publishers(
    engine: Callable[..., ReadySnapshot],
    exact_four_impl: Callable[..., Any],
) -> tuple[Callable[..., ReadySnapshot], Callable[..., Any]]:
    """Bind fixture and product wrappers around a non-authoritative engine.

    Python closure introspection is not a security boundary and can recover
    ``engine``.  Safety instead comes from the fact that the engine cannot mint
    the isolated authority signature required by the production metadata
    verifier.
    """

    def fixture_candidate(
        staging_db: str | Path,
        snapshot_dir: str | Path,
        *,
        required_datasets: Iterable[str],
        _profile_coverage_evidence: Mapping[str, Any] | None = None,
        _dependency_scope_evidence: Mapping[str, Any] | None = None,
        _ready_manifest_builder: (
            Callable[[Mapping[str, Any]], Mapping[str, Any]] | None
        ) = None,
        _ready_attestation_builder: (
            Callable[[ReadySnapshot], Path | None] | None
        ) = None,
        publication_gate: Callable[..., tuple[Any, ...]],
    ) -> ReadySnapshot:
        return engine(
            staging_db,
            snapshot_dir,
            required_datasets=required_datasets,
            _profile_coverage_evidence=_profile_coverage_evidence,
            _dependency_scope_evidence=_dependency_scope_evidence,
            _ready_manifest_builder=_ready_manifest_builder,
            _ready_attestation_builder=_ready_attestation_builder,
            publication_gate=publication_gate,
            fixture_compatibility=True,
            publication_scope="FIXTURE",
        )

    def exact_four_candidate(
        staging_db: str | Path,
        snapshot_dir: str | Path,
        *,
        signed_projection_document: object,
        _product_api: _ReadyPublicationProductApi,
    ) -> Any:
        return exact_four_impl(
            staging_db,
            snapshot_dir,
            signed_projection_document=signed_projection_document,
            _candidate_engine=engine,
            _product_api=_product_api,
        )

    return fixture_candidate, exact_four_candidate


(
    _publish_fixture_snapshot_candidate,
    _publish_exact_four_pilot_ready_snapshot_via_authority,
) = _bind_snapshot_candidate_publishers(
    _snapshot_candidate_engine,
    _publish_exact_four_pilot_ready_snapshot_via_authority_impl,
)
del _snapshot_candidate_engine
del _publish_exact_four_pilot_ready_snapshot_via_authority_impl
del _bind_snapshot_candidate_publishers


__all__ = [
    "DATA_SNAPSHOT_FORMAT",
    "LOCAL_SNAPSHOT_MANIFEST_FORMAT",
    "QUALITY_POLICY_VERSION",
    "READY_MANIFEST_SCHEMA",
    "RESEARCH_SNAPSHOT_MANIFEST_FORMAT",
    "SNAPSHOT_STATES",
    "ReadySnapshot",
    "SnapshotRejected",
    "begin_snapshot_sync",
    "data_snapshot_id",
    "describe_snapshot",
    "fail_snapshot_sync",
    "latest_ready_snapshot",
    "list_ready_snapshots",
]
