#!/usr/bin/env python3
"""Phase 3.5 S6 — sync Cloudflare D1 → local SQLite for `pit.get_*`.

The preferred production path uses the operator's authenticated Wrangler
session to export the private ingestion D1 directly.  An explicit local D1 SQL
export is also accepted for offline/bootstrap recovery, while the legacy
authenticated Worker export remains available during migration.

No explicit source defaults to the pinned private production D1 path; legacy
HTTP is used only with an explicit ``--url``. ``--incremental`` applies ``change_seq >
last_applied_change_seq`` after each durable page. Full table export is
bootstrap.  Replaying a page after interruption is idempotent; the cursor is
never allowed to move backwards.

Sync never mints READY from caller assertions. It can invoke the exact-four
publisher only with an Ed25519-verified Ops Projection envelope; otherwise it
finishes the apply and leaves snapshot publication closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, TypeVar
from urllib.parse import quote, urlencode
from weakref import WeakSet

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
else:
    raise RuntimeError("scripts/_bootstrap.py not found")
from _bootstrap import ensure_repo_root  # noqa: E402

ensure_repo_root()

import _private_d1_export as _private_export  # noqa: E402
from paper_runtime import (  # noqa: E402
    begin_snapshot_sync,
    fail_snapshot_sync,
)
from storage.sqlite_store import SqliteStore  # noqa: E402

_MirrorResult = TypeVar("_MirrorResult")

DEFAULT_TABLES: tuple[str, ...] = (
    "jquants_market_calendar",
    "jquants_listed_info",
    "jquants_daily_bars",
    "jquants_records",
    "jquants_market_calendar_revisions",
    "jquants_listed_info_revisions",
    "jquants_daily_bars_revisions",
    "jquants_records_revisions",
    "ingestion_run_log",
    "ingestion_validation",
    "ingestion_watermarks",
    "raw_retention_manifests",
    "coverage_segments",
    "collection_receipts",
)
DEFAULT_PAGE_LIMIT = 500
DEFAULT_MAX_PAGES = 10_000
_CHANGE_FEED_TABLES = frozenset({
    "jquants_records",
    "jquants_records_revisions",
})
# Change-feed markers with no local table; sequence still advances past them.
_CHANGE_FEED_SKIP_TABLES = frozenset({
    "jquants_records_r2",
    "equities_master_scd2",
})
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sync CF D1 → local SQLite (PIT)")
    p.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help="Fail if one export stream exceeds this many pages (default: 10000).",
    )
    source = p.add_mutually_exclusive_group()
    source.add_argument(
        "--url",
        default=None,
        help="Legacy base URL of the authenticated ingestion-premium worker",
    )
    source.add_argument(
        "--d1-export",
        default=None,
        help=(
            "Existing Wrangler D1 SQL or standalone SQLite export to apply "
            "offline. This input is operator-supplied/apply-only and cannot "
            "authorize READY."
        ),
    )
    source.add_argument(
        "--wrangler-remote",
        action="store_true",
        help=(
            "Privately export the governed production ingestion D1 with the "
            "repository-pinned Wrangler and apply it without a Worker URL."
        ),
    )
    p.add_argument(
        "--table",
        action="append",
        default=None,
        help="Restrict sync to one or more tables (repeatable).",
    )
    p.add_argument(
        "--db",
        required=True,
        help="Local SQLite path (will be created if missing).",
    )
    p.add_argument(
        "--snapshot-dir",
        default=None,
        help="READY artifact directory (default: <db-parent>/snapshots).",
    )
    p.add_argument(
        "--pilot-ready-evidence",
        default=None,
        help=(
            "Signed exact-four Ops Projection evidence envelope. Unsigned or "
            "untrusted JSON is rejected and cannot publish READY."
        ),
    )
    p.add_argument(
        "--page-limit",
        type=int,
        default=DEFAULT_PAGE_LIMIT,
        help="Rows requested per D1 export page (1-1000, default: 500).",
    )
    p.add_argument(
        "--incremental",
        action="store_true",
        help="Apply sequenced Worker changes after the local change_seq watermark.",
    )
    p.add_argument(
        "--since",
        default=None,
        help="Legacy ISO filter; production incremental sync uses change_seq.",
    )
    p.add_argument(
        "--publish-ops",
        action="store_true",
        help="After a successful sync, run scripts/publish_ops_projection.py (default off).",
    )
    p.add_argument(
        "--apply-remote-ops",
        action="store_true",
        help="With --publish-ops, also apply projection SQL to remote D1.",
    )
    return p


def _new_http_client():
    """Lazy httpx factory so tests can monkeypatch."""
    try:
        import httpx  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("httpx is required for sync (pip install httpx)") from exc
    return httpx.Client(timeout=120.0)


def _http_get_json(client, url: str, token: str) -> dict:
    """GET JSON; tests monkeypatch this symbol."""
    headers = {"X-Ingestion-Token": token} if token else {}
    resp = client.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


_materialize_d1_export = _private_export.materialize_d1_export
_open_export_sqlite = _private_export.open_export_sqlite


# Control-plane / non-PIT tables: no available_at column; must not be filtered.
_NO_AVAILABLE_AT_TABLES = frozenset({
    "ingestion_validation",
    "ingestion_run_log",
    "ingestion_watermarks",
    "raw_retention_manifests",
    "coverage_segments",
    "collection_receipts",
})


def _ensure_control_tables(conn: sqlite3.Connection) -> None:
    """Create control-plane tables if the local DB predates migrations."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ingestion_validation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            dataset TEXT,
            started_at TEXT,
            finished_at TEXT,
            status TEXT,
            rows_seen INTEGER,
            rows_inserted INTEGER,
            rows_revisions INTEGER,
            available_at_min TEXT,
            available_at_max TEXT,
            detail TEXT
        );
        CREATE TABLE IF NOT EXISTS ingestion_run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ran_at TEXT,
            source TEXT,
            runtime TEXT,
            status TEXT,
            detail TEXT,
            started_at TEXT,
            finished_at TEXT,
            dataset_count INTEGER,
            passed INTEGER,
            failed INTEGER,
            rows_inserted INTEGER,
            raw_bytes INTEGER,
            triggered_by TEXT
        );
        CREATE TABLE IF NOT EXISTS ingestion_watermarks (
            dataset TEXT PRIMARY KEY,
            last_event_date TEXT,
            last_ingested_at TEXT NOT NULL,
            last_export_cursor INTEGER
        );
        CREATE TABLE IF NOT EXISTS raw_retention_manifests (
            dataset TEXT NOT NULL,
            run_id INTEGER NOT NULL,
            manifest_key TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            row_count INTEGER NOT NULL,
            raw_bytes INTEGER NOT NULL,
            data_digest TEXT NOT NULL,
            completeness TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (dataset, run_id)
        );
        CREATE TABLE IF NOT EXISTS collection_receipts (
            source TEXT NOT NULL,
            dataset TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            segment_start TEXT NOT NULL,
            segment_end TEXT NOT NULL,
            expected_scope TEXT NOT NULL,
            expected_items INTEGER,
            observed_items INTEGER NOT NULL,
            raw_page_count INTEGER NOT NULL,
            raw_row_count INTEGER NOT NULL,
            structured_row_count INTEGER NOT NULL,
            pagination_exhausted INTEGER NOT NULL,
            digests_json TEXT NOT NULL,
            run_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            error TEXT,
            checked_at TEXT NOT NULL,
            PRIMARY KEY (source, dataset, segment_id, run_id)
        );
        CREATE TABLE IF NOT EXISTS coverage_segments (
            source TEXT NOT NULL,
            dataset TEXT NOT NULL,
            segment_id TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            segment_start TEXT NOT NULL,
            segment_end TEXT NOT NULL,
            expected_scope TEXT NOT NULL,
            expected_items INTEGER,
            status TEXT NOT NULL,
            receipt_run_id INTEGER,
            evaluated_at TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            PRIMARY KEY (source, dataset, segment_id, policy_version)
        );
        """
    )


def _local_table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return physical column names for ``table`` (empty if missing)."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    names: set[str] = set()
    for row in rows:
        name = row[1] if not isinstance(row, sqlite3.Row) else row["name"]
        names.add(str(name))
    return names


def _sync_control_plane(
    store: SqliteStore, table: str, rows: list[dict]
) -> tuple[int, int]:
    """Insert/replace control-plane rows; drop remote-only columns."""
    if not rows:
        return 0, 0
    conn = store._conn  # noqa: SLF001
    _ensure_control_tables(conn)
    local_cols = _local_table_columns(conn, table)
    cleaned = []
    dropped_cols: set[str] = set()
    for r in rows:
        row = {}
        for k, v in r.items():
            if k == "__export_cursor":
                continue
            if local_cols and k not in local_cols:
                dropped_cols.add(k)
                continue
            row[k] = v
        cleaned.append(row)
    warned_attr = f"_qp_dropped_cols_warned_{table}"
    if dropped_cols and not getattr(_sync_control_plane, warned_attr, False):
        print(
            f"[sync] {table}: dropped remote-only columns "
            f"{sorted(dropped_cols)} (absent from local schema)",
            file=sys.stderr,
        )
        setattr(_sync_control_plane, warned_attr, True)
    if not cleaned:
        return len(rows), 0
    cols = list(cleaned[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(cols)
    if table == "ingestion_watermarks" and "dataset" in cols:
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT(dataset) DO UPDATE SET "
            + ", ".join(f"{c}=excluded.{c}" for c in cols if c != "dataset")
        )
    elif table == "raw_retention_manifests" and {"dataset", "run_id"} <= set(cols):
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            "ON CONFLICT(dataset, run_id) DO UPDATE SET "
            + ", ".join(
                f"{c}=excluded.{c}" for c in cols if c not in {"dataset", "run_id"}
            )
        )
    elif table == "collection_receipts" and {
        "source", "dataset", "segment_id", "run_id"
    } <= set(cols):
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            "ON CONFLICT(source, dataset, segment_id, run_id) DO UPDATE SET "
            + ", ".join(
                f"{c}=excluded.{c}"
                for c in cols
                if c not in {"source", "dataset", "segment_id", "run_id"}
            )
        )
    elif table == "coverage_segments" and {
        "source", "dataset", "segment_id", "policy_version"
    } <= set(cols):
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            "ON CONFLICT(source, dataset, segment_id, policy_version) "
            "DO UPDATE SET "
            + ", ".join(
                f"{c}=excluded.{c}"
                for c in cols
                if c not in {
                    "source", "dataset", "segment_id", "policy_version"
                }
            )
        )
    elif "id" in cols:
        sql = (
            f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
        )
    else:
        sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    n = 0
    for row in cleaned:
        conn.execute(sql, [row.get(c) for c in cols])
        n += 1
    conn.commit()
    return len(rows), n


def _sync_one(
    store: SqliteStore, table: str, rows: list[dict]
) -> tuple[int, int]:
    """Upsert rows into local table. Returns (seen, registered)."""
    if not rows:
        return 0, 0
    if table in _NO_AVAILABLE_AT_TABLES:
        return _sync_control_plane(store, table, rows)
    cleaned = []
    for r in rows:
        row = {k: v for k, v in r.items() if v is not None}
        if not row.get("available_at"):
            continue
        cleaned.append(row)
    if not cleaned:
        return len(rows), 0
    n = store.upsert(table, cleaned)
    return len(rows), n


def _derive_since(store: SqliteStore, table: str) -> str | None:
    """MAX(ingested_at) watermark, or None when the table is empty/missing."""
    try:
        row = store._conn.execute(  # noqa: SLF001 — read-only helper
            f"SELECT MAX(ingested_at) AS mx FROM {table}"
        ).fetchone()
    except Exception:  # noqa: BLE001 — table may not exist yet on first run
        return None
    if not row:
        return None
    return row["mx"] if isinstance(row, sqlite3.Row) else row[0]


def _filter_since(rows: list[dict], since: str) -> tuple[list[dict], int]:
    """Keep rows with ingested_at > since (ISO text compare). Returns (kept, skipped)."""
    if not since:
        return rows, 0
    kept: list[dict] = []
    skipped = 0
    for r in rows:
        ia = r.get("ingested_at")
        if isinstance(ia, str) and ia <= since:
            skipped += 1
            continue
        kept.append(r)
    return kept, skipped


def _sync_table(
    store: SqliteStore,
    client,
    base: str,
    token: str,
    table: str,
    *,
    page_limit: int,
    since: str | None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> tuple[int, int, int, int, str | None]:
    """Pull one table. Returns (pages, seen, registered, skipped, effective_since)."""
    cursor: str | int | None = None
    pages = seen = registered = skipped = 0
    seen_cursors: set[str] = set()
    while True:
        if pages >= max_pages:
            raise ValueError(
                f"export exceeded max_pages={max_pages} for table={table}"
            )
        query: dict[str, str | int] = {"table": table, "limit": page_limit}
        if cursor is not None:
            query["cursor"] = cursor
        endpoint = f"{base}/v1/export/d1?{urlencode(query)}"
        payload = _http_get_json(client, endpoint, token)
        if payload.get("table", table) != table:
            raise ValueError(
                f"export returned table={payload.get('table')!r}, expected {table!r}"
            )
        rows = payload.get("rows") or []
        if not isinstance(rows, list):
            raise ValueError("export rows must be a list")
        if since:
            rows, page_skipped = _filter_since(rows, since)
            skipped += page_skipped
        seen += len(rows)
        page_registered = _sync_one(store, table, rows)[1]
        registered += page_registered
        pages += 1

        if not payload.get("has_more", False):
            break
        next_cursor = payload.get("next_cursor")
        if next_cursor is None or next_cursor == cursor:
            raise ValueError("export pagination did not advance cursor")
        cursor_token = str(next_cursor)
        if cursor_token in seen_cursors:
            raise ValueError("export pagination repeated a prior cursor")
        seen_cursors.add(cursor_token)
        cursor = next_cursor
    return pages, seen, registered, skipped, since


def _last_change_seq(store: SqliteStore) -> int:
    row = store._conn.execute(  # noqa: SLF001
        "SELECT last_applied_change_seq FROM main.sync_change_state "
        "WHERE feed = 'jquants_records'"
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _record_change_seq(store: SqliteStore, value: int) -> None:
    if not isinstance(value, int) or value < 0:
        raise ValueError("applied change_seq must be a non-negative integer")
    current = _last_change_seq(store)
    if value < current:
        raise ValueError(
            f"refusing to move applied change_seq backwards ({current} -> {value})"
        )
    store._conn.execute(  # noqa: SLF001
        """
        INSERT INTO main.sync_change_state (feed, last_applied_change_seq, updated_at)
        VALUES ('jquants_records', ?, ?)
        ON CONFLICT(feed) DO UPDATE SET
            last_applied_change_seq = excluded.last_applied_change_seq,
            updated_at = excluded.updated_at
        """,
        (value, datetime.now(timezone.utc).isoformat()),
    )
    store._conn.commit()  # noqa: SLF001


def _apply_change_rows(store: SqliteStore, rows: list[dict]) -> tuple[int, int]:
    """Apply one sequenced page. Returns (registered, skipped)."""
    registered = 0
    skipped = 0
    current_table: str | None = None
    current_rows: list[dict] = []

    def flush() -> None:
        nonlocal registered, current_rows
        if current_table is not None and current_rows:
            registered += _sync_one(store, current_table, current_rows)[1]
        current_rows = []

    for source in rows:
        table = str(source.get("table_name", ""))
        if table in _CHANGE_FEED_SKIP_TABLES:
            skipped += 1
            continue
        if table not in _CHANGE_FEED_TABLES:
            raise ValueError(f"change feed target is not allowed: {table!r}")
        if current_table != table:
            flush()
            current_table = table
        current_rows.append({
            key: value
            for key, value in source.items()
            if key not in {"change_seq", "table_name"}
        })
    flush()
    return registered, skipped


def _sync_changes(
    store: SqliteStore,
    client,
    base: str,
    token: str,
    *,
    page_limit: int,
    max_pages: int = DEFAULT_MAX_PAGES,
    legacy_since: str | None = None,
) -> tuple[int, int, int, int]:
    """Consume the monotonic change feed. Returns (pages, seen, registered, last_seq)."""
    after_seq = _last_change_seq(store)
    pages = seen = registered = skipped = 0
    visited = {after_seq}
    while True:
        if pages >= max_pages:
            raise ValueError(f"change feed exceeded max_pages={max_pages}")
        query = {
            "after_seq": after_seq,
            "limit": page_limit,
            "table": "jquants_records",
        }
        endpoint = f"{base}/v1/export/changes?{urlencode(query)}"
        payload = _http_get_json(client, endpoint, token)
        rows = payload.get("rows") or []
        if not isinstance(rows, list):
            raise ValueError("change feed rows must be a list")
        pages += 1

        if payload.get("format") != "jquants-change-feed/v1":
            filtered, _ = _filter_since(rows, legacy_since or "")
            seen += len(filtered)
            registered += _sync_one(store, "jquants_records", filtered)[1]
            if payload.get("has_more", False):
                raise ValueError(
                    "legacy incremental response cannot safely paginate; "
                    "deploy the Phase 6 change-feed Worker"
                )
            break

        previous = after_seq
        for row in rows:
            seq = row.get("change_seq")
            if not isinstance(seq, int) or seq <= previous:
                raise ValueError("change feed sequence is not strictly increasing")
            previous = seq
        next_seq = payload.get("next_seq", previous)
        if not isinstance(next_seq, int) or next_seq != previous:
            raise ValueError("change feed next_seq does not match its final row")
        seen += len(rows)
        page_registered, page_skipped = _apply_change_rows(store, rows)
        registered += page_registered
        skipped += page_skipped
        _record_change_seq(store, next_seq)
        after_seq = next_seq
        if not payload.get("has_more", False):
            break
        if not rows or after_seq in visited:
            raise ValueError("change feed pagination did not advance")
        visited.add(after_seq)
    if skipped:
        print(
            f"[sync] change_feed: skipped_non_local={skipped} "
            f"(R2/SCD2 markers; seq advanced)",
            file=sys.stderr,
        )
    return pages, seen, registered, after_seq


def _source_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM main.sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _validate_sync_table(table: str) -> str:
    if table not in DEFAULT_TABLES:
        raise ValueError(f"table is outside the governed sync inventory: {table!r}")
    return table


def _source_change_seq(conn: sqlite3.Connection) -> int:
    if not _source_table_exists(conn, "ingestion_change_log"):
        raise ValueError("D1 export is missing ingestion_change_log")
    columns = {
        str(row[1])
        for row in conn.execute(
            "PRAGMA main.table_info(ingestion_change_log)"
        ).fetchall()
    }
    required = {
        "change_seq",
        "table_name",
        "source",
        "dataset",
        "natural_key",
        "event_time",
        "available_at",
        "ingested_at",
        "payload",
        "raw_payload",
    }
    missing = sorted(required - columns)
    if missing:
        raise ValueError(f"D1 change feed is missing required columns: {missing}")
    row = conn.execute(
        "SELECT COALESCE(MAX(change_seq), 0) FROM main.ingestion_change_log"
    ).fetchone()
    value = row[0] if row is not None else 0
    if not isinstance(value, int) or value < 0:
        raise ValueError("D1 source change_seq is invalid")
    return value


def _governed_local_content_identity(
    store: SqliteStore | sqlite3.Connection,
    tables: tuple[str, ...] | None = None,
) -> tuple[str, dict[str, int]]:
    """Content-address all governed source-derived tables in the local mirror."""
    conn = store if isinstance(store, sqlite3.Connection) else store._conn  # noqa: SLF001
    tables = tables or DEFAULT_TABLES
    content_digest, _schema_digest, counts = _private_export.governed_content_identity(
        conn, tables
    )
    return content_digest, counts


def _verify_source_local_parity(
    store: SqliteStore,
    source: sqlite3.Connection,
    tables: list[str],
) -> tuple[str, str, dict[str, int]]:
    """Verify exact source/local schema, row counts, and content digests."""
    local = store._conn  # noqa: SLF001
    source_identity, _source_schema, _local_schema, counts = (
        _private_export._exact_source_local_reconciliation(  # noqa: SLF001
            source, local, tuple(tables)
        )
    )
    return source_identity, source_identity, counts


def _reset_governed_local_tables(store: SqliteStore, tables: list[str]) -> None:
    """Remove the prior mirror before a trusted full bootstrap.

    The audit row is intentionally outside this inventory. If the process is
    interrupted, its APPLYING status prevents cursor publication and a rerun
    reconstructs the governed tables from the authenticated export.
    """
    conn = store._conn  # noqa: SLF001
    for table in tables:
        if not _source_table_exists(conn, table):
            raise ValueError(f"local mirror is missing governed table: {table}")
        conn.execute(f'DELETE FROM main."{table}"')
    conn.execute(
        "DELETE FROM main.sync_change_state WHERE feed='jquants_records'"
    )
    conn.commit()


def _sync_export_table(
    store: SqliteStore,
    source: sqlite3.Connection,
    table: str,
    *,
    page_limit: int,
    since: str | None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> tuple[int, int, int, int, str | None]:
    """Apply one table from an isolated D1 export SQLite database."""
    table = _validate_sync_table(table)
    if not _source_table_exists(source, table):
        raise ValueError(f"D1 export is missing required table: {table}")
    cursor = 0
    pages = seen = registered = skipped = 0
    while True:
        if pages >= max_pages:
            raise ValueError(
                f"export exceeded max_pages={max_pages} for table={table}"
            )
        fetched = source.execute(
            f'SELECT rowid AS "__sync_rowid", * FROM main."{table}" '
            'WHERE rowid > ? ORDER BY rowid LIMIT ?',
            (cursor, page_limit + 1),
        ).fetchall()
        has_more = len(fetched) > page_limit
        page = fetched[:page_limit]
        rows = []
        for source_row in page:
            row = dict(source_row)
            cursor = int(row.pop("__sync_rowid"))
            rows.append(row)
        if since:
            rows, page_skipped = _filter_since(rows, since)
            skipped += page_skipped
        seen += len(rows)
        registered += _sync_one(store, table, rows)[1]
        pages += 1
        if not has_more:
            break
    return pages, seen, registered, skipped, since


def _sync_export_changes(
    store: SqliteStore,
    source: sqlite3.Connection,
    *,
    page_limit: int,
    max_pages: int = DEFAULT_MAX_PAGES,
    source_max_seq: int | None = None,
) -> tuple[int, int, int, int]:
    """Apply a private export's append-only change log page by page.

    Each page's fact upserts commit before its cursor. If the process stops in
    between, replay starts from the older cursor and the PIT upserts remain
    idempotent. A stale export can never roll the cursor back.
    """
    maximum = _source_change_seq(source) if source_max_seq is None else source_max_seq
    after_seq = _last_change_seq(store)
    if maximum < after_seq:
        raise ValueError(
            "D1 export is older than the local applied cursor; refusing stale apply"
        )
    pages = seen = registered = skipped = 0
    select_columns = (
        "change_seq, table_name, source, dataset, natural_key, event_time, "
        "available_at, ingested_at, payload, raw_payload"
    )
    while True:
        if pages >= max_pages:
            raise ValueError(f"change feed exceeded max_pages={max_pages}")
        fetched = source.execute(
            f"SELECT {select_columns} FROM main.ingestion_change_log "
            "WHERE change_seq > ? ORDER BY change_seq LIMIT ?",
            (after_seq, page_limit + 1),
        ).fetchall()
        has_more = len(fetched) > page_limit
        rows = [dict(row) for row in fetched[:page_limit]]
        pages += 1
        previous = after_seq
        for row in rows:
            seq = row.get("change_seq")
            if not isinstance(seq, int) or seq <= previous:
                raise ValueError("change feed sequence is not strictly increasing")
            previous = seq
        page_registered, page_skipped = _apply_change_rows(store, rows)
        registered += page_registered
        skipped += page_skipped
        seen += len(rows)
        _record_change_seq(store, previous)
        after_seq = previous
        if not has_more:
            break
        if not rows:
            raise ValueError("change feed pagination did not advance")
    if after_seq != maximum:
        raise ValueError(
            "D1 export change feed did not converge to its measured source cursor"
        )
    if skipped:
        print(
            f"[sync] change_feed: skipped_non_local={skipped} "
            f"(R2/SCD2 markers; seq advanced)",
            file=sys.stderr,
        )
    return pages, seen, registered, after_seq


def _ensure_export_sync_audit(store: SqliteStore) -> None:
    store._conn.execute(  # noqa: SLF001
        """
        CREATE TABLE IF NOT EXISTS main.local_d1_export_sync_runs (
            export_digest     TEXT PRIMARY KEY,
            artifact_format   TEXT NOT NULL,
            source_mode       TEXT NOT NULL,
            sync_kind         TEXT NOT NULL DEFAULT 'UNTRUSTED',
            source_change_seq INTEGER,
            applied_change_seq INTEGER NOT NULL,
            source_content_digest TEXT,
            local_content_digest TEXT,
            schema_digest     TEXT,
            table_counts_json TEXT,
            authority_id      TEXT,
            prior_audit_digest TEXT,
            audit_digest      TEXT,
            issuer_key_id     TEXT,
            signature         TEXT,
            signed_evidence_json TEXT,
            status            TEXT NOT NULL
                CHECK (status IN ('APPLYING', 'COMPLETE', 'FAILED')),
            started_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL,
            error             TEXT
        )
        """
    )
    columns = {
        str(row[1])
        for row in store._conn.execute(  # noqa: SLF001
            "PRAGMA main.table_info(local_d1_export_sync_runs)"
        )
    }
    additions = {
        "sync_kind": "TEXT NOT NULL DEFAULT 'UNTRUSTED'",
        "source_content_digest": "TEXT",
        "local_content_digest": "TEXT",
        "schema_digest": "TEXT",
        "table_counts_json": "TEXT",
        "authority_id": "TEXT",
        "prior_audit_digest": "TEXT",
        "audit_digest": "TEXT",
        "issuer_key_id": "TEXT",
        "signature": "TEXT",
        "signed_evidence_json": "TEXT",
    }
    for column, declaration in additions.items():
        if column not in columns:
            store._conn.execute(  # noqa: SLF001
                f"ALTER TABLE main.local_d1_export_sync_runs "
                f"ADD COLUMN {column} {declaration}"
            )
    store._conn.commit()  # noqa: SLF001


_SYNC_AUDIT_COLUMNS = (
    ("export_digest", "TEXT", 0, None, 1, 0),
    ("artifact_format", "TEXT", 1, None, 0, 0),
    ("source_mode", "TEXT", 1, None, 0, 0),
    ("sync_kind", "TEXT", 1, "'UNTRUSTED'", 0, 0),
    ("source_change_seq", "INTEGER", 0, None, 0, 0),
    ("applied_change_seq", "INTEGER", 1, None, 0, 0),
    ("source_content_digest", "TEXT", 0, None, 0, 0),
    ("local_content_digest", "TEXT", 0, None, 0, 0),
    ("schema_digest", "TEXT", 0, None, 0, 0),
    ("table_counts_json", "TEXT", 0, None, 0, 0),
    ("authority_id", "TEXT", 0, None, 0, 0),
    ("prior_audit_digest", "TEXT", 0, None, 0, 0),
    ("audit_digest", "TEXT", 0, None, 0, 0),
    ("issuer_key_id", "TEXT", 0, None, 0, 0),
    ("signature", "TEXT", 0, None, 0, 0),
    ("signed_evidence_json", "TEXT", 0, None, 0, 0),
    ("status", "TEXT", 1, None, 0, 0),
    ("started_at", "TEXT", 1, None, 0, 0),
    ("updated_at", "TEXT", 1, None, 0, 0),
    ("error", "TEXT", 0, None, 0, 0),
)


def _require_canonical_sync_audit_table(conn: sqlite3.Connection) -> None:
    """Reject database-side deputies on the signed COMPLETE write boundary."""
    columns = tuple(
        (row[1], row[2], row[3], row[4], row[5], row[6])
        for row in conn.execute(
            "PRAGMA main.table_xinfo(local_d1_export_sync_runs)"
        )
    )
    if columns != _SYNC_AUDIT_COLUMNS:
        raise ValueError("D1 sync audit table schema is not canonical")
    objects = conn.execute(
        "SELECT type,name,sql FROM main.sqlite_master "
        "WHERE tbl_name='local_d1_export_sync_runs' ORDER BY type,name"
    ).fetchall()
    expected_objects = [
        (
            "index",
            "sqlite_autoindex_local_d1_export_sync_runs_1",
            None,
        )
    ]
    observed_non_table = [tuple(row) for row in objects if row[0] != "table"]
    if observed_non_table != expected_objects or sum(
        int(row[0] == "table") for row in objects
    ) != 1:
        raise ValueError("D1 sync audit table has unowned schema objects")
    temp_deputies = conn.execute(
        "SELECT 1 FROM sqlite_temp_master "
        "WHERE name='local_d1_export_sync_runs' "
        "OR tbl_name='local_d1_export_sync_runs' LIMIT 1"
    ).fetchone()
    if temp_deputies is not None:
        raise ValueError("D1 sync audit table has an unowned temporary object")
    indexes = [
        (str(row[1]), int(row[2]), str(row[3]), int(row[4]))
        for row in conn.execute(
            "PRAGMA main.index_list(local_d1_export_sync_runs)"
        )
    ]
    if indexes != [
        ("sqlite_autoindex_local_d1_export_sync_runs_1", 1, "pk", 0)
    ] or list(
        conn.execute("PRAGMA main.foreign_key_list(local_d1_export_sync_runs)")
    ):
        raise ValueError("D1 sync audit table constraints are not canonical")


def _mark_untrusted_export_sync(
    store: SqliteStore,
    *,
    export_digest: str,
    artifact_format: str,
    source_mode: str,
    sync_kind: str,
    source_change_seq: int | None,
    source_content_digest: str | None = None,
    local_content_digest: str | None = None,
    table_counts: dict[str, int] | None = None,
    status: str,
    error: str | None = None,
) -> None:
    _ensure_export_sync_audit(store)
    now = datetime.now(timezone.utc).isoformat()
    store._conn.execute(  # noqa: SLF001
        """
        INSERT INTO main.local_d1_export_sync_runs (
            export_digest, artifact_format, source_mode, source_change_seq,
            applied_change_seq, status, started_at, updated_at, error,
            sync_kind, source_content_digest, local_content_digest,
            table_counts_json, authority_id, schema_digest,
            prior_audit_digest, audit_digest, issuer_key_id, signature,
            signed_evidence_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(export_digest) DO UPDATE SET
            artifact_format=excluded.artifact_format,
            source_mode=excluded.source_mode,
            source_change_seq=excluded.source_change_seq,
            applied_change_seq=excluded.applied_change_seq,
            status=excluded.status,
            updated_at=excluded.updated_at,
            error=excluded.error
            ,sync_kind=excluded.sync_kind
            ,source_content_digest=excluded.source_content_digest
            ,local_content_digest=excluded.local_content_digest
            ,table_counts_json=excluded.table_counts_json
            ,authority_id=excluded.authority_id
            ,schema_digest=excluded.schema_digest
            ,prior_audit_digest=excluded.prior_audit_digest
            ,audit_digest=excluded.audit_digest
            ,issuer_key_id=excluded.issuer_key_id
            ,signature=excluded.signature
            ,signed_evidence_json=excluded.signed_evidence_json
        """,
        (
            export_digest,
            artifact_format,
            source_mode,
            source_change_seq,
            _last_change_seq(store),
            status,
            now,
            now,
            error[:1000] if error else None,
            sync_kind,
            source_content_digest,
            local_content_digest,
            json.dumps(table_counts, sort_keys=True, separators=(",", ":"))
            if table_counts is not None
            else None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        ),
    )
    store._conn.commit()  # noqa: SLF001


def _latest_export_sync_row(conn: sqlite3.Connection) -> dict[str, object] | None:
    """Select current authority by signed issuance time.

    Historical rows signed by retired keys are ignored for current
    eligibility; they must not make a later active-key FULL import
    impossible. Revoked or tampered rows never become current.
    """
    cursor = conn.execute(
        "SELECT * FROM main.local_d1_export_sync_runs "
        "WHERE status='COMPLETE' AND signed_evidence_json IS NOT NULL"
    )
    columns = tuple(column[0] for column in cursor.description or ())
    rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    if not rows:
        return None

    current: list[tuple[datetime, dict[str, object], Mapping[str, object]]] = []
    for row in rows:
        try:
            envelope = _verified_sync_envelope_from_row(
                conn,
                row,
                recompute_local=False,
                require_fresh=False,
                eligibility="current",
            )
        except (
            ValueError,
            TypeError,
            RuntimeError,
            json.JSONDecodeError,
            sqlite3.Error,
        ):
            continue
        issued_at = datetime.fromisoformat(
            str(envelope["issued_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        current.append((issued_at, row, envelope))
    if not current:
        return None
    current.sort(key=lambda candidate: candidate[0])
    if len(current) > 1 and current[-2][0] == current[-1][0]:
        raise ValueError("signed D1 sync audit issuance order is ambiguous")

    eligible: list[tuple[datetime, dict[str, object], Mapping[str, object]]] = []
    seen_digests: set[object] = set()
    previous_cursor = -1
    for issued_at, row, envelope in current:
        source_cursor = envelope["source_change_seq"]
        if not isinstance(source_cursor, int) or source_cursor < previous_cursor:
            continue
        if envelope["sync_kind"] == "FULL":
            eligible.append((issued_at, row, envelope))
        elif (
            envelope["sync_kind"] == "INCREMENTAL"
            and envelope["prior_audit_digest"] in seen_digests
        ):
            eligible.append((issued_at, row, envelope))
        else:
            continue
        previous_cursor = source_cursor
        seen_digests.add(row["audit_digest"])
    if not eligible:
        return None
    return eligible[-1][1]


def _verified_sync_envelope_from_row(
    conn: sqlite3.Connection,
    row: dict[str, object],
    *,
    recompute_local: bool,
    require_fresh: bool = True,
    eligibility: str = "current",
) -> Mapping[str, object]:
    from ops.d1_sync_signing import (
        GOVERNED_AUTHORITY_ID,
        _decode_strict_json,
        _verify_signed_d1_sync_audit_document,
    )

    if type(row) is not dict:
        raise TypeError("D1 sync audit row must be one exact dict")
    row = dict.copy(row)
    exact_text_fields = (
        "signed_evidence_json",
        "status",
        "audit_digest",
        "issuer_key_id",
        "signature",
        "table_counts_json",
        "export_digest",
        "artifact_format",
        "source_mode",
        "sync_kind",
        "source_content_digest",
        "local_content_digest",
        "schema_digest",
        "authority_id",
    )
    if any(type(row.get(field)) is not str for field in exact_text_fields):
        raise ValueError("D1 sync audit SQLite row types are not canonical")
    if any(
        type(row.get(field)) is not int
        for field in ("source_change_seq", "applied_change_seq")
    ) or type(row.get("prior_audit_digest")) not in {str, type(None)}:
        raise ValueError("D1 sync audit SQLite row types are not canonical")
    document_text = row.get("signed_evidence_json")
    assert type(document_text) is str
    verified_document = _verify_signed_d1_sync_audit_document(
        document_text, require_fresh=require_fresh, eligibility=eligibility
    )
    envelope = verified_document.envelope
    audit_digest = verified_document.document_digest
    expected_counts = envelope["table_counts"]
    if set(expected_counts) != set(DEFAULT_TABLES):
        raise ValueError("signed D1 sync audit inventory membership drift")
    row_counts = _decode_strict_json(
        row["table_counts_json"], field="D1 sync audit SQLite table counts"
    )
    row_bindings = {
        "export_digest": row.get("export_digest"),
        "artifact_format": row.get("artifact_format"),
        "source_mode": row.get("source_mode"),
        "sync_kind": row.get("sync_kind"),
        "source_change_seq": row.get("source_change_seq"),
        "applied_change_seq": row.get("applied_change_seq"),
        "source_content_digest": row.get("source_content_digest"),
        "local_content_digest": row.get("local_content_digest"),
        "schema_digest": row.get("schema_digest"),
        "authority_id": row.get("authority_id"),
        "prior_audit_digest": row.get("prior_audit_digest"),
    }
    if (
        row.get("status") != "COMPLETE"
        or row.get("audit_digest") != audit_digest
        or row.get("issuer_key_id") != verified_document.issuer_key_id
        or row.get("signature") != verified_document.signature
        or row_counts != expected_counts
        or row_bindings
        != {
            key: envelope[key]
            for key in row_bindings
        }
        or envelope["authority_id"] != GOVERNED_AUTHORITY_ID
    ):
        raise ValueError("signed D1 sync audit does not bind its SQLite row")
    if recompute_local:
        observed_content, observed_schema, observed_counts = (
            _private_export.governed_content_identity(conn, DEFAULT_TABLES)
        )
        current_cursor = conn.execute(
            "SELECT last_applied_change_seq FROM main.sync_change_state "
            "WHERE feed='jquants_records'"
        ).fetchone()
        applied = current_cursor[0] if current_cursor is not None else 0
        if (
            observed_content != envelope["local_content_digest"]
            or observed_schema != envelope["schema_digest"]
            or observed_counts != expected_counts
            or applied != envelope["applied_change_seq"]
        ):
            raise ValueError(
                "local governed mirror differs from the signed D1 sync audit"
            )
    return envelope


def _mark_authenticated_export_complete(
    store: SqliteStore,
    authenticated_export,
) -> Mapping[str, object]:
    """Persist one single-use capability; there is no caller evidence input."""
    from ops.d1_sync_signing import (
        _seal_authenticated_wrangler_export,
        _verify_signed_d1_sync_audit_document,
    )

    _ensure_export_sync_audit(store)
    sealed = _seal_authenticated_wrangler_export(authenticated_export)
    audit_digest, issuer_key_id, signature, document = (
        sealed._consume_for_persistence()  # noqa: SLF001
    )
    verified_document = _verify_signed_d1_sync_audit_document(
        document, require_fresh=True, eligibility="current"
    )
    envelope = verified_document.envelope
    if (
        audit_digest != verified_document.document_digest
        or issuer_key_id != verified_document.issuer_key_id
        or signature != verified_document.signature
    ):
        raise ValueError("authenticated D1 sync audit digest mismatch")
    if set(envelope["table_counts"]) != set(DEFAULT_TABLES):
        raise ValueError("authenticated D1 sync audit inventory membership drift")
    conn = store._conn  # noqa: SLF001
    conn.execute("BEGIN IMMEDIATE")
    try:
        _require_canonical_sync_audit_table(conn)
        observed_content, observed_schema, observed_counts = (
            _private_export.governed_content_identity(conn, DEFAULT_TABLES)
        )
        if (
            observed_content != envelope["local_content_digest"]
            or observed_schema != envelope["schema_digest"]
            or observed_counts != envelope["table_counts"]
            or _last_change_seq(store) != envelope["applied_change_seq"]
        ):
            raise ValueError(
                "authenticated D1 sync audit changed before persistence"
            )
        existing_cursor = conn.execute(
            "SELECT * FROM main.local_d1_export_sync_runs WHERE export_digest=?",
            (envelope["export_digest"],),
        )
        existing_tuple = existing_cursor.fetchone()
        if existing_tuple is not None and envelope["sync_kind"] == "INCREMENTAL":
            existing_row = dict(
                zip(
                    (column[0] for column in existing_cursor.description),
                    existing_tuple,
                    strict=True,
                )
            )
            existing_envelope = _verified_sync_envelope_from_row(
                conn,
                existing_row,
                recompute_local=True,
                require_fresh=False,
            )
            unchanged_fields = (
                "export_digest",
                "artifact_format",
                "source_change_seq",
                "applied_change_seq",
                "source_content_digest",
                "local_content_digest",
                "source_schema_digest",
                "schema_digest",
                "table_counts",
            )
            if not (
                envelope["prior_audit_digest"] == existing_row["audit_digest"]
                and all(
                    envelope[field] == existing_envelope[field]
                    for field in unchanged_fields
                )
            ):
                raise ValueError(
                    "incremental D1 export digest collision is not a no-op"
                )
            final_existing = _verify_signed_d1_sync_audit_document(
                existing_row["signed_evidence_json"],
                require_fresh=True,
                eligibility="current",
            )
            conn.rollback()
            return final_existing.envelope

        before_other_rows = conn.execute(
            "SELECT * FROM main.local_d1_export_sync_runs "
            "WHERE export_digest<>? ORDER BY export_digest",
            (envelope["export_digest"],),
        ).fetchall()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
        INSERT INTO main.local_d1_export_sync_runs (
            export_digest, artifact_format, source_mode, source_change_seq,
            applied_change_seq, status, started_at, updated_at, error,
            sync_kind, source_content_digest, local_content_digest,
            table_counts_json, authority_id, schema_digest,
            prior_audit_digest, audit_digest, issuer_key_id, signature,
            signed_evidence_json
        ) VALUES (?, ?, ?, ?, ?, 'COMPLETE', ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(export_digest) DO UPDATE SET
            artifact_format=excluded.artifact_format,
            source_mode=excluded.source_mode,
            source_change_seq=excluded.source_change_seq,
            applied_change_seq=excluded.applied_change_seq,
            status='COMPLETE',
            updated_at=excluded.updated_at,
            error=NULL,
            sync_kind=excluded.sync_kind,
            source_content_digest=excluded.source_content_digest,
            local_content_digest=excluded.local_content_digest,
            table_counts_json=excluded.table_counts_json,
            authority_id=excluded.authority_id,
            schema_digest=excluded.schema_digest,
            prior_audit_digest=excluded.prior_audit_digest,
            audit_digest=excluded.audit_digest,
            issuer_key_id=excluded.issuer_key_id,
            signature=excluded.signature,
            signed_evidence_json=excluded.signed_evidence_json
            """,
            (
                envelope["export_digest"],
                envelope["artifact_format"],
                envelope["source_mode"],
                envelope["source_change_seq"],
                envelope["applied_change_seq"],
                envelope["issued_at"],
                now,
                envelope["sync_kind"],
                envelope["source_content_digest"],
                envelope["local_content_digest"],
                json.dumps(
                    dict(envelope["table_counts"]),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                envelope["authority_id"],
                envelope["schema_digest"],
                envelope["prior_audit_digest"],
                audit_digest,
                issuer_key_id,
                signature,
                verified_document.canonical_document_json,
            ),
        )

        post_cursor = conn.execute(
            "SELECT * FROM main.local_d1_export_sync_runs WHERE export_digest=?",
            (envelope["export_digest"],),
        )
        post_tuple = post_cursor.fetchone()
        if post_tuple is None or post_cursor.fetchone() is not None:
            raise ValueError(
                "authenticated D1 sync audit postcondition row is not exact"
            )
        post_row = dict(
            zip(
                (column[0] for column in post_cursor.description),
                post_tuple,
                strict=True,
            )
        )
        if conn.execute(
            "SELECT * FROM main.local_d1_export_sync_runs "
            "WHERE export_digest<>? ORDER BY export_digest",
            (envelope["export_digest"],),
        ).fetchall() != before_other_rows:
            raise ValueError(
                "authenticated D1 sync audit changed unrelated audit rows"
            )
        post_envelope = _verified_sync_envelope_from_row(
            conn,
            post_row,
            recompute_local=True,
            require_fresh=False,
        )
        if post_envelope != envelope:
            raise ValueError(
                "authenticated D1 sync audit postcondition identity changed"
            )
        # Final UTC and signature verification happens after every SQLite and
        # governed-content postcondition.  Crossing the lease during any of
        # those checks rolls back the audit row and trigger side effects.
        final_document = _verify_signed_d1_sync_audit_document(
            verified_document.canonical_document_json,
            require_fresh=True,
            eligibility="current",
        )
        if (
            final_document.document_digest != audit_digest
            or final_document.issuer_key_id != issuer_key_id
            or final_document.signature != signature
            or final_document.envelope != post_envelope
        ):
            raise ValueError(
                "authenticated D1 sync audit final identity changed"
            )
        conn.commit()
        return final_document.envelope
    except Exception:
        conn.rollback()
        raise


def _latest_trusted_sync_audit(
    store: SqliteStore,
) -> tuple[dict[str, object], Mapping[str, object]] | None:
    _ensure_export_sync_audit(store)
    row = _latest_export_sync_row(store._conn)  # noqa: SLF001
    if row is None:
        return None
    try:
        envelope = _verified_sync_envelope_from_row(
            store._conn, row, recompute_local=True  # noqa: SLF001
        )
    except (ValueError, TypeError, RuntimeError, json.JSONDecodeError, sqlite3.Error):
        return None
    return row, envelope


def _require_trusted_incremental_base(
    store: SqliteStore,
) -> tuple[dict[str, object], Mapping[str, object]]:
    verified = _latest_trusted_sync_audit(store)
    if verified is None:
        raise ValueError(
            "authenticated incremental apply requires a prior trusted full bootstrap"
        )
    row, envelope = verified
    expected_cursor = envelope["applied_change_seq"]
    expected_digest = envelope["local_content_digest"]
    if (
        not isinstance(expected_cursor, int)
        or expected_cursor != _last_change_seq(store)
        or not isinstance(expected_digest, str)
        or not expected_digest.startswith("sha256:")
    ):
        raise ValueError("trusted incremental base cursor/content identity is invalid")
    observed_digest, _ = _governed_local_content_identity(store)
    if observed_digest != expected_digest:
        raise ValueError(
            "local governed content changed after the trusted base; "
            "run a full authenticated bootstrap"
        )
    return row, envelope


def _run_private_export_sync(
    store: SqliteStore,
    source: sqlite3.Connection,
    tables: list[str],
    args,
    *,
    export_digest: str,
    artifact_format: str,
    authenticated_acquisition=None,
) -> tuple[int, int, int, list[str]]:
    total_seen = total_registered = total_skipped = 0
    failures: list[str] = []
    _private_export.reject_temp_governed_deputies(
        source, DEFAULT_TABLES
    )
    _private_export.reject_temp_governed_deputies(
        store._conn, DEFAULT_TABLES  # noqa: SLF001
    )
    _ensure_control_tables(store._conn)  # noqa: SLF001
    _ensure_export_sync_audit(store)
    store._conn.commit()  # noqa: SLF001
    source_mode = (
        "WRANGLER_REMOTE" if authenticated_acquisition is not None else "LOCAL_ARTIFACT"
    )
    trusted_full_inventory = bool(authenticated_acquisition is not None and not args.table)
    sync_kind = (
        "INCREMENTAL"
        if trusted_full_inventory and args.incremental
        else "FULL"
        if trusted_full_inventory
        else "UNTRUSTED"
    )
    needs_change_feed = bool(
        args.incremental and any(table in _CHANGE_FEED_TABLES for table in tables)
    )
    needs_bootstrap_cursor = not args.incremental and not args.table
    source_max: int | None = None
    source_content_digest: str | None = None
    local_content_digest: str | None = None
    table_counts: dict[str, int] | None = None
    prior_audit_digest: str | None = None
    noop_trusted = False
    if needs_change_feed or needs_bootstrap_cursor:
        try:
            source_max = _source_change_seq(source)
            if trusted_full_inventory and args.incremental:
                base_row, base_envelope = _require_trusted_incremental_base(store)
                prior_cursor = base_envelope["applied_change_seq"]
                prior_audit_digest = str(base_row["audit_digest"])
            elif trusted_full_inventory:
                prior_cursor = _last_change_seq(store)
            else:
                prior_cursor = _last_change_seq(store)
            if not isinstance(prior_cursor, int) or source_max < prior_cursor:
                raise ValueError(
                    "D1 export is older than the local applied cursor; "
                    "refusing stale apply"
                )
            if trusted_full_inventory:
                current_trusted = _latest_trusted_sync_audit(store)
                if current_trusted is not None:
                    _current_row, current_envelope = current_trusted
                    current_cursor = current_envelope["applied_change_seq"]
                    if (
                        isinstance(current_cursor, int)
                        and source_max == current_cursor
                    ):
                        source_identity, source_schema, _source_counts = (
                            _private_export.governed_content_identity(
                                source, tuple(tables)
                            )
                        )
                        if (
                            source_identity
                            == current_envelope["source_content_digest"]
                            and source_schema
                            == current_envelope["source_schema_digest"]
                        ):
                            noop_trusted = True
                        else:
                            raise ValueError(
                                "D1 export cursor matches the current mirror "
                                "with a different content digest"
                            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"change_feed: {exc}")
    if noop_trusted and not failures:
        return total_seen, total_registered, total_skipped, failures
    signed_digest_collision = store._conn.execute(  # noqa: SLF001
        "SELECT 1 FROM main.local_d1_export_sync_runs "
        "WHERE export_digest=? AND signed_evidence_json IS NOT NULL",
        (export_digest,),
    ).fetchone()
    audit_export_digest = export_digest
    if signed_digest_collision is not None:
        audit_export_digest = "sha256:" + hashlib.sha256(
            f"untrusted-attempt:{export_digest}".encode("utf-8")
        ).hexdigest()
    _mark_untrusted_export_sync(
        store,
        export_digest=audit_export_digest,
        artifact_format=artifact_format,
        source_mode=source_mode,
        sync_kind=sync_kind,
        source_change_seq=source_max,
        status="APPLYING",
    )
    if failures:
        _mark_untrusted_export_sync(
            store,
            export_digest=export_digest,
            artifact_format=artifact_format,
            source_mode=source_mode,
            sync_kind=sync_kind,
            source_change_seq=source_max,
            status="FAILED",
            error="; ".join(failures),
        )
        return total_seen, total_registered, total_skipped, failures

    if trusted_full_inventory and not args.incremental:
        try:
            _reset_governed_local_tables(store, tables)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"bootstrap_reset: {exc}")
    if failures:
        _mark_untrusted_export_sync(
            store,
            export_digest=export_digest,
            artifact_format=artifact_format,
            source_mode=source_mode,
            sync_kind=sync_kind,
            source_change_seq=source_max,
            status="FAILED",
            error="; ".join(failures),
        )
        return total_seen, total_registered, total_skipped, failures

    change_feed_done = False
    for table in tables:
        if args.incremental and table in _CHANGE_FEED_TABLES:
            if change_feed_done:
                continue
            try:
                pages, seen, registered, change_seq = _sync_export_changes(
                    store,
                    source,
                    page_limit=args.page_limit,
                    max_pages=args.max_pages,
                    source_max_seq=source_max,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"change_feed: {exc}")
                print(f"[sync] change_feed FAILED: {exc}", file=sys.stderr)
            else:
                total_seen += seen
                total_registered += registered
                print(
                    f"[sync] change_feed: pages={pages} seen={seen} "
                    f"registered={registered} change_seq={change_seq}"
                )
            change_feed_done = True
            continue
        if args.incremental:
            since = None if table in _NO_AVAILABLE_AT_TABLES else (
                args.since or _derive_since(store, table)
            )
        else:
            since = None
        try:
            pages, seen, registered, skipped, effective_since = _sync_export_table(
                store,
                source,
                table,
                page_limit=args.page_limit,
                since=since,
                max_pages=args.max_pages,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{table}: {exc}")
            print(f"[sync] {table} FAILED: {exc}", file=sys.stderr)
            continue
        total_seen += seen
        total_registered += registered
        total_skipped += skipped
        print(
            f"[sync] {table}: pages={pages} seen={seen} "
            f"registered={registered} skipped={skipped}"
            + (f" since={effective_since}" if effective_since else "")
        )
    if not failures and needs_bootstrap_cursor:
        assert source_max is not None
        try:
            _record_change_seq(store, source_max)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"change_feed: {exc}")
    if not failures and trusted_full_inventory:
        try:
            (
                source_content_digest,
                local_content_digest,
                table_counts,
            ) = _verify_source_local_parity(store, source, tables)
            authenticated_export = authenticated_acquisition.authenticate_local(
                store._conn,  # noqa: SLF001
                tuple(tables),
                sync_kind=sync_kind,
                prior_audit_digest=prior_audit_digest,
            )
            _mark_authenticated_export_complete(store, authenticated_export)
            if audit_export_digest != export_digest:
                store._conn.execute(  # noqa: SLF001
                    "DELETE FROM main.local_d1_export_sync_runs "
                    "WHERE export_digest=? AND signed_evidence_json IS NULL",
                    (audit_export_digest,),
                )
                store._conn.commit()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            failures.append(f"source_local_reconciliation: {exc}")
    if failures or not trusted_full_inventory:
        _mark_untrusted_export_sync(
            store,
            export_digest=audit_export_digest,
            artifact_format=artifact_format,
            source_mode=source_mode,
            sync_kind=sync_kind,
            source_change_seq=source_max,
            source_content_digest=source_content_digest,
            local_content_digest=local_content_digest,
            table_counts=table_counts,
            status="FAILED" if failures else "COMPLETE",
            error="; ".join(failures) if failures else None,
        )
    return total_seen, total_registered, total_skipped, failures


def _run_http_sync(
    store: SqliteStore,
    tables: list[str],
    args,
    *,
    base: str,
    token: str,
) -> tuple[int, int, int, list[str]]:
    """Run the legacy authenticated Worker export during client migration."""
    total_seen = total_registered = total_skipped = 0
    failures: list[str] = []
    try:
        client = _new_http_client()
    except Exception as exc:  # noqa: BLE001
        return 0, 0, 0, [f"http_client: {exc}"]
    try:
        change_feed_done = False
        for table in tables:
            if args.incremental and table in _CHANGE_FEED_TABLES:
                if change_feed_done:
                    continue
                try:
                    pages, seen, registered, change_seq = _sync_changes(
                        store,
                        client,
                        base,
                        token,
                        page_limit=args.page_limit,
                        max_pages=args.max_pages,
                        legacy_since=args.since or _derive_since(store, table),
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"change_feed: {exc}")
                    print(f"[sync] change_feed FAILED: {exc}", file=sys.stderr)
                else:
                    total_seen += seen
                    total_registered += registered
                    print(
                        f"[sync] change_feed: pages={pages} seen={seen} "
                        f"registered={registered} change_seq={change_seq}"
                    )
                change_feed_done = True
                continue
            if args.incremental:
                since = None if table in _NO_AVAILABLE_AT_TABLES else (
                    args.since or _derive_since(store, table)
                )
                if since:
                    print(
                        f"[sync] {table}: incremental since={since}",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"[sync] {table}: incremental since=<none> (full pull)",
                        file=sys.stderr,
                    )
            else:
                since = None
            try:
                pages, seen, registered, skipped, effective_since = _sync_table(
                    store,
                    client,
                    base,
                    token,
                    table,
                    page_limit=args.page_limit,
                    since=since,
                    max_pages=args.max_pages,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{table}: {exc}")
                print(f"[sync] {table} FAILED: {exc}", file=sys.stderr)
                continue
            total_seen += seen
            total_registered += registered
            total_skipped += skipped
            print(
                f"[sync] {table}: pages={pages} seen={seen} "
                f"registered={registered} skipped={skipped}"
                + (f" since={effective_since}" if effective_since else "")
            )
    finally:
        try:
            client.close()
        except Exception:  # pragma: no cover
            pass
    return total_seen, total_registered, total_skipped, failures


def _finalize_sync_policy(
    store: SqliteStore,
    args,
    failures: list[str],
    *,
    source_mode: str,
) -> None:
    """Keep production READY profile-bound and closed after every apply path."""
    if failures:
        fail_snapshot_sync(store._conn, "; ".join(failures))  # noqa: SLF001
        return
    if args.table:
        fail_snapshot_sync(
            store._conn,  # noqa: SLF001
            "targeted sync completed, but a full required-dataset sync "
            "is required before paper research",
        )
        return
    if args.pilot_ready_evidence:
        if source_mode != "WRANGLER_REMOTE":
            message = (
                "snapshot: only the pinned authenticated production D1 path "
                "can authorize production READY; use --wrangler-remote"
            )
            failures.append(message)
            fail_snapshot_sync(store._conn, message)  # noqa: SLF001
            print(f"[sync] snapshot FAILED: {message}", file=sys.stderr)
            return
        try:
            from research.ready_manifest import (
                publish_exact_four_pilot_ready_snapshot,
            )

            # Preserve the exact signed bytes for the Ops trust boundary.  The
            # verifier performs the one strict JSON decode, so duplicate keys
            # and non-finite values cannot be collapsed by this CLI first.
            signed_document = Path(args.pilot_ready_evidence).read_bytes()
            snapshot_dir = (
                Path(args.snapshot_dir)
                if args.snapshot_dir
                else Path(args.db).resolve().parent / "snapshots"
            )
            ready = publish_exact_four_pilot_ready_snapshot(
                args.db,
                snapshot_dir,
                signed_projection_document=signed_document,
            )
            print(f"[sync] READY published snapshot_id={ready.snapshot_id}")
        except Exception as exc:  # noqa: BLE001 - CLI fail-closed boundary
            message = f"snapshot: signed pilot READY publication failed: {exc}"
            failures.append(message)
            fail_snapshot_sync(store._conn, message)  # noqa: SLF001
            print(f"[sync] snapshot FAILED: {message}", file=sys.stderr)
        return
    fail_snapshot_sync(  # noqa: SLF001
        store._conn,
        "sync applied; exact-four profile/plan/closure READY evidence "
        "was not supplied",
    )
    print(
        "[sync] data applied; READY not published (missing "
        "--pilot-ready-evidence)"
    )


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if not 1 <= args.page_limit <= 1000:
        print("[sync] --page-limit must be between 1 and 1000", file=sys.stderr)
        return 2
    if args.max_pages < 1:
        print("[sync] --max-pages must be at least 1", file=sys.stderr)
        return 2
    if args.since and not args.incremental:
        print("[sync] --since requires --incremental", file=sys.stderr)
        return 2
    if not args.d1_export and not args.wrangler_remote and not args.url:
        # Production default: authenticated private D1 acquisition. The legacy
        # Worker transport is entered only by an explicit --url argument.
        args.wrangler_remote = True
    private_mode = bool(args.d1_export or args.wrangler_remote)
    url = args.url
    token = os.environ.get("DATA_EXPORT_TOKEN")

    tables = args.table or list(DEFAULT_TABLES)
    try:
        tables = [_validate_sync_table(table) for table in tables]
    except ValueError as exc:
        print(f"[sync] invalid table selection: {exc}", file=sys.stderr)
        return 2

    temporary: tempfile.TemporaryDirectory[str] | None = None
    source_conn: sqlite3.Connection | None = None
    export_digest = ""
    artifact_format = ""
    source_mode = "WORKER_HTTP"
    authenticated_acquisition = None
    if private_mode:
        temporary = tempfile.TemporaryDirectory(prefix="quant-d1-sync-")
        temporary_path = Path(temporary.name)
        try:
            if args.wrangler_remote:
                authenticated_acquisition = (
                    _private_export.acquire_pinned_wrangler_export(temporary_path)
                )
                export_digest = authenticated_acquisition.export_digest
                artifact_size = authenticated_acquisition.artifact_size
                artifact_format = authenticated_acquisition.artifact_format
                source_conn = authenticated_acquisition.open_source()
                source_mode = "WRANGLER_REMOTE"
                print("[sync] acquired private D1 export via authenticated Wrangler")
            else:
                raw_artifact = Path(args.d1_export)
                source_mode = "LOCAL_ARTIFACT"
                materialized = temporary_path / "export.sqlite"
                export_digest, artifact_size, artifact_format = _materialize_d1_export(
                    raw_artifact,
                    materialized,
                )
                source_conn = _open_export_sqlite(materialized)
            print(
                f"[sync] private export verified format={artifact_format} "
                f"bytes={artifact_size} digest={export_digest}"
            )
        except Exception as exc:  # noqa: BLE001 - operator CLI boundary
            print(f"[sync] private export preparation FAILED: {exc}", file=sys.stderr)
            temporary.cleanup()
            return 1

    store = SqliteStore(Path(args.db))
    begin_snapshot_sync(
        store._conn,  # noqa: SLF001
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    total_seen = total_registered = total_skipped = 0
    failures: list[str] = []
    try:
        if source_conn is not None:
            (
                total_seen,
                total_registered,
                total_skipped,
                failures,
            ) = _run_private_export_sync(
                store,
                source_conn,
                tables,
                args,
                export_digest=export_digest,
                artifact_format=artifact_format,
                authenticated_acquisition=authenticated_acquisition,
            )
        else:
            (
                total_seen,
                total_registered,
                total_skipped,
                failures,
            ) = _run_http_sync(
                store,
                tables,
                args,
                base=(url or "").rstrip("/"),
                token=token or "",
            )
        _finalize_sync_policy(store, args, failures, source_mode=source_mode)
    finally:
        store.close()
        if source_conn is not None:
            source_conn.close()
        if temporary is not None:
            temporary.cleanup()

    print(
        f"[sync] done db={args.db} seen={total_seen} "
        f"registered={total_registered} skipped={total_skipped} "
        f"failures={len(failures)}"
    )
    exit_code = 1 if failures else 0
    if exit_code == 0 and getattr(args, "publish_ops", False):
        projection_exit = _maybe_publish_ops_projection(
            args.db,
            apply_remote=bool(getattr(args, "apply_remote_ops", False)),
        )
        if projection_exit != 0:
            print(
                f"[sync] ops projection publication FAILED exit={projection_exit}",
                file=sys.stderr,
            )
            return projection_exit
    return exit_code


def _maybe_publish_ops_projection(db_path, *, apply_remote: bool = False) -> int:
    import subprocess

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "publish_ops_projection.py"),
        "--db",
        str(db_path),
    ]
    if apply_remote:
        cmd.append("--apply-remote")
    print("[sync] publishing ops projection")
    completed = subprocess.run(cmd, check=False)
    return int(completed.returncode)


def _authenticated_export_cursor_chain_from_conn(
    conn: sqlite3.Connection,
) -> tuple[int | None, int | None]:
    """Validate the trusted cursor/content chain in one caller-owned read view."""
    identity = _authenticated_applied_mirror_identity_from_conn(conn)
    source = identity["source_change_seq"]
    assert isinstance(source, int)  # validated by identity derivation
    return source, source


def _authenticated_applied_mirror_identity_from_conn(
    conn: sqlite3.Connection,
) -> dict[str, object]:
    """Recompute the complete signed-sync identity in the active read view."""
    row = _latest_export_sync_row(conn)
    if row is None:
        raise ValueError("applied mirror has no current signed D1 sync audit")
    envelope = _verified_sync_envelope_from_row(
        conn, row, recompute_local=True
    )
    source = envelope["source_change_seq"]
    applied = envelope["applied_change_seq"]
    if (
        isinstance(source, bool)
        or not isinstance(source, int)
        or source <= 0
        or isinstance(applied, bool)
        or not isinstance(applied, int)
        or applied != source
    ):
        raise ValueError(
            "authenticated applied mirror cursor chain is null or mismatched"
        )
    counts = envelope["table_counts"]
    if not isinstance(counts, Mapping):
        raise ValueError("authenticated applied mirror inventory is incomplete")
    owned_counts = dict(counts)
    return {
        "audit_digest": row.get("audit_digest"),
        "issuer_key_id": row.get("issuer_key_id"),
        "export_digest": envelope["export_digest"],
        "source_change_seq": source,
        "applied_change_seq": applied,
        "source_content_digest": envelope["source_content_digest"],
        "local_content_digest": envelope["local_content_digest"],
        "source_schema_digest": envelope["source_schema_digest"],
        "schema_digest": envelope["schema_digest"],
        "table_counts": owned_counts,
    }


_APPLIED_MIRROR_IDENTITY_FIELDS = frozenset(
    {
        "audit_digest",
        "issuer_key_id",
        "export_digest",
        "source_change_seq",
        "applied_change_seq",
        "source_content_digest",
        "local_content_digest",
        "source_schema_digest",
        "schema_digest",
        "table_counts",
    }
)


def _canonical_applied_mirror_identity_json(
    identity: dict[str, object],
) -> str:
    """Validate and freeze the sync/full-source identity held by one handle."""
    if type(identity) is not dict or set(identity) != _APPLIED_MIRROR_IDENTITY_FIELDS:
        raise ValueError("authenticated applied mirror identity is not closed")
    source = identity.get("source_change_seq")
    applied = identity.get("applied_change_seq")
    if (
        type(source) is not int
        or source <= 0
        or type(applied) is not int
        or applied != source
    ):
        raise ValueError(
            "authenticated applied mirror cursor chain is null or mismatched"
        )
    digest_fields = (
        "audit_digest",
        "export_digest",
        "source_content_digest",
        "local_content_digest",
        "source_schema_digest",
        "schema_digest",
    )
    for field in digest_fields:
        value = identity.get(field)
        if (
            type(value) is not str
            or len(value) != 71
            or not value.startswith("sha256:")
        ):
            raise ValueError(
                f"authenticated applied mirror {field} is invalid"
            )
        try:
            int(value.removeprefix("sha256:"), 16)
        except ValueError as exc:
            raise ValueError(
                f"authenticated applied mirror {field} is invalid"
            ) from exc
    issuer = identity.get("issuer_key_id")
    if type(issuer) is not str or not issuer:
        raise ValueError("authenticated applied mirror issuer is invalid")
    if identity["source_content_digest"] != identity["local_content_digest"]:
        raise ValueError("authenticated applied mirror source/local content differs")
    counts = identity.get("table_counts")
    if type(counts) is not dict or set(counts) != set(DEFAULT_TABLES):
        raise ValueError("authenticated applied mirror inventory is incomplete")
    if any(
        type(table) is not str
        or type(count) is not int
        or count < 0
        for table, count in dict.items(counts)
    ):
        raise ValueError("authenticated applied mirror table counts are invalid")
    owned = dict.copy(identity)
    owned["table_counts"] = dict.copy(counts)
    return json.dumps(
        owned,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _deep_immutable_json(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType(
            {key: _deep_immutable_json(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_immutable_json(item) for item in value)
    return value


def _authenticated_export_cursor_chain(
    db_path: str | Path,
) -> tuple[int | None, int | None]:
    """Return source/export cursors only for a completed direct Wrangler apply.

    A caller-supplied local artifact never becomes signed source-generation
    evidence. The applied cursor must equal the immutable export's measured
    source maximum before the projection publisher receives either value.
    """
    path = Path(db_path).resolve()
    if not path.is_file():
        return None, None
    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.execute("BEGIN")
        return _authenticated_export_cursor_chain_from_conn(conn)
    except (ValueError, TypeError, RuntimeError, json.JSONDecodeError, sqlite3.Error):
        return None, None
    finally:
        conn.close()


def _build_applied_mirror_authority():
    """Mint one-shot handles over one verified, open SQLite read snapshot."""
    live_mirrors = WeakSet()

    class _AuthenticatedAppliedMirror:
        __slots__ = (
            "_db_path",
            "_path_identity",
            "_conn",
            "_identity_json",
            "_consumed",
            "__weakref__",
        )

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError(
                "authenticated applied mirror has no public constructor"
            )

        def _consume_for_projection(
            self,
            consumer: Callable[
                [sqlite3.Connection, Mapping[str, object]], _MirrorResult
            ],
        ) -> _MirrorResult:
            if self not in live_mirrors or self._consumed:
                raise RuntimeError("authenticated applied mirror was already consumed")
            self._consumed = True
            live_mirrors.discard(self)
            try:
                try:
                    current = self._db_path.stat()
                except OSError as exc:
                    raise RuntimeError(
                        "authenticated applied mirror path disappeared"
                    ) from exc
                if (current.st_dev, current.st_ino) != self._path_identity:
                    raise RuntimeError(
                        "authenticated applied mirror path was replaced"
                    )
                observed = _authenticated_applied_mirror_identity_from_conn(
                    self._conn
                )
                observed_json = _canonical_applied_mirror_identity_json(observed)
                if observed_json != self._identity_json:
                    raise RuntimeError(
                        "authenticated applied mirror identity changed"
                    )
                restored = json.loads(self._identity_json)
                immutable_identity = _deep_immutable_json(restored)
                assert isinstance(immutable_identity, Mapping)
                return consumer(self._conn, immutable_identity)
            finally:
                try:
                    self._conn.rollback()
                finally:
                    self._conn.close()

    def _consume_authenticated_applied_mirror(
        handle: object,
        consumer: Callable[
            [sqlite3.Connection, Mapping[str, object]], _MirrorResult
        ],
    ) -> _MirrorResult:
        if type(handle) is not _AuthenticatedAppliedMirror:
            raise RuntimeError(
                "Ops projection requires an authenticated applied mirror handle"
            )
        return handle._consume_for_projection(consumer)

    def open_authenticated_applied_mirror(
        db_path: str | Path,
    ) -> _AuthenticatedAppliedMirror:
        path = Path(db_path).resolve()
        if not path.is_file():
            raise ValueError("applied mirror is not an authenticated current D1 export")
        stat = path.stat()
        uri = f"file:{quote(str(path), safe='/')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.execute("BEGIN")
            identity = _authenticated_applied_mirror_identity_from_conn(conn)
            identity_json = _canonical_applied_mirror_identity_json(identity)
        except (
            ValueError,
            TypeError,
            RuntimeError,
            json.JSONDecodeError,
            sqlite3.Error,
        ) as exc:
            conn.close()
            raise ValueError(
                "applied mirror is not an authenticated current D1 export"
            ) from exc
        except Exception:
            conn.close()
            raise
        handle = object.__new__(_AuthenticatedAppliedMirror)
        handle._db_path = path
        handle._path_identity = (stat.st_dev, stat.st_ino)
        handle._conn = conn
        handle._identity_json = identity_json
        handle._consumed = False
        live_mirrors.add(handle)
        return handle

    return (
        _AuthenticatedAppliedMirror,
        open_authenticated_applied_mirror,
        _consume_authenticated_applied_mirror,
    )


(
    _AuthenticatedAppliedMirror,
    open_authenticated_applied_mirror,
    _consume_authenticated_applied_mirror,
) = _build_applied_mirror_authority()
del _build_applied_mirror_authority


if __name__ == "__main__":
    sys.exit(main())
