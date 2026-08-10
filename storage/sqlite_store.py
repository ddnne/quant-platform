"""SQLite writer for structured ingestion rows.

Generic over tables defined in :mod:`storage.schema`. The hard PIT rule lives
here: any row lacking ``available_at`` is rejected before it touches the DB.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from ingestion.common.timeutil import now_iso

from .schema import NATURAL_KEYS, SCHEMA_SQL


class MissingAvailableAt(ValueError):
    """Raised when a structured row lacks ``available_at`` (PIT violation)."""


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
        """Idempotent upsert that preserves the earliest ``available_at``.

        Validates ``available_at`` on every row, then upserts keyed on the
        table's natural-key PRIMARY KEY. On conflict:

        * ``available_at`` is kept as the **earliest** of (existing, incoming)
          so a re-upsert never overwrites the original point-in-time stamp.
        * every other column takes the incoming value (e.g. an amended
          ``close``), and ``ingested_at`` is refreshed to the latest fetch.

        All incoming available_at values are canonical +09:00 ISO strings, so
        ``MIN(...)`` (lexicographic on TEXT) is also chronologically correct.

        The whole batch runs in one transaction; any failure rolls back so a
        partial batch is never committed.
        """
        rows = list(rows)
        if not rows:
            return 0

        for i, r in enumerate(rows):
            av = r.get("available_at")
            if av is None or (isinstance(av, str) and not av.strip()):
                raise MissingAvailableAt(
                    f"{table}[{i}] missing available_at — PIT requires available_at"
                )

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
        payload = [[r.get(c) for c in cols] for r in rows]

        key_cols = NATURAL_KEYS.get(table, [])
        if key_cols and all(k in seen for k in key_cols):
            # ON CONFLICT<natural key> DO UPDATE: keep earliest available_at,
            # refresh everything else from the incoming row.
            target = ",".join(key_cols)
            key_set = set(key_cols)
            assigns = []
            for c in cols:
                if c in key_set:
                    continue
                if c == "available_at":
                    assigns.append(
                        "available_at = MIN(available_at, excluded.available_at)"
                    )
                else:
                    assigns.append(f"{c} = excluded.{c}")
            sql = (
                f"INSERT INTO {table} ({collist}) VALUES ({placeholders}) "
                f"ON CONFLICT({target}) DO UPDATE SET {','.join(assigns)}"
            )
        else:
            # Defensive fallback (should not happen for known tables).
            sql = (
                f"INSERT OR REPLACE INTO {table} ({collist}) "
                f"VALUES ({placeholders})"
            )

        try:
            cur = self._conn.executemany(sql, payload)
            self._conn.commit()
        except Exception:
            # Never leave a partial batch committed then marked skipped.
            self._conn.rollback()
            raise
        # executemany.rowcount is -1 on some drivers; fall back to len.
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(payload)

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
