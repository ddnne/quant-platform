"""Compatibility surface for Coverage proof persistence and verification."""

from __future__ import annotations

from storage.coverage_proof import (
    COVERAGE_INVENTORY_FORMAT,
    COVERAGE_PROOF_FORMAT,
    LOCAL_COVERAGE_PROOF_FORMAT,
    CoverageProofVerificationError,
    VerifiedCoverageProof,
    persist_coverage_proof,
    require_persisted_coverage_proof,
    _canonical_digest,
    _canonical_json,
    _publication_cutoff_for_build,
    _validation_cutoff_for_build,
    _verify_coverage_manifest,
)
from storage.coverage_proof import _coverage_proof as _owned_coverage_proof


def _coverage_proof(*args, **kwargs):
    try:
        return _owned_coverage_proof(*args, **kwargs)
    except CoverageProofVerificationError as exc:
        from paper_runtime.snapshot import SnapshotRejected

        raise SnapshotRejected(str(exc)) from exc


__all__ = [
    "COVERAGE_INVENTORY_FORMAT",
    "COVERAGE_PROOF_FORMAT",
    "LOCAL_COVERAGE_PROOF_FORMAT",
    "CoverageProofVerificationError",
    "VerifiedCoverageProof",
    "persist_coverage_proof",
    "require_persisted_coverage_proof",
]
