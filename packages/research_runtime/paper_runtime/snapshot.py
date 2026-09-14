"""Cheap, control-plane-based identifiers for local SQLite data snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import ExitStack
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
from pit.sqlite_identity import (
    DATA_SNAPSHOT_FORMAT,
    RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
    _canonical_digest,
    _immutable_data_snapshot_id,
    _research_manifest_digest,
    _research_manifest_id,
    data_snapshot_id,
)
from paper_runtime.snapshot_persist import (
    _atomic_bytes,
    _atomic_json,
)
from pit.ready_evidence import (
    ReadyLedgerSession,
    begin_snapshot_sync,
    fail_snapshot_sync,
    ready_publication_session,
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


def canonical_observed_through_from_authenticated_exported_at(
    exported_at: Any,
) -> str:
    """Fail-closed observation clock from authenticated frozen exported_at.

    Wall time, decision time, personal_history_manifest, and dataset watermarks
    are not substitutes. The applied-mirror exported_at identity is the only
    accepted source.
    """
    from pit.errors import AsOfRequired, InvalidAsOf
    from pit.read_clock import MAX_SNAPSHOT_CLOCK_FUTURE_SKEW, normalize_as_of
    from ingestion.common.timeutil import now_jst, parse_dt

    if type(exported_at) is not str or not exported_at.strip():
        raise SnapshotRejected("authenticated exported_at is missing")
    try:
        canonical = normalize_as_of(exported_at)
    except (AsOfRequired, InvalidAsOf) as exc:
        raise SnapshotRejected("authenticated exported_at is malformed") from exc
    if exported_at != canonical:
        raise SnapshotRejected("authenticated exported_at is noncanonical")
    if parse_dt(canonical) - now_jst() > MAX_SNAPSHOT_CLOCK_FUTURE_SKEW:
        raise SnapshotRejected("authenticated exported_at is in the future")
    return canonical


def write_publisher_owned_snapshot_observation_clock(
    session: ReadyLedgerSession, observed_through: str
) -> str:
    """Write exactly one publisher-owned clock row into a temporary SQLite."""

    from pit.errors import PitError

    canonical = canonical_observed_through_from_authenticated_exported_at(
        observed_through
    )
    try:
        return session.write_observation_clock(canonical)
    except PitError as exc:
        raise SnapshotRejected(str(exc)) from exc


def _extract_authenticated_exported_at(ready_evidence: Mapping[str, Any] | None) -> str | None:
    if not isinstance(ready_evidence, Mapping):
        return None
    items = ready_evidence.get("items")
    if not isinstance(items, list):
        return None
    found: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        detail = item.get("detail")
        if not isinstance(detail, Mapping):
            continue
        value = detail.get("exported_at") or detail.get("authenticated_exported_at")
        if type(value) is str and value.strip():
            found.append(value)
        nested = detail.get("envelope")
        if isinstance(nested, Mapping):
            env = nested.get("exported_at")
            if type(env) is str and env.strip():
                found.append(env)
    unique = list(dict.fromkeys(found))
    if not unique:
        return None
    if len(unique) != 1:
        raise SnapshotRejected("authenticated exported_at is inconsistent")
    return unique[0]



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


def _latest_complete_run(
    session: ReadyLedgerSession, required: tuple[str, ...]
) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
    run = session.latest_jquants_ingestion_run()
    if run is None:
        raise RuntimeError("no ingestion run is available for snapshot commit")
    status = str(run["status"])
    run_id = int(run["id"])
    detail_raw = run["detail"]
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

    rows = session.ingestion_validation_run_rows(run_id)
    latest: dict[str, dict[str, Any]] = {}
    for item in rows:
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
    session: ReadyLedgerSession,
    required: tuple[str, ...],
    coverage_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    watermarks = [dict(row) for row in session.watermark_rows(required)]
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

    _session_stack = ExitStack()
    session = _session_stack.enter_context(ready_publication_session(staging_path))
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
        session.persist_building_publication(
            build_id=build_id,
            created_at=created_at,
            staging_path=str(staging_path),
            contract_version=contract,
            coverage_policy_version=coverage_policy_version,
            quality_policy_version=quality_policy_version,
        )
        _transition_policy(session, "SYNCED")
        session.persist_synced_publication(build_id)
        _transition_policy(session, "VALIDATING")
        session.mark_publication_validating(build_id)

        try:
            (
                run_id, run_detail, validations, coverage_rows,
                quality_summary, quality_failures, raw_manifests,
                coverage_proof, coverage_proof_id, ready_evidence,
            ) = publication_gate(
                session,
                staging_path,
                build_id=build_id,
                required=required,
            )
            watermarks = _watermarks_for(session, required, coverage_rows)
            if READY_MANIFEST_SCHEMA.get("$id") != "ready-manifest/v1":
                raise SnapshotRejected("ReadyManifest schema is not the publish gate")
        except Exception as exc:
            reason = str(exc)[:4000]
            session.mark_publication_rejected(build_id, reason)
            _transition_policy(session, "REJECTED", error=reason)
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
        quality_json = session.quality_results_json(build_id)
        if quality_json is None:
            raise SnapshotRejected("production READY quality result ledger is missing")
        try:
            quality_results = json.loads(quality_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SnapshotRejected(
                "production READY quality result ledger is malformed"
            ) from exc
        if not isinstance(quality_results, list) or not quality_results:
            raise SnapshotRejected("production READY quality results are empty")
        exported_at = _extract_authenticated_exported_at(ready_evidence)
        if exported_at is None and not fixture_compatibility:
            raise SnapshotRejected("authenticated exported_at is missing")
        publisher_observed_through: str | None = None
        if exported_at is not None:
            publisher_observed_through = (
                canonical_observed_through_from_authenticated_exported_at(
                    exported_at
                )
            )
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
        if publisher_observed_through is not None:
            manifest["observed_through"] = publisher_observed_through
        if profile_bound:
            manifest["profile_coverage_evidence"] = {
                str(dataset_id): dict(row)
                for dataset_id, row in _profile_coverage_evidence.items()
            }
        if _dependency_scope_evidence is not None:
            manifest["dependency_scope_evidence"] = dict(
                _dependency_scope_evidence
            )
        fd, raw_temp = tempfile.mkstemp(
            prefix=".obsclock.", suffix=".sqlite.tmp", dir=destination
        )
        os.close(fd)
        temp_db = Path(raw_temp)
        try:
            session.backup_sqlite(temp_db)
            if publisher_observed_through is None:
                raise SnapshotRejected("authenticated exported_at is missing")
            with ready_publication_session(temp_db) as clock_session:
                write_publisher_owned_snapshot_observation_clock(
                    clock_session, publisher_observed_through
                )
                clock_session.commit()
            snapshot_id = _research_manifest_id(manifest)
            manifest["snapshot_id"] = snapshot_id
            if profile_bound:
                nested = _ready_manifest_builder(manifest)
                if not isinstance(nested, Mapping):
                    raise SnapshotRejected("ReadyManifest builder did not return an object")
                if publisher_observed_through is not None:
                    nested = dict(nested)
                    nested["observed_through"] = publisher_observed_through
                manifest["ready_manifest"] = dict(nested)
            stem = _artifact_stem(snapshot_id)
            artifact_path = destination / f"{stem}.sqlite"
            manifest_path = destination / f"{stem}.manifest.json"
            publication_marker_path = destination / f"{stem}.publication.json"
            manifest["artifact"] = artifact_path.name
            manifest["manifest_digest"] = _research_manifest_digest(manifest)

            with ready_publication_session(temp_db) as embedded:
                manifest_json = json.dumps(
                    manifest, ensure_ascii=True, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                )
                embedded.embed_ready_manifest(
                    snapshot_id=snapshot_id,
                    committed_at=committed_at,
                    run_id=run_id,
                    change_seq=change_seq,
                    manifest_json=manifest_json,
                    artifact_path=str(artifact_path),
                    manifest_path=str(manifest_path),
                    build_id=build_id,
                )
                integrity = embedded.integrity_check()
                if integrity != "ok":
                    raise RuntimeError(f"snapshot integrity check failed: {integrity}")
                embedded.wal_checkpoint_truncate()
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

        session.persist_ready_on_staging(
            build_id=build_id,
            snapshot_id=snapshot_id,
            artifact_path=str(artifact_path),
            manifest_path=str(manifest_path),
            run_id=run_id,
            change_seq=change_seq,
            committed_at=committed_at,
            manifest_json=json.dumps(
                manifest, sort_keys=True, separators=(",", ":")
            ),
        )

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
        session.reject_publication_after_failure(build_id, str(exc)[:4000])
        if exc is not original_exc:
            raise exc from original_exc
        raise
    finally:
        _session_stack.close()


def _publish_exact_four_pilot_ready_snapshot_via_authority_impl(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    signed_projection_document: object,
    _candidate_engine: Callable[..., ReadySnapshot],
    _product_api: _ReadyPublicationProductApi,
) -> Any:
    """Paper-only READY publication uses the Cloudflare public-key issuer.

    Local six-principal ReadyPublisherAuthorityClient is not on this path.
    The issuer is unprovisioned, so publication fails closed before mutating
    caller staging data.
    """

    del staging_db, snapshot_dir, signed_projection_document
    del _candidate_engine, _product_api
    raise SnapshotRejected(
        "READY publication PENDING; Cloudflare/READY public-key issuer is "
        "unprovisioned"
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
