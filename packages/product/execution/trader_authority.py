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

    def to_canonical_body(self) -> dict[str, Any]:
        return {
            "format": TRADER_AUTHORIZATION_FORMAT,
            "authorization_id": self.authorization_id,
            "mode": self.mode,
            "strategy_id": self.strategy_id,
            "strategy_spec_hash": self.strategy_spec_hash,
            "max_gross_weight": self.max_gross_weight,
            "ready_snapshot_id": self.ready_snapshot_id,
            "ready_manifest_digest": self.ready_manifest_digest,
            "readiness_attestation_id": self.readiness_attestation_id,
            "profile_digest": self.profile_digest,
            "plan_set_digest": self.plan_set_digest,
            "dependency_closure_digest": self.dependency_closure_digest,
            "universe_contract_id": self.universe_contract_id,
            "universe_rule_digest": self.universe_rule_digest,
            "resolved_universe_digest": self.resolved_universe_digest,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "cost_scenario": self.cost_scenario,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "key_id": self.key_id,
            "issuer": self.issuer,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_canonical_body(), "signature": self.signature}

    def is_valid(
        self,
        *,
        now: datetime | None = None,
    ) -> bool:
        return _verify_pinned_trader_authorization(self, now=now)

    def require_valid(self, **kwargs: Any) -> "VerifiedTraderAuthorization":
        if not self.is_valid(**kwargs):
            raise MassResearchDisabledError(
                "VerifiedTraderAuthorization is expired, forged, or malformed"
            )
        return self


def _verify_pinned_trader_authorization(
    authorization: VerifiedTraderAuthorization,
    *,
    now: datetime | None = None,
) -> bool:
    """Authoritative product verifier; no caller registry can enter."""

    if type(authorization) is not VerifiedTraderAuthorization:
        return False
    try:
        registry = TraderAuthorizationPublicKeyRegistry.load_pinned()
    except MassResearchDisabledError:
        return False
    digests = (
        authorization.authorization_id,
        authorization.strategy_spec_hash,
        authorization.ready_snapshot_id,
        authorization.ready_manifest_digest,
        authorization.profile_digest,
        authorization.plan_set_digest,
        authorization.dependency_closure_digest,
        authorization.universe_rule_digest,
        authorization.resolved_universe_digest,
    )
    try:
        gross_weight = float(authorization.max_gross_weight)
    except (TypeError, ValueError):
        return False
    if (
        authorization.mode != "paper"
        or authorization.issuer != TRADER_AUTHORIZATION_ISSUER
        or any(
            not isinstance(value, str)
            or not value.startswith("sha256:")
            or len(value) != 71
            for value in digests
        )
        or not authorization.strategy_id
        or not authorization.readiness_attestation_id
        or not authorization.universe_contract_id
        or not authorization.period_start
        or authorization.period_start > authorization.period_end
        or not 0.0 < gross_weight <= 1.0
    ):
        return False
    try:
        issued = datetime.fromisoformat(
            authorization.issued_at.replace("Z", "+00:00")
        )
        expires = datetime.fromisoformat(
            authorization.expires_at.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return False
    if issued.tzinfo is None or expires.tzinfo is None:
        return False
    clock = now or _now()
    if (
        clock < issued - timedelta(minutes=5)
        or clock > expires
        or expires <= issued
        or expires - issued > timedelta(seconds=1800)
    ):
        return False
    id_body = authorization.to_canonical_body()
    id_body.pop("authorization_id")
    if authorization.authorization_id != _digest(id_body):
        return False
    return registry.verify(
        key_id=authorization.key_id,
        body=authorization.to_canonical_body(),
        signature=authorization.signature,
    )


__all__ = [
    "TraderAuthorizationPublicKeyRegistry",
    "VerifiedTraderAuthorization",
]
