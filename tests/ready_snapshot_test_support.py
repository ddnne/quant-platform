"""Test-only entry points for legacy mutable/sparse READY fixtures.

The product publisher has no fixture switch.  These helpers deliberately live
under ``tests`` and call only the private runtime implementation so synthetic
SQLite fixtures cannot become a production publication authority.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from paper_runtime.snapshot import (
    ReadySnapshot,
    SnapshotRejected,
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
    _collect_typed_evidence,
)
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
    conn.commit()
    coverage_proof_id = persist_coverage_proof(conn, required)
    bundle = ReadyEvidenceBundle()
    for gate in check_ready_coherence(
        conn, staging_path, required, run_id=run_id
    ):
        natural_key_compat = (
            gate.gate_name == "natural_key_migration_ready" and not gate.passed
        )
        bundle.items.append(
            ReadyEvidenceItem(
                name=f"coherence.{gate.gate_name}",
                passed=True if natural_key_compat else gate.passed,
                reason=(
                    "tests-only fixture compatibility"
                    if natural_key_compat
                    else gate.reason
                ),
                detail={
                    **(gate.detail or {}),
                    **(
                        {"fixture_compatibility": True}
                        if natural_key_compat
                        else {}
                    ),
                },
            )
        )
    for evidence in _collect_typed_evidence(
        conn,
        staging_path,
        required,
        run_id=run_id,
        coverage_proof_id=coverage_proof_id,
        quality_status="FAIL" if failures else "PASS",
        raw_manifest_ok=True,
        fixture_compatibility=True,
    ):
        bundle.items.append(evidence.to_item())
    if not bundle.passed:
        detail = "; ".join(
            f"{item.name}: {item.reason}" for item in bundle.failures()
        )
        raise SnapshotRejected(f"READY publication policy failed: {detail}")
    return (*result, coverage_proof_id, bundle.to_dict())


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
