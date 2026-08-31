"""Closed personal-history client over the Container history.source host.

The adapter implements ``fetch_dataset_evidenced`` for PersonalHistoryHydrator
by posting the existing J-Quants acquisition RPC request shape.  It stores
immutable source-page descriptors on an ephemeral disk spool and returns
selected rows with contributing-page proof.  It does not claim receipts,
Coverage, or READY.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse
import urllib.error
import urllib.request

from data_contracts.identity import canonical_json
from ingestion.jquants import acquisition_collection as acquisition
from ingestion.personal_history import PERSONAL_HISTORY_DATASETS, PersonalHistoryError

_CONTAINER_MODULE_DIR = str(Path(__file__).resolve().parent)
if _CONTAINER_MODULE_DIR not in sys.path:
    sys.path.insert(0, _CONTAINER_MODULE_DIR)

from personal_acquisition_cache import (
    CACHE_GET_TIMEOUT_S,
    CACHE_GZIP_MAX_BYTES,
    CACHE_PUT_TIMEOUT_S,
    CACHE_R2_ORIGIN,
    AcquisitionCacheConflict,
    AcquisitionCacheInvalid,
    AcquisitionCacheMiss,
    AcquisitionCacheUnavailable,
    VerifiedCacheMonth,
    build_cache_get_request,
    build_cache_put_request,
    cache_identity_document,
    cache_identity_hex,
    cache_object_key,
    gunzip_to_path,
    gzip_bytes,
    month_completion_digest,
    require_cache_get_contract,
    month_is_cacheable,
    utc_today as cache_utc_today,
    verify_month_shard,
    write_month_shard,
)

HISTORY_SOURCE_ORIGIN = "http://history.source"
HISTORY_SOURCE_PATH = "/v1/fetch-governed-page"
HISTORY_SOURCE_USER_AGENT = "quant-personal-history/v13"
HISTORY_SOURCE_FIXED_HEADERS = MappingProxyType(
    {
        "accept": "application/json",
        "accept-encoding": "identity",
        "connection": "close",
        "content-type": "application/json; charset=utf-8",
        "user-agent": HISTORY_SOURCE_USER_AGENT,
    }
)
_MAX_PAGES_PER_MONTH = 8192
_MAX_POST_ATTEMPTS = 4
_TRANSIENT_POST_STATUSES = frozenset({502, 503, 504})
_TRANSIENT_RETRY_DELAYS_S = (1, 2, 4)
_RETRY_AFTER_MIN_S = 1
_RETRY_AFTER_MAX_S = 120
_RETRY_AFTER_SECONDS_RE = __import__("re").compile(r"^[0-9]+$")
# 20 GiB Container disk: 3.5 GiB sqlite + ~3.5 GiB gzip + 256 MiB reserve.
# Keep the ephemeral spool under 8 GiB so a full snapshot still fits.
MAX_SPOOL_PAGES = 32_768
MAX_SPOOL_BYTES = 8 * 1024 ** 3
_DATE_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")


def _month_end(month: str) -> str:
    year, number = (int(item) for item in month.split("-"))
    return date(year, number, monthrange(year, number)[1]).isoformat()


def _month_of(day: str) -> str:
    return day[:7]


def _iter_months(start: str, end: str) -> list[str]:
    current = date.fromisoformat(f"{_month_of(start)}-01")
    last = date.fromisoformat(f"{_month_of(end)}-01")
    months: list[str] = []
    while current <= last:
        months.append(current.isoformat()[:7])
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        current = date(year, month, 1)
    return months


def _row_date(row: Mapping[str, Any]) -> str | None:
    for name in ("Date", "DiscDate", "DisclosedDate"):
        value = row.get(name)
        if isinstance(value, str) and _DATE_RE.fullmatch(value[:10]):
            return value[:10]
    return None


def _row_code(row: Mapping[str, Any]) -> str | None:
    value = row.get("Code")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if rows is None:
        for key in ("info", "daily_bars", "calendar", "summary"):
            if key in payload:
                rows = payload[key]
                break
    return [dict(row) for row in rows] if isinstance(rows, list) else []


def _canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        canonical_json(value).encode("utf-8")
    ).hexdigest()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def closed_history_source_headers(*, content_length: int, host: str) -> dict[str, str]:
    if not isinstance(content_length, int) or content_length < 1:
        raise PersonalHistoryError("history.source content-length is invalid")
    return {
        **HISTORY_SOURCE_FIXED_HEADERS,
        "content-length": str(content_length),
        "host": host,
    }


def _header_get(headers: Any, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    value = getter(name)
    if value is None:
        value = getter(name.lower())
    return value if isinstance(value, str) else None


def _bounded_retry_after_seconds(headers: Any) -> int | None:
    raw = _header_get(headers, "Retry-After")
    if raw is None or _RETRY_AFTER_SECONDS_RE.fullmatch(raw) is None:
        return None
    delay = int(raw)
    if delay < _RETRY_AFTER_MIN_S or delay > _RETRY_AFTER_MAX_S:
        return None
    return delay


def _close_http_error(error: urllib.error.HTTPError) -> None:
    try:
        error.read()
    except Exception:
        pass
    try:
        error.close()
    except Exception:
        pass


def build_history_source_request(body: bytes, *, origin: str = HISTORY_SOURCE_ORIGIN) -> urllib.request.Request:
    host = urlparse(origin).hostname or "history.source"
    headers = closed_history_source_headers(content_length=len(body), host=host)
    return urllib.request.Request(
        f"{origin.rstrip('/')}{HISTORY_SOURCE_PATH}",
        data=body,
        method="POST",
        headers=headers,
    )


@dataclass(frozen=True)
class SourcePage:
    request_path: str
    request_params: Mapping[str, Any]
    response_status: int
    body_digest: str
    row_count: int
    pagination_in: str | None = None
    pagination_out: str | None = None
    evidence_state: str | None = None
    slice_date: str | None = None
    response_body: bytes | None = None


@dataclass(frozen=True)
class SelectionEvidence:
    query: Mapping[str, Any]
    selected_row_count: int
    selected_digest: str
    source_row_count: int
    scanned_page_digests: tuple[str, ...]
    completion_digest: str
    contributing_page_digests: tuple[str, ...]


@dataclass(frozen=True)
class _Fetch:
    rows: tuple[dict[str, Any], ...]
    pages: tuple[SourcePage, ...]
    selection: SelectionEvidence | None = None


def selection_completion_digest(
    *,
    scanned_page_digests: Sequence[str],
    source_row_count: int,
) -> str:
    return _canonical_digest(
        {
            "scanned_page_digests": list(scanned_page_digests),
            "source_row_count": source_row_count,
            "page_count": len(scanned_page_digests),
            "status": "COMPLETE",
        }
    )


class AcquisitionSpool:
    """Ephemeral disk index of governed pages and decoded rows."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS source_pages (
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
            CREATE TABLE IF NOT EXISTS source_rows (
                dataset TEXT NOT NULL,
                month TEXT NOT NULL,
                page_ordinal INTEGER NOT NULL,
                row_index INTEGER NOT NULL,
                code TEXT,
                row_date TEXT,
                row_json TEXT NOT NULL,
                PRIMARY KEY (dataset, month, page_ordinal, row_index)
            );
            CREATE INDEX IF NOT EXISTS source_rows_dataset_date
                ON source_rows(dataset, row_date);
            CREATE INDEX IF NOT EXISTS source_rows_dataset_code
                ON source_rows(dataset, code);
            CREATE TABLE IF NOT EXISTS month_state (
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
            """
        )
        self._conn.commit()
        # Instance-local reuse of already-verified COMPLETE months. Not durable
        # and not shared with another spool/client/job.
        self._verified_pages: dict[tuple[str, str], tuple[SourcePage, ...]] = {}

    def close(self) -> None:
        self._verified_pages.clear()
        self._conn.close()

    def _checkpoint_committed_wal(self) -> None:
        result = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result is not None and int(result[0]) != 0:
            raise PersonalHistoryError(
                "acquisition spool WAL checkpoint could not acquire a safe lock"
            )

    def usage(self) -> tuple[int, int]:
        pages = int(
            self._conn.execute("SELECT COUNT(*) FROM source_pages").fetchone()[0]
        )
        size = self.path.stat().st_size if self.path.exists() else 0
        for suffix in ("-wal", "-shm"):
            extra = Path(str(self.path) + suffix)
            if extra.exists():
                size += extra.stat().st_size
        return pages, size

    def guard_bounds(self, *, extra_pages: int = 0, extra_bytes: int = 0) -> None:
        # Sole TRUNCATE site: pre-write extra_bytes and post-write physical size.
        self._checkpoint_committed_wal()
        pages, size = self.usage()
        next_pages = pages + extra_pages
        next_bytes = size + extra_bytes
        if next_pages > MAX_SPOOL_PAGES:
            raise PersonalHistoryError(
                "acquisition spool page bound exceeded: "
                f"pages={next_pages} max={MAX_SPOOL_PAGES}"
            )
        if next_bytes > MAX_SPOOL_BYTES:
            raise PersonalHistoryError(
                "acquisition spool byte bound exceeded: "
                f"bytes={next_bytes} max={MAX_SPOOL_BYTES}"
            )

    def month_complete(self, dataset: str, month: str) -> bool:
        return self.verified_complete_month(dataset, month) is not None

    def has_month(self, dataset: str, month: str) -> bool:
        return self.verified_complete_month(dataset, month) is not None

    def month_completion_digest(self, dataset: str, month: str) -> str | None:
        pages = self.verified_complete_month(dataset, month)
        return None if pages is None else month_completion_digest(pages)

    def verified_complete_month(
        self, dataset: str, month: str
    ) -> tuple[SourcePage, ...] | None:
        state = self._conn.execute(
            "SELECT * FROM month_state WHERE dataset=? AND month=?",
            (dataset, month),
        ).fetchone()
        if state is None or str(state["status"]) != "COMPLETE":
            return None
        pages = self._conn.execute(
            """
            SELECT page_ordinal, body_digest, row_count, request_path,
                   request_params_json, response_status, pagination_in,
                   pagination_out, evidence_state, slice_date
            FROM source_pages
            WHERE dataset=? AND month=?
            ORDER BY page_ordinal
            """,
            (dataset, month),
        ).fetchall()
        try:
            self._assert_verified_complete(state, pages, dataset, month)
        except PersonalHistoryError:
            self.clear_month(dataset, month)
            return None
        return tuple(self._page_from_row(page) for page in pages)

    def _cached_verified_month(
        self, dataset: str, month: str
    ) -> tuple[SourcePage, ...] | None:
        key = (dataset, month)
        cached = self._verified_pages.get(key)
        if cached is not None:
            return cached
        pages = self.verified_complete_month(dataset, month)
        if pages is None:
            return None
        self._verified_pages[key] = pages
        return pages

    def _assert_verified_complete(
        self,
        state: sqlite3.Row,
        pages: Sequence[sqlite3.Row],
        dataset: str,
        month: str,
    ) -> None:
        count = len(pages)
        declared = int(state["page_count"])
        if count < 1 or declared != count:
            raise PersonalHistoryError(
                f"{dataset} {month} COMPLETE page count does not match stored pages"
            )
        ordinals = [int(page["page_ordinal"]) for page in pages]
        if ordinals != list(range(count)):
            raise PersonalHistoryError(
                f"{dataset} {month} page ordinals are not contiguous"
            )
        duplicate = self._conn.execute(
            """
            SELECT 1 FROM source_pages
            WHERE dataset=? AND month=?
            GROUP BY page_ordinal HAVING COUNT(*) > 1
            LIMIT 1
            """,
            (dataset, month),
        ).fetchone()
        if duplicate is not None:
            raise PersonalHistoryError(f"{dataset} {month} has duplicate page ordinals")
        if pages[0]["pagination_in"] is not None:
            raise PersonalHistoryError(
                f"{dataset} {month} first page pagination_in must be empty"
            )
        for index in range(1, count):
            if pages[index]["pagination_in"] != pages[index - 1]["pagination_out"]:
                raise PersonalHistoryError(
                    f"{dataset} {month} pagination chain is broken"
                )
        if pages[-1]["pagination_out"] is not None:
            raise PersonalHistoryError(
                f"{dataset} {month} final page is not exhausted"
            )
        try:
            identity = json.loads(str(state["identity_json"] or ""))
        except json.JSONDecodeError as error:
            raise PersonalHistoryError(
                f"{dataset} {month} acquisition identity is invalid"
            ) from error
        if (
            not isinstance(identity, dict)
            or identity.get("dataset_id") != dataset
            or identity.get("segment_id") != month
        ):
            raise PersonalHistoryError(
                f"{dataset} {month} acquisition identity does not match"
            )
        paths = {str(page["request_path"]) for page in pages}
        if len(paths) != 1 or not next(iter(paths)):
            raise PersonalHistoryError(
                f"{dataset} {month} request path identity drifted"
            )
        reconstructed: list[SourcePage] = []
        for page in pages:
            ordinal = int(page["page_ordinal"])
            stored_count = int(page["row_count"])
            rows = self._conn.execute(
                """
                SELECT row_index, row_json FROM source_rows
                WHERE dataset=? AND month=? AND page_ordinal=?
                ORDER BY row_index
                """,
                (dataset, month, ordinal),
            ).fetchall()
            if [int(row["row_index"]) for row in rows] != list(range(stored_count)):
                raise PersonalHistoryError(
                    f"{dataset} {month} page {ordinal} rows do not match descriptor"
                )
            if len(rows) != stored_count:
                raise PersonalHistoryError(
                    f"{dataset} {month} page {ordinal} row count does not match"
                )
            for row in rows:
                try:
                    json.loads(str(row["row_json"]))
                except json.JSONDecodeError as error:
                    raise PersonalHistoryError(
                        f"{dataset} {month} page {ordinal} row is not JSON"
                    ) from error
            reconstructed.append(self._page_from_row(page))
        actual = month_completion_digest(reconstructed)
        stored_digest = str(state["completion_digest"] or "")
        if stored_digest != actual:
            raise PersonalHistoryError(
                f"{dataset} {month} completion digest does not match stored pages"
            )

    def clear_month(self, dataset: str, month: str) -> None:
        self._verified_pages.pop((dataset, month), None)
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                "DELETE FROM source_rows WHERE dataset=? AND month=?",
                (dataset, month),
            )
            self._conn.execute(
                "DELETE FROM source_pages WHERE dataset=? AND month=?",
                (dataset, month),
            )
            self._conn.execute(
                "DELETE FROM month_state WHERE dataset=? AND month=?",
                (dataset, month),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def begin_month(self, dataset: str, month: str, identity: Mapping[str, Any]) -> None:
        self._verified_pages.pop((dataset, month), None)
        self._conn.execute(
            """
            INSERT INTO month_state (
                dataset, month, status, page_count, next_cursor, identity_json,
                completion_digest, started_at, finished_at
            ) VALUES (?,?, 'FETCHING', 0, NULL, ?, NULL, ?, NULL)
            """,
            (dataset, month, canonical_json(dict(identity)), _now_iso()),
        )
        self._conn.commit()

    def complete_month(
        self,
        dataset: str,
        month: str,
        *,
        page_count: int,
        completion_digest: str,
    ) -> None:
        cursor = self._conn.execute(
            """
            UPDATE month_state SET
                status='COMPLETE', page_count=?, next_cursor=NULL,
                completion_digest=?, finished_at=?
            WHERE dataset=? AND month=?
            """,
            (page_count, completion_digest, _now_iso(), dataset, month),
        )
        if cursor.rowcount != 1:
            raise PersonalHistoryError(
                f"{dataset} {month} completion marker was not durable"
            )
        self._conn.commit()

    def import_complete_month(self, cached: VerifiedCacheMonth) -> None:
        extra_bytes = sum(len(str(row["row_json"]).encode("utf-8")) for row in cached.rows) + 512
        self.guard_bounds(extra_pages=len(cached.pages), extra_bytes=extra_bytes)
        self._verified_pages.pop((cached.dataset, cached.month), None)
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                "DELETE FROM source_rows WHERE dataset=? AND month=?",
                (cached.dataset, cached.month),
            )
            self._conn.execute(
                "DELETE FROM source_pages WHERE dataset=? AND month=?",
                (cached.dataset, cached.month),
            )
            self._conn.execute(
                "DELETE FROM month_state WHERE dataset=? AND month=?",
                (cached.dataset, cached.month),
            )
            self._conn.execute(
                """
                INSERT INTO month_state (
                    dataset, month, status, page_count, next_cursor, identity_json,
                    completion_digest, started_at, finished_at
                ) VALUES (?, ?, 'COMPLETE', ?, NULL, ?, ?, NULL, NULL)
                """,
                (
                    cached.dataset,
                    cached.month,
                    cached.page_count,
                    canonical_json(dict(cached.identity)),
                    cached.completion_digest,
                ),
            )
            for page in cached.pages:
                self._conn.execute(
                    """
                    INSERT INTO source_pages (
                        dataset, month, page_ordinal, slice_date, body_digest,
                        row_count, request_path, request_params_json, response_status,
                        pagination_in, pagination_out, evidence_state
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        page["dataset"],
                        page["month"],
                        page["page_ordinal"],
                        page["slice_date"],
                        page["body_digest"],
                        page["row_count"],
                        page["request_path"],
                        page["request_params_json"],
                        page["response_status"],
                        page["pagination_in"],
                        page["pagination_out"],
                        page["evidence_state"],
                    ),
                )
            for row in cached.rows:
                self._conn.execute(
                    """
                    INSERT INTO source_rows (
                        dataset, month, page_ordinal, row_index, code, row_date,
                        row_json
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        row["dataset"],
                        row["month"],
                        row["page_ordinal"],
                        row["row_index"],
                        row["code"],
                        row["row_date"],
                        row["row_json"],
                    ),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        self.guard_bounds()

    def record_page(
        self,
        *,
        dataset: str,
        month: str,
        page_ordinal: int,
        slice_date: str | None,
        body_digest: str,
        row_count: int,
        request_path: str,
        request_params: Mapping[str, Any],
        response_status: int,
        pagination_in: str | None,
        pagination_out: str | None,
        evidence_state: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        encoded_rows = [canonical_json(dict(row)) for row in rows]
        extra_bytes = sum(len(item.encode("utf-8")) for item in encoded_rows) + 512
        self.guard_bounds(extra_pages=1, extra_bytes=extra_bytes)
        self._conn.execute("BEGIN")
        try:
            self._conn.execute(
                """
                INSERT INTO source_pages (
                    dataset, month, page_ordinal, slice_date, body_digest,
                    row_count, request_path, request_params_json, response_status,
                    pagination_in, pagination_out, evidence_state
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    dataset,
                    month,
                    page_ordinal,
                    slice_date,
                    body_digest,
                    row_count,
                    request_path,
                    canonical_json(dict(request_params)),
                    response_status,
                    pagination_in,
                    pagination_out,
                    evidence_state,
                ),
            )
            for index, row in enumerate(rows):
                self._conn.execute(
                    """
                    INSERT INTO source_rows (
                        dataset, month, page_ordinal, row_index, code, row_date,
                        row_json
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        dataset,
                        month,
                        page_ordinal,
                        index,
                        _row_code(row),
                        _row_date(row),
                        encoded_rows[index],
                    ),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        self.guard_bounds()

    def _page_from_row(self, row: sqlite3.Row) -> SourcePage:
        return SourcePage(
            request_path=str(row["request_path"]),
            request_params=MappingProxyType(json.loads(row["request_params_json"])),
            response_status=int(row["response_status"]),
            body_digest=str(row["body_digest"]),
            row_count=int(row["row_count"]),
            pagination_in=row["pagination_in"],
            pagination_out=row["pagination_out"],
            evidence_state=row["evidence_state"],
            slice_date=row["slice_date"],
        )

    def pages_for_month(self, dataset: str, month: str) -> tuple[SourcePage, ...]:
        return self.verified_complete_month(dataset, month) or ()

    def pages_for_months(
        self, dataset: str, months: Sequence[str]
    ) -> tuple[SourcePage, ...]:
        collected: list[SourcePage] = []
        for month in months:
            verified = self._cached_verified_month(dataset, month)
            if verified is None:
                raise PersonalHistoryError(
                    f"{dataset} {month} is not a verified COMPLETE month"
                )
            collected.extend(verified)
        return tuple(collected)

    def pages_for_slice(self, dataset: str, slice_date: str) -> tuple[SourcePage, ...]:
        rows = self._conn.execute(
            """
            SELECT body_digest, row_count, request_path, request_params_json,
                   response_status, pagination_in, pagination_out,
                   evidence_state, slice_date
            FROM source_pages
            JOIN month_state USING (dataset, month)
            WHERE dataset=? AND slice_date=? AND month_state.status='COMPLETE'
            ORDER BY month, page_ordinal
            """,
            (dataset, slice_date),
        ).fetchall()
        return tuple(self._page_from_row(row) for row in rows)

    def contributing_pages(
        self,
        dataset: str,
        *,
        digests: Sequence[str],
    ) -> tuple[SourcePage, ...]:
        if not digests:
            return ()
        placeholders = ",".join("?" for _ in digests)
        rows = self._conn.execute(
            f"""
            SELECT body_digest, row_count, request_path, request_params_json,
                   response_status, pagination_in, pagination_out,
                   evidence_state, slice_date
            FROM source_pages
            JOIN month_state USING (dataset, month)
            WHERE dataset=? AND body_digest IN ({placeholders})
              AND month_state.status='COMPLETE'
            ORDER BY month, page_ordinal
            """,
            (dataset, *digests),
        ).fetchall()
        return tuple(self._page_from_row(row) for row in rows)

    def select_rows(
        self,
        dataset: str,
        months: Sequence[str],
        *,
        row_date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        code: str | None = None,
    ) -> tuple[list[dict[str, Any]], tuple[str, ...], tuple[SourcePage, ...], int]:
        pages = self.pages_for_months(dataset, months)
        if not months:
            return [], (), pages, 0
        month_filter = ",".join("?" for _ in months)
        clauses = [
            "dataset=?",
            f"month IN ({month_filter})",
            "month_state.status='COMPLETE'",
        ]
        params: list[Any] = [dataset, *months]
        if row_date is not None:
            clauses.append("row_date=?")
            params.append(row_date)
        if date_from is not None:
            clauses.append("row_date>=?")
            params.append(date_from)
        if date_to is not None:
            clauses.append("row_date<=?")
            params.append(date_to)
        if code is not None:
            clauses.append("code=?")
            params.append(code)
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            f"""
            SELECT row_json, body_digest FROM source_rows
            JOIN source_pages USING (dataset, month, page_ordinal)
            JOIN month_state USING (dataset, month)
            WHERE {where}
            ORDER BY month, page_ordinal, row_index
            """,
            params,
        ).fetchall()
        selected = [json.loads(row["row_json"]) for row in rows]
        contributing = tuple(dict.fromkeys(str(row["body_digest"]) for row in rows))
        source_count = sum(page.row_count for page in pages)
        return selected, contributing, pages, source_count


class PersonalHistorySourceClient:
    """Hydrator client that may only call the four personal history datasets."""

    def __init__(
        self,
        *,
        environment: str,
        period_end: str,
        spool_path: Path,
        origin: str = HISTORY_SOURCE_ORIGIN,
        opener: Any = None,
        r2_opener: Any = None,
        r2_origin: str = CACHE_R2_ORIGIN,
        utc_today: Callable[[], date] | None = None,
        _sleep: Any = None,
        _max_attempts: int | None = None,
    ) -> None:
        if environment not in {"production", "staging"}:
            raise PersonalHistoryError("acquisition environment is invalid")
        self.environment = environment
        self.period_end = period_end
        self.origin = origin.rstrip("/")
        self.r2_origin = r2_origin.rstrip("/")
        self._opener = opener
        self._r2_opener = r2_opener
        self._utc_today = cache_utc_today if utc_today is None else utc_today
        self._sleep = time.sleep if _sleep is None else _sleep
        self._max_attempts = _MAX_POST_ATTEMPTS if _max_attempts is None else _max_attempts
        self._registry = acquisition._target_registry()
        self.spool = AcquisitionSpool(spool_path)
        self.fetch_calls = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_published = 0
        self.cache_unavailable = 0
        self._live_bodies = 0
        self._started_at = time.monotonic()
        self.progress: dict[str, Any] = {
            "months_complete": 0,
            "pages": 0,
            "bytes": 0,
            "elapsed_s": 0.0,
        }

    def cache_metrics(self) -> dict[str, int]:
        return {
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_published": self.cache_published,
            "cache_unavailable": self.cache_unavailable,
            "live_fetch_calls": self.fetch_calls,
        }

    def close(self) -> None:
        self.spool.close()

    def fetch_dataset_evidenced(self, dataset: str, **params: Any) -> _Fetch:
        if dataset not in PERSONAL_HISTORY_DATASETS:
            raise PersonalHistoryError(f"{dataset} is not a personal history dataset")
        if dataset == "markets_calendar":
            return self._calendar(str(params["from"]), str(params["to"]))
        if dataset == "equities_master":
            return self._day_selection(dataset, str(params["date"]))
        if dataset == "equities_bars_daily":
            return self._day_selection(dataset, str(params["date"]))
        return self._fins_code(str(params["code"]))

    def _route(self, dataset: str) -> Any:
        route = self._registry.routes.get(dataset)
        if route is None:
            raise PersonalHistoryError(f"{dataset} is not in the acquisition registry")
        return route

    def _governed_request(
        self,
        dataset: str,
        month: str,
        continuation_token: str | None,
        identity: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if identity is not None:
            return {**dict(identity), "continuation_token": continuation_token}
        route = self._route(dataset)
        first = f"{month}-01"
        start = max(first, route.earliest)
        return {
            "schema_version": "jquants-acquisition-rpc-request/v2",
            "environment": self.environment,
            "operation": "fetch_governed_page",
            "dataset_id": dataset,
            "segment_id": month,
            "segment_start": start,
            "segment_end": _month_end(month),
            "acquisition_nonce": secrets.token_hex(32),
            "source_capability_digest": route.source_capability_digest,
            "dataset_contract_digest": route.dataset_contract_digest,
            "coverage_policy_digest": route.coverage_policy_digest,
            "query_contract_digest": route.query_contract_digest,
            "target_registry_digest": self._registry.digest,
            "continuation_token": continuation_token,
        }

    def _post(self, payload: Mapping[str, Any]) -> tuple[bytes, Mapping[str, str], int]:
        body = json.dumps(
            dict(payload),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        request = build_history_source_request(body, origin=self.origin)
        opener = self._opener or urllib.request
        attempts = self._max_attempts
        for attempt in range(attempts):
            try:
                with opener.urlopen(request, timeout=120) as response:
                    raw = response.read()
                    headers = {key.lower(): value for key, value in response.headers.items()}
                    return raw, headers, int(response.status)
            except urllib.error.HTTPError as error:
                code = int(error.code)
                retry_after = (
                    _bounded_retry_after_seconds(error.headers) if code == 429 else None
                )
                _close_http_error(error)
                if attempt + 1 >= attempts:
                    raise PersonalHistoryError(
                        f"history.source returned HTTP {code}"
                    ) from error
                if code == 429:
                    if retry_after is None:
                        raise PersonalHistoryError(
                            "history.source returned HTTP 429"
                        ) from error
                    delay = retry_after
                elif code in _TRANSIENT_POST_STATUSES:
                    delay = _TRANSIENT_RETRY_DELAYS_S[
                        min(attempt, len(_TRANSIENT_RETRY_DELAYS_S) - 1)
                    ]
                else:
                    raise PersonalHistoryError(
                        f"history.source returned HTTP {code}"
                    ) from error
                self._sleep(delay)
        raise PersonalHistoryError("history.source retry attempts are invalid")

    def _refresh_progress(self) -> None:
        pages, size = self.spool.usage()
        self.progress = {
            "months_complete": int(
                self.spool._conn.execute(
                    "SELECT COUNT(*) FROM month_state WHERE status='COMPLETE'"
                ).fetchone()[0]
            ),
            "pages": pages,
            "bytes": size,
            "elapsed_s": round(time.monotonic() - self._started_at, 3),
        }

    def _month_cacheable(self, month: str) -> bool:
        return month_is_cacheable(month, self._utc_today())

    def _cache_identity(self, dataset: str, month: str) -> dict[str, Any]:
        route = self._route(dataset)
        first = f"{month}-01"
        start = max(first, route.earliest)
        return cache_identity_document(
            environment=self.environment,
            dataset_id=dataset,
            segment_id=month,
            segment_start=start,
            segment_end=_month_end(month),
            route_path=route.path,
            route_mode=route.mode,
            source_capability_digest=route.source_capability_digest,
            dataset_contract_digest=route.dataset_contract_digest,
            coverage_policy_digest=route.coverage_policy_digest,
            query_contract_digest=route.query_contract_digest,
            target_registry_digest=self._registry.digest,
        )

    def _cache_key(self, dataset: str, month: str, identity: Mapping[str, Any]) -> str:
        return cache_object_key(
            environment=self.environment,
            dataset=dataset,
            month=month,
            identity_hex=cache_identity_hex(identity),
        )

    def _r2_urlopen(self, request: urllib.request.Request, *, timeout: int) -> Any:
        opener = self._r2_opener
        if opener is None:
            raise AcquisitionCacheUnavailable("acquisition cache opener is not configured")
        return opener.urlopen(request, timeout=timeout)

    def _classify_cache_http_error(self, error: urllib.error.HTTPError) -> None:
        code = int(error.code)
        _close_http_error(error)
        if code == 404:
            raise AcquisitionCacheMiss(f"acquisition cache HTTP {code}")
        if code in {502, 503, 504} or code >= 500:
            raise AcquisitionCacheUnavailable(f"acquisition cache HTTP {code}")
        raise AcquisitionCacheInvalid(f"acquisition cache HTTP {code}")

    def _download_cache_gzip(self, key: str) -> tuple[bytes, Mapping[str, str]]:
        request = build_cache_get_request(key, origin=self.r2_origin)
        try:
            with self._r2_urlopen(request, timeout=CACHE_GET_TIMEOUT_S) as response:
                status = int(response.status)
                headers = {name.lower(): value for name, value in response.headers.items()}
                body = response.read(CACHE_GZIP_MAX_BYTES + 1)
        except urllib.error.HTTPError as error:
            self._classify_cache_http_error(error)
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AcquisitionCacheUnavailable("acquisition cache transport failed") from error
        if status == 404:
            raise AcquisitionCacheMiss("acquisition cache HTTP 404")
        if status in {502, 503, 504} or status >= 500:
            raise AcquisitionCacheUnavailable(f"acquisition cache HTTP {status}")
        if status != 200:
            raise AcquisitionCacheInvalid(f"acquisition cache HTTP {status}")
        if len(body) < 1 or len(body) > CACHE_GZIP_MAX_BYTES:
            raise AcquisitionCacheInvalid("cache gzip exceeds the bound")
        return body, headers

    def _load_month_from_cache(self, dataset: str, month: str) -> bool:
        if self._r2_opener is None or not self._month_cacheable(month):
            return False
        identity = self._cache_identity(dataset, month)
        identity_hex = cache_identity_hex(identity)
        key = self._cache_key(dataset, month, identity)
        try:
            body, headers = self._download_cache_gzip(key)
        except AcquisitionCacheMiss:
            self.cache_misses += 1
            return False
        except AcquisitionCacheUnavailable:
            self.cache_unavailable += 1
            return False
        _content_digest, raw_declared = require_cache_get_contract(headers, body)
        work = Path(self.spool.path).parent
        sqlite_path = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f"acq-cache-{dataset}-{month}-",
                suffix=".sqlite",
                dir=work,
                delete=False,
            ) as handle:
                sqlite_path = Path(handle.name)
            gunzip_to_path(body, sqlite_path)
            raw_hasher = hashlib.sha256()
            with sqlite_path.open("rb") as sqlite_handle:
                for chunk in iter(lambda: sqlite_handle.read(1024 * 1024), b""):
                    raw_hasher.update(chunk)
            raw_actual = "sha256:" + raw_hasher.hexdigest()
            if raw_declared != raw_actual:
                raise AcquisitionCacheInvalid("cache raw digest does not match sqlite")
            cached = verify_month_shard(
                sqlite_path,
                expected_identity=identity,
                expected_identity_hex=identity_hex,
            )
            if cached.dataset != dataset or cached.month != month:
                raise AcquisitionCacheInvalid("cache month does not match request")
            self.spool.import_complete_month(cached)
        finally:
            if sqlite_path is not None:
                sqlite_path.unlink(missing_ok=True)
        verified = self.spool._cached_verified_month(dataset, month)
        if verified is None:
            raise AcquisitionCacheInvalid(
                f"{dataset} {month} cache import failed verified COMPLETE validation"
            )
        self.cache_hits += 1
        return True

    def _publish_month_cache(self, dataset: str, month: str) -> None:
        if self._r2_opener is None or not self._month_cacheable(month):
            return
        pages = self.spool._cached_verified_month(dataset, month)
        if pages is None:
            raise PersonalHistoryError(
                f"{dataset} {month} is not a verified COMPLETE month"
            )
        identity = self._cache_identity(dataset, month)
        identity_hex = cache_identity_hex(identity)
        key = self._cache_key(dataset, month, identity)
        work = Path(self.spool.path).parent
        sqlite_path = work / f"acq-cache-publish-{dataset}-{month}.sqlite"
        try:
            raw_digest = write_month_shard(
                self.spool._conn,
                sqlite_path,
                identity=identity,
            )
            verified = verify_month_shard(
                sqlite_path,
                expected_identity=identity,
                expected_identity_hex=identity_hex,
            )
            if verified.completion_digest != month_completion_digest(pages):
                raise AcquisitionCacheInvalid("cache shard completion digest drifted")
            blob = gzip_bytes(sqlite_path)
            content_digest = "sha256:" + hashlib.sha256(blob).hexdigest()
            request = build_cache_put_request(
                key,
                blob,
                content_digest=content_digest,
                raw_digest=raw_digest,
                origin=self.r2_origin,
            )
            try:
                with self._r2_urlopen(request, timeout=CACHE_PUT_TIMEOUT_S) as response:
                    status = int(response.status)
                    response.read()
            except urllib.error.HTTPError as error:
                code = int(error.code)
                _close_http_error(error)
                if code == 409:
                    raise AcquisitionCacheConflict(
                        f"{dataset} {month} immutable acquisition cache conflict"
                    ) from error
                if code in {502, 503, 504} or code >= 500:
                    raise AcquisitionCacheUnavailable(
                        f"acquisition cache PUT HTTP {code}"
                    ) from error
                raise AcquisitionCacheInvalid(
                    f"acquisition cache PUT HTTP {code}"
                ) from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise AcquisitionCacheUnavailable(
                    "acquisition cache PUT transport failed"
                ) from error
            if status in {200, 201}:
                self.cache_published += 1
                return
            if status == 409:
                raise AcquisitionCacheConflict(
                    f"{dataset} {month} immutable acquisition cache conflict"
                )
            if status in {502, 503, 504} or status >= 500:
                raise AcquisitionCacheUnavailable(f"acquisition cache PUT HTTP {status}")
            raise AcquisitionCacheInvalid(f"acquisition cache PUT HTTP {status}")
        finally:
            sqlite_path.unlink(missing_ok=True)
            Path(str(sqlite_path) + "-wal").unlink(missing_ok=True)
            Path(str(sqlite_path) + "-shm").unlink(missing_ok=True)

    def _ensure_month(self, dataset: str, month: str) -> None:
        if self.spool._cached_verified_month(dataset, month) is not None:
            return
        # Partial, forged, or truncated months are not selection evidence.
        self.spool.clear_month(dataset, month)
        if self._load_month_from_cache(dataset, month):
            self._refresh_progress()
            return
        route = self._route(dataset)
        continuation: str | None = None
        identity: dict[str, Any] | None = None
        ordinal = 0
        first = self._governed_request(dataset, month, None, None)
        identity = {
            key: value
            for key, value in first.items()
            if key != "continuation_token"
        }
        self.spool.begin_month(dataset, month, identity)
        recorded: list[SourcePage] = []
        for _ in range(_MAX_PAGES_PER_MONTH):
            request = self._governed_request(dataset, month, continuation, identity)
            self.fetch_calls += 1
            self._live_bodies += 1
            try:
                body, headers, status = self._post(request)
                evidence_state = headers.get("x-quant-acquisition-evidence-state", "")
                if status != 200 or evidence_state not in {"RAW_PAGE", "RAW_ONLY"}:
                    raise PersonalHistoryError(
                        f"{dataset} {month} acquisition was not RAW_PAGE"
                    )
                slice_date = headers.get("x-quant-acquisition-slice-date")
                if slice_date == "NONE":
                    slice_date = None
                if route.mode == "calendar_month_range":
                    query_params = {
                        "from": request["segment_start"],
                        "to": request["segment_end"],
                    }
                else:
                    query_params = {"date": slice_date or request["segment_start"]}
                pagination_out = headers.get("x-quant-acquisition-continuation")
                if pagination_out == "NONE":
                    pagination_out = None
                digest = "sha256:" + hashlib.sha256(body).hexdigest()
                rows = _records(json.loads(body.decode("utf-8")))
                self.spool.record_page(
                    dataset=dataset,
                    month=month,
                    page_ordinal=ordinal,
                    slice_date=slice_date,
                    body_digest=digest,
                    row_count=len(rows),
                    request_path=route.path,
                    request_params=query_params,
                    response_status=status,
                    pagination_in=continuation,
                    pagination_out=pagination_out,
                    evidence_state=evidence_state,
                    rows=rows,
                )
                recorded.append(
                    SourcePage(
                        request_path=route.path,
                        request_params=MappingProxyType(dict(query_params)),
                        response_status=status,
                        body_digest=digest,
                        row_count=len(rows),
                        pagination_in=continuation,
                        pagination_out=pagination_out,
                        evidence_state=evidence_state,
                        slice_date=slice_date,
                    )
                )
            finally:
                self._live_bodies -= 1
                body = b""
                rows = []
            pagination_state = headers.get("x-quant-acquisition-pagination-state")
            if pagination_state == "EXHAUSTED":
                self._finish_month(dataset, month, recorded)
                self._refresh_progress()
                return
            if pagination_state != "CONTINUATION" or not pagination_out:
                raise PersonalHistoryError(
                    f"{dataset} {month} pagination evidence is incomplete"
                )
            continuation = pagination_out
            ordinal += 1
        raise PersonalHistoryError(f"{dataset} {month} exceeded page bound")

    def _finish_month(
        self, dataset: str, month: str, pages: Sequence[SourcePage]
    ) -> None:
        self.spool.complete_month(
            dataset,
            month,
            page_count=len(pages),
            completion_digest=month_completion_digest(pages),
        )
        try:
            self._publish_month_cache(dataset, month)
        except AcquisitionCacheUnavailable:
            self.cache_unavailable += 1
        except AcquisitionCacheConflict:
            raise
        except AcquisitionCacheInvalid:
            raise

    def _selection(
        self,
        dataset: str,
        query: Mapping[str, Any],
        months: Sequence[str],
        *,
        row_date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        code: str | None = None,
    ) -> _Fetch:
        selected, contributing, pages, source_row_count = self.spool.select_rows(
            dataset,
            months,
            row_date=row_date,
            date_from=date_from,
            date_to=date_to,
            code=code,
        )
        if not pages:
            raise PersonalHistoryError(
                f"{dataset} has no COMPLETE scanned source pages for the query"
            )
        scanned = tuple(page.body_digest for page in pages)
        selection = SelectionEvidence(
            query=MappingProxyType(dict(query)),
            selected_row_count=len(selected),
            selected_digest=_canonical_digest(selected),
            source_row_count=source_row_count,
            scanned_page_digests=scanned,
            completion_digest=selection_completion_digest(
                scanned_page_digests=scanned,
                source_row_count=source_row_count,
            ),
            contributing_page_digests=contributing,
        )
        return _Fetch(tuple(selected), pages, selection)

    def _day_selection(self, dataset: str, day: str) -> _Fetch:
        month = _month_of(day)
        self._ensure_month(dataset, month)
        return self._selection(dataset, {"date": day}, [month], row_date=day)

    def _calendar(self, start: str, end: str) -> _Fetch:
        months = _iter_months(start, end)
        for month in months:
            self._ensure_month("markets_calendar", month)
        return self._selection(
            "markets_calendar",
            {"from": start, "to": end},
            months,
            date_from=start,
            date_to=end,
        )

    def _fins_code(self, code: str) -> _Fetch:
        # Official-earliest scan is required for PIT completeness. Reuse of a
        # layered financial seed is a later optimization, not a completeness
        # shortcut.
        route = self._route("fins_summary")
        months = _iter_months(route.earliest, self.period_end)
        for month in months:
            self._ensure_month("fins_summary", month)
        return self._selection("fins_summary", {"code": code}, months, code=code)
