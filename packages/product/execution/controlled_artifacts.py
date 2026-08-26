"""Verify-only contract for controlled execution artifacts.

The application process is not a controlled Paper/Risk/Selection/Knowledge
writer.  A separately permissioned execution authority must return one signed,
content-addressed bundle with the canonical four-stage lineage.  This module
parses and verifies that returned JSON; it has no writer, private key, HOME
store, output path, transport, or signer-injection surface.

The pinned writer registry intentionally contains no active key until the
dedicated authority principal is provisioned.  Production verification is
therefore explicit ``UNKNOWN/PENDING`` rather than a local fallback.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, NoReturn

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from selection.budget_ledger import MassResearchDisabledError

from .trader_authority import (
    TraderAuthorizationBinding,
    VerifiedTraderAuthorization,
    verify_exact_trader_authorization,
)


CONTROLLED_ARTIFACT_BUNDLE_FORMAT = "controlled-execution-artifact-bundle/v1"
CONTROLLED_ARTIFACT_FORMAT = "controlled-execution-artifact/v1"
CONTROLLED_ARTIFACT_WRITER_ISSUER = "ControlledPilotArtifactWriter/v1"
CONTROLLED_ARTIFACT_ALGORITHM = "Ed25519"
CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED = (
    "CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED"
)
PINNED_CONTROLLED_ARTIFACT_REGISTRY_DIGEST = (
    "sha256:eca16d3efe6aec0644111cdce093011c756c87dd2de846d15dcfb096e2ef20eb"
)
DEFAULT_CONTROLLED_ARTIFACT_PUBLIC_KEYS_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "execution_artifacts"
    / "public_keys.json"
)

CONTROLLED_ARTIFACT_TYPES = ("Paper", "Risk", "Selection", "Knowledge")
CONTROLLED_ARTIFACT_SCHEMA_VERSIONS: Mapping[str, str] = MappingProxyType(
    {
        "Paper": "controlled-paper-result/v1",
        "Risk": "controlled-risk-result/v1",
        "Selection": "controlled-selection-decision/v1",
        "Knowledge": "controlled-knowledge/v1",
    }
)

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BUNDLE_FIELDS = frozenset(
    {
        "format",
        "bundle_id",
        "authorization_id",
        "strategy_id",
        "strategy_spec_hash",
        "max_gross_weight",
        "ready_snapshot_id",
        "ready_manifest_digest",
        "readiness_attestation_id",
        "profile_digest",
        "plan_set_digest",
        "dependency_closure_digest",
        "universe_contract_id",
        "universe_rule_digest",
        "resolved_universe_digest",
        "period_start",
        "period_end",
        "cost_scenario",
        "generation_count",
        "automatic_promotion",
        "written_at",
        "writer_key_id",
        "issuer",
        "artifacts",
        "signature",
    }
)
_ARTIFACT_FIELDS = frozenset(
    {
        "format",
        "artifact_id",
        "artifact_type",
        "schema_version",
        "producer",
        "authorization_id",
        "strategy_id",
        "strategy_spec_hash",
        "max_gross_weight",
        "ready_snapshot_id",
        "ready_manifest_digest",
        "readiness_attestation_id",
        "profile_digest",
        "plan_set_digest",
        "dependency_closure_digest",
        "universe_rule_digest",
        "universe_contract_id",
        "resolved_universe_digest",
        "period_start",
        "period_end",
        "cost_scenario",
        "parent_artifact_ids",
        "payload",
    }
)
_COMMON_ARTIFACT_FIELDS = (
    "authorization_id",
    "strategy_id",
    "strategy_spec_hash",
    "max_gross_weight",
    "ready_snapshot_id",
    "ready_manifest_digest",
    "readiness_attestation_id",
    "profile_digest",
    "plan_set_digest",
    "dependency_closure_digest",
    "universe_contract_id",
    "universe_rule_digest",
    "resolved_universe_digest",
    "period_start",
    "period_end",
    "cost_scenario",
)
_PAYLOAD_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "Paper": frozenset(
            {"content_digest", "experiment_id", "run_id", "lifecycle"}
        ),
        "Risk": frozenset(
            {
                "content_digest",
                "audit_id",
                "paper_artifact_id",
                "status",
            }
        ),
        "Selection": frozenset(
            {
                "content_digest",
                "decision_id",
                "paper_artifact_id",
                "risk_artifact_id",
                "decision",
                "automatic_promotion",
            }
        ),
        "Knowledge": frozenset(
            {"content_digest", "knowledge_id", "selection_artifact_id"}
        ),
    }
)
_VERIFIED_BUNDLE_TOKEN = object()


class ControlledArtifactVerificationError(MassResearchDisabledError):
    """Returned controlled artifact bytes are invalid or untrusted."""


class ControlledArtifactAuthorityPending(ControlledArtifactVerificationError):
    """No separately permissioned artifact writer is currently trusted."""

    status = "UNKNOWN"
    reason_code = CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED

    def __init__(self) -> None:
        super().__init__(
            f"{self.status}: {self.reason_code}; controlled artifacts require "
            "a separately permissioned canonical writer"
        )


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _decode_signature(signature: str) -> bytes:
    if type(signature) is not str or not signature.startswith("ed25519:"):
        raise ControlledArtifactVerificationError(
            "controlled artifact signature must be Ed25519"
        )
    try:
        raw = base64.b64decode(signature[len("ed25519:") :], validate=True)
    except (TypeError, ValueError) as exc:
        raise ControlledArtifactVerificationError(
            "controlled artifact signature is not canonical base64"
        ) from exc
    if len(raw) != 64:
        raise ControlledArtifactVerificationError(
            "controlled artifact Ed25519 signature length is invalid"
        )
    return raw


@dataclass(frozen=True, slots=True)
class ControlledArtifactPublicKeyRegistry:
    """Pinned public-key-only registry for the external artifact writer."""

    _keys: Mapping[str, Ed25519PublicKey]

    def __post_init__(self) -> None:
        if len(self._keys) > 1:
            raise ControlledArtifactVerificationError(
                "controlled artifact registry permits at most one active key"
            )
        normalized: dict[str, Ed25519PublicKey] = {}
        for raw_id, key in self._keys.items():
            if (
                type(raw_id) is not str
                or not raw_id
                or not isinstance(key, Ed25519PublicKey)
            ):
                raise ControlledArtifactVerificationError(
                    "controlled artifact registry entry is invalid"
                )
            normalized[raw_id] = key
        object.__setattr__(self, "_keys", MappingProxyType(normalized))

    @property
    def active_key_count(self) -> int:
        return len(self._keys)

    @classmethod
    def from_document(
        cls, document: Mapping[str, Any]
    ) -> "ControlledArtifactPublicKeyRegistry":
        if type(document) is not dict or set(document) != {
            "schema_version",
            "purpose",
            "keys",
        }:
            raise ControlledArtifactVerificationError(
                "controlled artifact registry document is not closed"
            )
        if (
            type(document["schema_version"]) is not int
            or document["schema_version"] != 1
            or type(document["purpose"]) is not str
            or document["purpose"]
            != "controlled_execution_artifact_verification"
            or type(document["keys"]) is not list
        ):
            raise ControlledArtifactVerificationError(
                "controlled artifact registry identity is invalid"
            )
        active: dict[str, Ed25519PublicKey] = {}
        seen: set[str] = set()
        for row in document["keys"]:
            if type(row) is not dict or set(row) != {
                "key_id",
                "algorithm",
                "public_key_b64",
                "status",
            }:
                raise ControlledArtifactVerificationError(
                    "controlled artifact registry row is not closed"
                )
            key_id = row["key_id"]
            status = row["status"]
            if (
                type(key_id) is not str
                or not key_id
                or key_id in seen
                or type(row["algorithm"]) is not str
                or row["algorithm"] != CONTROLLED_ARTIFACT_ALGORITHM
                or type(status) is not str
                or status not in {"active", "revoked"}
                or type(row["public_key_b64"]) is not str
            ):
                raise ControlledArtifactVerificationError(
                    "controlled artifact registry row is invalid"
                )
            seen.add(key_id)
            try:
                raw = base64.b64decode(row["public_key_b64"], validate=True)
                key = Ed25519PublicKey.from_public_bytes(raw)
            except (TypeError, ValueError) as exc:
                raise ControlledArtifactVerificationError(
                    "controlled artifact public key is invalid"
                ) from exc
            if status == "active":
                active[key_id] = key
        return cls(active)

    @classmethod
    def load_pinned(cls) -> "ControlledArtifactPublicKeyRegistry":
        try:
            document = json.loads(
                DEFAULT_CONTROLLED_ARTIFACT_PUBLIC_KEYS_PATH.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ControlledArtifactVerificationError(
                "cannot load pinned controlled artifact registry"
            ) from exc
        if type(document) is not dict:
            raise ControlledArtifactVerificationError(
                "controlled artifact registry must be an object"
            )
        if _digest(document) != PINNED_CONTROLLED_ARTIFACT_REGISTRY_DIGEST:
            raise ControlledArtifactVerificationError(
                "pinned controlled artifact registry digest mismatch"
            )
        return cls.from_document(document)

    def verify(
        self, *, key_id: str, body: Mapping[str, Any], signature: str
    ) -> bool:
        if type(key_id) is not str or type(body) is not dict:
            return False
        key = self._keys.get(key_id)
        if key is None:
            return False
        try:
            key.verify(_decode_signature(signature), _canonical_bytes(body))
        except (ControlledArtifactVerificationError, InvalidSignature, ValueError):
            return False
        return True


class VerifiedControlledExecutionArtifacts:
    """Deep-frozen result returned only after both authority signatures pass."""

    __slots__ = ("_document", "_artifacts")

    def __init_subclass__(cls, **kwargs: Any) -> NoReturn:
        raise TypeError("VerifiedControlledExecutionArtifacts is final")

    def __init__(self, document: dict[str, Any], *, _token: object = None) -> None:
        if _token is not _VERIFIED_BUNDLE_TOKEN:
            raise ControlledArtifactVerificationError(
                "verified controlled artifacts require the pinned loader"
            )
        frozen = _freeze_json(document)
        object.__setattr__(self, "_document", frozen)
        object.__setattr__(self, "_artifacts", frozen["artifacts"])

    @property
    def bundle_id(self) -> str:
        return self._document["bundle_id"]

    @property
    def authorization_id(self) -> str:
        return self._document["authorization_id"]

    @property
    def artifacts(self) -> tuple[Mapping[str, Any], ...]:
        return self._artifacts

    def artifact(self, artifact_type: str) -> Mapping[str, Any]:
        matches = tuple(
            artifact
            for artifact in self._artifacts
            if artifact["artifact_type"] == artifact_type
        )
        if len(matches) != 1:
            raise KeyError(artifact_type)
        return matches[0]

    def to_dict(self) -> dict[str, Any]:
        return _thaw_json(self._document)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ControlledArtifactVerificationError(
                f"controlled artifact JSON contains duplicate key {key!r}"
            )
        document[key] = value
    return document


def _reject_nonfinite_constant(value: str) -> NoReturn:
    raise ControlledArtifactVerificationError(
        f"controlled artifact JSON contains non-finite number {value}"
    )


def _parse_document(payload: bytes | str) -> dict[str, Any]:
    if type(payload) is bytes:
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ControlledArtifactVerificationError(
                "controlled artifact response is not UTF-8"
            ) from exc
    elif type(payload) is str:
        text = payload
    else:
        raise TypeError("controlled artifact response must be exact bytes or str")
    try:
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except json.JSONDecodeError as exc:
        raise ControlledArtifactVerificationError(
            "controlled artifact response is not JSON"
        ) from exc
    if type(document) is not dict:
        raise ControlledArtifactVerificationError(
            "controlled artifact response must be an object"
        )
    return document


def _require_closed(
    document: dict[str, Any], fields: frozenset[str], label: str
) -> None:
    if set(document) != fields:
        missing = sorted(fields - set(document))
        extra = sorted(set(document) - fields)
        raise ControlledArtifactVerificationError(
            f"{label} fields are not closed: missing={missing}, extra={extra}"
        )


def _require_string(document: dict[str, Any], name: str) -> str:
    value = document[name]
    if type(value) is not str or not value:
        raise ControlledArtifactVerificationError(
            f"controlled artifact {name} must be an exact non-empty string"
        )
    return value


def _require_sha(document: dict[str, Any], name: str) -> str:
    value = _require_string(document, name)
    if _SHA256_RE.fullmatch(value) is None:
        raise ControlledArtifactVerificationError(
            f"controlled artifact {name} must be canonical sha256"
        )
    return value


def _require_gross(document: dict[str, Any]) -> float:
    value = document["max_gross_weight"]
    if (
        type(value) is not float
        or not math.isfinite(value)
        or not 0.0 < value <= 1.0
    ):
        raise ControlledArtifactVerificationError(
            "controlled artifact max_gross_weight must be an exact finite "
            "float in (0, 1]"
        )
    return value


def _require_timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlledArtifactVerificationError(
            "controlled artifact written_at is not ISO datetime"
        ) from exc
    if parsed.tzinfo is None:
        raise ControlledArtifactVerificationError(
            "controlled artifact written_at must include timezone"
        )


def _validate_stage_payload(
    payload: Any,
    *,
    artifact_type: str,
    prior_artifacts: tuple[dict[str, Any], ...],
) -> None:
    if type(payload) is not dict:
        raise ControlledArtifactVerificationError(
            f"controlled {artifact_type} payload must be an object"
        )
    _require_closed(
        payload,
        _PAYLOAD_FIELDS[artifact_type],
        f"controlled {artifact_type} payload",
    )
    _require_sha(payload, "content_digest")
    for name, value in payload.items():
        if name == "automatic_promotion":
            continue
        if type(value) is not str or not value:
            raise ControlledArtifactVerificationError(
                f"controlled {artifact_type} payload {name} must be a string"
            )

    if artifact_type == "Paper":
        if payload["lifecycle"] != "Paper":
            raise ControlledArtifactVerificationError(
                "controlled Paper lifecycle must be Paper"
            )
    elif artifact_type == "Risk":
        if (
            payload["paper_artifact_id"] != prior_artifacts[0]["artifact_id"]
            or payload["status"] not in {"PASS", "REVIEW", "FAIL"}
        ):
            raise ControlledArtifactVerificationError(
                "controlled Risk payload does not bind the Paper artifact"
            )
    elif artifact_type == "Selection":
        if (
            payload["paper_artifact_id"] != prior_artifacts[0]["artifact_id"]
            or payload["risk_artifact_id"] != prior_artifacts[1]["artifact_id"]
            or payload["decision"] not in {"PROMOTE", "HOLD", "REJECT"}
            or payload["automatic_promotion"] is not False
        ):
            raise ControlledArtifactVerificationError(
                "controlled Selection payload lineage or policy is invalid"
            )
    elif (
        payload["selection_artifact_id"]
        != prior_artifacts[2]["artifact_id"]
    ):
        raise ControlledArtifactVerificationError(
            "controlled Knowledge payload does not bind Selection"
        )


def _freeze_json(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw_json(item) for item in value]
    return value


def _validate_artifact(
    artifact: Any,
    *,
    artifact_type: str,
    bundle: dict[str, Any],
    expected_parents: tuple[str, ...],
    prior_artifacts: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    if type(artifact) is not dict:
        raise ControlledArtifactVerificationError(
            f"controlled {artifact_type} artifact must be an object"
        )
    _require_closed(artifact, _ARTIFACT_FIELDS, f"controlled {artifact_type}")
    if (
        artifact["format"] != CONTROLLED_ARTIFACT_FORMAT
        or artifact["artifact_type"] != artifact_type
        or artifact["schema_version"]
        != CONTROLLED_ARTIFACT_SCHEMA_VERSIONS[artifact_type]
        or artifact["producer"] != CONTROLLED_ARTIFACT_WRITER_ISSUER
    ):
        raise ControlledArtifactVerificationError(
            f"controlled {artifact_type} artifact identity is invalid"
        )
    artifact_id = _require_sha(artifact, "artifact_id")
    for name in _COMMON_ARTIFACT_FIELDS:
        value = artifact[name]
        if type(value) not in {str, float} or value != bundle[name]:
            raise ControlledArtifactVerificationError(
                f"controlled {artifact_type} artifact {name} is not bundle-bound"
            )
    parents = artifact["parent_artifact_ids"]
    if (
        type(parents) is not list
        or any(type(item) is not str for item in parents)
        or tuple(parents) != expected_parents
    ):
        raise ControlledArtifactVerificationError(
            f"controlled {artifact_type} artifact parent lineage is invalid"
        )
    _validate_stage_payload(
        artifact["payload"],
        artifact_type=artifact_type,
        prior_artifacts=prior_artifacts,
    )
    identity = dict(artifact)
    identity.pop("artifact_id")
    if artifact_id != _digest(identity):
        raise ControlledArtifactVerificationError(
            f"controlled {artifact_type} artifact_id does not match content"
        )
    return artifact


def load_verified_controlled_execution_artifacts(
    payload: bytes | str,
    *,
    authorization: VerifiedTraderAuthorization,
) -> VerifiedControlledExecutionArtifacts:
    """Parse and verify one authority-returned canonical four-artifact bundle.

    The caller may provide bytes and the already-returned Trader authorization,
    but cannot provide a key registry, signer, store, output path, or verifier.
    Both trust roots are loaded from pinned public-only registries.
    """

    document = _parse_document(payload)
    _require_closed(document, _BUNDLE_FIELDS, "controlled artifact bundle")
    if (
        document["format"] != CONTROLLED_ARTIFACT_BUNDLE_FORMAT
        or document["issuer"] != CONTROLLED_ARTIFACT_WRITER_ISSUER
        or type(document["generation_count"]) is not int
        or document["generation_count"] != 1
        or document["automatic_promotion"] is not False
    ):
        raise ControlledArtifactVerificationError(
            "controlled artifact bundle policy identity is invalid"
        )

    for name in (
        "bundle_id",
        "authorization_id",
        "strategy_spec_hash",
        "ready_snapshot_id",
        "ready_manifest_digest",
        "profile_digest",
        "plan_set_digest",
        "dependency_closure_digest",
        "universe_rule_digest",
        "resolved_universe_digest",
    ):
        _require_sha(document, name)
    for name in (
        "strategy_id",
        "readiness_attestation_id",
        "universe_contract_id",
        "period_start",
        "period_end",
        "cost_scenario",
        "written_at",
        "writer_key_id",
        "issuer",
        "signature",
    ):
        _require_string(document, name)
    _require_gross(document)
    if document["period_start"] > document["period_end"]:
        raise ControlledArtifactVerificationError(
            "controlled artifact period is reversed"
        )
    _require_timestamp(document["written_at"])

    artifacts = document["artifacts"]
    if type(artifacts) is not list or len(artifacts) != 4:
        raise ControlledArtifactVerificationError(
            "controlled artifact bundle requires exactly four artifacts"
        )
    validated: list[dict[str, Any]] = []
    for index, artifact_type in enumerate(CONTROLLED_ARTIFACT_TYPES):
        if index == 0:
            parents = (document["authorization_id"],)
        elif index == 1:
            parents = (validated[0]["artifact_id"],)
        elif index == 2:
            parents = (
                validated[0]["artifact_id"],
                validated[1]["artifact_id"],
            )
        else:
            parents = tuple(item["artifact_id"] for item in validated)
        validated.append(
            _validate_artifact(
                artifacts[index],
                artifact_type=artifact_type,
                bundle=document,
                expected_parents=parents,
                prior_artifacts=tuple(validated),
            )
        )

    unsigned_identity = dict(document)
    unsigned_identity.pop("signature")
    declared_bundle_id = unsigned_identity.pop("bundle_id")
    if declared_bundle_id != _digest(unsigned_identity):
        raise ControlledArtifactVerificationError(
            "controlled artifact bundle_id does not match content"
        )

    registry = ControlledArtifactPublicKeyRegistry.load_pinned()
    if registry.active_key_count == 0:
        raise ControlledArtifactAuthorityPending()

    binding = TraderAuthorizationBinding(
        authorization_id=document["authorization_id"],
        strategy_id=document["strategy_id"],
        strategy_spec_hash=document["strategy_spec_hash"],
        max_gross_weight=document["max_gross_weight"],
        ready_snapshot_id=document["ready_snapshot_id"],
        ready_manifest_digest=document["ready_manifest_digest"],
        readiness_attestation_id=document["readiness_attestation_id"],
        profile_digest=document["profile_digest"],
        plan_set_digest=document["plan_set_digest"],
        dependency_closure_digest=document["dependency_closure_digest"],
        universe_contract_id=document["universe_contract_id"],
        universe_rule_digest=document["universe_rule_digest"],
        resolved_universe_digest=document["resolved_universe_digest"],
        period_start=document["period_start"],
        period_end=document["period_end"],
        cost_scenario=document["cost_scenario"],
    )
    if not verify_exact_trader_authorization(authorization, binding):
        raise ControlledArtifactVerificationError(
            "controlled artifacts do not match a valid exact Trader authorization"
        )

    signed_body = dict(document)
    signature = signed_body.pop("signature")
    if not registry.verify(
        key_id=document["writer_key_id"],
        body=signed_body,
        signature=signature,
    ):
        raise ControlledArtifactVerificationError(
            "controlled artifact writer signature is invalid"
        )
    return VerifiedControlledExecutionArtifacts(
        document, _token=_VERIFIED_BUNDLE_TOKEN
    )


def verify_controlled_artifact_content(
    content: bytes, *, expected_digest: str
) -> bool:
    """Verify authority-returned artifact bytes against a signed content ref."""

    if type(content) is not bytes or type(expected_digest) is not str:
        return False
    if _SHA256_RE.fullmatch(expected_digest) is None:
        return False
    return (
        "sha256:" + hashlib.sha256(content).hexdigest()
        == expected_digest
    )


__all__ = [
    "CONTROLLED_ARTIFACT_AUTHORITY_UNPROVISIONED",
    "CONTROLLED_ARTIFACT_SCHEMA_VERSIONS",
    "CONTROLLED_ARTIFACT_TYPES",
    "ControlledArtifactAuthorityPending",
    "ControlledArtifactPublicKeyRegistry",
    "ControlledArtifactVerificationError",
    "VerifiedControlledExecutionArtifacts",
    "load_verified_controlled_execution_artifacts",
    "verify_controlled_artifact_content",
]
