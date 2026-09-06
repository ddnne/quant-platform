"""Canonical receipt-bound research product materialization.

The Receipt Evidence Authority signs the digest of the exact JSONL bytes it
writes to the governed structured plane.  Export, projection, and READY all
recompute those bytes from ``jquants_records`` through this module so a shadow
receipt table can never substitute for the product consumed by research.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable, Iterator, Mapping


PRODUCT_ARTIFACT_SCHEMA = "jquants_records/v1"
PRODUCT_ARTIFACT_FIELDS = (
    "source",
    "dataset",
    "natural_key",
    "event_time",
    "available_at",
    "ingested_at",
    "payload",
    "raw_payload",
)


def _canonical_product_row(raw: Mapping[str, Any] | Any) -> dict[str, str]:
    """Normalize one catalog row to the exact signed product field set."""

    if not isinstance(raw, Mapping):
        raise ValueError("product materialization row must be a mapping")
    missing = set(PRODUCT_ARTIFACT_FIELDS) - set(raw)
    if missing:
        raise ValueError(
            "product materialization row is missing fields: "
            + ",".join(sorted(missing))
        )
    row = {field: raw[field] for field in PRODUCT_ARTIFACT_FIELDS}
    if any(type(value) is not str for value in row.values()):
        raise ValueError("product materialization fields must be exact text")
    if row["source"] not in {"jquants", "jsda"} or not row["dataset"]:
        raise ValueError("product materialization source/dataset is invalid")
    return row  # type: ignore[return-value]


def _aware_instant(value: Any, *, label: str) -> datetime:
    """Parse a timezone-aware instant, preserving fractional seconds.

    Same strict ``fromisoformat`` + ``Z`` + tzinfo contract as governed
    collection clocks. Naive or malformed values raise; fractions are kept.
    """

    if type(value) is not str or not value:
        raise ValueError(f"{label} is malformed")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} is malformed") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} lacks timezone")
    return parsed


def iter_observed_segment_product_rows(
    conn: Any,
    *,
    source: str,
    dataset: str,
    segment_start: str,
    segment_end: str,
    observed_through: str,
) -> Iterator[dict[str, str]]:
    """Yield the complete signed catalog segment observed by the mirror.

    SQL scope is governed source/dataset/event-date identity only.
    Observation cutoff compares timezone-aware ingestion instants, so UTC
    millisecond authority clocks and JST mirror cutoffs are equivalent.
    Later revisions after the cutoff are excluded; stored timestamp strings
    are yielded unchanged.
    """

    if type(source) is not str or type(dataset) is not str or not source or not dataset:
        raise ValueError("product materialization source/dataset is invalid")
    start = str(segment_start)[:10]
    end = str(segment_end)[:10]
    if not start or not end:
        raise ValueError("product segment identity is invalid")
    cutoff = _aware_instant(
        observed_through, label="product observation cutoff"
    )
    fields = ",".join(PRODUCT_ARTIFACT_FIELDS)
    sql = (
        f"SELECT {fields} FROM jquants_records "
        "WHERE source=? AND dataset=? "
        "AND substr(event_time, 1, 10) BETWEEN ? AND ? "
        "ORDER BY source, dataset, natural_key"
    )
    for raw in conn.execute(sql, (source, dataset, start, end)):
        row = _canonical_product_row(
            {field: raw[field] for field in PRODUCT_ARTIFACT_FIELDS}
        )
        ingested = _aware_instant(
            row["ingested_at"], label="product ingestion clock"
        )
        if ingested > cutoff:
            continue
        yield row


def canonical_product_artifact_bytes(
    rows: Iterable[Mapping[str, Any]],
) -> bytes:
    """Render the exact authority JSONL representation, failing on coercion."""

    normalized: list[dict[str, str]] = []
    identities: set[tuple[str, str, str]] = set()
    for raw in rows:
        row = _canonical_product_row(raw)
        identity = (row["source"], row["dataset"], row["natural_key"])
        if identity in identities:
            raise ValueError("product materialization natural key is duplicated")
        identities.add(identity)
        normalized.append(row)
    if not normalized:
        raise ValueError("empty product materialization is not signable")
    normalized.sort(
        key=lambda row: tuple(
            row[field].encode("utf-8")
            for field in ("source", "dataset", "natural_key")
        )
    )
    return b"".join(
        json.dumps(
            row,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
        for row in normalized
    )


def product_artifact_digest(rows: Iterable[Mapping[str, Any]]) -> str:
    """Return the signed digest of the exact research product artifact."""

    body = canonical_product_artifact_bytes(rows)
    return "sha256:" + hashlib.sha256(body).hexdigest()


def product_artifact_digest_ordered(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[int, str, int]:
    """Hash already-ordered product rows without retaining them.

    ``rows`` must already be unique and ordered by
    ``(source, dataset, natural_key)``. Returns
    ``(row_count, sha256 digest, utf-8 byte count)``.
    """

    hasher = hashlib.sha256()
    count = 0
    nbytes = 0
    previous: tuple[str, str, str] | None = None
    for raw in rows:
        row = _canonical_product_row(raw)
        identity = (row["source"], row["dataset"], row["natural_key"])
        binary_identity = tuple(value.encode("utf-8") for value in identity)
        binary_previous = (
            None
            if previous is None
            else tuple(value.encode("utf-8") for value in previous)
        )
        if binary_previous is not None and binary_identity <= binary_previous:
            raise ValueError(
                "product materialization rows must be unique and ordered"
            )
        previous = identity
        encoded = (
            json.dumps(
                row,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        hasher.update(encoded)
        count += 1
        nbytes += len(encoded)
    if count == 0:
        raise ValueError("empty product materialization is not signable")
    return count, "sha256:" + hasher.hexdigest(), nbytes


def product_artifact_body_digest(body: Any) -> str:
    """Rehash the exported UTF-8 copy of the authority's R2 readback bytes."""

    if type(body) is not str or not body:
        raise ValueError("product materialization artifact body must be exact text")
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


__all__ = [
    "PRODUCT_ARTIFACT_FIELDS",
    "PRODUCT_ARTIFACT_SCHEMA",
    "canonical_product_artifact_bytes",
    "iter_observed_segment_product_rows",
    "product_artifact_body_digest",
    "product_artifact_digest",
    "product_artifact_digest_ordered",
]
