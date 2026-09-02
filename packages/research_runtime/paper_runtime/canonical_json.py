"""One canonical JSON profile shared by Python Controlled Pilot digests.

Profile:
- UTF-8 bytes, not ASCII-escaped non-ASCII
- objects with lexicographic key order
- arrays in given order
- finite numbers only; integers stay integers
- strings as JSON strings (UTF-8, required escapes only)
- timestamps remain canonical UTC strings, never Date objects
- no NaN/Infinity, no extra whitespace
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class CanonicalJsonError(ValueError):
    """Raised when a value cannot be represented in the closed JSON profile."""


def canonical_json_dumps(value: Any) -> str:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalJsonError("value is not canonical JSON") from exc
    return text


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json_dumps(value).encode("utf-8")


def canonical_json_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


__all__ = [
    "CanonicalJsonError",
    "canonical_json_bytes",
    "canonical_json_digest",
    "canonical_json_dumps",
]
