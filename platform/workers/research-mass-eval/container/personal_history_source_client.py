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
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse
import urllib.error
import urllib.request

from data_contracts.identity import canonical_json
from ingestion.jquants import acquisition_collection as acquisition
from ingestion.personal_history import PERSONAL_HISTORY_DATASETS, PersonalHistoryError

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
_MAX_PAGES = 8192
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


def closed_history_source_headers(*, content_length: int, host: str) -> dict[str, str]:
    if not isinstance(content_length, int) or content_length < 1:
        raise PersonalHistoryError("history.source content-length is invalid")
    return {
        **HISTORY_SOURCE_FIXED_HEADERS,
        "content-length": str(content_length),
        "host": host,
    }


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
    contributing_page_digests: tuple[str, ...]


@dataclass(frozen=True)
class _Fetch:
    rows: tuple[dict[str, Any], ...]
    pages: tuple[SourcePage, ...]
    selection: SelectionEvidence | None = None


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
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def has_month(self, dataset: str, month: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM source_pages WHERE dataset=? AND month=? LIMIT 1",
            (dataset, month),
        ).fetchone()
        return row is not None

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
                        canonical_json(dict(row)),
                    ),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

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
        rows = self._conn.execute(
            """
            SELECT body_digest, row_count, request_path, request_params_json,
                   response_status, pagination_in, pagination_out,
                   evidence_state, slice_date
            FROM source_pages
            WHERE dataset=? AND month=?
            ORDER BY page_ordinal
            """,
            (dataset, month),
        ).fetchall()
        return tuple(self._page_from_row(row) for row in rows)

    def pages_for_slice(self, dataset: str, slice_date: str) -> tuple[SourcePage, ...]:
        rows = self._conn.execute(
            """
            SELECT body_digest, row_count, request_path, request_params_json,
                   response_status, pagination_in, pagination_out,
                   evidence_state, slice_date
            FROM source_pages
            WHERE dataset=? AND slice_date=?
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
            WHERE dataset=? AND body_digest IN ({placeholders})
            ORDER BY month, page_ordinal
            """,
            (dataset, *digests),
        ).fetchall()
        return tuple(self._page_from_row(row) for row in rows)

    def select_rows(
        self,
        dataset: str,
        *,
        row_date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        code: str | None = None,
    ) -> tuple[list[dict[str, Any]], tuple[str, ...], int]:
        clauses = ["dataset=?"]
        params: list[Any] = [dataset]
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
            WHERE {where}
            ORDER BY month, page_ordinal, row_index
            """,
            params,
        ).fetchall()
        selected = [json.loads(row["row_json"]) for row in rows]
        contributing = tuple(dict.fromkeys(str(row["body_digest"]) for row in rows))
        source_count = int(
            self._conn.execute(
                "SELECT COALESCE(SUM(row_count),0) FROM source_pages WHERE dataset=?",
                (dataset,),
            ).fetchone()[0]
        )
        if row_date is not None or date_from is not None or date_to is not None or code is not None:
            # Source count for selection proof is the contributing pages' rows,
            # not the entire dataset history.
            if contributing:
                placeholders = ",".join("?" for _ in contributing)
                source_count = int(
                    self._conn.execute(
                        f"""
                        SELECT COALESCE(SUM(row_count),0) FROM source_pages
                        WHERE dataset=? AND body_digest IN ({placeholders})
                        """,
                        (dataset, *contributing),
                    ).fetchone()[0]
                )
            else:
                source_count = 0
        return selected, contributing, source_count


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
    ) -> None:
        if environment not in {"production", "staging"}:
            raise PersonalHistoryError("acquisition environment is invalid")
        self.environment = environment
        self.period_end = period_end
        self.origin = origin.rstrip("/")
        self._opener = opener
        self._registry = acquisition._target_registry()
        self.spool = AcquisitionSpool(spool_path)
        self.fetch_calls = 0
        self._live_bodies = 0

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
        try:
            with opener.urlopen(request, timeout=120) as response:
                raw = response.read()
                headers = {key.lower(): value for key, value in response.headers.items()}
                return raw, headers, int(response.status)
        except urllib.error.HTTPError as error:
            raise PersonalHistoryError(
                f"history.source returned HTTP {error.code}"
            ) from error

    def _ensure_month(self, dataset: str, month: str) -> None:
        if self.spool.has_month(dataset, month):
            return
        route = self._route(dataset)
        continuation: str | None = None
        identity: dict[str, Any] | None = None
        ordinal = 0
        for _ in range(_MAX_PAGES):
            request = self._governed_request(dataset, month, continuation, identity)
            if identity is None:
                identity = {
                    key: value
                    for key, value in request.items()
                    if key != "continuation_token"
                }
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
            finally:
                self._live_bodies -= 1
                body = b""
                rows = []
            pagination_state = headers.get("x-quant-acquisition-pagination-state")
            if pagination_state == "EXHAUSTED":
                return
            if pagination_state != "CONTINUATION" or not pagination_out:
                raise PersonalHistoryError(
                    f"{dataset} {month} pagination evidence is incomplete"
                )
            continuation = pagination_out
            ordinal += 1
        raise PersonalHistoryError(f"{dataset} {month} exceeded page bound")

    def _selection(
        self,
        dataset: str,
        query: Mapping[str, Any],
        *,
        row_date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        code: str | None = None,
    ) -> _Fetch:
        selected, contributing, source_row_count = self.spool.select_rows(
            dataset,
            row_date=row_date,
            date_from=date_from,
            date_to=date_to,
            code=code,
        )
        pages = self.spool.contributing_pages(dataset, digests=contributing)
        selection = SelectionEvidence(
            query=MappingProxyType(dict(query)),
            selected_row_count=len(selected),
            selected_digest=_canonical_digest(selected),
            source_row_count=source_row_count,
            contributing_page_digests=contributing,
        )
        return _Fetch(tuple(selected), pages, selection)

    def _day_selection(self, dataset: str, day: str) -> _Fetch:
        self._ensure_month(dataset, _month_of(day))
        fetched = self._selection(dataset, {"date": day}, row_date=day)
        if fetched.pages:
            return fetched
        slice_pages = self.spool.pages_for_slice(dataset, day)
        if not slice_pages:
            raise PersonalHistoryError(
                f"{dataset} has no governed source page for {day}"
            )
        selection = SelectionEvidence(
            query=MappingProxyType({"date": day}),
            selected_row_count=0,
            selected_digest=_canonical_digest([]),
            source_row_count=sum(page.row_count for page in slice_pages),
            contributing_page_digests=tuple(page.body_digest for page in slice_pages),
        )
        return _Fetch((), slice_pages, selection)

    def _calendar(self, start: str, end: str) -> _Fetch:
        for month in _iter_months(start, end):
            self._ensure_month("markets_calendar", month)
        fetched = self._selection(
            "markets_calendar",
            {"from": start, "to": end},
            date_from=start,
            date_to=end,
        )
        if not fetched.pages:
            raise PersonalHistoryError(
                "markets_calendar has no governed source page for the requested window"
            )
        return fetched

    def _fins_code(self, code: str) -> _Fetch:
        route = self._route("fins_summary")
        for month in _iter_months(route.earliest, self.period_end):
            self._ensure_month("fins_summary", month)
        return self._selection("fins_summary", {"code": code}, code=code)
