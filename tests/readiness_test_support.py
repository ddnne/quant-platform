"""Test-only constructors for READY capabilities and configured consumers.

Production modules deliberately expose no signer, verifier, clock, digest, or
fixture-policy injection API.  Unit tests that need a synthetic signed
capability keep those powers under ``tests`` and exercise production consumers
through their configured public-key loader.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from research.readiness import (
    ReadinessPublicKeyRegistry,
    VerifiedPilotReadiness,
)
from research.ready_manifest import (
    ReadyManifest,
    canonical_digest,
    load_exact_four_pilot_ready_binding,
    missing_ready_manifest_proofs,
    validate_ready_manifest_profile_binding,
)
from selection.budget_ledger import MassResearchDisabledError


class _TestReadinessSigner:
    """Ephemeral signer that exists only in the tests distribution."""

    __test__ = False

    def __init__(self, *, key_id: str, private_key: Ed25519PrivateKey) -> None:
        if type(key_id) is not str or not key_id.strip():
            raise ValueError("test readiness key_id required")
        self.key_id = key_id.strip()
        self._private_key = private_key

    def sign(self, body: dict[str, Any]) -> str:
        encoded = json.dumps(
            body, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        signature = self._private_key.sign(encoded)
        return "ed25519:" + base64.b64encode(signature).decode("ascii")

    def public_registry(self) -> ReadinessPublicKeyRegistry:
        return ReadinessPublicKeyRegistry(
            self.public_keys()
        )

    def public_keys(self) -> dict[str, Ed25519PublicKey]:
        return {self.key_id: self._private_key.public_key()}

    # Compatibility for existing tests; this class is never shipped by product.
    def _public_registry(self) -> ReadinessPublicKeyRegistry:
        return self.public_registry()


def make_readiness_signer(
    *,
    key_id: str = "test-readiness-v1",
    private_key: Ed25519PrivateKey | None = None,
) -> _TestReadinessSigner:
    """Create a private publication signer strictly for test fixtures."""
    key = private_key or Ed25519PrivateKey.generate()
    return _TestReadinessSigner(key_id=key_id, private_key=key)


def mint_pilot_readiness(
    manifest: ReadyManifest,
    *,
    publisher: _TestReadinessSigner | None = None,
    immutable_db_digest: str,
    profile_binding: Any | None = None,
    now: datetime | None = None,
    ttl_seconds: int = 3600,
) -> VerifiedPilotReadiness:
    """Mint a synthetic capability without adding a product signing seam."""
    if not isinstance(manifest, ReadyManifest):
        raise MassResearchDisabledError("ReadyManifest required")
    if manifest.publication_scope != VerifiedPilotReadiness.EXPECTED_SCOPE:
        raise MassResearchDisabledError(
            "PILOT readiness requires a PILOT ReadyManifest"
        )
    missing = missing_ready_manifest_proofs(manifest)
    if missing:
        raise MassResearchDisabledError(
            "ReadyManifest proofs UNKNOWN/MISSING: " + ", ".join(missing)
        )
    binding = profile_binding or load_exact_four_pilot_ready_binding()
    validate_ready_manifest_profile_binding(manifest, profile=binding)
    signer = publisher or make_readiness_signer()
    clock = now or datetime.now(timezone.utc)
    expires = clock + timedelta(seconds=max(60, ttl_seconds))
    evidence = {
        "manifest": manifest.to_dict(),
        "immutable_db_digest": immutable_db_digest,
    }
    body = {
        "attestation_id": str(uuid4()),
        "readiness_scope": VerifiedPilotReadiness.EXPECTED_SCOPE,
        "snapshot_id": manifest.snapshot_id,
        "profile_id": manifest.profile_id,
        "profile_version": manifest.profile_version,
        "profile_digest": manifest.profile_digest,
        "plan_ids": tuple(manifest.plan_ids),
        "plan_set_digest": manifest.plan_set_digest,
        "dependency_closure_digest": manifest.dependency_closure_digest,
        "universe_rule_digest": manifest.universe_rule_digest,
        "resolved_universe_digest": manifest.resolved_universe_digest,
        "dataset_ids": tuple(manifest.dataset_ids),
        "ready_state": "READY",
        "ready_manifest_digest": manifest.to_dict()["manifest_digest"],
        "immutable_db_digest": immutable_db_digest,
        "coverage_policy_version": manifest.coverage_policy_version,
        "coverage_policy_digest": manifest.coverage_policy_digest,
        "coverage_proof_digest": manifest.coverage_proof_digest,
        "governed_membership_digest": manifest.dataset_membership_digest,
        "raw_proof_digest": manifest.raw_proof_digest,
        "receipt_proof_digest": manifest.receipt_proof_digest,
        "validation_proof_digest": manifest.validation_proof_digest,
        "b0_quality_proof_digest": manifest.b0_proof_digest,
        "b4_quality_proof_digest": manifest.b4_proof_digest,
        "source_generation": manifest.source_generation,
        "export_cursor": manifest.export_cursor,
        "applied_cursor": manifest.applied_cursor,
        "verified_at": clock.isoformat(),
        "expires_at": expires.isoformat(),
        "evidence_digest": canonical_digest(evidence),
        "key_id": signer.key_id,
        "issuer": "ReadyPublicationService/v3",
    }
    signature = signer.sign(
        {"format": VerifiedPilotReadiness.FORMAT, **body}
    )
    minted = VerifiedPilotReadiness(signature=signature, **body)
    if not signer.public_registry().verify(
        key_id=minted.key_id,
        body=minted.to_canonical_body(),
        signature=minted.signature,
    ):
        raise MassResearchDisabledError(
            "synthetic VerifiedPilotReadiness signature verification failed"
        )
    return minted


def controlled_pilot_scheduler(
    *,
    verifier: ReadinessPublicKeyRegistry,
    **kwargs: Any,
) -> Any:
    """Construct the public scheduler under a test-only config patch."""
    from research.phase7_pilot import ControlledPilotScheduler

    with patch.object(
        ReadinessPublicKeyRegistry,
        "load_pinned",
        return_value=verifier,
    ):
        return ControlledPilotScheduler(**kwargs)
