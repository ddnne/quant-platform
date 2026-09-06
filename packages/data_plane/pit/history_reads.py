"""Unmanaged DRAFT history catalog reads for research eval sidecars.

These are typed PIT fetches, not a SQL capability and not READY authority.
Callers must pass an explicit ``as_of``. Missing files yield empty results.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Sequence

from storage.schema import CATALOG_CODE_SQL, NATURAL_KEYS, REVISION_TABLES

from .cooperative_deadline import check_deadline
from .errors import AsOfRequired, DatabaseNotFound, HistoryReadError, PitError
from .query import _open_readonly_sqlite, _require_unmanaged_draft, normalize_as_of
from .read_clock import resolve_read_clock, visibility_predicates

HISTORY_READ_PAGE_SIZE = 1024
HISTORY_CODE_BATCH = 32
_CATALOG_CODE_COLUMNS = frozenset({"natural_key", "payload", "raw_payload"})
_CATALOG_PIT_COLUMNS = (
    "source",
    "dataset",
    "natural_key",
    "event_time",
    "available_at",
    "ingested_at",
    "payload",
    "raw_payload",
)
# Revision storage already has a governed natural-key + ``available_at``
# version identity. The only cross-relation collision is the archived version
# versus the current table, so this closed origin rank is the minimal final
# keyset discriminator; SQLite rowid is deliberately not part of the contract.
_REVISION_ORIGIN = 0
_CURRENT_ORIGIN = 1
_VERSION_ORIGINS = frozenset({_REVISION_ORIGIN, _CURRENT_ORIGIN})


@dataclass(frozen=True, slots=True)
class _CatalogPageCursor:
    """Closed cursor for the catalog's deterministic version order."""

    event_time: str
    available_at: str
    ingested_at: str
    natural_key: str
    version_origin: int

    def __post_init__(self) -> None:
        if self.version_origin not in _VERSION_ORIGINS:
            raise HistoryReadError("history catalog cursor origin is invalid")


@dataclass(frozen=True, slots=True)
class _RevisionPageCursor:
    """Closed cursor for the immutable revision sweep order."""

    available_at: str
    ingested_at: str
    natural_key: str
    event_time: str
    version_origin: int

    def __post_init__(self) -> None:
        if self.version_origin not in _VERSION_ORIGINS:
            raise HistoryReadError("history revision cursor origin is invalid")


def _strict_keyset_gate(
    columns: Sequence[str], values: Sequence[Any]
) -> tuple[str, list[Any]]:
    """Return a strict lexicographic gate for static internal columns."""

    if len(columns) != len(values) or not columns:
        raise HistoryReadError("history page cursor is invalid")
    branches: list[str] = []
    bound: list[Any] = []
    for index, column in enumerate(columns):
        prefix = [f"{columns[pos]} = ?" for pos in range(index)]
        branches.append("(" + " AND ".join([*prefix, f"{column} > ?"]) + ")")
        bound.extend(values[: index + 1])
    return "(" + " OR ".join(branches) + ")", bound


def _history_connect(db_path: Any) -> sqlite3.Connection | None:
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        conn = _open_readonly_sqlite(path)
    except DatabaseNotFound:
        return None
    try:
        _require_unmanaged_draft(conn)
    except Exception:
        conn.close()
        raise
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def fetch_unmanaged_draft_catalog_rows(
    db_path: Any,
    *,
    as_of: Any,
    dataset: str,
    start: str | None = None,
    end: str | None = None,
    natural_key_likes: Sequence[str] = (),
    natural_key_min: str | None = None,
    natural_key_max: str | None = None,
    codes: Sequence[str] = (),
    include_available_at: bool = False,
    limit: int | None = None,
    versions: bool = False,
    _after_cursor: _CatalogPageCursor | None = None,
    _include_version_origin: bool = False,
    event_as_of: Any | None = None,
    ingested_as_of: Any | None = None,
) -> list[dict[str, Any]]:
    """PIT-visible ``jquants_records`` (+ revisions) for one dataset, or ``[]``.

    Unmanaged DRAFT only: cannot authorize READY or Controlled. ``as_of`` is
    required; there is no latest default. Default ranking emits one visible
    vintage per natural key. ``versions=True`` is a debug dump of every
    visible version and is not a product PIT result.
    """

    try:
        as_of_iso = normalize_as_of(as_of)
    except AsOfRequired:
        raise
    conn = _history_connect(db_path)
    if conn is None:
        return []
    try:
        columns = _table_columns(conn, "jquants_records")
        if not set(_CATALOG_PIT_COLUMNS) <= columns:
            raise HistoryReadError("history catalog schema is invalid")
        wanted = [str(code).strip() for code in codes if str(code).strip()]
        if wanted and not _CATALOG_CODE_COLUMNS <= columns:
            raise HistoryReadError("history catalog cannot filter codes")
        check_deadline()
        clock = resolve_read_clock(as_of_iso, conn=conn)
        event_cutoff = (
            clock.decision_at
            if event_as_of is None
            else normalize_as_of(event_as_of)
        )
        ingested_cutoff = (
            clock.observed_through
            if ingested_as_of is None
            else normalize_as_of(ingested_as_of)
        )
        if event_cutoff > clock.decision_at:
            raise HistoryReadError("history event cutoff exceeds decision clock")
        if ingested_cutoff > clock.observed_through:
            raise HistoryReadError("history ingestion cutoff exceeds observation clock")
        where = [
            "source = 'jquants'",
            "dataset = ?",
            "available_at IS NOT NULL",
            "event_time IS NOT NULL",
            "ingested_at IS NOT NULL",
            "available_at <= ?",
            "event_time <= ?",
            "ingested_at <= ?",
        ]
        params: list[Any] = [
            dataset,
            clock.decision_at,
            event_cutoff,
            ingested_cutoff,
        ]
        if start:
            where.append("substr(event_time, 1, 10) >= ?")
            params.append(str(start)[:10])
        if end:
            where.append("substr(event_time, 1, 10) <= ?")
            params.append(str(end)[:10])
        keyset_gate = ""
        keyset_params: list[Any] = []
        if _after_cursor is not None:
            if not isinstance(_after_cursor, _CatalogPageCursor):
                raise HistoryReadError("history catalog cursor is invalid")
            keyset_gate, keyset_params = _strict_keyset_gate(
                (
                    "event_time",
                    "available_at",
                    "ingested_at",
                    "natural_key",
                    "_pit_current",
                ),
                (
                    _after_cursor.event_time,
                    _after_cursor.available_at,
                    _after_cursor.ingested_at,
                    _after_cursor.natural_key,
                    _after_cursor.version_origin,
                ),
            )
        if natural_key_min is not None:
            where.append("natural_key >= ?")
            params.append(natural_key_min)
        if natural_key_max is not None:
            where.append("natural_key <= ?")
            params.append(natural_key_max)
        likes = [str(value) for value in natural_key_likes if str(value)]
        if likes:
            where.append(
                "(" + " OR ".join("natural_key LIKE ?" for _ in likes) + ")"
            )
            params.extend(likes)
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            where.append(f"{CATALOG_CODE_SQL} IN ({placeholders})")
            params.extend(wanted)
        select_cols = (
            "source, dataset, natural_key, event_time, payload, raw_payload, "
            "available_at, ingested_at"
        )
        revision_table = REVISION_TABLES["jquants_records"]
        has_revisions = bool(_table_columns(conn, revision_table))
        gate = " AND ".join(where)
        out_cols = (
            "natural_key, event_time, payload, available_at, ingested_at, "
            "_pit_current"
        )
        if has_revisions:
            key_cols = ",".join(NATURAL_KEYS["jquants_records"])
            ranked = "" if versions else " WHERE _pit_rank = 1"
            rank_sql = (
                ""
                if versions
                else (
                    ", pit_ranked AS (SELECT *, ROW_NUMBER() OVER ("
                    f"PARTITION BY {key_cols} "
                    "ORDER BY available_at DESC, ingested_at DESC, _pit_current DESC"
                    ") AS _pit_rank FROM pit_visible) "
                )
            )
            source_rel = "pit_visible" if versions else "pit_ranked"
            if keyset_gate:
                ranked += (" WHERE " if not ranked else " AND ") + keyset_gate
            sql = (
                "WITH pit_versions AS ("
                f"SELECT {select_cols}, {_CURRENT_ORIGIN} AS _pit_current "
                "FROM jquants_records "
                f"UNION ALL SELECT {select_cols}, {_REVISION_ORIGIN} AS _pit_current "
                f"FROM {revision_table}"
                f"), pit_visible AS (SELECT * FROM pit_versions WHERE {gate})"
                f"{rank_sql}"
                f" SELECT {out_cols} FROM {source_rel}{ranked}"
            )
        else:
            sql = (
                "WITH pit_visible AS ("
                f"SELECT {select_cols}, {_CURRENT_ORIGIN} AS _pit_current "
                f"FROM jquants_records WHERE {gate}) "
                f"SELECT {out_cols} FROM pit_visible"
            )
            if keyset_gate:
                sql += " WHERE " + keyset_gate
        sql += (
            " ORDER BY event_time ASC, available_at ASC, ingested_at ASC, "
            "natural_key ASC, _pit_current ASC"
        )
        bound = [*params, *keyset_params]
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                raise HistoryReadError("history catalog limit is invalid")
            sql += " LIMIT ?"
            bound.append(int(limit))
        rows: list[dict[str, Any]] = []
        for raw in conn.execute(sql, bound):
            item = dict(raw)
            if include_available_at and "available_at" not in item:
                item["available_at"] = None
            if not include_available_at:
                item.pop("available_at", None)
            if not _include_version_origin:
                item.pop("_pit_current", None)
            rows.append(item)
        return rows
    except HistoryReadError:
        raise
    except sqlite3.Error as exc:
        raise HistoryReadError("history catalog query failed") from exc
    finally:
        conn.close()


def iter_unmanaged_draft_catalog_pages(
    db_path: Any,
    *,
    as_of: Any,
    dataset: str,
    start: str | None = None,
    end: str | None = None,
    natural_key_likes: Sequence[str] = (),
    natural_key_min: str | None = None,
    natural_key_max: str | None = None,
    codes: Sequence[str] = (),
    include_available_at: bool = False,
    versions: bool = False,
    page_size: int = HISTORY_READ_PAGE_SIZE,
    event_as_of: Any | None = None,
    ingested_as_of: Any | None = None,
) -> Iterator[tuple[dict[str, Any], ...]]:
    """Yield bounded catalog pages. Never returns an unbounded list."""

    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
        raise HistoryReadError("history catalog page size is invalid")
    if page_size > HISTORY_READ_PAGE_SIZE:
        page_size = HISTORY_READ_PAGE_SIZE
    after: _CatalogPageCursor | None = None
    while True:
        page = fetch_unmanaged_draft_catalog_rows(
            db_path,
            as_of=as_of,
            dataset=dataset,
            start=start,
            end=end,
            natural_key_likes=natural_key_likes,
            natural_key_min=natural_key_min,
            natural_key_max=natural_key_max,
            codes=codes,
            include_available_at=True,
            limit=page_size,
            versions=versions,
            _after_cursor=after,
            _include_version_origin=True,
            event_as_of=event_as_of,
            ingested_as_of=ingested_as_of,
        )
        if not page:
            return
        visible = []
        for item in page:
            row = dict(item)
            row.pop("_pit_current", None)
            if not include_available_at:
                row.pop("available_at", None)
            visible.append(row)
        yield tuple(visible)
        if len(page) < page_size:
            return
        last = page[-1]
        after = _CatalogPageCursor(
            event_time=str(last.get("event_time") or ""),
            available_at=str(last.get("available_at") or ""),
            ingested_at=str(last.get("ingested_at") or ""),
            natural_key=str(last.get("natural_key") or ""),
            version_origin=int(last.get("_pit_current")),
        )


def fetch_unmanaged_draft_revision_rows(
    db_path: Any,
    *,
    as_of: Any,
    dataset: str,
    start: str | None = None,
    end: str | None = None,
    codes: Sequence[str] = (),
    limit: int | None = None,
    _after_cursor: _RevisionPageCursor | None = None,
    _include_version_origin: bool = False,
) -> list[dict[str, Any]]:
    """Immutable catalog revisions ordered by available_at + natural key.

    One PIT-bounded fetch of current + displaced vintages. Callers sweep
    forward; this is not a per-decision history reread.
    """

    try:
        as_of_iso = normalize_as_of(as_of)
    except AsOfRequired:
        raise
    conn = _history_connect(db_path)
    if conn is None:
        return []
    try:
        columns = _table_columns(conn, "jquants_records")
        if not set(_CATALOG_PIT_COLUMNS) <= columns:
            raise HistoryReadError("history catalog schema is invalid")
        wanted = [str(code).strip() for code in codes if str(code).strip()]
        if wanted and not _CATALOG_CODE_COLUMNS <= columns:
            raise HistoryReadError("history catalog cannot filter codes")
        check_deadline()
        clock = resolve_read_clock(as_of_iso, conn=conn)
        where = [
            "source = 'jquants'",
            "dataset = ?",
            "available_at IS NOT NULL",
            "event_time IS NOT NULL",
            "ingested_at IS NOT NULL",
            "available_at <= ?",
            "event_time <= ?",
            "ingested_at <= ?",
        ]
        params: list[Any] = [
            dataset,
            clock.decision_at,
            clock.decision_at,
            clock.observed_through,
        ]
        if start:
            where.append("substr(event_time, 1, 10) >= ?")
            params.append(str(start)[:10])
        if end:
            where.append("substr(event_time, 1, 10) <= ?")
            params.append(str(end)[:10])
        keyset_gate = ""
        keyset_params: list[Any] = []
        if _after_cursor is not None:
            if not isinstance(_after_cursor, _RevisionPageCursor):
                raise HistoryReadError("history revision cursor is invalid")
            keyset_gate, keyset_params = _strict_keyset_gate(
                (
                    "available_at",
                    "ingested_at",
                    "natural_key",
                    "event_time",
                    "_pit_current",
                ),
                (
                    _after_cursor.available_at,
                    _after_cursor.ingested_at,
                    _after_cursor.natural_key,
                    _after_cursor.event_time,
                    _after_cursor.version_origin,
                ),
            )
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            where.append(f"{CATALOG_CODE_SQL} IN ({placeholders})")
            params.extend(wanted)
        select_cols = (
            "source, dataset, natural_key, event_time, payload, raw_payload, "
            "available_at, ingested_at"
        )
        revision_table = REVISION_TABLES["jquants_records"]
        has_revisions = bool(_table_columns(conn, revision_table))
        gate = " AND ".join(where)
        out_cols = (
            "natural_key, event_time, payload, available_at, ingested_at, "
            "source, dataset, _pit_current"
        )
        if has_revisions:
            sql = (
                "WITH pit_versions AS ("
                f"SELECT {select_cols}, {_CURRENT_ORIGIN} AS _pit_current "
                "FROM jquants_records "
                f"UNION ALL SELECT {select_cols}, {_REVISION_ORIGIN} AS _pit_current "
                f"FROM {revision_table}"
                f"), pit_visible AS (SELECT * FROM pit_versions WHERE {gate}) "
                f"SELECT {out_cols} FROM pit_visible"
            )
        else:
            sql = (
                "WITH pit_visible AS ("
                f"SELECT {select_cols}, {_CURRENT_ORIGIN} AS _pit_current "
                f"FROM jquants_records WHERE {gate}) "
                f"SELECT {out_cols} FROM pit_visible"
            )
        if keyset_gate:
            sql += " WHERE " + keyset_gate
        sql += (
            " ORDER BY available_at ASC, ingested_at ASC, natural_key ASC, "
            "event_time ASC, _pit_current ASC"
        )
        bound = [*params, *keyset_params]
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                raise HistoryReadError("history catalog limit is invalid")
            sql += " LIMIT ?"
            bound.append(int(limit))
        rows: list[dict[str, Any]] = []
        for raw in conn.execute(sql, bound):
            item = dict(raw)
            if not _include_version_origin:
                item.pop("_pit_current", None)
            rows.append(item)
        return rows
    except HistoryReadError:
        raise
    except sqlite3.Error as exc:
        raise HistoryReadError("history revision query failed") from exc
    finally:
        conn.close()


def iter_unmanaged_draft_revision_pages(
    db_path: Any,
    *,
    as_of: Any,
    dataset: str,
    start: str | None = None,
    end: str | None = None,
    codes: Sequence[str] = (),
    page_size: int = HISTORY_READ_PAGE_SIZE,
) -> Iterator[tuple[dict[str, Any], ...]]:
    """Yield immutable revisions in available_at order. Bounded pages."""

    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
        raise HistoryReadError("history catalog page size is invalid")
    if page_size > HISTORY_READ_PAGE_SIZE:
        page_size = HISTORY_READ_PAGE_SIZE
    after: _RevisionPageCursor | None = None
    while True:
        page = fetch_unmanaged_draft_revision_rows(
            db_path,
            as_of=as_of,
            dataset=dataset,
            start=start,
            end=end,
            codes=codes,
            limit=page_size,
            _after_cursor=after,
            _include_version_origin=True,
        )
        if not page:
            return
        visible = []
        for item in page:
            row = dict(item)
            row.pop("_pit_current", None)
            visible.append(row)
        yield tuple(visible)
        if len(page) < page_size:
            return
        last = page[-1]
        after = _RevisionPageCursor(
            available_at=str(last.get("available_at") or ""),
            ingested_at=str(last.get("ingested_at") or ""),
            natural_key=str(last.get("natural_key") or ""),
            event_time=str(last.get("event_time") or ""),
            version_origin=int(last.get("_pit_current")),
        )


def fetch_jsda_repo_history_rows(
    db_path: Any,
    *,
    as_of: str,
    start: str | None = None,
    end: str | None = None,
    tenor_contains: str | None = "overnight",
) -> list[dict[str, Any]]:
    """PIT-gated unmanaged DRAFT ``jsda_repo_rates`` history."""

    as_of_s = str(as_of).strip() if as_of is not None else ""
    if not as_of_s:
        raise ValueError("as_of is required (PIT has no latest default)")
    conn = _history_connect(db_path)
    if conn is None:
        return []
    try:
        columns = _table_columns(conn, "jsda_repo_rates")
        if not columns:
            return []
        required = {"event_time", "available_at", "ingested_at", "as_of_date", "rate"}
        if not required <= columns:
            raise HistoryReadError(
                "jsda repo history cannot prove event/available/ingested observation fields"
            )
        clock = resolve_read_clock(as_of_s, conn=conn)
        vis_sql, vis_bound = visibility_predicates(clock)
        sql = (
            "SELECT as_of_date, tenor, rate_type, rate, available_at, event_time, ingested_at "
            "FROM jsda_repo_rates WHERE rate IS NOT NULL AND "
            + " AND ".join(vis_sql)
        )
        params: list[Any] = list(vis_bound)
        if start:
            sql += " AND as_of_date >= ?"
            params.append(str(start)[:10])
        if end:
            sql += " AND as_of_date <= ?"
            params.append(str(end)[:10])
        if tenor_contains:
            sql += " AND lower(tenor) LIKE ?"
            params.append(f"%{str(tenor_contains).lower()}%")
        sql += " ORDER BY as_of_date ASC"
        rows: list[dict[str, Any]] = []
        for (
            as_of_date,
            tenor,
            rate_type,
            rate,
            available_at,
            event_time,
            ingested_at,
        ) in conn.execute(sql, params):
            if (
                not event_time
                or str(event_time) > clock.decision_at
                or not available_at
                or str(available_at) > clock.decision_at
                or not ingested_at
                or str(ingested_at) > clock.observed_through
            ):
                continue
            rows.append(
                {
                    "as_of_date": str(as_of_date)[:10],
                    "tenor": tenor,
                    "rate_type": rate_type,
                    "rate": float(rate) if rate is not None else None,
                    "available_at": available_at,
                    "event_time": event_time,
                    "ingested_at": ingested_at,
                }
            )
        return rows
    except sqlite3.Error as exc:
        raise HistoryReadError("jsda repo history query failed") from exc
    finally:
        conn.close()


def jsda_repo_history_status(db_path: Any) -> dict[str, Any]:
    """Disclose sqlite history presence without claiming D1 or READY."""

    path = Path(db_path)
    missing = not path.is_file()
    n = 0
    mn = mx = None
    tenors = 0
    if not missing:
        conn = _history_connect(path)
        if conn is not None:
            try:
                if not _table_columns(conn, "jsda_repo_rates"):
                    return {
                        "dataset": "jsda_tokyo_repo_rates",
                        "table": "jsda_repo_rates",
                        "sqlite_rows": 0,
                        "sqlite_min": None,
                        "sqlite_max": None,
                        "sqlite_tenors": 0,
                        "sqlite_missing": False,
                        "d1_role": "hot_tip_only",
                        "pit_path": "fail_closed_until_READY",
                        "invent_complete": False,
                        "ffill_applied": False,
                    }
                n, mn, mx = conn.execute(
                    "SELECT COUNT(*), MIN(as_of_date), MAX(as_of_date) "
                    "FROM jsda_repo_rates"
                ).fetchone()
                tenors = int(
                    conn.execute(
                        "SELECT COUNT(DISTINCT tenor) FROM jsda_repo_rates"
                    ).fetchone()[0]
                    or 0
                )
            except sqlite3.Error as exc:
                raise HistoryReadError("jsda repo history status query failed") from exc
            finally:
                conn.close()
    return {
        "dataset": "jsda_tokyo_repo_rates",
        "table": "jsda_repo_rates",
        "sqlite_rows": int(n or 0),
        "sqlite_min": mn,
        "sqlite_max": mx,
        "sqlite_tenors": int(tenors or 0),
        "sqlite_missing": missing,
        "d1_role": "hot_tip_only",
        "pit_path": "fail_closed_until_READY",
        "invent_complete": False,
        "ffill_applied": False,
    }


__all__ = [
    "HISTORY_CODE_BATCH",
    "HISTORY_READ_PAGE_SIZE",
    "fetch_jsda_repo_history_rows",
    "fetch_unmanaged_draft_catalog_rows",
    "fetch_unmanaged_draft_revision_rows",
    "iter_unmanaged_draft_catalog_pages",
    "iter_unmanaged_draft_revision_pages",
    "jsda_repo_history_status",
]
