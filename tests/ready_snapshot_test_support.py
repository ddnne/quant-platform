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
    CoverageEvidence,
    ReadyEvidenceBundle,
    ReadyEvidenceItem,
    collect_typed_evidence,
)
from paper_runtime.snapshot_persist import _persist_synced_policy
from data_contracts.coverage import (
    coverage_policy_binding,
    coverage_policy_set_binding,
)
from storage.coverage_ledger import refresh_coverage_ledger
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


def _fixture_coverage_proof(
    conn: sqlite3.Connection,
    required: tuple[str, ...],
) -> dict[str, Any]:
    """Observed-inventory marker with no production READY authority."""
    placeholders = ",".join("?" for _ in required)
    rows = conn.execute(
        "SELECT source,dataset,segment_id,policy_version,receipt_run_id "
        "FROM coverage_segments "
        f"WHERE dataset IN ({placeholders}) "
        "ORDER BY dataset,source,segment_id",
        required,
    ).fetchall()
    current = [
        row for row in rows
        if row["policy_version"]
        == coverage_policy_binding(str(row["dataset"]))["policy_version"]
    ]
    summaries = []
    for dataset in required:
        segments = [row for row in current if row["dataset"] == dataset]
        summaries.append({
            "dataset": dataset,
            **dict(coverage_policy_binding(dataset)),
            "required_segments": len(segments),
            "complete_segments": len(segments),
            "first_segment": str(segments[0]["segment_id"]),
            "last_segment": str(segments[-1]["segment_id"]),
        })
    policy_set = coverage_policy_set_binding(list(required))
    receipt_markers = [
        {
            "source": str(row["source"]),
            "dataset": str(row["dataset"]),
            "segment_id": str(row["segment_id"]),
            "receipt_run_id": row["receipt_run_id"],
        }
        for row in current
    ]
    return {
        "format": "coverage-proof/v1",
        "status": "COMPLETE",
        "policy_version": policy_set["policy_version"],
        "policy_digest": policy_set["policy_digest"],
        "dataset_count": len(required),
        "segment_count": len(current),
        "receipt_count": len(current),
        "proof_digest": _canonical_digest(receipt_markers),
        "datasets": summaries,
        "fixture_only": True,
    }


def _refresh_fixture_coverage(
    conn: sqlite3.Connection,
    staging_path: Path,
    *,
    required: tuple[str, ...],
    today: str,
    build_id: str,
) -> list[dict[str, Any]]:
    """Mint observed-inventory COMPLETE only inside tests/FIXTURE scope.

    Product refresh remains C10 fail-closed.  This adapter first lets it
    evaluate every segment and signed receipt, then restores the legacy fixture
    aggregate only when the product-computed status was COMPLETE before the
    missing transition authority blocked it.  Product READY readers reject the
    resulting FIXTURE publication marker.
    """
    rows = refresh_coverage_ledger(
        conn,
        staging_path,
        datasets=required,
        today=today,
        index_text=None,
        _publication_build_id=build_id,
    )
    for row in rows:
        detail = json.loads(str(row["detail_json"]))
        gate = (detail.get("coverage_v2") or {}).get(
            "aggregate_complete_gate"
        ) or {}
        if gate.get("computed_status") != "COMPLETE":
            continue
        dataset = str(row["dataset"])
        policy_version = str(coverage_policy_binding(dataset)["policy_version"])
        segment_statuses = conn.execute(
            "SELECT status,COUNT(*) FROM coverage_segments "
            "WHERE dataset=? AND policy_version=? GROUP BY status",
            (dataset, policy_version),
        ).fetchall()
        counts = {str(item[0]): int(item[1]) for item in segment_statuses}
        if not counts or set(counts) != {"COMPLETE"}:
            continue
        fixture_detail = dict(detail.get("coverage_v2") or {})
        fixture_detail["fixture_complete_basis"] = {
            "publication_scope": "FIXTURE",
            "required_segments": counts["COMPLETE"],
            "product_ready_eligible": False,
        }
        detail["coverage_v2"] = fixture_detail
        row["status"] = "COMPLETE"
        row["detail_json"] = json.dumps(
            detail,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        conn.execute(
            "UPDATE dataset_coverage SET status='COMPLETE',detail_json=? "
            "WHERE dataset=? AND policy_version=?",
            (row["detail_json"], dataset, policy_version),
        )
    conn.commit()
    return rows


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
        _fixture_coverage_refresh=_refresh_fixture_coverage,
    )
    (
        run_id,
        _run_detail,
        _validations,
        _coverage_rows,
        _quality_summary,
        failures,
        _raw_manifests,
        _untrusted_product_coverage_proof,
    ) = result
    coverage_proof = _fixture_coverage_proof(conn, required)
    result = (*result[:-1], coverage_proof)
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
    coverage_proof_id = _canonical_digest({
        "format": "fixture-coverage-proof-id/v1",
        "build_id": build_id,
        "coverage_proof": coverage_proof,
    })
    bundle = ReadyEvidenceBundle()
    bundle.items.append(ReadyEvidenceItem(
        name="CoverageEvidence",
        passed=True,
        reason=None,
        detail={
            "status": "COMPLETE",
            "proof_id": coverage_proof_id,
            "fixture_only": True,
        },
    ))
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
        if isinstance(evidence, CoverageEvidence):
            continue
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
