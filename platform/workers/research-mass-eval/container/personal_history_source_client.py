"""Closed personal-history client over the Container history.source host.

The adapter implements ``fetch_dataset_evidenced`` for PersonalHistoryHydrator
by posting the existing J-Quants acquisition RPC request shape.  It does not
claim receipts, Coverage, or READY.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
import json
import secrets
from types import MappingProxyType
from typing import Any, Mapping
import urllib.error
import urllib.request

from ingestion.jquants import acquisition_collection as acquisition
from ingestion.personal_history import PERSONAL_HISTORY_DATASETS, PersonalHistoryError

HISTORY_SOURCE_ORIGIN = "http://history.source"
_FETCH_PATH = "/v1/fetch-governed-page"
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


@dataclass(frozen=True)
class _Page:
    request_path: str
    request_params: Mapping[str, Any]
    response_status: int
    response_body: bytes
    pagination_in: str | None = None
    pagination_out: str | None = None


@dataclass(frozen=True)
class _Fetch:
    rows: tuple[dict[str, Any], ...]
    pages: tuple[_Page, ...]


class PersonalHistorySourceClient:
    """Hydrator client that may only call the four personal history datasets."""

    def __init__(
        self,
        *,
        environment: str,
        period_end: str,
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
        self._month_cache: dict[tuple[str, str], tuple[_Page, ...]] = {}

    def fetch_dataset_evidenced(self, dataset: str, **params: Any) -> _Fetch:
        if dataset not in PERSONAL_HISTORY_DATASETS:
            raise PersonalHistoryError(f"{dataset} is not a personal history dataset")
        if dataset == "markets_calendar":
            return self._calendar(str(params["from"]), str(params["to"]))
        if dataset == "equities_master":
            return self._day_pages(dataset, str(params["date"]))
        if dataset == "equities_bars_daily":
            return self._day_pages(dataset, str(params["date"]))
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
    ) -> dict[str, Any]:
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
        request = urllib.request.Request(
            f"{self.origin}{_FETCH_PATH}",
            data=body,
            method="POST",
            headers={
                "content-type": "application/json; charset=utf-8",
                "content-length": str(len(body)),
                "accept": "application/json",
            },
        )
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

    def _month_pages(self, dataset: str, month: str) -> tuple[_Page, ...]:
        cached = self._month_cache.get((dataset, month))
        if cached is not None:
            return cached
        route = self._route(dataset)
        pages: list[_Page] = []
        continuation: str | None = None
        identity_nonce_request: dict[str, Any] | None = None
        for _ in range(_MAX_PAGES):
            if identity_nonce_request is None:
                request = self._governed_request(dataset, month, None)
                identity_nonce_request = {
                    key: value
                    for key, value in request.items()
                    if key != "continuation_token"
                }
            else:
                request = {
                    **identity_nonce_request,
                    "continuation_token": continuation,
                }
            body, headers, status = self._post(request)
            evidence_state = headers.get("x-quant-acquisition-evidence-state", "")
            if status != 200 or evidence_state not in {"RAW_PAGE", "RAW_ONLY"}:
                raise PersonalHistoryError(
                    f"{dataset} {month} acquisition was not RAW_PAGE"
                )
            slice_date = headers.get("x-quant-acquisition-slice-date")
            if slice_date == "NONE":
                slice_date = None
            query_params: dict[str, Any]
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
            pages.append(
                _Page(
                    request_path=route.path,
                    request_params=MappingProxyType(query_params),
                    response_status=status,
                    response_body=bytes(body),
                    pagination_in=continuation,
                    pagination_out=pagination_out,
                )
            )
            pagination_state = headers.get("x-quant-acquisition-pagination-state")
            if pagination_state == "EXHAUSTED":
                break
            if pagination_state != "CONTINUATION" or not pagination_out:
                raise PersonalHistoryError(
                    f"{dataset} {month} pagination evidence is incomplete"
                )
            continuation = pagination_out
        else:
            raise PersonalHistoryError(f"{dataset} {month} exceeded page bound")
        stored = tuple(pages)
        self._month_cache[(dataset, month)] = stored
        return stored

    def _day_pages(self, dataset: str, day: str) -> _Fetch:
        pages = [
            page
            for page in self._month_pages(dataset, _month_of(day))
            if page.request_params.get("date") == day
        ]
        if not pages:
            empty = json.dumps({"data": []}, separators=(",", ":")).encode("utf-8")
            pages = [
                _Page(
                    request_path=self._route(dataset).path,
                    request_params=MappingProxyType({"date": day}),
                    response_status=200,
                    response_body=empty,
                )
            ]
        rows: list[dict[str, Any]] = []
        for page in pages:
            rows.extend(_records(json.loads(page.response_body.decode("utf-8"))))
        return _Fetch(tuple(rows), tuple(pages))

    def _calendar(self, start: str, end: str) -> _Fetch:
        kept: list[dict[str, Any]] = []
        for month in _iter_months(start, end):
            for page in self._month_pages("markets_calendar", month):
                for row in _records(json.loads(page.response_body.decode("utf-8"))):
                    day = _row_date(row)
                    if day is not None and start <= day <= end:
                        kept.append(row)
        body = json.dumps({"data": kept}, separators=(",", ":")).encode("utf-8")
        page = _Page(
            request_path=self._route("markets_calendar").path,
            request_params=MappingProxyType({"from": start, "to": end}),
            response_status=200,
            response_body=body,
        )
        return _Fetch(tuple(kept), (page,))

    def _fins_code(self, code: str) -> _Fetch:
        route = self._route("fins_summary")
        kept: list[dict[str, Any]] = []
        for month in _iter_months(route.earliest, self.period_end):
            for page in self._month_pages("fins_summary", month):
                for row in _records(json.loads(page.response_body.decode("utf-8"))):
                    if str(row.get("Code") or "").strip() == code:
                        kept.append(row)
        body = json.dumps({"data": kept}, separators=(",", ":")).encode("utf-8")
        page = _Page(
            request_path=route.path,
            request_params=MappingProxyType({"code": code}),
            response_status=200,
            response_body=body,
        )
        return _Fetch(tuple(kept), (page,))
