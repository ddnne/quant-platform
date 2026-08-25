"""Scope-separated research readiness attestations.

READY is a positive capability, not a count supplied by a scheduler. Pilot
and Mass attestations are deliberately different nominal types, and every
attestation is signed by a dedicated Ed25519 key owned by the READY
publication service. Verifiers receive public keys only; receipt signing keys
and HMAC compatibility fallbacks are intentionally not consulted.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Mapping, TypeVar
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from selection.budget_ledger import (
    MassResearchDisabledError,
    ResearchBudgetCapability,
)

READINESS_SIGNATURE_ALGORITHM = "Ed25519"
DEFAULT_READINESS_PUBLIC_KEYS_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "ready"
    / "readiness_verify_public_keys.json"
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
MASS_READINESS_ENABLED: bool = False
_MASS_AUTHORITY_TOKEN = object()
_READY_PUBLICATION_SIGNER_TOKEN = object()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(payload: Mapping[str, Any] | list[Any] | str) -> str:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical_bytes(body: Mapping[str, Any]) -> bytes:
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _decode_signature(signature: str) -> bytes:
    prefix = "ed25519:"
    if not signature.startswith(prefix):
        raise ValueError("readiness signature must use Ed25519")
    try:
        return base64.b64decode(signature[len(prefix) :], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("readiness signature is not valid base64") from exc


@dataclass(frozen=True, slots=True)
class ReadinessPublicKeyRegistry:
    """Immutable verifier registry containing public keys only."""

    _keys: Mapping[str, Ed25519PublicKey]

    def __post_init__(self) -> None:
        if not self._keys:
            raise MassResearchDisabledError("readiness public key registry is empty")
        normalized: dict[str, Ed25519PublicKey] = {}
        for raw_key_id, key in self._keys.items():
            key_id = str(raw_key_id).strip()
            if not key_id or not isinstance(key, Ed25519PublicKey):
                raise MassResearchDisabledError(
                    "readiness registry entries require key_id and Ed25519 public key"
                )
            normalized[key_id] = key
        object.__setattr__(self, "_keys", MappingProxyType(normalized))

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "ReadinessPublicKeyRegistry":
        if document.get("schema_version") != 1:
            raise MassResearchDisabledError(
                "readiness public key registry schema_version must be 1"
            )
        rows = document.get("keys")
        if not isinstance(rows, list) or not rows:
            raise MassResearchDisabledError("readiness public key registry keys missing")
        keys: dict[str, Ed25519PublicKey] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise MassResearchDisabledError("invalid readiness public key row")
            if row.get("algorithm") != READINESS_SIGNATURE_ALGORITHM:
                raise MassResearchDisabledError(
                    "readiness public key algorithm must be Ed25519"
                )
            if row.get("status", "active") != "active":
                continue
            key_id = str(row.get("key_id") or "").strip()
            encoded = str(row.get("public_key_b64") or "").strip()
            try:
                raw = base64.b64decode(encoded, validate=True)
                key = Ed25519PublicKey.from_public_bytes(raw)
            except (ValueError, TypeError) as exc:
                raise MassResearchDisabledError(
                    f"invalid readiness public key for {key_id!r}"
                ) from exc
            if not key_id or key_id in keys:
                raise MassResearchDisabledError(
                    "readiness public key ids must be non-empty and unique"
                )
            keys[key_id] = key
        if not keys:
            raise MassResearchDisabledError(
                "readiness public key registry has no active keys"
            )
        return cls(keys)

    @classmethod
    def from_file(cls, path: str | Path) -> "ReadinessPublicKeyRegistry":
        source = Path(path)
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MassResearchDisabledError(
                f"cannot load readiness public key registry: {source}"
            ) from exc
        if not isinstance(document, Mapping):
            raise MassResearchDisabledError(
                "readiness public key registry must be an object"
            )
        return cls.from_document(document)

    @classmethod
    def load_pinned(cls) -> "ReadinessPublicKeyRegistry":
        """Load only the committed production trust root; no path/env override."""
        try:
            document = json.loads(
                DEFAULT_READINESS_PUBLIC_KEYS_PATH.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise MassResearchDisabledError(
                "cannot load the pinned readiness public key registry"
            ) from exc
        if (
            not isinstance(document, Mapping)
            or document.get("purpose")
            != "readiness_attestation_verification"
        ):
            raise MassResearchDisabledError(
                "pinned readiness public key registry purpose mismatch"
            )
        return cls.from_document(document)

    def _key_id_for_public_key(self, key: Ed25519PublicKey) -> str:
        raw = key.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        matches = [
            key_id
            for key_id, registered in self._keys.items()
            if registered.public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )
            == raw
        ]
        if len(matches) != 1:
            raise MassResearchDisabledError(
                "dedicated readiness key does not match exactly one active "
                "key in the pinned registry"
            )
        return matches[0]

    def verify(self, *, key_id: str, body: Mapping[str, Any], signature: str) -> bool:
        key = self._keys.get(str(key_id))
        if key is None:
            return False
        try:
            key.verify(_decode_signature(signature), _canonical_bytes(body))
        except (InvalidSignature, ValueError):
            return False
        return True


@dataclass(frozen=True)
class _VerifiedReadiness:
    """Signed immutable capability shared by the two nominal scope types."""

    EXPECTED_SCOPE: ClassVar[str] = ""
    FORMAT: ClassVar[str] = "verified-readiness-attestation/v1"

    attestation_id: str
    readiness_scope: str
    snapshot_id: str
    profile_id: str
    profile_version: str
    profile_digest: str
    plan_ids: tuple[str, ...]
    plan_set_digest: str
    dependency_closure_digest: str
    dataset_ids: tuple[str, ...]
    ready_state: str
    ready_manifest_digest: str
    immutable_db_digest: str
    coverage_policy_version: str
    coverage_policy_digest: str
    coverage_proof_digest: str
    governed_membership_digest: str
    raw_proof_digest: str
    receipt_proof_digest: str
    validation_proof_digest: str
    b0_quality_proof_digest: str
    b4_quality_proof_digest: str
    source_generation: str
    export_cursor: str
    applied_cursor: str
    verified_at: str
    expires_at: str
    evidence_digest: str
    key_id: str
    signature: str
    issuer: str = "ReadyPublicationService/v3"

    def __post_init__(self) -> None:
        if self.readiness_scope != self.EXPECTED_SCOPE:
            raise ValueError(
                f"{type(self).__name__} requires readiness_scope "
                f"{self.EXPECTED_SCOPE!r}"
            )

    def to_canonical_body(self) -> dict[str, Any]:
        return {
            "format": self.FORMAT,
            "attestation_id": self.attestation_id,
            "readiness_scope": self.readiness_scope,
            "snapshot_id": self.snapshot_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_digest": self.profile_digest,
            "plan_ids": list(self.plan_ids),
            "plan_set_digest": self.plan_set_digest,
            "dependency_closure_digest": self.dependency_closure_digest,
            "dataset_ids": list(self.dataset_ids),
            "ready_state": self.ready_state,
            "ready_manifest_digest": self.ready_manifest_digest,
            "immutable_db_digest": self.immutable_db_digest,
            "coverage_policy_version": self.coverage_policy_version,
            "coverage_policy_digest": self.coverage_policy_digest,
            "coverage_proof_digest": self.coverage_proof_digest,
            "governed_membership_digest": self.governed_membership_digest,
            "raw_proof_digest": self.raw_proof_digest,
            "receipt_proof_digest": self.receipt_proof_digest,
            "validation_proof_digest": self.validation_proof_digest,
            "b0_quality_proof_digest": self.b0_quality_proof_digest,
            "b4_quality_proof_digest": self.b4_quality_proof_digest,
            "source_generation": self.source_generation,
            "export_cursor": self.export_cursor,
            "applied_cursor": self.applied_cursor,
            "verified_at": self.verified_at,
            "expires_at": self.expires_at,
            "evidence_digest": self.evidence_digest,
            "key_id": self.key_id,
            "issuer": self.issuer,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete signed capability for immutable retention."""
        return {**self.to_canonical_body(), "signature": self.signature}

    def is_expired(self, *, now: datetime | None = None) -> bool:
        clock = now or _now()
        try:
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if expires.tzinfo is None:
            return True
        return clock > expires

    def _scope_fields_valid(self) -> bool:
        return True

    def is_valid(
        self,
        *,
        expected_snapshot_id: str | None = None,
        expected_plan_set_digest: str | None = None,
        expected_closure_digest: str | None = None,
        verifier: ReadinessPublicKeyRegistry | None = None,
        now: datetime | None = None,
    ) -> bool:
        digest_fields = (
            self.snapshot_id,
            self.profile_digest,
            self.plan_set_digest,
            self.dependency_closure_digest,
            self.ready_manifest_digest,
            self.immutable_db_digest,
            self.coverage_policy_digest,
            self.coverage_proof_digest,
            self.governed_membership_digest,
            self.raw_proof_digest,
            self.receipt_proof_digest,
            self.validation_proof_digest,
            self.b0_quality_proof_digest,
            self.b4_quality_proof_digest,
            self.evidence_digest,
        )
        if (
            not self.attestation_id
            or self.ready_state != "READY"
            or self.readiness_scope != self.EXPECTED_SCOPE
            or not self.profile_id
            or not self.profile_version
            or not self.plan_ids
            or len(self.plan_ids) != len(set(self.plan_ids))
            or not self.dataset_ids
            or len(self.dataset_ids) != len(set(self.dataset_ids))
            or not self.key_id
            or any(not _is_sha256(value) for value in digest_fields)
            or not self.source_generation
            or not self.export_cursor
            or not self.applied_cursor
            or self.source_generation != self.export_cursor
            or self.export_cursor != self.applied_cursor
            or not self._scope_fields_valid()
            or self.is_expired(now=now)
        ):
            return False
        if expected_snapshot_id is not None and self.snapshot_id != expected_snapshot_id:
            return False
        if (
            expected_plan_set_digest is not None
            and self.plan_set_digest != expected_plan_set_digest
        ):
            return False
        if (
            expected_closure_digest is not None
            and self.dependency_closure_digest != expected_closure_digest
        ):
            return False
        registry = verifier or ReadinessPublicKeyRegistry.load_pinned()
        return registry.verify(
            key_id=self.key_id,
            body=self.to_canonical_body(),
            signature=self.signature,
        )

    def require_valid(self, **kwargs: Any) -> "_VerifiedReadiness":
        if not self.is_valid(**kwargs):
            raise MassResearchDisabledError(
                f"{type(self).__name__} invalid, expired, scope-mismatched, "
                "or signature mismatch"
            )
        return self


class VerifiedPilotReadiness(_VerifiedReadiness):
    """Capability valid only for an exact controlled-pilot plan set."""

    EXPECTED_SCOPE = "PILOT"

    def _scope_fields_valid(self) -> bool:
        return (
            self.profile_id == "controlled-pilot/exact-four"
            and len(self.plan_ids) == 4
        )


def load_verified_pilot_readiness(
    path: str | Path,
    *,
    expected_snapshot_id: str | None = None,
    expected_ready_manifest_digest: str | None = None,
) -> VerifiedPilotReadiness:
    """Strictly load and verify an exact-four readiness sidecar.

    This is a public-key-only consumer boundary.  The caller can narrow the
    expected immutable publication identity, but cannot inject a verifier,
    choose an alternate plan/profile binding, or bypass expiry checks.
    """
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MassResearchDisabledError(
            f"cannot load pilot readiness sidecar: {source}"
        ) from exc
    if not isinstance(document, Mapping):
        raise MassResearchDisabledError("pilot readiness sidecar must be an object")

    canonical_fields = {field.name for field in fields(VerifiedPilotReadiness)}
    expected_fields = canonical_fields | {"format"}
    if set(document) != expected_fields:
        missing = sorted(expected_fields - set(document))
        extra = sorted(set(document) - expected_fields)
        raise MassResearchDisabledError(
            "pilot readiness sidecar fields are not closed: "
            f"missing={missing}, extra={extra}"
        )
    if document.get("format") != VerifiedPilotReadiness.FORMAT:
        raise MassResearchDisabledError("pilot readiness sidecar format mismatch")
    if document.get("readiness_scope") != VerifiedPilotReadiness.EXPECTED_SCOPE:
        raise MassResearchDisabledError("pilot readiness sidecar scope mismatch")
    if document.get("issuer") != "ReadyPublicationService/v3":
        raise MassResearchDisabledError("pilot readiness sidecar issuer mismatch")

    init_payload = {key: document[key] for key in canonical_fields}
    for field in ("plan_ids", "dataset_ids"):
        value = init_payload[field]
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) or not item for item in value)
        ):
            raise MassResearchDisabledError(
                f"pilot readiness sidecar {field} must be a non-empty string array"
            )
        init_payload[field] = tuple(value)
    for field, value in init_payload.items():
        if field in {"plan_ids", "dataset_ids"}:
            continue
        if not isinstance(value, str) or not value:
            raise MassResearchDisabledError(
                f"pilot readiness sidecar {field} must be a non-empty string"
            )
    try:
        readiness = VerifiedPilotReadiness(**init_payload)
    except (TypeError, ValueError) as exc:
        raise MassResearchDisabledError(
            "pilot readiness sidecar cannot construct the nominal pilot capability"
        ) from exc

    # A PILOT signature is useful only for the single governed exact-four
    # compiler output.  Do not let a signed self-consistent alternate set
    # become publication authority at a consumer boundary.
    from research.ready_manifest import load_exact_four_pilot_ready_binding

    binding = load_exact_four_pilot_ready_binding()
    if (
        readiness.profile_id != binding.profile_id
        or readiness.profile_version != binding.profile_version
        or readiness.profile_digest != binding.profile_digest
        or readiness.plan_ids != binding.plan_ids
        or readiness.plan_set_digest != binding.plan_set_digest
        or readiness.dependency_closure_digest != binding.closure_set_digest
        or readiness.dataset_ids != binding.required_datasets
    ):
        raise MassResearchDisabledError(
            "pilot readiness sidecar does not match the canonical exact-four binding"
        )
    if (
        expected_ready_manifest_digest is not None
        and readiness.ready_manifest_digest != expected_ready_manifest_digest
    ):
        raise MassResearchDisabledError(
            "pilot readiness sidecar ReadyManifest digest mismatch"
        )
    registry = ReadinessPublicKeyRegistry.load_pinned()
    if not readiness.is_valid(
        expected_snapshot_id=expected_snapshot_id,
        expected_plan_set_digest=binding.plan_set_digest,
        expected_closure_digest=binding.closure_set_digest,
        verifier=registry,
    ):
        raise MassResearchDisabledError(
            "pilot readiness sidecar is invalid, expired, or untrusted"
        )
    return readiness


class VerifiedMassReadiness(_VerifiedReadiness):
    """Capability valid only for an explicit Mass data profile."""

    EXPECTED_SCOPE = "MASS"

    def _scope_fields_valid(self) -> bool:
        return self.profile_id.startswith("mass/")


class GovernedMassReadinessAuthority:
    """Nominal authority for a separately governed Mass policy/profile.

    This phase deliberately exposes no issuer. Possession of the READY signing
    key alone cannot turn a generic/core profile into Mass readiness. A future
    phase must add a governed policy loader and private factory first.
    """

    __slots__ = ("policy_id", "profile_id", "policy_digest")

    def __init__(
        self,
        *,
        policy_id: str,
        profile_id: str,
        policy_digest: str,
        _authority_token: object | None = None,
    ) -> None:
        if _authority_token is not _MASS_AUTHORITY_TOKEN:
            raise MassResearchDisabledError(
                "GovernedMassReadinessAuthority has no public issuer; "
                "Mass Research remains disabled"
            )
        self.policy_id = policy_id
        self.profile_id = profile_id
        self.policy_digest = policy_digest


# Compatibility import only. It resolves to the Mass type, so a pilot
# capability can never pass old mass call sites through inheritance.
VerifiedResearchReadiness = VerifiedMassReadiness


_R = TypeVar("_R", bound=_VerifiedReadiness)


class _ReadyPublicationSigner:
    """Private signing capability owned by the READY publication service."""

    __slots__ = ("_key_id", "_private_key")

    def __init__(
        self,
        *,
        key_id: str,
        private_key: Ed25519PrivateKey,
        _factory_token: object | None = None,
    ) -> None:
        if _factory_token is not _READY_PUBLICATION_SIGNER_TOKEN:
            raise MassResearchDisabledError(
                "READY signer is issued only inside the publication service"
            )
        key = str(key_id).strip()
        if not key or not isinstance(private_key, Ed25519PrivateKey):
            raise MassResearchDisabledError(
                "READY publisher requires key_id and Ed25519 private key"
            )
        self._key_id = key
        self._private_key = private_key

    @classmethod
    def _from_private_pem(
        cls, *, key_id: str, private_pem: bytes
    ) -> "_ReadyPublicationSigner":
        try:
            key = serialization.load_pem_private_key(private_pem, password=None)
        except (TypeError, ValueError) as exc:
            raise MassResearchDisabledError("invalid readiness private key PEM") from exc
        if not isinstance(key, Ed25519PrivateKey):
            raise MassResearchDisabledError("readiness signing key must be Ed25519")
        return cls(
            key_id=key_id,
            private_key=key,
            _factory_token=_READY_PUBLICATION_SIGNER_TOKEN,
        )

    @property
    def key_id(self) -> str:
        return self._key_id

    def _public_registry(self) -> ReadinessPublicKeyRegistry:
        return ReadinessPublicKeyRegistry(
            {self._key_id: self._private_key.public_key()}
        )

    def _sign(self, body: Mapping[str, Any]) -> str:
        signature = self._private_key.sign(_canonical_bytes(body))
        return "ed25519:" + base64.b64encode(signature).decode("ascii")

    def _mint_pilot(
        self,
        manifest: Any,
        *,
        db_path: str | Path,
        profile_binding: Any,
        ttl_seconds: int = 3600,
    ) -> VerifiedPilotReadiness:
        return _mint_bound_readiness(
            VerifiedPilotReadiness,
            manifest,
            publisher=self,
            db_path=db_path,
            profile_binding=profile_binding,
            ttl_seconds=ttl_seconds,
        )

    def _mint_mass(
        self,
        manifest: Any,
        *,
        mass_authority: GovernedMassReadinessAuthority | None = None,
    ) -> VerifiedMassReadiness:
        if not isinstance(mass_authority, GovernedMassReadinessAuthority):
            raise MassResearchDisabledError(
                "explicit GovernedMassReadinessAuthority required; "
                "generic/core profiles cannot mint Mass readiness"
            )
        raise MassResearchDisabledError(
            "Mass readiness minting is hard-disabled in Phase 6.3.1"
        )


def _load_pinned_ready_publication_signer() -> _ReadyPublicationSigner:
    """Load the dedicated default key and derive identity from pinned trust."""
    path = (
        Path.home()
        / ".config"
        / "quant-platform"
        / "readiness_signing_key.pem"
    )
    try:
        private_pem = path.read_bytes()
    except OSError as exc:
        raise MassResearchDisabledError(
            f"dedicated readiness signing key unavailable: {path}"
        ) from exc
    try:
        key = serialization.load_pem_private_key(private_pem, password=None)
    except (TypeError, ValueError) as exc:
        raise MassResearchDisabledError("invalid readiness private key PEM") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise MassResearchDisabledError("readiness signing key must be Ed25519")
    registry = ReadinessPublicKeyRegistry.load_pinned()
    key_id = registry._key_id_for_public_key(key.public_key())
    return _ReadyPublicationSigner(
        key_id=key_id,
        private_key=key,
        _factory_token=_READY_PUBLICATION_SIGNER_TOKEN,
    )

def _mint_bound_readiness(
    readiness_type: type[_R],
    manifest: Any,
    *,
    publisher: _ReadyPublicationSigner,
    db_path: str | Path,
    profile_binding: Any,
    ttl_seconds: int,
) -> _R:
    # Kept here rather than in ready_manifest.py so the private key never
    # crosses into a policy/parser module.
    from research.ready_manifest import (
        ReadyManifest,
        canonical_digest,
        is_sha256_digest,
        missing_ready_manifest_proofs,
        validate_ready_manifest_profile_binding,
    )

    if not isinstance(manifest, ReadyManifest):
        raise MassResearchDisabledError("ReadyManifest required")
    expected_scope = readiness_type.EXPECTED_SCOPE
    if manifest.publication_scope != expected_scope:
        raise MassResearchDisabledError(
            f"{expected_scope} readiness cannot be minted from "
            f"{manifest.publication_scope} ReadyManifest"
        )
    missing = missing_ready_manifest_proofs(manifest)
    if missing:
        raise MassResearchDisabledError(
            "ReadyManifest proofs UNKNOWN/MISSING: " + ", ".join(missing)
        )
    validate_ready_manifest_profile_binding(manifest, profile=profile_binding)
    artifact = Path(db_path)
    if not artifact.is_file():
        raise MassResearchDisabledError(
            f"READY snapshot artifact missing: {artifact}"
        )
    digest = hashlib.sha256()
    with artifact.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    db_digest = "sha256:" + digest.hexdigest()
    try:
        from paper_runtime import data_snapshot_id

        observed_snapshot_id = data_snapshot_id(artifact)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise MassResearchDisabledError(
            "READY publisher requires a verified snapshot artifact"
        ) from exc
    if observed_snapshot_id != manifest.snapshot_id:
        raise MassResearchDisabledError(
            "READY artifact snapshot_id does not match ReadyManifest"
        )
    if not is_sha256_digest(db_digest):
        raise MassResearchDisabledError(
            "ReadyManifest proofs UNKNOWN/MISSING: immutable_db_digest"
        )

    clock = _now()
    expires = clock + timedelta(seconds=max(60, ttl_seconds))
    evidence = {
        "manifest": manifest.to_dict(),
        "immutable_db_digest": db_digest,
    }
    body = {
        "attestation_id": str(uuid4()),
        "readiness_scope": expected_scope,
        "snapshot_id": manifest.snapshot_id,
        "profile_id": manifest.profile_id,
        "profile_version": manifest.profile_version,
        "profile_digest": manifest.profile_digest,
        "plan_ids": tuple(manifest.plan_ids),
        "plan_set_digest": manifest.plan_set_digest,
        "dependency_closure_digest": manifest.dependency_closure_digest,
        "dataset_ids": tuple(manifest.dataset_ids),
        "ready_state": "READY",
        "ready_manifest_digest": manifest.to_dict()["manifest_digest"],
        "immutable_db_digest": db_digest,
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
        "key_id": publisher.key_id,
        "issuer": "ReadyPublicationService/v3",
    }
    signature = publisher._sign({"format": readiness_type.FORMAT, **body})
    minted = readiness_type(signature=signature, **body)
    if not minted.is_valid(verifier=publisher._public_registry(), now=clock):
        raise MassResearchDisabledError(
            f"{readiness_type.__name__} scope or signed field invariants failed"
        )
    return minted


@dataclass(frozen=True)
class OperatorOverrideCapability:
    """Non-safety policy override only — never substitutes for readiness."""

    override_id: str
    reason: str
    operator_identity: str
    issued_at: str
    expires_at: str
    audit_artifact_digest: str
    scope: str

    ALLOWED_SCOPES = frozenset(
        {"hold_period", "selection_threshold", "single_extra_experiment"}
    )

    def __post_init__(self) -> None:
        if self.scope not in self.ALLOWED_SCOPES:
            raise ValueError(
                f"operator override scope {self.scope!r} not allowed; "
                "cannot bypass safety gates"
            )


class OperatorOverrideService:
    """Mints non-safety overrides only."""

    def __init__(self, *, audit_dir: Path | None = None) -> None:
        self._audit_dir = audit_dir

    def mint(
        self,
        *,
        reason: str,
        operator_identity: str,
        scope: str,
        ttl_seconds: int = 3600,
    ) -> OperatorOverrideCapability:
        if scope not in OperatorOverrideCapability.ALLOWED_SCOPES:
            raise ValueError(f"scope {scope!r} cannot bypass structural safety")
        if not reason.strip() or not operator_identity.strip():
            raise ValueError("reason and operator_identity required")
        if ttl_seconds < 60 or ttl_seconds > 86_400:
            raise ValueError("ttl_seconds must be in [60, 86400]")
        issued = _now()
        expires = issued + timedelta(seconds=ttl_seconds)
        override_id = str(uuid4())
        body = {
            "override_id": override_id,
            "reason": reason.strip(),
            "operator_identity": operator_identity.strip(),
            "issued_at": issued.isoformat(),
            "expires_at": expires.isoformat(),
            "scope": scope,
        }
        digest = _digest(body)
        if self._audit_dir is not None:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            (self._audit_dir / f"override-{override_id}.json").write_text(
                json.dumps({**body, "digest": digest}, indent=2), encoding="utf-8"
            )
        return OperatorOverrideCapability(
            override_id=override_id,
            reason=reason.strip(),
            operator_identity=operator_identity.strip(),
            issued_at=issued.isoformat(),
            expires_at=expires.isoformat(),
            audit_artifact_digest=digest,
            scope=scope,
        )


class ResearchReadinessService:
    """Public-key-only verifier for an already minted READY attestation."""

    def __init__(self) -> None:
        self._verifier = ReadinessPublicKeyRegistry.load_pinned()

    def verify(
        self,
        readiness: _VerifiedReadiness,
        *,
        expected_snapshot_id: str | None = None,
    ) -> _VerifiedReadiness:
        if not isinstance(readiness, _VerifiedReadiness):
            raise MassResearchDisabledError("signed readiness attestation required")
        return readiness.require_valid(
            expected_snapshot_id=expected_snapshot_id,
            verifier=self._verifier,
        )


def require_mass_research_start(
    *,
    budget: ResearchBudgetCapability | None,
    readiness: VerifiedMassReadiness | None,
    expected_snapshot_id: str | None = None,
) -> tuple[ResearchBudgetCapability, VerifiedMassReadiness]:
    """Fail-closed Mass start: only a valid Mass-scoped capability is accepted."""
    raise MassResearchDisabledError(
        "Mass Research remains disabled in Phase 6.3.1"
    )


__all__ = [
    "GovernedMassReadinessAuthority",
    "MASS_READINESS_ENABLED",
    "MassResearchDisabledError",
    "OperatorOverrideCapability",
    "OperatorOverrideService",
    "ReadinessPublicKeyRegistry",
    "ResearchReadinessService",
    "VerifiedMassReadiness",
    "VerifiedPilotReadiness",
    "VerifiedResearchReadiness",
    "load_verified_pilot_readiness",
    "require_mass_research_start",
]
