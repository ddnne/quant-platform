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
from typing import Any, Iterable, Iterator, Mapping, Sequence


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


def _encode_product_row(row: Mapping[str, str]) -> bytes:
    """Render one canonical JSONL line, including the trailing newline."""

    return (
        json.dumps(
            dict(row),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _iter_binary_jsonl_lines(source: Any) -> Iterator[bytes]:
    """Yield raw JSONL line bytes, including the terminating newline.

    Accepts in-memory ``str``/``bytes`` or a binary ``readline`` stream.
    Text-mode streams are rejected so CRLF decoding cannot rewrite signed bytes.
    """

    if type(source) is str or type(source) is bytes:
        newline: str | bytes = "\n" if type(source) is str else b"\n"
        if not source or not source.endswith(newline):
            raise ValueError("product materialization artifact body must be JSONL")
        start = 0
        length = len(source)
        while start < length:
            end = source.find(newline, start)
            line = source[start : end + 1]
            if line == newline:
                raise ValueError(
                    "product materialization artifact body is not JSONL"
                )
            yield line.encode("utf-8") if type(source) is str else line
            start = end + 1
        return
    readline = getattr(source, "readline", None)
    if not callable(readline):
        raise ValueError(
            "product materialization artifact body must be JSONL text, bytes, "
            "or a binary line stream"
        )
    while True:
        line = readline()
        if line == b"":
            break
        if type(line) is not bytes:
            raise ValueError("product artifact stream must be binary")
        if not line.endswith(b"\n") or line == b"\n":
            raise ValueError("product materialization artifact body is not JSONL")
        yield line


def _iter_canonical_artifact_rows(
    source: Any,
) -> Iterator[tuple[bytes, dict[str, str]]]:
    """Parse one JSONL artifact without retaining prior rows.

    Each raw line must already be the canonical UTF-8 JSONL encoding.
    """

    previous: tuple[str, str, str] | None = None
    for raw_line in _iter_binary_jsonl_lines(source):
        try:
            parsed = json.loads(raw_line[:-1].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "product materialization artifact body is not JSONL"
            ) from exc
        row = _canonical_product_row(parsed)
        if _encode_product_row(row) != raw_line:
            raise ValueError(
                "product materialization artifact body is not canonical JSONL"
            )
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
        yield raw_line, row


def measure_product_artifact_jsonl(source: Any) -> tuple[int, str, int]:
    """Hash one JSONL artifact from real bytes without retaining rows.

    Returns ``(row_count, sha256 digest, utf-8 byte count)`` derived from the
    stream itself. Caller-supplied digest/count values are not inputs.
    """

    hasher = hashlib.sha256()
    count = 0
    nbytes = 0
    for raw_line, _row in _iter_canonical_artifact_rows(source):
        hasher.update(raw_line)
        count += 1
        nbytes += len(raw_line)
    if count == 0:
        raise ValueError("empty product materialization is not signable")
    return count, "sha256:" + hasher.hexdigest(), nbytes


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
        _encode_product_row(row) for row in normalized
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
        encoded = _encode_product_row(row)
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
    return measure_product_artifact_jsonl(body)[1]


def iter_product_artifact_body_rows(body: Any) -> Iterator[dict[str, str]]:
    """Yield canonical product rows from one signed JSONL artifact body.

    Accepts exact UTF-8 text, bytes, or a binary readline stream already
    understood by ``_iter_canonical_artifact_rows``. Catalog reconstruction
    still does not substitute for this generation body.
    """

    if type(body) is str or type(body) is bytes:
        if not body:
            raise ValueError("empty product materialization is not signable")
        source = body
    else:
        readline = getattr(body, "readline", None)
        if not callable(readline):
            raise ValueError(
                "product materialization artifact body must be exact text"
            )
        source = body
    yielded = False
    for _raw_line, row in _iter_canonical_artifact_rows(source):
        yielded = True
        yield row
    if not yielded:
        raise ValueError("empty product materialization is not signable")


def product_row_digest(raw: Mapping[str, Any] | Any) -> str:
    """Digest one canonical product row with the signed JSONL profile."""

    row = _canonical_product_row(raw)
    return "sha256:" + hashlib.sha256(_encode_product_row(row)).hexdigest()


_CATALOG_OWNERSHIP_TABLES = frozenset(
    {"jquants_records", "jquants_records_revisions"}
)


def catalog_owned_product_row_digests(
    conn: Any,
    *,
    source: str,
    dataset: str,
    segment_start: str,
    segment_end: str,
    observed_through: str,
    tables: Sequence[str],
) -> set[str]:
    """Digest CURRENT and REVISION catalog versions owned in ``tables``.

    This is catalog ownership of signed product fields. It is not
    current-only reconstruction and does not mint a receipt. Callers must
    pass concrete tables; missing tables fail at execute time.
    """

    if type(source) is not str or type(dataset) is not str or not source or not dataset:
        raise ValueError("product materialization source/dataset is invalid")
    if not tables:
        raise ValueError("catalog ownership tables are missing")
    start = str(segment_start)[:10]
    end = str(segment_end)[:10]
    if not start or not end:
        raise ValueError("product segment identity is invalid")
    cutoff = _aware_instant(
        observed_through, label="product observation cutoff"
    )
    fields = ",".join(PRODUCT_ARTIFACT_FIELDS)
    digests: set[str] = set()
    for table in tables:
        if type(table) is not str or table not in _CATALOG_OWNERSHIP_TABLES:
            raise ValueError("catalog ownership table is invalid")
        sql = (
            f"SELECT {fields} FROM {table} "
            "WHERE source=? AND dataset=? "
            "AND substr(event_time, 1, 10) BETWEEN ? AND ?"
        )
        for raw in conn.execute(sql, (source, dataset, start, end)):
            try:
                row = {field: raw[field] for field in PRODUCT_ARTIFACT_FIELDS}
                ingested = _aware_instant(
                    row["ingested_at"], label="product ingestion clock"
                )
            except (KeyError, TypeError, ValueError):
                continue
            if ingested > cutoff:
                continue
            try:
                digests.add(product_row_digest(row))
            except ValueError:
                continue
    return digests


def measure_owned_product_artifact_body(
    body: Any,
    *,
    owned_digests: set[str],
) -> tuple[int, str, int, frozenset[str]]:
    """Hash one immutable artifact and require every row is catalog-owned."""

    row_digests: set[str] = set()

    def rows() -> Iterator[dict[str, str]]:
        for raw in iter_product_artifact_body_rows(body):
            digest = product_row_digest(raw)
            if digest not in owned_digests:
                raise ValueError(
                    "verified artifact row is not materialized on the "
                    "owner connection"
                )
            row_digests.add(digest)
            yield raw

    observed_count, observed_digest, observed_bytes = (
        product_artifact_digest_ordered(rows())
    )
    return observed_count, observed_digest, observed_bytes, frozenset(row_digests)


def _mapping_field(raw: Mapping[str, Any] | Any, name: str) -> Any:
    if not isinstance(raw, Mapping):
        raise ValueError(f"full-segment {name} evidence must be a mapping")
    try:
        return raw[name]
    except KeyError as exc:
        raise ValueError(f"full-segment evidence is missing {name}") from exc


def verify_full_segment_product_materialization(
    closure: Any,
    *,
    product: Mapping[str, Any] | Any,
    run: Mapping[str, Any] | Any,
    raw_manifest: Mapping[str, Any] | Any,
    observed_count: int,
    observed_digest: str,
    observed_bytes: int,
    artifact: Any = None,
) -> None:
    """Close one full source segment against a verifier-minted receipt.

    ``observed_*`` is independently obtained by the caller: current
    ``jquants_records`` reconstruction for READY/export, exact-generation
    ownership for complete-master. Artifact count/digest/bytes are derived
    here from real JSONL bytes. Current-only SQL is not revision proof.
    """

    from storage.verified_receipt import VerifiedCollectionClosure

    if type(closure) is not VerifiedCollectionClosure:
        raise TypeError("full-segment product requires VerifiedCollectionClosure")
    if type(observed_count) is not int or observed_count < 1:
        raise ValueError("observed full-segment row count is invalid")
    if type(observed_digest) is not str or not observed_digest:
        raise ValueError("observed full-segment digest is invalid")
    if type(observed_bytes) is not int or observed_bytes < 1:
        raise ValueError("observed full-segment byte count is invalid")
    if not isinstance(product, Mapping):
        raise ValueError("receipt product materialization is missing")
    if not isinstance(run, Mapping):
        raise ValueError("authority-bound ingestion run is missing")
    if not isinstance(raw_manifest, Mapping):
        raise ValueError("raw retention manifest is missing")

    artifact_source = (
        artifact if artifact is not None else _mapping_field(product, "artifact_body")
    )
    try:
        artifact_count, artifact_digest, artifact_bytes = (
            measure_product_artifact_jsonl(artifact_source)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "full-segment product materialization does not close the signed receipt"
        ) from exc
    if (
        closure.status != "SUCCESS"
        or not closure.pagination_exhausted
        or not closure.discovery_exhausted
        or (artifact_count, artifact_digest, artifact_bytes)
        != (observed_count, observed_digest, observed_bytes)
        or artifact_digest != closure.structured_digest
        or artifact_count != closure.structured_row_count
        or artifact_digest != _mapping_field(product, "artifact_digest")
        or artifact_count != _mapping_field(product, "row_count")
        or artifact_bytes != _mapping_field(product, "byte_count")
        or _mapping_field(product, "raw_manifest_digest")
        != closure.raw_manifest_digest
        or _mapping_field(product, "raw_page_count") != closure.raw_page_count
        or _mapping_field(product, "raw_row_count") != closure.raw_row_count
        or _mapping_field(run, "id") != closure.run_id
        or _mapping_field(run, "source") != closure.source
        or _mapping_field(run, "runtime") != "receipt-evidence-authority"
        or _mapping_field(run, "status") != "SUCCESS"
        or _mapping_field(run, "authority_operation_id")
        != _mapping_field(product, "operation_id")
        or _mapping_field(raw_manifest, "manifest_key")
        != _mapping_field(product, "raw_manifest_key")
        or _mapping_field(raw_manifest, "page_count") != closure.raw_page_count
        or _mapping_field(raw_manifest, "row_count") != closure.raw_row_count
        or _mapping_field(raw_manifest, "raw_bytes")
        != _mapping_field(product, "raw_bytes")
        or _mapping_field(raw_manifest, "data_digest")
        != closure.raw_manifest_digest
    ):
        raise ValueError(
            "full-segment product materialization does not close the signed receipt"
        )


__all__ = [
    "PRODUCT_ARTIFACT_FIELDS",
    "PRODUCT_ARTIFACT_SCHEMA",
    "canonical_product_artifact_bytes",
    "catalog_owned_product_row_digests",
    "iter_observed_segment_product_rows",
    "iter_product_artifact_body_rows",
    "measure_owned_product_artifact_body",
    "measure_product_artifact_jsonl",
    "product_artifact_body_digest",
    "product_artifact_digest",
    "product_artifact_digest_ordered",
    "product_row_digest",
    "verify_full_segment_product_materialization",
]
