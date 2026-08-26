"""Canonical JSON, primitive validators, errors, and trusted UTC clock."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from selection.budget_ledger import MassResearchDisabledError


PLAN_EXECUTION_BINDING_FORMAT = "plan-execution-binding/v1"
EXACT_FOUR_BINDING_FORMAT = "exact-four-execution-binding/v1"
PILOT_READINESS_CLAIMS_FORMAT = "pilot-readiness-attestation-claims/v2"
TRADER_AUTHORIZATION_CLAIMS_FORMAT = "exact-four-trader-authorization-claims/v2"
CONTROLLED_EXECUTION_CLAIMS_FORMAT = "exact-four-execution-request-claims/v2"

PILOT_READINESS_SCOPE = "VERIFIED_PILOT_READINESS"
TRADER_AUTHORIZATION_SCOPE = "EXACT_FOUR_TRADER_AUTHORIZATION"
CONTROLLED_EXECUTION_SCOPE = "EXACT_FOUR_CONTROLLED_PAPER_EXECUTION"
PILOT_EXECUTION_MODE = "paper"
AUTHORITY_PROTOCOL_STATE = "PENDING_EXTERNAL_AUTHORITIES"

_CURRENT_CLOCK_SKEW = timedelta(seconds=30)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_UNAVAILABLE_CURRENT_VALUES = frozenset(
    {
        "n/a",
        "na",
        "none",
        "not-declared",
        "not_declared",
        "null",
        "pending",
        "stale",
        "unknown",
        "unset",
    }
)


class ExactFourAuthorityContractError(MassResearchDisabledError):
    """Raised when immutable exact-four authority claims are not canonical."""


class ExactFourAuthorityPending(ExactFourAuthorityContractError):
    """Raised because no v2 publication/approval/execution principal exists."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ExactFourAuthorityContractError(
                f"authority contract contains duplicate JSON key: {key}"
            )
        document[key] = value
    return document


def _reject_nonfinite(value: str) -> Any:
    raise ExactFourAuthorityContractError(
        f"authority contract contains non-finite JSON number: {value}"
    )


def _require_exact_json(value: Any, *, path: str = "$") -> None:
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ExactFourAuthorityContractError(
                    f"{path}: JSON object keys must be exact strings"
                )
            _require_exact_json(item, path=f"{path}.{key}")
        return
    if type(value) is list:
        for ordinal, item in enumerate(value):
            _require_exact_json(item, path=f"{path}[{ordinal}]")
        return
    if type(value) not in {str, int, bool, type(None)}:
        raise ExactFourAuthorityContractError(
            f"{path}: value must be an exact JSON built-in"
        )


def _strict_json_loads(raw: bytes | str, *, label: str) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8") if type(raw) is bytes else raw
        if type(text) is not str:
            raise TypeError("raw authority document must be bytes or str")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExactFourAuthorityContractError(f"cannot decode {label}") from exc
    if type(value) is not dict:
        raise ExactFourAuthorityContractError(f"{label} must be one JSON object")
    _require_exact_json(value)
    return value


def _canonical_bytes(value: Any) -> bytes:
    _require_exact_json(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExactFourAuthorityContractError(
            "authority contract value is not canonical JSON"
        ) from exc


def canonical_authority_digest(value: Any) -> str:
    """Return the common content address used by every v2 protocol body."""

    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_text(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ExactFourAuthorityContractError(
            f"{label} must be an exact non-empty string"
        )
    return value


def _require_digest(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if _SHA256_RE.fullmatch(text) is None:
        raise ExactFourAuthorityContractError(
            f"{label} must be a canonical sha256 digest"
        )
    return text


def _require_timestamp(value: Any, label: str) -> str:
    text = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExactFourAuthorityContractError(
            f"{label} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExactFourAuthorityContractError(f"{label} must include a timezone")
    return text


def _parsed_timestamp(value: Any, label: str) -> datetime:
    text = _require_timestamp(value, label)
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _require_bounded_window(
    issued_at: Any,
    expires_at: Any,
    *,
    ttl_seconds: Any,
    label: str,
) -> tuple[datetime, datetime]:
    if type(ttl_seconds) is not int or ttl_seconds < 1:
        raise ExactFourAuthorityContractError(f"{label} TTL must be a positive integer")
    issued = _parsed_timestamp(issued_at, f"{label} issued_at")
    expires = _parsed_timestamp(expires_at, f"{label} expires_at")
    lifetime = (expires - issued).total_seconds()
    if lifetime <= 0:
        raise ExactFourAuthorityContractError(f"{label} expiry must be after issuance")
    if lifetime > ttl_seconds:
        raise ExactFourAuthorityContractError(
            f"{label} lifetime exceeds the controlled-pilot policy TTL"
        )
    return issued, expires


def _trusted_utc_now() -> datetime:
    """Read the module-owned system clock used by public current validators."""

    return datetime.now(timezone.utc)


def _require_current_window(
    issued_at: Any,
    expires_at: Any,
    *,
    label: str,
    now: datetime,
) -> None:
    issued = _parsed_timestamp(issued_at, f"{label} issued_at")
    expires = _parsed_timestamp(expires_at, f"{label} expires_at")
    current = now.astimezone(timezone.utc)
    if issued > current + _CURRENT_CLOCK_SKEW:
        raise ExactFourAuthorityContractError(
            f"{label} is not yet valid at the trusted UTC clock"
        )
    if expires <= current:
        raise ExactFourAuthorityContractError(
            f"{label} is expired at the trusted UTC clock"
        )


def _require_current_token(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if text.casefold() in _UNAVAILABLE_CURRENT_VALUES:
        raise ExactFourAuthorityContractError(
            f"{label} must identify a current non-sentinel value"
        )
    return text


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ExactFourAuthorityContractError(
            f"{label} must be an exact positive integer"
        )
    return value


def _require_date(value: Any, label: str) -> str:
    text = _require_text(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ExactFourAuthorityContractError(
            f"{label} must be an ISO date (YYYY-MM-DD)"
        ) from exc
    if parsed.isoformat() != text:
        raise ExactFourAuthorityContractError(
            f"{label} must be an ISO date (YYYY-MM-DD)"
        )
    return text


__all__ = [
    "AUTHORITY_PROTOCOL_STATE",
    "CONTROLLED_EXECUTION_CLAIMS_FORMAT",
    "CONTROLLED_EXECUTION_SCOPE",
    "EXACT_FOUR_BINDING_FORMAT",
    "ExactFourAuthorityContractError",
    "ExactFourAuthorityPending",
    "PILOT_EXECUTION_MODE",
    "PILOT_READINESS_CLAIMS_FORMAT",
    "PILOT_READINESS_SCOPE",
    "PLAN_EXECUTION_BINDING_FORMAT",
    "TRADER_AUTHORIZATION_CLAIMS_FORMAT",
    "TRADER_AUTHORIZATION_SCOPE",
    "canonical_authority_digest",
]
