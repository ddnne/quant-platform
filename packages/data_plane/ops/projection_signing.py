"""Dedicated Ed25519 authority for immutable Ops Projection envelopes.

This module intentionally has no Receipt or READY key fallback. The publisher
is the only private-key consumer; readers load public keys only.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


SIGNED_DOCUMENT_SCHEMA = "ops-projection-signed-envelope/v1"
ENVELOPE_SCHEMA = "ops-projection-envelope/v1"
SIGNING_KEY_ENV = "QUANT_OPS_PROJECTION_SIGNING_KEY_PEM"
SIGNING_KEY_ID_ENV = "QUANT_OPS_PROJECTION_SIGNING_KEY_ID"
VERIFY_REGISTRY_ENV = "QUANT_OPS_PROJECTION_VERIFY_REGISTRY"
DEFAULT_SIGNING_KEY_PATH = (
    Path.home() / ".config" / "quant-platform" / "ops_projection_signing_key.pem"
)
DEFAULT_VERIFY_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "ops_projection"
    / "verify_public_keys.json"
)


class OpsProjectionSignatureError(RuntimeError):
    """Projection envelope is unsigned, malformed, or unverifiable."""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_digest(value: Mapping[str, Any]) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _signed_body(*, key_id: str, envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SIGNED_DOCUMENT_SCHEMA,
        "algorithm": "Ed25519",
        "issuer_key_id": key_id,
        "envelope": dict(envelope),
    }


def _validate_envelope(envelope: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "generation_id",
        "content_digest",
        "source_db_digest",
        "generated_at",
        "producer_commit_sha",
        "contract_digest",
        "registry_digest",
        "coverage_policy_version",
        "projection_status",
        "source_generation",
        "source_snapshot_generation",
        "source_cursor",
        "export_cursor",
        "applied_cursor",
        "coverage_status_digest",
        "dataset_coverage",
        "b0_status",
        "b0_evidence_digest",
        "b4_status",
        "b4_evidence_digest",
        "evidence_digests",
        "row_counts",
    }
    if envelope.get("schema_version") != ENVELOPE_SCHEMA:
        raise OpsProjectionSignatureError("unsupported Ops Projection envelope schema")
    missing = required - set(envelope)
    if missing:
        raise OpsProjectionSignatureError(
            "Ops Projection envelope fields missing: " + ",".join(sorted(missing))
        )
    for field in (
        "content_digest",
        "source_db_digest",
        "contract_digest",
        "registry_digest",
        "coverage_status_digest",
        "b0_evidence_digest",
        "b4_evidence_digest",
    ):
        value = str(envelope.get(field) or "")
        if not value.startswith("sha256:") or len(value) != 71:
            raise OpsProjectionSignatureError(f"invalid {field}")
    if envelope.get("b0_status") not in {"PASS", "FAIL", "UNKNOWN"}:
        raise OpsProjectionSignatureError("invalid b0_status")
    if envelope.get("b4_status") not in {"PASS", "FAIL", "UNKNOWN"}:
        raise OpsProjectionSignatureError("invalid b4_status")
    if envelope.get("projection_status") not in {"FRESH", "STALE", "FAILED", "UNKNOWN"}:
        raise OpsProjectionSignatureError("invalid projection_status")
    for field in ("source_generation", "source_cursor", "export_cursor", "applied_cursor"):
        value = envelope.get(field)
        if value is not None and (not isinstance(value, int) or value < 0):
            raise OpsProjectionSignatureError(f"invalid {field}")
    if not isinstance(envelope.get("evidence_digests"), Mapping):
        raise OpsProjectionSignatureError("evidence_digests must be an object")
    if not isinstance(envelope.get("dataset_coverage"), Mapping):
        raise OpsProjectionSignatureError("dataset_coverage must be an object")
    if not isinstance(envelope.get("row_counts"), Mapping):
        raise OpsProjectionSignatureError("row_counts must be an object")


@dataclass(frozen=True)
class OpsProjectionSigningKey:
    """Positive capability held only by the out-of-band projection publisher."""

    key_id: str
    _private_key: Ed25519PrivateKey

    def __post_init__(self) -> None:
        if not self.key_id.strip() or not isinstance(self._private_key, Ed25519PrivateKey):
            raise OpsProjectionSignatureError(
                "Ops Projection signer requires key_id and Ed25519 private key"
            )

    def sign(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        _validate_envelope(envelope)
        body = _signed_body(key_id=self.key_id, envelope=envelope)
        signature = self._private_key.sign(canonical_json_bytes(body))
        return {
            **body,
            "signature": "ed25519:" + base64.b64encode(signature).decode("ascii"),
        }


def load_ops_projection_signer(
    *,
    pem: bytes | str | None = None,
    path: str | Path | None = None,
    key_id: str | None = None,
    required: bool = False,
) -> OpsProjectionSigningKey | None:
    """Load only the dedicated Ops key; never consult Receipt/READY settings."""

    resolved_key_id = str(key_id or os.environ.get(SIGNING_KEY_ID_ENV) or "").strip()
    material: bytes | None
    if pem is not None:
        material = pem.encode("utf-8") if isinstance(pem, str) else pem
    elif os.environ.get(SIGNING_KEY_ENV):
        material = os.environ[SIGNING_KEY_ENV].encode("utf-8")
    else:
        selected = Path(path).expanduser() if path is not None else DEFAULT_SIGNING_KEY_PATH
        # Tests never inherit an operator's host mint key unless explicitly injected.
        if path is None and os.environ.get("PYTEST_CURRENT_TEST"):
            material = None
        else:
            material = selected.read_bytes() if selected.is_file() else None
    if material is None:
        if required:
            raise OpsProjectionSignatureError(
                "dedicated Ops Projection signing key is unavailable"
            )
        return None
    if not resolved_key_id:
        raise OpsProjectionSignatureError("Ops Projection signing key id is required")
    try:
        private_key = serialization.load_pem_private_key(material, password=None)
    except (TypeError, ValueError) as exc:
        raise OpsProjectionSignatureError("invalid Ops Projection private key PEM") from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise OpsProjectionSignatureError("Ops Projection signing key must be Ed25519")
    return OpsProjectionSigningKey(resolved_key_id, private_key)


@dataclass(frozen=True)
class OpsProjectionPublicKeyRegistry:
    """Public-key-only verifier registry for Ops Projection consumers."""

    _keys: Mapping[str, Ed25519PublicKey]

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "OpsProjectionPublicKeyRegistry":
        if document.get("schema_version") != 1:
            raise OpsProjectionSignatureError("Ops Projection key registry schema must be 1")
        rows = document.get("keys")
        if not isinstance(rows, list):
            raise OpsProjectionSignatureError("Ops Projection key registry keys missing")
        keys: dict[str, Ed25519PublicKey] = {}
        for row in rows:
            if not isinstance(row, Mapping) or row.get("algorithm") != "Ed25519":
                raise OpsProjectionSignatureError("Ops Projection registry requires Ed25519")
            if row.get("status", "active") != "active":
                continue
            key_id = str(row.get("key_id") or "").strip()
            try:
                raw = base64.b64decode(str(row.get("public_key_base64") or ""), validate=True)
                public_key = Ed25519PublicKey.from_public_bytes(raw)
            except (ValueError, TypeError) as exc:
                raise OpsProjectionSignatureError(
                    f"invalid Ops Projection public key: {key_id or '<missing>'}"
                ) from exc
            if not key_id or key_id in keys:
                raise OpsProjectionSignatureError("Ops Projection key ids must be unique")
            keys[key_id] = public_key
        return cls(keys)

    @classmethod
    def load(
        cls, path: str | Path | None = None
    ) -> "OpsProjectionPublicKeyRegistry":
        selected = Path(
            path or os.environ.get(VERIFY_REGISTRY_ENV) or DEFAULT_VERIFY_REGISTRY_PATH
        ).expanduser()
        try:
            document = json.loads(selected.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise OpsProjectionSignatureError(
                f"cannot load Ops Projection public key registry: {selected}"
            ) from exc
        if not isinstance(document, Mapping):
            raise OpsProjectionSignatureError("Ops Projection registry must be an object")
        return cls.from_document(document)

    def verify(self, document: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {
            "schema_version", "algorithm", "issuer_key_id", "envelope", "signature"
        }
        if set(document) != allowed:
            raise OpsProjectionSignatureError("signed Ops Projection document shape invalid")
        key_id = str(document.get("issuer_key_id") or "")
        public_key = self._keys.get(key_id)
        if public_key is None:
            raise OpsProjectionSignatureError("Ops Projection issuer is not trusted")
        envelope = document.get("envelope")
        if not isinstance(envelope, Mapping):
            raise OpsProjectionSignatureError("Ops Projection envelope is missing")
        _validate_envelope(envelope)
        body = _signed_body(key_id=key_id, envelope=envelope)
        signature_value = str(document.get("signature") or "")
        if not signature_value.startswith("ed25519:"):
            raise OpsProjectionSignatureError("Ops Projection signature must use Ed25519")
        try:
            signature = base64.b64decode(
                signature_value.removeprefix("ed25519:"), validate=True
            )
            public_key.verify(signature, canonical_json_bytes(body))
        except (ValueError, InvalidSignature) as exc:
            raise OpsProjectionSignatureError("Ops Projection signature is invalid") from exc
        return dict(envelope)

    def verified_dataset_evidence(
        self,
        document: Mapping[str, Any],
        required_datasets: tuple[str, ...] | list[str],
    ) -> dict[str, dict[str, Any]]:
        """Derive READY input only from a verified, signed envelope."""

        envelope = self.verify(document)
        coverage = envelope["dataset_coverage"]
        assert isinstance(coverage, Mapping)  # validated by verify
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
                "policy_version": row.get("policy_version"),
                "projection_status": envelope["projection_status"],
                "projection_generation": envelope["generation_id"],
                "projection_content_digest": envelope["content_digest"],
                "source_generation": envelope["source_generation"],
                "export_cursor": envelope["export_cursor"],
                "applied_cursor": envelope["applied_cursor"],
            }
        return evidence


__all__ = [
    "DEFAULT_SIGNING_KEY_PATH",
    "DEFAULT_VERIFY_REGISTRY_PATH",
    "ENVELOPE_SCHEMA",
    "OpsProjectionPublicKeyRegistry",
    "OpsProjectionSignatureError",
    "OpsProjectionSigningKey",
    "SIGNED_DOCUMENT_SCHEMA",
    "SIGNING_KEY_ENV",
    "SIGNING_KEY_ID_ENV",
    "VERIFY_REGISTRY_ENV",
    "canonical_json_bytes",
    "load_ops_projection_signer",
    "sha256_digest",
]
