"""Single READY publication policy — sole final PASS/FAIL gate.

Subsystems produce typed evidence only. ReadyPublicationPolicy alone decides.
The private runtime publisher must refuse READY transition without policy PASS.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from paper_runtime.coherence import CoherenceGateResult, check_ready_coherence


@dataclass(frozen=True)
class CoverageEvidence:
    """Typed coverage evidence — no PASS/FAIL decision of its own for READY."""

    governed_complete: int
    governed_total: int
    proof_digest: str | None = None
    status: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_item(self) -> "ReadyEvidenceItem":
        ok = (
            self.governed_total > 0
            and self.governed_complete == self.governed_total
            and (self.status is None or self.status == "COMPLETE")
        )
        return ReadyEvidenceItem(
            name="CoverageEvidence",
            passed=ok,
            reason=None
            if ok
            else f"COMPLETE {self.governed_complete}/{self.governed_total}",
            detail=dict(self.detail),
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
    quality_status: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    def to_item(self) -> "ReadyEvidenceItem":
        ok = self.b0_status == "PASS" and self.quality_status == "PASS"
        return ReadyEvidenceItem(
            name="QualityEvidence",
            passed=ok,
            reason=None if ok else f"b0={self.b0_status} quality={self.quality_status}",
            detail={
                "b0_status": self.b0_status,
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


def _collect_typed_evidence(
    conn: sqlite3.Connection,
    db_path: str | Path,
    required_datasets: Sequence[str],
    *,
    run_id: int | None = None,
    coverage_proof: dict[str, Any] | None = None,
    quality_status: str | None = None,
    raw_manifest_ok: bool | None = None,
    fixture_compatibility: bool,
) -> list[TypedReadyEvidence]:
    """Subsystems produce typed evidence only — no READY decision here."""
    required = tuple(required_datasets)
    evidence: list[TypedReadyEvidence] = []

    # Coverage counts from dataset_coverage when present.
    complete = 0
    total = len(required)
    try:
        rows = conn.execute(
            "SELECT dataset, status FROM dataset_coverage WHERE dataset IN ({})".format(
                ",".join("?" * len(required))
            ),
            required,
        ).fetchall()
        status_map = {str(r[0]): str(r[1]) for r in rows}
        complete = sum(1 for d in required if status_map.get(d) == "COMPLETE")
    except sqlite3.Error:
        complete = 0
    proof_status = None
    proof_digest = None
    if coverage_proof is not None:
        proof_status = str(coverage_proof.get("status") or "")
        proof_digest = (
            str(coverage_proof.get("proof_digest"))
            if coverage_proof.get("proof_digest")
            else None
        )
    evidence.append(
        CoverageEvidence(
            governed_complete=complete,
            governed_total=total,
            proof_digest=proof_digest,
            status=proof_status,
            detail={"required": list(required)},
        )
    )

    # Raw retention
    manifest_count = 0
    manifests_ok = False if raw_manifest_ok is None else bool(raw_manifest_ok)
    try:
        row = conn.execute("SELECT COUNT(*) FROM raw_retention_manifests").fetchone()
        manifest_count = int(row[0]) if row else 0
        if raw_manifest_ok is None:
            manifests_ok = manifest_count > 0
    except sqlite3.Error:
        if fixture_compatibility and raw_manifest_ok is None:
            manifests_ok = complete == total
    evidence.append(
        RawRetentionEvidence(manifests_ok=manifests_ok, manifest_count=manifest_count)
    )

    # Validation
    val_status = "UNKNOWN"
    if run_id is not None:
        try:
            counts = conn.execute(
                """
                SELECT COUNT(*), SUM(
                    CASE WHEN status NOT IN ('pass', 'PASS') THEN 1 ELSE 0 END
                ) FROM ingestion_validation WHERE run_id=?
                """,
                (run_id,),
            ).fetchone()
            total_validations = int(counts[0]) if counts else 0
            failures = int(counts[1] or 0) if counts else 0
            val_status = (
                "PASS"
                if total_validations >= len(required) and failures == 0
                else "FAIL"
            )
        except sqlite3.Error:
            val_status = "PASS" if fixture_compatibility else "UNKNOWN"
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
        nk_state = "READY" if fixture_compatibility else "UNKNOWN"
    evidence.append(NaturalKeyEvidence(state=nk_state))

    # Quality / B0
    b0 = "UNKNOWN"
    q = quality_status or ("PASS" if fixture_compatibility else "UNKNOWN")
    try:
        row = conn.execute(
            "SELECT status FROM ops_b0_status ORDER BY checked_at DESC LIMIT 1"
        ).fetchone()
        if row:
            b0 = str(row[0])
    except sqlite3.Error:
        b0 = "PASS" if fixture_compatibility else "UNKNOWN"
    if fixture_compatibility and b0 == "UNKNOWN":
        b0 = "PASS"
    evidence.append(QualityEvidence(b0_status=b0, quality_status=q))

    # Sync generation
    src_gen = 0
    sync_gen = 0
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(change_seq), 0) FROM ingestion_change_log"
        ).fetchone()
        src_gen = int(row[0]) if row else 0
    except sqlite3.Error:
        src_gen = 1 if fixture_compatibility and complete == total and complete > 0 else 0
    try:
        row = conn.execute(
            "SELECT last_applied_change_seq FROM sync_change_state "
            "WHERE feed='jquants_records'"
        ).fetchone()
        sync_gen = int(row[0]) if row else 0
    except sqlite3.Error:
        sync_gen = src_gen if fixture_compatibility else 0
    if fixture_compatibility and sync_gen <= 0:
        sync_gen = src_gen
    evidence.append(
        SyncGenerationEvidence(source_generation=src_gen, sync_generation=sync_gen)
    )

    return evidence


def collect_typed_evidence(
    conn: sqlite3.Connection,
    db_path: str | Path,
    required_datasets: Sequence[str],
    *,
    run_id: int | None = None,
    coverage_proof: dict[str, Any] | None = None,
    quality_status: str | None = None,
    raw_manifest_ok: bool | None = None,
) -> list[TypedReadyEvidence]:
    """Production evidence collection; missing ledgers are never compatible."""
    return _collect_typed_evidence(
        conn,
        db_path,
        required_datasets,
        run_id=run_id,
        coverage_proof=coverage_proof,
        quality_status=quality_status,
        raw_manifest_ok=raw_manifest_ok,
        fixture_compatibility=False,
    )


class ReadyPublicationPolicy:
    """Sole READY eligibility decision. Fail closed on any failed evidence item."""

    def evaluate(
        self,
        conn: sqlite3.Connection,
        db_path: str | Path,
        required_datasets: Sequence[str],
        *,
        run_id: int | None = None,
        coverage_proof: dict[str, Any] | None = None,
        quality_status: str | None = None,
        raw_manifest_ok: bool | None = None,
        typed_evidence: Sequence[TypedReadyEvidence] | None = None,
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
            typed_evidence
            if typed_evidence is not None
            else collect_typed_evidence(
                conn,
                db_path,
                required,
                run_id=run_id,
                coverage_proof=coverage_proof,
                quality_status=quality_status,
                raw_manifest_ok=raw_manifest_ok,
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
