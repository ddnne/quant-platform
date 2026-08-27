"""Public, verify-only Ed25519 receipt cryptography.

This product module deliberately has no private-key type, private-key loader,
or signing helper.  Receipt minting belongs to a separately provisioned
evidence authority; Coverage and READY consume only signed documents verified
against the committed public-key registry.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_PINNED_VERIFY_KEYS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data_contracts"
    / "receipt_verify_public_keys.json"
)
_PINNED_PRIOR_VERIFY_KEYS_PATH = _PINNED_VERIFY_KEYS_PATH.with_name(
    "receipt_verify_public_keys.generation-1.json"
)
_AUTHORITY_INSTANCES_PATH = _PINNED_VERIFY_KEYS_PATH.with_name(
    "receipt_authority_instances.json"
)
_PINNED_SCOPED_VERIFY_KEYS_PATHS = {
    "production": _PINNED_VERIFY_KEYS_PATH.with_name(
        "receipt_verify_public_keys.production.json"
    ),
    "staging": _PINNED_VERIFY_KEYS_PATH.with_name(
        "receipt_verify_public_keys.staging.json"
    ),
}
PINNED_RECEIPT_AUTHORITY_INSTANCES_RAW_DIGEST = (
    "sha256:8b7cee2f0fb8d992b28ede1e6ad843381245d78e1cd64b4fc0e1b1ee06462574"
)
PINNED_RECEIPT_AUTHORITY_INSTANCES_DOCUMENT_DIGEST = (
    "sha256:46e764657aa1f9e71250ca17bda538a68ecf3836cde650f643110236287d3123"
)
PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS = {
    "production": (
        "sha256:a63f439bbf478ce25795ed2c80ed6e88ddcd344a4c8538713a20410ac58b8f8c"
    ),
    "staging": (
        "sha256:0fa133cf345bdd1f979beebb18e3873fbad88ac7631fc7d5b07ffaca34e68ac7"
    ),
}
PINNED_SCOPED_RECEIPT_REGISTRY_RAW_DIGESTS = {
    "production": (
        "sha256:3c1237ad4ea822531523ebb1a88339b4d196458ac38a2c0f263ca81c9a456a62"
    ),
    "staging": (
        "sha256:ed4adfef43009c1e8c0801deb7099dc33ff0d50cf5e9fb131eb5313afd2e9db8"
    ),
}
PINNED_RECEIPT_REGISTRY_RAW_DIGEST = (
    "sha256:dc6095db1d09bf775f972cb428944a1ba5bc47fefa0af19e77c3f3a157ae47f5"
)
PINNED_RECEIPT_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:188c39c9833802026ff614a2de6ad3c48e7c83e628c43958b00f003097a36516"
)
PINNED_RECEIPT_REGISTRY_GENERATION = 2
PINNED_RECEIPT_AUTHORITY_STATUS = "PENDING"
PINNED_RECEIPT_PRIOR_REGISTRY_DIGEST = (
    "sha256:087cfea679c27c267c4e79aaa7518097778d3b44d251c931e5bb6fd2803a2465"
)
PINNED_RECEIPT_PRIOR_REGISTRY_RAW_DIGEST = (
    "sha256:de08e72ea133bf4ab876944e27520a5aa7207e7bdfee412b8866131b9e7b1c90"
)
PINNED_RECEIPT_PRIOR_REGISTRY_DOCUMENT_DIGEST = (
    "sha256:087cfea679c27c267c4e79aaa7518097778d3b44d251c931e5bb6fd2803a2465"
)
PINNED_RECEIPT_PRIOR_REGISTRY_GENERATION = 1
PINNED_RECEIPT_PRIOR_AUTHORITY_STATUS = "REVOKED"
PINNED_RECEIPT_REGISTRY_BODY_DIGEST = (
    "sha256:7dbf4eae91e927d74bd7075bc69210232030bb9077052d55853dc09f0c7bb921"
)


class ReceiptKeyConfigurationError(RuntimeError):
    """Receipt verification keys are absent, malformed, or unpinned."""


PARSER_NORMALIZER_VERSION = "coverage-receipt/v4-ed25519-closure"
SIGNED_RECEIPT_CLAIMS_VERSION = "signed-receipt-claims/v3"
AUDIT_SIGNED_RECEIPT_CLAIMS_VERSION_V2 = "signed-receipt-claims/v2"
LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION = "signed-receipt-claims/v1"
PRODUCTION_RECEIPT_ENVIRONMENT = "production"
PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST = (
    PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS[PRODUCTION_RECEIPT_ENVIRONMENT]
)

# Closed claim names plus envelope aliases. extra_digests cannot occupy these.
STANDARD_CLAIM_KEYS = frozenset(
    {
        "version",
        "environment",
        "authority_instance_digest",
        "coverage_policy_version",
        "dataset",
        "source",
        "segment_id",
        "segment_start",
        "segment_end",
        "expected_scope",
        "expected_items",
        "observed_items",
        "raw_page_count",
        "source_request_digest",
        "raw_manifest_digest",
        "raw_digest",
        "raw_count",
        "structured_digest",
        "structured_count",
        "parser_normalizer_version",
        "structured_generation",
        "pagination_exhausted",
        "discovery_exhausted",
        "status",
        "error",
        "scope_digest",
        "observation_digest",
        "run_id",
        "issuer_id",
        "issued_at",
        "checked_at",
        "extra_digests",
        "raw",
        "eligibility",
        "signature",
        "signed_body_b64",
        "issuer_class",
        "issuer_key_id",
        "body_digest",
    }
)


def canonical_receipt_body(fields: Mapping[str, Any]) -> bytes:
    """Deterministic JSON bytes for signing (sorted keys, no whitespace)."""
    return json.dumps(
        dict(fields),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")


def _strict_json_document(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, value in pairs:
            if key in document:
                raise ReceiptKeyConfigurationError(
                    f"receipt registry contains duplicate key {key!r}"
                )
            document[key] = value
        return document

    def reject_nonfinite(value: str) -> None:
        raise ReceiptKeyConfigurationError(
            f"receipt registry contains non-finite value {value!r}"
        )

    try:
        document = json.loads(
            raw,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except ReceiptKeyConfigurationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptKeyConfigurationError(
            "cannot load the pinned receipt public-key registry"
        ) from exc
    if type(document) is not dict:
        raise ReceiptKeyConfigurationError(
            "pinned receipt public-key registry is invalid"
        )
    return document


def _canonical_registry_bytes(document: dict[str, Any]) -> bytes:
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def body_digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def canonical_evidence_digest(payload: Any) -> str:
    """Digest bytes verbatim or structured evidence as closed canonical JSON."""
    raw = payload if isinstance(payload, bytes) else json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return body_digest(raw)


@dataclass(frozen=True)
class ReceiptVerifyKey:
    key_id: str
    public_key: Ed25519PublicKey

    def verify(self, body: bytes, signature: str) -> bool:
        if type(body) is not bytes or type(signature) is not str:
            return False
        if not signature.startswith("ed25519:"):
            return False
        raw = _decode_canonical_base64(
            signature[len("ed25519:") :], expected_length=64
        )
        if raw is None:
            return False
        try:
            self.public_key.verify(raw, body)
            return True
        except InvalidSignature:
            return False


@dataclass(frozen=True)
class _ReceiptVerifyRegistryEntry:
    key_id: str
    public_key_bytes: bytes
    status: str


@dataclass(frozen=True)
class _ReceiptVerifyRegistry:
    generation: int
    authority_status: str
    environment: str | None
    authority_instance_digest: str | None
    prior_registry_digest: str | None
    registry_digest: str
    entries: tuple[_ReceiptVerifyRegistryEntry, ...]
    active_keys: tuple[ReceiptVerifyKey, ...]
    audit_keys: tuple[ReceiptVerifyKey, ...]


@dataclass(frozen=True)
class _PriorReceiptVerifyRegistry:
    generation: int
    authority_status: str
    document_digest: str
    entries: tuple[_ReceiptVerifyRegistryEntry, ...]


_REGISTRY_FIELDS = {
    "schema_version",
    "purpose",
    "generation",
    "authority_status",
    "prior_registry_digest",
    "keys",
    "registry_digest",
}
_REGISTRY_KEY_FIELDS = {
    "key_id",
    "algorithm",
    "public_key_base64",
    "status",
}
_SCOPED_REGISTRY_FIELDS = _REGISTRY_FIELDS | {
    "environment",
    "authority_instance_digest",
}
_PRIOR_REGISTRY_FIELDS = {
    "schema_version",
    "purpose",
    "keys",
}
_PRIOR_REGISTRY_KEY_FIELDS = {
    "key_id",
    "public_key_b64",
    "algorithm",
    "status",
    "note",
}


def _decode_canonical_base64(
    value: object, *, expected_length: int | None = None
) -> bytes | None:
    if type(value) is not str:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    if base64.b64encode(raw).decode("ascii") != value:
        return None
    if expected_length is not None and len(raw) != expected_length:
        return None
    return raw


def decode_canonical_signed_body(value: object) -> bytes | None:
    """Decode one receipt body only when its Base64 spelling is canonical."""
    return _decode_canonical_base64(value)


def _registry_body_digest(document: Mapping[str, Any]) -> str:
    body = {
        key: value
        for key, value in document.items()
        if key != "registry_digest"
    }
    return body_digest(_canonical_registry_bytes(body))


@lru_cache(maxsize=8)
def _parse_registry_document(raw: bytes) -> _ReceiptVerifyRegistry:
    """Parse one exact registry byte string; content, not stat, keys the cache."""
    doc = _strict_json_document(raw)
    if set(doc) != _REGISTRY_FIELDS:
        raise ReceiptKeyConfigurationError(
            "pinned receipt public-key registry is invalid"
        )
    if (
        type(doc["schema_version"]) is not int
        or doc["schema_version"] != 2
        or type(doc["purpose"]) is not str
        or doc["purpose"] != "receipt_verification"
        or type(doc["generation"]) is not int
        or doc["generation"] < 1
        or type(doc["authority_status"]) is not str
        or doc["authority_status"] not in {"ACTIVE", "PENDING"}
        or (
            doc["generation"] == 1
            and doc["prior_registry_digest"] is not None
        )
        or (
            doc["generation"] > 1
            and (
                type(doc["prior_registry_digest"]) is not str
                or not _is_sha256_digest(doc["prior_registry_digest"])
            )
        )
        or type(doc["registry_digest"]) is not str
        or not _is_sha256_digest(doc["registry_digest"])
        or type(doc["keys"]) is not list
        or len(doc["keys"]) < 1
        or len(doc["keys"]) > 16
    ):
        raise ReceiptKeyConfigurationError(
            "pinned receipt public-key registry is invalid"
        )
    if _registry_body_digest(doc) != doc["registry_digest"]:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry body digest mismatch"
        )
    active: dict[str, ReceiptVerifyKey] = {}
    audit: dict[str, ReceiptVerifyKey] = {}
    entries: list[_ReceiptVerifyRegistryEntry] = []
    seen_ids: set[str] = set()
    seen_public_key_status: dict[bytes, str] = {}
    pending_count = 0
    for row in doc["keys"]:
        if type(row) is not dict or set(row) != _REGISTRY_KEY_FIELDS:
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry row is not closed"
            )
        if any(type(row[field]) is not str for field in _REGISTRY_KEY_FIELDS):
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry fields must be exact strings"
            )
        raw_key_id = row["key_id"]
        key_id = raw_key_id.strip()
        if raw_key_id != key_id or not key_id or key_id in seen_ids:
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry key ids must be trimmed, non-empty, and unique"
            )
        seen_ids.add(key_id)
        if row["algorithm"] != "Ed25519":
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry requires Ed25519 entries"
            )
        status = row["status"]
        if status not in {"active", "pending", "revoked"}:
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry requires an explicit key status"
            )
        try:
            raw_key = _decode_canonical_base64(
                row["public_key_base64"], expected_length=32
            )
            if raw_key is None:
                raise ValueError("receipt public key is not canonical Ed25519 base64")
            public_key = Ed25519PublicKey.from_public_bytes(raw_key)
        except (TypeError, ValueError) as exc:
            raise ReceiptKeyConfigurationError(
                f"invalid pinned receipt public key: {key_id}"
            ) from exc
        prior_status = seen_public_key_status.get(raw_key)
        if prior_status is not None and (
            prior_status != "revoked" or status != "revoked"
        ):
            raise ReceiptKeyConfigurationError(
                "active or pending receipt public keys must not reuse public-key bytes"
            )
        seen_public_key_status[raw_key] = status
        entries.append(
            _ReceiptVerifyRegistryEntry(
                key_id=key_id,
                public_key_bytes=raw_key,
                status=status,
            )
        )
        verify_key = ReceiptVerifyKey(key_id=key_id, public_key=public_key)
        if status == "active":
            active[key_id] = verify_key
            audit[key_id] = verify_key
        elif status == "revoked":
            audit[key_id] = verify_key
        else:
            pending_count += 1
    expected_active = 1 if doc["authority_status"] == "ACTIVE" else 0
    if len(active) != expected_active:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry active keys do not match authority status"
        )
    if pending_count > 1:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry permits at most one pending key"
        )
    return _ReceiptVerifyRegistry(
        generation=doc["generation"],
        authority_status=doc["authority_status"],
        environment=None,
        authority_instance_digest=None,
        prior_registry_digest=doc["prior_registry_digest"],
        registry_digest=doc["registry_digest"],
        entries=tuple(entries),
        active_keys=tuple(active.values()),
        audit_keys=tuple(audit.values()),
    )


@lru_cache(maxsize=4)
def _parse_prior_registry_document(raw: bytes) -> _PriorReceiptVerifyRegistry:
    """Parse the exact legacy generation-1 audit artifact."""
    doc = _strict_json_document(raw)
    if (
        set(doc) != _PRIOR_REGISTRY_FIELDS
        or type(doc["schema_version"]) is not int
        or doc["schema_version"] != 1
        or type(doc["purpose"]) is not str
        or doc["purpose"] != "receipt_verification"
        or type(doc["keys"]) is not list
        or not 1 <= len(doc["keys"]) <= 16
    ):
        raise ReceiptKeyConfigurationError(
            "pinned prior receipt registry is invalid"
        )

    entries: list[_ReceiptVerifyRegistryEntry] = []
    seen_ids: set[str] = set()
    for row in doc["keys"]:
        if type(row) is not dict or set(row) != _PRIOR_REGISTRY_KEY_FIELDS:
            raise ReceiptKeyConfigurationError(
                "pinned prior receipt registry row is not closed"
            )
        if any(type(row[field]) is not str for field in _PRIOR_REGISTRY_KEY_FIELDS):
            raise ReceiptKeyConfigurationError(
                "pinned prior receipt registry fields must be exact strings"
            )
        raw_key_id = row["key_id"]
        key_id = raw_key_id.strip()
        if raw_key_id != key_id or not key_id or key_id in seen_ids:
            raise ReceiptKeyConfigurationError(
                "pinned prior receipt registry key ids must be trimmed, "
                "non-empty, and unique"
            )
        seen_ids.add(key_id)
        if (
            row["algorithm"] != "Ed25519"
            or row["status"] != "revoked"
            or row["note"] != row["note"].strip()
            or not row["note"]
        ):
            raise ReceiptKeyConfigurationError(
                "pinned prior receipt registry must remain revoked audit evidence"
            )
        raw_key = _decode_canonical_base64(
            row["public_key_b64"], expected_length=32
        )
        if raw_key is None:
            raise ReceiptKeyConfigurationError(
                f"invalid pinned prior receipt public key: {key_id}"
            )
        entries.append(
            _ReceiptVerifyRegistryEntry(
                key_id=key_id,
                public_key_bytes=raw_key,
                status="revoked",
            )
        )
    return _PriorReceiptVerifyRegistry(
        generation=1,
        authority_status="REVOKED",
        document_digest=body_digest(_canonical_registry_bytes(doc)),
        entries=tuple(entries),
    )


def _is_sha256_digest(value: str) -> bool:
    return (
        len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


@lru_cache(maxsize=1)
def _load_pinned_authority_instances() -> Mapping[str, Mapping[str, Any]]:
    """Load the exact environment/resource authority contract."""
    try:
        raw = _AUTHORITY_INSTANCES_PATH.read_bytes()
    except OSError as exc:
        raise ReceiptKeyConfigurationError(
            "cannot read the pinned receipt authority instance contract"
        ) from exc
    if body_digest(raw) != PINNED_RECEIPT_AUTHORITY_INSTANCES_RAW_DIGEST:
        raise ReceiptKeyConfigurationError(
            "pinned receipt authority instance raw digest mismatch"
        )
    document = _strict_json_document(raw)
    if (
        body_digest(_canonical_registry_bytes(document))
        != PINNED_RECEIPT_AUTHORITY_INSTANCES_DOCUMENT_DIGEST
        or set(document) != {"schema_version", "instances"}
        or document.get("schema_version") != "receipt-authority-instances/v1"
        or type(document.get("instances")) is not dict
        or set(document["instances"]) != {"production", "staging"}
    ):
        raise ReceiptKeyConfigurationError(
            "pinned receipt authority instance contract is invalid"
        )
    instances: dict[str, Mapping[str, Any]] = {}
    resource_shapes = {
        "d1": {"binding", "database_name", "database_id"},
        "authority_evidence_r2": {
            "binding", "bucket_name", "raw_prefix", "product_prefix"
        },
        "durable_object": {"binding", "class_name"},
        "acquisition_service": {"binding", "service", "entrypoint"},
    }
    for environment in ("production", "staging"):
        instance = document["instances"].get(environment)
        if (
            type(instance) is not dict
            or set(instance)
            != {"environment", "authority_id", "worker_name", "resources"}
            or instance.get("environment") != environment
            or instance.get("authority_id") != "receipt-evidence-authority"
            or type(instance.get("worker_name")) is not str
            or not instance["worker_name"]
            or type(instance.get("resources")) is not dict
            or set(instance["resources"]) != set(resource_shapes)
        ):
            raise ReceiptKeyConfigurationError(
                "pinned receipt authority instance is invalid"
            )
        for resource_name, fields in resource_shapes.items():
            resource = instance["resources"].get(resource_name)
            if (
                type(resource) is not dict
                or set(resource) != fields
                or any(type(resource[field]) is not str or not resource[field]
                       for field in fields)
            ):
                raise ReceiptKeyConfigurationError(
                    "pinned receipt authority resource binding is invalid"
                )
        digest = canonical_evidence_digest(instance)
        if digest != PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS[environment]:
            raise ReceiptKeyConfigurationError(
                "pinned receipt authority instance digest mismatch"
            )
        instances[environment] = instance
    return MappingProxyType(instances)


def receipt_authority_instance_digest(environment: str) -> str:
    """Return the pinned resource-authority digest for one exact environment."""
    if type(environment) is not str or environment not in {"production", "staging"}:
        raise ReceiptKeyConfigurationError(
            "receipt authority environment must be production or staging"
        )
    _load_pinned_authority_instances()
    return PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS[environment]


@lru_cache(maxsize=8)
def _parse_scoped_registry_document(raw: bytes) -> _ReceiptVerifyRegistry:
    """Parse a v3 key registry bound to one environment/resource instance."""
    doc = _strict_json_document(raw)
    if (
        set(doc) != _SCOPED_REGISTRY_FIELDS
        or doc.get("schema_version") != 3
        or doc.get("purpose") != "receipt_verification"
        or type(doc.get("generation")) is not int
        or doc["generation"] < 1
        or doc.get("authority_status") not in {"ACTIVE", "PENDING"}
        or doc.get("environment") not in {"production", "staging"}
        or type(doc.get("authority_instance_digest")) is not str
        or not _is_sha256_digest(doc["authority_instance_digest"])
        or (
            doc["generation"] == 1 and doc.get("prior_registry_digest") is not None
        )
        or (
            doc["generation"] > 1
            and (
                type(doc.get("prior_registry_digest")) is not str
                or not _is_sha256_digest(doc["prior_registry_digest"])
            )
        )
        or type(doc.get("registry_digest")) is not str
        or not _is_sha256_digest(doc["registry_digest"])
        or type(doc.get("keys")) is not list
        or len(doc["keys"]) > 16
        or _registry_body_digest(doc) != doc["registry_digest"]
    ):
        raise ReceiptKeyConfigurationError(
            "pinned scoped receipt public-key registry is invalid"
        )
    if (
        doc["authority_instance_digest"]
        != receipt_authority_instance_digest(doc["environment"])
    ):
        raise ReceiptKeyConfigurationError(
            "scoped receipt registry authority instance mismatch"
        )
    active: dict[str, ReceiptVerifyKey] = {}
    audit: dict[str, ReceiptVerifyKey] = {}
    entries: list[_ReceiptVerifyRegistryEntry] = []
    seen_ids: set[str] = set()
    seen_public_key_status: dict[bytes, str] = {}
    pending_count = 0
    for row in doc["keys"]:
        if type(row) is not dict or set(row) != _REGISTRY_KEY_FIELDS:
            raise ReceiptKeyConfigurationError(
                "scoped receipt registry row is not closed"
            )
        if any(type(row[field]) is not str for field in _REGISTRY_KEY_FIELDS):
            raise ReceiptKeyConfigurationError(
                "scoped receipt registry fields must be exact strings"
            )
        key_id = row["key_id"]
        if key_id != key_id.strip() or not key_id or key_id in seen_ids:
            raise ReceiptKeyConfigurationError(
                "scoped receipt registry key ids must be trimmed and unique"
            )
        seen_ids.add(key_id)
        if row["algorithm"] != "Ed25519" or row["status"] not in {
            "active", "pending", "revoked"
        }:
            raise ReceiptKeyConfigurationError(
                "scoped receipt registry key lifecycle is invalid"
            )
        raw_key = _decode_canonical_base64(
            row["public_key_base64"], expected_length=32
        )
        if raw_key is None:
            raise ReceiptKeyConfigurationError(
                f"invalid scoped receipt public key: {key_id}"
            )
        prior_status = seen_public_key_status.get(raw_key)
        if prior_status is not None and (
            prior_status != "revoked" or row["status"] != "revoked"
        ):
            raise ReceiptKeyConfigurationError(
                "active or pending scoped receipt keys must not reuse bytes"
            )
        seen_public_key_status[raw_key] = row["status"]
        entry = _ReceiptVerifyRegistryEntry(
            key_id=key_id,
            public_key_bytes=raw_key,
            status=row["status"],
        )
        entries.append(entry)
        verify_key = ReceiptVerifyKey(
            key_id=key_id,
            public_key=Ed25519PublicKey.from_public_bytes(raw_key),
        )
        if row["status"] == "active":
            active[key_id] = verify_key
            audit[key_id] = verify_key
        elif row["status"] == "revoked":
            audit[key_id] = verify_key
        else:
            pending_count += 1
    expected_active = 1 if doc["authority_status"] == "ACTIVE" else 0
    if len(active) != expected_active or pending_count > 1:
        raise ReceiptKeyConfigurationError(
            "scoped receipt registry keys do not match authority status"
        )
    return _ReceiptVerifyRegistry(
        generation=doc["generation"],
        authority_status=doc["authority_status"],
        environment=doc["environment"],
        authority_instance_digest=doc["authority_instance_digest"],
        prior_registry_digest=doc["prior_registry_digest"],
        registry_digest=doc["registry_digest"],
        entries=tuple(entries),
        active_keys=tuple(active.values()),
        audit_keys=tuple(audit.values()),
    )


def _load_pinned_scoped_registry(
    *, expected_environment: str, expected_authority_instance_digest: str
) -> _ReceiptVerifyRegistry:
    if (
        type(expected_environment) is not str
        or expected_environment not in {"production", "staging"}
        or type(expected_authority_instance_digest) is not str
        or expected_authority_instance_digest
        != receipt_authority_instance_digest(expected_environment)
    ):
        raise ReceiptKeyConfigurationError(
            "receipt verifier expected authority scope is not pinned"
        )
    path = _PINNED_SCOPED_VERIFY_KEYS_PATHS[expected_environment]
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReceiptKeyConfigurationError(
            "cannot read the pinned scoped receipt public-key registry"
        ) from exc
    if body_digest(raw) != PINNED_SCOPED_RECEIPT_REGISTRY_RAW_DIGESTS[
        expected_environment
    ]:
        raise ReceiptKeyConfigurationError(
            "pinned scoped receipt registry raw digest mismatch"
        )
    registry = _parse_scoped_registry_document(raw)
    if (
        registry.environment != expected_environment
        or registry.authority_instance_digest
        != expected_authority_instance_digest
    ):
        raise ReceiptKeyConfigurationError(
            "pinned scoped receipt registry selection mismatch"
        )
    return registry


def _parse_verify_key_document(raw: bytes) -> tuple[ReceiptVerifyKey, ...]:
    """Return only ACTIVE keys; PENDING and revoked keys cannot grant COMPLETE."""
    return _parse_registry_document(raw).active_keys


def _parse_audit_key_document(raw: bytes) -> tuple[ReceiptVerifyKey, ...]:
    """Return ACTIVE/revoked public keys for explicitly audit-only verification."""
    return _parse_registry_document(raw).audit_keys


def _load_verify_key_file(
    path_text: str, mtime_ns: int | None = None, size: int | None = None
) -> tuple[ReceiptVerifyKey, ...]:
    """Parse a registry for diagnostics; production additionally pins bytes."""
    del mtime_ns, size
    try:
        raw = Path(path_text).read_bytes()
    except OSError as exc:
        raise ReceiptKeyConfigurationError(
            "cannot load the pinned receipt public-key registry"
        ) from exc
    return _parse_verify_key_document(raw)


def _load_pinned_registry() -> _ReceiptVerifyRegistry:
    """Load and pin the complete committed receipt verifier registry."""
    keys_path = _PINNED_VERIFY_KEYS_PATH
    try:
        raw = keys_path.read_bytes()
    except OSError as exc:
        raise ReceiptKeyConfigurationError(
            "cannot read the pinned receipt public-key registry"
        ) from exc
    raw_digest = body_digest(raw)
    if raw_digest != PINNED_RECEIPT_REGISTRY_RAW_DIGEST:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry raw digest mismatch"
        )
    document = _strict_json_document(raw)
    document_digest = body_digest(_canonical_registry_bytes(document))
    if document_digest != PINNED_RECEIPT_REGISTRY_DOCUMENT_DIGEST:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry document digest mismatch"
        )
    registry = _parse_registry_document(raw)
    if (
        registry.generation != PINNED_RECEIPT_REGISTRY_GENERATION
        or registry.authority_status != PINNED_RECEIPT_AUTHORITY_STATUS
        or registry.prior_registry_digest
        != PINNED_RECEIPT_PRIOR_REGISTRY_DIGEST
        or registry.registry_digest != PINNED_RECEIPT_REGISTRY_BODY_DIGEST
    ):
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry generation chain mismatch"
        )
    if registry.generation > 1:
        prior = _load_pinned_prior_registry()
        _validate_registry_chain(prior=prior, current=registry)
    return registry


def _load_pinned_prior_registry() -> _PriorReceiptVerifyRegistry:
    """Load the immutable predecessor artifact and all of its code pins."""
    try:
        raw = _PINNED_PRIOR_VERIFY_KEYS_PATH.read_bytes()
    except OSError as exc:
        raise ReceiptKeyConfigurationError(
            "cannot read the pinned prior receipt public-key registry"
        ) from exc
    if body_digest(raw) != PINNED_RECEIPT_PRIOR_REGISTRY_RAW_DIGEST:
        raise ReceiptKeyConfigurationError(
            "pinned prior receipt registry raw digest mismatch"
        )
    document = _strict_json_document(raw)
    document_digest = body_digest(_canonical_registry_bytes(document))
    if document_digest != PINNED_RECEIPT_PRIOR_REGISTRY_DOCUMENT_DIGEST:
        raise ReceiptKeyConfigurationError(
            "pinned prior receipt registry document digest mismatch"
        )
    prior = _parse_prior_registry_document(raw)
    if (
        prior.generation != PINNED_RECEIPT_PRIOR_REGISTRY_GENERATION
        or prior.authority_status != PINNED_RECEIPT_PRIOR_AUTHORITY_STATUS
        or prior.document_digest != PINNED_RECEIPT_PRIOR_REGISTRY_DOCUMENT_DIGEST
    ):
        raise ReceiptKeyConfigurationError(
            "pinned prior receipt registry code pins mismatch"
        )
    return prior


def _validate_registry_chain(
    *, prior: _PriorReceiptVerifyRegistry, current: _ReceiptVerifyRegistry
) -> None:
    """Validate the repository-pinned generation-1 -> generation-2 transition.

    This closes the immutable repository chain. An external monotonic state is
    still required before a future authority can prove rollback resistance.
    """
    if (
        current.generation != prior.generation + 1
        or current.prior_registry_digest != prior.document_digest
        or (prior.authority_status, current.authority_status)
        != ("REVOKED", "PENDING")
    ):
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry prior chain mismatch"
        )
    current_by_id = {entry.key_id: entry for entry in current.entries}
    for prior_entry in prior.entries:
        current_entry = current_by_id.get(prior_entry.key_id)
        if (
            current_entry is None
            or current_entry.public_key_bytes != prior_entry.public_key_bytes
            or prior_entry.status != "revoked"
            or current_entry.status != "revoked"
        ):
            raise ReceiptKeyConfigurationError(
                "pinned receipt registry revoked history transition mismatch"
            )


def load_verify_keys() -> dict[str, ReceiptVerifyKey]:
    """Load legacy v1/v2 registry keys for compatibility diagnostics only.

    COMPLETE eligibility never calls this unscoped loader.
    """
    return {row.key_id: row for row in _load_pinned_registry().active_keys}


def load_scoped_verify_keys(
    *, expected_environment: str, expected_authority_instance_digest: str
) -> dict[str, ReceiptVerifyKey]:
    """Load ACTIVE v3 keys from one exact environment/authority registry."""
    registry = _load_pinned_scoped_registry(
        expected_environment=expected_environment,
        expected_authority_instance_digest=expected_authority_instance_digest,
    )
    return {row.key_id: row for row in registry.active_keys}


def load_audit_verify_keys() -> dict[str, ReceiptVerifyKey]:
    """Load ACTIVE/revoked keys for audit; never use this result for COMPLETE."""
    return {row.key_id: row for row in _load_pinned_registry().audit_keys}


def load_scoped_audit_verify_keys(
    *, expected_environment: str, expected_authority_instance_digest: str
) -> dict[str, ReceiptVerifyKey]:
    """Load v3 ACTIVE/revoked keys for audit within one exact authority scope."""
    registry = _load_pinned_scoped_registry(
        expected_environment=expected_environment,
        expected_authority_instance_digest=expected_authority_instance_digest,
    )
    return {row.key_id: row for row in registry.audit_keys}


def receipt_verify_key_status(key_id: str) -> str | None:
    """Return the pinned lifecycle state for one exact receipt key id.

    Callers may use this only to decide whether a cryptographically valid
    receipt is historical audit evidence.  COMPLETE eligibility must continue
    to use :func:`load_verify_keys` and the full collection-closure verifier.
    """
    if type(key_id) is not str or not key_id or key_id != key_id.strip():
        return None
    matches = [
        entry.status
        for entry in _load_pinned_registry().entries
        if entry.key_id == key_id
    ]
    if len(matches) > 1:
        raise ReceiptKeyConfigurationError(
            "pinned receipt registry contains a duplicate key id"
        )
    return matches[0] if matches else None


def scoped_receipt_verify_key_status(
    key_id: str,
    *,
    expected_environment: str,
    expected_authority_instance_digest: str,
) -> str | None:
    """Return one key lifecycle state only inside an exact v3 authority scope."""
    if type(key_id) is not str or not key_id or key_id != key_id.strip():
        return None
    registry = _load_pinned_scoped_registry(
        expected_environment=expected_environment,
        expected_authority_instance_digest=expected_authority_instance_digest,
    )
    matches = [entry.status for entry in registry.entries if entry.key_id == key_id]
    if len(matches) > 1:
        raise ReceiptKeyConfigurationError(
            "scoped receipt registry contains a duplicate key id"
        )
    return matches[0] if matches else None


def partition_extra_digests(extra_digests: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy extra_digests excluding standard claims and envelope aliases."""
    if extra_digests is None:
        return {}
    if not isinstance(extra_digests, Mapping):
        raise TypeError("extra_digests must be a mapping")
    return {
        str(key): value
        for key, value in extra_digests.items()
        if str(key) not in STANDARD_CLAIM_KEYS
    }


def verify_receipt_signature(
    digests: Mapping[str, Any],
    *,
    expected_environment: str,
    expected_authority_instance_digest: str,
) -> bool:
    """Verify only inside an exact caller-owned environment/authority scope."""
    if type(digests) is not dict:
        return False
    frozen = dict(digests)
    body_b64 = frozen.get("signed_body_b64")
    signature = frozen.get("signature")
    key_id = frozen.get("issuer_key_id")
    if type(body_b64) is not str or type(signature) is not str:
        return False
    if type(key_id) is not str or not key_id or key_id != key_id.strip():
        return False
    body = decode_canonical_signed_body(body_b64)
    if body is None:
        return False
    return verify_receipt_signature_values(
        body=body,
        signature=signature,
        key_id=key_id,
        expected_environment=expected_environment,
        expected_authority_instance_digest=expected_authority_instance_digest,
    )


def verify_receipt_signature_values(
    *,
    body: bytes,
    signature: str,
    key_id: str,
    expected_environment: str,
    expected_authority_instance_digest: str,
) -> bool:
    """Verify one body inside an exact caller-owned authority scope."""
    if (
        type(body) is not bytes
        or type(signature) is not str
        or type(key_id) is not str
        or not key_id
        or key_id != key_id.strip()
    ):
        return False
    vk = load_scoped_verify_keys(
        expected_environment=expected_environment,
        expected_authority_instance_digest=expected_authority_instance_digest,
    ).get(key_id)
    return False if vk is None else vk.verify(body, signature)


def verify_receipt_signature_values_for_audit(
    *,
    body: bytes,
    signature: str,
    key_id: str,
    expected_environment: str | None = None,
    expected_authority_instance_digest: str | None = None,
) -> bool:
    """Verify with ACTIVE/revoked public keys without granting eligibility."""
    if (
        type(body) is not bytes
        or type(signature) is not str
        or type(key_id) is not str
        or not key_id
        or key_id != key_id.strip()
    ):
        return False
    if expected_environment is None and expected_authority_instance_digest is None:
        vk = load_audit_verify_keys().get(key_id)
    elif (
        expected_environment is not None
        and expected_authority_instance_digest is not None
    ):
        vk = load_scoped_audit_verify_keys(
            expected_environment=expected_environment,
            expected_authority_instance_digest=expected_authority_instance_digest,
        ).get(key_id)
    else:
        return False
    return False if vk is None else vk.verify(body, signature)


__all__ = [
    "PARSER_NORMALIZER_VERSION",
    "AUDIT_SIGNED_RECEIPT_CLAIMS_VERSION_V2",
    "LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION",
    "SIGNED_RECEIPT_CLAIMS_VERSION",
    "PRODUCTION_RECEIPT_ENVIRONMENT",
    "PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST",
    "STANDARD_CLAIM_KEYS",
    "ReceiptKeyConfigurationError",
    "ReceiptVerifyKey",
    "PINNED_RECEIPT_AUTHORITY_STATUS",
    "PINNED_RECEIPT_PRIOR_AUTHORITY_STATUS",
    "PINNED_RECEIPT_PRIOR_REGISTRY_DIGEST",
    "PINNED_RECEIPT_PRIOR_REGISTRY_DOCUMENT_DIGEST",
    "PINNED_RECEIPT_PRIOR_REGISTRY_GENERATION",
    "PINNED_RECEIPT_PRIOR_REGISTRY_RAW_DIGEST",
    "PINNED_RECEIPT_REGISTRY_BODY_DIGEST",
    "PINNED_RECEIPT_REGISTRY_DOCUMENT_DIGEST",
    "PINNED_RECEIPT_REGISTRY_GENERATION",
    "PINNED_RECEIPT_REGISTRY_RAW_DIGEST",
    "canonical_evidence_digest",
    "canonical_receipt_body",
    "decode_canonical_signed_body",
    "load_audit_verify_keys",
    "load_scoped_audit_verify_keys",
    "load_scoped_verify_keys",
    "load_verify_keys",
    "partition_extra_digests",
    "receipt_authority_instance_digest",
    "scoped_receipt_verify_key_status",
    "verify_receipt_signature",
    "verify_receipt_signature_values",
    "verify_receipt_signature_values_for_audit",
]
