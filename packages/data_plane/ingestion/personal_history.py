"""Bounded, resumable J-Quants history for one person's DRAFT research.

This is deliberately not an ingestion authority.  It stores compact PIT rows
and request-page digests in a dedicated local SQLite file, but never issues a
receipt, updates Coverage/READY, or claims that an observed window is complete.

The master history needs special care.  The historical endpoint can return a
dated snapshot but cannot reconstruct when a later correction was originally
published.  Personal research therefore uses the explicit approximation
``Date=D -> available_at=D 08:00 JST``.  That approximation is recorded on
every checkpoint and is forbidden as controlled/live evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

from data_contracts.identity import canonical_json, session_close_jst
from data_contracts.personal_history_compact import (
    PERSONAL_HISTORY_COMPACT_CREATE_SQL,
    PERSONAL_HISTORY_COMPACT_FORMAT,
    PERSONAL_HISTORY_COMPACT_TABLES,
)
from data_contracts.personal_universe import (
    PERSONAL_HISTORY_SCOPE_DIGEST,
    PERSONAL_HISTORY_SCOPE_ID,
    PERSONAL_HISTORY_SCOPE_VERSION,
    canonical_topix_scale_category,
)
from data_contracts.source_capability import source_capability_contract_for

from .common.timeutil import JST, now_iso, parse_dt, to_iso
from .jquants import normalize as JN
from .pipeline import _assert_personal_draft_store_is_unmanaged


PERSONAL_HISTORY_DATASETS: tuple[str, ...] = (
    "markets_calendar",
    "equities_master",
    "fins_summary",
    "equities_bars_daily",
)


def _official_availability(dataset: str) -> str:
    return source_capability_contract_for(dataset).earliest_official_availability


def personal_snapshot_data_floor() -> str:
    """Earliest day a personal snapshot can hydrate bars.

    The floor is the latest ``earliest_official_availability`` among the
    compact-v7 source contracts. It is not a hardcoded calendar date.
    """

    return max(_official_availability(dataset) for dataset in PERSONAL_HISTORY_DATASETS)


PERSONAL_HISTORY_FORMAT = PERSONAL_HISTORY_COMPACT_FORMAT
PERSONAL_RESEARCH_STATE = "PERSONAL_DRAFT"
PERSONAL_COMPLETENESS_CLAIM = "NONE"
PERSONAL_CONTROLLED_ELIGIBILITY = "FORBIDDEN"
MASTER_AVAILABILITY_POLICY = "scheduled_snapshot_approximation/date_08:00_jst/v1"
CALENDAR_AVAILABILITY_POLICY = "historical_calendar_event_time/v1"
FINS_AVAILABILITY_POLICY = (
    "explicit_disc_timestamp_else_next_calendar_day_00:00_jst/v1"
)
BARS_AVAILABILITY_POLICY = "canonical_session_close/v1"
DEFAULT_LOOKBACK_SESSIONS = 10
DEFAULT_CALENDAR_WINDOW_DAYS = 180
DEFAULT_TOPIX_CODE_ESTIMATE = 2_200
DEFAULT_MIN_OBSERVED_BAR_RATIO = 0.995
DEFAULT_MAX_DATABASE_BYTES = 5 * 1024**3
DEFAULT_MINIMUM_FREE_BYTES = 8 * 1024**3
DEFAULT_WAL_CHECKPOINT_SEGMENTS = 25
# Compact WITHOUT ROWID rows plus SQLite page/index/snapshot headroom.
DEFAULT_COMPACT_STORAGE_BYTES_PER_ROW = 256
# Calendar and fins stay generic JSON; this is a conservative page/index bound.
DEFAULT_GENERIC_JSON_STORAGE_BYTES_PER_ROW = 1024
_TERMINAL_STATES = frozenset({"OBSERVED", "OBSERVED_EMPTY"})
_RETRYABLE_STATES = frozenset({"RUNNING", "FAILED"})
_TYPED_JQUANTS_TABLES: tuple[str, ...] = (
    "jquants_listed_info",
    "jquants_daily_bars",
    "jquants_market_calendar",
)


def _compact_table_builder_shape(
    connection: sqlite3.Connection, table: str
) -> tuple[Any, ...] | None:
    """Capture the compact-table contract CREATE TABLE IF NOT EXISTS can miss.

    Ordered columns, declared types, NOT NULL, composite PK ordinals, hidden
    or generated columns, and WITHOUT ROWID are compared exactly.  The helper
    is private to the trusted builder and is not a reader-side schema API.
    """

    if table not in PERSONAL_HISTORY_COMPACT_TABLES:
        raise PersonalHistoryError(
            f"personal history compact table {table} does not match builder DDL"
        )
    listing = connection.execute(
        "SELECT type, ncol, wr FROM pragma_table_list "
        "WHERE schema='main' AND name=?",
        (table,),
    ).fetchone()
    if listing is None:
        return None
    columns = tuple(
        (
            int(row[0]),
            str(row[1]),
            str(row[2]),
            int(row[3]),
            int(row[5]),
            int(row[6]),
        )
        for row in connection.execute(f"PRAGMA table_xinfo({table})")
    )
    return (str(listing[0]), int(listing[1]), int(listing[2]), columns)


class PersonalHistoryError(RuntimeError):
    """The personal history input or observed API response is unsafe."""


@dataclass(frozen=True, slots=True)
class PersonalHistoryPlan:
    period_start: str
    period_end: str
    calendar_start: str
    lookback_sessions: int
    calendar_window_days: int
    calendar_segments: int
    estimated_trading_sessions: int
    estimated_requests_lower_bound: int
    estimated_structured_rows: int
    estimated_bytes: int
    research_state: str = PERSONAL_RESEARCH_STATE
    completeness_claim: str = PERSONAL_COMPLETENESS_CLAIM
    controlled_live_eligibility: str = PERSONAL_CONTROLLED_ELIGIBILITY
    master_availability_policy: str = MASTER_AVAILABILITY_POLICY
    master_revision_pit: bool = False
    history_scope_id: str = PERSONAL_HISTORY_SCOPE_ID
    history_scope_version: str = PERSONAL_HISTORY_SCOPE_VERSION
    history_scope_digest: str = PERSONAL_HISTORY_SCOPE_DIGEST

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PersonalHistorySummary:
    period_start: str
    period_end: str
    bar_start: str
    segment_counts: Mapping[str, int]
    fetched_rows: int
    written_rows: int
    skipped_segments: int
    database_bytes: int
    actual_lookback_sessions: int
    lookback_truncated: bool
    research_state: str = PERSONAL_RESEARCH_STATE
    completeness_claim: str = PERSONAL_COMPLETENESS_CLAIM
    controlled_live_eligibility: str = PERSONAL_CONTROLLED_ELIGIBILITY
    master_availability_policy: str = MASTER_AVAILABILITY_POLICY
    master_revision_pit: bool = False
    history_scope_id: str = PERSONAL_HISTORY_SCOPE_ID
    history_scope_version: str = PERSONAL_HISTORY_SCOPE_VERSION
    history_scope_digest: str = PERSONAL_HISTORY_SCOPE_DIGEST
    status: str = "COMPLETE_DRAFT"

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["segment_counts"] = dict(self.segment_counts)
        body["warning"] = (
            "DRAFT observations only: no receipt, Coverage, READY, or source "
            "completeness claim; master correction publication time is not "
            "reconstructed"
        )
        return body


@dataclass(frozen=True, slots=True)
class _SegmentOutcome:
    dataset: str
    segment_id: str
    fetched: int
    written: int
    skipped: bool
    state: str
    membership_digest: str | None = None


def _parse_day(value: str, label: str) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise PersonalHistoryError(f"{label} must be an ISO date") from exc
    if parsed.isoformat() != str(value):
        raise PersonalHistoryError(f"{label} must be an ISO date")
    return parsed


def _iter_days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _membership_change_planning_allowance(estimated_sessions: int) -> int:
    """Snapshot-day allowance for compact master planning.

    ``ceil((estimated_sessions + 1) / 2)``, floored at 24, then capped to
    ``estimated_sessions + 1``. Labelled a planning allowance; physical
    guards remain authoritative.
    """

    return min(
        estimated_sessions + 1,
        max(24, math.ceil((estimated_sessions + 1) / 2)),
    )


def _iter_windows(start: date, end: date, days: int) -> Iterable[tuple[date, date]]:
    current = start
    step = timedelta(days=days)
    while current <= end:
        window_end = min(end, current + step - timedelta(days=1))
        yield current, window_end
        current = window_end + timedelta(days=1)


def build_personal_history_plan(
    *,
    period_start: str,
    period_end: str,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    calendar_window_days: int = DEFAULT_CALENDAR_WINDOW_DAYS,
    today: date | None = None,
) -> PersonalHistoryPlan:
    """Validate a requested research range and return a side-effect-free plan."""

    start = _parse_day(period_start, "period_start")
    end = _parse_day(period_end, "period_end")
    current = today or datetime.now(JST).date()
    if end < start:
        raise PersonalHistoryError("period_end is before period_start")
    if end > current:
        raise PersonalHistoryError("future history windows are not allowed")
    if isinstance(lookback_sessions, bool) or not 0 <= int(lookback_sessions) <= 252:
        raise PersonalHistoryError("lookback_sessions must be between 0 and 252")
    if (
        isinstance(calendar_window_days, bool)
        or not 7 <= int(calendar_window_days) <= 366
    ):
        raise PersonalHistoryError("calendar_window_days must be between 7 and 366")

    lookback = int(lookback_sessions)
    window_days = int(calendar_window_days)
    calendar_floor = date.fromisoformat(_official_availability("markets_calendar"))
    profile_floor = date.fromisoformat(personal_snapshot_data_floor())
    if end < profile_floor:
        raise PersonalHistoryError(
            "period_end is before the personal snapshot data floor"
        )
    # Same conservative conversion used by PersonalResearchService, plus two
    # weeks so the first requested master snapshot has an observed predecessor.
    # Calendar may start before the profile floor so a master seed on/after
    # the master contract floor remains observable.
    calendar_buffer = max(30, lookback * 2 + 30) + 14
    calendar_start = max(
        start - timedelta(days=calendar_buffer),
        calendar_floor,
    )
    effective_start = max(start, profile_floor)
    if start <= profile_floor:
        available_lookback = 0
    else:
        available_lookback = sum(
            1
            for day in _iter_days(profile_floor, start - timedelta(days=1))
            if day.weekday() < 5
        )
    planned_lookback = min(lookback, available_lookback)
    all_days = (end - effective_start).days + 1
    estimated_sessions = sum(
        1 for day in _iter_days(effective_start, end) if day.weekday() < 5
    )
    estimated_sessions += planned_lookback
    calendar_segments = sum(
        1 for _ in _iter_windows(calendar_start, end, window_days)
    )
    # calendar windows + daily master + daily fins + daily bars. Pagination is
    # intentionally not guessed, so this is labelled a lower bound.
    requests = calendar_segments + estimated_sessions * 2 + all_days
    bar_rows = estimated_sessions * DEFAULT_TOPIX_CODE_ESTIMATE
    # Period-dependent membership-change planning allowance for compact
    # master snapshots: half of estimated trading sessions, rounded up,
    # at least 24 days, and never more than sessions+1. This is a planning
    # allowance, not an exact or conservative proof of membership churn.
    # Physical max_page_count and file-size guards stay authoritative.
    # Calendar and fins remain generic JSON payloads rather than WITHOUT
    # ROWID facts.
    master_rows = DEFAULT_TOPIX_CODE_ESTIMATE * _membership_change_planning_allowance(
        estimated_sessions
    )
    generic_json_rows = all_days * 100
    estimated_rows = bar_rows + master_rows + generic_json_rows
    # Compact WITHOUT ROWID bar/master rows are planned at 256 bytes/row.
    # Calendar/fins generic JSON uses a separate 1024 byte/row estimate.
    # The physical max_page_count guard still enforces DEFAULT_MAX_DATABASE_BYTES.
    estimated_bytes = (
        (bar_rows + master_rows) * DEFAULT_COMPACT_STORAGE_BYTES_PER_ROW
        + generic_json_rows * DEFAULT_GENERIC_JSON_STORAGE_BYTES_PER_ROW
    )
    return PersonalHistoryPlan(
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        calendar_start=calendar_start.isoformat(),
        lookback_sessions=lookback,
        calendar_window_days=window_days,
        calendar_segments=calendar_segments,
        estimated_trading_sessions=estimated_sessions,
        estimated_requests_lower_bound=requests,
        estimated_structured_rows=estimated_rows,
        estimated_bytes=estimated_bytes,
    )


def assert_personal_history_database(db_path: Path, *, governed_default: Path) -> None:
    """Read-only preflight before :class:`SqliteStore` can run migrations."""

    target = Path(db_path).expanduser().resolve()
    if target == Path(governed_default).expanduser().resolve():
        raise PersonalHistoryError(
            "personal history refuses the governed ingestion.sqlite database"
        )
    if not target.exists():
        return
    uri = "file:" + quote(str(target), safe="/") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        _assert_personal_draft_store_is_unmanaged(
            SimpleNamespace(_conn=connection)
        )
    except ValueError as exc:
        raise PersonalHistoryError(str(exc)) from exc
    finally:
        connection.close()


def _pick(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and value != "":
            return value
    return None


def _canonical_digest(value: Any) -> str:
    payload = canonical_json(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _estimated_fact_write_bytes(rows: Sequence[Mapping[str, Any]]) -> int:
    """Conservative SQLite write estimate used by the size guard.

    Payload JSON dominates fins facts.  Page evidence stays on the
    acquisition spool and is not part of this estimate.
    """
    return sum(
        len(str(row.get("payload") or "").encode("utf-8")) + 400
        for row in rows
    ) * 3


def _page_row_count(body: bytes) -> int:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonalHistoryError("J-Quants page is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise PersonalHistoryError("J-Quants page envelope must be an object")
    for key in ("data", "info", "daily_bars", "calendar", "summary"):
        if key in payload:
            rows = payload[key]
            if not isinstance(rows, list):
                raise PersonalHistoryError(
                    f"J-Quants page field {key!r} must be a list"
                )
            return len(rows)
    return 0


def _page_digest_hex(value: Any) -> str:
    digest = str(value or "")
    if digest.startswith("sha256:"):
        digest = digest[7:]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise PersonalHistoryError("source page digest is missing")
    return digest


def _source_page_descriptor(ordinal: int, page: Any) -> dict[str, Any]:
    body = getattr(page, "response_body", None)
    stored_digest = getattr(page, "body_digest", None)
    if body is not None:
        raw = bytes(body)
        digest = hashlib.sha256(raw).hexdigest()
        if stored_digest is not None and _page_digest_hex(stored_digest) != digest:
            raise PersonalHistoryError("page body digest does not match bytes")
        row_count = _page_row_count(raw)
        declared = getattr(page, "row_count", None)
        if declared is not None and int(declared) != row_count:
            raise PersonalHistoryError("page row count does not match body")
    else:
        digest = _page_digest_hex(stored_digest)
        declared = getattr(page, "row_count", None)
        if declared is None or int(declared) < 0:
            raise PersonalHistoryError("source page row count is missing")
        row_count = int(declared)
    descriptor = {
        "ordinal": ordinal,
        "sha256": digest,
        "row_count": row_count,
        "request_path": str(page.request_path),
        "request_params": dict(page.request_params),
        "response_status": int(page.response_status),
        "pagination_in": page.pagination_in,
        "pagination_out": page.pagination_out,
    }
    evidence_state = getattr(page, "evidence_state", None)
    if evidence_state:
        descriptor["evidence_state"] = str(evidence_state)
    slice_date = getattr(page, "slice_date", None)
    if slice_date:
        descriptor["slice_date"] = str(slice_date)
    return descriptor


def _count_field(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return -1
    return value


def _selection_fields(selection: Any) -> Mapping[str, Any]:
    if isinstance(selection, Mapping):
        return selection
    query = getattr(selection, "query", None)
    if query is None:
        raise PersonalHistoryError("selection evidence is invalid")
    return {
        "query": query,
        "selected_row_count": getattr(selection, "selected_row_count", None),
        "selected_digest": getattr(selection, "selected_digest", None),
        "source_row_count": getattr(selection, "source_row_count", None),
        "scanned_page_digests": getattr(selection, "scanned_page_digests", ()),
        "completion_digest": getattr(selection, "completion_digest", None),
        "contributing_page_digests": getattr(selection, "contributing_page_digests", ()),
    }


def _validated_selection(
    selection: Mapping[str, Any],
    source_pages: Sequence[Mapping[str, Any]],
    selected_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    query = selection.get("query")
    if not isinstance(query, Mapping):
        raise PersonalHistoryError("selection query is missing")
    source_digests = tuple(str(page["sha256"]) for page in source_pages)
    source_digest_set = set(source_digests)
    scanned_raw = selection.get("scanned_page_digests")
    if scanned_raw is None:
        scanned = source_digests
    else:
        scanned = tuple(_page_digest_hex(item) for item in scanned_raw)
        if scanned != source_digests:
            raise PersonalHistoryError(
                "selection scanned pages do not match fetched source pages"
            )
    contributing = tuple(
        _page_digest_hex(item)
        for item in (selection.get("contributing_page_digests") or ())
    )
    if any(digest not in source_digest_set for digest in contributing):
        raise PersonalHistoryError("selection cites a page that was not fetched")
    selected_digest = _canonical_digest(list(selected_rows))
    declared_digest = str(selection.get("selected_digest") or "")
    if declared_digest.startswith("sha256:"):
        declared_hex = declared_digest[7:]
    else:
        declared_hex = declared_digest
    if declared_hex != selected_digest[7:]:
        raise PersonalHistoryError("selection digest does not match selected rows")
    selected_count = _count_field(selection.get("selected_row_count"))
    if selected_count != len(selected_rows):
        raise PersonalHistoryError("selection row count does not match selected rows")
    source_row_count = sum(int(page["row_count"]) for page in source_pages)
    declared_source = _count_field(selection.get("source_row_count"))
    if declared_source != source_row_count:
        raise PersonalHistoryError("selection source row count does not match pages")
    completion = str(selection.get("completion_digest") or "")
    expected_completion = _canonical_digest(
        {
            "scanned_page_digests": [f"sha256:{digest}" for digest in scanned],
            "source_row_count": source_row_count,
            "page_count": len(scanned),
            "status": "COMPLETE",
        }
    )
    if not completion or _page_digest_hex(completion) != _page_digest_hex(
        expected_completion
    ):
        raise PersonalHistoryError("selection completion digest does not match pages")
    return {
        "query": dict(query),
        "selected_row_count": selected_count,
        "selected_digest": selected_digest,
        "source_row_count": source_row_count,
        "scanned_page_digests": list(scanned),
        "completion_digest": expected_completion,
        "contributing_page_digests": list(contributing),
    }


_FINS_COMPACT_SELECTION_KEYS = frozenset(
    {
        "query",
        "selected_row_count",
        "selected_digest",
        "contributing_page_digests",
        "shared_scan_digest",
        "integrity_digest",
    }
)


def _shared_scan_fields(
    page_evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Independently derive the canonical fins source-scan record from pages."""

    pages = [dict(page) for page in page_evidence]
    if not pages:
        raise PersonalHistoryError("shared fins scan has no page evidence")
    scanned = [str(page["sha256"]) for page in pages]
    for digest in scanned:
        _page_digest_hex(digest)
    source_row_count = 0
    for page in pages:
        count = int(page["row_count"])
        if count < 0:
            raise PersonalHistoryError("shared fins scan page row count is invalid")
        source_row_count += count
    completion = _canonical_digest(
        {
            "scanned_page_digests": [f"sha256:{digest}" for digest in scanned],
            "source_row_count": source_row_count,
            "page_count": len(scanned),
            "status": "COMPLETE",
        }
    )
    return {
        "scan_digest": _canonical_digest(pages),
        "page_count": len(pages),
        "source_row_count": source_row_count,
        "completion_digest": completion,
        "scanned_page_digests": scanned,
        "page_evidence": pages,
    }


def _compact_fins_selection(
    selection: Mapping[str, Any], *, scan_digest: str
) -> dict[str, Any]:
    compact = {
        "query": dict(selection["query"]),
        "selected_row_count": int(selection["selected_row_count"]),
        "selected_digest": str(selection["selected_digest"]),
        "contributing_page_digests": list(selection["contributing_page_digests"]),
        "shared_scan_digest": scan_digest,
    }
    compact["integrity_digest"] = _canonical_digest(compact)
    return compact


def _validated_compact_fins_selection(selection: Any) -> dict[str, Any]:
    if not isinstance(selection, Mapping):
        raise PersonalHistoryError("fins_summary selection evidence is invalid")
    if set(selection) != _FINS_COMPACT_SELECTION_KEYS:
        raise PersonalHistoryError("fins_summary selection evidence fields are closed")
    query = selection.get("query")
    if not isinstance(query, Mapping):
        raise PersonalHistoryError("selection query is missing")
    contributing_raw = selection.get("contributing_page_digests")
    if not isinstance(contributing_raw, list):
        raise PersonalHistoryError("selection contributing pages are invalid")
    contributing = [_page_digest_hex(item) for item in contributing_raw]
    selected_count = _count_field(selection.get("selected_row_count"))
    if selected_count < 0:
        raise PersonalHistoryError("selection row count does not match selected rows")
    selected_digest = str(selection.get("selected_digest") or "")
    _page_digest_hex(selected_digest)
    scan_digest = str(selection.get("shared_scan_digest") or "")
    _page_digest_hex(scan_digest)
    body = {
        "query": dict(query),
        "selected_row_count": selected_count,
        "selected_digest": selected_digest
        if selected_digest.startswith("sha256:")
        else "sha256:" + selected_digest,
        "contributing_page_digests": contributing,
        "shared_scan_digest": scan_digest
        if scan_digest.startswith("sha256:")
        else "sha256:" + scan_digest,
    }
    expected_integrity = _canonical_digest(body)
    declared_integrity = str(selection.get("integrity_digest") or "")
    if not declared_integrity or _page_digest_hex(
        declared_integrity
    ) != _page_digest_hex(expected_integrity):
        raise PersonalHistoryError("selection digest does not match selected rows")
    body["integrity_digest"] = expected_integrity
    return body


def _page_evidence(
    fetch_result: Any,
) -> tuple[list[dict[str, Any]], str, dict[str, Any] | None]:
    pages = tuple(getattr(fetch_result, "pages", ()) or ())
    selected_rows = tuple(dict(row) for row in getattr(fetch_result, "rows", ()) or ())
    selection = getattr(fetch_result, "selection", None)
    if not pages:
        raise PersonalHistoryError("J-Quants response has no page evidence")
    evidence = [
        _source_page_descriptor(ordinal, page)
        for ordinal, page in enumerate(pages)
    ]
    source_row_count = sum(int(page["row_count"]) for page in evidence)
    if selection is None:
        if source_row_count != len(selected_rows):
            raise PersonalHistoryError(
                f"page row count {source_row_count} != decoded {len(selected_rows)}"
            )
        return evidence, _canonical_digest(evidence), None
    return (
        evidence,
        _canonical_digest(evidence),
        _validated_selection(_selection_fields(selection), evidence, selected_rows),
    )


def _compact_calendar(
    rows: Sequence[Mapping[str, Any]],
    ingested_at: str,
    *,
    expected_start: str,
    expected_end: str,
) -> list[dict]:
    normalized: list[dict] = []
    observed: set[str] = set()
    for source in rows:
        day = str(_pick(source, "Date") or "")[:10]
        holiday = _pick(source, "HolidayDivision", "HolDiv")
        _parse_day(day, "markets_calendar.Date")
        if day in observed:
            raise PersonalHistoryError(f"markets_calendar duplicate Date={day}")
        observed.add(day)
        compact = {"Date": day, "HolidayDivision": str(holiday or "")}
        one = JN.normalize_generic(
            [compact],
            dataset="markets_calendar",
            ingested_at=ingested_at,
            available_at=f"{day}T00:00:00+09:00",
        )[0]
        one["raw_payload"] = None
        normalized.append(one)
    expected = {
        day.isoformat()
        for day in _iter_days(
            _parse_day(expected_start, "calendar expected_start"),
            _parse_day(expected_end, "calendar expected_end"),
        )
    }
    if observed != expected:
        missing = sorted(expected - observed)[:5]
        extra = sorted(observed - expected)[:5]
        raise PersonalHistoryError(
            "markets_calendar response does not match its query window: "
            f"missing={missing} extra={extra}"
        )
    return normalized


def _master_availability(day: str) -> str:
    _parse_day(day, "equities_master.Date")
    return f"{day}T08:00:00+09:00"


def _canonical_jst(value: Any, label: str) -> datetime:
    text = str(value or "")
    try:
        parsed = parse_dt(text)
    except (TypeError, ValueError) as exc:
        raise PersonalHistoryError(
            f"{label} is not a canonical JST timestamp"
        ) from exc
    if to_iso(parsed) != text:
        raise PersonalHistoryError(f"{label} is not a canonical JST timestamp")
    return parsed


def _require_ingested_not_before(
    ingested_at: Any, available_at: Any, label: str
) -> None:
    ingested = _canonical_jst(ingested_at, f"{label} ingested_at")
    available = _canonical_jst(available_at, f"{label} available_at")
    if ingested < available:
        raise PersonalHistoryError(
            f"{label} ingested_at is earlier than available_at"
        )


def _session_close(day: str, label: str) -> str:
    _parse_day(day, label)
    try:
        return session_close_jst(day)
    except ValueError as exc:
        raise PersonalHistoryError(f"{label} must be an ISO date") from exc


def _compact_master(
    rows: Sequence[Mapping[str, Any]], *, snapshot_day: str, ingested_at: str
) -> tuple[list[dict], str]:
    members: dict[str, dict[str, str]] = {}
    for source in rows:
        source_day = _pick(source, "Date")
        if source_day is not None and str(source_day)[:10] != snapshot_day:
            raise PersonalHistoryError(
                f"equities_master returned Date={source_day!r} for query {snapshot_day}"
            )
        code = str(_pick(source, "Code", "code") or "").strip()
        market = str(
            _pick(source, "MarketCode", "MktCode", "Mkt") or ""
        ).strip()
        raw_scale = str(
            _pick(source, "ScaleCategory", "ScaleCat") or ""
        ).strip()
        scale_category = canonical_topix_scale_category(raw_scale)
        if not code:
            raise PersonalHistoryError("equities_master row has no Code")
        if scale_category is None:
            continue
        if code in members:
            raise PersonalHistoryError(
                f"equities_master snapshot {snapshot_day} has duplicate Code={code}"
            )
        members[code] = {
            "Code": code,
            "Date": snapshot_day,
            "MarketCode": market,
            # Keep the small, PIT-observed classification surface needed for
            # within-industry and size-bucket relative factors.  These values
            # must travel with each dated master snapshot; backfilling a
            # current classification into historical sessions would create a
            # subtle look-ahead path.
            "Sector17Code": str(
                _pick(source, "Sector17Code", "Sec17Code", "S17") or ""
            ).strip(),
            "Sector33Code": str(
                _pick(source, "Sector33Code", "Sec33Code", "S33") or ""
            ).strip(),
            "ScaleCategory": scale_category,
            "SourceScaleCategory": raw_scale,
        }
    if not members:
        raise PersonalHistoryError(
            f"equities_master snapshot {snapshot_day} has no TOPIX scale members"
        )
    compact = [members[code] for code in sorted(members)]
    # A classification change is also a new PIT master state.  Hashing only
    # membership would silently compress it away and make historical
    # sector/scale-neutral factors use stale classifications.
    digest = _canonical_digest(
        [
            {key: value for key, value in row.items() if key != "Date"}
            for row in compact
        ]
    )
    expected_available = _master_availability(snapshot_day)
    normalized = JN.normalize_generic(
        compact,
        dataset="equities_master",
        ingested_at=ingested_at,
        available_at=expected_available,
    )
    for row in normalized:
        row["raw_payload"] = None
        event = _canonical_jst(row["event_time"], "equities_master event_time")
        if event.date().isoformat() != snapshot_day:
            raise PersonalHistoryError(
                "equities_master event_time date does not equal snapshot_date"
            )
        if str(row["available_at"]) != expected_available:
            raise PersonalHistoryError(
                "equities_master available_at must be snapshot_date 08:00 JST"
            )
        _require_ingested_not_before(
            row["ingested_at"], row["available_at"], "equities_master"
        )
    return normalized, digest


# Immutable personal-fins research projection.  Canonical statement identity
# plus the exact aliases consumed by current personal AM/PM factor features.
# Full J-Quants source rows remain on the acquisition spool for page/selection
# evidence; they must not be copied into the research SQLite payload.
_PERSONAL_FINS_FEATURE_ALIASES: tuple[tuple[str, ...], ...] = (
    ("BPS", "BookValuePerShare"),
    ("EPS", "EarningsPerShare"),
    ("ROE", "ReturnOnEquity"),
    ("Sales", "NetSales"),
    ("NP", "Profit"),
    ("TA", "TotalAssets"),
    ("Eq", "Equity"),
    ("EqAR", "EquityToAssetRatio"),
    ("CurPerType", "TypeOfCurrentPeriod"),
    ("CurPerEn", "CurrentPeriodEndDate"),
    ("DocType", "TypeOfDocument"),
    ("DiscDate", "DisclosedDate"),
    ("DiscTime", "DisclosedTime"),
)


def _personal_fins_projection(
    source: Mapping[str, Any],
    *,
    code: str,
    disc_date: str,
    disc_time: str,
    disc_no: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "Code": code,
        "DiscDate": disc_date,
        "DiscNo": disc_no,
    }
    if disc_time:
        item["DiscTime"] = disc_time
    for aliases in _PERSONAL_FINS_FEATURE_ALIASES:
        if aliases == ("DiscTime", "DisclosedTime") and not disc_time:
            continue
        for key in aliases:
            if key in item:
                continue
            value = source.get(key)
            if value is None or value == "":
                continue
            item[key] = value
    return item


def _compact_fins(
    rows: Sequence[Mapping[str, Any]],
    ingested_at: str,
    *,
    expected_code: str,
    period_end: str,
) -> list[dict]:
    compact: list[dict[str, Any]] = []
    for source in rows:
        disc_date = str(
            _pick(source, "DiscDate", "DisclosedDate") or ""
        )[:10]
        disc_time = str(_pick(source, "DiscTime", "DisclosedTime") or "").strip()
        _parse_day(disc_date, "fins_summary.DiscDate")
        if disc_time:
            try:
                parsed = datetime.fromisoformat(f"{disc_date}T{disc_time}")
            except ValueError as exc:
                raise PersonalHistoryError(
                    "fins_summary DiscTime is not a valid wall-clock time"
                ) from exc
            if parsed.tzinfo is not None:
                raise PersonalHistoryError(
                    "fins_summary DiscTime must be a JST wall-clock time"
                )
        code = str(_pick(source, "Code") or "").strip()
        disc_no = str(_pick(source, "DiscNo") or "").strip()
        if not code or not disc_no:
            raise PersonalHistoryError(
                "fins_summary requires Code, DiscDate, and DiscNo"
            )
        if code != expected_code:
            raise PersonalHistoryError(
                f"fins_summary query Code={expected_code} returned Code={code}"
            )
        if disc_date > period_end:
            continue
        item = _personal_fins_projection(
            source,
            code=code,
            disc_date=disc_date,
            disc_time=disc_time,
            disc_no=disc_no,
        )
        if disc_time:
            available_at = f"{disc_date}T{disc_time}+09:00"
        else:
            available_at = (
                date.fromisoformat(disc_date) + timedelta(days=1)
            ).isoformat() + "T00:00:00+09:00"
        one = JN.normalize_generic(
            [item],
            dataset="fins_summary",
            ingested_at=ingested_at,
            available_at=available_at,
        )[0]
        one["raw_payload"] = None
        compact.append(one)
    return compact


_BAR_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Close", ("Close", "C")),
    ("AdjustmentClose", ("AdjustmentClose", "AdjClose", "AdjC")),
    ("Volume", ("Volume", "Vo")),
    ("AdjustmentVolume", ("AdjustmentVolume", "AdjVolume", "AdjVo")),
    ("TurnoverValue", ("TurnoverValue", "Va")),
    ("MarketCapitalization", ("MarketCapitalization", "MarketCap", "MktCap")),
    ("AdjustmentFactor", ("AdjustmentFactor", "AdjFactor", "AdjF")),
    ("MorningAdjustmentClose", ("MorningAdjustmentClose", "MAdjC")),
    ("AfternoonAdjustmentClose", ("AfternoonAdjustmentClose", "AAdjC")),
    ("MorningTurnoverValue", ("MorningTurnoverValue", "MVa")),
    ("AfternoonTurnoverValue", ("AfternoonTurnoverValue", "AVa")),
    ("MorningAdjustmentVolume", ("MorningAdjustmentVolume", "MAdjVo")),
    ("AfternoonAdjustmentVolume", ("AfternoonAdjustmentVolume", "AAdjVo")),
)
_BAR_STRICTLY_POSITIVE_FIELDS = frozenset(
    {
        "Close",
        "AdjustmentClose",
        "MorningAdjustmentClose",
        "AfternoonAdjustmentClose",
        "AdjustmentFactor",
    }
)
_BAR_NONNEGATIVE_FIELDS = frozenset(
    {
        "Volume",
        "AdjustmentVolume",
        "MorningAdjustmentVolume",
        "AfternoonAdjustmentVolume",
        "TurnoverValue",
        "MorningTurnoverValue",
        "AfternoonTurnoverValue",
        "MarketCapitalization",
    }
)


def _validated_bar_number(value: Any, field: str) -> int | float:
    """Reject non-finite garbage while preserving original numeric values."""

    if isinstance(value, bool) or value is None:
        raise PersonalHistoryError(
            f"equities_bars_daily {field} is not a finite numeric value"
        )
    if isinstance(value, int):
        number: int | float = value
        original: int | float | None = value
    elif isinstance(value, float):
        number = value
        original = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise PersonalHistoryError(
                f"equities_bars_daily {field} is not a finite numeric value"
            )
        try:
            number = int(text)
        except ValueError:
            try:
                number = float(text)
            except ValueError as exc:
                raise PersonalHistoryError(
                    f"equities_bars_daily {field} is not a finite numeric value"
                ) from exc
        original = None
    else:
        raise PersonalHistoryError(
            f"equities_bars_daily {field} is not a finite numeric value"
        )
    try:
        as_float = float(number)
    except OverflowError as exc:
        raise PersonalHistoryError(
            f"equities_bars_daily {field} is not a finite numeric value"
        ) from exc
    if not math.isfinite(as_float):
        raise PersonalHistoryError(
            f"equities_bars_daily {field} is not a finite numeric value"
        )
    if field in _BAR_STRICTLY_POSITIVE_FIELDS and not as_float > 0.0:
        raise PersonalHistoryError(
            f"equities_bars_daily {field} must be finite and strictly positive"
        )
    if field in _BAR_NONNEGATIVE_FIELDS and as_float < 0.0:
        raise PersonalHistoryError(
            f"equities_bars_daily {field} must be finite and non-negative"
        )
    return number if original is None else original


def _allowed_missing_observed_bars(expected: int, minimum_ratio: float) -> int:
    """Missing expected codes tolerated by one compact daily-bar session.

    Uses integer ``floor(expected * (1 - minimum_ratio))`` so float rounding
    cannot change the budget.  Ratios below 1.0 also allow one missing code
    (a 5/6 2008-style session).  ``minimum_ratio >= 1.0`` stays strict.
    """

    if expected <= 0 or minimum_ratio >= 1.0:
        return 0
    numerator, denominator = minimum_ratio.as_integer_ratio()
    proportional = expected * (denominator - numerator) // denominator
    return max(1, proportional)


def _compact_bars(
    rows: Sequence[Mapping[str, Any]],
    *,
    trading_day: str,
    scope_union: frozenset[str],
    ingested_at: str,
    minimum_ratio: float = DEFAULT_MIN_OBSERVED_BAR_RATIO,
) -> list[dict]:
    compact: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in rows:
        source_day = str(_pick(source, "Date") or "")[:10]
        if source_day != trading_day:
            raise PersonalHistoryError(
                f"equities_bars_daily returned Date={source_day!r} "
                f"for query {trading_day}"
            )
        code = str(_pick(source, "Code") or "").strip()
        if not code or code not in scope_union:
            continue
        if code in seen:
            raise PersonalHistoryError(
                f"equities_bars_daily {trading_day} has duplicate Code={code}"
            )
        seen.add(code)
        item: dict[str, Any] = {"Code": code, "Date": trading_day}
        for canonical, aliases in _BAR_FIELDS:
            value = _pick(source, *aliases)
            if value is not None:
                item[canonical] = _validated_bar_number(value, canonical)
        # Suspended/no-trade issues can be present with a null close.  Exclude
        # them from research facts; they stay absent and untradable that day.
        # Do not impute a price row.  The observed-breadth gate decides whether
        # the day remains usable.
        if "Close" not in item:
            continue
        compact.append(item)
    if not compact:
        raise PersonalHistoryError(
            f"equities_bars_daily {trading_day} has no rows in observed TOPIX union"
        )
    observed = len(compact)
    expected = len(scope_union)
    missing = expected - observed
    allowed_missing = _allowed_missing_observed_bars(expected, minimum_ratio)
    if missing > allowed_missing:
        raise PersonalHistoryError(
            f"equities_bars_daily {trading_day} observed ratio "
            f"{observed}/{expected} is below {minimum_ratio:.6f} "
            f"(missing {missing}, allowed-missing {allowed_missing})"
        )
    session_close = _session_close(trading_day, "equities_bars_daily.Date")
    normalized = JN.normalize_generic(
        compact,
        dataset="equities_bars_daily",
        ingested_at=ingested_at,
        available_at=session_close,
    )
    for row in normalized:
        row["raw_payload"] = None
        if (
            str(row["event_time"]) != session_close
            or str(row["available_at"]) != session_close
        ):
            raise PersonalHistoryError(
                "equities_bars_daily timestamps must be the official session close"
            )
        _require_ingested_not_before(
            row["ingested_at"], row["available_at"], "equities_bars_daily"
        )
    return normalized


class PersonalHistoryHydrator:
    """Sequential segment runner with atomic fact+checkpoint commits."""

    def __init__(
        self,
        *,
        client: Any,
        store: Any,
        plan: PersonalHistoryPlan,
        max_database_bytes: int = DEFAULT_MAX_DATABASE_BYTES,
        minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES,
        wal_checkpoint_segments: int = DEFAULT_WAL_CHECKPOINT_SEGMENTS,
    ) -> None:
        self.client = client
        self.store = store
        self.plan = plan
        if max_database_bytes < 1024 * 1024:
            raise PersonalHistoryError("max_database_bytes must be at least 1 MiB")
        if minimum_free_bytes < 0:
            raise PersonalHistoryError("minimum_free_bytes cannot be negative")
        if wal_checkpoint_segments < 1:
            raise PersonalHistoryError("wal_checkpoint_segments must be positive")
        self.max_database_bytes = int(max_database_bytes)
        self.minimum_free_bytes = int(minimum_free_bytes)
        self.wal_checkpoint_segments = int(wal_checkpoint_segments)
        self._new_segments = 0
        _assert_personal_draft_store_is_unmanaged(store)
        self._connection: sqlite3.Connection = store._conn
        self._ensure_checkpoint_schema()
        self._assert_compact_tables_match_builder_ddl()
        self._apply_max_page_count()
        self._initialize_manifest()
        self._outcomes: list[_SegmentOutcome] = []

    def _database_footprint(self) -> int:
        path = Path(self.store.path)
        return sum(
            candidate.stat().st_size if candidate.exists() else 0
            for candidate in (
                path,
                Path(str(path) + "-wal"),
                Path(str(path) + "-shm"),
            )
        )

    def _guard_capacity(self, *, phase: str, additional_bytes: int = 0) -> None:
        footprint = self._database_footprint()
        if footprint + max(0, int(additional_bytes)) > self.max_database_bytes:
            raise PersonalHistoryError(
                f"personal history size guard stopped at {phase}: "
                f"current={footprint} additional={additional_bytes} "
                f"limit={self.max_database_bytes}"
            )
        free = shutil.disk_usage(Path(self.store.path).parent).free
        required_free = self.minimum_free_bytes + max(0, int(additional_bytes))
        if free < required_free:
            raise PersonalHistoryError(
                f"personal history free-space guard stopped at {phase}: "
                f"free={free} required={required_free}"
            )

    def _checkpoint_wal_if_due(self) -> None:
        if self._new_segments % self.wal_checkpoint_segments:
            return
        self._checkpoint_wal()

    def _checkpoint_wal(self) -> None:
        result = self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result is not None and int(result[0]) != 0:
            raise PersonalHistoryError(
                "personal history WAL checkpoint could not acquire a safe lock"
            )

    def _apply_max_page_count(self) -> None:
        page_size = int(self._connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(self._connection.execute("PRAGMA page_count").fetchone()[0])
        maximum_pages = self.max_database_bytes // page_size
        if page_count > maximum_pages:
            raise PersonalHistoryError(
                "personal history database already exceeds the configured size limit"
            )
        applied = int(
            self._connection.execute(
                f"PRAGMA max_page_count={maximum_pages}"
            ).fetchone()[0]
        )
        if applied > maximum_pages:
            raise PersonalHistoryError(
                "SQLite refused the configured personal history page limit"
            )

    def _ensure_checkpoint_schema(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS personal_history_manifest (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                format TEXT NOT NULL,
                plan_digest TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                history_scope_id TEXT NOT NULL,
                history_scope_version TEXT NOT NULL,
                history_scope_digest TEXT NOT NULL,
                status TEXT NOT NULL,
                research_state TEXT NOT NULL DEFAULT 'PERSONAL_DRAFT',
                completeness_claim TEXT NOT NULL DEFAULT 'NONE',
                controlled_live_eligibility TEXT NOT NULL DEFAULT 'FORBIDDEN',
                master_availability_policy TEXT NOT NULL,
                fins_availability_policy TEXT NOT NULL,
                master_revision_pit INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                last_error TEXT,
                CHECK (research_state = 'PERSONAL_DRAFT'),
                CHECK (completeness_claim = 'NONE'),
                CHECK (controlled_live_eligibility = 'FORBIDDEN'),
                CHECK (master_revision_pit = 0),
                CHECK (history_scope_id = 'topix_all'),
                CHECK (status IN ('BUILDING','VALIDATING','COMPLETE_DRAFT'))
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS personal_history_shared_scans (
                scan_digest TEXT PRIMARY KEY,
                dataset TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                source_row_count INTEGER NOT NULL,
                completion_digest TEXT NOT NULL,
                scanned_page_digests_json TEXT NOT NULL,
                page_evidence_json TEXT NOT NULL,
                CHECK (dataset = 'fins_summary'),
                CHECK (page_count >= 1),
                CHECK (source_row_count >= 0)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS personal_history_segments (
                dataset TEXT NOT NULL,
                segment_id TEXT NOT NULL,
                query_start TEXT NOT NULL,
                query_end TEXT NOT NULL,
                query_params TEXT NOT NULL,
                state TEXT NOT NULL,
                research_state TEXT NOT NULL DEFAULT 'PERSONAL_DRAFT',
                completeness_claim TEXT NOT NULL DEFAULT 'NONE',
                controlled_live_eligibility TEXT NOT NULL DEFAULT 'FORBIDDEN',
                pit_policy TEXT NOT NULL,
                master_revision_pit INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                rows_fetched INTEGER NOT NULL DEFAULT 0,
                rows_written INTEGER NOT NULL DEFAULT 0,
                page_count INTEGER NOT NULL DEFAULT 0,
                page_evidence_json TEXT,
                selection_evidence_json TEXT,
                response_digest TEXT,
                facts_digest TEXT,
                membership_digest TEXT,
                expected_rows INTEGER,
                observed_ratio REAL,
                started_at TEXT,
                finished_at TEXT,
                error TEXT,
                PRIMARY KEY (dataset, segment_id),
                CHECK (research_state = 'PERSONAL_DRAFT'),
                CHECK (completeness_claim = 'NONE'),
                CHECK (controlled_live_eligibility = 'FORBIDDEN'),
                CHECK (master_revision_pit = 0),
                CHECK (state IN ('RUNNING','OBSERVED','OBSERVED_EMPTY','FAILED'))
            )
            """
        )
        for _table, create_sql in PERSONAL_HISTORY_COMPACT_CREATE_SQL:
            self._connection.execute(create_sql)
        self._connection.commit()
        columns = {
            str(row[1])
            for row in self._connection.execute(
                "PRAGMA table_info(personal_history_segments)"
            )
        }
        if "selection_evidence_json" not in columns:
            self._connection.execute(
                "ALTER TABLE personal_history_segments "
                "ADD COLUMN selection_evidence_json TEXT"
            )
            self._connection.commit()

    def _assert_compact_tables_match_builder_ddl(self) -> None:
        """Reject lookalike compact tables that IF NOT EXISTS would otherwise keep."""

        probe = sqlite3.connect(":memory:")
        try:
            for _table, create_sql in PERSONAL_HISTORY_COMPACT_CREATE_SQL:
                probe.execute(create_sql)
            for table in PERSONAL_HISTORY_COMPACT_TABLES:
                if _compact_table_builder_shape(
                    self._connection, table
                ) != _compact_table_builder_shape(probe, table):
                    raise PersonalHistoryError(
                        f"personal history compact table {table} does not "
                        "match builder DDL"
                    )
        finally:
            probe.close()

    def _initialize_manifest(self) -> None:
        plan_json = canonical_json(self.plan.to_dict())
        plan_digest = "sha256:" + hashlib.sha256(
            plan_json.encode("utf-8")
        ).hexdigest()
        existing = self._connection.execute(
            "SELECT format,plan_digest FROM personal_history_manifest "
            "WHERE singleton=1"
        ).fetchone()
        if existing is not None:
            if str(existing["format"]) != PERSONAL_HISTORY_FORMAT:
                raise PersonalHistoryError(
                    "personal history database uses an older compact format; "
                    "build a new dedicated SQLite file so compact master and "
                    "bar WITHOUT ROWID tables, PIT classifications, market "
                    "cap, AM/PM session fields, the compact personal-fins "
                    "projection, and shared fins scan evidence are fetched "
                    "again"
                )
            if str(existing["plan_digest"]) != plan_digest:
                raise PersonalHistoryError(
                    "personal history database is bound to a different plan; "
                    "use a new dedicated SQLite file"
                )
        self._connection.execute(
            """
            INSERT INTO personal_history_manifest (
                singleton,format,plan_digest,plan_json,status,
                history_scope_id,history_scope_version,history_scope_digest,
                master_availability_policy,fins_availability_policy,
                updated_at,last_error
            ) VALUES (1,?,?,?,'BUILDING',?,?,?,?,?,?,NULL)
            ON CONFLICT(singleton) DO UPDATE SET
                status='BUILDING',updated_at=excluded.updated_at,last_error=NULL
            """,
            (
                PERSONAL_HISTORY_FORMAT,
                plan_digest,
                plan_json,
                PERSONAL_HISTORY_SCOPE_ID,
                PERSONAL_HISTORY_SCOPE_VERSION,
                PERSONAL_HISTORY_SCOPE_DIGEST,
                MASTER_AVAILABILITY_POLICY,
                FINS_AVAILABILITY_POLICY,
                now_iso(),
            ),
        )
        self._connection.commit()

    def _manifest_status(self, status: str, error: str | None = None) -> None:
        self._connection.execute(
            "UPDATE personal_history_manifest SET status=?,updated_at=?,last_error=? "
            "WHERE singleton=1",
            (status, now_iso(), error),
        )
        self._connection.commit()

    def _checkpoint(self, dataset: str, segment_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM personal_history_segments "
            "WHERE dataset=? AND segment_id=?",
            (dataset, segment_id),
        ).fetchone()

    def _start_segment(
        self,
        *,
        dataset: str,
        segment_id: str,
        query_start: str,
        query_end: str,
        params: Mapping[str, Any],
        pit_policy: str,
    ) -> sqlite3.Row | None:
        checkpoint = self._checkpoint(dataset, segment_id)
        if checkpoint is not None and checkpoint["state"] in _TERMINAL_STATES:
            return checkpoint
        if checkpoint is not None and checkpoint["state"] not in _RETRYABLE_STATES:
            raise PersonalHistoryError(
                f"unknown checkpoint state {checkpoint['state']!r}"
            )
        started = now_iso()
        self._connection.execute(
            """
            INSERT INTO personal_history_segments (
                dataset,segment_id,query_start,query_end,query_params,state,
                pit_policy,attempts,started_at,finished_at,error
            ) VALUES (?,?,?,?,?,'RUNNING',?,1,?,NULL,NULL)
            ON CONFLICT(dataset,segment_id) DO UPDATE SET
                query_start=excluded.query_start,
                query_end=excluded.query_end,
                query_params=excluded.query_params,
                state='RUNNING',
                pit_policy=excluded.pit_policy,
                attempts=personal_history_segments.attempts+1,
                started_at=excluded.started_at,
                finished_at=NULL,
                error=NULL
            """,
            (
                dataset,
                segment_id,
                query_start,
                query_end,
                canonical_json(dict(params)),
                pit_policy,
                started,
            ),
        )
        self._connection.commit()
        return None

    def _fail_segment(self, dataset: str, segment_id: str, exc: Exception) -> None:
        self._connection.rollback()
        self._connection.execute(
            "UPDATE personal_history_segments SET state='FAILED',"
            "finished_at=?,error=? WHERE dataset=? AND segment_id=?",
            (now_iso(), f"{type(exc).__name__}: {exc}"[:2000], dataset, segment_id),
        )
        self._connection.commit()

    def _run_segment(
        self,
        *,
        dataset: str,
        segment_id: str,
        query_start: str,
        query_end: str,
        params: Mapping[str, Any],
        pit_policy: str,
        transform: Any,
        allow_observed_empty: bool = False,
        membership_digest: str | None = None,
        expected_rows: int | None = None,
    ) -> _SegmentOutcome:
        existing = self._checkpoint(dataset, segment_id)
        if existing is not None and existing["state"] in _TERMINAL_STATES:
            outcome = _SegmentOutcome(
                dataset=dataset,
                segment_id=segment_id,
                fetched=0,
                written=0,
                skipped=True,
                state=str(existing["state"]),
                membership_digest=existing["membership_digest"],
            )
            self._outcomes.append(outcome)
            return outcome
        self._guard_capacity(phase=f"before fetch {segment_id}")
        checkpoint = self._start_segment(
            dataset=dataset,
            segment_id=segment_id,
            query_start=query_start,
            query_end=query_end,
            params=params,
            pit_policy=pit_policy,
        )
        if checkpoint is not None:
            outcome = _SegmentOutcome(
                dataset=dataset,
                segment_id=segment_id,
                fetched=0,
                written=0,
                skipped=True,
                state=str(checkpoint["state"]),
                membership_digest=checkpoint["membership_digest"],
            )
            self._outcomes.append(outcome)
            return outcome

        try:
            fetched = self.client.fetch_dataset_evidenced(dataset, **dict(params))
            source_rows = tuple(dict(row) for row in fetched.rows)
            page_evidence, response_digest, selection = _page_evidence(fetched)
            transformed = transform(source_rows, now_iso())
            if isinstance(transformed, tuple):
                rows, derived_membership = transformed
                membership_digest = derived_membership
            else:
                rows = transformed
            rows = list(rows)
            if not source_rows and not allow_observed_empty:
                raise PersonalHistoryError(
                    f"{dataset} empty response is not accepted for this segment"
                )
            state = "OBSERVED_EMPTY" if not source_rows else "OBSERVED"
            facts_digest = _canonical_digest(
                sorted(
                    (
                        {
                            "natural_key": row["natural_key"],
                            "event_time": row["event_time"],
                            "available_at": row["available_at"],
                            "payload": row.get("payload"),
                        }
                        for row in rows
                    ),
                    key=lambda row: str(row["natural_key"]),
                )
            )
            if dataset in ("equities_master", "equities_bars_daily"):
                estimated_write_bytes = (
                    len(rows) * DEFAULT_COMPACT_STORAGE_BYTES_PER_ROW
                )
            else:
                estimated_write_bytes = _estimated_fact_write_bytes(rows)
            page_evidence_json: str | None
            selection_evidence_json: str | None
            stored_page_count = len(page_evidence)
            scan: Mapping[str, Any] | None = None
            if dataset == "fins_summary" and selection is not None:
                scan = _shared_scan_fields(page_evidence)
                if (
                    selection["scanned_page_digests"] != scan["scanned_page_digests"]
                    or selection["source_row_count"] != scan["source_row_count"]
                    or _page_digest_hex(selection["completion_digest"])
                    != _page_digest_hex(scan["completion_digest"])
                    or response_digest != scan["scan_digest"]
                ):
                    raise PersonalHistoryError(
                        "fins_summary selection does not match independently "
                        "derived shared scan"
                    )
                compact = _compact_fins_selection(
                    selection, scan_digest=scan["scan_digest"]
                )
                page_evidence_json = None
                selection_evidence_json = canonical_json(compact)
                response_digest = scan["scan_digest"]
                stored_page_count = scan["page_count"]
                estimated_write_bytes += len(selection_evidence_json.encode("utf-8")) * 3
                known_scan = self._connection.execute(
                    "SELECT 1 FROM personal_history_shared_scans WHERE scan_digest=?",
                    (scan["scan_digest"],),
                ).fetchone()
                if known_scan is None:
                    estimated_write_bytes += (
                        len(canonical_json(scan["page_evidence"]).encode("utf-8")) * 3
                    )
            else:
                page_evidence_json = canonical_json(page_evidence)
                selection_evidence_json = (
                    None if selection is None else canonical_json(selection)
                )
            self._guard_capacity(
                phase=f"before commit {segment_id}",
                additional_bytes=estimated_write_bytes,
            )
            self._connection.execute("BEGIN IMMEDIATE")
            if scan is not None:
                self._upsert_shared_fins_scan(scan)
            if dataset in ("equities_master", "equities_bars_daily"):
                written = self._insert_compact_facts(dataset, rows)
            else:
                written = self.store.upsert("jquants_records", rows, commit=False)
            self._connection.execute(
                """
                UPDATE personal_history_segments SET
                    state=?,rows_fetched=?,rows_written=?,page_count=?,
                    page_evidence_json=?,selection_evidence_json=?,
                    response_digest=?,facts_digest=?,
                    membership_digest=?,expected_rows=?,observed_ratio=?,
                    finished_at=?,error=NULL
                WHERE dataset=? AND segment_id=?
                """,
                (
                    state,
                    len(source_rows),
                    written,
                    stored_page_count,
                    page_evidence_json,
                    selection_evidence_json,
                    response_digest,
                    facts_digest,
                    membership_digest,
                    expected_rows,
                    (
                        len(rows) / expected_rows
                        if expected_rows is not None and expected_rows > 0
                        else None
                    ),
                    now_iso(),
                    dataset,
                    segment_id,
                ),
            )
            self._connection.commit()
        except Exception as exc:  # noqa: BLE001 - checkpoint exact failure
            self._fail_segment(dataset, segment_id, exc)
            if isinstance(exc, PersonalHistoryError):
                raise
            raise PersonalHistoryError(
                f"{dataset} segment {segment_id} failed: {exc}"
            ) from exc
        outcome = _SegmentOutcome(
            dataset=dataset,
            segment_id=segment_id,
            fetched=len(source_rows),
            written=written,
            skipped=False,
            state=state,
            membership_digest=membership_digest,
        )
        self._outcomes.append(outcome)
        self._new_segments += 1
        self._checkpoint_wal_if_due()
        self._guard_capacity(phase=f"after commit {segment_id}")
        return outcome

    def _hydrate_calendar(self) -> None:
        start = _parse_day(self.plan.calendar_start, "calendar_start")
        end = _parse_day(self.plan.period_end, "period_end")
        for window_start, window_end in _iter_windows(
            start, end, self.plan.calendar_window_days
        ):
            params = {
                "from": window_start.isoformat(),
                "to": window_end.isoformat(),
            }
            self._run_segment(
                dataset="markets_calendar",
                segment_id=(
                    f"calendar:{window_start.isoformat()}:{window_end.isoformat()}"
                ),
                query_start=window_start.isoformat(),
                query_end=window_end.isoformat(),
                params=params,
                pit_policy=CALENDAR_AVAILABILITY_POLICY,
                transform=lambda rows, stamp, start=window_start, end=window_end: (
                    _compact_calendar(
                        rows,
                        stamp,
                        expected_start=start.isoformat(),
                        expected_end=end.isoformat(),
                    )
                ),
            )

    def _trading_days(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT event_time,payload FROM jquants_records "
            "WHERE source='jquants' AND dataset='markets_calendar' "
            "AND substr(event_time,1,10) BETWEEN ? AND ? "
            "ORDER BY event_time",
            (self.plan.calendar_start, self.plan.period_end),
        ).fetchall()
        trading: list[str] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise PersonalHistoryError(
                    "stored markets_calendar payload is invalid"
                ) from exc
            holiday = str(
                _pick(payload, "HolidayDivision", "HolDiv") or ""
            )
            if holiday == "1":
                trading.append(str(row["event_time"])[:10])
        trading = sorted(set(trading))
        if not trading:
            raise PersonalHistoryError("markets_calendar has no observed trading days")
        return trading

    def _bar_and_master_days(self, trading: Sequence[str]) -> tuple[str, list[str]]:
        profile_floor = personal_snapshot_data_floor()
        master_floor = _official_availability("equities_master")
        usable = [
            day
            for day in trading
            if profile_floor <= day <= self.plan.period_end
        ]
        if not usable:
            raise PersonalHistoryError(
                "research window has no observed trading days on or after "
                "the personal snapshot data floor"
            )
        prior = [day for day in usable if day < self.plan.period_start]
        actual_lookback = min(self.plan.lookback_sessions, len(prior))
        if actual_lookback:
            bar_start = prior[-actual_lookback]
        else:
            window_start = max(self.plan.period_start, profile_floor)
            on_or_after = [day for day in usable if day >= window_start]
            if not on_or_after:
                raise PersonalHistoryError(
                    "research window has no observed trading days on or after "
                    "the personal snapshot data floor"
                )
            bar_start = on_or_after[0]
        bar_days = [
            day for day in trading if bar_start <= day <= self.plan.period_end
        ]
        if not bar_days:
            raise PersonalHistoryError("research window has no observed trading days")
        seed_days = [
            day for day in trading if master_floor <= day < bar_days[0]
        ]
        if not seed_days:
            raise PersonalHistoryError(
                "observed calendar does not contain a master seed on or after "
                "official master availability"
            )
        return bar_start, [seed_days[-1], *bar_days]

    def _hydrate_master(self, master_days: Sequence[str]) -> None:
        previous_digest: str | None = None
        master_floor = _official_availability("equities_master")
        for day in master_days:
            if day < master_floor:
                raise PersonalHistoryError(
                    "equities_master query is before official availability"
                )

            def transform(rows: Sequence[Mapping[str, Any]], stamp: str):
                normalized, digest = _compact_master(
                    rows, snapshot_day=day, ingested_at=stamp
                )
                return ([] if digest == previous_digest else normalized), digest

            outcome = self._run_segment(
                dataset="equities_master",
                segment_id=f"master:{day}",
                query_start=day,
                query_end=day,
                params={"date": day},
                pit_policy=MASTER_AVAILABILITY_POLICY,
                transform=transform,
            )
            previous_digest = outcome.membership_digest

    def _topix_union(self) -> frozenset[str]:
        codes = {
            str(row["code"]).strip()
            for row in self._connection.execute(
                "SELECT DISTINCT code,scale_category "
                "FROM personal_history_compact_master "
                "WHERE trim(code) <> '' AND scale_category IS NOT NULL "
                "AND trim(scale_category) <> ''"
            )
            if str(row["code"] or "").strip()
            and canonical_topix_scale_category(row["scale_category"]) is not None
        }
        if not codes:
            raise PersonalHistoryError("compressed master has no TOPIX code union")
        return frozenset(codes)

    def _hydrate_fins(self, scope_union: frozenset[str]) -> None:
        for code in sorted(scope_union):
            self._run_segment(
                dataset="fins_summary",
                segment_id=f"fins:{code}",
                query_start="earliest_entitled",
                query_end=self.plan.period_end,
                params={"code": code},
                pit_policy=FINS_AVAILABILITY_POLICY,
                transform=lambda rows, stamp, code=code: _compact_fins(
                    rows,
                    stamp,
                    expected_code=code,
                    period_end=self.plan.period_end,
                ),
                allow_observed_empty=True,
            )

    def _master_memberships(self) -> list[tuple[str, frozenset[str]]]:
        rows = self._connection.execute(
            "SELECT snapshot_date,code,scale_category "
            "FROM personal_history_compact_master "
            "ORDER BY snapshot_date,code"
        ).fetchall()
        by_day: dict[str, set[str]] = {}
        for row in rows:
            day = str(row["snapshot_date"] or "")[:10]
            code = str(row["code"] or "").strip()
            category = canonical_topix_scale_category(row["scale_category"])
            if day and code and category is not None:
                by_day.setdefault(day, set()).add(code)
        if not by_day:
            raise PersonalHistoryError("compressed master membership is empty")
        return [
            (day, frozenset(by_day[day]))
            for day in sorted(by_day)
        ]

    def _first_visible_fins_by_code(self) -> dict[str, str]:
        rows = self._connection.execute(
            "SELECT available_at,payload FROM jquants_records "
            "WHERE source='jquants' AND dataset='fins_summary' "
            "ORDER BY available_at"
        ).fetchall()
        first: dict[str, str] = {}
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise PersonalHistoryError(
                    "stored fins_summary payload is invalid"
                ) from exc
            code = str(_pick(payload, "Code") or "").strip()
            availability = str(row["available_at"] or "")
            if code and availability:
                previous = first.get(code)
                if previous is None or availability < previous:
                    first[code] = availability
        return first

    @staticmethod
    def _membership_for_day(
        snapshots: Sequence[tuple[str, frozenset[str]]], day: str
    ) -> frozenset[str]:
        membership: frozenset[str] | None = None
        for snapshot_day, codes in snapshots:
            if snapshot_day > day:
                break
            membership = codes
        if membership is None:
            raise PersonalHistoryError(
                f"no compressed TOPIX master snapshot is visible for {day}"
            )
        return membership

    def _hydrate_bars(
        self, *, bar_start: str, trading: Sequence[str]
    ) -> None:
        snapshots = self._master_memberships()
        first_fins = self._first_visible_fins_by_code()
        profile_floor = personal_snapshot_data_floor()
        started = False
        for day in trading:
            if day < bar_start or day > self.plan.period_end:
                continue
            if day < profile_floor:
                raise PersonalHistoryError(
                    "equities_bars_daily query is before the personal "
                    "snapshot data floor"
                )
            topix = self._membership_for_day(snapshots, day)
            close = _session_close(day, "equities_bars_daily.Date")
            expected = frozenset(
                code
                for code in topix
                if first_fins.get(code, "9999") <= close
            )
            if not expected:
                if not started:
                    continue
                raise PersonalHistoryError(
                    f"TOPIX intersect PIT-visible fins is empty for {day}"
                )
            self._run_segment(
                dataset="equities_bars_daily",
                segment_id=f"bars:{day}",
                query_start=day,
                query_end=day,
                params={"date": day},
                pit_policy=BARS_AVAILABILITY_POLICY,
                transform=lambda rows, stamp, day=day, expected=expected: _compact_bars(
                    rows,
                    trading_day=day,
                    scope_union=expected,
                    ingested_at=stamp,
                ),
                membership_digest=_canonical_digest(sorted(expected)),
                expected_rows=len(expected),
            )
            started = True
        if not started:
            raise PersonalHistoryError(
                "TOPIX intersect PIT-visible fins is empty for the research window"
            )

    def _insert_compact_facts(
        self, dataset: str, rows: Sequence[Mapping[str, Any]]
    ) -> int:
        """Insert already-normalized master/bar rows into compact WITHOUT ROWID tables."""

        if not rows:
            return 0

        def payload_of(row: Mapping[str, Any]) -> Mapping[str, Any]:
            raw = row.get("payload")
            if isinstance(raw, Mapping):
                return raw
            try:
                parsed = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise PersonalHistoryError("compact fact payload is invalid") from exc
            if not isinstance(parsed, dict):
                raise PersonalHistoryError("compact fact payload is invalid")
            return parsed

        values: list[tuple[Any, ...]]
        if dataset == "equities_master":
            sql = """
                INSERT INTO personal_history_compact_master (
                    snapshot_date,code,event_time,available_at,ingested_at,
                    market_code,sector_17_code,sector_33_code,
                    scale_category,source_scale_category
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """
            values = []
            for row in rows:
                payload = payload_of(row)
                values.append(
                    (
                        str(payload.get("Date") or "")[:10],
                        str(payload.get("Code") or ""),
                        row["event_time"],
                        row["available_at"],
                        row["ingested_at"],
                        payload.get("MarketCode"),
                        payload.get("Sector17Code"),
                        payload.get("Sector33Code"),
                        payload.get("ScaleCategory"),
                        payload.get("SourceScaleCategory"),
                    )
                )
        elif dataset == "equities_bars_daily":
            sql = """
                INSERT INTO personal_history_compact_bars (
                    code,date,event_time,available_at,ingested_at,
                    close,volume,turnover_value,adjustment_close,adjustment_volume,
                    morning_adjustment_close,afternoon_adjustment_close,
                    morning_turnover_value,afternoon_turnover_value,
                    morning_adjustment_volume,afternoon_adjustment_volume,
                    market_cap
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """
            values = []
            for row in rows:
                payload = payload_of(row)
                values.append(
                    (
                        str(payload.get("Code") or ""),
                        str(payload.get("Date") or "")[:10],
                        row["event_time"],
                        row["available_at"],
                        row["ingested_at"],
                        payload.get("Close"),
                        payload.get("Volume"),
                        payload.get("TurnoverValue"),
                        payload.get("AdjustmentClose"),
                        payload.get("AdjustmentVolume"),
                        payload.get("MorningAdjustmentClose"),
                        payload.get("AfternoonAdjustmentClose"),
                        payload.get("MorningTurnoverValue"),
                        payload.get("AfternoonTurnoverValue"),
                        payload.get("MorningAdjustmentVolume"),
                        payload.get("AfternoonAdjustmentVolume"),
                        payload.get("MarketCapitalization"),
                    )
                )
        else:
            raise PersonalHistoryError(
                f"personal history cannot write {dataset} as compact facts"
            )
        self._connection.executemany(sql, values)
        return len(values)

    def _upsert_shared_fins_scan(self, scan: Mapping[str, Any]) -> None:
        scan_digest = str(scan["scan_digest"])
        existing_digests = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT scan_digest FROM personal_history_shared_scans "
                "WHERE dataset='fins_summary'"
            )
        }
        if existing_digests - {scan_digest}:
            raise PersonalHistoryError("fins_summary shared scan evidence diverged")
        existing = self._connection.execute(
            "SELECT scan_digest,page_count,source_row_count,completion_digest "
            "FROM personal_history_shared_scans WHERE scan_digest=?",
            (scan_digest,),
        ).fetchone()
        if existing is None:
            self._connection.execute(
                """
                INSERT INTO personal_history_shared_scans (
                    scan_digest,dataset,page_count,source_row_count,
                    completion_digest,scanned_page_digests_json,page_evidence_json
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    scan_digest,
                    "fins_summary",
                    int(scan["page_count"]),
                    int(scan["source_row_count"]),
                    str(scan["completion_digest"]),
                    canonical_json(scan["scanned_page_digests"]),
                    canonical_json(scan["page_evidence"]),
                ),
            )
            inserted = self._connection.execute(
                "SELECT * FROM personal_history_shared_scans WHERE scan_digest=?",
                (scan_digest,),
            ).fetchone()
            if inserted is None:
                raise PersonalHistoryError(
                    "fins_summary shared scan reference is missing"
                )
            self._verified_shared_scan_metadata(inserted)
            return
        if (
            int(existing["page_count"]) != int(scan["page_count"])
            or int(existing["source_row_count"]) != int(scan["source_row_count"])
            or _page_digest_hex(existing["completion_digest"])
            != _page_digest_hex(scan["completion_digest"])
        ):
            raise PersonalHistoryError(
                "fins_summary selection does not match independently "
                "derived shared scan"
            )

    def _verified_shared_scan_metadata(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            pages = json.loads(row["page_evidence_json"])
            scanned_stored = json.loads(row["scanned_page_digests_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise PersonalHistoryError(
                "shared fins scan evidence is invalid"
            ) from exc
        if not isinstance(pages, list) or not isinstance(scanned_stored, list):
            raise PersonalHistoryError("shared fins scan evidence is invalid")
        derived = _shared_scan_fields(pages)
        if derived["scan_digest"] != str(row["scan_digest"]):
            raise PersonalHistoryError(
                "shared scan digest does not match page evidence"
            )
        if derived["page_count"] != int(row["page_count"]):
            raise PersonalHistoryError(
                "shared scan page count does not match page evidence"
            )
        if derived["source_row_count"] != int(row["source_row_count"]):
            raise PersonalHistoryError(
                "selection source row count does not match pages"
            )
        if _page_digest_hex(derived["completion_digest"]) != _page_digest_hex(
            row["completion_digest"]
        ):
            raise PersonalHistoryError(
                "selection completion digest does not match pages"
            )
        if derived["scanned_page_digests"] != [
            _page_digest_hex(item) for item in scanned_stored
        ]:
            raise PersonalHistoryError(
                "selection scanned pages do not match fetched source pages"
            )
        if str(row["dataset"]) != "fins_summary":
            raise PersonalHistoryError("shared scan dataset is invalid")
        return {
            "scan_digest": derived["scan_digest"],
            "page_count": derived["page_count"],
            "source_row_count": derived["source_row_count"],
            "completion_digest": derived["completion_digest"],
            "scanned_set": set(derived["scanned_page_digests"]),
        }

    def _validate_shared_fins_scan_evidence(self) -> None:
        verified: dict[str, dict[str, Any]] = {}
        for row in self._connection.execute(
            "SELECT * FROM personal_history_shared_scans"
        ):
            metadata = self._verified_shared_scan_metadata(row)
            verified[metadata["scan_digest"]] = metadata
        referenced: set[str] = set()
        saw_shared = False
        saw_local = False
        for segment in self._connection.execute(
            "SELECT segment_id,state,rows_fetched,page_count,page_evidence_json,"
            "selection_evidence_json,response_digest "
            "FROM personal_history_segments WHERE dataset='fins_summary'"
        ):
            selection_raw = segment["selection_evidence_json"]
            page_raw = segment["page_evidence_json"]
            if selection_raw is None:
                if not page_raw:
                    raise PersonalHistoryError(
                        "fins_summary segment is missing page evidence"
                    )
                saw_local = True
                continue
            saw_shared = True
            if page_raw is not None:
                raise PersonalHistoryError(
                    "fins_summary page evidence must live in the shared scan record"
                )
            try:
                selection = json.loads(selection_raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise PersonalHistoryError(
                    "fins_summary selection evidence is invalid"
                ) from exc
            compact = _validated_compact_fins_selection(selection)
            scan_digest = compact["shared_scan_digest"]
            scan = verified.get(scan_digest)
            if scan is None:
                raise PersonalHistoryError(
                    "fins_summary shared scan reference is missing"
                )
            referenced.add(scan_digest)
            expected_code = str(segment["segment_id"]).split(":", 1)[-1]
            if str(compact["query"].get("code") or "") != expected_code:
                raise PersonalHistoryError(
                    "fins_summary selection query does not match the segment"
                )
            if str(segment["response_digest"]) != scan_digest:
                raise PersonalHistoryError(
                    "fins_summary response digest does not match shared scan"
                )
            if int(segment["page_count"]) != int(scan["page_count"]):
                raise PersonalHistoryError(
                    "shared scan page count does not match page evidence"
                )
            if int(segment["rows_fetched"]) != int(compact["selected_row_count"]):
                raise PersonalHistoryError(
                    "selection row count does not match selected rows"
                )
            contributing = compact["contributing_page_digests"]
            if any(digest not in scan["scanned_set"] for digest in contributing):
                raise PersonalHistoryError("selection cites a page that was not fetched")
            if int(compact["selected_row_count"]) > 0 and not contributing:
                raise PersonalHistoryError(
                    "selection digest does not match selected rows"
                )
        if saw_shared and saw_local:
            raise PersonalHistoryError(
                "fins_summary cannot mix shared and local page evidence"
            )
        if saw_shared and set(verified) != referenced:
            raise PersonalHistoryError("fins_summary shared scan reference is missing")

    def _validate_draft_boundary(self) -> None:
        _assert_personal_draft_store_is_unmanaged(self.store)
        active = self._connection.execute(
            "SELECT COUNT(*) FROM personal_history_segments "
            "WHERE state IN ('RUNNING','FAILED')"
        ).fetchone()[0]
        if int(active):
            raise PersonalHistoryError(
                f"personal history has {active} unfinished segment(s)"
            )
        duplicated = self._connection.execute(
            "SELECT COUNT(*) FROM jquants_records WHERE source='jquants' "
            "AND dataset IN (?,?,?,?) AND raw_payload IS NOT NULL",
            PERSONAL_HISTORY_DATASETS,
        ).fetchone()[0]
        if int(duplicated):
            raise PersonalHistoryError(
                "personal history rows contain forbidden raw_payload copies"
            )
        generic_compacted = int(
            self._connection.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM jquants_records WHERE source='jquants' "
                " AND dataset IN ('equities_master','equities_bars_daily')) + "
                "(SELECT COUNT(*) FROM jquants_records_revisions "
                " WHERE source='jquants' "
                " AND dataset IN ('equities_master','equities_bars_daily'))"
            ).fetchone()[0]
        )
        if generic_compacted:
            raise PersonalHistoryError(
                "personal history generic master or bars remain"
            )
        expected_master = int(
            self._connection.execute(
                "SELECT COALESCE(SUM(rows_written),0) "
                "FROM personal_history_segments "
                "WHERE dataset='equities_master' "
                "AND state IN ('OBSERVED','OBSERVED_EMPTY')"
            ).fetchone()[0]
        )
        compact_master = int(
            self._connection.execute(
                "SELECT COUNT(*) FROM personal_history_compact_master"
            ).fetchone()[0]
        )
        if expected_master < 1 or compact_master != expected_master:
            raise PersonalHistoryError(
                "personal history compact master does not match completed checkpoints"
            )
        expected_bars = int(
            self._connection.execute(
                "SELECT COALESCE(SUM(rows_written),0) "
                "FROM personal_history_segments "
                "WHERE dataset='equities_bars_daily' "
                "AND state IN ('OBSERVED','OBSERVED_EMPTY')"
            ).fetchone()[0]
        )
        compact_bars = int(
            self._connection.execute(
                "SELECT COUNT(*) FROM personal_history_compact_bars"
            ).fetchone()[0]
        )
        if expected_bars < 1 or compact_bars != expected_bars:
            raise PersonalHistoryError(
                "personal history compact bars do not match completed checkpoints"
            )
        master_mismatch = self._connection.execute(
            """
            SELECT 1 FROM personal_history_segments AS segments
            LEFT JOIN (
                SELECT snapshot_date,COUNT(*) AS row_count
                FROM personal_history_compact_master
                GROUP BY snapshot_date
            ) AS compact ON compact.snapshot_date=segments.query_start
            WHERE segments.dataset='equities_master'
              AND segments.state IN ('OBSERVED','OBSERVED_EMPTY')
              AND COALESCE(compact.row_count,0) <> segments.rows_written
            LIMIT 1
            """
        ).fetchone()
        if master_mismatch is not None:
            raise PersonalHistoryError(
                "personal history compact master snapshot counts do not match "
                "checkpoints"
            )
        day_mismatch = self._connection.execute(
            """
            SELECT 1 FROM personal_history_segments AS segments
            LEFT JOIN (
                SELECT date,COUNT(*) AS row_count
                FROM personal_history_compact_bars
                GROUP BY date
            ) AS bars ON bars.date=segments.query_start
            WHERE segments.dataset='equities_bars_daily'
              AND segments.state IN ('OBSERVED','OBSERVED_EMPTY')
              AND COALESCE(bars.row_count,0) <> segments.rows_written
            LIMIT 1
            """
        ).fetchone()
        if day_mismatch is not None:
            raise PersonalHistoryError(
                "personal history compact bar day counts do not match checkpoints"
            )
        compact_raw = int(
            self._connection.execute(
                """
                SELECT
                (SELECT COUNT(*) FROM personal_history_compact_master
                 WHERE trim(code)='' OR snapshot_date <> substr(event_time,1,10)
                   OR scale_category IS NULL OR trim(scale_category)='')
                +
                (SELECT COUNT(*) FROM personal_history_compact_bars
                 WHERE trim(code)='' OR close IS NULL
                   OR date <> substr(event_time,1,10))
                """
            ).fetchone()[0]
        )
        if compact_raw:
            raise PersonalHistoryError(
                "personal history compact rows violate compact PIT invariants"
            )
        self._assert_compact_v7_timestamps()
        for table in _TYPED_JQUANTS_TABLES:
            remaining = int(
                self._connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            )
            remaining += int(
                self._connection.execute(
                    f"SELECT COUNT(*) FROM {table}_revisions"
                ).fetchone()[0]
            )
            if remaining:
                raise PersonalHistoryError(
                    "personal history standard typed jquants tables must stay empty"
                )
        policies = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT DISTINCT pit_policy FROM personal_history_segments"
            )
        }
        expected = {
            CALENDAR_AVAILABILITY_POLICY,
            MASTER_AVAILABILITY_POLICY,
            FINS_AVAILABILITY_POLICY,
            BARS_AVAILABILITY_POLICY,
        }
        if policies != expected:
            raise PersonalHistoryError(
                f"personal history PIT policies are incomplete: {sorted(policies)}"
            )
        self._validate_shared_fins_scan_evidence()

    def _assert_compact_v7_timestamps(self) -> None:
        canonical_ingested = (
            "ingested_at IS NULL "
            "OR length(ingested_at) <> 25 "
            "OR ingested_at NOT GLOB '????-??-??T??:??:??+09:00'"
        )
        if self._connection.execute(
            """
            SELECT 1 FROM personal_history_compact_master
            WHERE available_at IS NOT snapshot_date || 'T08:00:00+09:00'
            LIMIT 1
            """
        ).fetchone() is not None:
            raise PersonalHistoryError(
                "personal history compact master available_at is not "
                "snapshot_date 08:00 JST"
            )
        if self._connection.execute(
            """
            SELECT 1 FROM personal_history_compact_master
            WHERE substr(event_time,1,10) IS NOT snapshot_date
            LIMIT 1
            """
        ).fetchone() is not None:
            raise PersonalHistoryError(
                "personal history compact master event_time date does not "
                "equal snapshot_date"
            )
        if self._connection.execute(
            f"""
            SELECT 1 FROM personal_history_compact_master
            WHERE {canonical_ingested}
               OR ingested_at < available_at
            LIMIT 1
            """
        ).fetchone() is not None:
            raise PersonalHistoryError(
                "personal history compact master ingested_at is not "
                "canonical or precedes available_at"
            )
        if self._connection.execute(
            """
            SELECT 1 FROM personal_history_compact_bars
            WHERE event_time IS NOT date || CASE
                    WHEN date < '2024-11-05' THEN 'T15:00:00+09:00'
                    ELSE 'T15:30:00+09:00'
                  END
               OR available_at IS NOT date || CASE
                    WHEN date < '2024-11-05' THEN 'T15:00:00+09:00'
                    ELSE 'T15:30:00+09:00'
                  END
            LIMIT 1
            """
        ).fetchone() is not None:
            raise PersonalHistoryError(
                "personal history compact bar timestamps are not the "
                "official session close"
            )
        if self._connection.execute(
            """
            SELECT 1 FROM personal_history_compact_bars
            WHERE substr(event_time,1,10) IS NOT date
               OR substr(available_at,1,10) IS NOT date
            LIMIT 1
            """
        ).fetchone() is not None:
            raise PersonalHistoryError(
                "personal history compact bar date does not match timestamps"
            )
        if self._connection.execute(
            f"""
            SELECT 1 FROM personal_history_compact_bars
            WHERE {canonical_ingested}
               OR ingested_at < available_at
            LIMIT 1
            """
        ).fetchone() is not None:
            raise PersonalHistoryError(
                "personal history compact bars ingested_at is not "
                "canonical or precedes available_at"
            )

    def hydrate(self) -> PersonalHistorySummary:
        self._outcomes = []
        self._new_segments = 0
        self._manifest_status("BUILDING")
        try:
            self._hydrate_calendar()
            self._checkpoint_wal()
            self._guard_capacity(phase="after calendar stage")
            trading = self._trading_days()
            bar_start, master_days = self._bar_and_master_days(trading)
            self._hydrate_master(master_days)
            self._checkpoint_wal()
            self._guard_capacity(phase="after master stage")
            scope_union = self._topix_union()
            self._hydrate_fins(scope_union)
            self._checkpoint_wal()
            self._guard_capacity(phase="after fins stage")
            self._hydrate_bars(bar_start=bar_start, trading=trading)
            self._checkpoint_wal()
            self._guard_capacity(phase="after bars stage")
            self._manifest_status("VALIDATING")
            self._validate_draft_boundary()
            hydrated_days = [
                str(row[0])
                for row in self._connection.execute(
                    "SELECT DISTINCT date FROM personal_history_compact_bars "
                    "ORDER BY date"
                )
            ]
            if not hydrated_days:
                raise PersonalHistoryError(
                    "personal history hydrated no bar sessions"
                )
            data_start = hydrated_days[0]
            requested_lookback = self.plan.lookback_sessions
            actual_lookback = sum(
                1 for day in hydrated_days if day < self.plan.period_start
            )
            self._manifest_status("COMPLETE_DRAFT")
            self._checkpoint_wal()
        except Exception as exc:
            self._manifest_status(
                "BUILDING", f"{type(exc).__name__}: {exc}"[:2000]
            )
            raise
        counts = {dataset: 0 for dataset in PERSONAL_HISTORY_DATASETS}
        for outcome in self._outcomes:
            counts[outcome.dataset] += 1
        return PersonalHistorySummary(
            period_start=self.plan.period_start,
            period_end=self.plan.period_end,
            bar_start=data_start,
            segment_counts=counts,
            fetched_rows=sum(outcome.fetched for outcome in self._outcomes),
            written_rows=sum(outcome.written for outcome in self._outcomes),
            skipped_segments=sum(outcome.skipped for outcome in self._outcomes),
            database_bytes=self._database_footprint(),
            actual_lookback_sessions=actual_lookback,
            lookback_truncated=actual_lookback < requested_lookback,
        )


__all__ = [
    "BARS_AVAILABILITY_POLICY",
    "CALENDAR_AVAILABILITY_POLICY",
    "DEFAULT_CALENDAR_WINDOW_DAYS",
    "DEFAULT_COMPACT_STORAGE_BYTES_PER_ROW",
    "DEFAULT_GENERIC_JSON_STORAGE_BYTES_PER_ROW",
    "DEFAULT_LOOKBACK_SESSIONS",
    "DEFAULT_MAX_DATABASE_BYTES",
    "FINS_AVAILABILITY_POLICY",
    "MASTER_AVAILABILITY_POLICY",
    "PERSONAL_COMPLETENESS_CLAIM",
    "PERSONAL_HISTORY_DATASETS",
    "PERSONAL_HISTORY_FORMAT",
    "PERSONAL_HISTORY_SCOPE_DIGEST",
    "PERSONAL_HISTORY_SCOPE_ID",
    "PERSONAL_HISTORY_SCOPE_VERSION",
    "PERSONAL_RESEARCH_STATE",
    "PersonalHistoryError",
    "PersonalHistoryHydrator",
    "PersonalHistoryPlan",
    "PersonalHistorySummary",
    "assert_personal_history_database",
    "build_personal_history_plan",
    "personal_snapshot_data_floor",
]
