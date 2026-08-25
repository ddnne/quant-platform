"""Publication policy for paper data snapshots.

READY stays fail-closed. Empty DB and PARTIAL coverage must not publish READY.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cf_platform.ingest_premium.coverage import run_coverage, summarize
from data_contracts.loader import all_contracts
from paper_runtime.snapshot_coverage_proof import _coverage_proof
from qp_paths import repo_root
from storage.coverage_ledger import refresh_coverage_ledger

READY_MANIFEST_SCHEMA_REL = Path("specs") / "ready" / "ready_manifest.schema.json"
READY_MANIFEST_FORMAT = "ready-manifest/v1"


def ready_manifest_schema_path() -> Path:
    return repo_root() / READY_MANIFEST_SCHEMA_REL


def load_ready_manifest_schema() -> dict[str, Any]:
    """Load the single ReadyManifest schema. No second gate document."""
    path = ready_manifest_schema_path()
    if not path.is_file():
        from paper_runtime.snapshot import SnapshotRejected

        raise SnapshotRejected(f"ReadyManifest schema missing: {path}")
    schema = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(schema, dict) or schema.get("$id") != READY_MANIFEST_FORMAT:
        from paper_runtime.snapshot import SnapshotRejected

        raise SnapshotRejected("ReadyManifest schema $id must be ready-manifest/v1")
    if schema.get("additionalProperties") is not False:
        from paper_runtime.snapshot import SnapshotRejected

        raise SnapshotRejected("ReadyManifest schema must set additionalProperties false")
    return schema


READY_MANIFEST_SCHEMA: dict[str, Any] = load_ready_manifest_schema()

_JQUANTS_DATASETS = frozenset(
    contract.dataset_id for contract in all_contracts()
)


def _raw_manifests_for(
    conn: sqlite3.Connection, run_id: int, required: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """Require one COMPLETE R2 raw-retention attestation per dataset."""
    from paper_runtime.snapshot import SnapshotRejected

    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='raw_retention_manifests'"
    ).fetchone()
    if table is None:
        raise SnapshotRejected("raw retention manifest ledger is missing")
    placeholders = ",".join("?" for _ in required)
    rows = conn.execute(
        "SELECT dataset, run_id, manifest_key, page_count, row_count, "
        "raw_bytes, data_digest, completeness, created_at "
        "FROM raw_retention_manifests WHERE run_id=? "
        f"AND dataset IN ({placeholders}) ORDER BY dataset",
        (run_id, *required),
    ).fetchall()
    manifests = {str(row["dataset"]): dict(row) for row in rows}
    missing = sorted(set(required) - set(manifests))
    failed = sorted(
        dataset for dataset, row in manifests.items()
        if row["completeness"] != "COMPLETE"
    )
    if missing or failed:
        raise SnapshotRejected(
            f"raw retention incomplete: missing={missing}, failed={failed}"
        )
    return manifests


def _transition_policy(
    conn: sqlite3.Connection,
    state: str,
    *,
    error: str | None = None,
    snapshot_id: str | None = None,
    readable: bool = False,
) -> None:
    from paper_runtime.snapshot import SNAPSHOT_STATES

    if state not in SNAPSHOT_STATES:
        raise ValueError(f"invalid snapshot state: {state}")
    conn.execute(
        "UPDATE local_snapshot_policy SET publication_state=?, "
        "snapshot_ready=?, last_error=?, active_snapshot_id=? "
        "WHERE singleton=1",
        (state, int(readable), error, snapshot_id),
    )
    conn.commit()


def _evaluate_publication_gate_impl(
    conn: sqlite3.Connection,
    staging_path: Path,
    *,
    build_id: str,
    required: tuple[str, ...],
    fixture_compatibility: bool,
) -> tuple[
    int, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]],
    dict[str, int], list[dict[str, Any]], dict[str, dict[str, Any]],
    dict[str, Any],
]:
    """Strict B0 + Phase 3.5 daily checks + governed Coverage ledger."""
    from paper_runtime.snapshot import (
        QUALITY_POLICY_VERSION,
        SnapshotRejected,
        _latest_complete_run,
    )

    jquants_required = tuple(
        dataset for dataset in required if dataset in _JQUANTS_DATASETS
    )
    if not jquants_required:
        raise SnapshotRejected(
            "READY publication requires the governed J-Quants foundation"
        )
    run_id, run_detail, validations = _latest_complete_run(
        conn, jquants_required
    )
    raw_manifests = _raw_manifests_for(conn, run_id, jquants_required)
    today = datetime.now(timezone.utc).date().isoformat()
    # No year-index HTML on the READY path. Explicit None is fail-closed empty OTC.
    coverage_rows = refresh_coverage_ledger(
        conn, staging_path, datasets=required, today=today, index_text=None
    )
    quality_results = run_coverage(
        staging_path,
        tier="daily",
        datasets=jquants_required,
        today=today,
        workers=1,
        strict_live_gates=True,
    )
    quality_summary = summarize(quality_results)
    failures = [
        result.as_log_dict() for result in quality_results
        if result.status == "fail"
    ]
    if fixture_compatibility:
        # Explicit test-only compatibility: structural READY proofs and B4
        # still run, but sparse synthetic fixtures may omit unrelated daily
        # matrix observations such as K3.
        failures = [
            item for item in failures if item.get("check_id") == "B4"
        ]
    incomplete = [
        {
            "dataset": row["dataset"],
            "status": row["status"],
            "observed_start": row["observed_start"],
            "history_target_start": row["history_target_start"],
        }
        for row in coverage_rows
        if row["governance_tier"] == "governed"
        and row["status"] != "COMPLETE"
    ]
    coverage_proof: dict[str, Any] | None = None
    proof_failure: str | None = None
    try:
        coverage_proof = _coverage_proof(conn, required, coverage_rows)
    except SnapshotRejected as exc:
        proof_failure = str(exc)
    evaluated_at = datetime.now(timezone.utc).isoformat()
    passed = not failures and not incomplete and proof_failure is None
    conn.execute(
        """
        INSERT INTO snapshot_quality_results
            (build_id, status, policy_version, evaluated_at, summary_json,
             results_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(build_id) DO UPDATE SET
            status=excluded.status,
            policy_version=excluded.policy_version,
            evaluated_at=excluded.evaluated_at,
            summary_json=excluded.summary_json,
            results_json=excluded.results_json
        """,
        (
            build_id, "PASS" if passed else "FAIL", QUALITY_POLICY_VERSION,
            evaluated_at,
            json.dumps(quality_summary, sort_keys=True, separators=(",", ":")),
            json.dumps(
                [result.as_log_dict() for result in quality_results],
                sort_keys=True, separators=(",", ":"),
            ),
        ),
    )
    conn.commit()
    if not passed:
        parts = []
        if failures:
            parts.append(
                "quality failures="
                + repr([(item["check_id"], item["dataset"]) for item in failures])
            )
        if incomplete:
            parts.append(
                "coverage not COMPLETE="
                + repr([(item["dataset"], item["status"]) for item in incomplete])
            )
        if proof_failure is not None:
            parts.append(proof_failure)
        raise SnapshotRejected("; ".join(parts))
    if coverage_proof is None:  # pragma: no cover - guarded by passed
        raise SnapshotRejected("governed Coverage proof was not produced")
    return (
        run_id, run_detail, validations, coverage_rows, quality_summary,
        failures,
        raw_manifests,
        coverage_proof,
    )


def _evaluate_publication_gate(
    conn: sqlite3.Connection,
    staging_path: Path,
    *,
    build_id: str,
    required: tuple[str, ...],
) -> tuple[
    int, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]],
    dict[str, int], list[dict[str, Any]], dict[str, dict[str, Any]],
    dict[str, Any],
]:
    """Production B0/Coverage gate; compatibility cannot be selected."""
    return _evaluate_publication_gate_impl(
        conn,
        staging_path,
        build_id=build_id,
        required=required,
        fixture_compatibility=False,
    )


def evaluate_ready_publication(
    conn: sqlite3.Connection,
    staging_path: Path,
    *,
    build_id: str,
    required: tuple[str, ...],
) -> tuple[
    int, dict[str, Any], list[dict[str, Any]], list[dict[str, Any]],
    dict[str, int], list[dict[str, Any]], dict[str, dict[str, Any]],
    dict[str, Any], dict[str, Any],
]:
    """Single READY publication gate. Coverage/B0 plus ReadyPublicationPolicy."""
    from paper_runtime.ready_policy import ReadyPublicationPolicy
    from paper_runtime.snapshot import SnapshotRejected

    # Bind the single ReadyManifest schema so publish cannot drift.
    if READY_MANIFEST_SCHEMA.get("$id") != READY_MANIFEST_FORMAT:
        raise SnapshotRejected("ReadyManifest schema is not the publish gate")

    result = _evaluate_publication_gate(
        conn,
        staging_path,
        build_id=build_id,
        required=required,
    )
    (
        run_id, _run_detail, _validations, _coverage_rows, _quality_summary,
        failures, _raw_manifests, coverage_proof,
    ) = result
    policy = ReadyPublicationPolicy()
    bundle = policy.evaluate(
        conn,
        staging_path,
        required,
        run_id=run_id,
        coverage_proof=coverage_proof if isinstance(coverage_proof, dict) else None,
        quality_status="FAIL" if failures else "PASS",
        raw_manifest_ok=True,
    )
    if not bundle.passed:
        detail = "; ".join(f"{i.name}: {i.reason}" for i in bundle.failures())
        raise SnapshotRejected(f"READY publication policy failed: {detail}")
    return (*result, bundle.to_dict())
