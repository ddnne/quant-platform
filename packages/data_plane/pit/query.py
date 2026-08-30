"""``as_of`` filter SQL helpers for the PIT Data API.

One hard rule lives here: **every** read applies ``available_at <= as_of``
(and rejects NULL ``available_at``). Optional range / equality filters on the
event column are *additive* — they never replace the ``available_at`` gate.
This module owns the read-only connection and the canonical ``as_of``
normalization; :mod:`pit.api` builds the per-table filters on top.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from ingestion.common.timeutil import ensure_jst, parse_dt, to_iso
from storage.schema import NATURAL_KEYS, REVISION_TABLES

from .errors import AsOfRequired, DatabaseNotFound, InvalidAsOf, SnapshotNotReady

# Sentinel default for ``as_of`` on the public API. A bare ``None`` default
# would collide with an explicit ``None`` argument; this object is distinct,
# so :func:`normalize_as_of` can tell "caller omitted as_of" apart and raise
# :class:`AsOfRequired` with a helpful message instead of a bare ``TypeError``.
_NOT_GIVEN: Any = object()

# Default structured DB location (relative to the process cwd, i.e. the repo
# root in normal use). Override per-call with ``db_path=``.
DEFAULT_DB_PATH = Path("data/structured/ingestion.sqlite")

# Columns that hold a verbatim/source JSON blob; decoded into Python objects
# in returned rows when the stored string is valid JSON.
_JSON_PAYLOAD_COLS = ("raw_payload", "payload")

# Explicitly scoped personal-paper reads may reuse one read-only SQLite handle
# within the calling thread.  The default API never populates this state and
# therefore continues to open and close one connection per query.
_READ_SCOPE_STATE = threading.local()


def normalize_as_of(as_of: Any = _NOT_GIVEN) -> str:
    """Return a canonical JST ISO string for ``as_of``, or raise.

    * missing (sentinel) / ``None`` / empty string -> :class:`AsOfRequired`
      (PIT has **no** "latest" default).
    * unparseable -> :class:`InvalidAsOf`.

    Accepts ISO-8601 strings, aware or naive :class:`~datetime.datetime`
    (naive assumed JST), and :class:`~datetime.date` (JST midnight). The
    result is seconds-precision ``+09:00`` — the same canonical form
    ``available_at`` is stored in (see
    :func:`ingestion.common.available_at.validate_available_at`) — so the two
    compare correctly as ISO strings in SQL.
    """
    if as_of is None or as_of is _NOT_GIVEN:
        raise AsOfRequired(
            "as_of is required (PIT has no 'latest' default); pass an explicit "
            "Asia/Tokyo instant, e.g. as_of='2025-04-01T00:00:00+09:00'."
        )
    if isinstance(as_of, datetime):
        return to_iso(ensure_jst(as_of))
    if isinstance(as_of, date):  # datetime is a subclass of date — checked above
        return to_iso(ensure_jst(datetime(as_of.year, as_of.month, as_of.day)))
    if isinstance(as_of, str):
        s = as_of.strip()
        if not s:
            raise AsOfRequired("as_of is required (an empty string is not allowed).")
        try:
            return to_iso(parse_dt(s))
        except ValueError as exc:
            raise InvalidAsOf(
                f"as_of {as_of!r} is not a valid ISO-8601 instant: {exc}"
            ) from exc
    raise InvalidAsOf(
        f"as_of unsupported type {type(as_of).__name__!r}; "
        "expected str / datetime / date."
    )


def resolve_db_path(db_path: Any) -> Path:
    """Resolved DB path: explicit override or :data:`DEFAULT_DB_PATH`."""
    return Path(db_path) if db_path is not None else DEFAULT_DB_PATH


def connect_readonly(db_path: Any = None) -> sqlite3.Connection:
    """Open the structured DB **read-only** via a ``mode=ro`` file URI.

    Read-only is enforced structurally: any ``INSERT``/``UPDATE``/``DDL`` from
    this connection raises ``sqlite3.OperationalError`` ("attempt to write a
    readonly database") rather than silently mutating data. A missing DB file
    raises :class:`DatabaseNotFound` (a missing DB is a setup error, not an
    empty result).

    Uses a ``file:…?mode=ro`` URI so the path may contain spaces / non-ASCII
    safely; ``row_factory`` is set to :class:`sqlite3.Row` for dict-friendly
    decoding.
    """
    path = resolve_db_path(db_path)
    if not path.exists():
        raise DatabaseNotFound(
            f"structured DB not found at {path!s}. Run ingestion first "
            "(scripts/run_ingestion_once.py), or pass db_path= pointing at an "
            "existing ingestion.sqlite."
        )
    descriptor_backed = (
        path.is_absolute()
        and path.parent in {Path("/dev/fd"), Path("/proc/self/fd")}
        and path.name.isdigit()
    )
    # Resolving /proc/self/fd/N on Linux yields the original pathname and
    # silently recreates the validate-then-reopen race.  Descriptor-backed
    # callers must preserve the lexical FD path all the way into SQLite.
    resolved = path if descriptor_backed else path.resolve()
    query = "?mode=ro&immutable=1" if descriptor_backed else "?mode=ro"
    uri = "file:" + quote(str(resolved)) + query
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    # Managed production databases fail closed unless their generation is a
    # committed READY snapshot. Legacy/test fixtures explicitly retain
    # require_manifest=0 and remain readable for offline unit construction.
    policy_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='local_snapshot_policy'"
    ).fetchone()
    if policy_table is not None:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(local_snapshot_policy)")
        }
        projection = "require_manifest, snapshot_ready"
        if "publication_state" in columns:
            projection += ", publication_state"
        policy = conn.execute(
            f"SELECT {projection} FROM local_snapshot_policy WHERE singleton=1"
        ).fetchone()
        if policy is not None and bool(policy["require_manifest"]):
            state = (
                str(policy["publication_state"])
                if "publication_state" in policy.keys() else "READY"
            )
            if not bool(policy["snapshot_ready"]) or state != "READY":
                conn.close()
                raise SnapshotNotReady(
                    "managed research snapshot is not READY; PIT access is denied. "
                    "Historical JSDA repo eval uses "
                    "research.eval_loaders.load_repo_rows_all_tenors_from_sqlite "
                    "(local sqlite / R2 history). D1 jsda_repo_rates is hot tip only. "
                    "Do not declare READY from this path."
                )
    return conn


def _read_scope_key(db_path: Any) -> str:
    """Return the exact resolved database identity used by a read scope."""

    path = resolve_db_path(db_path)
    descriptor_backed = (
        path.is_absolute()
        and path.parent in {Path("/dev/fd"), Path("/proc/self/fd")}
        and path.name.isdigit()
    )
    return str(path if descriptor_backed else path.resolve())


def _thread_read_scopes() -> dict[str, tuple[sqlite3.Connection, int]]:
    scopes = getattr(_READ_SCOPE_STATE, "connections", None)
    if scopes is None:
        scopes = {}
        _READ_SCOPE_STATE.connections = scopes
    return scopes


def _thread_adjustment_probe_shapes() -> dict[str, bool]:
    """Per-read-scope cache for the immutable personal DB shape probe."""

    shapes = getattr(_READ_SCOPE_STATE, "adjustment_probe_shapes", None)
    if shapes is None:
        shapes = {}
        _READ_SCOPE_STATE.adjustment_probe_shapes = shapes
    return shapes


@contextmanager
def _readonly_connection_scope(db_path: Any) -> Iterator[None]:
    """Reuse one read-only connection for one explicit synchronous scope.

    The scope is private infrastructure for an immutable personal-paper run.
    It is keyed by the exact resolved DB path and stored in thread-local state,
    so another database or thread can never inherit the handle.  Nesting the
    same path reuses the outer handle and only the outermost exit closes it.

    No transaction spans the scope: :func:`run_query` retains its per-query
    ``BEGIN``/rollback boundary.  The yielded value is deliberately ``None``
    rather than a raw SQL capability.
    """

    key = _read_scope_key(db_path)
    scopes = _thread_read_scopes()
    active = scopes.get(key)
    if active is None:
        connection = connect_readonly(Path(key))
        scopes[key] = (connection, 1)
        # A prior scope for the same pathname must never lend shape authority
        # to a newly opened SQLite generation.
        _thread_adjustment_probe_shapes().pop(key, None)
    else:
        connection, depth = active
        scopes[key] = (connection, depth + 1)
    try:
        yield
    finally:
        current = scopes.get(key)
        if current is not None and current[1] > 1:
            scopes[key] = (current[0], current[1] - 1)
        elif current is not None:
            scopes.pop(key, None)
            shapes = getattr(_READ_SCOPE_STATE, "adjustment_probe_shapes", None)
            if shapes is not None:
                shapes.pop(key, None)
            try:
                current[0].rollback()
            finally:
                try:
                    current[0].close()
                finally:
                    if not scopes:
                        try:
                            del _READ_SCOPE_STATE.connections
                        except AttributeError:
                            pass
                        try:
                            del _READ_SCOPE_STATE.adjustment_probe_shapes
                        except AttributeError:
                            pass


def _scoped_read_connection(db_path: Any) -> sqlite3.Connection | None:
    scopes = getattr(_READ_SCOPE_STATE, "connections", None)
    if not scopes:
        return None
    active = scopes.get(_read_scope_key(db_path))
    return None if active is None else active[0]


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    """Row -> dict, decoding JSON payload columns into Python objects.

    Best-effort: if a payload column holds a string that is not valid JSON
    (or is empty), the original string is preserved untouched.
    """
    d = dict(row)
    # Window-ranking helpers used by revision-aware reads are implementation
    # details, not part of the public row schema.
    d.pop("_pit_current", None)
    d.pop("_pit_rank", None)
    for k in _JSON_PAYLOAD_COLS:
        v = d.get(k)
        if isinstance(v, str) and v:
            try:
                d[k] = json.loads(v)
            except (ValueError, TypeError):
                pass  # leave the verbatim string as-is
    return d


def run_query(
    db_path: Any,
    *,
    as_of: str,
    table: str,
    extra_where: Optional[str] = None,
    params: Optional[list[Any]] = None,
    order_by: Optional[str] = None,
    keyset_after: Optional[tuple[tuple[str, ...], tuple[Any, ...]]] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Run a PIT-gated ``SELECT *`` and return decoded rows.

    The gate ``available_at IS NOT NULL AND available_at <= ?`` is **always**
    applied with ``as_of`` as the first bound parameter; ``extra_where`` /
    ``params`` (optional, additive) extend it — they can never replace it.

    ``table``, ``order_by``, and the optional keyset column names are internal
    trusted identifiers (hard-coded in :mod:`pit.api`), never user input, so
    they are interpolated directly. All user-controlled values (``as_of``,
    codes, dates, dataset, and cursor keys) are bound as parameters. When
    supplied, ``limit`` is applied in SQL; callers can request one extra row
    to determine whether another keyset page exists without materializing the
    complete result set.

    The connection is opened read-only and closed in a ``finally`` so a query
    error never leaks a writer-capable handle.
    """
    where = ["available_at IS NOT NULL", "available_at <= ?"]
    bound: list[Any] = [as_of]
    if extra_where:
        where.append(f"({extra_where})")
    if params:
        bound.extend(params)
    keyset_sql: str | None = None
    keyset_bound: list[Any] = []
    if keyset_after is not None:
        columns, values = keyset_after
        if not columns or len(columns) != len(values):
            raise ValueError("keyset columns and values must have equal length")
        branches: list[str] = []
        for index, column in enumerate(columns):
            comparisons = [f"{prior} = ?" for prior in columns[:index]]
            comparisons.append(f"{column} > ?")
            branches.append("(" + " AND ".join(comparisons) + ")")
            keyset_bound.extend(values[: index + 1])
        keyset_sql = "(" + " OR ".join(branches) + ")"
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise ValueError("limit must be a positive integer")
    conn = _scoped_read_connection(db_path)
    close_connection = conn is None
    if conn is None:
        conn = connect_readonly(db_path)
    try:
        # Pin revision discovery and the fact read to one SQLite snapshot.
        # Without an explicit read transaction, a concurrent amendment could
        # archive the visible primary row after the empty-revision check and
        # before the SELECT, producing a mixed-generation result.
        conn.execute("BEGIN")
        revision_table = REVISION_TABLES.get(table)
        has_revision_rows = False
        if revision_table is not None:
            has_revision_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (revision_table,),
            ).fetchone() is not None
            if has_revision_table:
                # Personal DRAFT databases normally have the revision schema
                # but no amendments.  Avoid paying for a UNION + window rank
                # on every feature read until a revision actually exists.
                has_revision_rows = conn.execute(
                    f"SELECT 1 FROM {revision_table} LIMIT 1"
                ).fetchone() is not None

        if has_revision_rows:
            key_cols = NATURAL_KEYS[table]
            partition_by = ",".join(key_cols)
            sql = (
                "WITH pit_versions AS ("
                f"SELECT *, 1 AS _pit_current FROM {table} UNION ALL "
                f"SELECT *, 0 AS _pit_current FROM {revision_table}"
                "), pit_visible AS ("
                "SELECT * FROM pit_versions WHERE " + " AND ".join(where)
                + "), pit_ranked AS ("
                "SELECT *, ROW_NUMBER() OVER ("
                f"PARTITION BY {partition_by} "
                "ORDER BY available_at DESC, ingested_at DESC, _pit_current DESC"
                ") AS _pit_rank FROM pit_visible) "
                "SELECT * FROM pit_ranked WHERE _pit_rank = 1"
            )
        else:
            # Compatibility with databases created before revision tables were
            # introduced. Opening them once through SqliteStore installs the
            # history schema for all subsequent reads.
            sql = f"SELECT * FROM {table} WHERE " + " AND ".join(where)
        if keyset_sql:
            sql += f" AND {keyset_sql}"
            bound.extend(keyset_bound)
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += " LIMIT ?"
            bound.append(limit)
        cur = conn.execute(sql, bound)
        return [_decode_row(r) for r in cur.fetchall()]
    finally:
        try:
            conn.rollback()
        finally:
            if close_connection:
                conn.close()


def _probe_standalone_typed_adjustment_candidates(
    db_path: Any,
    *,
    as_of: str,
    codes: tuple[str, ...],
    from_event: str | None,
    to_event: str | None,
) -> tuple[bool, list[dict[str, Any]]]:
    """Return narrow typed-bar candidates when that result is provably exact.

    ``get_equity_bars_daily`` merges the curated table, its revision history,
    and the generic catalog partition.  Pushing an invalid-value predicate
    below either revision ranking or that cross-store merge can resurrect an
    older invalid value that the public PIT result has superseded.  The fast
    path is therefore deliberately limited to the common personal-snapshot
    shape: one ``jquants`` curated table, no bar revisions, and no generic
    ``equities_bars_daily`` rows.  The caller must use the public full read
    whenever ``exact`` is false.

    Candidate classification is intentionally broad.  SQLite values with a
    non-numeric storage class are returned for Python to apply the canonical
    ``float`` semantics (for example a numeric-looking TEXT/BLOB may still be
    valid).  Ordinary positive finite REAL/INTEGER rows never leave SQLite.
    Shape checks and the candidate read share one read transaction.
    """

    key = _read_scope_key(db_path)
    conn = _scoped_read_connection(db_path)
    scoped_connection = conn is not None
    close_connection = conn is None
    if conn is None:
        conn = connect_readonly(db_path)
    try:
        cached_shape = None
        if scoped_connection:
            cached_shape = _thread_adjustment_probe_shapes().get(key)
            if cached_shape is False:
                return False, []
        conn.execute("BEGIN")

        def _table_exists(table: str) -> bool:
            return (
                conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                is not None
            )

        # Any revision changes where the invalid predicate must be applied:
        # after visible-version ranking, not before it.  Preserve the existing
        # public API exactly by declining the optimization for that DB shape.
        if cached_shape is None:
            shape_exact = True
            if _table_exists("jquants_daily_bars_revisions") and (
                conn.execute(
                    "SELECT 1 FROM jquants_daily_bars_revisions LIMIT 1"
                ).fetchone()
                is not None
            ):
                shape_exact = False

            # Generic bar rows participate in a second revision-aware merge
            # and are normalized from JSON in Python. SQL JSON coercion is not
            # a proven substitute, so any such partition forces fallback.
            if shape_exact:
                for table in ("jquants_records", "jquants_records_revisions"):
                    if _table_exists(table) and (
                        conn.execute(
                            f"SELECT 1 FROM {table} WHERE dataset=? LIMIT 1",
                            ("equities_bars_daily",),
                        ).fetchone()
                        is not None
                    ):
                        shape_exact = False
                        break

            # Ascending/descending PK-index edge probes are O(1) and detect
            # both a non-jquants source and a nullable-source compatibility
            # schema without scanning a canonical all-jquants table.
            if shape_exact:
                source_edges = [
                    conn.execute(
                        "SELECT source FROM jquants_daily_bars "
                        f"ORDER BY source {direction} LIMIT 1"
                    ).fetchone()
                    for direction in ("ASC", "DESC")
                ]
                if any(
                    row is not None and row[0] != "jquants"
                    for row in source_edges
                ):
                    shape_exact = False

            if scoped_connection:
                _thread_adjustment_probe_shapes()[key] = shape_exact
            if not shape_exact:
                return False, []

        where = [
            "available_at IS NOT NULL",
            "available_at <= ?",
            "source = 'jquants'",
        ]
        bound: list[Any] = [as_of]
        if codes:
            placeholders = ",".join("?" for _ in codes)
            where.append(f"code IN ({placeholders})")
            bound.extend(codes)
        else:
            where.append("0")
        if from_event is not None:
            where.append("date >= ?")
            bound.append(from_event)
        if to_event is not None:
            where.append("date <= ?")
            bound.append(to_event)

        # This superset contains every value that can fail the canonical
        # Python check: NULL, non-numeric storage, non-positive, NaN (where
        # supported), and infinities outside the finite IEEE-754 range.
        where.append(
            "(adjustment_close IS NULL "
            "OR typeof(adjustment_close) NOT IN ('integer','real') "
            "OR adjustment_close <= 0 "
            "OR adjustment_close != adjustment_close "
            "OR adjustment_close > 1.7976931348623157e308)"
        )
        cursor = conn.execute(
            "SELECT * FROM jquants_daily_bars WHERE "
            + " AND ".join(where)
            + " ORDER BY code, date",
            bound,
        )
        return True, [_decode_row(row) for row in cursor.fetchall()]
    finally:
        try:
            conn.rollback()
        finally:
            if close_connection:
                conn.close()
