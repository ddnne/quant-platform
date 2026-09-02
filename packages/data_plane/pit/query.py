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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

from data_contracts.loader import contract_for
from data_contracts.personal_history_compact import PERSONAL_HISTORY_COMPACT_NATURAL_KEYS
from ingestion.common.timeutil import ensure_jst, parse_dt, to_iso
from storage.schema import NATURAL_KEYS, REVISION_TABLES

from .errors import (
    AsOfRequired,
    DatabaseNotFound,
    InvalidAsOf,
    SnapshotNotReady,
    SnapshotObservationClockError,
)

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
# therefore continues to open and close one connection per query. Ordinary
# callers never receive this box; it is not a writable connection map.
_READ_SCOPE_STATE = threading.local()

# Publisher and reader share this bound; the exact signed clocks must still
# agree. This protects a malformed future clock without turning local wall
# time into an authority for historical visibility.
MAX_SNAPSHOT_CLOCK_FUTURE_SKEW = timedelta(minutes=5)


class _ReadScopeBox:
    """Opaque READY-gated leases. Not a caller-writable sqlite3 registry."""

    __slots__ = ("_leases", "_shapes")

    def __init__(self) -> None:
        self._leases: dict[str, tuple[Any, int]] = {}
        self._shapes: dict[str, bool] = {}

    def empty(self) -> bool:
        return not self._leases

    def lease(self, key: str) -> tuple[Any, int] | None:
        item = self._leases.get(key)
        if not isinstance(item, tuple) or len(item) != 2:
            self._leases.pop(key, None)
            return None
        conn, depth = item
        if conn is None or not isinstance(depth, int) or depth < 1:
            self._leases.pop(key, None)
            return None
        return conn, depth

    def store(self, key: str, conn: Any, depth: int) -> None:
        if conn is None or not isinstance(depth, int) or depth < 1:
            raise TypeError("read scope lease is invalid")
        self._leases[key] = (conn, depth)

    def drop(self, key: str) -> None:
        self._leases.pop(key, None)
        self._shapes.pop(key, None)

    def shape_get(self, key: str) -> bool | None:
        value = self._shapes.get(key)
        return value if isinstance(value, bool) else None

    def shape_set(self, key: str, exact: bool) -> None:
        self._shapes[key] = bool(exact)

    def shape_clear(self, key: str) -> None:
        self._shapes.pop(key, None)


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


def snapshot_observed_through(
    db_path: Any = None, *, expected: str | None = None
) -> str:
    """Return the immutable snapshot observation clock, or fail closed.

    Controlled execution never substitutes decision time, an unbounded
    cutoff, or a dataset watermark for this singleton clock.
    """

    path = resolve_db_path(db_path)
    if not path.exists():
        raise SnapshotObservationClockError(
            "snapshot observation clock is missing"
        )
    conn = _scoped_read_connection(path)
    close_connection = conn is None
    try:
        descriptor_backed = (
            path.is_absolute()
            and path.parent in {Path("/dev/fd"), Path("/proc/self/fd")}
            and path.name.isdigit()
        )
        resolved = path if descriptor_backed else path.resolve()
        uri = "file:" + quote(str(resolved)) + "?mode=ro"
        if conn is None:
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "snapshot_observation_clock" not in tables:
            raise SnapshotObservationClockError(
                "snapshot observation clock is missing"
            )
        rows = conn.execute(
            "SELECT observed_through FROM snapshot_observation_clock"
        ).fetchall()
        if not rows:
            raise SnapshotObservationClockError(
                "snapshot observed_through is missing"
            )
        if len(rows) != 1:
            raise SnapshotObservationClockError(
                "snapshot observation clock is not a singleton"
            )
        text = str(rows[0][0] or "")
        if not text or text.strip() in {"0", "0.0"}:
            raise SnapshotObservationClockError(
                "snapshot observation clock is malformed"
            )
        try:
            canonical = normalize_as_of(text)
        except (AsOfRequired, InvalidAsOf) as exc:
            raise SnapshotObservationClockError(
                "snapshot observation clock is malformed"
            ) from exc
        if text != canonical:
            raise SnapshotObservationClockError(
                "snapshot observation clock is noncanonical"
            )
        from ingestion.common.timeutil import now_jst

        if parse_dt(canonical) - now_jst() > MAX_SNAPSHOT_CLOCK_FUTURE_SKEW:
            raise SnapshotObservationClockError(
                "snapshot observation clock is in the future"
            )
        if expected is not None:
            expected_canonical = normalize_as_of(expected)
            if expected != expected_canonical:
                raise SnapshotObservationClockError(
                    "manifest observation clock is noncanonical"
                )
            if canonical != expected_canonical:
                raise SnapshotObservationClockError(
                    "snapshot observation clock does not match manifest"
                )
        return canonical
    except SnapshotObservationClockError:
        raise
    except sqlite3.Error as exc:
        raise SnapshotObservationClockError(
            "snapshot observation clock is unreadable"
        ) from exc
    finally:
        if close_connection and conn is not None:
            conn.close()


def _local_snapshot_policy(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Return the singleton snapshot policy row, if the table exists."""

    policy_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='local_snapshot_policy'"
    ).fetchone()
    if policy_table is None:
        return None
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(local_snapshot_policy)")
    }
    projection = "require_manifest, snapshot_ready"
    if "publication_state" in columns:
        projection += ", publication_state"
    return conn.execute(
        f"SELECT {projection} FROM local_snapshot_policy WHERE singleton=1"
    ).fetchone()


def _policy_publication_state(policy: sqlite3.Row, *, missing: str | None) -> str | None:
    if "publication_state" in policy.keys():
        return str(policy["publication_state"])
    return missing


def _deny_managed_preready(conn: sqlite3.Connection) -> None:
    """Refuse a governed pre-READY database. Clocks are not authority."""

    policy = _local_snapshot_policy(conn)
    if policy is None:
        return
    state = _policy_publication_state(policy, missing="READY")
    require_manifest = bool(policy["require_manifest"])
    if state == "BUILDING" or (
        require_manifest
        and (not bool(policy["snapshot_ready"]) or state != "READY")
    ):
        raise SnapshotNotReady(
            "managed research snapshot is not READY; PIT access is denied. "
            "Historical JSDA repo eval uses "
            "research.eval_loaders.load_repo_rows_all_tenors_from_sqlite "
            "(local sqlite / R2 history). D1 jsda_repo_rates is hot tip only. "
            "Do not declare READY from this path."
        )


def _require_unmanaged_draft(conn: sqlite3.Connection) -> None:
    """Unmanaged DRAFT APIs may not query a managed snapshot."""

    policy = _local_snapshot_policy(conn)
    if policy is None:
        return
    state = _policy_publication_state(policy, missing=None)
    if bool(policy["require_manifest"]) or state == "BUILDING":
        raise SnapshotNotReady(
            "unmanaged DRAFT reads cannot use a managed snapshot"
        )


def _open_readonly_sqlite(db_path: Any = None) -> sqlite3.Connection:
    """Open SQLite ``mode=ro``. Missing file → :class:`DatabaseNotFound`.

    Ordinary callers cannot use this as a READY-policy bypass. A managed
    pre-READY database (``require_manifest=1`` or lifecycle ``BUILDING``)
    raises :class:`SnapshotNotReady` and does not return a connection.
    Unmanaged DRAFT files remain readable. Public PIT still goes through
    :func:`connect_readonly`.
    """
    path = resolve_db_path(db_path)
    if not path.exists():
        raise DatabaseNotFound(
            f"structured DB not found at {path!s}. Run ingestion first "
            "(scripts/run_ingestion_once.py), or pass db_path= pointing at an "
            "existing ingestion.sqlite."
        )
    owner_key = _read_scope_key(path)
    owned = getattr(_READ_SCOPE_STATE, "external_owned", None)
    if owned and owner_key in owned:
        raise SnapshotObservationClockError(
            "second connection to pinned snapshot is forbidden"
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
    try:
        _deny_managed_preready(conn)
    except SnapshotNotReady:
        conn.close()
        raise
    return conn


def connect_readonly(db_path: Any = None) -> sqlite3.Connection:
    """Open the structured DB **read-only** via a ``mode=ro`` file URI.

    Read-only is enforced structurally: any ``INSERT``/``UPDATE``/``DDL`` from
    this connection raises ``sqlite3.OperationalError`` ("attempt to write a
    readonly database") rather than silently mutating data. A missing DB file
    raises :class:`DatabaseNotFound` (a missing DB is a setup error, not an
    empty result).

    Uses a ``file:…?mode=ro`` URI so the path may contain spaces / non-ASCII
    safely; ``row_factory`` is set to :class:`sqlite3.Row` for dict-friendly
    decoding. Managed production databases fail closed unless their generation
    is a committed READY snapshot. Legacy/test fixtures explicitly retain
    ``require_manifest=0`` and remain readable for offline unit construction.
    """
    return _open_readonly_sqlite(db_path)


def _read_scope_key(db_path: Any) -> str:
    """Return the exact resolved database identity used by a read scope."""

    path = resolve_db_path(db_path)
    descriptor_backed = (
        path.is_absolute()
        and path.parent in {Path("/dev/fd"), Path("/proc/self/fd")}
        and path.name.isdigit()
    )
    return str(path if descriptor_backed else path.resolve())


def _scope_box() -> _ReadScopeBox:
    box = getattr(_READ_SCOPE_STATE, "_box", None)
    if not isinstance(box, _ReadScopeBox):
        box = _ReadScopeBox()
        _READ_SCOPE_STATE._box = box
    return box


@contextmanager
def _install_readonly_scope(db_path: Any) -> Iterator[None]:
    """Install a READY-gated read-only scope. Callers cannot supply an opener."""

    key = _read_scope_key(db_path)
    box = _scope_box()
    active = box.lease(key)
    if active is None:
        owned = getattr(_READ_SCOPE_STATE, "external_owned", None)
        if owned and key in owned:
            raise SnapshotObservationClockError(
                "pinned snapshot connection was swapped"
            )
        conn = connect_readonly(db_path)
        try:
            box.store(key, conn, 1)
            box.shape_clear(key)
        except Exception:
            conn.close()
            raise
    else:
        box.store(key, active[0], active[1] + 1)
    try:
        yield
    finally:
        current = box.lease(key)
        if current is not None and current[1] > 1:
            box.store(key, current[0], current[1] - 1)
        elif current is not None:
            box.drop(key)
            try:
                current[0].rollback()
            finally:
                try:
                    current[0].close()
                finally:
                    if box.empty():
                        try:
                            del _READ_SCOPE_STATE._box
                        except AttributeError:
                            pass


@contextmanager
def _readonly_connection_scope(db_path: Any) -> Iterator[None]:
    """Reuse one READY-gated read-only connection for one explicit scope."""

    with _install_readonly_scope(db_path):
        yield


def _scoped_read_connection(db_path: Any) -> sqlite3.Connection | None:
    box = getattr(_READ_SCOPE_STATE, "_box", None)
    if not isinstance(box, _ReadScopeBox):
        return None
    key = _read_scope_key(db_path)
    checks = getattr(_READ_SCOPE_STATE, "identity_checks", None)
    if checks and key in checks:
        checks[key]()
    active = box.lease(key)
    if active is None:
        return None
    conn = active[0]
    _deny_managed_preready(conn)
    return conn


def _uses_external_read_transaction(db_path: Any) -> bool:
    """Whether ``db_path`` is inside the verifier-owned pinned transaction."""

    owned = getattr(_READ_SCOPE_STATE, "external_owned", None)
    return bool(owned and _read_scope_key(db_path) in owned)


@contextmanager
def bind_external_readonly_connection(
    db_path: Any,
    connection: sqlite3.Connection,
    *,
    identity_check: Callable[[], None],
) -> Iterator[None]:
    """Lend one already-pinned connection to PIT reads; caller owns close."""

    key = _read_scope_key(db_path)
    box = _scope_box()
    if box.lease(key) is not None:
        raise SnapshotObservationClockError(
            "second connection to pinned snapshot is forbidden"
        )
    owned = getattr(_READ_SCOPE_STATE, "external_owned", None)
    if owned is None:
        owned = {}
        _READ_SCOPE_STATE.external_owned = owned
    if key in owned:
        raise SnapshotObservationClockError(
            "second connection to pinned snapshot is forbidden"
        )
    checks = getattr(_READ_SCOPE_STATE, "identity_checks", None)
    if checks is None:
        checks = {}
        _READ_SCOPE_STATE.identity_checks = checks
    identity_check()
    owned[key] = True
    checks[key] = identity_check
    box.store(key, connection, 1)
    box.shape_clear(key)
    try:
        yield
    finally:
        box.drop(key)
        owned.pop(key, None)
        checks.pop(key, None)
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        if box.empty():
            try:
                del _READ_SCOPE_STATE._box
            except AttributeError:
                pass
        if not owned:
            try:
                del _READ_SCOPE_STATE.external_owned
            except AttributeError:
                pass
        if not checks:
            try:
                del _READ_SCOPE_STATE.identity_checks
            except AttributeError:
                pass


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
    dataset_id: str | None = None,
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

    ``table``, ``dataset_id``, ``order_by``, and the optional keyset column
    names are internal trusted identifiers (hard-coded in :mod:`pit.api`),
    never user input, so they are interpolated directly. All user-controlled
    values (``as_of``, codes, dates, dataset, and cursor keys) are bound as
    parameters. When supplied, ``limit`` is applied in SQL; callers can
    request one extra row to determine whether another keyset page exists
    without materializing the complete result set.

    The connection is opened read-only and closed in a ``finally`` so a query
    error never leaks a writer-capable handle.
    """
    compact_keys = PERSONAL_HISTORY_COMPACT_NATURAL_KEYS.get(table)
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
        external_transaction = _uses_external_read_transaction(db_path)
        if not external_transaction:
            conn.execute("BEGIN")
        from .cooperative_deadline import check_deadline
        from .read_clock import resolve_read_clock

        check_deadline()
        where = ["available_at IS NOT NULL", "available_at <= ?"]
        bound: list[Any] = [as_of]
        timed_tables = (
            compact_keys is not None
            or table in REVISION_TABLES
            or table in NATURAL_KEYS
        )
        if timed_tables:
            clock = resolve_read_clock(as_of, conn=conn)
            calendar_prepublished = False
            if dataset_id is not None and (
                table == "jquants_records"
                or (
                    table == "jquants_market_calendar"
                    and dataset_id == "markets_calendar"
                )
            ):
                try:
                    calendar_prepublished = (
                        contract_for(dataset_id).available_at_policy
                        == "calendar_prepublished"
                    )
                except KeyError:
                    # Unknown catalog partitions retain the strict event-time
                    # wall; only the governed contract can opt into a
                    # prepublished calendar.
                    calendar_prepublished = False
            where.append("event_time IS NOT NULL")
            if not calendar_prepublished:
                where.append("event_time <= ?")
                bound.append(clock.decision_at)
            where.extend(["ingested_at IS NOT NULL", "ingested_at <= ?"])
            bound.append(clock.observed_through)
        if extra_where:
            where.append(f"({extra_where})")
        if params:
            bound.extend(params)
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

        if compact_keys:
            partition_by = ",".join(compact_keys)
            sql = (
                "WITH pit_visible AS (SELECT * FROM "
                f"{table} WHERE " + " AND ".join(where) + "), pit_ranked AS ("
                "SELECT *, ROW_NUMBER() OVER ("
                f"PARTITION BY {partition_by} "
                "ORDER BY available_at DESC, ingested_at DESC"
                ") AS _pit_rank FROM pit_visible) "
                "SELECT * FROM pit_ranked WHERE _pit_rank = 1"
            )
        elif has_revision_rows:
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
            if not locals().get("external_transaction", False):
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
        box = getattr(_READ_SCOPE_STATE, "_box", None)
        if scoped_connection and isinstance(box, _ReadScopeBox):
            cached_shape = box.shape_get(key)
            if cached_shape is False:
                return False, []
        external_transaction = _uses_external_read_transaction(db_path)
        if not external_transaction:
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

            if scoped_connection and isinstance(box, _ReadScopeBox):
                box.shape_set(key, shape_exact)
            if not shape_exact:
                return False, []

        from .read_clock import resolve_read_clock, visibility_predicates

        clock = resolve_read_clock(as_of, conn=conn)
        vis_sql, vis_bound = visibility_predicates(clock)
        where = [*vis_sql, "source = 'jquants'"]
        bound: list[Any] = list(vis_bound)
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
            if not locals().get("external_transaction", False):
                conn.rollback()
        finally:
            if close_connection:
                conn.close()
