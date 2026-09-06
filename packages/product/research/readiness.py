"""Scope-separated research readiness attestations.

READY is a positive capability, not a count supplied by a scheduler. Pilot
and Mass attestations are deliberately different nominal types. This product
module is verify-only: a separately isolated READY publication service must
sign every attestation with its dedicated Ed25519 key. Verifiers receive
public keys only; receipt signing keys and HMAC compatibility fallbacks are
intentionally not consulted.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Mapping, final
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from paper_runtime.readiness_attestation import (
    ReadyAttestationVerificationError,
    derive_ready_authority_resource_digest as _derive_ready_authority_resource_digest,
    ready_authority_instance_id as _ready_authority_instance_id,
)

from selection.budget_ledger import (
    MassResearchDisabledError,
    ResearchBudgetCapability,
)
from execution.controlled_fill_contract import (
    CONTROLLED_FILL_CONTRACT_DIGEST,
    require_controlled_fill_contract_digest,
    ControlledFillContractError,
)
from selection.controlled_pilot_policy import (
    CONTROLLED_PILOT_IDENTITY,
    ControlledPilotPolicyError,
    require_controlled_pilot_identity,
)

READINESS_SIGNATURE_ALGORITHM = "Ed25519"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
MASS_READINESS_ENABLED: bool = False
_MASS_AUTHORITY_TOKEN = object()

READY_PUBLICATION_AUTHORITY_CONTRACT = "ready-publication-authority/v1"
READY_AUTHORITY_RESOURCE_FORMAT = "ready-authority-resource/v1"
READY_AUTHORITY_INSTANCE_SUFFIX = "v1"
_READY_ENVIRONMENTS = frozenset({"staging", "production"})
READY_PUBLICATION_REQUIRED_CHECKS = (
    "authenticated_immutable_ops_mirror",
    "canonical_exact_four_plan_closure_profile",
    "trusted_coverage_proof",
    "b0_b4_pass",
    "source_export_applied_generation_coherence",
    "independently_reopened_immutable_snapshot_copy",
)


class ReadyPublicationAuthorityPending(MassResearchDisabledError):
    """A dedicated READY issuer principal or remote service is unavailable."""


@dataclass(frozen=True, slots=True)
class ReadyPublicationAuthorityStatus:
    """Machine-readable fail-closed state for the external READY issuer."""

    state: str
    evidence_state: str
    contract_version: str
    required_checks: tuple[str, ...]
    mass_state: str
    reason: str

    def __post_init__(self) -> None:
        if (
            self.state not in {"PENDING", "ACTIVE"}
            or self.evidence_state not in {"UNKNOWN", "VERIFIED"}
            or self.mass_state != "DISABLED"
            or self.contract_version != READY_PUBLICATION_AUTHORITY_CONTRACT
            or self.required_checks != READY_PUBLICATION_REQUIRED_CHECKS
        ):
            raise ValueError("invalid READY publication authority status")


def ready_publication_authority_status() -> ReadyPublicationAuthorityStatus:
    """Report operational truth without mistaking filesystem preflight for liveness.

    Product code intentionally has no private-key type, private-key loader,
    signer factory, or issuer injection hook.  Passive status cannot prove a
    live Cloudflare/READY publisher.  Only a verified public-key attestation
    can do that, so this report remains PENDING/UNKNOWN until that evidence
    exists.
    """

    return ReadyPublicationAuthorityStatus(
        state="PENDING",
        evidence_state="UNKNOWN",
        contract_version=READY_PUBLICATION_AUTHORITY_CONTRACT,
        required_checks=READY_PUBLICATION_REQUIRED_CHECKS,
        mass_state="DISABLED",
        reason=(
            "Cloudflare/READY public-key issuer is unprovisioned; "
            "local six-principal publication is not on the Paper-only path"
        ),
    )


def require_ready_publication_authority() -> None:
    """Never mint a positive capability from passive endpoint metadata."""

    status = ready_publication_authority_status()
    raise ReadyPublicationAuthorityPending(
        f"READY authority {status.state}; evidence {status.evidence_state}; "
        f"contract={status.contract_version}; Mass={status.mass_state}"
    )


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(payload: Mapping[str, Any] | list[Any] | str) -> str:
    import hashlib

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


def ready_authority_instance_id(environment: str) -> str:
    """Return the sole governed READY authority instance for an environment."""

    try:
        return _ready_authority_instance_id(environment)
    except ReadyAttestationVerificationError as exc:
        raise MassResearchDisabledError(
            "READY authority environment must be staging or production"
        ) from exc


def derive_ready_authority_resource_digest(
    *,
    environment: str,
    authority_instance_id: str,
    snapshot_id: str,
    immutable_db_digest: str,
    ready_manifest_digest: str,
    signed_projection_document_digest: str,
) -> str:
    """Bind one signed READY decision to its environment and immutable inputs."""

    try:
        return _derive_ready_authority_resource_digest(
            environment=environment,
            authority_instance_id=authority_instance_id,
            snapshot_id=snapshot_id,
            immutable_db_digest=immutable_db_digest,
            ready_manifest_digest=ready_manifest_digest,
            signed_projection_document_digest=signed_projection_document_digest,
        )
    except ReadyAttestationVerificationError as exc:
        raise MassResearchDisabledError(
            "READY authority resource identity is invalid"
        ) from exc


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

    _keys: Mapping[tuple[str, str, str], Ed25519PublicKey]

    def __post_init__(self) -> None:
        normalized: dict[tuple[str, str, str], Ed25519PublicKey] = {}
        for raw_scope, key in self._keys.items():
            if (
                type(raw_scope) is not tuple
                or len(raw_scope) != 3
                or any(type(item) is not str or not item for item in raw_scope)
                or not isinstance(key, Ed25519PublicKey)
            ):
                raise MassResearchDisabledError(
                    "readiness registry entries require an exact "
                    "(environment, authority_instance_id, key_id) scope"
                )
            environment, authority_instance_id, key_id = raw_scope
            if (
                environment not in _READY_ENVIRONMENTS
                or authority_instance_id
                != ready_authority_instance_id(environment)
                or any(item != item.strip() for item in raw_scope)
            ):
                raise MassResearchDisabledError(
                    "readiness registry key scope is not canonical"
                )
            normalized[(environment, authority_instance_id, key_id)] = key
        object.__setattr__(self, "_keys", MappingProxyType(normalized))

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "ReadinessPublicKeyRegistry":
        expected_document_fields = {
            "schema_version",
            "purpose",
            "environment",
            "authority_instance_id",
            "keys",
        }
        if set(document) != expected_document_fields or document.get(
            "schema_version"
        ) != 2:
            raise MassResearchDisabledError(
                "readiness public key registry must be one exact v2 document"
            )
        environment = document.get("environment")
        authority_instance_id = document.get("authority_instance_id")
        if (
            environment not in {"staging", "production"}
            or document.get("purpose") != "readiness_attestation_verification"
            or authority_instance_id != ready_authority_instance_id(environment)
        ):
            raise MassResearchDisabledError(
                "readiness public key registry authority scope is invalid"
            )
        rows = document.get("keys")
        if not isinstance(rows, list) or not rows:
            raise MassResearchDisabledError("readiness public key registry keys missing")
        keys: dict[tuple[str, str, str], Ed25519PublicKey] = {}
        seen_ids: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise MassResearchDisabledError("invalid readiness public key row")
            if row.get("algorithm") != READINESS_SIGNATURE_ALGORITHM:
                raise MassResearchDisabledError(
                    "readiness public key algorithm must be Ed25519"
                )
            status = row.get("status")
            if status not in {"active", "revoked"}:
                raise MassResearchDisabledError(
                    "readiness public key status must be explicit active/revoked"
                )
            key_id = str(row.get("key_id") or "").strip()
            encoded = str(row.get("public_key_b64") or "").strip()
            try:
                raw = base64.b64decode(encoded, validate=True)
                key = Ed25519PublicKey.from_public_bytes(raw)
            except (ValueError, TypeError) as exc:
                raise MassResearchDisabledError(
                    f"invalid readiness public key for {key_id!r}"
                ) from exc
            if not key_id or key_id in seen_ids:
                raise MassResearchDisabledError(
                    "readiness public key ids must be non-empty and unique"
                )
            seen_ids.add(key_id)
            if status == "active":
                keys[(environment, authority_instance_id, key_id)] = key
        if len(keys) > 1:
            raise MassResearchDisabledError(
                "readiness public key registry must have at most one active key"
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
    def load_pinned(
        cls, *, expected_environment: str
    ) -> "ReadinessPublicKeyRegistry":
        """Load only the code-pinned lower-plane verifier trust root."""
        from paper_runtime.readiness_attestation import (
            ReadyAttestationVerificationError,
            load_pinned_readiness_public_keys,
        )

        try:
            return cls(
                load_pinned_readiness_public_keys(
                    expected_environment=expected_environment
                )
            )
        except ReadyAttestationVerificationError as exc:
            raise MassResearchDisabledError(
                "cannot load the pinned readiness public key registry"
            ) from exc

    def verify(
        self,
        *,
        expected_environment: str,
        authority_instance_id: str,
        key_id: str,
        body: Mapping[str, Any],
        signature: str,
    ) -> bool:
        if authority_instance_id != ready_authority_instance_id(
            expected_environment
        ):
            return False
        key = self._keys.get(
            (expected_environment, authority_instance_id, str(key_id))
        )
        if key is None:
            return False
        try:
            key.verify(_decode_signature(signature), _canonical_bytes(body))
        except (InvalidSignature, ValueError):
            return False
        return True


@dataclass(frozen=True, slots=True)
class _VerifiedReadiness:
    """Signed immutable capability shared by the two nominal scope types."""

    EXPECTED_SCOPE: ClassVar[str] = ""
    FORMAT: ClassVar[str] = "verified-readiness-attestation/v1"

    attestation_id: str
    environment: str
    authority_instance_id: str
    authority_resource_digest: str
    signed_projection_document_digest: str
    readiness_scope: str
    snapshot_id: str
    profile_id: str
    profile_version: str
    profile_digest: str
    plan_ids: tuple[str, ...]
    plan_set_digest: str
    dependency_closure_digest: str
    universe_rule_digest: str
    resolved_universe_digest: str
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
    identity: str
    fill_contract_digest: str = CONTROLLED_FILL_CONTRACT_DIGEST
    issuer: str = "ReadyPublicationService/v3"

    def __post_init__(self) -> None:
        concrete_type = type(self)
        if concrete_type is VerifiedPilotReadiness:
            expected_scope = "PILOT"
        elif concrete_type is VerifiedMassReadiness:
            expected_scope = "MASS"
        else:
            raise ValueError("readiness capability requires an exact final scope type")
        environment = object.__getattribute__(self, "environment")
        authority_instance_id = object.__getattribute__(self, "authority_instance_id")
        authority_resource_digest = object.__getattribute__(
            self, "authority_resource_digest"
        )
        signed_projection_document_digest = object.__getattribute__(
            self, "signed_projection_document_digest"
        )
        if (
            type(environment) is not str
            or environment not in _READY_ENVIRONMENTS
            or authority_instance_id != ready_authority_instance_id(environment)
            or not _is_sha256(authority_resource_digest)
            or not _is_sha256(signed_projection_document_digest)
        ):
            raise ValueError("readiness authority environment/resource scope is invalid")
        readiness_scope = object.__getattribute__(self, "readiness_scope")
        if type(readiness_scope) is not str or readiness_scope != expected_scope:
            raise ValueError(
                f"{concrete_type.__name__} requires readiness_scope "
                f"{expected_scope!r}"
            )
        identity = object.__getattribute__(self, "identity")
        if concrete_type is VerifiedPilotReadiness:
            try:
                object.__setattr__(
                    self, "identity", require_controlled_pilot_identity(identity)
                )
            except ControlledPilotPolicyError as exc:
                raise ValueError(
                    "VerifiedPilotReadiness identity must be exactly "
                    f"{CONTROLLED_PILOT_IDENTITY!r}"
                ) from exc
        elif identity == CONTROLLED_PILOT_IDENTITY:
            raise MassResearchDisabledError(
                "VerifiedMassReadiness cannot carry controlled_pilot_v1"
            )
        if concrete_type is VerifiedPilotReadiness:
            try:
                object.__setattr__(
                    self,
                    "fill_contract_digest",
                    require_controlled_fill_contract_digest(
                        object.__getattribute__(self, "fill_contract_digest")
                    ),
                )
            except ControlledFillContractError as exc:
                raise ValueError(
                    "VerifiedPilotReadiness fill_contract_digest must be the "
                    "governed morning-close to same-day afternoon-close contract"
                ) from exc

    def to_canonical_body(self) -> dict[str, Any]:
        return {
            "format": self.FORMAT,
            "attestation_id": self.attestation_id,
            "environment": self.environment,
            "authority_instance_id": self.authority_instance_id,
            "authority_resource_digest": self.authority_resource_digest,
            "signed_projection_document_digest": (
                self.signed_projection_document_digest
            ),
            "readiness_scope": self.readiness_scope,
            "identity": self.identity,
            "snapshot_id": self.snapshot_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_digest": self.profile_digest,
            "plan_ids": list(self.plan_ids),
            "plan_set_digest": self.plan_set_digest,
            "dependency_closure_digest": self.dependency_closure_digest,
            "universe_rule_digest": self.universe_rule_digest,
            "resolved_universe_digest": self.resolved_universe_digest,
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
            "fill_contract_digest": self.fill_contract_digest,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete signed capability for immutable retention."""
        return {**self.to_canonical_body(), "signature": self.signature}

    def is_valid(self, *, expected_environment: str) -> bool:
        """Verify only through the configured pinned product trust root.

        The DTO deliberately accepts no caller registry, expected binding, or
        clock. Consumers that need an expected artifact identity use the
        module verifier, which also materializes the exact final type once.
        """

        try:
            self.require_valid(expected_environment=expected_environment)
        except (MassResearchDisabledError, TypeError, ValueError):
            return False
        return True

    def require_valid(self, *, expected_environment: str) -> "_VerifiedReadiness":
        """Return a freshly materialized, pinned capability or fail closed."""

        if type(self) is VerifiedPilotReadiness:
            return verify_pinned_pilot_readiness(
                self, expected_environment=expected_environment
            )
        raise MassResearchDisabledError(
            f"{type(self).__name__} cannot be verified by an enabled authority"
        )


@final
class VerifiedPilotReadiness(_VerifiedReadiness):
    """Capability valid only for an exact controlled-pilot plan set."""

    __slots__ = ()
    EXPECTED_SCOPE = "PILOT"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        del cls, kwargs
        raise TypeError("VerifiedPilotReadiness is final")


def load_verified_pilot_readiness(
    path: str | Path,
    *,
    expected_environment: str,
    expected_snapshot_id: str | None = None,
    expected_ready_manifest_digest: str | None = None,
    expected_authority_resource_digest: str | None = None,
) -> VerifiedPilotReadiness:
    """Strictly load and verify an exact-four readiness sidecar.

    This is a public-key-only consumer boundary.  The caller can narrow the
    expected immutable publication identity, but cannot inject a verifier,
    choose an alternate plan/profile binding, or bypass expiry checks.
    """
    source = Path(path)
    try:
        raw_document = source.read_bytes()
    except OSError as exc:
        raise MassResearchDisabledError(
            f"cannot load pilot readiness sidecar: {source}"
        ) from exc
    return _load_verified_pilot_readiness_bytes(
        raw_document,
        expected_environment=expected_environment,
        expected_snapshot_id=expected_snapshot_id,
        expected_ready_manifest_digest=expected_ready_manifest_digest,
        expected_authority_resource_digest=expected_authority_resource_digest,
    )


def _load_verified_pilot_readiness_bytes(
    raw_document: bytes,
    *,
    expected_environment: str,
    expected_snapshot_id: str | None = None,
    expected_ready_manifest_digest: str | None = None,
    expected_authority_resource_digest: str | None = None,
) -> VerifiedPilotReadiness:
    """Verify descriptor-pinned sidecar bytes without reopening a pathname."""

    if type(raw_document) is not bytes or not raw_document:
        raise MassResearchDisabledError(
            "pilot readiness sidecar must be exact non-empty bytes"
        )
    from paper_runtime.readiness_attestation import (
        ReadyAttestationVerificationError,
        decode_strict_ready_json,
    )

    try:
        document = decode_strict_ready_json(raw_document)
    except ReadyAttestationVerificationError as exc:
        raise MassResearchDisabledError(
            "pilot readiness sidecar JSON is ambiguous or invalid"
        ) from exc
    if type(document) is not dict:
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
            type(value) is not list
            or not value
            or any(type(item) is not str or not item for item in value)
        ):
            raise MassResearchDisabledError(
                f"pilot readiness sidecar {field} must be a non-empty string array"
            )
        init_payload[field] = tuple(value)
    for field, value in init_payload.items():
        if field in {"plan_ids", "dataset_ids"}:
            continue
        if type(value) is not str or not value:
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
    return verify_pinned_pilot_readiness(
        readiness,
        expected_environment=expected_environment,
        expected_snapshot_id=expected_snapshot_id,
        expected_ready_manifest_digest=expected_ready_manifest_digest,
        expected_authority_resource_digest=expected_authority_resource_digest,
    )


@final
class VerifiedMassReadiness(_VerifiedReadiness):
    """Capability valid only for an explicit Mass data profile."""

    __slots__ = ()
    EXPECTED_SCOPE = "MASS"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        del cls, kwargs
        raise TypeError("VerifiedMassReadiness is final")


_READINESS_SEQUENCE_FIELDS = frozenset({"plan_ids", "dataset_ids"})


def _materialize_exact_pilot_readiness(
    readiness: object,
) -> dict[str, Any]:
    """Read every exact capability field once into closed built-in values."""

    if type(readiness) is not VerifiedPilotReadiness:
        raise MassResearchDisabledError(
            "exact VerifiedPilotReadiness required; subclasses are rejected"
        )
    frozen: dict[str, Any] = {}
    for field in fields(VerifiedPilotReadiness):
        value = object.__getattribute__(readiness, field.name)
        if field.name in _READINESS_SEQUENCE_FIELDS:
            if (
                type(value) is not tuple
                or not value
                or any(type(item) is not str or not item for item in value)
            ):
                raise MassResearchDisabledError(
                    f"readiness {field.name} must be an exact non-empty string tuple"
                )
            frozen[field.name] = tuple(value)
        else:
            if type(value) is not str or not value:
                raise MassResearchDisabledError(
                    f"readiness {field.name} must be an exact non-empty string"
                )
            frozen[field.name] = value
    return frozen


def _canonical_pilot_body(values: Mapping[str, Any]) -> dict[str, Any]:
    """Build signed bytes from the one frozen value set, never dynamic methods."""

    return {
        "format": VerifiedPilotReadiness.FORMAT,
        "attestation_id": values["attestation_id"],
        "environment": values["environment"],
        "authority_instance_id": values["authority_instance_id"],
        "authority_resource_digest": values["authority_resource_digest"],
        "signed_projection_document_digest": values[
            "signed_projection_document_digest"
        ],
        "readiness_scope": values["readiness_scope"],
        "identity": values["identity"],
        "snapshot_id": values["snapshot_id"],
        "profile_id": values["profile_id"],
        "profile_version": values["profile_version"],
        "profile_digest": values["profile_digest"],
        "plan_ids": list(values["plan_ids"]),
        "plan_set_digest": values["plan_set_digest"],
        "dependency_closure_digest": values["dependency_closure_digest"],
        "universe_rule_digest": values["universe_rule_digest"],
        "resolved_universe_digest": values["resolved_universe_digest"],
        "dataset_ids": list(values["dataset_ids"]),
        "ready_state": values["ready_state"],
        "ready_manifest_digest": values["ready_manifest_digest"],
        "immutable_db_digest": values["immutable_db_digest"],
        "coverage_policy_version": values["coverage_policy_version"],
        "coverage_policy_digest": values["coverage_policy_digest"],
        "coverage_proof_digest": values["coverage_proof_digest"],
        "governed_membership_digest": values["governed_membership_digest"],
        "raw_proof_digest": values["raw_proof_digest"],
        "receipt_proof_digest": values["receipt_proof_digest"],
        "validation_proof_digest": values["validation_proof_digest"],
        "b0_quality_proof_digest": values["b0_quality_proof_digest"],
        "b4_quality_proof_digest": values["b4_quality_proof_digest"],
        "source_generation": values["source_generation"],
        "export_cursor": values["export_cursor"],
        "applied_cursor": values["applied_cursor"],
        "verified_at": values["verified_at"],
        "expires_at": values["expires_at"],
        "evidence_digest": values["evidence_digest"],
        "key_id": values["key_id"],
        "issuer": values["issuer"],
        "fill_contract_digest": values["fill_contract_digest"],
    }


def _verify_exact_pilot_readiness_values(
    readiness: object,
    *,
    registry: ReadinessPublicKeyRegistry,
    clock: datetime,
    expected_environment: str,
    expected_snapshot_id: str | None = None,
    expected_ready_manifest_digest: str | None = None,
    expected_authority_resource_digest: str | None = None,
) -> VerifiedPilotReadiness:
    """Non-overridable verifier over one frozen exact capability value set."""

    if type(registry) is not ReadinessPublicKeyRegistry:
        raise MassResearchDisabledError(
            "exact pinned readiness public-key registry required"
        )
    if clock.tzinfo is None:
        raise MassResearchDisabledError("readiness verifier clock must be aware")
    if (
        type(expected_environment) is not str
        or expected_environment not in _READY_ENVIRONMENTS
    ):
        raise MassResearchDisabledError(
            "expected READY environment must be staging or production"
        )
    if expected_snapshot_id is not None and type(expected_snapshot_id) is not str:
        raise MassResearchDisabledError("expected snapshot id must be an exact string")
    if (
        expected_ready_manifest_digest is not None
        and type(expected_ready_manifest_digest) is not str
    ):
        raise MassResearchDisabledError(
            "expected ReadyManifest digest must be an exact string"
        )
    if (
        expected_authority_resource_digest is not None
        and not _is_sha256(expected_authority_resource_digest)
    ):
        raise MassResearchDisabledError(
            "expected READY authority resource digest must be canonical sha256"
        )
    values = _materialize_exact_pilot_readiness(readiness)

    from paper_runtime.readiness_attestation import (
        MAX_READY_ATTESTATION_TTL_SECONDS,
        MIN_READY_ATTESTATION_TTL_SECONDS,
    )
    from research.ready_manifest import load_exact_four_pilot_ready_binding
    from research.universe_contract import EXACT_FOUR_UNIVERSE_RULE_DIGEST

    binding = load_exact_four_pilot_ready_binding()
    digest_fields = (
        "snapshot_id",
        "profile_digest",
        "plan_set_digest",
        "dependency_closure_digest",
        "universe_rule_digest",
        "resolved_universe_digest",
        "ready_manifest_digest",
        "immutable_db_digest",
        "coverage_policy_digest",
        "coverage_proof_digest",
        "governed_membership_digest",
        "raw_proof_digest",
        "receipt_proof_digest",
        "validation_proof_digest",
        "b0_quality_proof_digest",
        "b4_quality_proof_digest",
        "evidence_digest",
        "authority_resource_digest",
        "signed_projection_document_digest",
    )
    if any(not _is_sha256(values[field]) for field in digest_fields):
        raise MassResearchDisabledError("readiness proof digest is malformed")
    derived_authority_resource_digest = derive_ready_authority_resource_digest(
        environment=expected_environment,
        authority_instance_id=values["authority_instance_id"],
        snapshot_id=values["snapshot_id"],
        immutable_db_digest=values["immutable_db_digest"],
        ready_manifest_digest=values["ready_manifest_digest"],
        signed_projection_document_digest=values[
            "signed_projection_document_digest"
        ],
    )
    if (
        values["readiness_scope"] != "PILOT"
        or values["identity"] != CONTROLLED_PILOT_IDENTITY
        or values["environment"] != expected_environment
        or values["authority_instance_id"]
        != ready_authority_instance_id(expected_environment)
        or values["ready_state"] != "READY"
        or values["issuer"] != "ReadyPublicationService/v3"
        or values["profile_id"] != binding.profile_id
        or values["profile_version"] != binding.profile_version
        or values["profile_digest"] != binding.profile_digest
        or values["plan_ids"] != binding.plan_ids
        or values["plan_set_digest"] != binding.plan_set_digest
        or values["dependency_closure_digest"] != binding.closure_set_digest
        or values["universe_rule_digest"] != EXACT_FOUR_UNIVERSE_RULE_DIGEST
        or values["dataset_ids"] != binding.required_datasets
        or values["source_generation"] != values["export_cursor"]
        or values["export_cursor"] != values["applied_cursor"]
        or values["authority_resource_digest"]
        != derived_authority_resource_digest
        or (
            expected_snapshot_id is not None
            and values["snapshot_id"] != expected_snapshot_id
        )
        or (
            expected_ready_manifest_digest is not None
            and values["ready_manifest_digest"]
            != expected_ready_manifest_digest
        )
        or (
            expected_authority_resource_digest is not None
            and values["authority_resource_digest"]
            != expected_authority_resource_digest
        )
    ):
        raise MassResearchDisabledError(
            "pilot readiness does not match the canonical exact-four binding"
        )
    try:
        verified_at = datetime.fromisoformat(
            values["verified_at"].replace("Z", "+00:00")
        )
        expires_at = datetime.fromisoformat(
            values["expires_at"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise MassResearchDisabledError(
            "pilot readiness timestamps are malformed"
        ) from exc
    if verified_at.tzinfo is None or expires_at.tzinfo is None:
        raise MassResearchDisabledError(
            "pilot readiness timestamps must be timezone-aware"
        )
    ttl = expires_at - verified_at
    if (
        ttl < timedelta(seconds=MIN_READY_ATTESTATION_TTL_SECONDS)
        or ttl > timedelta(seconds=MAX_READY_ATTESTATION_TTL_SECONDS)
        or verified_at > clock + timedelta(minutes=5)
        or clock > expires_at
    ):
        raise MassResearchDisabledError(
            "pilot readiness is expired or time-incoherent"
        )
    key = object.__getattribute__(registry, "_keys").get(
        (
            expected_environment,
            values["authority_instance_id"],
            values["key_id"],
        )
    )
    if key is None:
        raise MassResearchDisabledError("pilot readiness issuer is untrusted")
    body = _canonical_pilot_body(values)
    try:
        key.verify(_decode_signature(values["signature"]), _canonical_bytes(body))
    except (InvalidSignature, ValueError) as exc:
        raise MassResearchDisabledError(
            "pilot readiness signature is invalid"
        ) from exc
    return VerifiedPilotReadiness(**values)


def verify_pinned_pilot_readiness(
    readiness: object,
    *,
    expected_environment: str,
    expected_snapshot_id: str | None = None,
    expected_ready_manifest_digest: str | None = None,
    expected_authority_resource_digest: str | None = None,
) -> VerifiedPilotReadiness:
    """Verify an exact pilot capability against only the pinned trust root."""

    return _verify_exact_pilot_readiness_values(
        readiness,
        registry=ReadinessPublicKeyRegistry.load_pinned(
            expected_environment=expected_environment
        ),
        clock=_now(),
        expected_environment=expected_environment,
        expected_snapshot_id=expected_snapshot_id,
        expected_ready_manifest_digest=expected_ready_manifest_digest,
        expected_authority_resource_digest=expected_authority_resource_digest,
    )


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

    def verify(
        self,
        readiness: _VerifiedReadiness,
        *,
        expected_environment: str,
        expected_snapshot_id: str | None = None,
    ) -> _VerifiedReadiness:
        if type(readiness) is VerifiedPilotReadiness:
            return verify_pinned_pilot_readiness(
                readiness,
                expected_environment=expected_environment,
                expected_snapshot_id=expected_snapshot_id,
            )
        if type(readiness) is VerifiedMassReadiness:
            raise MassResearchDisabledError(
                "Mass readiness verification remains disabled in Phase 6.3.1"
            )
        raise MassResearchDisabledError("signed readiness attestation required")


def require_mass_research_start(
    *,
    budget: ResearchBudgetCapability | None,
    readiness: VerifiedMassReadiness | None,
    expected_snapshot_id: str | None = None,
) -> tuple[ResearchBudgetCapability, VerifiedMassReadiness]:
    """Fail-closed Mass start: only a valid Mass-scoped capability is accepted."""
    del budget, expected_snapshot_id
    if type(readiness) is VerifiedPilotReadiness:
        raise MassResearchDisabledError(
            "Mass Research rejects VerifiedPilotReadiness"
        )
    raise MassResearchDisabledError(
        "Mass Research remains disabled; VerifiedMassReadiness cannot start it"
    )


__all__ = [
    "GovernedMassReadinessAuthority",
    "MASS_READINESS_ENABLED",
    "MassResearchDisabledError",
    "OperatorOverrideCapability",
    "OperatorOverrideService",
    "ReadinessPublicKeyRegistry",
    "ReadyPublicationAuthorityPending",
    "ReadyPublicationAuthorityStatus",
    "ResearchReadinessService",
    "READY_PUBLICATION_AUTHORITY_CONTRACT",
    "READY_PUBLICATION_REQUIRED_CHECKS",
    "VerifiedMassReadiness",
    "VerifiedPilotReadiness",
    "VerifiedResearchReadiness",
    "load_verified_pilot_readiness",
    "ready_publication_authority_status",
    "require_ready_publication_authority",
    "require_mass_research_start",
    "verify_pinned_pilot_readiness",
]
