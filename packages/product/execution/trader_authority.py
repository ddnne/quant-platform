"""Pinned Ed25519 authority for one controlled-pilot paper authorization.

Agent output is a proposal, not an execution capability.  Only this trusted
service owns the dedicated private key and can mint the signed authorization
accepted by ``ControlledPilotExecutionService``.  The production factories
take no key id, path, registry, or verifier argument.
"""

from __future__ import annotations

import base64
import hashlib
import json
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from agents.types import PortfolioDecision
from selection.budget_ledger import MassResearchDisabledError
from strategies.spec import strategy_spec_digest


TRADER_AUTHORIZATION_FORMAT = "verified-trader-authorization/v1"
TRADER_AUTHORIZATION_ISSUER = "ControlledTraderAuthorizationService/v1"
TRADER_AUTHORIZATION_ALGORITHM = "Ed25519"
DEFAULT_TRADER_AUTHORIZATION_PUBLIC_KEYS_PATH = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "trader_authorization"
    / "public_keys.json"
)
DEFAULT_TRADER_AUTHORIZATION_PRIVATE_KEY_PATH = (
    Path.home()
    / ".config"
    / "quant-platform"
    / "trader_authorization_signing_key.pem"
)
_ISSUER_TOKEN = object()


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
        if len(self._keys) != 1:
            raise MassResearchDisabledError(
                "trader authorization registry requires exactly one active key"
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
        return cls.from_document(document)

    def key_id_for(self, public_key: Ed25519PublicKey) -> str:
        raw = public_key.public_bytes(
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
                "dedicated trader authorization key does not match exactly one "
                "active key in the pinned registry"
            )
        return matches[0]

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
        verifier: TraderAuthorizationPublicKeyRegistry | None = None,
        now: datetime | None = None,
    ) -> bool:
        digests = (
            self.authorization_id,
            self.strategy_spec_hash,
            self.ready_snapshot_id,
            self.ready_manifest_digest,
            self.profile_digest,
            self.plan_set_digest,
            self.dependency_closure_digest,
            self.universe_rule_digest,
            self.resolved_universe_digest,
        )
        try:
            gross_weight = float(self.max_gross_weight)
        except (TypeError, ValueError):
            return False
        if (
            self.mode != "paper"
            or self.issuer != TRADER_AUTHORIZATION_ISSUER
            or any(
                not isinstance(value, str)
                or not value.startswith("sha256:")
                or len(value) != 71
                for value in digests
            )
            or not self.strategy_id
            or not self.readiness_attestation_id
            or not self.universe_contract_id
            or not self.period_start
            or self.period_start > self.period_end
            or not 0.0 < gross_weight <= 1.0
        ):
            return False
        try:
            issued = datetime.fromisoformat(self.issued_at.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return False
        if issued.tzinfo is None or expires.tzinfo is None:
            return False
        clock = now or _now()
        if clock < issued - timedelta(minutes=5) or clock > expires or expires <= issued:
            return False
        id_body = self.to_canonical_body()
        id_body.pop("authorization_id")
        if self.authorization_id != _digest(id_body):
            return False
        registry = verifier or TraderAuthorizationPublicKeyRegistry.load_pinned()
        return registry.verify(
            key_id=self.key_id,
            body=self.to_canonical_body(),
            signature=self.signature,
        )

    def require_valid(self, **kwargs: Any) -> "VerifiedTraderAuthorization":
        if not self.is_valid(**kwargs):
            raise MassResearchDisabledError(
                "VerifiedTraderAuthorization is expired, forged, or malformed"
            )
        return self


class _ControlledTraderAuthorizationIssuer:
    __slots__ = ("_key_id", "_private_key")

    def __init__(
        self,
        *,
        key_id: str,
        private_key: Ed25519PrivateKey,
        _token: object | None = None,
    ) -> None:
        if _token is not _ISSUER_TOKEN:
            raise MassResearchDisabledError(
                "trader authorization issuer is factory-owned"
            )
        self._key_id = str(key_id)
        self._private_key = private_key

    def issue(
        self,
        *,
        decision: PortfolioDecision,
        experiment_plan: Any,
        plan_set_binding: Any,
        ready_manifest: Any,
        readiness: Any,
        resolved_universe: Any,
        ttl_seconds: int = 1800,
    ) -> VerifiedTraderAuthorization:
        from research.artifacts import ExperimentPlan
        from research.readiness import (
            ReadinessPublicKeyRegistry,
            VerifiedPilotReadiness,
        )
        from research.ready_manifest import (
            ExactFourPilotReadyBinding,
            ReadyManifest,
            validate_ready_manifest_profile_binding,
        )
        from research.universe_contract import ResolvedUniverseMembership

        if not isinstance(decision, PortfolioDecision) or not decision.approved:
            raise MassResearchDisabledError(
                "approved PortfolioDecision is required for trader authorization"
            )
        if not isinstance(experiment_plan, ExperimentPlan):
            raise MassResearchDisabledError("exact ExperimentPlan is required")
        if not isinstance(plan_set_binding, ExactFourPilotReadyBinding):
            raise MassResearchDisabledError("exact-four binding is required")
        if not isinstance(ready_manifest, ReadyManifest):
            raise MassResearchDisabledError("ReadyManifest is required")
        if not isinstance(readiness, VerifiedPilotReadiness):
            raise MassResearchDisabledError("VerifiedPilotReadiness is required")
        if not isinstance(resolved_universe, ResolvedUniverseMembership):
            raise MassResearchDisabledError(
                "snapshot-resolved universe membership is required"
            )
        canonical_plan = next(
            (
                plan
                for plan in plan_set_binding.plans
                if plan.plan_id == experiment_plan.plan_id
            ),
            None,
        )
        if (
            canonical_plan is None
            or canonical_plan.to_dict() != experiment_plan.to_dict()
        ):
            raise MassResearchDisabledError(
                "trader authorization plan is not canonical exact-four"
            )
        if decision.strategy_spec.strategy_id != experiment_plan.strategy_spec_id:
            raise MassResearchDisabledError(
                "PortfolioDecision strategy does not match ExperimentPlan"
            )
        validate_ready_manifest_profile_binding(
            ready_manifest, profile=plan_set_binding
        )
        readiness.require_valid(
            expected_snapshot_id=ready_manifest.snapshot_id,
            expected_plan_set_digest=plan_set_binding.plan_set_digest,
            expected_closure_digest=plan_set_binding.closure_set_digest,
            verifier=ReadinessPublicKeyRegistry.load_pinned(),
        )
        if (
            readiness.ready_manifest_digest != ready_manifest.manifest_digest
            or readiness.universe_rule_digest != resolved_universe.rule_digest
            or readiness.resolved_universe_digest
            != resolved_universe.resolved_membership_digest
            or ready_manifest.universe_rule_digest != resolved_universe.rule_digest
            or ready_manifest.resolved_universe_digest
            != resolved_universe.resolved_membership_digest
            or resolved_universe.period_start != experiment_plan.period_start
            or resolved_universe.period_end != experiment_plan.period_end
            or tuple(experiment_plan.universe) != (resolved_universe.rule_id,)
        ):
            raise MassResearchDisabledError(
                "trader authorization READY/universe digest chain mismatch"
            )
        seconds = int(ttl_seconds)
        if seconds < 60 or seconds > 1800:
            raise MassResearchDisabledError(
                "trader authorization ttl must be between 60 and 1800 seconds"
            )
        issued = _now()
        body: dict[str, Any] = {
            "format": TRADER_AUTHORIZATION_FORMAT,
            "mode": "paper",
            "strategy_id": decision.strategy_spec.strategy_id,
            "strategy_spec_hash": strategy_spec_digest(decision.strategy_spec),
            "max_gross_weight": float(decision.max_gross_weight),
            "ready_snapshot_id": ready_manifest.snapshot_id,
            "ready_manifest_digest": ready_manifest.manifest_digest,
            "readiness_attestation_id": readiness.attestation_id,
            "profile_digest": plan_set_binding.profile_digest,
            "plan_set_digest": plan_set_binding.plan_set_digest,
            "dependency_closure_digest": plan_set_binding.closure_set_digest,
            "universe_contract_id": resolved_universe.rule_id,
            "universe_rule_digest": resolved_universe.rule_digest,
            "resolved_universe_digest": (
                resolved_universe.resolved_membership_digest
            ),
            "period_start": experiment_plan.period_start,
            "period_end": experiment_plan.period_end,
            "cost_scenario": experiment_plan.cost_scenario,
            "issued_at": issued.isoformat(),
            "expires_at": (issued + timedelta(seconds=seconds)).isoformat(),
            "key_id": self._key_id,
            "issuer": TRADER_AUTHORIZATION_ISSUER,
        }
        body["authorization_id"] = _digest(body)
        signature = "ed25519:" + base64.b64encode(
            self._private_key.sign(_canonical_bytes(body))
        ).decode("ascii")
        authorization = VerifiedTraderAuthorization(
            signature=signature,
            **{key: value for key, value in body.items() if key != "format"},
        )
        if not authorization.is_valid(
            verifier=TraderAuthorizationPublicKeyRegistry(
                {self._key_id: self._private_key.public_key()}
            ),
            now=issued,
        ):
            raise MassResearchDisabledError(
                "minted trader authorization failed signed invariants"
            )
        return authorization


def open_controlled_trader_authorization_issuer(
) -> _ControlledTraderAuthorizationIssuer:
    """Load the dedicated private key and bind it to the pinned registry."""
    try:
        metadata = DEFAULT_TRADER_AUTHORIZATION_PRIVATE_KEY_PATH.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_mode & 0o077
        ):
            raise OSError(
                "trader authorization signing key must be a regular 0600 file"
            )
        private_pem = DEFAULT_TRADER_AUTHORIZATION_PRIVATE_KEY_PATH.read_bytes()
        private_key = serialization.load_pem_private_key(
            private_pem, password=None
        )
    except (OSError, TypeError, ValueError) as exc:
        raise MassResearchDisabledError(
            "dedicated trader authorization signing key is unavailable"
        ) from exc
    if not isinstance(private_key, Ed25519PrivateKey):
        raise MassResearchDisabledError(
            "trader authorization signing key must be Ed25519"
        )
    registry = TraderAuthorizationPublicKeyRegistry.load_pinned()
    key_id = registry.key_id_for(private_key.public_key())
    return _ControlledTraderAuthorizationIssuer(
        key_id=key_id,
        private_key=private_key,
        _token=_ISSUER_TOKEN,
    )


__all__ = [
    "TraderAuthorizationPublicKeyRegistry",
    "VerifiedTraderAuthorization",
    "open_controlled_trader_authorization_issuer",
]
