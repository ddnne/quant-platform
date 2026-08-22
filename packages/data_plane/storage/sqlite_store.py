"""SQLite writer for structured ingestion rows. ``available_at`` is mandatory."""

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

from .migrate_jquants_keys import (
    ensure_migration_table,
    migrate_before_write,
    migrate_contract_keys_v2,
)
from .migrations import apply_schema_migrations
from .schema import NATURAL_KEYS, REVISION_TABLES, SCHEMA_SQL


class MissingAvailableAt(ValueError):
    """Raised when a structured row lacks ``available_at`` (PIT violation)."""


def _payload_signature(
    row: Mapping[str, Any], cols: list[str], skip: set[str]
) -> str:
    """Canonical payload signature. Prefers ``raw_payload`` when present."""
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
    """Earlier of two ``available_at`` instants (aware datetimes, not text)."""
    da, db = parse_dt(a), parse_dt(b)
    return to_iso(da if da <= db else db)


def _later_available(a: str, b: str) -> str:
    """Return the later aware instant in canonical storage form."""
    da, db = parse_dt(a), parse_dt(b)
    return to_iso(da if da >= db else db)


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
        apply_schema_migrations(self._conn)
        ensure_migration_table(self._conn)
        with self._conn:
            migrate_contract_keys_v2(self._conn, now_iso=now_iso())

    def upsert(self, table: str, rows: Iterable[Mapping[str, Any]]) -> int:
        """PIT-safe upsert on the natural key. Unchanged re-fetch keeps earliest
        ``available_at``; amendments archive the displaced row first.
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
            r["available_at"] = validate_available_at(av)

        cols: list[str] = []
        seen: set[str] = set()
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    cols.append(k)

        if table == "jquants_records":
            migrate_before_write(
                self._conn,
                (r.get("dataset") for r in rows if r.get("dataset")),
                now_iso=now_iso(),
            )

        placeholders = ",".join("?" for _ in cols)
        collist = ",".join(cols)
        revisions_to_archive: tuple[list[str], list[dict[str, Any]]] | None = None

        key_cols = NATURAL_KEYS.get(table, [])
        if key_cols and all(k in seen for k in key_cols):
            key_set = set(key_cols)
            skip = key_set | {"available_at", "ingested_at"}
            existing = self._existing_by_key(table, key_cols, rows)
            revisions: list[dict[str, Any]] = []

            for r in rows:
                key = tuple(r[k] for k in key_cols)
                ex = existing.get(key)
                if ex is not None and _payload_signature(
                    r, cols, skip
                ) == _payload_signature(ex, cols, skip):
                    r["available_at"] = _earlier_available(
                        ex["available_at"], r["available_at"]
                    )
                elif ex is not None:
                    if r.get("ingested_at"):
                        r["available_at"] = _later_available(
                            r["available_at"], str(r["ingested_at"])
                        )
                    revisions.append(dict(ex))
                existing[key] = dict(r)

            if revisions:
                revisions_to_archive = (key_cols, revisions)

            assigns = [f"{c} = excluded.{c}" for c in cols if c not in key_set]
            sql = (
                f"INSERT INTO {table} ({collist}) VALUES ({placeholders}) "
                f"ON CONFLICT({','.join(key_cols)}) DO UPDATE SET {','.join(assigns)}"
            )
        else:
            sql = (
                f"INSERT OR REPLACE INTO {table} ({collist}) "
                f"VALUES ({placeholders})"
            )

        payload = [[r.get(c) for c in cols] for r in rows]
        try:
            if revisions_to_archive is not None:
                self._archive_revisions(table, *revisions_to_archive)
            cur = self._conn.executemany(sql, payload)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(payload)

    def _archive_revisions(
        self, table: str, key_cols: list[str], rows: list[Mapping[str, Any]]
    ) -> None:
        """Persist displaced fact rows. Caller owns the surrounding transaction."""
        revision_table = REVISION_TABLES.get(table)
        if revision_table is None or not rows:
            return
        cols = list(rows[0].keys())
        placeholders = ",".join("?" for _ in cols)
        version_key = [*key_cols, "available_at", "ingested_at"]
        version_key_set = set(version_key)
        assigns = [f"{c} = excluded.{c}" for c in cols if c not in version_key_set]
        conflict = f"ON CONFLICT({','.join(version_key)}) DO NOTHING"
        if assigns:
            conflict = (
                f"ON CONFLICT({','.join(version_key)}) DO UPDATE SET "
                + ",".join(assigns)
            )
        sql = (
            f"INSERT INTO {revision_table} ({','.join(cols)}) "
            f"VALUES ({placeholders}) {conflict}"
        )
        self._conn.executemany(sql, [[row.get(c) for c in cols] for row in rows])

    def _existing_by_key(
        self, table: str, key_cols: list[str], rows: list[Mapping[str, Any]]
    ) -> dict[tuple, dict]:
        """Existing rows keyed by natural-key tuple. Chunked for SQLite param limits."""
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
