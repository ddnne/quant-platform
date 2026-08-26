"""Test-only entry points for legacy mutable/sparse READY fixtures.

The product publisher has no fixture switch.  These helpers deliberately live
under ``tests`` and call only the private runtime implementation so synthetic
SQLite fixtures cannot become a production publication authority.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_runtime.snapshot import (
    LOCAL_SNAPSHOT_MANIFEST_FORMAT,
    ReadySnapshot,
    SnapshotRejected,
    _canonical_digest,
    _latest_complete_run,
    _publish_ready_snapshot_impl,
)
from paper_runtime.snapshot_read import (
    _describe_fixture_snapshot,
    _latest_fixture_snapshot,
    _list_fixture_snapshots,
    _open_fixture_snapshot,
)
from paper_runtime.coherence import check_ready_coherence
from paper_runtime.ready_policy import (
    ReadyEvidenceBundle,
    ReadyEvidenceItem,
    collect_typed_evidence,
)
from paper_runtime.snapshot_persist import _persist_synced_policy
from paper_runtime.snapshot_coverage_proof import persist_coverage_proof
from paper_runtime.snapshot_publish_policy import (
    READY_MANIFEST_FORMAT,
    READY_MANIFEST_SCHEMA,
    _evaluate_publication_gate_impl,
)
from research.research_data_profile import (
    CORE_PROFILE_ID,
    load_core_profile,
    profile_ready,
)
from selection.budget_ledger import MassResearchDisabledError


def _evaluate_ready_publication_fixture(
    conn,
    staging_path: Path,
    *,
    build_id: str,
    required: tuple[str, ...],
):
    """Sparse synthetic compatibility policy, intentionally tests-only."""
    if READY_MANIFEST_SCHEMA.get("$id") != READY_MANIFEST_FORMAT:
        raise SnapshotRejected("ReadyManifest schema is not the publish gate")
    result = _evaluate_publication_gate_impl(
        conn,
        staging_path,
        build_id=build_id,
        required=required,
        fixture_compatibility=True,
    )
    (
        run_id,
        _run_detail,
        _validations,
        _coverage_rows,
        _quality_summary,
        failures,
        _raw_manifests,
        coverage_proof,
    ) = result
    # Older sparse fixtures predate the source change ledger.  Tests may add
    # that missing observation, but they still persist and verify the exact
    # same immutable Coverage record as production.  Existing mismatches are
    # deliberately not repaired here.
    applied_row = conn.execute(
        "SELECT last_applied_change_seq FROM sync_change_state "
        "WHERE feed='jquants_records'"
    ).fetchone()
    applied_generation = int(applied_row[0]) if applied_row else 0
    if applied_generation <= 0:
        applied_generation = 1
        conn.execute(
            "INSERT INTO sync_change_state "
            "(feed,last_applied_change_seq,updated_at) VALUES "
            "('jquants_records',1,'tests-only-fixture') "
            "ON CONFLICT(feed) DO UPDATE SET "
            "last_applied_change_seq=excluded.last_applied_change_seq, "
            "updated_at=excluded.updated_at"
        )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ingestion_change_log "
        "(change_seq INTEGER NOT NULL)"
    )
    source_row = conn.execute(
        "SELECT COALESCE(MAX(change_seq),0) FROM ingestion_change_log"
    ).fetchone()
    if int(source_row[0]) == 0:
        conn.execute(
            "INSERT INTO ingestion_change_log(change_seq) VALUES (?)",
            (applied_generation,),
        )
    # Sparse fixture databases predate three production ledgers.  Materialize
    # explicit tests-only observations before either coherence or typed policy
    # evaluates them, so repeated fixture publication is content-stable.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ingestion_validation "
        "(run_id INTEGER, dataset TEXT, status TEXT)"
    )
    for dataset_id in required:
        present = conn.execute(
            "SELECT 1 FROM ingestion_validation WHERE run_id=? AND dataset=?",
            (run_id, dataset_id),
        ).fetchone()
        if present is None:
            conn.execute(
                "INSERT INTO ingestion_validation(run_id,dataset,status) "
                "VALUES (?,?,'PASS')",
                (run_id, dataset_id),
            )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS natural_key_migrations (state TEXT)"
    )
    if (
        conn.execute("SELECT 1 FROM natural_key_migrations LIMIT 1").fetchone()
        is None
    ):
        conn.execute("INSERT INTO natural_key_migrations(state) VALUES ('READY')")
    quality_row = conn.execute(
        "SELECT results_json FROM snapshot_quality_results WHERE build_id=?",
        (build_id,),
    ).fetchone()
    if quality_row is not None:
        quality_results = json.loads(str(quality_row[0]))
        if isinstance(quality_results, list):
            quality_results = [
                item
                for item in quality_results
                if not isinstance(item, dict) or item.get("check_id") != "B0"
            ]
            quality_results.append(
                {
                    "check_id": "B0",
                    "dataset": None,
                    "status": "pass",
                    "detail": "tests-only fixture observation",
                    "metrics": {"fixture_compatibility": True},
                }
            )
            conn.execute(
                "UPDATE snapshot_quality_results SET results_json=? "
                "WHERE build_id=?",
                (
                    json.dumps(
                        quality_results,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    build_id,
                ),
            )
    conn.commit()
    coverage_proof_id = persist_coverage_proof(conn, required)
    bundle = ReadyEvidenceBundle()
    for gate in check_ready_coherence(
        conn, staging_path, required, run_id=run_id
    ):
        bundle.items.append(
            ReadyEvidenceItem(
                name=f"coherence.{gate.gate_name}",
                passed=gate.passed,
                reason=gate.reason,
                detail=dict(gate.detail or {}),
            )
        )
    for evidence in collect_typed_evidence(
        conn,
        staging_path,
        required,
        run_id=run_id,
        build_id=build_id,
        coverage_proof_id=coverage_proof_id,
    ):
        bundle.items.append(evidence.to_item())
    if not bundle.passed:
        detail = "; ".join(
            f"{item.name}: {item.reason}" for item in bundle.failures()
        )
        raise SnapshotRejected(f"READY publication policy failed: {detail}")
    return (*result, coverage_proof_id, bundle.to_dict())


def commit_snapshot_manifest_fixture(
    conn: sqlite3.Connection,
    *,
    required_datasets: Iterable[str],
) -> str:
    """Tests-only in-place manifest for legacy mutable history fixtures."""
    required = tuple(sorted(set(str(item) for item in required_datasets)))
    if not required:
        raise ValueError("required_datasets must not be empty")
    _persist_synced_policy(conn)
    conn.execute(
        "UPDATE local_snapshot_policy SET publication_state='VALIDATING' "
        "WHERE singleton=1"
    )
    conn.commit()
    run_id, detail, validations = _latest_complete_run(conn, required)

    placeholders = ",".join("?" for _ in required)
    rows = conn.execute(
        "SELECT dataset, last_event_date, last_ingested_at "
        "FROM ingestion_watermarks "
        f"WHERE dataset IN ({placeholders}) ORDER BY dataset",
        required,
    ).fetchall()
    watermarks = [dict(row) for row in rows]
    present = {str(row["dataset"]) for row in watermarks}
    missing = sorted(set(required) - present)
    if missing:
        raise RuntimeError(f"required dataset watermarks missing: {missing}")
    change = conn.execute(
        "SELECT last_applied_change_seq FROM sync_change_state "
        "WHERE feed = 'jquants_records'"
    ).fetchone()
    change_seq = int(change[0]) if change is not None else 0
    committed_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "format": LOCAL_SNAPSHOT_MANIFEST_FORMAT,
        "committed_at": committed_at,
        "source_run": {
            "id": run_id,
            "started_at": detail.get("startedAt"),
            "finished_at": detail.get("finishedAt"),
        },
        "required_datasets": list(required),
        "change_seq": change_seq,
        "dataset_watermarks": watermarks,
        "validations": validations,
    }
    snapshot_id = _canonical_digest(manifest)
    manifest_json = json.dumps(
        manifest,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT OR IGNORE INTO local_snapshot_manifests
                (snapshot_id, format, committed_at, source_run_id, change_seq,
                 manifest_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                LOCAL_SNAPSHOT_MANIFEST_FORMAT,
                committed_at,
                run_id,
                change_seq,
                manifest_json,
            ),
        )
        conn.execute(
            "UPDATE local_snapshot_policy SET snapshot_ready = 1, "
            "last_error = NULL, publication_state='READY', "
            "active_snapshot_id=? WHERE singleton = 1",
            (snapshot_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return snapshot_id


def publish_ready_snapshot_fixture(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    required_datasets: Iterable[str],
    profile_coverage_evidence: Mapping[str, Any] | None = None,
    ready_manifest_builder: (
        Callable[[Mapping[str, Any]], Mapping[str, Any]] | None
    ) = None,
    ready_attestation_builder: Callable[[ReadySnapshot], Path | None] | None = None,
) -> ReadySnapshot:
    return _publish_ready_snapshot_impl(
        staging_db,
        snapshot_dir,
        required_datasets=required_datasets,
        _profile_coverage_evidence=profile_coverage_evidence,
        _ready_manifest_builder=ready_manifest_builder,
        _ready_attestation_builder=ready_attestation_builder,
        publication_gate=_evaluate_ready_publication_fixture,
        fixture_compatibility=True,
    )


def describe_ready_snapshot_fixture(
    snapshot_dir: str | Path, snapshot_id: str
) -> ReadySnapshot:
    """Read a tests-only fixture without entering the product READY surface."""
    return _describe_fixture_snapshot(snapshot_dir, snapshot_id)


def latest_ready_snapshot_fixture(snapshot_dir: str | Path) -> ReadySnapshot:
    return _latest_fixture_snapshot(snapshot_dir)


def list_ready_snapshots_fixture(snapshot_dir: str | Path) -> list[ReadySnapshot]:
    return _list_fixture_snapshots(snapshot_dir)


def open_ready_snapshot_fixture(
    snapshot_dir: str | Path, snapshot_id: str | None = None
):
    return _open_fixture_snapshot(snapshot_dir, snapshot_id)


def publish_core_profile_ready_fixture(
    staging_db: str | Path,
    snapshot_dir: str | Path,
    *,
    profile_id: str,
    evidence_by_dataset: Mapping[str, Any] | None,
) -> ReadySnapshot:
    """Exercise the old core fixture gate without creating a signed READY."""
    if profile_id != CORE_PROFILE_ID:
        raise MassResearchDisabledError(
            f"unsupported governed research profile: {profile_id!r}"
        )
    profile = load_core_profile()
    if not profile_ready(profile, evidence_by_dataset):
        raise MassResearchDisabledError(
            "profile-bound READY evidence is incomplete, stale, unpinned, or not V3"
        )
    return publish_ready_snapshot_fixture(
        staging_db,
        snapshot_dir,
        required_datasets=profile.required_datasets,
    )
