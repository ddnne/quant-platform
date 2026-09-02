"""Bounded compact-v8 PIT reads for the typed personal research view.

This adapter is the only path that opens ``personal_history_compact_bars`` /
``personal_history_compact_master``. It yields one latest visible vintage per
natural key. Visibility requires ``event_time`` / ``available_at`` ``<=``
decision time and ``ingested_at`` ``<=`` the snapshot observation cutoff.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from data_contracts.identity import natural_key as contract_natural_key
from data_contracts.personal_history_compact import (
    PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
    PERSONAL_HISTORY_COMPACT_NATURAL_KEYS,
    PERSONAL_HISTORY_COMPACT_VERSION_KEYS,
    compact_history_state,
    compact_rebuild_reason,
)

from .cooperative_deadline import check_deadline
from .errors import AsOfRequired, HistoryReadError, PitError
from .history_reads import HISTORY_READ_PAGE_SIZE
from .query import _open_readonly_sqlite, _require_unmanaged_draft, normalize_as_of
from .read_clock import resolve_read_clock

_COMPACT_DATASETS = {
    "equities_bars_daily": PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    "equities_master": PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
}


def _pk_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    ranked = sorted(
        (
            (int(info[5]), str(info[1]))
            for info in conn.execute(f"PRAGMA table_info({table})")
            if int(info[5]) > 0
        ),
        key=lambda item: item[0],
    )
    return tuple(name for _ordinal, name in ranked)


def compact_revision_semantics(conn: sqlite3.Connection) -> bool:
    """True only when compact PKs keep version identity, not overwrite keys."""

    if compact_history_state(conn) != "compact":
        return False
    for table, expected in PERSONAL_HISTORY_COMPACT_VERSION_KEYS.items():
        if _pk_columns(conn, table) != expected:
            return False
    return True


def classify_draft_surface(conn: sqlite3.Connection) -> str:
    state = compact_history_state(conn)
    if state == "compact" and not compact_revision_semantics(conn):
        return "invalid"
    return state


def _bar_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    close = raw.get("close")
    return {
        "Code": str(raw.get("code") or "").strip(),
        "Date": str(raw.get("date") or "")[:10],
        "C": close,
        "Close": close,
        "AdjC": raw.get("adjustment_close"),
        "Va": raw.get("turnover_value"),
        "Vo": raw.get("volume"),
        "AAdjC": raw.get("afternoon_adjustment_close"),
        "MAdjC": raw.get("morning_adjustment_close"),
        "AVa": raw.get("afternoon_turnover_value"),
        "MVa": raw.get("morning_turnover_value"),
        "AAdjVo": raw.get("afternoon_adjustment_volume"),
        "MAdjVo": raw.get("morning_adjustment_volume"),
        "AdjVo": raw.get("adjustment_volume"),
        "MarketCapitalization": raw.get("market_cap"),
    }


def _master_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "Code": str(raw.get("code") or "").strip(),
        "Date": str(raw.get("snapshot_date") or "")[:10],
        "MarketCode": raw.get("market_code"),
        "Sector17Code": raw.get("sector_17_code"),
        "Sector33Code": raw.get("sector_33_code"),
        "ScaleCategory": raw.get("scale_category"),
        "SourceScaleCategory": raw.get("source_scale_category"),
    }


def _catalog_row(dataset: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    payload = (
        _bar_payload(raw) if dataset == "equities_bars_daily" else _master_payload(raw)
    )
    return {
        "source": "jquants",
        "dataset": dataset,
        "natural_key": contract_natural_key(payload, dataset),
        "event_time": raw.get("event_time"),
        "available_at": raw.get("available_at"),
        "ingested_at": raw.get("ingested_at"),
        "payload": payload,
        "raw_payload": payload,
    }


def iter_compact_decision_pages(
    db_path: Any,
    *,
    as_of: Any,
    dataset: str,
    start: str | None = None,
    end: str | None = None,
    codes: Sequence[str] = (),
    page_size: int = HISTORY_READ_PAGE_SIZE,
) -> Iterator[tuple[dict[str, Any], ...]]:
    """Yield singleton-vintage compact pages. Never an unbounded list."""

    if dataset not in _COMPACT_DATASETS:
        raise HistoryReadError(f"compact adapter cannot read {dataset}")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
        raise HistoryReadError("compact catalog page size is invalid")
    size = min(int(page_size), HISTORY_READ_PAGE_SIZE)
    try:
        as_of_iso = normalize_as_of(as_of)
    except AsOfRequired:
        raise
    table = _COMPACT_DATASETS[dataset]
    natural = PERSONAL_HISTORY_COMPACT_NATURAL_KEYS[table]
    date_column = "date" if dataset == "equities_bars_daily" else "snapshot_date"
    wanted = [str(code).strip() for code in codes if str(code).strip()]
    order_cols = ("event_time", "available_at", "ingested_at", *natural)
    after: tuple[str, ...] | None = None
    while True:
        conn = _open_readonly_sqlite(db_path)
        try:
            _require_unmanaged_draft(conn)
            check_deadline()
            if not compact_revision_semantics(conn):
                raise PitError(
                    compact_rebuild_reason(conn)
                    or "compact schema is invalid; rebuild as personal-draft-history/v8"
                )
            clock = resolve_read_clock(as_of_iso, conn=conn)
            where = [
                "available_at IS NOT NULL",
                "event_time IS NOT NULL",
                "ingested_at IS NOT NULL",
                "available_at <= ?",
                "event_time <= ?",
                "ingested_at <= ?",
            ]
            params: list[Any] = [
                clock.decision_at,
                clock.decision_at,
                clock.observed_through,
            ]
            if start:
                where.append(f"substr({date_column}, 1, 10) >= ?")
                params.append(str(start)[:10])
            if end:
                where.append(f"substr({date_column}, 1, 10) <= ?")
                params.append(str(end)[:10])
            if wanted:
                placeholders = ",".join("?" for _ in wanted)
                where.append(f"code IN ({placeholders})")
                params.extend(wanted)
            keyset_sql = ""
            if after is not None:
                branches: list[str] = []
                for index, column in enumerate(order_cols):
                    comparisons = [f"{prior} = ?" for prior in order_cols[:index]]
                    comparisons.append(f"{column} > ?")
                    branches.append("(" + " AND ".join(comparisons) + ")")
                    params.extend(after[: index + 1])
                keyset_sql = " AND (" + " OR ".join(branches) + ")"
            partition = ",".join(natural)
            gate = " AND ".join(where)
            sql = (
                "WITH pit_visible AS (SELECT * FROM "
                f"{table} WHERE {gate}), pit_ranked AS ("
                "SELECT *, ROW_NUMBER() OVER ("
                f"PARTITION BY {partition} "
                "ORDER BY available_at DESC, ingested_at DESC"
                ") AS _pit_rank FROM pit_visible) "
                "SELECT * FROM pit_ranked WHERE _pit_rank = 1"
                f"{keyset_sql} "
                f"ORDER BY {', '.join(f'{col} ASC' for col in order_cols)} "
                "LIMIT ?"
            )
            bound = [*params, size]
            page_rows: list[dict[str, Any]] = []
            cursor_rows: list[dict[str, Any]] = []
            for raw in conn.execute(sql, bound):
                mapped = dict(raw)
                cursor_rows.append(mapped)
                page_rows.append(_catalog_row(dataset, mapped))
            page = tuple(page_rows)
        except PitError:
            raise
        except sqlite3.Error as exc:
            raise HistoryReadError("compact catalog query failed") from exc
        finally:
            conn.close()
        if not page:
            return
        if len(page) > size:
            raise HistoryReadError("compact catalog page exceeded the fixed bound")
        yield page
        if len(page) < size:
            return
        last_raw = cursor_rows[-1]
        after = tuple(str(last_raw.get(col) or "") for col in order_cols)


def compact_surface_or_error(db_path: Any) -> str:
    conn = _open_readonly_sqlite(db_path)
    try:
        _require_unmanaged_draft(conn)
        return classify_draft_surface(conn)
    finally:
        conn.close()


__all__ = [
    "classify_draft_surface",
    "compact_revision_semantics",
    "compact_surface_or_error",
    "iter_compact_decision_pages",
]
