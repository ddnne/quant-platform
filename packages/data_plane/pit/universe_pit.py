"""Shared PIT universe-day selector for Controlled and personal DRAFT.

Activation is ``max(event_time, available_at)`` with ``available_at``,
``event_time``, and ``ingested_at`` all ``<= as_of``.
Latest complete master snapshot wins, so a delisted code disappears. Product
policy (scale vs Prime, fins intersection) stays outside this module.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from data_contracts.identity import natural_key as contract_natural_key
from data_contracts.personal_history_compact import (
    compact_history_state,
    compact_rebuild_reason,
)
from data_contracts.personal_universe import canonical_topix_scale_category
from storage.schema import CATALOG_CODE_SQL

from .cooperative_deadline import check_deadline
from .errors import DatabaseNotFound, PitError
from .query import _scoped_read_connection, connect_readonly, normalize_as_of
from .read_clock import resolve_read_clock

_VersionIdentity = tuple[str, str, str]
_CATALOG_REQUIRED = {
    "source",
    "dataset",
    "natural_key",
    "event_time",
    "available_at",
    "ingested_at",
    "payload",
}


@dataclass(frozen=True, slots=True)
class UniverseMasterMember:
    code: str
    market_code: str
    scale_category: str


@dataclass(frozen=True, slots=True)
class UniverseDaySlice:
    decision_date: str
    as_of: str
    snapshot_date: str
    members: tuple[UniverseMasterMember, ...]
    fins_codes: frozenset[str]


def _parse_dt(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PitError(f"{label} is not an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise PitError(f"{label} must include a timezone")
    return parsed


def _decode_mapping(raw: Any, *, dataset_id: str) -> dict[str, Any]:
    payload: Any = raw
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise PitError(f"{dataset_id} payload is not canonical JSON") from exc
    if not isinstance(payload, Mapping):
        raise PitError(f"{dataset_id} payload is missing")
    return {str(key): value for key, value in payload.items()}


def _pick(payload: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _calendar_dates(start: str, end: str) -> tuple[str, ...]:
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    if cursor > stop:
        raise PitError("universe period is reversed")
    values: list[str] = []
    while cursor <= stop:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(values)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _require_catalog(conn: sqlite3.Connection, table: str) -> None:
    columns = _table_columns(conn, table)
    if not columns:
        if table == "jquants_records":
            raise PitError("universe requires canonical jquants_records")
        return
    if not _CATALOG_REQUIRED <= columns:
        raise PitError(f"universe requires canonical {table} schema")


_SNAPSHOT_DATE_SQL = (
    "COALESCE(CAST(json_extract(payload, '$.Date') AS TEXT), "
    "substr(event_time, 1, 10))"
)
_ACTIVATION_SQL = (
    "CASE WHEN event_time > available_at THEN event_time ELSE available_at END"
)


def _catalog_select(
    conn: sqlite3.Connection,
    *,
    table: str,
    dataset: str,
    last_as_of: str | None,
    period_start: str | None = None,
    period_end: str | None = None,
    extra_columns: str = "",
    extra_where: str | None = None,
    extra_params: Sequence[Any] = (),
    order_by: str | None = None,
    observed_through: str,
):
    if not _table_columns(conn, table):
        return ()
    where = [
        "source='jquants'",
        "dataset=?",
        "ingested_at IS NOT NULL",
        "ingested_at <= ?",
    ]
    params: list[Any] = [dataset, observed_through]
    if period_start:
        where.append("substr(event_time, 1, 10) >= ?")
        params.append(period_start)
    if period_end:
        where.append("substr(event_time, 1, 10) <= ?")
        params.append(period_end)
    if last_as_of is not None:
        where.extend(
            [
                "available_at IS NOT NULL",
                "event_time IS NOT NULL",
                "available_at <= ?",
                "event_time <= ?",
            ]
        )
        params.extend((last_as_of, last_as_of))
    if extra_where:
        where.append(f"({extra_where})")
        params.extend(extra_params)
    columns = (
        "source,dataset,natural_key,event_time,available_at,ingested_at,payload"
        + extra_columns
    )
    ranking = order_by or "event_time,natural_key,available_at,ingested_at"
    return conn.execute(
        f"SELECT {columns} FROM {table} WHERE "
        + " AND ".join(where)
        + f" ORDER BY {ranking}",
        params,
    )


@dataclass(frozen=True, slots=True)
class _Event:
    activation: datetime
    dataset: str
    identity: _VersionIdentity
    available: datetime
    ingested: datetime
    insertion: int
    calendar_date: str = ""
    holiday: str = ""
    snapshot_date: str = ""
    code: str = ""
    market_code: str = ""
    scale_category: str = ""


def _event_from_row(
    raw: Mapping[str, Any],
    *,
    insertion: int,
    dataset: str,
) -> _Event:
    payload = _decode_mapping(raw.get("payload"), dataset_id=dataset)
    expected = contract_natural_key(payload, dataset)
    natural_key = str(raw.get("natural_key") or "")
    if expected.startswith("hash:sha256:") or natural_key != expected:
        raise PitError(f"{dataset} natural key is missing or noncanonical")
    available = _parse_dt(raw.get("available_at"), label=f"{dataset}.available_at")
    event_time = _parse_dt(raw.get("event_time"), label=f"{dataset}.event_time")
    ingested = _parse_dt(raw.get("ingested_at"), label=f"{dataset}.ingested_at")
    calendar_date = ""
    holiday = ""
    snapshot_date = ""
    code = ""
    market_code = ""
    scale_category = ""
    if dataset == "markets_calendar":
        calendar_date = _pick(payload, "Date") or str(raw.get("event_time") or "")[:10]
        holiday = _pick(payload, "HolidayDivision", "HolDiv", "holiday_division")
    elif dataset == "equities_master":
        snapshot_date = (
            _pick(payload, "Date")
            or str(raw.get("snapshot_date") or "")[:10]
            or str(raw.get("event_time") or "")[:10]
        )
        code = _pick(payload, "Code", "code")
        market_code = _pick(payload, "MarketCode", "MktCode", "Mkt")
        scale_category = _pick(
            payload,
            "CanonicalScaleCategory",
            "ScaleCategory",
            "ScaleCat",
            "scale_category",
        )
    elif dataset == "fins_summary":
        code = _pick(payload, "Code", "code")
    return _Event(
        activation=max(event_time, available),
        dataset=dataset,
        identity=(str(raw.get("source") or "jquants"), dataset, natural_key),
        available=available,
        ingested=ingested,
        insertion=insertion,
        calendar_date=calendar_date,
        holiday=holiday,
        snapshot_date=snapshot_date,
        code=code,
        market_code=market_code,
        scale_category=scale_category,
    )


def _event_from_compact_master(raw: Mapping[str, Any], *, insertion: int) -> _Event:
    scale = str(raw.get("scale_category") or "").strip()
    source_scale = str(raw.get("source_scale_category") or "").strip()
    canonical = canonical_topix_scale_category(scale)
    if canonical is None:
        canonical = canonical_topix_scale_category(source_scale)
    payload = {
        "Code": str(raw.get("code") or "").strip(),
        "Date": str(raw.get("snapshot_date") or "")[:10],
        "MarketCode": str(raw.get("market_code") or "").strip(),
        "ScaleCategory": scale,
        "CanonicalScaleCategory": canonical or "",
    }
    wrapped = {
        "source": "jquants",
        "dataset": "equities_master",
        "natural_key": contract_natural_key(payload, "equities_master"),
        "event_time": raw.get("event_time"),
        "available_at": raw.get("available_at"),
        "ingested_at": raw.get("ingested_at"),
        "payload": payload,
    }
    return _event_from_row(wrapped, insertion=insertion, dataset="equities_master")


def _master_window(
    *,
    anchor: str | None,
    first_as_of: str,
    compact: bool,
) -> tuple[str, tuple[Any, ...]]:
    column = "snapshot_date" if compact else _SNAPSHOT_DATE_SQL
    if anchor:
        return f"{column} >= ?", (anchor,)
    return "(available_at > ? OR event_time > ?)", (first_as_of, first_as_of)


def _anchor_snapshot_date(
    conn: sqlite3.Connection,
    *,
    compact: bool,
    first_as_of: str,
    observed_through: str,
) -> str | None:
    dates: list[str] = []
    ingested_gate = " AND ingested_at IS NOT NULL AND ingested_at <= ?"
    ingested_params: tuple[str, ...] = (observed_through,)
    if compact:
        row = conn.execute(
            "SELECT MAX(snapshot_date) FROM personal_history_compact_master "
            "WHERE available_at IS NOT NULL AND event_time IS NOT NULL "
            "AND available_at <= ? AND event_time <= ?"
            + ingested_gate,
            (first_as_of, first_as_of, *ingested_params),
        ).fetchone()
        if row and row[0]:
            dates.append(str(row[0])[:10])
    else:
        for table in ("jquants_records", "jquants_records_revisions"):
            if not _table_columns(conn, table):
                continue
            row = conn.execute(
                f"SELECT MAX({_SNAPSHOT_DATE_SQL}) FROM {table} "
                "WHERE source='jquants' AND dataset='equities_master' "
                "AND available_at IS NOT NULL AND event_time IS NOT NULL "
                "AND available_at <= ? AND event_time <= ?"
                + ingested_gate,
                (first_as_of, first_as_of, *ingested_params),
            ).fetchone()
            if row and row[0]:
                dates.append(str(row[0])[:10])
    return max(dates) if dates else None


def _iter_fins_rows(
    conn: sqlite3.Connection, *, last_as_of: str, observed_through: str
):
    extra = f", {CATALOG_CODE_SQL} AS code"
    ranking = f"{_ACTIVATION_SQL},available_at,ingested_at,natural_key"
    selects: list[str] = []
    params: list[Any] = []
    ingested_sql = " AND ingested_at IS NOT NULL AND ingested_at <= ?"
    for table in ("jquants_records", "jquants_records_revisions"):
        if not _table_columns(conn, table):
            continue
        selects.append(
            "SELECT source,dataset,natural_key,event_time,available_at,"
            f"ingested_at,payload{extra} FROM {table} WHERE source='jquants' "
            "AND dataset=? AND available_at IS NOT NULL AND event_time IS NOT NULL "
            "AND available_at <= ? AND event_time <= ?"
            + ingested_sql
        )
        params.extend(("fins_summary", last_as_of, last_as_of, observed_through))
    if not selects:
        return ()
    return conn.execute(
        "SELECT * FROM (" + " UNION ALL ".join(selects) + f") ORDER BY {ranking}",
        params,
    )


def _activate_fins_row(
    raw: Mapping[str, Any],
    *,
    latest: dict[_VersionIdentity, tuple[datetime, datetime]],
    eligible_at: dict[str, datetime],
) -> None:
    event = _event_from_row(dict(raw), insertion=0, dataset="fins_summary")
    if event.code in eligible_at:
        return
    version = (event.available, event.ingested)
    previous = latest.get(event.identity)
    if previous is not None and version <= previous:
        return
    if event.code:
        eligible_at[event.code] = event.activation
        latest.pop(event.identity, None)
        return
    latest[event.identity] = version


def _iter_master_events(
    conn: sqlite3.Connection,
    *,
    compact: bool,
    first_as_of: str,
    last_as_of: str,
    observed_through: str,
):
    insertion = 0
    window_sql, window_params = _master_window(
        anchor=_anchor_snapshot_date(
            conn,
            compact=compact,
            first_as_of=first_as_of,
            observed_through=observed_through,
        ),
        first_as_of=first_as_of,
        compact=compact,
    )
    ranking = f"{_ACTIVATION_SQL},available_at,ingested_at,natural_key"
    ingested_sql = " AND ingested_at IS NOT NULL AND ingested_at <= ?"
    ingested_params: tuple[str, ...] = (observed_through,)
    if compact:
        rows = conn.execute(
            "SELECT snapshot_date,code,event_time,available_at,ingested_at,"
            "market_code,scale_category,source_scale_category "
            "FROM personal_history_compact_master "
            "WHERE available_at IS NOT NULL AND event_time IS NOT NULL "
            "AND available_at <= ? AND event_time <= ?"
            + ingested_sql
            + " AND "
            + window_sql
            + f" ORDER BY {_ACTIVATION_SQL},available_at,ingested_at,code",
            (last_as_of, last_as_of, *ingested_params, *window_params),
        )
        for raw in rows:
            yield _event_from_compact_master(dict(raw), insertion=insertion)
            insertion += 1
        return
    selects: list[str] = []
    params: list[Any] = []
    for table in ("jquants_records", "jquants_records_revisions"):
        if not _table_columns(conn, table):
            continue
        selects.append(
            (
                "SELECT source,dataset,natural_key,event_time,available_at,"
                "ingested_at,payload FROM {table} WHERE source='jquants' "
                "AND dataset=? AND available_at IS NOT NULL AND event_time IS NOT NULL "
                "AND available_at <= ? AND event_time <= ?"
                + ingested_sql
                + " AND ({window})"
            ).format(table=table, window=window_sql)
        )
        params.extend(("equities_master", last_as_of, last_as_of, *ingested_params, *window_params))
    if not selects:
        return
    for raw in conn.execute(
        "SELECT * FROM (" + " UNION ALL ".join(selects) + f") ORDER BY {ranking}",
        params,
    ):
        yield _event_from_row(dict(raw), insertion=insertion, dataset="equities_master")
        insertion += 1


def _compact_flag_from_connection(conn: sqlite3.Connection) -> bool:
    state = compact_history_state(conn)
    if state in {"invalid", "mixed"}:
        raise PitError(
            compact_rebuild_reason(conn)
            or "compact schema is invalid; rebuild as personal-draft-history/v8"
        )
    return state == "compact"


def _universe_day_slices_from_connection(
    conn: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    as_of_for_day: Mapping[str, str],
) -> tuple[UniverseDaySlice, ...]:
    """Resolve universe slices on an already-open verifier or READY connection.

    This is not a public opener. Callers that only have a path must use
    :func:`resolve_universe_day_slices`, which READY-gates the file.
    """

    requested = _calendar_dates(period_start, period_end)
    as_ofs = {
        day: _parse_dt(as_of_for_day[day], label="decision_as_of")
        for day in requested
    }
    first_as_of = normalize_as_of(min(as_of_for_day[day] for day in requested))
    last_as_of = normalize_as_of(max(as_of_for_day[day] for day in requested))
    try:
        check_deadline()
        compact = _compact_flag_from_connection(conn)
        clock = resolve_read_clock(last_as_of, conn=conn)
        observed_through = clock.observed_through
        _require_catalog(conn, "jquants_records")
        _require_catalog(conn, "jquants_records_revisions")
        calendar_events: list[_Event] = []
        present_days: set[str] = set()
        insertion = 0
        for table in ("jquants_records", "jquants_records_revisions"):
            for raw in _catalog_select(
                conn,
                table=table,
                dataset="markets_calendar",
                last_as_of=None,
                period_start=period_start,
                period_end=period_end,
                observed_through=observed_through,
            ):
                event = _event_from_row(
                    dict(raw), insertion=insertion, dataset="markets_calendar"
                )
                insertion += 1
                present_days.add(event.calendar_date)
                calendar_events.append(event)
        for day in requested:
            if day not in present_days:
                raise PitError(f"markets_calendar is missing required date {day}")
        calendar_events.sort(
            key=lambda item: (
                item.activation,
                item.identity,
                item.available,
                item.ingested,
                item.insertion,
            )
        )
        check_deadline()
        fins_eligible_at: dict[str, datetime] = {}
        latest_fins: dict[_VersionIdentity, tuple[datetime, datetime]] = {}
        for raw in _iter_fins_rows(
            conn, last_as_of=last_as_of, observed_through=observed_through
        ):
            _activate_fins_row(
                raw, latest=latest_fins, eligible_at=fins_eligible_at
            )
        latest_fins.clear()
        master_iter = iter(
            _iter_master_events(
                conn,
                compact=bool(compact),
                first_as_of=first_as_of,
                last_as_of=last_as_of,
                observed_through=observed_through,
            )
        )
        calendar_by_day: dict[str, dict[_VersionIdentity, _Event]] = {}
        calendar_latest: dict[_VersionIdentity, _Event] = {}
        master_latest: dict[_VersionIdentity, _Event] = {}
        current_snapshot = ""
        current_members: dict[_VersionIdentity, _Event] = {}

        def activate_calendar(event: _Event) -> None:
            previous = calendar_latest.get(event.identity)
            version = (event.available, event.ingested)
            if previous is not None and version <= (
                previous.available,
                previous.ingested,
            ):
                return
            if previous is not None:
                bucket = calendar_by_day.get(previous.calendar_date)
                if bucket is not None:
                    bucket.pop(previous.identity, None)
                    if not bucket:
                        del calendar_by_day[previous.calendar_date]
            calendar_latest[event.identity] = event
            calendar_by_day.setdefault(event.calendar_date, {})[
                event.identity
            ] = event

        calendar_index = 0
        master_event = next(master_iter, None)

        def next_due() -> _Event | None:
            nonlocal calendar_index, master_event
            calendar_item = (
                calendar_events[calendar_index]
                if calendar_index < len(calendar_events)
                else None
            )
            if calendar_item is None and master_event is None:
                return None
            if master_event is None or (
                calendar_item is not None
                and (
                    calendar_item.activation,
                    calendar_item.dataset,
                    calendar_item.identity,
                )
                <= (
                    master_event.activation,
                    master_event.dataset,
                    master_event.identity,
                )
            ):
                calendar_index += 1
                return calendar_item
            due = master_event
            master_event = next(master_iter, None)
            return due

        due = next_due()
        slices: list[UniverseDaySlice] = []
        member_intern: dict[tuple[str, str, str], UniverseMasterMember] = {}
        interned_members: tuple[UniverseMasterMember, ...] | None = None
        interned_fins: frozenset[str] | None = None
        members_dirty = True
        fins_by_activation = sorted(
            fins_eligible_at.items(), key=lambda item: (item[1], item[0])
        )
        fins_index = 0
        eligible_fins: list[str] = []
        saw_trading_day = False

        def activate_master(event: _Event) -> None:
            nonlocal current_snapshot, members_dirty
            previous = master_latest.get(event.identity)
            version = (event.available, event.ingested)
            if previous is not None and version <= (
                previous.available,
                previous.ingested,
            ):
                return
            members_dirty = True
            if previous is not None and previous.snapshot_date == current_snapshot:
                current_members.pop(previous.identity, None)
            master_latest[event.identity] = event
            if not current_snapshot or event.snapshot_date > current_snapshot:
                current_snapshot = event.snapshot_date
                current_members.clear()
                for identity, held in list(master_latest.items()):
                    if held.snapshot_date != current_snapshot:
                        master_latest.pop(identity, None)
                    else:
                        current_members[identity] = held
                return
            if event.snapshot_date == current_snapshot:
                current_members[event.identity] = event

        for day in requested:
            check_deadline()
            as_of = as_ofs[day]
            while due is not None and due.activation <= as_of:
                if due.dataset == "markets_calendar":
                    activate_calendar(due)
                else:
                    activate_master(due)
                due = next_due()
            visible_calendar = calendar_by_day.get(day)
            if not visible_calendar:
                raise PitError(f"markets_calendar row for {day} is not PIT-visible")
            if len(visible_calendar) != 1:
                raise PitError(
                    f"markets_calendar has duplicate natural keys for {day}"
                )
            calendar_event = next(iter(visible_calendar.values()))
            if calendar_event.holiday != "1":
                continue
            saw_trading_day = True
            if not current_snapshot or not current_members:
                raise PitError(
                    f"equities_master has no PIT-visible snapshot for {day}"
                )
            while (
                fins_index < len(fins_by_activation)
                and fins_by_activation[fins_index][1] <= as_of
            ):
                eligible_fins.append(fins_by_activation[fins_index][0])
                fins_index += 1
                interned_fins = None
            if interned_fins is None:
                interned_fins = frozenset(eligible_fins)
            if members_dirty or interned_members is None:
                members: list[UniverseMasterMember] = []
                seen: set[str] = set()
                for event in current_members.values():
                    if not event.code or event.code in seen:
                        raise PitError(
                            f"equities_master snapshot {current_snapshot} "
                            "has invalid code identity"
                        )
                    seen.add(event.code)
                    identity = (
                        event.code,
                        event.market_code,
                        event.scale_category,
                    )
                    held = member_intern.get(identity)
                    if held is None:
                        held = UniverseMasterMember(
                            code=event.code,
                            market_code=event.market_code,
                            scale_category=event.scale_category,
                        )
                        member_intern[identity] = held
                    members.append(held)
                members.sort(key=lambda item: item.code)
                interned_members = tuple(members)
                members_dirty = False
            slices.append(
                UniverseDaySlice(
                    decision_date=day,
                    as_of=normalize_as_of(as_of_for_day[day]),
                    snapshot_date=current_snapshot,
                    members=interned_members,
                    fins_codes=interned_fins,
                )
            )
        if not saw_trading_day:
            raise PitError("universe has no trading dates")
        return tuple(slices)
    except PitError:
        raise
    except (DatabaseNotFound, sqlite3.Error) as exc:
        raise PitError("universe snapshot query failed") from exc


def resolve_universe_day_slices(
    db_path: Any,
    *,
    period_start: str,
    period_end: str,
    as_of_for_day: Mapping[str, str],
) -> tuple[UniverseDaySlice, ...]:
    """Return PIT-visible trading-day master/fins facts for one period."""

    source = Path(db_path).resolve()
    if not source.is_file():
        raise PitError(f"universe snapshot is missing: {source}")
    conn = _scoped_read_connection(source)
    close_connection = conn is None
    try:
        if conn is None:
            conn = connect_readonly(source)
        return _universe_day_slices_from_connection(
            conn,
            period_start=period_start,
            period_end=period_end,
            as_of_for_day=as_of_for_day,
        )
    finally:
        if close_connection and conn is not None:
            conn.close()


__all__ = [
    "UniverseDaySlice",
    "UniverseMasterMember",
    "resolve_universe_day_slices",
]
