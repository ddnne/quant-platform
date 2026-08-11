#!/usr/bin/env python3
"""Phase 3.5 S6 — sync Cloudflare D1 → local SQLite for `pit.get_*`.

Pulls the structured fact tables from the ingestion-premium Worker
(`/v1/export/d1`) and upserts them into a local SQLite DB shaped exactly like
`storage/schema.py` (so `pit.get_*` reads work without code changes).

Offline-safety: with no `--url` and no proxy config, the script exits with
code 2 (nothing fetched) and never touches the network.

Incremental mode
----------------
``--incremental`` consumes the append-only Worker change feed with
``change_seq > last_applied_change_seq``. The sequence watermark advances
only after a whole page has been durably applied. Full table export remains
the bootstrap path; client-side timestamp filtering is compatibility-only for
pre-Phase-6 mocked responses and is not the production correctness mechanism.

Examples
--------
  # All tables, default proxy config (~/.config/quant-platform/* or env):
  python3 scripts/sync_d1_to_sqlite.py \\
      --db data/structured/ingestion.sqlite

  # One table:
  python3 scripts/sync_d1_to_sqlite.py --table jquants_records \\
      --db data/structured/ingestion.sqlite

  # Incremental pull (skips rows already in the local DB by ingested_at):
  python3 scripts/sync_d1_to_sqlite.py --incremental \\
      --db data/structured/ingestion.sqlite

  # Explicit URL+token (do not commit these):
  python3 scripts/sync_d1_to_sqlite.py \\
      --url https://quant-platform-ingestion-premium.<acct>.workers.dev \\
      --token "$DATA_EXPORT_TOKEN" \\
      --db data/structured/ingestion.sqlite
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from ingestion.common.secrets import resolve_proxy_config  # noqa: E402
from data_contracts import all_coverage_contracts  # noqa: E402
from paper_runtime import (  # noqa: E402
    begin_snapshot_sync,
    fail_snapshot_sync,
    publish_ready_snapshot,
)
from storage.sqlite_store import SqliteStore  # noqa: E402

# Tables we sync (mirror schema.py). Order matters for FK-friendly ingestion
# but SQLite defers FK checks per-row only when configured; we use plain
# upserts keyed on natural keys so order is informational.
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
GOVERNED_READY_DATASETS = tuple(
    contract.dataset_id
    for contract in all_coverage_contracts()
    if contract.governance_tier == "governed"
)


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
        help=(
            "READY artifact directory (default: <db-parent>/snapshots). "
            "Staging DB is never research-readable."
        ),
    )
    p.add_argument(
        "--page-limit",
        type=int,
        default=DEFAULT_PAGE_LIMIT,
        help="Rows requested per D1 export page (1-1000, default: 500).",
    )
    p.add_argument(
        "--no-proxy-config",
        dest="no_proxy_config",
        action="store_true",
        help="Ignore ~/.config/quant-platform/ proxy config.",
    )
    p.add_argument(
        "--incremental",
        action="store_true",
        help=(
            "Apply only sequenced Worker changes after the locally committed "
            "change_seq watermark."
        ),
    )
    p.add_argument(
        "--since",
        default=None,
        help=(
            "Legacy ISO filter for compatibility with a pre-change-feed "
            "response. Production incremental sync uses change_seq."
        ),
    )
    p.add_argument(
        "--publish-ops",
        action="store_true",
        help=(
            "After a successful sync (exit 0 path), run "
            "scripts/publish_ops_projection.py for the local DB."
        ),
    )
    p.add_argument(
        "--apply-remote-ops",
        action="store_true",
        help=(
            "With --publish-ops, also apply the projection SQL to remote D1 "
            "via wrangler (requires CF auth)."
        ),
    )
    return p


def _resolve_endpoint(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """Pick the data-export URL and its independently scoped token.

    J-Quants proxy credentials are intentionally never reused here.
    """
    if args.url:
        return args.url, args.token
    return None, None


def _new_http_client():
    """Lazy httpx import + factory. Kept tiny so tests can monkeypatch."""
    try:
        import httpx  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("httpx is required for sync (pip install httpx)") from exc
    return httpx.Client(timeout=120.0)


def _http_get_json(client, url: str, token: str) -> dict:
    """Fetch JSON from the worker using a shared client.

    Tests monkeypatch this top-level symbol to stub the network; the real
    transport uses ``client.get`` so connection pooling covers every page.
    """
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
    """Create control-plane tables if the local DB was opened before migrations."""
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


def _sync_control_plane(
    store: SqliteStore, table: str, rows: list[dict]
) -> tuple[int, int]:
    """Insert/replace control-plane rows without PIT available_at gate."""
    if not rows:
        return 0, 0
    conn = store._conn  # noqa: SLF001
    _ensure_control_tables(conn)
    # Drop export cursor column if present.
    cleaned = []
    for r in rows:
        # Preserve nullable evidence fields such as receipt error/expected_items;
        # dropping them could make later rows inherit the first row's shape.
        row = {k: v for k, v in r.items() if k != "__export_cursor"}
        cleaned.append(row)
    if not cleaned:
        return len(rows), 0
    cols = list(cleaned[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(cols)
    # Prefer INSERT OR REPLACE on natural identity when possible.
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
    # Re-key JSON-stringified payload columns if present (the D1 export
    # round-trips them as strings; the writer expects strings too).
    cleaned = []
    for r in rows:
        row = {k: v for k, v in r.items() if v is not None}
        if not row.get("available_at"):
            # PIT hard gate — skip fact rows that would be rejected anyway.
            continue
        cleaned.append(row)
    if not cleaned:
        return len(rows), 0
    n = store.upsert(table, cleaned)
    return len(rows), n


def _derive_since(store: SqliteStore, table: str) -> str | None:
    """Local freshness watermark = MAX(ingested_at) for ``table``.

    Returns None when the table is empty or missing so callers can treat the
    first incremental run as a full pull without special-casing.
    """
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
    """Apply the client-side ``ingested_at > since`` filter.

    Returns (kept_rows, skipped_count). ``since`` is compared as text — every
    ingested_at in our schema is already a JST ISO string, so lexicographic
    comparison matches chronological order for a fixed offset and the
    canonical form produced by ``validate_available_at``.
    """
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
    """Pull one table end-to-end.

    Returns ``(pages, seen, registered, skipped, effective_since)``. The
    ``effective_since`` echoed back so callers can log the derived watermark
    alongside the explicit one.
    """
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


def _apply_change_rows(store: SqliteStore, rows: list[dict]) -> int:
    """Apply one sequenced page while preserving target-table order."""
    registered = 0
    current_table: str | None = None
    current_rows: list[dict] = []

    def flush() -> None:
        nonlocal registered, current_rows
        if current_table is not None and current_rows:
            registered += _sync_one(store, current_table, current_rows)[1]
        current_rows = []

    for source in rows:
        table = str(source.get("table_name", ""))
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
    return registered


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
    """Consume the server-side monotonic change feed.

    Returns ``(pages, seen, registered, last_applied_change_seq)``.
    ``change_seq`` is checked for strict monotonicity on every page and is
    persisted only after all rows in that page are durable.
    """
    after_seq = _last_change_seq(store)
    pages = seen = registered = 0
    visited = {after_seq}
    while True:
        if pages >= max_pages:
            raise ValueError(f"change feed exceeded max_pages={max_pages}")
        query = {
            "after_seq": after_seq,
            "limit": page_limit,
            # Harmless on the real endpoint; keeps old offline fixtures able
            # to return a compatibility page while they migrate.
            "table": "jquants_records",
        }
        endpoint = f"{base}/v1/export/changes?{urlencode(query)}"
        payload = _http_get_json(client, endpoint, token)
        rows = payload.get("rows") or []
        if not isinstance(rows, list):
            raise ValueError("change feed rows must be a list")
        pages += 1

        if payload.get("format") != "jquants-change-feed/v1":
            # Unit-fixture/backward compatibility only. A deployed old Worker
            # returns 404 before reaching this branch, so production never
            # silently falls back from sequence correctness to a full scan.
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
        registered += _apply_change_rows(store, rows)
        _record_change_seq(store, next_seq)
        after_seq = next_seq
        if not payload.get("has_more", False):
            break
        if not rows or after_seq in visited:
            raise ValueError("change feed pagination did not advance")
        visited.add(after_seq)
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
    url, token = _resolve_endpoint(args)
    if not url:
        print(
            "[sync] no worker URL (pass --url, set INGESTION_PREMIUM_URL, "
            "or have a proxy config). Nothing synced.",
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
                # Control/specialized tables are bounded bootstrap exports;
                # mutable generic facts above use the sequenced feed.
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
        else:
            try:
                ready = publish_ready_snapshot(
                    Path(args.db),
                    Path(args.snapshot_dir)
                    if args.snapshot_dir
                    else Path(args.db).resolve().parent / "snapshots",
                    required_datasets=GOVERNED_READY_DATASETS,
                )
                print(
                    f"[sync] committed snapshot={ready.snapshot_id} "
                    f"artifact={ready.db_path}"
                )
            except Exception as exc:  # noqa: BLE001
                message = f"snapshot: {exc}"
                failures.append(message)
                fail_snapshot_sync(store._conn, message)  # noqa: SLF001
                print(f"[sync] snapshot FAILED: {exc}", file=sys.stderr)
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
    """Out-of-band ops projection publish after a successful sync."""
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
