"""Verify-only READY attestation boundary for immutable paper snapshots.

This lower-plane module owns no private key and exposes no signing callback.
It verifies a production snapshot's sidecar against a code-pinned public-key
registry and the canonical exact-four binding before ``paper_runtime`` treats
the snapshot as READY.  Product code may add stricter policy checks, but the
runtime never imports the product plane to establish cryptographic trust.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


READINESS_ATTESTATION_FORMAT = "verified-readiness-attestation/v1"
READY_MANIFEST_FORMAT = "ready-manifest/v1"
READINESS_SIGNATURE_ALGORITHM = "Ed25519"
MIN_READY_ATTESTATION_TTL_SECONDS = 60
MAX_READY_ATTESTATION_TTL_SECONDS = 86_400
PINNED_READINESS_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:17c2978493dc3be0d72f3b94dbefd09aaff91c021f9e3d109464b6a7edcefa50"
)
PINNED_STAGING_READINESS_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:30a7a04c4cca8ed96f0813423e1ceb049d4d80c36c0db62c01e327354e5c8aae"
)
_PINNED_READINESS_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "ready"
    / "readiness_verify_public_keys.json"
)
_PINNED_STAGING_READINESS_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "ready"
    / "readiness_verify_public_keys.staging.json"
)
_READY_ENVIRONMENTS = frozenset({"staging", "production"})
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")

# Compile-time consumer pin for the sole accepted pilot lineage.  Updating any
# plan/profile/closure requires an explicit code review at this trust boundary.
EXACT_FOUR_PROFILE_ID = "controlled-pilot/exact-four"
EXACT_FOUR_PROFILE_VERSION = "research-data-profile-set/v1"
EXACT_FOUR_PROFILE_DIGEST = (
    "sha256:6e5af32e15d89498cd754f954c9188f785a9841300df40e46cfe1f44903797cc"
)
EXACT_FOUR_PLAN_IDS = (
    "exp-mdh-hold10-momentum",
    "exp-xs-hold10-mom5",
    "exp-event-post-hold5",
    "exp-fund-hold10-value-mom",
)
EXACT_FOUR_PLAN_SET_DIGEST = (
    "sha256:3da05a67d22d8f8d65b9fc2e36db089c618221f32749b087eeb9e99ff278a0c8"
)
EXACT_FOUR_CLOSURE_DIGEST = (
    "sha256:c2caee361198b40ba261cf9ff32bf461869d801882242d64611ee7755fc2cea4"
)
EXACT_FOUR_UNIVERSE_RULE_DIGEST = (
    "sha256:2d8b9b49ff0b99e9da1f206f839aeb5b1f88e264be4796cd17954ea181a7e860"
)
EXACT_FOUR_DATASET_IDS = (
    "equities_bars_daily",
    "equities_master",
    "fins_summary",
    "indices_bars_daily_topix",
    "markets_calendar",
)

_READY_MANIFEST_FIELDS = {
    "format",
    "snapshot_id",
    "publication_scope",
    "profile_id",
    "profile_version",
    "profile_digest",
    "plan_ids",
    "plan_set_digest",
    "dependency_closure_digest",
    "universe_rule_digest",
    "resolved_universe_digest",
    "dataset_ids",
    "dataset_membership_digest",
    "coverage_policy_version",
    "coverage_policy_digest",
    "coverage_proof_digest",
    "raw_proof_digest",
    "receipt_proof_digest",
    "validation_proof_digest",
    "b0_proof_digest",
    "b4_proof_digest",
    "source_generation",
    "applied_sync_generation",
    "export_cursor",
    "applied_cursor",
    "pit_contract_digests",
    "feature_generation",
    "catalog_generation",
    "created_at",
    "published_at",
    "manifest_digest",
}
_ATTESTATION_FIELDS = {
    "format",
    "attestation_id",
    "environment",
    "authority_instance_id",
    "authority_resource_digest",
    "signed_projection_document_digest",
    "readiness_scope",
    "snapshot_id",
    "profile_id",
    "profile_version",
    "profile_digest",
    "plan_ids",
    "plan_set_digest",
    "dependency_closure_digest",
    "universe_rule_digest",
    "resolved_universe_digest",
    "dataset_ids",
    "ready_state",
    "ready_manifest_digest",
    "immutable_db_digest",
    "coverage_policy_version",
    "coverage_policy_digest",
    "coverage_proof_digest",
    "governed_membership_digest",
    "raw_proof_digest",
    "receipt_proof_digest",
    "validation_proof_digest",
    "b0_quality_proof_digest",
    "b4_quality_proof_digest",
    "source_generation",
    "export_cursor",
    "applied_cursor",
    "verified_at",
    "expires_at",
    "evidence_digest",
    "key_id",
    "signature",
    "issuer",
}


class ReadyAttestationVerificationError(RuntimeError):
    """A snapshot READY sidecar or its pinned trust root is invalid."""


def _reject_duplicate_object_pairs(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ReadyAttestationVerificationError(
                f"READY JSON contains duplicate key {key!r}"
            )
        document[key] = value
    return document


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ReadyAttestationVerificationError(
        f"READY JSON contains non-finite constant {value!r}"
    )


def decode_strict_ready_json(payload: bytes) -> Any:
    """Decode closed READY JSON without cross-parser ambiguity."""

    if type(payload) is not bytes:
        raise ReadyAttestationVerificationError(
            "READY JSON must be one immutable byte string"
        )
    try:
        return json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_object_pairs,
            parse_constant=_reject_nonfinite_json_constant,
        )
    except ReadyAttestationVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadyAttestationVerificationError("READY JSON is invalid") from exc


def _materialize_exact_json(value: Any, *, field: str) -> Any:
    """Snapshot one JSON value and reject subclass-driven observations.

    ``ReadyManifest`` is supplied by a caller while the attestation document
    is decoded locally.  Both must nevertheless cross the verifier through the
    same closed, exact-built-in representation.  A shallow ``dict()`` copy is
    insufficient because a nested ``str``/``list``/``dict`` subclass can make
    digesting, semantic validation, and later use observe different values.
    """

    if type(value) is dict:
        items = tuple(value.items())
        frozen: dict[str, Any] = {}
        for key, item in items:
            if type(key) is not str or key in frozen:
                raise ReadyAttestationVerificationError(
                    f"{field} keys must be unique exact strings"
                )
            frozen[key] = _materialize_exact_json(
                item,
                field=f"{field}.{key}",
            )
        return frozen
    if type(value) is list:
        items = tuple(value)
        return [
            _materialize_exact_json(item, field=f"{field}[{index}]")
            for index, item in enumerate(items)
        ]
    if type(value) in {str, int, bool, type(None)}:
        return value
    raise ReadyAttestationVerificationError(
        f"{field} must contain only exact JSON built-in values"
    )


def _deep_immutable_json(value: Any) -> Any:
    """Return an immutable view of an already materialized JSON value."""

    if type(value) is dict:
        return MappingProxyType(
            {key: _deep_immutable_json(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_immutable_json(item) for item in value)
    return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _is_sha256(value: Any) -> bool:
    return type(value) is str and bool(_SHA256_RE.fullmatch(value))


def _require_environment(value: object) -> str:
    if type(value) is not str or value not in _READY_ENVIRONMENTS:
        raise ReadyAttestationVerificationError(
            "READY verifier requires an explicit staging or production environment"
        )
    return value


def ready_authority_instance_id(environment: str) -> str:
    return f"ready-authority/{_require_environment(environment)}/v1"


def derive_ready_authority_resource_digest(
    *,
    environment: str,
    authority_instance_id: str,
    snapshot_id: str,
    immutable_db_digest: str,
    ready_manifest_digest: str,
    signed_projection_document_digest: str,
) -> str:
    selected = _require_environment(environment)
    if authority_instance_id != ready_authority_instance_id(selected):
        raise ReadyAttestationVerificationError(
            "READY authority instance crosses the expected environment"
        )
    values = (
        snapshot_id,
        immutable_db_digest,
        ready_manifest_digest,
        signed_projection_document_digest,
    )
    if any(not _is_sha256(value) for value in values):
        raise ReadyAttestationVerificationError(
            "READY authority resource inputs require canonical sha256 digests"
        )
    return _digest(
        {
            "format": "ready-authority-resource/v1",
            "environment": selected,
            "authority_instance_id": authority_instance_id,
            "snapshot_id": snapshot_id,
            "immutable_db_digest": immutable_db_digest,
            "ready_manifest_digest": ready_manifest_digest,
            "signed_projection_document_digest": (
                signed_projection_document_digest
            ),
        }
    )


def _registry_contract(environment: str) -> tuple[Path, str]:
    selected = _require_environment(environment)
    if selected == "staging":
        return (
            _PINNED_STAGING_READINESS_REGISTRY_PATH,
            PINNED_STAGING_READINESS_REGISTRY_DOCUMENT_DIGEST,
        )
    return (
        _PINNED_READINESS_REGISTRY_PATH,
        PINNED_READINESS_REGISTRY_DOCUMENT_DIGEST,
    )


def _load_pinned_readiness_public_keys(
    *, expected_environment: str
) -> dict[tuple[str, str, str], Ed25519PublicKey]:
    """Load the exact committed registry generation; no path/env injection."""

    selected = _require_environment(expected_environment)
    registry_path, registry_digest = _registry_contract(selected)
    try:
        document = decode_strict_ready_json(
            registry_path.read_bytes()
        )
    except (OSError, ReadyAttestationVerificationError) as exc:
        raise ReadyAttestationVerificationError(
            "cannot load the pinned readiness public-key registry"
        ) from exc
    if type(document) is not dict:
        raise ReadyAttestationVerificationError(
            "pinned readiness public-key registry is not an object"
        )
    if _digest(document) != registry_digest:
        raise ReadyAttestationVerificationError(
            "pinned readiness public-key registry digest mismatch"
        )
    if (
        set(document)
        != {
            "schema_version",
            "purpose",
            "environment",
            "authority_instance_id",
            "keys",
        }
        or document.get("schema_version") != 2
        or document.get("purpose") != "readiness_attestation_verification"
        or document.get("environment") != selected
        or document.get("authority_instance_id")
        != ready_authority_instance_id(selected)
        or type(document.get("keys")) is not list
    ):
        raise ReadyAttestationVerificationError(
            "pinned readiness public-key registry is invalid"
        )
    keys: dict[tuple[str, str, str], Ed25519PublicKey] = {}
    seen: set[str] = set()
    for row in document["keys"]:
        if (
            type(row) is not dict
            or set(row) != {"key_id", "algorithm", "public_key_b64", "status"}
            or row.get("algorithm") != READINESS_SIGNATURE_ALGORITHM
            or row.get("status") not in {"active", "revoked"}
            or type(row.get("key_id")) is not str
        ):
            raise ReadyAttestationVerificationError(
                "pinned readiness public-key registry entry is invalid"
            )
        key_id = row["key_id"].strip()
        if not key_id or key_id in seen:
            raise ReadyAttestationVerificationError(
                "pinned readiness public-key ids must be non-empty and unique"
            )
        seen.add(key_id)
        try:
            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(row["public_key_b64"], validate=True)
            )
        except (TypeError, ValueError) as exc:
            raise ReadyAttestationVerificationError(
                f"invalid pinned readiness public key: {key_id}"
            ) from exc
        if row["status"] == "active":
            keys[(selected, document["authority_instance_id"], key_id)] = public_key
    if len(keys) > 1:
        raise ReadyAttestationVerificationError(
            "pinned readiness registry has multiple active keys"
        )
    return keys


def load_pinned_readiness_public_keys(
    *, expected_environment: str
) -> Mapping[tuple[str, str, str], Ed25519PublicKey]:
    """Return a copy of the code-pinned verify-only key registry."""

    return dict(
        _load_pinned_readiness_public_keys(
            expected_environment=expected_environment
        )
    )


def _validate_exact_four_ready_manifest(
    manifest: Mapping[str, Any], *, expected_snapshot_id: str
) -> dict[str, Any]:
    if type(expected_snapshot_id) is not str or not _is_sha256(
        expected_snapshot_id
    ):
        raise ReadyAttestationVerificationError(
            "expected snapshot id must be an exact sha256 string"
        )
    frozen = _materialize_exact_json(manifest, field="embedded ReadyManifest")
    if type(frozen) is not dict or set(frozen) != _READY_MANIFEST_FIELDS:
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest shape is invalid"
        )
    declared_digest = frozen.get("manifest_digest")
    body = {key: value for key, value in frozen.items() if key != "manifest_digest"}
    if not _is_sha256(declared_digest) or _digest(body) != declared_digest:
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest digest is invalid"
        )
    if (
        frozen.get("format") != READY_MANIFEST_FORMAT
        or frozen.get("snapshot_id") != expected_snapshot_id
        or frozen.get("publication_scope") != "PILOT"
        or frozen.get("profile_id") != EXACT_FOUR_PROFILE_ID
        or frozen.get("profile_version") != EXACT_FOUR_PROFILE_VERSION
        or frozen.get("profile_digest") != EXACT_FOUR_PROFILE_DIGEST
        or frozen.get("plan_ids") != list(EXACT_FOUR_PLAN_IDS)
        or frozen.get("plan_set_digest") != EXACT_FOUR_PLAN_SET_DIGEST
        or frozen.get("dependency_closure_digest") != EXACT_FOUR_CLOSURE_DIGEST
        or frozen.get("universe_rule_digest")
        != EXACT_FOUR_UNIVERSE_RULE_DIGEST
        or frozen.get("dataset_ids") != list(EXACT_FOUR_DATASET_IDS)
    ):
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest is not the canonical exact-four binding"
        )
    digest_fields = (
        "resolved_universe_digest",
        "dataset_membership_digest",
        "coverage_policy_digest",
        "coverage_proof_digest",
        "raw_proof_digest",
        "receipt_proof_digest",
        "validation_proof_digest",
        "b0_proof_digest",
        "b4_proof_digest",
        "feature_generation",
        "catalog_generation",
    )
    if any(not _is_sha256(frozen.get(field)) for field in digest_fields):
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest has missing proof digests"
        )
    # ReadyManifest computes the membership digest over the array itself, not
    # a named wrapper. Keep that exact representation at this boundary.
    expected_membership_digest = "sha256:" + hashlib.sha256(
        json.dumps(
            sorted(set(EXACT_FOUR_DATASET_IDS)),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    if frozen.get("dataset_membership_digest") != expected_membership_digest:
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest dataset membership digest is invalid"
        )
    from data_contracts.coverage import coverage_policy_set_binding

    expected_policy = coverage_policy_set_binding(list(EXACT_FOUR_DATASET_IDS))
    if (
        frozen.get("coverage_policy_version") != expected_policy["policy_version"]
        or frozen.get("coverage_policy_digest") != expected_policy["policy_digest"]
    ):
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest Coverage policy binding is invalid"
        )
    generations = tuple(
        frozen.get(field)
        for field in (
            "source_generation",
            "applied_sync_generation",
            "export_cursor",
            "applied_cursor",
        )
    )
    if (
        any(type(value) is not str or not value for value in generations)
        or len(set(generations)) != 1
    ):
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest generation/cursor chain is not current"
        )
    pit = frozen.get("pit_contract_digests")
    if (
        type(pit) is not dict
        or not pit
        or any(type(key) is not str or not _is_sha256(value) for key, value in pit.items())
    ):
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest PIT proof is invalid"
        )
    try:
        created_at = datetime.fromisoformat(
            frozen["created_at"].replace("Z", "+00:00")
        )
        published_at = datetime.fromisoformat(
            frozen["published_at"].replace("Z", "+00:00")
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest timestamps are invalid"
        ) from exc
    if (
        created_at.tzinfo is None
        or published_at.tzinfo is None
        or published_at < created_at
    ):
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest timestamps are time-incoherent"
        )
    return frozen


def verify_pinned_pilot_snapshot_attestation(
    attestation_bytes: bytes,
    *,
    snapshot_id: str,
    ready_manifest: Mapping[str, Any],
    immutable_db_digest: str,
    expected_environment: str,
) -> Mapping[str, Any]:
    """Verify one exact sidecar byte string against immutable snapshot facts.

    The caller hashes and verifies this same byte object. Accepting a path here
    would create a check/use race if a same-UID process swapped the sidecar
    between the publication-digest check and signature verification.
    """

    selected_environment = _require_environment(expected_environment)
    if type(attestation_bytes) is not bytes:
        raise ReadyAttestationVerificationError(
            "READY attestation must be one immutable byte string"
        )
    if type(immutable_db_digest) is not str or not _is_sha256(
        immutable_db_digest
    ):
        raise ReadyAttestationVerificationError(
            "immutable DB digest must be an exact sha256 string"
        )
    manifest = _validate_exact_four_ready_manifest(
        ready_manifest, expected_snapshot_id=snapshot_id
    )
    decoded = decode_strict_ready_json(attestation_bytes)
    document = _materialize_exact_json(decoded, field="READY attestation")
    if type(document) is not dict or set(document) != _ATTESTATION_FIELDS:
        raise ReadyAttestationVerificationError(
            "READY attestation sidecar shape is invalid"
        )
    if (
        document.get("format") != READINESS_ATTESTATION_FORMAT
        or document.get("environment") != selected_environment
        or document.get("authority_instance_id")
        != ready_authority_instance_id(selected_environment)
        or document.get("readiness_scope") != "PILOT"
        or document.get("ready_state") != "READY"
        or document.get("issuer") != "ReadyPublicationService/v3"
        or document.get("snapshot_id") != snapshot_id
        or document.get("immutable_db_digest") != immutable_db_digest
        or type(document.get("attestation_id")) is not str
        or not document["attestation_id"].strip()
    ):
        raise ReadyAttestationVerificationError(
            "READY attestation identity or artifact binding is invalid"
        )
    field_pairs = {
        "profile_id": "profile_id",
        "profile_version": "profile_version",
        "profile_digest": "profile_digest",
        "plan_ids": "plan_ids",
        "plan_set_digest": "plan_set_digest",
        "dependency_closure_digest": "dependency_closure_digest",
        "universe_rule_digest": "universe_rule_digest",
        "resolved_universe_digest": "resolved_universe_digest",
        "dataset_ids": "dataset_ids",
        "ready_manifest_digest": "manifest_digest",
        "coverage_policy_version": "coverage_policy_version",
        "coverage_policy_digest": "coverage_policy_digest",
        "coverage_proof_digest": "coverage_proof_digest",
        "governed_membership_digest": "dataset_membership_digest",
        "raw_proof_digest": "raw_proof_digest",
        "receipt_proof_digest": "receipt_proof_digest",
        "validation_proof_digest": "validation_proof_digest",
        "b0_quality_proof_digest": "b0_proof_digest",
        "b4_quality_proof_digest": "b4_proof_digest",
        "source_generation": "source_generation",
        "export_cursor": "export_cursor",
        "applied_cursor": "applied_cursor",
    }
    if any(
        document.get(attestation_field) != manifest.get(manifest_field)
        for attestation_field, manifest_field in field_pairs.items()
    ):
        raise ReadyAttestationVerificationError(
            "READY attestation does not bind the embedded ReadyManifest"
        )
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
    if any(not _is_sha256(document.get(field)) for field in digest_fields):
        raise ReadyAttestationVerificationError(
            "READY attestation has missing proof digests"
        )
    expected_evidence_digest = _digest(
        {"manifest": manifest, "immutable_db_digest": immutable_db_digest}
    )
    if document.get("evidence_digest") != expected_evidence_digest:
        raise ReadyAttestationVerificationError(
            "READY attestation evidence digest is invalid"
        )
    expected_authority_resource_digest = derive_ready_authority_resource_digest(
        environment=selected_environment,
        authority_instance_id=document["authority_instance_id"],
        snapshot_id=snapshot_id,
        immutable_db_digest=immutable_db_digest,
        ready_manifest_digest=document["ready_manifest_digest"],
        signed_projection_document_digest=document[
            "signed_projection_document_digest"
        ],
    )
    if document["authority_resource_digest"] != expected_authority_resource_digest:
        raise ReadyAttestationVerificationError(
            "READY attestation authority resource digest is invalid"
        )
    if (
        document.get("plan_ids") != list(EXACT_FOUR_PLAN_IDS)
        or document.get("dataset_ids") != list(EXACT_FOUR_DATASET_IDS)
    ):
        raise ReadyAttestationVerificationError(
            "READY attestation exact-four membership is invalid"
        )
    try:
        verified_at = datetime.fromisoformat(
            document["verified_at"].replace("Z", "+00:00")
        )
        expires_at = datetime.fromisoformat(
            document["expires_at"].replace("Z", "+00:00")
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ReadyAttestationVerificationError(
            "READY attestation timestamps are invalid"
        ) from exc
    clock = _now()
    try:
        manifest_published_at = datetime.fromisoformat(
            manifest["published_at"].replace("Z", "+00:00")
        )
    except (AttributeError, TypeError, ValueError) as exc:  # already validated
        raise ReadyAttestationVerificationError(
            "embedded ReadyManifest published_at is invalid"
        ) from exc
    if (
        verified_at.tzinfo is None
        or expires_at.tzinfo is None
        or expires_at < verified_at
        or expires_at - verified_at
        < timedelta(seconds=MIN_READY_ATTESTATION_TTL_SECONDS)
        or expires_at - verified_at
        > timedelta(seconds=MAX_READY_ATTESTATION_TTL_SECONDS)
        or manifest_published_at > verified_at
        or verified_at > clock + timedelta(minutes=5)
        or clock > expires_at
    ):
        raise ReadyAttestationVerificationError(
            "READY attestation is expired or time-incoherent"
        )
    key_id = document.get("key_id")
    signature = document.get("signature")
    if type(key_id) is not str or type(signature) is not str:
        raise ReadyAttestationVerificationError(
            "READY attestation signing identity is invalid"
        )
    key = _load_pinned_readiness_public_keys(
        expected_environment=selected_environment
    ).get((selected_environment, document["authority_instance_id"], key_id))
    if key is None or not signature.startswith("ed25519:"):
        raise ReadyAttestationVerificationError(
            "READY attestation issuer is not trusted"
        )
    signed_body = {key: value for key, value in document.items() if key != "signature"}
    try:
        key.verify(
            base64.b64decode(signature.removeprefix("ed25519:"), validate=True),
            _canonical_bytes(signed_body),
        )
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise ReadyAttestationVerificationError(
            "READY attestation signature is invalid"
        ) from exc
    return _deep_immutable_json(document)


__all__ = [
    "EXACT_FOUR_CLOSURE_DIGEST",
    "EXACT_FOUR_DATASET_IDS",
    "EXACT_FOUR_PLAN_IDS",
    "EXACT_FOUR_PLAN_SET_DIGEST",
    "EXACT_FOUR_PROFILE_DIGEST",
    "EXACT_FOUR_PROFILE_ID",
    "EXACT_FOUR_PROFILE_VERSION",
    "EXACT_FOUR_UNIVERSE_RULE_DIGEST",
    "MAX_READY_ATTESTATION_TTL_SECONDS",
    "MIN_READY_ATTESTATION_TTL_SECONDS",
    "PINNED_READINESS_REGISTRY_DOCUMENT_DIGEST",
    "READINESS_ATTESTATION_FORMAT",
    "ReadyAttestationVerificationError",
    "decode_strict_ready_json",
    "derive_ready_authority_resource_digest",
    "load_pinned_readiness_public_keys",
    "ready_authority_instance_id",
    "verify_pinned_pilot_snapshot_attestation",
]
