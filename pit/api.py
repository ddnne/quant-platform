"""Public point-in-time (PIT) read API.

Every function requires ``as_of`` and returns a :class:`~pit.models.PitResult`
whose rows satisfy ``available_at <= as_of`` (NULL ``available_at`` excluded).
This is the **sole read path for structured facts** — research, features and
strategy code must go through here, never direct SQLite. No writes, no
external HTTP.

Default DB is ``data/structured/ingestion.sqlite`` (relative to cwd, i.e. the
repo root in normal use); override per-call with ``db_path=``. Connections are
opened read-only (``mode=ro``).

Tables (see :mod:`storage.schema`):

* :func:`get_equity_master`      -> ``jquants_listed_info`` plus the
  ``equities_master`` partition of ``jquants_records``
* :func:`get_equity_bars_daily`  -> ``jquants_daily_bars`` plus the
  ``equities_bars_daily`` partition of ``jquants_records``
* :func:`get_market_calendar`    -> ``jquants_market_calendar`` plus the
  ``markets_calendar`` partition of ``jquants_records``
* :func:`get_jquants_records`    -> ``jquants_records`` (generic, by ``dataset``)
* :func:`get_jsda_bond_trades`   -> ``jsda_bond_trades``
"""

from __future__ import annotations

from typing import Any

from ingestion.common.timeutil import parse_date_str, parse_dt, to_iso
from ingestion.jquants.normalize import (
    normalize_daily_bars,
    normalize_listed_info,
    normalize_market_calendar,
)

from .errors import InvalidDataset
from .models import PIT_API_VERSION, PitResult
from .query import _NOT_GIVEN, normalize_as_of, run_query

__all__ = [
    "get_equity_master",
    "get_equity_bars_daily",
    "get_market_calendar",
    "get_jquants_records",
    "get_jsda_bond_trades",
    "PitResult",
    "PIT_API_VERSION",
]


def _result(
    rows: list[dict[str, Any]],
    *,
    as_of: str,
    table: str,
    source: str | None = None,
    dataset: str | None = None,
) -> PitResult:
    """Build a :class:`PitResult` with standard provenance metadata."""
    md: dict[str, Any] = {
        "as_of": as_of,
        "table": table,
        "count": len(rows),
        "pit_api_version": PIT_API_VERSION,
    }
    if source is not None:
        md["source"] = source
    if dataset is not None:
        md["dataset"] = dataset
    return PitResult(rows=rows, metadata=md)


def _date_bound(value: Any) -> str:
    """Normalize a date-ish bound to ``YYYY-MM-DD`` for date-column filters."""
    return parse_date_str(str(value))


def _event_time_bound(value: Any) -> str:
    """Normalize a datetime-ish bound to canonical JST ISO (for ``event_time``)."""
    return to_iso(parse_dt(str(value)))


def _catalog_partition_rows(
    db_path: Any,
    *,
    as_of: str,
    dataset: str,
    clauses: list[str] | None = None,
    params: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Read one catalog partition through the same mandatory PIT gate."""
    where = ["dataset = ?", *(clauses or [])]
    bound: list[Any] = [dataset, *(params or [])]
    return run_query(
        db_path,
        as_of=as_of,
        table="jquants_records",
        extra_where=" AND ".join(where),
        params=bound,
        order_by="event_time, natural_key",
    )


def _catalog_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    """Return the decoded source payload from a generic catalog row."""
    for name in ("payload", "raw_payload"):
        value = row.get(name)
        if isinstance(value, dict):
            return value
    return None


def _latest_rows(
    rows: list[dict[str, Any]], *, key_fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Deduplicate legacy/catalog rows at their shared curated business key."""
    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(field) for field in key_fields)
        previous = latest.get(key)
        version = (row.get("available_at") or "", row.get("ingested_at") or "")
        if previous is None or version > (
            previous.get("available_at") or "",
            previous.get("ingested_at") or "",
        ):
            latest[key] = row
    return list(latest.values())


def _catalog_daily_bars(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map generic ``equities_bars_daily`` rows to the curated bar schema."""
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = _catalog_payload(row)
        if payload is None:
            continue
        normalized = normalize_daily_bars(
            [payload],
            ingested_at=row["ingested_at"],
            available_at=row["available_at"],
        )
        if normalized:
            normalized[0]["raw_payload"] = payload
            out.append(normalized[0])
    return out


def _catalog_equity_master(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map generic ``equities_master`` rows to the curated master schema."""
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = _catalog_payload(row)
        if payload is None:
            continue
        snapshot_date = str(payload.get("Date") or row["event_time"])[:10]
        normalized = normalize_listed_info(
            [payload],
            ingested_at=row["ingested_at"],
            available_at=row["available_at"],
            snapshot_date=snapshot_date,
        )
        if normalized:
            normalized[0]["raw_payload"] = payload
            out.append(normalized[0])
    return out


def _catalog_market_calendar(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map generic ``markets_calendar`` rows to the curated calendar schema."""
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = _catalog_payload(row)
        if payload is None:
            continue
        normalized = normalize_market_calendar(
            [payload],
            ingested_at=row["ingested_at"],
            available_at=row["available_at"],
        )
        if normalized:
            normalized[0]["raw_payload"] = payload
            out.append(normalized[0])
    return out


def get_equity_master(
    as_of: Any = _NOT_GIVEN, code: str | None = None, *, db_path: Any = None
) -> PitResult:
    """Point-in-time listed-equity master snapshots (``jquants_listed_info``).

    Returns every master snapshot row whose ``available_at <= as_of``. Because
    the table's natural key includes ``snapshot_date``, multiple snapshots of
    a code may be returned (ordered by ``code, snapshot_date``); callers that
    want the *latest-known-as-of* snapshot should take the last row per code.

    ``code`` optionally restricts to a single issue (e.g. ``"8697"``).
    """
    as_of_iso = normalize_as_of(as_of)
    extra_where: str | None = None
    params: list[Any] = []
    if code is not None:
        extra_where, params = "code = ?", [code]
    rows = run_query(
        db_path,
        as_of=as_of_iso,
        table="jquants_listed_info",
        extra_where=extra_where,
        params=params,
        order_by="code, snapshot_date",
    )
    catalog_clauses: list[str] = []
    catalog_params: list[Any] = []
    if code is not None:
        catalog_clauses.append("natural_key LIKE ?")
        catalog_params.append(f'%"Code": "{code}"%')
    catalog = _catalog_partition_rows(
        db_path,
        as_of=as_of_iso,
        dataset="equities_master",
        clauses=catalog_clauses,
        params=catalog_params,
    )
    rows = _latest_rows(
        [*rows, *_catalog_equity_master(catalog)],
        key_fields=("source", "code", "snapshot_date"),
    )
    rows.sort(
        key=lambda row: (row.get("code") or "", row.get("snapshot_date") or "")
    )
    return _result(rows, as_of=as_of_iso, table="jquants_listed_info", source="jquants")


def get_equity_bars_daily(
    as_of: Any = _NOT_GIVEN,
    code: str | None = None,
    from_event: Any = None,
    to_event: Any = None,
    *,
    db_path: Any = None,
) -> PitResult:
    """Point-in-time daily OHLCV bars (``jquants_daily_bars``).

    Returns every bar row whose ``available_at <= as_of``. ``from_event`` /
    ``to_event`` are additive bounds on the trading **date**
    (``YYYY-MM-DD``; flexible inputs like ``"2025/04/01"`` or a full datetime
    are accepted and reduced to the date). ``code`` optionally restricts to a
    single issue. Ordered by ``code, date``.
    """
    as_of_iso = normalize_as_of(as_of)
    clauses: list[str] = []
    params: list[Any] = []
    if code is not None:
        clauses.append("code = ?")
        params.append(code)
    if from_event is not None:
        clauses.append("date >= ?")
        params.append(_date_bound(from_event))
    if to_event is not None:
        clauses.append("date <= ?")
        params.append(_date_bound(to_event))
    rows = run_query(
        db_path,
        as_of=as_of_iso,
        table="jquants_daily_bars",
        extra_where=" AND ".join(clauses) if clauses else None,
        params=params,
        order_by="code, date",
    )
    catalog_clauses: list[str] = []
    catalog_params: list[Any] = []
    if code is not None:
        catalog_clauses.append("natural_key LIKE ?")
        catalog_params.append(f'%"Code": "{code}"%')
    if from_event is not None:
        catalog_clauses.append("substr(event_time, 1, 10) >= ?")
        catalog_params.append(_date_bound(from_event))
    if to_event is not None:
        catalog_clauses.append("substr(event_time, 1, 10) <= ?")
        catalog_params.append(_date_bound(to_event))
    catalog = _catalog_partition_rows(
        db_path,
        as_of=as_of_iso,
        dataset="equities_bars_daily",
        clauses=catalog_clauses,
        params=catalog_params,
    )
    rows = _latest_rows(
        [*rows, *_catalog_daily_bars(catalog)],
        key_fields=("source", "code", "date"),
    )
    rows.sort(key=lambda row: (row.get("code") or "", row.get("date") or ""))
    return _result(rows, as_of=as_of_iso, table="jquants_daily_bars", source="jquants")


def get_market_calendar(
    as_of: Any = _NOT_GIVEN,
    from_date: Any = None,
    to_date: Any = None,
    *,
    db_path: Any = None,
) -> PitResult:
    """Point-in-time market calendar (``jquants_market_calendar``).

    Returns every calendar row whose ``available_at <= as_of``. ``from_date``
    / ``to_date`` are additive bounds on the calendar ``date``
    (``YYYY-MM-DD``; flexible inputs accepted). Ordered by ``date``.
    """
    as_of_iso = normalize_as_of(as_of)
    clauses: list[str] = []
    params: list[Any] = []
    if from_date is not None:
        clauses.append("date >= ?")
        params.append(_date_bound(from_date))
    if to_date is not None:
        clauses.append("date <= ?")
        params.append(_date_bound(to_date))
    rows = run_query(
        db_path,
        as_of=as_of_iso,
        table="jquants_market_calendar",
        extra_where=" AND ".join(clauses) if clauses else None,
        params=params,
        order_by="date",
    )
    catalog_clauses: list[str] = []
    catalog_params: list[Any] = []
    if from_date is not None:
        catalog_clauses.append("substr(event_time, 1, 10) >= ?")
        catalog_params.append(_date_bound(from_date))
    if to_date is not None:
        catalog_clauses.append("substr(event_time, 1, 10) <= ?")
        catalog_params.append(_date_bound(to_date))
    catalog = _catalog_partition_rows(
        db_path,
        as_of=as_of_iso,
        dataset="markets_calendar",
        clauses=catalog_clauses,
        params=catalog_params,
    )
    rows = _latest_rows(
        [*rows, *_catalog_market_calendar(catalog)],
        key_fields=("source", "date"),
    )
    rows.sort(key=lambda row: row.get("date") or "")
    return _result(rows, as_of=as_of_iso, table="jquants_market_calendar", source="jquants")


def get_jquants_records(
    as_of: Any = _NOT_GIVEN,
    dataset: Any = _NOT_GIVEN,
    code: str | None = None,
    from_event: Any = None,
    to_event: Any = None,
    *,
    db_path: Any = None,
) -> PitResult:
    """Point-in-time generic J-Quants records (``jquants_records``).

    Catalog-mode ingestion stores every requested dataset here, including the
    three series that also have legacy curated tables (plus fins, indices,
    derivatives, markets analytics, EDINET, minute/tick/TDnet add-ons — see
    ``ingestion.jquants.catalog.DATASETS``). It is partitioned by ``dataset``,
    which is therefore **required** here.

    * ``dataset`` (required): the catalog dataset id (e.g. ``"fins_dividend"``).
    * ``code``: best-effort filter on the natural key's canonical ``"Code"``
      field via ``LIKE``. Datasets without a ``Code`` key simply yield nothing
      for a given ``code`` — filter on the decoded payload in that case.
    * ``from_event`` / ``to_event``: additive bounds on ``event_time``
      (canonical JST ISO; flexible inputs accepted and normalized).

    Ordered by ``event_time, natural_key``.
    """
    as_of_iso = normalize_as_of(as_of)
    if dataset is None or dataset is _NOT_GIVEN or (
        isinstance(dataset, str) and not dataset.strip()
    ):
        raise InvalidDataset(
            "dataset is required for get_jquants_records (the generic "
            "jquants_records table is partitioned by dataset). See "
            "ingestion.jquants.catalog.DATASETS for valid ids."
        )
    clauses: list[str] = ["dataset = ?"]
    params: list[Any] = [dataset]
    if code is not None:
        # natural_key is json.dumps(..., sort_keys=True) so the canonical
        # "Code" field serializes as `"Code": "<code>"` — match it with LIKE.
        clauses.append("natural_key LIKE ?")
        params.append(f'%"Code": "{code}"%')
    if from_event is not None:
        clauses.append("event_time >= ?")
        params.append(_event_time_bound(from_event))
    if to_event is not None:
        clauses.append("event_time <= ?")
        params.append(_event_time_bound(to_event))
    rows = run_query(
        db_path,
        as_of=as_of_iso,
        table="jquants_records",
        extra_where=" AND ".join(clauses),
        params=params,
        order_by="event_time, natural_key",
    )
    return _result(
        rows, as_of=as_of_iso, table="jquants_records", source="jquants", dataset=dataset
    )


def get_jsda_bond_trades(
    as_of: Any = _NOT_GIVEN,
    isin: str | None = None,
    from_event: Any = None,
    to_event: Any = None,
    *,
    db_path: Any = None,
) -> PitResult:
    """Point-in-time JSDA public/Corporate bond trade statistics (``jsda_bond_trades``).

    Returns every trade row whose ``available_at <= as_of``. ``isin``
    optionally restricts to a single bond; ``from_event`` / ``to_event`` are
    additive bounds on ``trade_date`` (``YYYY-MM-DD``; flexible inputs
    accepted). Ordered by ``trade_date, isin``.
    """
    as_of_iso = normalize_as_of(as_of)
    clauses: list[str] = []
    params: list[Any] = []
    if isin is not None:
        clauses.append("isin = ?")
        params.append(isin)
    if from_event is not None:
        clauses.append("trade_date >= ?")
        params.append(_date_bound(from_event))
    if to_event is not None:
        clauses.append("trade_date <= ?")
        params.append(_date_bound(to_event))
    rows = run_query(
        db_path,
        as_of=as_of_iso,
        table="jsda_bond_trades",
        extra_where=" AND ".join(clauses) if clauses else None,
        params=params,
        order_by="trade_date, isin",
    )
    return _result(rows, as_of=as_of_iso, table="jsda_bond_trades", source="jsda")
