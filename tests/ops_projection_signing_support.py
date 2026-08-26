"""Tests-only ephemeral Ops Projection signing support."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ops.projection_signing import (
    _signed_body,
    _validate_envelope,
    canonical_json_bytes,
    OpsProjectionSignatureError,
)
from scripts.export_ops_projection import (
    ProjectionBundle,
    _render_projection_bundle,
)


@dataclass(frozen=True)
class TestOpsProjectionSigningKey:
    """Ephemeral signer that production packages never import."""

    key_id: str
    private_key: Ed25519PrivateKey

    __test__ = False

    def sign(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        _validate_envelope(envelope)
        body = _signed_body(key_id=self.key_id, envelope=envelope)
        signature = self.private_key.sign(canonical_json_bytes(body))
        return {
            **body,
            "signature": "ed25519:" + base64.b64encode(signature).decode("ascii"),
        }


@dataclass(frozen=True)
class TestOpsProjectionVerifier:
    """Ephemeral verifier unavailable from production packages."""

    key_id: str
    public_key: Ed25519PublicKey

    __test__ = False

    def verify(self, document: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {
            "schema_version", "algorithm", "issuer_key_id", "envelope", "signature"
        }
        if set(document) != allowed:
            raise OpsProjectionSignatureError(
                "signed Ops Projection document shape invalid"
            )
        if document.get("issuer_key_id") != self.key_id:
            raise OpsProjectionSignatureError("Ops Projection issuer is not trusted")
        envelope = document.get("envelope")
        if not isinstance(envelope, Mapping):
            raise OpsProjectionSignatureError("Ops Projection envelope is missing")
        _validate_envelope(envelope)
        body = _signed_body(key_id=self.key_id, envelope=envelope)
        signature_value = str(document.get("signature") or "")
        if not signature_value.startswith("ed25519:"):
            raise OpsProjectionSignatureError(
                "Ops Projection signature must use Ed25519"
            )
        try:
            signature = base64.b64decode(
                signature_value.removeprefix("ed25519:"), validate=True
            )
            self.public_key.verify(signature, canonical_json_bytes(body))
        except (ValueError, InvalidSignature) as exc:
            raise OpsProjectionSignatureError(
                "Ops Projection signature is invalid"
            ) from exc
        return dict(envelope)

    def verified_dataset_evidence(
        self,
        document: Mapping[str, Any],
        required_datasets: tuple[str, ...] | list[str],
    ) -> dict[str, dict[str, Any]]:
        envelope = self.verify(document)
        coverage = envelope["dataset_coverage"]
        assert isinstance(coverage, Mapping)
        evidence: dict[str, dict[str, Any]] = {}
        for dataset in required_datasets:
            row = coverage.get(dataset)
            if not isinstance(row, Mapping):
                raise OpsProjectionSignatureError(
                    f"signed Ops Projection Coverage missing for {dataset}"
                )
            evidence[str(dataset)] = {
                "dataset": str(dataset),
                "status": row.get("status"),
                "coverage_mode": row.get("coverage_mode"),
                "policy_id": row.get("policy_id"),
                "policy_version": row.get("policy_version"),
                "policy_digest": row.get("policy_digest"),
                "observed_start": row.get("observed_start"),
                "observed_end": row.get("observed_end"),
                "projection_status": envelope["projection_status"],
                "projection_generation": envelope["generation_id"],
                "projection_content_digest": envelope["content_digest"],
                "source_generation": envelope["source_generation"],
                "export_cursor": envelope["export_cursor"],
                "applied_cursor": envelope["applied_cursor"],
            }
        return evidence


def make_test_ops_projection_verifier(
    private_key: Ed25519PrivateKey,
    *,
    key_id: str = "ops-projection-test-v1",
) -> TestOpsProjectionVerifier:
    return TestOpsProjectionVerifier(key_id, private_key.public_key())


def render_projection_bundle_for_test(
    db_path: str | Path,
    **kwargs: Any,
) -> ProjectionBundle:
    """Render synthetic cursor states without adding a product test seam."""
    return _render_projection_bundle(db_path, **kwargs)


def sign_projection_bundle_for_test(
    bundle: ProjectionBundle,
    signer: TestOpsProjectionSigningKey,
) -> dict[str, Any]:
    """Sign only in tests; product renderers never receive this signer."""
    return signer.sign(bundle.envelope)
