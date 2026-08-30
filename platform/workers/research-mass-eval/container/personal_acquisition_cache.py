"""Deterministic personal DRAFT month acquisition cache (one dataset, one month).

This is a research optimization over ephemeral AcquisitionSpool.  The immutable
R2 checksum binds the trusted first-writer shard; this DRAFT cache does not
re-prove raw body_digest or claim Receipt/READY.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse
import urllib.request

from data_contracts.identity import canonical_json
from ingestion.personal_history import PERSONAL_HISTORY_DATASETS, PersonalHistoryError

CACHE_FORMAT = "personal-draft-acquisition-cache/v1"
CACHE_SCHEMA_EPOCH = 1
CACHE_R2_ORIGIN = "http://research.r2"
CACHE_PLANE = "personal_acquisition_cache"
CACHE_USER_AGENT = "quant-personal-history/v13"
CACHE_GZIP_MAX_BYTES = 536_870_912
CACHE_SQLITE_MAX_BYTES = 1_073_741_824
CACHE_MAX_PAGES = 8192
CACHE_MAX_ROWS_PER_PAGE = 250_000
CACHE_MAX_ROWS_TOTAL = 1_000_000
CACHE_GET_TIMEOUT_S = 15
CACHE_PUT_TIMEOUT_S = 60
_DIGEST_RE = __import__("re").compile(r"^sha256:[0-9a-f]{64}$")
_HEX64_RE = __import__("re").compile(r"^[0-9a-f]{64}$")
_MONTH_RE = __import__("re").compile(r"^(\d{4})-(\d{2})$")
_DATE_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_ENVIRONMENTS = frozenset({"production", "staging"})
_ALLOWED_DATASETS = frozenset(PERSONAL_HISTORY_DATASETS)
_FORBIDDEN_HEADER_OR_META = (
    "authorization",
    "cookie",
    "set-cookie",
    "proxy-authorization",
    "api_key",
    "api-key",
    "x-api-key",
    "jquants_api_key",
    "password",
    "secret",
    "token",
    "credential",
    "credentials",
    "raw_headers",
    "request_headers",
    "raw-request-headers",
)
CACHE_GET_FIXED_HEADERS = {
    "accept": "application/gzip",
    "accept-encoding": "identity",
    "connection": "close",
    "user-agent": CACHE_USER_AGENT,
}
CACHE_PUT_FIXED_HEADERS = {
    **CACHE_GET_FIXED_HEADERS,
    "content-type": "application/gzip",
}
_PAGE_COLUMNS = (
    "dataset",
    "month",
    "page_ordinal",
    "slice_date",
    "body_digest",
    "row_count",
    "request_path",
    "request_params_json",
    "response_status",
    "pagination_in",
    "pagination_out",
    "evidence_state",
)
_ROW_COLUMNS = (
    "dataset",
    "month",
    "page_ordinal",
    "row_index",
    "code",
    "row_date",
    "row_json",
)
_SHARD_TABLES = ("cache_identity", "month_state", "source_pages", "source_rows")


class AcquisitionCacheMiss(Exception):
    """No object at the canonical key; live acquisition is required."""


class AcquisitionCacheUnavailable(Exception):
    """Bounded cache transport failed; live acquisition may continue."""


class AcquisitionCacheInvalid(PersonalHistoryError):
    """Present cache is corrupt, tampered, or the wrong identity."""


class AcquisitionCacheConflict(PersonalHistoryError):
    """Same cache key already holds different immutable content."""


def _canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def month_completion_digest(pages: Sequence[Any]) -> str:
    return _canonical_digest(
        {
            "page_count": len(pages),
            "status": "COMPLETE",
            "pages": [
                {
                    "ordinal": index,
                    "body_digest": page.body_digest
                    if hasattr(page, "body_digest")
                    else page["body_digest"],
                    "row_count": page.row_count
                    if hasattr(page, "row_count")
                    else page["row_count"],
                    "request_path": page.request_path
                    if hasattr(page, "request_path")
                    else page["request_path"],
                    "request_params": dict(
                        page.request_params
                        if hasattr(page, "request_params")
                        else json.loads(page["request_params_json"])
                    ),
                    "pagination_in": page.pagination_in
                    if hasattr(page, "pagination_in")
                    else page["pagination_in"],
                    "pagination_out": page.pagination_out
                    if hasattr(page, "pagination_out")
                    else page["pagination_out"],
                    "response_status": page.response_status
                    if hasattr(page, "response_status")
                    else page["response_status"],
                }
                for index, page in enumerate(pages)
            ],
        }
    )


def month_end(month: str) -> str:
    year, number = (int(item) for item in month.split("-"))
    return date(year, number, monthrange(year, number)[1]).isoformat()


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def month_is_cacheable(month: str, today: date | None = None) -> bool:
    current = utc_today() if today is None else today
    return month_end(month) < current.isoformat()


def _require_month(month: str) -> str:
    match = _MONTH_RE.fullmatch(month)
    if match is None:
        raise AcquisitionCacheInvalid("cache month is invalid")
    year = int(match.group(1))
    number = int(match.group(2))
    try:
        parsed = date(year, number, 1)
    except ValueError as error:
        raise AcquisitionCacheInvalid("cache month is invalid") from error
    if parsed.isoformat()[:7] != month:
        raise AcquisitionCacheInvalid("cache month is invalid")
    return month


def cache_identity_document(
    *,
    environment: str,
    dataset_id: str,
    segment_id: str,
    segment_start: str,
    segment_end: str,
    route_path: str,
    route_mode: str,
    source_capability_digest: str,
    dataset_contract_digest: str,
    coverage_policy_digest: str,
    query_contract_digest: str,
    target_registry_digest: str,
) -> dict[str, Any]:
    if environment not in _ALLOWED_ENVIRONMENTS:
        raise PersonalHistoryError("acquisition environment is invalid")
    if dataset_id not in _ALLOWED_DATASETS:
        raise PersonalHistoryError(f"{dataset_id} is not a personal history dataset")
    _require_month(segment_id)
    return {
        "coverage_policy_digest": coverage_policy_digest,
        "dataset_contract_digest": dataset_contract_digest,
        "dataset_id": dataset_id,
        "environment": environment,
        "query_contract_digest": query_contract_digest,
        "route_mode": route_mode,
        "route_path": route_path,
        "schema": CACHE_FORMAT,
        "schema_epoch": CACHE_SCHEMA_EPOCH,
        "segment_end": segment_end,
        "segment_id": segment_id,
        "segment_start": segment_start,
        "source_capability_digest": source_capability_digest,
        "target_registry_digest": target_registry_digest,
    }


def cache_identity_hex(identity: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(dict(identity)).encode("utf-8")).hexdigest()
    if _HEX64_RE.fullmatch(digest) is None:
        raise AcquisitionCacheInvalid("cache identity is invalid")
    return digest


def cache_object_key(
    *,
    environment: str,
    dataset: str,
    month: str,
    identity_hex: str,
) -> str:
    if environment not in _ALLOWED_ENVIRONMENTS:
        raise PersonalHistoryError("acquisition environment is invalid")
    if dataset not in _ALLOWED_DATASETS:
        raise PersonalHistoryError(f"{dataset} is not a personal history dataset")
    _require_month(month)
    if _HEX64_RE.fullmatch(identity_hex) is None:
        raise AcquisitionCacheInvalid("cache identity is invalid")
    return (
        "research/personal/acquisition-cache/v1/"
        f"environment={environment}/dataset={dataset}/"
        f"month={month}/identity={identity_hex}.sqlite.gz"
    )


def parse_cache_object_key(key: str) -> dict[str, str]:
    prefix = "research/personal/acquisition-cache/v1/"
    if not key.startswith(prefix) or not key.endswith(".sqlite.gz"):
        raise AcquisitionCacheInvalid("cache object key is invalid")
    parts = key[len(prefix) : -len(".sqlite.gz")].split("/")
    if len(parts) != 4:
        raise AcquisitionCacheInvalid("cache object key is invalid")
    parsed: dict[str, str] = {}
    for part, expected in zip(
        parts, ("environment", "dataset", "month", "identity"), strict=True
    ):
        name, separator, value = part.partition("=")
        if separator != "=" or name != expected or not value:
            raise AcquisitionCacheInvalid("cache object key is invalid")
        parsed[expected] = value
    if parsed["environment"] not in _ALLOWED_ENVIRONMENTS:
        raise AcquisitionCacheInvalid("cache object key is invalid")
    if parsed["dataset"] not in _ALLOWED_DATASETS:
        raise AcquisitionCacheInvalid("cache object key is invalid")
    _require_month(parsed["month"])
    if _HEX64_RE.fullmatch(parsed["identity"]) is None:
        raise AcquisitionCacheInvalid("cache object key is invalid")
    return parsed


def closed_cache_get_headers(*, host: str) -> dict[str, str]:
    return {**CACHE_GET_FIXED_HEADERS, "host": host}


def closed_cache_put_headers(
    *,
    host: str,
    content_length: int,
    content_digest: str,
    raw_digest: str,
) -> dict[str, str]:
    if not isinstance(content_length, int) or content_length < 1:
        raise AcquisitionCacheInvalid("cache content-length is invalid")
    if content_length > CACHE_GZIP_MAX_BYTES:
        raise AcquisitionCacheInvalid("cache gzip exceeds the bound")
    if _DIGEST_RE.fullmatch(content_digest) is None:
        raise AcquisitionCacheInvalid("cache content digest is invalid")
    if _DIGEST_RE.fullmatch(raw_digest) is None:
        raise AcquisitionCacheInvalid("cache raw digest is invalid")
    return {
        **CACHE_PUT_FIXED_HEADERS,
        "content-length": str(content_length),
        "host": host,
        "x-acquisition-cache-raw-sha256": raw_digest,
        "x-content-sha256": content_digest,
    }


def _r2_host(origin: str) -> str:
    return urlparse(origin).hostname or "research.r2"


def build_cache_get_request(
    key: str, *, origin: str = CACHE_R2_ORIGIN
) -> urllib.request.Request:
    parse_cache_object_key(key)
    headers = closed_cache_get_headers(host=_r2_host(origin))
    return urllib.request.Request(
        f"{origin.rstrip('/')}/{key}",
        method="GET",
        headers=headers,
    )


def build_cache_put_request(
    key: str,
    body: bytes,
    *,
    content_digest: str,
    raw_digest: str,
    origin: str = CACHE_R2_ORIGIN,
) -> urllib.request.Request:
    parse_cache_object_key(key)
    headers = closed_cache_put_headers(
        host=_r2_host(origin),
        content_length=len(body),
        content_digest=content_digest,
        raw_digest=raw_digest,
    )
    return urllib.request.Request(
        f"{origin.rstrip('/')}/{key}",
        data=body,
        method="PUT",
        headers=headers,
    )


def header_name_is_forbidden(name: str) -> bool:
    lowered = name.strip().lower()
    return any(token in lowered for token in _FORBIDDEN_HEADER_OR_META)


def derived_row_code(row: Mapping[str, Any]) -> str | None:
    value = row.get("Code")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def derived_row_date(row: Mapping[str, Any]) -> str | None:
    for name in ("Date", "DiscDate", "DisclosedDate"):
        value = row.get(name)
        if isinstance(value, str) and _DATE_RE.fullmatch(value[:10]):
            return value[:10]
    return None


def require_cache_get_contract(
    headers: Mapping[str, str], body: bytes
) -> tuple[str, str]:
    if headers.get("content-type") != "application/gzip":
        raise AcquisitionCacheInvalid("cache content-type is invalid")
    raw_length = headers.get("content-length")
    if (
        raw_length is None
        or not raw_length.isdigit()
        or str(int(raw_length)) != raw_length
    ):
        raise AcquisitionCacheInvalid("cache content-length is invalid")
    length = int(raw_length)
    if length < 1 or length > CACHE_GZIP_MAX_BYTES:
        raise AcquisitionCacheInvalid("cache gzip exceeds the bound")
    if length != len(body):
        raise AcquisitionCacheInvalid("cache content-length does not match body")
    content_digest = headers.get("x-content-sha256")
    if content_digest is None:
        raise AcquisitionCacheInvalid("cache content digest is missing")
    if _DIGEST_RE.fullmatch(content_digest) is None:
        raise AcquisitionCacheInvalid("cache content digest is invalid")
    if content_digest != "sha256:" + hashlib.sha256(body).hexdigest():
        raise AcquisitionCacheInvalid("cache content digest does not match body")
    raw_digest = headers.get("x-acquisition-cache-raw-sha256")
    if raw_digest is None:
        raise AcquisitionCacheInvalid("cache raw digest is missing")
    if _DIGEST_RE.fullmatch(raw_digest) is None:
        raise AcquisitionCacheInvalid("cache raw digest is invalid")
    return content_digest, raw_digest


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def gzip_bytes(source: Path) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        compresslevel=6,
        fileobj=buffer,
        mtime=0,
    ) as compressed:
        with source.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                compressed.write(chunk)
    blob = buffer.getvalue()
    if len(blob) > CACHE_GZIP_MAX_BYTES:
        raise AcquisitionCacheInvalid("cache gzip exceeds the bound")
    return blob


def assert_deterministic_gzip(blob: bytes) -> None:
    if len(blob) < 10 or blob[0:2] != b"\x1f\x8b":
        raise AcquisitionCacheInvalid("cache gzip is invalid")
    if blob[3] != 0:
        raise AcquisitionCacheInvalid("cache gzip extra fields are forbidden")
    mtime = int.from_bytes(blob[4:8], "little")
    if mtime != 0:
        raise AcquisitionCacheInvalid("cache gzip mtime must be 0")


def gunzip_to_path(blob: bytes, destination: Path) -> None:
    if len(blob) > CACHE_GZIP_MAX_BYTES:
        raise AcquisitionCacheInvalid("cache gzip exceeds the bound")
    assert_deterministic_gzip(blob)
    written = 0
    with gzip.GzipFile(fileobj=io.BytesIO(blob), mode="rb") as compressed:
        if int(getattr(compressed, "mtime", 0) or 0) != 0:
            raise AcquisitionCacheInvalid("cache gzip mtime must be 0")
        with destination.open("wb") as handle:
            while True:
                chunk = compressed.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > CACHE_SQLITE_MAX_BYTES:
                    raise AcquisitionCacheInvalid("cache sqlite exceeds the bound")
                handle.write(chunk)
    if written < 1:
        raise AcquisitionCacheInvalid("cache sqlite is empty")


def _table_names(connection: sqlite3.Connection) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT name FROM sqlite_schema
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _column_names(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
    )


def _require_json_object(raw: str, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AcquisitionCacheInvalid(f"{label} is not JSON") from error
    if not isinstance(parsed, dict):
        raise AcquisitionCacheInvalid(f"{label} is not a JSON object")
    return parsed


@dataclass(frozen=True)
class VerifiedCacheMonth:
    identity: Mapping[str, Any]
    identity_hex: str
    environment: str
    dataset: str
    month: str
    completion_digest: str
    page_count: int
    pages: tuple[dict[str, Any], ...]
    rows: tuple[dict[str, Any], ...]


def write_month_shard(
    source: sqlite3.Connection,
    destination: Path,
    *,
    identity: Mapping[str, Any],
) -> str:
    dataset = str(identity["dataset_id"])
    month = str(identity["segment_id"])
    identity_hex = cache_identity_hex(identity)
    state = source.execute(
        "SELECT * FROM month_state WHERE dataset=? AND month=?",
        (dataset, month),
    ).fetchone()
    if state is None or str(state["status"]) != "COMPLETE":
        raise PersonalHistoryError(f"{dataset} {month} is not a verified COMPLETE month")
    pages = source.execute(
        f"""
        SELECT {", ".join(_PAGE_COLUMNS)}
        FROM source_pages
        WHERE dataset=? AND month=?
        ORDER BY page_ordinal
        """,
        (dataset, month),
    ).fetchall()
    rows = source.execute(
        f"""
        SELECT {", ".join(_ROW_COLUMNS)}
        FROM source_rows
        WHERE dataset=? AND month=?
        ORDER BY page_ordinal, row_index
        """,
        (dataset, month),
    ).fetchall()
    if destination.exists():
        destination.unlink()
    shard = sqlite3.connect(str(destination))
    try:
        shard.execute("PRAGMA journal_mode=DELETE")
        shard.executescript(
            """
            CREATE TABLE cache_identity (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                format TEXT NOT NULL,
                schema_epoch INTEGER NOT NULL,
                identity_json TEXT NOT NULL,
                identity_hex TEXT NOT NULL,
                environment TEXT NOT NULL,
                dataset_id TEXT NOT NULL,
                month TEXT NOT NULL
            );
            CREATE TABLE month_state (
                dataset TEXT NOT NULL,
                month TEXT NOT NULL,
                status TEXT NOT NULL,
                page_count INTEGER NOT NULL DEFAULT 0,
                next_cursor TEXT,
                identity_json TEXT,
                completion_digest TEXT,
                started_at TEXT,
                finished_at TEXT,
                PRIMARY KEY (dataset, month),
                CHECK (status IN ('FETCHING','COMPLETE'))
            );
            CREATE TABLE source_pages (
                dataset TEXT NOT NULL,
                month TEXT NOT NULL,
                page_ordinal INTEGER NOT NULL,
                slice_date TEXT,
                body_digest TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                request_path TEXT NOT NULL,
                request_params_json TEXT NOT NULL,
                response_status INTEGER NOT NULL,
                pagination_in TEXT,
                pagination_out TEXT,
                evidence_state TEXT NOT NULL,
                PRIMARY KEY (dataset, month, page_ordinal)
            );
            CREATE TABLE source_rows (
                dataset TEXT NOT NULL,
                month TEXT NOT NULL,
                page_ordinal INTEGER NOT NULL,
                row_index INTEGER NOT NULL,
                code TEXT,
                row_date TEXT,
                row_json TEXT NOT NULL,
                PRIMARY KEY (dataset, month, page_ordinal, row_index)
            );
            """
        )
        shard.execute(
            """
            INSERT INTO cache_identity (
                singleton, format, schema_epoch, identity_json, identity_hex,
                environment, dataset_id, month
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                CACHE_FORMAT,
                CACHE_SCHEMA_EPOCH,
                canonical_json(dict(identity)),
                identity_hex,
                str(identity["environment"]),
                dataset,
                month,
            ),
        )
        shard.execute(
            """
            INSERT INTO month_state (
                dataset, month, status, page_count, next_cursor, identity_json,
                completion_digest, started_at, finished_at
            ) VALUES (?, ?, 'COMPLETE', ?, NULL, ?, ?, NULL, NULL)
            """,
            (
                dataset,
                month,
                int(state["page_count"]),
                canonical_json(dict(identity)),
                str(state["completion_digest"]),
            ),
        )
        for page in pages:
            shard.execute(
                f"""
                INSERT INTO source_pages ({", ".join(_PAGE_COLUMNS)})
                VALUES ({", ".join("?" for _ in _PAGE_COLUMNS)})
                """,
                tuple(page[name] for name in _PAGE_COLUMNS),
            )
        for row in rows:
            shard.execute(
                f"""
                INSERT INTO source_rows ({", ".join(_ROW_COLUMNS)})
                VALUES ({", ".join("?" for _ in _ROW_COLUMNS)})
                """,
                tuple(row[name] for name in _ROW_COLUMNS),
            )
        shard.commit()
        shard.execute("VACUUM")
    finally:
        shard.close()
    size = destination.stat().st_size
    if size < 1 or size > CACHE_SQLITE_MAX_BYTES:
        raise AcquisitionCacheInvalid("cache sqlite exceeds the bound")
    return _file_sha256(destination)


def verify_month_shard(
    path: Path,
    *,
    expected_identity: Mapping[str, Any],
    expected_identity_hex: str,
) -> VerifiedCacheMonth:
    size = path.stat().st_size if path.exists() else 0
    if size < 1 or size > CACHE_SQLITE_MAX_BYTES:
        raise AcquisitionCacheInvalid("cache sqlite exceeds the bound")
    uri = "file:" + str(path.resolve()) + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        if [tuple(row) for row in integrity] != [("ok",)]:
            raise AcquisitionCacheInvalid("cache sqlite integrity_check failed")
        if _table_names(connection) != _SHARD_TABLES:
            raise AcquisitionCacheInvalid("cache sqlite schema is invalid")
        if _column_names(connection, "cache_identity") != (
            "singleton",
            "format",
            "schema_epoch",
            "identity_json",
            "identity_hex",
            "environment",
            "dataset_id",
            "month",
        ):
            raise AcquisitionCacheInvalid("cache identity schema is invalid")
        meta_rows = connection.execute(
            "SELECT * FROM cache_identity ORDER BY singleton"
        ).fetchall()
        if len(meta_rows) != 1:
            raise AcquisitionCacheInvalid("cache identity must be a singleton")
        meta = meta_rows[0]
        identity = _require_json_object(str(meta["identity_json"]), "cache identity")
        if (
            str(meta["format"]) != CACHE_FORMAT
            or int(meta["schema_epoch"]) != CACHE_SCHEMA_EPOCH
            or str(meta["identity_hex"]) != expected_identity_hex
            or cache_identity_hex(identity) != expected_identity_hex
            or canonical_json(identity) != canonical_json(dict(expected_identity))
            or str(meta["environment"]) != str(expected_identity["environment"])
            or str(meta["dataset_id"]) != str(expected_identity["dataset_id"])
            or str(meta["month"]) != str(expected_identity["segment_id"])
        ):
            raise AcquisitionCacheInvalid("cache identity does not match")
        states = connection.execute("SELECT * FROM month_state").fetchall()
        if len(states) != 1:
            raise AcquisitionCacheInvalid("cache must contain exactly one month_state")
        state = states[0]
        dataset = str(state["dataset"])
        month = str(state["month"])
        if (
            dataset != str(expected_identity["dataset_id"])
            or month != str(expected_identity["segment_id"])
            or str(state["status"]) != "COMPLETE"
            or state["started_at"] is not None
            or state["finished_at"] is not None
            or state["next_cursor"] is not None
        ):
            raise AcquisitionCacheInvalid("cache month_state is invalid")
        stored_identity = _require_json_object(
            str(state["identity_json"] or ""), "month identity"
        )
        if canonical_json(stored_identity) != canonical_json(dict(expected_identity)):
            raise AcquisitionCacheInvalid("cache month identity does not match")
        if "acquisition_nonce" in stored_identity:
            raise AcquisitionCacheInvalid("cache identity must omit acquisition nonce")
        declared = int(state["page_count"])
        if declared < 1 or declared > CACHE_MAX_PAGES:
            raise AcquisitionCacheInvalid("cache page count exceeds the bound")
        page_sql_count = int(
            connection.execute("SELECT COUNT(*) FROM source_pages").fetchone()[0]
        )
        if page_sql_count != declared:
            raise AcquisitionCacheInvalid("cache page count does not match")
        total_row_sql = int(
            connection.execute("SELECT COUNT(*) FROM source_rows").fetchone()[0]
        )
        if total_row_sql > CACHE_MAX_ROWS_TOTAL:
            raise AcquisitionCacheInvalid("cache row count exceeds the bound")
        declared_row_sum = int(
            connection.execute(
                "SELECT COALESCE(SUM(row_count), 0) FROM source_pages"
            ).fetchone()[0]
        )
        if declared_row_sum != total_row_sql or declared_row_sum > CACHE_MAX_ROWS_TOTAL:
            raise AcquisitionCacheInvalid("cache row counts do not match pages")
        extra_rows = connection.execute(
            "SELECT COUNT(*) FROM source_rows WHERE dataset!=? OR month!=?",
            (dataset, month),
        ).fetchone()
        if int(extra_rows[0]) != 0:
            raise AcquisitionCacheInvalid("cache rows include a foreign month")
        orphan = connection.execute(
            """
            SELECT 1 FROM source_rows
            WHERE NOT EXISTS (
                SELECT 1 FROM source_pages
                WHERE source_pages.dataset = source_rows.dataset
                  AND source_pages.month = source_rows.month
                  AND source_pages.page_ordinal = source_rows.page_ordinal
            )
            LIMIT 1
            """
        ).fetchone()
        if orphan is not None:
            raise AcquisitionCacheInvalid("cache has orphan source_rows")
        pages = connection.execute(
            f"""
            SELECT {", ".join(_PAGE_COLUMNS)}
            FROM source_pages
            ORDER BY page_ordinal
            """
        ).fetchall()
        if {str(page["dataset"]) for page in pages} != {dataset}:
            raise AcquisitionCacheInvalid("cache pages include a foreign dataset")
        if {str(page["month"]) for page in pages} != {month}:
            raise AcquisitionCacheInvalid("cache pages include a foreign month")
        count = len(pages)
        expected_ordinal = 0
        for page in pages:
            if int(page["page_ordinal"]) != expected_ordinal:
                raise AcquisitionCacheInvalid("cache page ordinals are not contiguous")
            expected_ordinal += 1
        if expected_ordinal != count or count != declared:
            raise AcquisitionCacheInvalid("cache page ordinals are not contiguous")
        if pages[0]["pagination_in"] is not None:
            raise AcquisitionCacheInvalid("cache first page pagination_in must be empty")
        for index in range(1, count):
            if pages[index]["pagination_in"] != pages[index - 1]["pagination_out"]:
                raise AcquisitionCacheInvalid("cache pagination chain is broken")
        if pages[-1]["pagination_out"] is not None:
            raise AcquisitionCacheInvalid("cache final page is not exhausted")
        copied_pages: list[dict[str, Any]] = []
        copied_rows: list[dict[str, Any]] = []
        for page in pages:
            ordinal = int(page["page_ordinal"])
            stored_count = int(page["row_count"])
            if stored_count < 0 or stored_count > CACHE_MAX_ROWS_PER_PAGE:
                raise AcquisitionCacheInvalid("cache page row count exceeds the bound")
            row_sql_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM source_rows
                    WHERE dataset=? AND month=? AND page_ordinal=?
                    """,
                    (dataset, month, ordinal),
                ).fetchone()[0]
            )
            if row_sql_count != stored_count:
                raise AcquisitionCacheInvalid("cache page row count does not match")
            page_rows = connection.execute(
                f"""
                SELECT {", ".join(_ROW_COLUMNS)}
                FROM source_rows
                WHERE dataset=? AND month=? AND page_ordinal=?
                ORDER BY row_index
                """,
                (dataset, month, ordinal),
            ).fetchall()
            _require_json_object(str(page["request_params_json"]), "request params")
            expected_index = 0
            for row in page_rows:
                if int(row["row_index"]) != expected_index:
                    raise AcquisitionCacheInvalid("cache page rows do not match descriptor")
                if str(row["dataset"]) != dataset or str(row["month"]) != month:
                    raise AcquisitionCacheInvalid("cache rows include a foreign month")
                parsed_row = _require_json_object(str(row["row_json"]), "source row")
                if row["code"] != derived_row_code(parsed_row) or row[
                    "row_date"
                ] != derived_row_date(parsed_row):
                    raise AcquisitionCacheInvalid("cache row index does not match row_json")
                copied_rows.append({name: row[name] for name in _ROW_COLUMNS})
                expected_index += 1
            if expected_index != stored_count:
                raise AcquisitionCacheInvalid("cache page row count does not match")
            copied_pages.append({name: page[name] for name in _PAGE_COLUMNS})
        reconstructed = [
            {
                "body_digest": page["body_digest"],
                "row_count": page["row_count"],
                "request_path": page["request_path"],
                "request_params_json": page["request_params_json"],
                "pagination_in": page["pagination_in"],
                "pagination_out": page["pagination_out"],
                "response_status": page["response_status"],
            }
            for page in copied_pages
        ]
        actual = month_completion_digest(reconstructed)
        stored_digest = str(state["completion_digest"] or "")
        if stored_digest != actual:
            raise AcquisitionCacheInvalid("cache completion digest does not match")
        return VerifiedCacheMonth(
            identity=identity,
            identity_hex=expected_identity_hex,
            environment=str(expected_identity["environment"]),
            dataset=dataset,
            month=month,
            completion_digest=actual,
            page_count=count,
            pages=tuple(copied_pages),
            rows=tuple(copied_rows),
        )
    finally:
        connection.close()
