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

* :func:`get_equity_master`      -> ``jquants_listed_info``
* :func:`get_equity_bars_daily`  -> ``jquants_daily_bars``
* :func:`get_market_calendar`    -> ``jquants_market_calendar``
* :func:`get_jquants_records`    -> ``jquants_records`` (generic, by ``dataset``)
* :func:`get_jsda_bond_trades`   -> ``jsda_bond_trades``
"""

from __future__ import annotations

from typing import Any

from ingestion.common.timeutil import parse_date_str, parse_dt, to_iso

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

    The generic table holds every catalog dataset that is not one of the three
    curated series (fins, indices, derivatives, markets analytics, EDINET,
    minute/tick/TDnet add-ons — see ``ingestion.jquants.catalog.DATASETS``).
    It is partitioned by ``dataset``, which is therefore **required** here.

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
