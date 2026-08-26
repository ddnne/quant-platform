"""Pinned Ed25519 verifier for controlled-pilot Trader authorization.

Agent output is a proposal, not an execution capability.  This product module
contains public verification material only.  The dedicated authorization
authority is an external security principal and is intentionally not
provisioned in the application process.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from selection.budget_ledger import MassResearchDisabledError


TRADER_AUTHORIZATION_FORMAT = "verified-trader-authorization/v1"
TRADER_AUTHORIZATION_ISSUER = "ControlledTraderAuthorizationService/v1"
TRADER_AUTHORIZATION_ALGORITHM = "Ed25519"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
PINNED_TRADER_AUTHORIZATION_REGISTRY_DIGEST = (
    "sha256:14c1968604545135545c7dc13d353110b9148d911edd0dababe80bb07381096c"
)
DEFAULT_TRADER_AUTHORIZATION_PUBLIC_KEYS_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "trader_authorization"
    / "public_keys.json"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _decode_signature(signature: str) -> bytes:
    if not isinstance(signature, str) or not signature.startswith("ed25519:"):
        raise ValueError("trader authorization signature must be Ed25519")
    return base64.b64decode(signature[len("ed25519:") :], validate=True)


@dataclass(frozen=True, slots=True)
class TraderAuthorizationPublicKeyRegistry:
    """Public-key-only pinned verifier registry."""

    _keys: Mapping[str, Ed25519PublicKey]

    def __post_init__(self) -> None:
        if len(self._keys) > 1:
            raise MassResearchDisabledError(
                "trader authorization registry permits at most one active key"
            )
        normalized: dict[str, Ed25519PublicKey] = {}
        for raw_id, key in self._keys.items():
            key_id = str(raw_id).strip()
            if not key_id or not isinstance(key, Ed25519PublicKey):
                raise MassResearchDisabledError(
                    "trader authorization registry entry is invalid"
                )
            normalized[key_id] = key
        object.__setattr__(self, "_keys", MappingProxyType(normalized))

    @classmethod
    def from_document(
        cls, document: Mapping[str, Any]
    ) -> "TraderAuthorizationPublicKeyRegistry":
        if (
            document.get("schema_version") != 1
            or document.get("purpose")
            != "controlled_trader_authorization_verification"
        ):
            raise MassResearchDisabledError(
                "trader authorization registry identity is invalid"
            )
        rows = document.get("keys")
        if not isinstance(rows, list) or not rows:
            raise MassResearchDisabledError(
                "trader authorization registry keys are missing"
            )
        active: dict[str, Ed25519PublicKey] = {}
        seen_ids: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise MassResearchDisabledError(
                    "trader authorization registry row is invalid"
                )
            if row.get("algorithm") != TRADER_AUTHORIZATION_ALGORITHM:
                raise MassResearchDisabledError(
                    "trader authorization registry requires Ed25519"
                )
            status = row.get("status")
            if status not in {"active", "revoked"}:
                raise MassResearchDisabledError(
                    "trader authorization key status must be explicit active/revoked"
                )
            key_id = str(row.get("key_id") or "").strip()
            if not key_id or key_id in seen_ids:
                raise MassResearchDisabledError(
                    "trader authorization key ids must be unique"
                )
            seen_ids.add(key_id)
            try:
                raw = base64.b64decode(
                    str(row.get("public_key_b64") or ""), validate=True
                )
                public_key = Ed25519PublicKey.from_public_bytes(raw)
            except (TypeError, ValueError) as exc:
                raise MassResearchDisabledError(
                    f"trader authorization public key is invalid: {key_id}"
                ) from exc
            if status == "active":
                active[key_id] = public_key
        return cls(active)

    @classmethod
    def load_pinned(cls) -> "TraderAuthorizationPublicKeyRegistry":
        try:
            document = json.loads(
                DEFAULT_TRADER_AUTHORIZATION_PUBLIC_KEYS_PATH.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise MassResearchDisabledError(
                "cannot load pinned trader authorization registry"
            ) from exc
        if not isinstance(document, Mapping):
            raise MassResearchDisabledError(
                "trader authorization registry must be an object"
            )
        if _digest(document) != PINNED_TRADER_AUTHORIZATION_REGISTRY_DIGEST:
            raise MassResearchDisabledError(
                "pinned trader authorization registry digest mismatch"
            )
        return cls.from_document(document)

    def verify(
        self, *, key_id: str, body: Mapping[str, Any], signature: str
    ) -> bool:
        key = self._keys.get(str(key_id))
        if key is None:
            return False
        try:
            key.verify(_decode_signature(signature), _canonical_bytes(body))
        except (InvalidSignature, TypeError, ValueError):
            return False
        return True


@dataclass(frozen=True, slots=True)
class VerifiedTraderAuthorization:
    """Signed, immutable authorization for one exact READY/plan/universe."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("VerifiedTraderAuthorization is final")

    authorization_id: str
    mode: str
    strategy_id: str
    strategy_spec_hash: str
    max_gross_weight: float
    ready_snapshot_id: str
    ready_manifest_digest: str
    readiness_attestation_id: str
    profile_digest: str
    plan_set_digest: str
    dependency_closure_digest: str
    universe_contract_id: str
    universe_rule_digest: str
    resolved_universe_digest: str
    period_start: str
    period_end: str
    cost_scenario: str
    issued_at: str
    expires_at: str
    key_id: str
    signature: str
    issuer: str = TRADER_AUTHORIZATION_ISSUER

    def __post_init__(self) -> None:
        # Do not admit str/float subclasses or stateful coercion objects into
        # an authority-bearing DTO.  Verification below still snapshots every
        # field once because ``frozen=True`` is not an OS security boundary.
        _materialize_authorization(self)

    def to_canonical_body(self) -> dict[str, Any]:
        body, _signature = _materialize_authorization(self)
        return body

    def to_dict(self) -> dict[str, Any]:
        body, signature = _materialize_authorization(self)
        return {**body, "signature": signature}

    def is_valid(self) -> bool:
        return _verify_pinned_trader_authorization(self)

    def require_valid(self) -> "VerifiedTraderAuthorization":
        if not self.is_valid():
            raise MassResearchDisabledError(
                "VerifiedTraderAuthorization is expired, forged, or malformed"
            )
        return self


@dataclass(frozen=True, slots=True)
class TraderAuthorizationBinding:
    """Authority-free expected values reconstructed by a trusted consumer.

    This object does not approve or sign anything.  It freezes the exact
    READY/plan/closure/universe/StrategySpec/gross-limit values that a
    separately permissioned human-approval authority must have signed.  The
    product verifier compares the signed body with this binding atomically.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("TraderAuthorizationBinding is final")

    authorization_id: str
    strategy_id: str
    strategy_spec_hash: str
    max_gross_weight: float
    ready_snapshot_id: str
    ready_manifest_digest: str
    readiness_attestation_id: str
    profile_digest: str
    plan_set_digest: str
    dependency_closure_digest: str
    universe_contract_id: str
    universe_rule_digest: str
    resolved_universe_digest: str
    period_start: str
    period_end: str
    cost_scenario: str
    issued_at: str
    expires_at: str

    def __post_init__(self) -> None:
        values = tuple(
            object.__getattribute__(self, name)
            for name in _BINDING_STRING_FIELDS
        )
        if any(type(value) is not str or not value for value in values):
            raise TypeError(
                "TraderAuthorizationBinding requires exact non-empty strings"
            )
        gross = object.__getattribute__(self, "max_gross_weight")
        if type(gross) is not float or not math.isfinite(gross):
            raise TypeError(
                "TraderAuthorizationBinding max_gross_weight must be an exact "
                "finite float"
            )
        if not 0.0 < gross <= 1.0:
            raise ValueError(
                "TraderAuthorizationBinding max_gross_weight must be in (0, 1]"
            )
        _materialize_binding(self)

    def to_dict(self) -> dict[str, Any]:
        return _materialize_binding(self)


_AUTHORIZATION_STRING_FIELDS = (
    "authorization_id",
    "mode",
    "strategy_id",
    "strategy_spec_hash",
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
    "issued_at",
    "expires_at",
    "key_id",
    "signature",
    "issuer",
)

_BINDING_STRING_FIELDS = (
    "authorization_id",
    "strategy_id",
    "strategy_spec_hash",
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
    "issued_at",
    "expires_at",
)


def _materialize_authorization(
    authorization: VerifiedTraderAuthorization,
) -> tuple[dict[str, Any], str]:
    """Read every signed field exactly once and require built-in scalars."""

    if type(authorization) is not VerifiedTraderAuthorization:
        raise TypeError("exact VerifiedTraderAuthorization required")
    values = {
        name: object.__getattribute__(authorization, name)
        for name in _AUTHORIZATION_STRING_FIELDS
    }
    if any(type(value) is not str for value in values.values()):
        raise TypeError(
            "VerifiedTraderAuthorization fields must be exact built-in strings"
        )
    gross = object.__getattribute__(authorization, "max_gross_weight")
    if type(gross) is not float or not math.isfinite(gross):
        raise TypeError(
            "VerifiedTraderAuthorization max_gross_weight must be an exact "
            "finite float"
        )
    body = {
        "format": TRADER_AUTHORIZATION_FORMAT,
        "authorization_id": values["authorization_id"],
        "mode": values["mode"],
        "strategy_id": values["strategy_id"],
        "strategy_spec_hash": values["strategy_spec_hash"],
        "max_gross_weight": gross,
        "ready_snapshot_id": values["ready_snapshot_id"],
        "ready_manifest_digest": values["ready_manifest_digest"],
        "readiness_attestation_id": values["readiness_attestation_id"],
        "profile_digest": values["profile_digest"],
        "plan_set_digest": values["plan_set_digest"],
        "dependency_closure_digest": values["dependency_closure_digest"],
        "universe_contract_id": values["universe_contract_id"],
        "universe_rule_digest": values["universe_rule_digest"],
        "resolved_universe_digest": values["resolved_universe_digest"],
        "period_start": values["period_start"],
        "period_end": values["period_end"],
        "cost_scenario": values["cost_scenario"],
        "issued_at": values["issued_at"],
        "expires_at": values["expires_at"],
        "key_id": values["key_id"],
        "issuer": values["issuer"],
    }
    return body, values["signature"]


def _materialize_binding(binding: TraderAuthorizationBinding) -> dict[str, Any]:
    if type(binding) is not TraderAuthorizationBinding:
        raise TypeError("exact TraderAuthorizationBinding required")
    values = {
        name: object.__getattribute__(binding, name)
        for name in _BINDING_STRING_FIELDS
    }
    if any(type(value) is not str or not value for value in values.values()):
        raise TypeError(
            "TraderAuthorizationBinding requires exact non-empty strings"
        )
    gross = object.__getattribute__(binding, "max_gross_weight")
    if type(gross) is not float or not math.isfinite(gross):
        raise TypeError(
            "TraderAuthorizationBinding max_gross_weight must be an exact "
            "finite float"
        )
    for name in (
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
        if _SHA256_RE.fullmatch(values[name]) is None:
            raise ValueError(f"TraderAuthorizationBinding {name} is not sha256")
    return {**values, "max_gross_weight": gross}


def _verify_pinned_trader_authorization(
    authorization: VerifiedTraderAuthorization,
) -> bool:
    """Authoritative product verifier; no caller registry can enter."""

    try:
        body, signature = _materialize_authorization(authorization)
        registry = TraderAuthorizationPublicKeyRegistry.load_pinned()
    except (MassResearchDisabledError, TypeError, ValueError):
        return False
    return _verify_materialized_authorization(
        body,
        signature=signature,
        registry=registry,
    )


def verify_exact_trader_authorization(
    authorization: VerifiedTraderAuthorization,
    binding: TraderAuthorizationBinding,
) -> bool:
    """Verify signature and exact independently reconstructed decision values.

    The same one-time materialization is used for both cryptographic and
    semantic checks.  A caller cannot make validation observe one value and
    the execution-artifact verifier observe another via a stateful scalar.
    """

    try:
        body, signature = _materialize_authorization(authorization)
        expected = _materialize_binding(binding)
        registry = TraderAuthorizationPublicKeyRegistry.load_pinned()
    except (MassResearchDisabledError, TypeError, ValueError):
        return False

    if not _verify_materialized_authorization(
        body, signature=signature, registry=registry
    ):
        return False
    return all(body[name] == value for name, value in expected.items())


def _verify_materialized_authorization(
    body: Mapping[str, Any],
    *,
    signature: str,
    registry: TraderAuthorizationPublicKeyRegistry,
) -> bool:
    """Verify an already-frozen body without rereading the source object."""

    digests = tuple(
        body[name]
        for name in (
            "authorization_id",
            "strategy_spec_hash",
            "ready_snapshot_id",
            "ready_manifest_digest",
            "profile_digest",
            "plan_set_digest",
            "dependency_closure_digest",
            "universe_rule_digest",
            "resolved_universe_digest",
        )
    )
    if (
        body.get("format") != TRADER_AUTHORIZATION_FORMAT
        or body.get("mode") != "paper"
        or body.get("issuer") != TRADER_AUTHORIZATION_ISSUER
        or any(
            type(value) is not str
            or _SHA256_RE.fullmatch(value) is None
            for value in digests
        )
        or type(body.get("strategy_id")) is not str
        or not body["strategy_id"]
        or type(body.get("readiness_attestation_id")) is not str
        or not body["readiness_attestation_id"]
        or type(body.get("universe_contract_id")) is not str
        or not body["universe_contract_id"]
        or type(body.get("period_start")) is not str
        or type(body.get("period_end")) is not str
        or not body["period_start"]
        or body["period_start"] > body["period_end"]
        or type(body.get("max_gross_weight")) is not float
        or not 0.0 < body["max_gross_weight"] <= 1.0
    ):
        return False
    try:
        issued = datetime.fromisoformat(body["issued_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(
            body["expires_at"].replace("Z", "+00:00")
        )
    except (AttributeError, TypeError, ValueError):
        return False
    if issued.tzinfo is None or expires.tzinfo is None:
        return False
    clock = _now()
    if (
        clock < issued - timedelta(minutes=5)
        or clock > expires
        or expires <= issued
        or expires - issued > timedelta(seconds=1800)
    ):
        return False
    id_body = dict(body)
    id_body.pop("authorization_id", None)
    return body["authorization_id"] == _digest(id_body) and registry.verify(
        key_id=body["key_id"], body=body, signature=signature
    )


__all__ = [
    "TraderAuthorizationBinding",
    "TraderAuthorizationPublicKeyRegistry",
    "VerifiedTraderAuthorization",
    "verify_exact_trader_authorization",
]
