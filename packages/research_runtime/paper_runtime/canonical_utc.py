"""Strict canonical UTC timestamps. No Date.parse / fromisoformat permissiveness."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

_CANONICAL_UTC = re.compile(
    r"\A(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|\+00:00)\Z"
)


class CanonicalUtcError(ValueError):
    """Raised when a timestamp is not one canonical UTC instant."""


def parse_canonical_utc(value: Any, *, label: str = "timestamp") -> datetime:
    if type(value) is not str or not _CANONICAL_UTC.fullmatch(value):
        raise CanonicalUtcError(f"{label} is not a canonical UTC timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise CanonicalUtcError(f"{label} is not a canonical UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise CanonicalUtcError(f"{label} must be UTC")
    calendar = datetime(
        parsed.year,
        parsed.month,
        parsed.day,
        parsed.hour,
        parsed.minute,
        parsed.second,
        parsed.microsecond,
        tzinfo=timezone.utc,
    )
    if calendar != parsed.astimezone(timezone.utc):
        raise CanonicalUtcError(f"{label} is not a real UTC calendar instant")
    return parsed.astimezone(timezone.utc)


def require_key_validity_window(
    *,
    signed_at: datetime,
    not_before: Any,
    not_after: Any,
    revoked_at: Any,
    status: Any,
    label: str,
) -> None:
    start = parse_canonical_utc(not_before, label=f"{label}.not_before")
    end = parse_canonical_utc(not_after, label=f"{label}.not_after")
    if start > signed_at or signed_at > end:
        raise CanonicalUtcError(f"{label} is outside its not_before/not_after window")
    if status == "revoked":
        if revoked_at is None:
            raise CanonicalUtcError(f"{label} revoked key is missing revoked_at")
        revoked = parse_canonical_utc(revoked_at, label=f"{label}.revoked_at")
        if signed_at >= revoked:
            raise CanonicalUtcError(f"{label} was revoked at the signed instant")
        raise CanonicalUtcError(f"{label} status is not active")
    if status != "active":
        raise CanonicalUtcError(f"{label} status is not active")
    if revoked_at is not None:
        raise CanonicalUtcError(f"{label} active key must not set revoked_at")


__all__ = [
    "CanonicalUtcError",
    "parse_canonical_utc",
    "require_key_validity_window",
]
