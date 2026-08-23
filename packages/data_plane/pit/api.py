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
* :func:`get_jsda_repo_rates`    -> ``jsda_repo_rates``
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Mapping

from data_contracts.source_capability import (
    apply_official_query_clamp,
    source_capability_contract_for,
)
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
    "get_jsda_repo_rates",
    "PitResult",
    "PIT_API_VERSION",
]

# Contract keys are compact canonical JSON when complete and a non-JSON
# ``hash:sha256:...`` token when any discriminator is absent.  Code filtering
# therefore reads the key when possible and falls back to retained payloads.
_CATALOG_CODE_SQL = """COALESCE(
    CASE WHEN json_valid(natural_key)
         THEN CAST(json_extract(natural_key, '$.Code') AS TEXT) END,
    CASE WHEN json_valid(payload)
         THEN CAST(json_extract(payload, '$.Code') AS TEXT) END,
    CASE WHEN json_valid(raw_payload)
         THEN CAST(json_extract(raw_payload, '$.Code') AS TEXT) END
)"""

_PAGE_CURSOR_VERSION = 1
_MAX_PAGE_SIZE = 1_000
_JQUANTS_PAGE_ORDER = ("event_time", "natural_key", "source")


def _result(
    rows: list[dict[str, Any]],
    *,
    as_of: str,
    table: str,
    source: str | None = None,
    dataset: str | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
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
    if extra_metadata:
        md.update(extra_metadata)
    return PitResult(rows=rows, metadata=md)


def _page_query_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _encode_page_token(
    *,
    snapshot_id: str | None,
    query_hash: str,
    last_row: Mapping[str, Any],
) -> str:
    payload = {
        "version": _PAGE_CURSOR_VERSION,
        "snapshot_id": snapshot_id,
        "query_hash": query_hash,
        "last_event_time": last_row["event_time"],
        "last_natural_key": last_row["natural_key"],
        "last_source": last_row["source"],
    }
    return base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def _decode_page_token(
    token: str,
    *,
    snapshot_id: str | None,
    query_hash: str,
) -> tuple[str, str, str]:
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        )
        if not isinstance(payload, dict):
            raise ValueError
        if payload.get("version") != _PAGE_CURSOR_VERSION:
            raise ValueError
        if payload.get("snapshot_id") != snapshot_id:
            raise ValueError
        if payload.get("query_hash") != query_hash:
            raise ValueError
        values = (
            payload["last_event_time"],
            payload["last_natural_key"],
            payload["last_source"],
        )
        if not all(isinstance(value, str) for value in values):
            raise ValueError
        return values
    except Exception as exc:
        raise ValueError("invalid or mismatched page_token") from exc


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

    ``snapshot_date`` is clipped to SourceCapabilityContract
    ``earliest_official_availability`` (2008-05-07 for equities_master).
    Pre-official dates are vendor-misdate, not required history. The PIT
    ``as_of`` used for ``available_at <= as_of`` is not rewritten.

    ``code`` optionally restricts to a single issue (e.g. ``"8697"``).
    """
    as_of_iso = normalize_as_of(as_of)
    contract = source_capability_contract_for("equities_master")
    # Floor snapshot/query dates; keep original as_of for the available_at gate.
    official_start = apply_official_query_clamp(
        min(as_of_iso[:10], contract.earliest_official_availability),
        contract,
    )
    extra_where = "snapshot_date >= ?"
    params: list[Any] = [official_start]
    if code is not None:
        extra_where += " AND code = ?"
        params.append(code)
    rows = run_query(
        db_path,
        as_of=as_of_iso,
        table="jquants_listed_info",
        extra_where=extra_where,
        params=params,
        order_by="code, snapshot_date",
    )
    catalog_clauses: list[str] = ["substr(event_time, 1, 10) >= ?"]
    catalog_params: list[Any] = [official_start]
    if code is not None:
        catalog_clauses.append(f"{_CATALOG_CODE_SQL} = ?")
        catalog_params.append(code)
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
    rows = [
        row
        for row in rows
        if str(row.get("snapshot_date") or "")[:10] >= official_start
    ]
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
    codes: tuple[str, ...] | list[str] | set[str] | None = None,
    db_path: Any = None,
) -> PitResult:
    """Point-in-time daily OHLCV bars (``jquants_daily_bars``).

    Returns every bar row whose ``available_at <= as_of``. ``from_event`` /
    ``to_event`` are additive bounds on the trading **date**
    (``YYYY-MM-DD``; flexible inputs like ``"2025/04/01"`` or a full datetime
    are accepted and reduced to the date). ``code`` optionally restricts to a
    single issue; ``codes`` accepts multiple issues for efficient batched
    reads. They are mutually exclusive. Ordered by ``code, date``.
    """
    as_of_iso = normalize_as_of(as_of)
    if code is not None and codes is not None:
        raise ValueError("code and codes are mutually exclusive")
    requested_codes: list[str] | None
    if code is not None:
        requested_codes = [code]
    elif codes is not None:
        requested_codes = sorted({str(value) for value in codes})
    else:
        requested_codes = None
    clauses: list[str] = []
    params: list[Any] = []
    if requested_codes is not None:
        if requested_codes:
            placeholders = ",".join("?" for _ in requested_codes)
            clauses.append(f"code IN ({placeholders})")
            params.extend(requested_codes)
        else:
            clauses.append("0")
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
    if requested_codes is not None:
        if requested_codes:
            placeholders = ",".join("?" for _ in requested_codes)
            catalog_clauses.append(f"{_CATALOG_CODE_SQL} IN ({placeholders})")
            catalog_params.extend(requested_codes)
        else:
            catalog_clauses.append("0")
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
    natural_key: str | None = None,
    db_path: Any = None,
    page_size: int | None = None,
    page_token: str | None = None,
    snapshot_id: str | None = None,
) -> PitResult:
    """Point-in-time generic J-Quants records (``jquants_records``).

    Catalog-mode ingestion stores every requested dataset here, including the
    three series that also have legacy curated tables (plus fins, indices,
    derivatives, markets analytics, EDINET, minute/tick/TDnet add-ons — see
    ``ingestion.jquants.catalog.DATASETS``). It is partitioned by ``dataset``,
    which is therefore **required** here.

    * ``dataset`` (required): the catalog dataset id (e.g. ``"fins_dividend"``).
    * ``code``: filter on canonical ``natural_key.Code`` with payload fallback
      for SHA-256 fallback keys or datasets whose identity has no Code field.
    * ``from_event`` / ``to_event``: additive bounds on ``event_time``
      (canonical JST ISO; flexible inputs accepted and normalized).

    Ordered by the stable keyset ``event_time, natural_key, source``. Passing
    ``page_size`` makes pagination execute in SQL with ``LIMIT page_size+1``;
    the returned ``metadata.next_page_token`` is bound to the complete query
    and, when supplied, the immutable ``snapshot_id``. Omitting pagination
    preserves the original unbounded PIT API behavior for local research
    callers.
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
    dataset_value = str(dataset)
    clauses: list[str] = ["dataset = ?"]
    params: list[Any] = [dataset_value]
    if natural_key is not None:
        clauses.append("natural_key = ?")
        params.append(natural_key)
    if code is not None:
        clauses.append(f"{_CATALOG_CODE_SQL} = ?")
        params.append(code)
    from_event_iso: str | None = None
    to_event_iso: str | None = None
    if from_event is not None:
        from_event_iso = _event_time_bound(from_event)
        clauses.append("event_time >= ?")
        params.append(from_event_iso)
    if to_event is not None:
        to_event_iso = _event_time_bound(to_event)
        clauses.append("event_time <= ?")
        params.append(to_event_iso)

    size: int | None = None
    query_hash: str | None = None
    keyset_after: tuple[tuple[str, ...], tuple[Any, ...]] | None = None
    sql_limit: int | None = None
    if page_size is None:
        if page_token is not None:
            raise ValueError("page_size is required when page_token is supplied")
    else:
        try:
            size = int(page_size)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"page_size must be between 1 and {_MAX_PAGE_SIZE}"
            ) from exc
        if not 1 <= size <= _MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {_MAX_PAGE_SIZE}")
        query_hash = _page_query_hash({
            "cursor_version": _PAGE_CURSOR_VERSION,
            "snapshot_id": snapshot_id,
            "as_of": as_of_iso,
            "dataset": dataset_value,
            "code": code,
            "natural_key": natural_key,
            "from_event": from_event_iso,
            "to_event": to_event_iso,
            "page_size": size,
        })
        if page_token is not None:
            last_keys = _decode_page_token(
                page_token,
                snapshot_id=snapshot_id,
                query_hash=query_hash,
            )
            keyset_after = (_JQUANTS_PAGE_ORDER, last_keys)
        sql_limit = size + 1
    rows = run_query(
        db_path,
        as_of=as_of_iso,
        table="jquants_records",
        extra_where=" AND ".join(clauses),
        params=params,
        order_by=", ".join(_JQUANTS_PAGE_ORDER),
        keyset_after=keyset_after,
        limit=sql_limit,
    )
    page_metadata: dict[str, Any] | None = None
    if size is not None:
        has_more = len(rows) > size
        rows = rows[:size]
        next_page_token = None
        if has_more and rows:
            assert query_hash is not None
            next_page_token = _encode_page_token(
                snapshot_id=snapshot_id,
                query_hash=query_hash,
                last_row=rows[-1],
            )
        page_metadata = {
            "page_size": size,
            "next_page_token": next_page_token,
        }
    return _result(
        rows,
        as_of=as_of_iso,
        table="jquants_records",
        source="jquants",
        dataset=dataset_value,
        extra_metadata=page_metadata,
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


def get_jsda_repo_rates(
    as_of: Any = _NOT_GIVEN,
    tenor: str | None = None,
    rate_type: str | None = None,
    from_event: Any = None,
    to_event: Any = None,
    *,
    db_path: Any = None,
) -> PitResult:
    """Point-in-time JSDA repo rates (``jsda_repo_rates``).

    Returns every observation whose ``available_at <= as_of``. ``tenor`` and
    ``rate_type`` optionally select a series; ``from_event`` / ``to_event``
    are additive bounds on ``as_of_date`` (``YYYY-MM-DD``; flexible inputs
    accepted). Ordered by ``as_of_date, tenor, rate_type``.

    Fail-closed while production READY is undeclared (``SnapshotNotReady``).
    Coverage V2 COMPLETE for ``jsda_tokyo_repo_rates`` is receipt-owned
    (quant-mcp). D1 holds the hot tip only. Historical research eval must
    use ``research.eval_loaders.load_repo_rows_all_tenors_from_sqlite``
    against local sqlite / R2 — do not invent COMPLETE, do not ffill.
    """
    as_of_iso = normalize_as_of(as_of)
    clauses: list[str] = []
    params: list[Any] = []
    if tenor is not None:
        clauses.append("tenor = ?")
        params.append(tenor)
    if rate_type is not None:
        clauses.append("rate_type = ?")
        params.append(rate_type)
    if from_event is not None:
        clauses.append("as_of_date >= ?")
        params.append(_date_bound(from_event))
    if to_event is not None:
        clauses.append("as_of_date <= ?")
        params.append(_date_bound(to_event))
    rows = run_query(
        db_path,
        as_of=as_of_iso,
        table="jsda_repo_rates",
        extra_where=" AND ".join(clauses) if clauses else None,
        params=params,
        order_by="as_of_date, tenor, rate_type",
    )
    return _result(rows, as_of=as_of_iso, table="jsda_repo_rates", source="jsda")
