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
    uri = "file:" + quote(str(path.resolve())) + "?mode=ro"
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
                    "managed research snapshot is not READY; PIT access is denied"
                )
    return conn


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
) -> list[dict[str, Any]]:
    """Run a PIT-gated ``SELECT *`` and return decoded rows.

    The gate ``available_at IS NOT NULL AND available_at <= ?`` is **always**
    applied with ``as_of`` as the first bound parameter; ``extra_where`` /
    ``params`` (optional, additive) extend it — they can never replace it.

    ``table`` and ``order_by`` are internal trusted identifiers (hard-coded in
    :mod:`pit.api`), never user input, so they are interpolated directly. All
    user-controlled values (``as_of``, codes, dates, dataset) are bound as
    parameters.

    The connection is opened read-only and closed in a ``finally`` so a query
    error never leaks a writer-capable handle.
    """
    where = ["available_at IS NOT NULL", "available_at <= ?"]
    bound: list[Any] = [as_of]
    if extra_where:
        where.append(f"({extra_where})")
    if params:
        bound.extend(params)
    conn = connect_readonly(db_path)
    try:
        revision_table = REVISION_TABLES.get(table)
        has_revision_table = False
        if revision_table is not None:
            has_revision_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (revision_table,),
            ).fetchone() is not None

        if has_revision_table:
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
        if order_by:
            sql += f" ORDER BY {order_by}"
        cur = conn.execute(sql, bound)
        return [_decode_row(r) for r in cur.fetchall()]
    finally:
        conn.close()
