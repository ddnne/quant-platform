"""SQLite writer for structured ingestion rows.

Generic over tables defined in :mod:`storage.schema`. The hard PIT rule lives
here: any row lacking ``available_at`` is rejected before it touches the DB,
and ``available_at`` is canonicalized to a JST ISO string on write.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from ingestion.common.available_at import (
    is_available_at_known,
    validate_available_at,
)
from ingestion.common.timeutil import now_iso, parse_dt, to_iso

from .schema import NATURAL_KEYS, SCHEMA_SQL


class MissingAvailableAt(ValueError):
    """Raised when a structured row lacks ``available_at`` (PIT violation)."""


def _payload_signature(
    row: Mapping[str, Any], cols: list[str], skip: set[str]
) -> str:
    """Canonical, order-independent signature of a row's non-PIT payload.

    Used to decide whether a conflicting row is an *unchanged re-fetch* (keep
    the earliest ``available_at``) or an *amendment* (take the incoming
    ``available_at``). ``skip`` holds the identity/audit columns to ignore —
    the natural-key columns plus ``available_at`` and ``ingested_at``.

    Prefers ``raw_payload`` — the verbatim source record — when present, since
    it faithfully captures any amendment; otherwise falls back to the
    remaining structured columns.
    """
    raw = row.get("raw_payload")
    if raw not in (None, ""):
        try:
            obj = json.loads(raw) if isinstance(raw, str) else raw
            return json.dumps(obj, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(raw)
    return json.dumps(
        {c: row.get(c) for c in cols if c not in skip},
        sort_keys=True,
        ensure_ascii=False,
    )


def _earlier_available(a: str, b: str) -> str:
    """Return the chronologically earlier of two ``available_at`` ISO strings.

    Compared as **aware datetimes** (canonicalized to JST), not as raw text —
    so equivalent instants in different offsets compare equal and we never
    backdate via a lexicographic fluke.
    """
    da, db = parse_dt(a), parse_dt(b)
    return to_iso(da if da <= db else db)


class SqliteStore:
    def __init__(self, db_path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.OperationalError:
            pass
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    # --- core write -------------------------------------------------------

    def upsert(self, table: str, rows: Iterable[Mapping[str, Any]]) -> int:
        """Idempotent, PIT-safe upsert keyed on the table's natural key.

        Validates + canonicalizes ``available_at`` on every row, then upserts.
        On conflict (same natural key):

        * **unchanged payload** (re-fetch of identical data): keep the
          *earliest* ``available_at`` (compared as aware datetimes) and refresh
          ``ingested_at``. A later re-fetch must never move the point-in-time
          stamp backward.
        * **amended payload** (the non-PIT data changed): take the *incoming*
          ``available_at`` and field values. An amended close was **not**
          available at the original publication time, so MIN-ing it with the
          old stamp would backdate the amendment — that is the P1 bug.

        Payload identity prefers ``raw_payload`` (the verbatim source record)
        when present. The whole batch runs in one transaction; any failure
        rolls back so a partial batch is never committed.
        """
        rows = [dict(r) for r in rows]
        if not rows:
            return 0

        for i, r in enumerate(rows):
            av = r.get("available_at")
            if not is_available_at_known(av):
                raise MissingAvailableAt(
                    f"{table}[{i}] missing available_at — PIT requires available_at"
                )
            # Canonicalize to a JST ISO string so equivalent offsets unify
            # (e.g. 17:00+09:00 == 08:00+00:00) before any comparison/write.
            r["available_at"] = validate_available_at(av)

        # Stable, de-duplicated column list across all rows.
        cols: list[str] = []
        seen: set[str] = set()
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    cols.append(k)

        placeholders = ",".join("?" for _ in cols)
        collist = ",".join(cols)

        key_cols = NATURAL_KEYS.get(table, [])
        if key_cols and all(k in seen for k in key_cols):
            key_set = set(key_cols)
            skip = key_set | {"available_at", "ingested_at"}
            existing = self._existing_by_key(table, key_cols, rows)

            for r in rows:
                key = tuple(r[k] for k in key_cols)
                ex = existing.get(key)
                if ex is not None and _payload_signature(
                    r, cols, skip
                ) == _payload_signature(ex, cols, skip):
                    # Unchanged re-fetch: never backdate the PIT stamp.
                    r["available_at"] = _earlier_available(
                        ex["available_at"], r["available_at"]
                    )
                # else: new row OR amendment -> incoming available_at stays.

            assigns = [f"{c} = excluded.{c}" for c in cols if c not in key_set]
            sql = (
                f"INSERT INTO {table} ({collist}) VALUES ({placeholders}) "
                f"ON CONFLICT({','.join(key_cols)}) DO UPDATE SET {','.join(assigns)}"
            )
        else:
            # Defensive fallback (should not happen for known tables).
            sql = (
                f"INSERT OR REPLACE INTO {table} ({collist}) "
                f"VALUES ({placeholders})"
            )

        payload = [[r.get(c) for c in cols] for r in rows]
        try:
            cur = self._conn.executemany(sql, payload)
            self._conn.commit()
        except Exception:
            # Never leave a partial batch committed then marked skipped.
            self._conn.rollback()
            raise
        # executemany.rowcount is -1 on some drivers; fall back to len.
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(payload)

    def _existing_by_key(
        self, table: str, key_cols: list[str], rows: list[Mapping[str, Any]]
    ) -> dict[tuple, dict]:
        """Existing rows keyed by natural-key tuple (empty if none match).

        Chunked to stay under SQLite's host-parameter limit on older builds.
        """
        out: dict[tuple, dict] = {}
        if not rows:
            return out
        one = "(" + ",".join("?" for _ in key_cols) + ")"
        chunk = max(1, 500 // max(1, len(key_cols)))
        sel_prefix = (
            f"SELECT * FROM {table} WHERE ({','.join(key_cols)}) IN (VALUES "
        )
        for i in range(0, len(rows), chunk):
            batch = rows[i : i + chunk]
            value_rows = ",".join(one for _ in batch)
            params = [v for r in batch for v in (r[k] for k in key_cols)]
            cur = self._conn.execute(sel_prefix + value_rows + ")", params)
            for row in cur.fetchall():
                d = dict(row)
                out[tuple(d[k] for k in key_cols)] = d
        return out

    # --- helpers ----------------------------------------------------------

    def count(self, table: str) -> int:
        return self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def fetch_all(self, table: str) -> list[dict]:
        return [dict(r) for r in self._conn.execute(f"SELECT * FROM {table}").fetchall()]

    def fetch_where(self, table: str, where: str, params: tuple = ()) -> list[dict]:
        return [
            dict(r)
            for r in self._conn.execute(
                f"SELECT * FROM {table} WHERE {where}", params
            ).fetchall()
        ]

    def log_run(
        self,
        *,
        source: str,
        runtime: str,
        status: str,
        detail: str = "",
        ran_at: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail) "
            "VALUES (?,?,?,?,?)",
            (ran_at or now_iso(), source, runtime, status, detail),
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover
            pass

    def __enter__(self) -> "SqliteStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
