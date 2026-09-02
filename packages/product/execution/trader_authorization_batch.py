"""Verify-only signed exact-four Trader authorization batch v2.

One closed canonical body, one signature, one environment-specific ACTIVE
key.  This module does not mint authorizations.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from execution.controlled_fill_contract import (
    CONTROLLED_FILL_CONTRACT_DIGEST,
    require_controlled_fill_contract_digest,
)
from execution.exact_four_binding import load_exact_four_execution_binding
from research.experiment_plans import PILOT_EXPERIMENT_PLAN_IDS
from selection.budget_ledger import MassResearchDisabledError
from selection.controlled_pilot_policy import (
    CONTROLLED_PILOT_IDENTITY,
    CONTROLLED_PILOT_POLICY_DIGEST,
    require_controlled_pilot_identity,
)


TRADER_BATCH_FORMAT = "controlled-pilot-trader-authorization-batch/v2"
TRADER_BATCH_ISSUER = "ControlledTraderAuthorizationService/v1"
TRADER_AUTHORITY_ALGORITHM = "Ed25519"
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ENVIRONMENTS = frozenset({"staging", "production"})
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 86_400

_PINNED_PRODUCTION = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "trader_authorization"
    / "public_keys.json"
)
_PINNED_STAGING = (
    Path(__file__).resolve().parents[3]
    / "specs"
    / "trader_authorization"
    / "public_keys.staging.json"
)

_BODY_FIELDS = (
    "format",
    "schema_version",
    "purpose",
    "algorithm",
    "identity",
    "environment",
    "authority_instance_id",
    "request_digest",
    "idempotency_key",
    "ready_attestation_id",
    "ready_manifest_digest",
    "snapshot_id",
    "immutable_db_digest",
    "snapshot_key",
    "snapshot_size",
    "profile_digest",
    "dependency_closure_digest",
    "exact_four_binding_digest",
    "policy_digest",
    "budget_scope_digest",
    "execution_limit_set_digest",
    "resolved_universe_digest",
    "fill_contract_digest",
    "rows",
    "issued_at",
    "expires_at",
    "key_id",
    "issuer",
)
_REGISTRY_FIELDS = {
    "schema_version",
    "purpose",
    "environment",
    "authority_instance_id",
    "keys",
}
_KEY_ROW_FIELDS = {"key_id", "algorithm", "public_key_b64", "status", "not_before", "not_after", "revoked_at"}
PINNED_TRADER_REGISTRY_RAW = {
    "production": (
        "sha256:68aef4c6bc2571b368718546da362156e76b7c452676b9db26d87c6eb44ceded",
        519,
        "sha256:ca52153e148fc0603a6073cd2eecb7eeaa058345eefc4dbfa882664fc1640e49",
    ),
    "staging": (
        "sha256:cd9599a08f5e6ec9fcfc3f3441dfd78edb23ff0a7138102062c7fc9f201e093d",
        187,
        "sha256:99333ec060ada318e65d8bb61479397cd601f127a28c3d670fc8b24435efbdd1",
    ),
}
TRADER_BATCH_PURPOSE = "controlled_trader_authorization_verification"
TRADER_BATCH_SCHEMA_VERSION = 2
_ROW_FIELDS = (
    "ordinal",
    "plan_id",
    "plan_binding_digest",
    "strategy_spec_id",
    "strategy_spec_version",
    "strategy_spec_hash",
)


class TraderBatchAuthorizationError(MassResearchDisabledError):
    """Raised when the signed exact-four batch is missing or invalid."""


def trader_authority_instance_id(environment: str) -> str:
    if environment not in _ENVIRONMENTS:
        raise TraderBatchAuthorizationError("trader environment is invalid")
    return f"trader-authority/{environment}/v1"


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Mapping[str, Any] | Sequence[Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value) if isinstance(value, Mapping) else json.dumps(
        list(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    return type(value) is str and bool(_SHA256_RE.fullmatch(value))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise TraderBatchAuthorizationError(
                f"trader JSON contains duplicate key {key!r}"
            )
        document[key] = value
    return document


def _reject_nonfinite(value: str) -> None:
    raise TraderBatchAuthorizationError(
        f"trader JSON contains non-finite constant {value!r}"
    )


def decode_strict_trader_json(payload: bytes) -> Any:
    if type(payload) is not bytes:
        raise TraderBatchAuthorizationError("trader JSON must be one immutable byte string")
    try:
        return json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except TraderBatchAuthorizationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TraderBatchAuthorizationError("trader JSON is invalid") from exc


def _load_active_key(environment: str, key_id: str) -> Ed25519PublicKey:
    path = _PINNED_STAGING if environment == "staging" else _PINNED_PRODUCTION
    try:
        raw = path.read_bytes()
        raw_digest, raw_size, canonical = PINNED_TRADER_REGISTRY_RAW[environment]
        observed_raw = "sha256:" + hashlib.sha256(raw).hexdigest()
        if len(raw) != raw_size or observed_raw != raw_digest or raw_digest == canonical:
            raise TraderBatchAuthorizationError("trader registry raw digest mismatch")
        document = decode_strict_trader_json(raw)
        if _digest(document) != canonical:
            raise TraderBatchAuthorizationError("trader registry canonical digest mismatch")
    except (OSError, TraderBatchAuthorizationError) as exc:
        raise TraderBatchAuthorizationError(
            "cannot load pinned trader authorization registry"
        ) from exc
    if type(document) is not dict or set(document) != _REGISTRY_FIELDS:
        raise TraderBatchAuthorizationError("trader registry shape is invalid")
    if (
        document.get("schema_version") != TRADER_BATCH_SCHEMA_VERSION
        or document.get("purpose") != TRADER_BATCH_PURPOSE
        or document.get("environment") != environment
        or document.get("authority_instance_id")
        != trader_authority_instance_id(environment)
        or type(document.get("keys")) is not list
    ):
        raise TraderBatchAuthorizationError("trader registry contract is invalid")
    rows = document["keys"]
    active: dict[str, Ed25519PublicKey] = {}
    seen: set[str] = set()
    for row in rows:
        if type(row) is not dict or set(row) != _KEY_ROW_FIELDS:
            raise TraderBatchAuthorizationError("trader registry key row is invalid")
        if row.get("algorithm") != TRADER_AUTHORITY_ALGORITHM:
            raise TraderBatchAuthorizationError("trader registry algorithm is invalid")
        if row.get("status") not in {"active", "revoked", "pending"}:
            raise TraderBatchAuthorizationError("trader registry status is invalid")
        rid = str(row.get("key_id") or "").strip()
        if not rid or rid in seen:
            raise TraderBatchAuthorizationError("trader public-key ids must be unique")
        seen.add(rid)
        if row.get("status") == "revoked" and row.get("revoked_at") in {None, ""}:
            raise TraderBatchAuthorizationError("trader revoked key missing revoked_at")
        if row.get("status") != "active":
            continue
        if row.get("revoked_at") is not None:
            raise TraderBatchAuthorizationError("active trader key must not set revoked_at")
        try:
            active[rid] = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(str(row.get("public_key_b64") or ""), validate=True)
            )
        except (TypeError, ValueError) as exc:
            raise TraderBatchAuthorizationError(
                f"trader public key is invalid: {rid}"
            ) from exc
    if len(active) > 1:
        raise TraderBatchAuthorizationError(
            "pinned trader registry has multiple active keys"
        )
    key = active.get(key_id)
    if key is None:
        raise TraderBatchAuthorizationError("trader authorization issuer is untrusted")
    return key


def verify_trader_authorization_batch(
    document: Mapping[str, Any],
    *,
    environment: str,
    request_digest: str,
    idempotency_key: str,
    ready_attestation_id: str,
    ready_manifest_digest: str,
    snapshot_id: str,
    immutable_db_digest: str,
    snapshot_key: str,
    snapshot_size: int,
    resolved_universe_digest: str,
    keys: Mapping[str, Ed25519PublicKey] | None = None,
    now: datetime | None = None,
) -> str:
    """Verify one signed exact-four batch. Returns the authorization digest."""

    if environment not in _ENVIRONMENTS:
        raise TraderBatchAuthorizationError("trader environment is invalid")
    if type(document) is not dict:
        raise TraderBatchAuthorizationError("trader authorization must be an object")
    extra = sorted(set(document) - set(_BODY_FIELDS) - {"signature"})
    if extra:
        raise TraderBatchAuthorizationError(
            f"trader authorization has unknown field(s): {extra}"
        )
    missing = [field for field in (*_BODY_FIELDS, "signature") if field not in document]
    if missing:
        raise TraderBatchAuthorizationError(
            f"trader authorization missing {missing}"
        )
    try:
        require_controlled_pilot_identity(document.get("identity"))
        require_controlled_fill_contract_digest(document.get("fill_contract_digest"))
    except Exception as exc:
        raise TraderBatchAuthorizationError(str(exc)) from exc
    binding = load_exact_four_execution_binding()
    if (
        document.get("format") != TRADER_BATCH_FORMAT
        or document.get("environment") != environment
        or document.get("authority_instance_id") != trader_authority_instance_id(environment)
        or document.get("request_digest") != request_digest
        or document.get("idempotency_key") != idempotency_key
        or document.get("ready_attestation_id") != ready_attestation_id
        or document.get("ready_manifest_digest") != ready_manifest_digest
        or document.get("snapshot_id") != snapshot_id
        or document.get("immutable_db_digest") != immutable_db_digest
        or document.get("snapshot_key") != snapshot_key
        or document.get("snapshot_size") != snapshot_size
        or document.get("profile_digest") != binding.profile_set_digest
        or document.get("dependency_closure_digest") != binding.dependency_closure_set_digest
        or document.get("exact_four_binding_digest") != binding.binding_digest
        or document.get("policy_digest") != CONTROLLED_PILOT_POLICY_DIGEST
        or document.get("budget_scope_digest") != binding.budget_scope_digest
        or document.get("execution_limit_set_digest") != binding.execution_limit_set_digest
        or document.get("resolved_universe_digest") != resolved_universe_digest
        or not _is_sha256(document.get("resolved_universe_digest"))
        or document.get("fill_contract_digest") != CONTROLLED_FILL_CONTRACT_DIGEST
        or document.get("issuer") != TRADER_BATCH_ISSUER
        or document.get("schema_version") != TRADER_BATCH_SCHEMA_VERSION
        or document.get("purpose") != TRADER_BATCH_PURPOSE
        or document.get("algorithm") != TRADER_AUTHORITY_ALGORITHM
        or snapshot_id == immutable_db_digest
    ):
        raise TraderBatchAuthorizationError(
            "trader authorization does not bind the closed exact-four batch"
        )
    rows = document.get("rows")
    if type(rows) is not list or len(rows) != 4:
        raise TraderBatchAuthorizationError("trader authorization rows must be exact four")
    expected_plans = list(PILOT_EXPERIMENT_PLAN_IDS)
    expected_bindings = list(binding.plan_bindings)
    for index, raw in enumerate(rows):
        if type(raw) is not dict or set(raw) != set(_ROW_FIELDS):
            raise TraderBatchAuthorizationError("trader authorization row is invalid")
        plan = expected_bindings[index]
        if (
            raw.get("ordinal") != index + 1
            or raw.get("plan_id") != expected_plans[index]
            or raw.get("plan_id") != plan.plan_id
            or raw.get("plan_binding_digest") != plan.binding_digest
            or raw.get("strategy_spec_id") != plan.strategy_spec_id
            or raw.get("strategy_spec_version") != plan.strategy_spec_version
            or raw.get("strategy_spec_hash") != plan.strategy_spec_hash
        ):
            raise TraderBatchAuthorizationError(
                "trader authorization plan sequence is not the canonical ordered four"
            )
    try:
        from paper_runtime.canonical_utc import CanonicalUtcError, parse_canonical_utc, require_key_validity_window

        issued = parse_canonical_utc(document["issued_at"], label="issued_at")
        expires = parse_canonical_utc(document["expires_at"], label="expires_at")
    except (TypeError, ValueError, CanonicalUtcError) as exc:
        raise TraderBatchAuthorizationError(
            "trader authorization timestamps are invalid"
        ) from exc
    clock = now if now is not None else _now()
    if (
        issued.tzinfo is None
        or expires.tzinfo is None
        or expires < issued
        or expires - issued < timedelta(seconds=MIN_TTL_SECONDS)
        or expires - issued > timedelta(seconds=MAX_TTL_SECONDS)
        or clock > expires
    ):
        raise TraderBatchAuthorizationError("trader authorization is expired")
    signature = document.get("signature")
    key_id = str(document.get("key_id") or "")
    if type(signature) is not str or not signature.startswith("ed25519:"):
        raise TraderBatchAuthorizationError("trader authorization signature is invalid")
    body = {field: document[field] for field in _BODY_FIELDS}
    if keys is None:
        public_key = _load_active_key(environment, key_id)
        meta = _load_trader_key_meta(environment, key_id)
        try:
            require_key_validity_window(
                signed_at=issued,
                not_before=meta["not_before"],
                not_after=meta["not_after"],
                revoked_at=meta["revoked_at"],
                status=meta["status"],
                label="trader key",
            )
        except CanonicalUtcError as exc:
            raise TraderBatchAuthorizationError(str(exc)) from exc
    else:
        if len(keys) > 1:
            raise TraderBatchAuthorizationError(
                "trader authorization permits exactly one active key"
            )
        public_key = keys.get(key_id)
        if public_key is None:
            raise TraderBatchAuthorizationError("trader authorization issuer is untrusted")
    try:
        public_key.verify(
            base64.b64decode(signature[len("ed25519:") :], validate=True),
            _canonical_bytes(body),
        )
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise TraderBatchAuthorizationError(
            "trader authorization signature is invalid"
        ) from exc
    return _digest({**body, "signature": signature})


def verify_trader_authorization_batch_bytes(
    payload: bytes,
    **kwargs: Any,
) -> str:
    decoded = decode_strict_trader_json(payload)
    if type(decoded) is not dict:
        raise TraderBatchAuthorizationError("trader authorization must be an object")
    return verify_trader_authorization_batch(decoded, **kwargs)


__all__ = [
    "TRADER_BATCH_FORMAT",
    "TRADER_BATCH_ISSUER",
    "TraderBatchAuthorizationError",
    "decode_strict_trader_json",
    "trader_authority_instance_id",
    "verify_trader_authorization_batch",
    "verify_trader_authorization_batch_bytes",
]
