#!/usr/bin/env python3
"""Phase 3.5 S6 — sync Cloudflare D1 → local SQLite for `pit.get_*`.

Pulls structured fact tables from the ingestion-premium Worker (`/v1/export/d1`)
and upserts them into local SQLite matching `storage/schema.py`.

No `--url` / ``INGESTION_PREMIUM_URL`` → exit 2, no network.
``--incremental`` applies ``change_seq > last_applied_change_seq`` after each
durable page. Full table export is bootstrap.

Sync never mints READY from caller assertions. It can invoke the exact-four
publisher only with an Ed25519-verified Ops Projection envelope; otherwise it
finishes the apply and leaves snapshot publication closed.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

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

from paper_runtime import (  # noqa: E402
    begin_snapshot_sync,
    fail_snapshot_sync,
)
from storage.sqlite_store import SqliteStore  # noqa: E402

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
    p.add_argument(
        "--url",
        default=os.environ.get("INGESTION_PREMIUM_URL"),
        help="Base URL of the ingestion-premium worker",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("DATA_EXPORT_TOKEN"),
        help="X-Ingestion-Token for /v1/export/d1",
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
        "SELECT last_applied_change_seq FROM sync_change_state "
        "WHERE feed = 'jquants_records'"
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _record_change_seq(store: SqliteStore, value: int) -> None:
    store._conn.execute(  # noqa: SLF001
        """
        INSERT INTO sync_change_state (feed, last_applied_change_seq, updated_at)
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
    url, token = args.url, args.token
    if not url:
        print(
            "[sync] no worker URL (pass --url or set INGESTION_PREMIUM_URL). "
            "Nothing synced.",
            file=sys.stderr,
        )
        return 2

    tables = args.table or list(DEFAULT_TABLES)
    store = SqliteStore(Path(args.db))
    begin_snapshot_sync(
        store._conn,  # noqa: SLF001
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    base = url.rstrip("/")
    total_seen = total_registered = total_skipped = 0
    failures: list[str] = []

    client = _new_http_client()
    try:
        change_feed_done = False
        for t in tables:
            if args.incremental and t in _CHANGE_FEED_TABLES:
                if change_feed_done:
                    continue
                try:
                    pages, seen, registered, change_seq = _sync_changes(
                        store,
                        client,
                        base,
                        token or "",
                        page_limit=args.page_limit,
                        max_pages=args.max_pages,
                        legacy_since=args.since or _derive_since(store, t),
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
                since = None if t in _NO_AVAILABLE_AT_TABLES else (
                    args.since or _derive_since(store, t)
                )
                if since:
                    print(f"[sync] {t}: incremental since={since}", file=sys.stderr)
                else:
                    print(
                        f"[sync] {t}: incremental since=<none> (full pull)",
                        file=sys.stderr,
                    )
            else:
                since = None
            try:
                pages, seen, registered, skipped, eff_since = _sync_table(
                    store,
                    client,
                    base,
                    token or "",
                    t,
                    page_limit=args.page_limit,
                    since=since,
                    max_pages=args.max_pages,
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{t}: {exc}")
                print(f"[sync] {t} FAILED: {exc}", file=sys.stderr)
                continue
            total_seen += seen
            total_registered += registered
            total_skipped += skipped
            print(
                f"[sync] {t}: pages={pages} seen={seen} "
                f"registered={registered} skipped={skipped}"
                + (f" since={eff_since}" if eff_since else "")
            )
        if failures:
            fail_snapshot_sync(store._conn, "; ".join(failures))  # noqa: SLF001
        elif args.table:
            fail_snapshot_sync(
                store._conn,  # noqa: SLF001
                "targeted sync completed, but a full required-dataset sync "
                "is required before paper research",
            )
        elif args.pilot_ready_evidence:
            try:
                from ops.projection_signing import OpsProjectionPublicKeyRegistry
                from research.ready_manifest import (
                    publish_exact_four_pilot_ready_snapshot,
                )

                signed_document = json.loads(
                    Path(args.pilot_ready_evidence).read_text(encoding="utf-8")
                )
                snapshot_dir = (
                    Path(args.snapshot_dir)
                    if args.snapshot_dir
                    else Path(args.db).resolve().parent / "snapshots"
                )
                ready = publish_exact_four_pilot_ready_snapshot(
                    args.db,
                    snapshot_dir,
                    signed_projection_document=signed_document,
                    projection_verifier=OpsProjectionPublicKeyRegistry.load(),
                )
                print(f"[sync] READY published snapshot_id={ready.snapshot_id}")
            except Exception as exc:  # noqa: BLE001 - CLI fail-closed boundary
                message = f"snapshot: signed pilot READY publication failed: {exc}"
                failures.append(message)
                fail_snapshot_sync(store._conn, message)  # noqa: SLF001
                print(f"[sync] snapshot FAILED: {message}", file=sys.stderr)
        else:
            fail_snapshot_sync(  # noqa: SLF001
                store._conn,
                "sync applied; exact-four profile/plan/closure READY evidence "
                "was not supplied",
            )
            print(
                "[sync] data applied; READY not published (missing "
                "--pilot-ready-evidence)"
            )
    finally:
        try:
            client.close()
        except Exception:  # pragma: no cover
            pass
        store.close()

    print(
        f"[sync] done db={args.db} seen={total_seen} "
        f"registered={total_registered} skipped={total_skipped} "
        f"failures={len(failures)}"
    )
    exit_code = 1 if failures else 0
    if exit_code == 0 and getattr(args, "publish_ops", False):
        _maybe_publish_ops_projection(
            args.db,
            apply_remote=bool(getattr(args, "apply_remote_ops", False)),
        )
    return exit_code


def _maybe_publish_ops_projection(db_path, *, apply_remote: bool = False) -> None:
    import subprocess

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "publish_ops_projection.py"),
        "--db",
        str(db_path),
    ]
    if apply_remote:
        cmd.append("--apply-remote")
    print(f"[sync] publishing ops projection: {' '.join(cmd)}")
    subprocess.run(cmd, check=False)


if __name__ == "__main__":
    sys.exit(main())
