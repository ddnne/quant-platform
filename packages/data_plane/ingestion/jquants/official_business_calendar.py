"""Strict official J-Quants business-calendar derivation.

The equities master endpoint resolves non-business ``date`` values forward.
Consequently a calendar-day loop can silently mix a later segment into the
month being proved.  This module accepts only the exact V2 market-calendar
wire response, proves that it enumerates every requested calendar day, and
derives the TSE business-day slices from ``HolDiv``.

``HolDiv`` values 1 (business day) and 2 (TSE half-day session) are eligible
equities-master dates.  Values 0 and 3 are non-business days for TSE equities.
No weekday or locally maintained holiday approximation is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping


_CALENDAR_SCHEMA = "jquants-official-business-calendar/v1"
_DATES_SCHEMA = "jquants-official-business-dates/v1"
_BINDING_SCHEMA = "jquants-official-business-calendar-binding/v1"
_CALENDAR_PATH = "/v2/markets/calendar"
_TSE_BUSINESS_DIVISIONS = frozenset({"1", "2"})
_HOLIDAY_DIVISIONS = frozenset({"0", "1", "2", "3"})


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"official calendar contains duplicate JSON key: {key}")
        result[key] = value
    return result


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    return _digest_bytes(_canonical_bytes(value))


def _parse_date(value: Any, *, label: str) -> date:
    if type(value) is not str or len(value) != 10:
        raise ValueError(f"{label} must be an ISO calendar date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO calendar date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must be a canonical ISO calendar date")
    return parsed


@dataclass(frozen=True)
class OfficialBusinessCalendar:
    """Receipt-side measurement of one exact official calendar response."""

    segment_start: str
    segment_end: str
    raw_body_digest: str
    calendar_query_digest: str
    business_dates_digest: str
    binding_digest: str
    business_dates: tuple[str, ...]
    rows_by_date: Mapping[str, str]


def derive_official_business_calendar(
    raw: bytes,
    *,
    segment_start: str,
    segment_end: str,
) -> OfficialBusinessCalendar:
    """Parse exact official bytes and derive the bounded master slice list.

    The response must contain exactly one row for every calendar date in the
    requested interval, in ascending order.  This proves both range exhaustion
    and that weekends/holidays were not silently omitted or synthesized.
    """

    if type(raw) is not bytes or not raw:
        raise TypeError("official calendar raw body must be non-empty bytes")
    start = _parse_date(segment_start, label="calendar segment_start")
    end = _parse_date(segment_end, label="calendar segment_end")
    if start > end:
        raise ValueError("official calendar range is empty")
    try:
        text = raw.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"non-finite official calendar value: {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("official calendar body is not strict UTF-8 JSON") from exc
    if type(document) is not dict or set(document) != {"data"}:
        raise ValueError("official calendar response must contain only data")
    rows = document["data"]
    if type(rows) is not list:
        raise ValueError("official calendar data must be an array")

    expected_count = (end - start).days + 1
    if len(rows) != expected_count:
        raise ValueError("official calendar does not enumerate the complete range")
    divisions: dict[str, str] = {}
    business_dates: list[str] = []
    for ordinal, row in enumerate(rows):
        if type(row) is not dict or set(row) != {"Date", "HolDiv"}:
            raise ValueError("official calendar row has an unexpected schema")
        expected_date = (start + timedelta(days=ordinal)).isoformat()
        observed_date = row["Date"]
        division = row["HolDiv"]
        if observed_date != expected_date:
            raise ValueError(
                "official calendar dates are missing, duplicate, reordered, or out of range"
            )
        if type(division) is not str or division not in _HOLIDAY_DIVISIONS:
            raise ValueError("official calendar HolDiv is outside the reviewed domain")
        divisions[expected_date] = division
        if division in _TSE_BUSINESS_DIVISIONS:
            business_dates.append(expected_date)
    if not business_dates:
        raise ValueError("official calendar range contains no TSE business day")

    raw_digest = _digest_bytes(raw)
    ordered_query = [["from", segment_start], ["to", segment_end]]
    query_digest = _digest(
        {
            "schema_version": "jquants-acquisition-query/v2",
            "path": _CALENDAR_PATH,
            "ordered_query": ordered_query,
        }
    )
    dates = tuple(business_dates)
    dates_digest = _digest(
        {
            "schema_version": _DATES_SCHEMA,
            "segment_start": segment_start,
            "segment_end": segment_end,
            "dates": list(dates),
        }
    )
    binding_digest = _digest(
        {
            "schema_version": _BINDING_SCHEMA,
            "path": _CALENDAR_PATH,
            "ordered_query": ordered_query,
            "raw_body_digest": raw_digest,
            "calendar_query_digest": query_digest,
            "business_dates_digest": dates_digest,
            "business_dates": list(dates),
        }
    )
    return OfficialBusinessCalendar(
        segment_start=segment_start,
        segment_end=segment_end,
        raw_body_digest=raw_digest,
        calendar_query_digest=query_digest,
        business_dates_digest=dates_digest,
        binding_digest=binding_digest,
        business_dates=dates,
        rows_by_date=MappingProxyType(divisions),
    )


def master_query_digest(
    *,
    path: str,
    slice_date: str,
    provider_cursor: str | None,
    calendar: OfficialBusinessCalendar,
) -> str:
    """Bind one master provider query to the independently measured calendar."""

    if path != "/v2/equities/master":
        raise ValueError("official calendar binding is only valid for equities_master")
    if slice_date not in calendar.business_dates:
        raise ValueError("master slice is not an official TSE business date")
    ordered_query: list[list[str]] = [["date", slice_date]]
    if provider_cursor is not None:
        if type(provider_cursor) is not str or not provider_cursor:
            raise ValueError("provider cursor must be a non-empty string")
        ordered_query.append(["pagination_key", provider_cursor])
    return _digest(
        {
            "schema_version": "jquants-acquisition-query/v3",
            "path": path,
            "ordered_query": ordered_query,
            "official_calendar_binding": {
                "binding_digest": calendar.binding_digest,
                "raw_body_digest": calendar.raw_body_digest,
                "calendar_query_digest": calendar.calendar_query_digest,
                "business_dates_digest": calendar.business_dates_digest,
                "business_dates": list(calendar.business_dates),
            },
        }
    )
