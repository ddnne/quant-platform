"""Bounded reader for existing R2 bars, not API pagination or Receipt proof.

The caller reads one bounded object at a time and consumes its iterator within
a scratch transaction. A malformed later row must roll back that transaction.
Stored vintage clocks are preserved; this reader never invents publication time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import io
import json
import re
from typing import Any, Iterator

from data_contracts.identity import natural_key, natural_key_fields
from ingestion.personal_history import PersonalHistoryError


@dataclass(frozen=True)
class StructuredBarsObject:
    key: str
    sha256: str
    size: int
    rows: int


STRUCTURED_MANIFEST_MAX_BYTES = 1024 * 1024


def decode_structured_bar_manifest(body: bytes, digest: str) -> dict[str, tuple[StructuredBarsObject, ...]]:
    """Resolve a pinned monthly input list, not a Coverage or Receipt proof."""
    if not 0 < len(body) <= STRUCTURED_MANIFEST_MAX_BYTES or hashlib.sha256(body).hexdigest() != digest:
        raise PersonalHistoryError("stored bars manifest size/digest rejected")
    try:
        document = json.loads(body)
        if set(document) not in ({"schema", "months"}, {"schema", "objects"}) or document["schema"] != "personal-stored-bars/v1":
            raise ValueError("schema")
        # Flat metadata lists are indexed by actual row dates in the cloud.
        # The internal '*' entry is never treated as a coverage claim.
        unindexed = "objects" in document
        months = {"*": document["objects"]} if unindexed else document["months"]
        if not isinstance(months, dict) or not months:
            raise ValueError("months")
        result = {}
        for month, objects in months.items():
            if (not unindexed and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month)) or not isinstance(objects, list) or not objects:
                raise ValueError("month")
            sources = []
            for item in objects:
                if set(item) != {"key", "sha256", "bytes", "rows"}:
                    raise ValueError("object fields")
                if (
                    not isinstance(item["key"], str)
                    or not re.fullmatch(r"structured/jsonl/equities_bars_daily/[A-Za-z0-9/_.=-]+\.jsonl", item["key"])
                    or not isinstance(item["sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                    or any(type(item[field]) is not int or item[field] <= 0 for field in ("bytes", "rows"))
                ):
                    raise ValueError("object descriptor")
                sources.append(StructuredBarsObject(item["key"], item["sha256"], item["bytes"], item["rows"]))
            if len({source.key for source in sources}) != len(sources):
                raise ValueError("duplicate object")
            result[month] = tuple(sources)
        return result
    except (ValueError, TypeError, KeyError) as exc:
        raise PersonalHistoryError("invalid stored bars manifest") from exc


def _clock(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise PersonalHistoryError(f"structured bars missing {name}")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise PersonalHistoryError(f"structured bars invalid {name}") from exc
    if parsed.tzinfo is None:
        raise PersonalHistoryError(f"structured bars unzoned {name}")
    return parsed


def _reject_nonfinite(value: str) -> None:
    raise PersonalHistoryError(f"structured bars nonfinite JSON number: {value}")


def iter_verified_structured_bars(
    body: bytes,
    source: StructuredBarsObject,
    *,
    max_object_bytes: int,
) -> Iterator[dict[str, Any]]:
    """Yield original envelopes from one hash-checked, size-bounded R2 object.

No filtering by the key's dt partition: it names only the FIRST row's date.
No latest-row collapse: the scratch consumer must retain distinct vintages.
"""
    if not source.key.startswith("structured/jsonl/equities_bars_daily/"):
        raise PersonalHistoryError("structured bars source key is outside bars")
    if type(source.size) is not int or type(source.rows) is not int:
        raise PersonalHistoryError("structured bars invalid object counts")
    if (
        type(max_object_bytes) is not int
        or max_object_bytes <= 0
        or source.rows <= 0
        or not 0 < source.size <= max_object_bytes
        or len(body) != source.size
    ):
        raise PersonalHistoryError("structured bars object size/count rejected")
    if hashlib.sha256(body).hexdigest() != source.sha256:
        raise PersonalHistoryError("structured bars object digest mismatch")
    # Count without decoding or materializing all lines. Validate before yielding.
    if sum(bool(line.strip()) for line in io.BytesIO(body)) != source.rows:
        raise PersonalHistoryError("structured bars object row count mismatch")
    for line in io.BytesIO(body):
        if not line.strip():
            continue
        try:
            row = json.loads(line, parse_constant=_reject_nonfinite)
        except (ValueError, UnicodeDecodeError) as exc:
            raise PersonalHistoryError("structured bars malformed JSONL") from exc
        if not isinstance(row, dict) or row.get("dataset") != "equities_bars_daily":
            raise PersonalHistoryError("structured bars dataset mismatch")
        payload = row.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload, parse_constant=_reject_nonfinite)
            except (ValueError, UnicodeDecodeError) as exc:
                raise PersonalHistoryError("structured bars malformed payload") from exc
        if not isinstance(payload, dict) or not payload.get("Code"):
            raise PersonalHistoryError("structured bars missing code/payload")
        event = _clock(row.get("event_time"), "event_time")
        available = _clock(row.get("available_at"), "available_at")
        observed = _clock(row.get("ingested_at"), "ingested_at")
        if payload.get("Date") != event.date().isoformat():
            raise PersonalHistoryError("structured bars event/payload date mismatch")
        if observed < available or available < event:
            raise PersonalHistoryError("structured bars vintage clocks are inconsistent")
        try:
            key = row.get("natural_key")
            if isinstance(key, str):
                key = json.loads(key, parse_constant=_reject_nonfinite)
            expected_key = natural_key_fields(payload, "equities_bars_daily")
            # Normal bar keys are strings: comparing their selected fields is
            # identical to a canonical JSON round trip, without serializing
            # every row. Preserve historical normalization for other types.
            if not all(isinstance(value, str) for value in expected_key.values()):
                expected_key = json.loads(natural_key(payload, "equities_bars_daily"))
        except (ValueError, TypeError) as exc:
            raise PersonalHistoryError("structured bars invalid natural key") from exc
        if key != expected_key:
            raise PersonalHistoryError("structured bars natural key/payload mismatch")
        # Keep the original envelope (including its payload representation).
        # The existing compact normalizer owns field aliases and numeric checks.
        yield row
