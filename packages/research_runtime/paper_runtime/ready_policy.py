"""Single READY publication policy — sole final PASS/FAIL gate.

Subsystems produce typed evidence only. ReadyPublicationPolicy alone decides.
The private runtime publisher must refuse READY transition without policy PASS.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from paper_runtime.coherence import CoherenceGateResult, check_ready_coherence
from paper_runtime.snapshot_coverage_proof import (
    CoverageProofVerificationError,
    require_persisted_coverage_proof,
)


@dataclass(frozen=True, slots=True)
class CoverageEvidence:
    """Self-verifying Coverage evidence; stored values are never authority."""

    _conn: sqlite3.Connection = field(repr=False)
    _required_datasets: tuple[str, ...]
    _proof_id: object = field(repr=False)

    def to_item(self) -> "ReadyEvidenceItem":
        try:
            verified = require_persisted_coverage_proof(
                self._conn,
                self._required_datasets,
                self._proof_id,
            )
        except CoverageProofVerificationError as exc:
            return ReadyEvidenceItem(
                name="CoverageEvidence",
                passed=False,
                reason=str(exc),
                detail={"status": "UNKNOWN", "proof_id": "MISSING"},
            )
        proof = verified.proof
        detail = {
            "proof_id": verified.proof_id,
            "status": proof.get("status"),
            "proof_digest": proof.get("proof_digest"),
            "governed_complete": proof.get("dataset_count"),
            "governed_total": proof.get("dataset_count"),
            "required_datasets": list(verified.required_datasets),
            "source_generation": verified.source_generation,
            "applied_generation": verified.applied_generation,
        }
        governed_complete = detail.get("governed_complete")
        governed_total = detail.get("governed_total")
        ok = (
            isinstance(governed_total, int)
            and governed_total > 0
            and governed_complete == governed_total
            and detail.get("status") == "COMPLETE"
        )
        return ReadyEvidenceItem(
            name="CoverageEvidence",
            passed=ok,
            reason=None if ok else "Verified Coverage proof is not COMPLETE",
            detail=detail,
        )


@dataclass(frozen=True)
class RawRetentionEvidence:
    manifests_ok: bool
    manifest_count: int = 0
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_item(self) -> "ReadyEvidenceItem":
        return ReadyEvidenceItem(
            name="RawRetentionEvidence",
            passed=self.manifests_ok,
            reason=None if self.manifests_ok else "raw retention incomplete",
            detail={"manifest_count": self.manifest_count, **dict(self.detail)},
        )


@dataclass(frozen=True)
class ValidationEvidence:
    status: str
    run_id: int | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_item(self) -> "ReadyEvidenceItem":
        ok = self.status == "PASS"
        return ReadyEvidenceItem(
            name="ValidationEvidence",
            passed=ok,
            reason=None if ok else f"validation={self.status}",
            detail=dict(self.detail),
        )


@dataclass(frozen=True)
class NaturalKeyEvidence:
    state: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_item(self) -> "ReadyEvidenceItem":
        ok = self.state == "READY"
        return ReadyEvidenceItem(
            name="NaturalKeyEvidence",
            passed=ok,
            reason=None if ok else f"natural_key={self.state}",
            detail=dict(self.detail),
        )


@dataclass(frozen=True)
class QualityEvidence:
    b0_status: str
    b4_status: str
    quality_status: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_item(self) -> "ReadyEvidenceItem":
        ok = (
            self.b0_status == "PASS"
            and self.b4_status == "PASS"
            and self.quality_status == "PASS"
        )
        return ReadyEvidenceItem(
            name="QualityEvidence",
            passed=ok,
            reason=(
                None
                if ok
                else (
                    f"b0={self.b0_status} b4={self.b4_status} "
                    f"quality={self.quality_status}"
                )
            ),
            detail={
                "b0_status": self.b0_status,
                "b4_status": self.b4_status,
                "quality_status": self.quality_status,
                **dict(self.detail),
            },
        )


@dataclass(frozen=True)
class SyncGenerationEvidence:
    source_generation: int
    sync_generation: int
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_item(self) -> "ReadyEvidenceItem":
        ok = (
            self.source_generation > 0
            and self.sync_generation > 0
            and self.source_generation == self.sync_generation
        )
        return ReadyEvidenceItem(
            name="SyncGenerationEvidence",
            passed=ok,
            reason=None
            if ok
            else (
                f"source_gen={self.source_generation} "
                f"sync_gen={self.sync_generation}"
            ),
            detail={
                "source_generation": self.source_generation,
                "applied_sync_generation": self.sync_generation,
                **dict(self.detail),
            },
        )


class TypedReadyEvidence(Protocol):
    def to_item(self) -> "ReadyEvidenceItem":
        ...


@dataclass(frozen=True)
class ReadyEvidenceItem:
    name: str
    passed: bool
    reason: str | None = None
    detail: dict[str, Any] | None = None


@dataclass
class ReadyEvidenceBundle:
    """All evidence required for READY publication."""

    items: list[ReadyEvidenceItem] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.items) and all(i.passed for i in self.items)

    def failures(self) -> list[ReadyEvidenceItem]:
        return [i for i in self.items if not i.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "items": [
                {
                    "name": i.name,
                    "passed": i.passed,
                    "reason": i.reason,
                    "detail": i.detail or {},
                }
                for i in self.items
            ],
        }


def collect_typed_evidence(
    conn: sqlite3.Connection,
    db_path: str | Path,
    required_datasets: Sequence[str],
    *,
    run_id: int | None = None,
    build_id: str | None = None,
    coverage_proof_id: object,
) -> list[TypedReadyEvidence]:
    """Collect production evidence; absent ledgers never receive substitutes."""
    required = tuple(required_datasets)
    evidence: list[TypedReadyEvidence] = []

    evidence.append(
        CoverageEvidence(
            _conn=conn,
            _required_datasets=required,
            _proof_id=coverage_proof_id,
        )
    )

    # Raw retention
    manifest_count = 0
    manifests_ok = False
    try:
        if run_id is not None:
            placeholders = ",".join("?" for _ in required)
            rows = conn.execute(
                "SELECT dataset, completeness FROM raw_retention_manifests "
                f"WHERE run_id=? AND dataset IN ({placeholders})",
                (run_id, *required),
            ).fetchall()
            status_by_dataset: dict[str, str] = {}
            duplicate_dataset = False
            for row in rows:
                dataset = str(row[0])
                if dataset in status_by_dataset:
                    duplicate_dataset = True
                status_by_dataset[dataset] = str(row[1])
            manifest_count = len(rows)
            manifests_ok = (
                not duplicate_dataset
                and manifest_count == len(required)
                and set(status_by_dataset) == set(required)
                and all(
                    status_by_dataset.get(dataset) in ("ACQUIRED", "COMPLETE")
                    for dataset in required
                )
            )
    except sqlite3.Error:
        manifests_ok = False
    evidence.append(
        RawRetentionEvidence(manifests_ok=manifests_ok, manifest_count=manifest_count)
    )

    # Validation
    val_status = "UNKNOWN"
    if run_id is not None:
        try:
            placeholders = ",".join("?" for _ in required)
            rows = conn.execute(
                "SELECT dataset, status FROM ingestion_validation "
                f"WHERE run_id=? AND dataset IN ({placeholders})",
                (run_id, *required),
            ).fetchall()
            validation_by_dataset: dict[str, str] = {}
            duplicate_dataset = False
            for row in rows:
                dataset = str(row[0])
                if dataset in validation_by_dataset:
                    duplicate_dataset = True
                validation_by_dataset[dataset] = str(row[1])
            val_status = (
                "PASS"
                if not duplicate_dataset
                and set(validation_by_dataset) == set(required)
                and all(
                    validation_by_dataset[dataset] in ("pass", "PASS")
                    for dataset in required
                )
                else "FAIL"
            )
        except sqlite3.Error:
            val_status = "UNKNOWN"
    evidence.append(ValidationEvidence(status=val_status, run_id=run_id))

    # Natural keys
    nk_state = "UNKNOWN"
    try:
        row = conn.execute(
            "SELECT state FROM natural_key_migrations ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row:
            nk_state = str(row[0])
    except sqlite3.Error:
        nk_state = "UNKNOWN"
    evidence.append(NaturalKeyEvidence(state=nk_state))

    # Quality / B0 / B4.  All three observations come from the same exact
    # build row; a global/latest Ops row cannot authorize a different build.
    b0 = "UNKNOWN"
    b4 = "UNKNOWN"
    q = "UNKNOWN"
    if build_id is not None:
        try:
            rows = conn.execute(
                "SELECT status, results_json FROM snapshot_quality_results "
                "WHERE build_id=?",
                (build_id,),
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                q = str(row[0])
                result_rows = json.loads(str(row[1]))
                if not isinstance(result_rows, list):
                    raise ValueError("quality results must be a list")

                def exact_check_status(check_id: str) -> str:
                    checks = [
                        item
                        for item in result_rows
                        if isinstance(item, Mapping)
                        and item.get("check_id") == check_id
                    ]
                    if not checks:
                        return "UNKNOWN"
                    return (
                        "PASS"
                        if all(item.get("status") == "pass" for item in checks)
                        else "FAIL"
                    )

                b0 = exact_check_status("B0")
                b4 = exact_check_status("B4")
        except sqlite3.Error:
            q = "UNKNOWN"
        except (TypeError, ValueError, json.JSONDecodeError):
            b0 = "UNKNOWN"
            b4 = "UNKNOWN"
            q = "UNKNOWN"
    evidence.append(
        QualityEvidence(b0_status=b0, b4_status=b4, quality_status=q)
    )

    # Sync generation
    src_gen = 0
    sync_gen = 0
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(change_seq), 0) FROM ingestion_change_log"
        ).fetchone()
        src_gen = int(row[0]) if row else 0
    except sqlite3.Error:
        src_gen = 0
    try:
        row = conn.execute(
            "SELECT last_applied_change_seq FROM sync_change_state "
            "WHERE feed='jquants_records'"
        ).fetchone()
        sync_gen = int(row[0]) if row else 0
    except sqlite3.Error:
        sync_gen = 0
    evidence.append(
        SyncGenerationEvidence(source_generation=src_gen, sync_generation=sync_gen)
    )

    return evidence


class ReadyPublicationPolicy:
    """Sole READY eligibility decision. Fail closed on any failed evidence item."""

    def evaluate(
        self,
        conn: sqlite3.Connection,
        db_path: str | Path,
        required_datasets: Sequence[str],
        *,
        run_id: int | None = None,
        build_id: str | None = None,
        coverage_proof_id: object,
    ) -> ReadyEvidenceBundle:
        required = tuple(required_datasets)
        bundle = ReadyEvidenceBundle()

        # Coherence suite remains evidence producers (gates → items).
        coherence = check_ready_coherence(
            conn, db_path, required, run_id=run_id
        )
        for gate in coherence:
            bundle.items.append(
                ReadyEvidenceItem(
                    name=f"coherence.{gate.gate_name}",
                    passed=gate.passed,
                    reason=gate.reason,
                    detail=dict(gate.detail or {}),
                )
            )

        evidence = list(
            collect_typed_evidence(
                conn,
                db_path,
                required,
                run_id=run_id,
                build_id=build_id,
                coverage_proof_id=coverage_proof_id,
            )
        )
        for ev in evidence:
            bundle.items.append(ev.to_item())

        return bundle

    def require_pass(self, bundle: ReadyEvidenceBundle) -> ReadyEvidenceBundle:
        """Hard gate used by the runtime publisher — no READY without PASS."""
        if not bundle.passed:
            detail = "; ".join(f"{i.name}: {i.reason}" for i in bundle.failures())
            raise ReadyPolicyRejected(f"READY publication policy failed: {detail}")
        return bundle


class ReadyPolicyRejected(RuntimeError):
    """Raised when ReadyPublicationPolicy does not PASS."""


__all__ = [
    "CoverageEvidence",
    "NaturalKeyEvidence",
    "QualityEvidence",
    "RawRetentionEvidence",
    "ReadyEvidenceBundle",
    "ReadyEvidenceItem",
    "ReadyPolicyRejected",
    "ReadyPublicationPolicy",
    "SyncGenerationEvidence",
    "ValidationEvidence",
    "collect_typed_evidence",
]
