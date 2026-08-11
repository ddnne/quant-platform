"""Single READY publication policy — sole gate entry for publish_ready_snapshot.

Consolidates coverage V2 proof, raw retention, quality, and coherence checks
into one ReadyEvidenceBundle evaluation so the same conditions are not
re-implemented ad hoc across modules.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from paper_runtime.coherence import CoherenceGateResult, check_ready_coherence


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


class ReadyPublicationPolicy:
    """Evaluate READY eligibility. Fail closed on any failed evidence item."""

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
    ) -> ReadyEvidenceBundle:
        required = tuple(required_datasets)
        bundle = ReadyEvidenceBundle()

        # Coherence suite (coverage COMPLETE, trusted receipts, validation,
        # natural keys, B0, change generation).
        coherence = check_ready_coherence(
            conn, db_path, required, run_id=run_id
        )
        for gate in coherence:
            bundle.items.append(
                ReadyEvidenceItem(
                    name=f"coherence.{gate.gate_name}",
                    passed=gate.passed,
                    reason=gate.reason,
                    detail=gate.detail,
                )
            )

        if coverage_proof is not None:
            ok = (
                coverage_proof.get("status") == "COMPLETE"
                and str(coverage_proof.get("proof_digest", "")).startswith("sha256:")
            )
            bundle.items.append(
                ReadyEvidenceItem(
                    name="coverage_v2_proof",
                    passed=bool(ok),
                    reason=None if ok else "coverage_v2_proof not COMPLETE",
                    detail={"status": coverage_proof.get("status")},
                )
            )

        if quality_status is not None:
            ok = quality_status == "PASS"
            bundle.items.append(
                ReadyEvidenceItem(
                    name="b0_quality",
                    passed=ok,
                    reason=None if ok else f"quality_status={quality_status}",
                )
            )

        if raw_manifest_ok is not None:
            bundle.items.append(
                ReadyEvidenceItem(
                    name="raw_retention_manifests",
                    passed=bool(raw_manifest_ok),
                    reason=None if raw_manifest_ok else "raw retention incomplete",
                )
            )

        return bundle


__all__ = [
    "ReadyEvidenceBundle",
    "ReadyEvidenceItem",
    "ReadyPublicationPolicy",
]
