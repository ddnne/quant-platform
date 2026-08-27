"""Canonical receipt-bound research product materialization.

The Receipt Evidence Authority signs the digest of the exact JSONL bytes it
writes to the governed structured plane.  Export, projection, and READY all
recompute those bytes from ``jquants_records`` through this module so a shadow
receipt table can never substitute for the product consumed by research.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping


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


def canonical_product_artifact_bytes(
    rows: Iterable[Mapping[str, Any]],
) -> bytes:
    """Render the exact authority JSONL representation, failing on coercion."""

    normalized: list[dict[str, str]] = []
    identities: set[tuple[str, str, str]] = set()
    for raw in rows:
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
        if row["source"] != "jquants" or not row["dataset"]:
            raise ValueError("product materialization source/dataset is invalid")
        identity = (row["source"], row["dataset"], row["natural_key"])
        if identity in identities:
            raise ValueError("product materialization natural key is duplicated")
        identities.add(identity)
        normalized.append(row)  # type: ignore[arg-type]
    if not normalized:
        raise ValueError("empty product materialization is not signable")
    normalized.sort(
        key=lambda row: (row["source"], row["dataset"], row["natural_key"])
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


def product_artifact_body_digest(body: Any) -> str:
    """Rehash the exported UTF-8 copy of the authority's R2 readback bytes."""

    if type(body) is not str or not body:
        raise ValueError("product materialization artifact body must be exact text")
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


__all__ = [
    "PRODUCT_ARTIFACT_FIELDS",
    "PRODUCT_ARTIFACT_SCHEMA",
    "canonical_product_artifact_bytes",
    "product_artifact_body_digest",
    "product_artifact_digest",
]
