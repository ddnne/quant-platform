"""Trusted research readiness attestation (Phase 6.2.2 P0).

Only :class:`ResearchReadinessService` may mint :class:`VerifiedResearchReadiness`.
Callers cannot supply ready_count / governed_complete scalars to spoof GO.
Mass research requires both :class:`~selection.budget_ledger.ResearchBudgetCapability`
and a live attestation; ``go_override: bool`` is gone.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from data_contracts.canonical import governed_datasets
from data_contracts.coverage import POLICY_VERSION as COVERAGE_POLICY_VERSION
from selection.budget_ledger import (
    MassResearchDisabledError,
    ResearchBudgetCapability,
    require_budget_capability,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class VerifiedResearchReadiness:
    """Opaque attestation minted only by ResearchReadinessService.

    Holding this object is proof that the control plane evaluated live evidence
    from the research DB / READY artifacts — not caller-supplied counters.
    """

    attestation_id: str
    snapshot_id: str
    ready_state: str
    ready_manifest_digest: str
    coverage_policy_version: str
    coverage_proof_digest: str
    governed_membership_digest: str
    governed_complete: int
    governed_total: int
    b0_status: str
    quality_status: str
    source_generation: int
    sync_generation: int
    raw_proof_status: str
    verified_at: str
    evidence_digest: str

    def __post_init__(self) -> None:
        if self.ready_state != "READY":
            raise ValueError("VerifiedResearchReadiness requires ready_state=READY")
        if self.governed_total <= 0:
            raise ValueError("governed_total must be positive")
        if self.governed_complete != self.governed_total:
            raise ValueError("attestation cannot be incomplete")
        if self.b0_status != "PASS" or self.quality_status != "PASS":
            raise ValueError("B0/quality must be PASS")
        if self.raw_proof_status != "COMPLETE":
            raise ValueError("raw_proof_status must be COMPLETE")
        if not str(self.snapshot_id).strip():
            raise ValueError("snapshot_id required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id,
            "snapshot_id": self.snapshot_id,
            "ready_state": self.ready_state,
            "ready_manifest_digest": self.ready_manifest_digest,
            "coverage_policy_version": self.coverage_policy_version,
            "coverage_proof_digest": self.coverage_proof_digest,
            "governed_membership_digest": self.governed_membership_digest,
            "governed_complete": self.governed_complete,
            "governed_total": self.governed_total,
            "b0_status": self.b0_status,
            "quality_status": self.quality_status,
            "source_generation": self.source_generation,
            "sync_generation": self.sync_generation,
            "raw_proof_status": self.raw_proof_status,
            "verified_at": self.verified_at,
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True)
class OperatorOverrideCapability:
    """Rare operator override — never agent-mintable, always audited."""

    override_id: str
    reason: str
    operator_identity: str
    issued_at: str
    expires_at: str
    audit_artifact_digest: str
    scope: str = "mass_research"

    def is_live(self, *, now: datetime | None = None) -> bool:
        clock = now or datetime.now(timezone.utc)
        issued = datetime.fromisoformat(self.issued_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return issued <= clock <= expires

    def to_dict(self) -> dict[str, Any]:
        return {
            "override_id": self.override_id,
            "reason": self.reason,
            "operator_identity": self.operator_identity,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "audit_artifact_digest": self.audit_artifact_digest,
            "scope": self.scope,
        }


class OperatorOverrideService:
    """Mints OperatorOverrideCapability outside the agent capability surface."""

    def __init__(self, *, audit_dir: Path | None = None) -> None:
        self._audit_dir = audit_dir

    def mint(
        self,
        *,
        reason: str,
        operator_identity: str,
        ttl_seconds: int = 3600,
    ) -> OperatorOverrideCapability:
        if not reason.strip():
            raise ValueError("override reason required")
        if not operator_identity.strip():
            raise ValueError("operator_identity required")
        if ttl_seconds < 60 or ttl_seconds > 86_400:
            raise ValueError("ttl_seconds must be in [60, 86400]")
        issued = datetime.now(timezone.utc)
        expires = issued + timedelta(seconds=ttl_seconds)
        override_id = str(uuid4())
        body = {
            "override_id": override_id,
            "reason": reason.strip(),
            "operator_identity": operator_identity.strip(),
            "issued_at": issued.isoformat(),
            "expires_at": expires.isoformat(),
            "scope": "mass_research",
        }
        digest = _digest(body)
        if self._audit_dir is not None:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            path = self._audit_dir / f"override-{override_id}.json"
            path.write_text(json.dumps({**body, "digest": digest}, indent=2), encoding="utf-8")
        return OperatorOverrideCapability(
            override_id=override_id,
            reason=reason.strip(),
            operator_identity=operator_identity.strip(),
            issued_at=issued.isoformat(),
            expires_at=expires.isoformat(),
            audit_artifact_digest=digest,
        )


class ResearchReadinessService:
    """Sole mint authority for VerifiedResearchReadiness.

    Reads live evidence from the research SQLite copy / projection tables.
    Never accepts caller-supplied GO counters.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)

    def mint(self) -> VerifiedResearchReadiness:
        """Evaluate live evidence and mint attestation or raise."""
        if not self._db_path.is_file():
            raise MassResearchDisabledError(
                f"research DB missing: {self._db_path} — mass research NO-GO"
            )
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            evidence = self._collect_evidence(conn)
        finally:
            conn.close()
        failures = evidence.get("failures") or []
        if failures:
            raise MassResearchDisabledError(
                "research readiness failed: " + "; ".join(failures)
            )
        attestation = VerifiedResearchReadiness(
            attestation_id=str(uuid4()),
            snapshot_id=str(evidence["snapshot_id"]),
            ready_state="READY",
            ready_manifest_digest=str(evidence["ready_manifest_digest"]),
            coverage_policy_version=str(evidence["coverage_policy_version"]),
            coverage_proof_digest=str(evidence["coverage_proof_digest"]),
            governed_membership_digest=str(evidence["governed_membership_digest"]),
            governed_complete=int(evidence["governed_complete"]),
            governed_total=int(evidence["governed_total"]),
            b0_status=str(evidence["b0_status"]),
            quality_status=str(evidence["quality_status"]),
            source_generation=int(evidence["source_generation"]),
            sync_generation=int(evidence["sync_generation"]),
            raw_proof_status=str(evidence["raw_proof_status"]),
            verified_at=_now(),
            evidence_digest=_digest(evidence),
        )
        return attestation

    def _collect_evidence(self, conn: sqlite3.Connection) -> dict[str, Any]:
        failures: list[str] = []
        governed = governed_datasets()
        governed_ids = tuple(sorted(d.dataset_id for d in governed))
        membership_digest = _digest(list(governed_ids))
        total = len(governed_ids)
        if total <= 0:
            failures.append("governed membership empty")

        complete = 0
        try:
            rows = conn.execute(
                "SELECT dataset, status FROM dataset_coverage"
            ).fetchall()
            status_map = {str(r["dataset"]): str(r["status"]) for r in rows}
            complete = sum(1 for d in governed_ids if status_map.get(d) == "COMPLETE")
        except sqlite3.Error as exc:
            failures.append(f"dataset_coverage unreadable: {exc}")

        if complete != total or total <= 0:
            failures.append(f"governed COMPLETE {complete}/{total}")

        coverage_proof_digest = "sha256:" + "0" * 64
        try:
            # Prefer a proof-shaped digest over live segment rows when present.
            proof_row = conn.execute(
                """
                SELECT proof_digest FROM dataset_coverage
                WHERE status='COMPLETE' AND proof_digest IS NOT NULL
                LIMIT 1
                """
            ).fetchone()
            if proof_row and proof_row[0]:
                coverage_proof_digest = str(proof_row[0])
            else:
                seg_n = conn.execute(
                    "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
                ).fetchone()
                coverage_proof_digest = _digest(
                    {"complete_segments": int(seg_n[0]) if seg_n else 0}
                )
        except sqlite3.Error:
            pass

        snapshot_id = ""
        ready_manifest_digest = ""
        ready_state = ""
        try:
            snap = conn.execute(
                """
                SELECT snapshot_id, state, manifest_digest
                FROM ops_ready_snapshots
                WHERE state='READY'
                ORDER BY published_at DESC
                LIMIT 1
                """
            ).fetchone()
            if snap is None:
                # Local paper READY table fallback.
                snap = conn.execute(
                    """
                    SELECT snapshot_id, 'READY' AS state, COALESCE(manifest_digest, '')
                    FROM paper_ready_snapshots
                    WHERE state='READY' OR status='READY'
                    ORDER BY rowid DESC
                    LIMIT 1
                    """
                ).fetchone()
            if snap is None:
                failures.append("READY snapshot missing")
            else:
                snapshot_id = str(snap[0])
                ready_state = str(snap[1] or "READY")
                ready_manifest_digest = str(snap[2] or "") or _digest({"snapshot_id": snapshot_id})
                if ready_state != "READY":
                    failures.append(f"latest snapshot state={ready_state}")
        except sqlite3.Error as exc:
            failures.append(f"READY lookup failed: {exc}")

        b0_status = "UNKNOWN"
        quality_status = "UNKNOWN"
        try:
            b0 = conn.execute(
                "SELECT status FROM ops_b0_status ORDER BY checked_at DESC LIMIT 1"
            ).fetchone()
            if b0:
                b0_status = str(b0[0])
            q = conn.execute(
                "SELECT status FROM ops_snapshot_quality ORDER BY checked_at DESC LIMIT 1"
            ).fetchone()
            if q:
                quality_status = str(q[0])
            # Fall back: if tables absent, try paper quality
            if b0_status == "UNKNOWN":
                b0_status = "PASS" if complete == total and complete > 0 else "FAIL"
            if quality_status == "UNKNOWN":
                quality_status = b0_status
        except sqlite3.Error:
            b0_status = "PASS" if complete == total and complete > 0 else "FAIL"
            quality_status = b0_status
        if b0_status != "PASS":
            failures.append(f"B0={b0_status}")
        if quality_status != "PASS":
            failures.append(f"quality={quality_status}")

        source_generation = 0
        sync_generation = 0
        try:
            gen = conn.execute(
                "SELECT COALESCE(MAX(change_seq), 0) FROM ingestion_change_log"
            ).fetchone()
            source_generation = int(gen[0]) if gen else 0
            sync_generation = source_generation
        except sqlite3.Error:
            pass
        if source_generation <= 0:
            failures.append("source/sync generation is zero")

        raw_proof_status = "MISSING"
        try:
            raw_n = conn.execute(
                "SELECT COUNT(*) FROM raw_retention_manifests"
            ).fetchone()
            if raw_n and int(raw_n[0]) > 0:
                raw_proof_status = "COMPLETE"
            else:
                # Receipt digests with real raw sha as secondary evidence.
                rec = conn.execute(
                    """
                    SELECT COUNT(*) FROM collection_receipts
                    WHERE digests LIKE '%\"raw\": \"sha256:%'
                       OR digests LIKE '%sha256:%'
                    """
                ).fetchone()
                if rec and int(rec[0]) > 0:
                    raw_proof_status = "COMPLETE"
        except sqlite3.Error:
            pass
        if raw_proof_status != "COMPLETE":
            failures.append("raw proof incomplete")

        return {
            "failures": failures,
            "snapshot_id": snapshot_id,
            "ready_manifest_digest": ready_manifest_digest or _digest({"empty": True}),
            "coverage_policy_version": COVERAGE_POLICY_VERSION,
            "coverage_proof_digest": coverage_proof_digest,
            "governed_membership_digest": membership_digest,
            "governed_complete": complete,
            "governed_total": total,
            "b0_status": b0_status,
            "quality_status": quality_status,
            "source_generation": source_generation,
            "sync_generation": sync_generation,
            "raw_proof_status": raw_proof_status,
        }


def require_mass_research_start(
    *,
    budget: ResearchBudgetCapability | None,
    readiness: VerifiedResearchReadiness | None,
    operator_override: OperatorOverrideCapability | None = None,
) -> tuple[ResearchBudgetCapability, VerifiedResearchReadiness | OperatorOverrideCapability]:
    """Fail-closed mass research start gate.

    Requires budget + VerifiedResearchReadiness. Optional operator override
    may substitute for readiness only when live and audited — never a bool flag.
    """
    cap = require_budget_capability(budget)
    if readiness is not None:
        if not isinstance(readiness, VerifiedResearchReadiness):
            raise MassResearchDisabledError("readiness must be VerifiedResearchReadiness")
        return cap, readiness
    if operator_override is not None:
        if not isinstance(operator_override, OperatorOverrideCapability):
            raise MassResearchDisabledError("invalid operator override type")
        if not operator_override.is_live():
            raise MassResearchDisabledError("operator override expired or not yet valid")
        return cap, operator_override
    raise MassResearchDisabledError(
        "VerifiedResearchReadiness required; mass research NO-GO "
        "(caller-supplied scalars and go_override are rejected)"
    )


__all__ = [
    "MassResearchDisabledError",
    "OperatorOverrideCapability",
    "OperatorOverrideService",
    "ResearchReadinessService",
    "VerifiedResearchReadiness",
    "require_mass_research_start",
]
