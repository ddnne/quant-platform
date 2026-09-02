"""PENDING capability types and digest-pinned protocol schema loaders."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, NoReturn

from execution.exact_four_codec import (
    AUTHORITY_PROTOCOL_STATE,
    ExactFourAuthorityContractError,
    ExactFourAuthorityPending,
    _strict_json_loads,
    canonical_authority_digest,
)
from qp_paths import repo_root
from selection.controlled_pilot_policy import CONTROLLED_PILOT_POLICY_SCHEMA_URI


EXACT_FOUR_AUTHORITY_SCHEMA_REL = (
    Path("specs") / "ready" / "exact_four_authority_protocol.schema.json"
)
PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST = (
    "sha256:144081ec55221cf867fb3ca0087fbc35356e071cb143ba3b9c446993604492d4"
)
PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST = (
    "sha256:f5573a9c2ac4c3f37fa745bf765541b4405bef12df0bb5fb7d87554c02146f50"
)
EXACT_FOUR_RESULT_SCHEMA_REL = (
    Path("specs") / "ready" / "exact_four_result_manifest.schema.json"
)
PINNED_EXACT_FOUR_RESULT_SCHEMA_DIGEST = (
    "sha256:af3518e0d482bc732df3e8bf432146da90e9fbfd4233bec2967a4b9f4166b217"
)
PINNED_EXACT_FOUR_RESULT_SCHEMA_RAW_DIGEST = (
    "sha256:9162c820c168b1efef8ef59fb60e79fb632a47792afeaa858fc90880aac23e49"
)


class _PendingCapability:
    __slots__ = ()

    def __new__(cls, *args: Any, **kwargs: Any) -> NoReturn:
        del args, kwargs
        raise ExactFourAuthorityPending(
            f"{cls.__name__} is unavailable: {AUTHORITY_PROTOCOL_STATE}"
        )


class VerifiedPilotReadinessV2(_PendingCapability):
    """Opaque future output of the isolated READY verifier."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("VerifiedPilotReadinessV2 is final")


class VerifiedExactFourTraderAuthorizationV2(_PendingCapability):
    """Opaque future output of the isolated human Trader verifier."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("VerifiedExactFourTraderAuthorizationV2 is final")


class AuthorizedExactFourExecutionV2(_PendingCapability):
    """Opaque future output of the controlled one-shot execution writer."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("AuthorizedExactFourExecutionV2 is final")


def authority_schema_path() -> Path:
    return repo_root() / EXACT_FOUR_AUTHORITY_SCHEMA_REL


def load_exact_four_authority_schema() -> dict[str, Any]:
    try:
        raw = authority_schema_path().read_bytes()
        value = _strict_json_loads(raw, label="exact-four authority protocol schema")
    except (OSError, ExactFourAuthorityContractError) as exc:
        raise ExactFourAuthorityContractError(
            "cannot load exact-four authority protocol schema"
        ) from exc
    raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if raw_digest != PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST:
        raise ExactFourAuthorityContractError(
            "pinned exact-four authority protocol schema raw digest mismatch"
        )
    if type(value) is not dict:
        raise ExactFourAuthorityContractError(
            "exact-four authority protocol schema must be an object"
        )
    if set(value) != {"$schema", "$id", "title", "oneOf", "$defs"} or (
        value.get("$schema") != CONTROLLED_PILOT_POLICY_SCHEMA_URI
        or value.get("$id")
        != "https://quant-platform.local/specs/ready/"
        "exact_four_authority_protocol.schema.json"
        or value.get("title")
        != "Exact-four controlled-pilot v2 authority protocol"
    ):
        raise ExactFourAuthorityContractError(
            "exact-four authority protocol schema identity is not closed"
        )
    if canonical_authority_digest(value) != PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST:
        raise ExactFourAuthorityContractError(
            "pinned exact-four authority protocol schema digest mismatch"
        )
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise ExactFourAuthorityContractError(
            "exact-four authority protocol schema is invalid"
        ) from exc
    return value


def exact_four_result_schema_path() -> Path:
    return repo_root() / EXACT_FOUR_RESULT_SCHEMA_REL


def load_exact_four_result_schema() -> dict[str, Any]:
    path = exact_four_result_schema_path()
    try:
        raw = path.read_bytes()
        value = _strict_json_loads(raw, label="exact-four result manifest schema")
    except (OSError, ExactFourAuthorityContractError) as exc:
        raise ExactFourAuthorityContractError(
            "cannot load exact-four result manifest schema"
        ) from exc
    raw_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if raw_digest != PINNED_EXACT_FOUR_RESULT_SCHEMA_RAW_DIGEST:
        raise ExactFourAuthorityContractError(
            "pinned exact-four result manifest schema raw digest mismatch"
        )
    if (
        type(value) is not dict
        or value.get("$schema") != CONTROLLED_PILOT_POLICY_SCHEMA_URI
        or value.get("$id")
        != "https://quant-platform.local/specs/ready/"
        "exact_four_result_manifest.schema.json"
        or value.get("title")
        != "Exact-four controlled-pilot v2 result manifest"
        or canonical_authority_digest(value)
        != PINNED_EXACT_FOUR_RESULT_SCHEMA_DIGEST
    ):
        raise ExactFourAuthorityContractError(
            "pinned exact-four result manifest schema identity or digest mismatch"
        )
    try:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(value)
    except Exception as exc:
        raise ExactFourAuthorityContractError(
            "exact-four result manifest schema is invalid"
        ) from exc
    return value


def require_verified_pilot_readiness_v2(value: Any) -> VerifiedPilotReadinessV2:
    """Nominal gate: claims/booleans/Trader tokens can never substitute READY."""
    del value
    raise ExactFourAuthorityPending("isolated v2 READY verification is not active")


def require_verified_trader_authorization_v2(
    value: Any,
) -> VerifiedExactFourTraderAuthorizationV2:
    """Nominal gate: READY or execution claims cannot authorize a Trader."""
    del value
    raise ExactFourAuthorityPending(
        "isolated v2 human Trader authorization is not active"
    )


def require_authorized_exact_four_execution_v2(
    value: Any,
) -> AuthorizedExactFourExecutionV2:
    """Nominal gate: only the future one-shot writer can return this type."""
    del value
    raise ExactFourAuthorityPending(
        "isolated v2 controlled execution writer is not active"
    )

__all__ = [
    "AuthorizedExactFourExecutionV2",
    "PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_DIGEST",
    "PINNED_EXACT_FOUR_AUTHORITY_SCHEMA_RAW_DIGEST",
    "PINNED_EXACT_FOUR_RESULT_SCHEMA_DIGEST",
    "PINNED_EXACT_FOUR_RESULT_SCHEMA_RAW_DIGEST",
    "VerifiedExactFourTraderAuthorizationV2",
    "VerifiedPilotReadinessV2",
    "authority_schema_path",
    "exact_four_result_schema_path",
    "load_exact_four_authority_schema",
    "load_exact_four_result_schema",
    "require_authorized_exact_four_execution_v2",
    "require_verified_pilot_readiness_v2",
    "require_verified_trader_authorization_v2",
]
