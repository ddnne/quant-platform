#!/usr/bin/env python3
"""Phase 3.5 S6 — sync Cloudflare D1 → local SQLite for `pit.get_*`.

Pulls the structured fact tables from the ingestion-premium Worker
(`/v1/export/d1`) and upserts them into a local SQLite DB shaped exactly like
`storage/schema.py` (so `pit.get_*` reads work without code changes).

Offline-safety: with no `--url` and no proxy config, the script exits with
code 2 (nothing fetched) and never touches the network.

Incremental mode
----------------
The D1 export endpoint only paginates by `rowid`; it has **no server-side
``ingested_at`` filter**. ``--incremental`` therefore derives a per-table
``since`` from the local DB's ``MAX(ingested_at)`` and skips rows whose
``ingested_at`` is at or before that watermark *after* page fetch (documented
limitation — see ``docs/phase35_storage_scale.md``). An explicit ``--since``
ISO timestamp overrides the derived value. A run that produces zero new rows
still walks every page; for tables that grow without bound the operational
answer is the planned parquet/R2 timeseries path, not this script.

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
      --token "$INGESTION_PROXY_TOKEN" \\
      --db data/structured/ingestion.sqlite
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlencode

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from ingestion.common.secrets import resolve_proxy_config  # noqa: E402
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
)
DEFAULT_PAGE_LIMIT = 500


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Sync CF D1 → local SQLite (PIT)")
    p.add_argument(
        "--url",
        default=os.environ.get("INGESTION_PREMIUM_URL"),
        help="Base URL of the ingestion-premium worker",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("INGESTION_PROXY_TOKEN"),
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
            "Skip rows already mirrored locally. Derives a per-table since="
            "MAX(ingested_at) from the local DB and applies it client-side "
            "after page fetch (the export API has no server-side filter)."
        ),
    )
    p.add_argument(
        "--since",
        default=None,
        help=(
            "ISO timestamp override for --incremental filtering. Applies to "
            "every table; ignored without --incremental."
        ),
    )
    return p


def _resolve_endpoint(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """Pick (url, token) from args first, else proxy config files."""
    if args.url:
        return args.url, args.token
    if args.no_proxy_config:
        return None, None
    cfg = resolve_proxy_config()
    if cfg is None:
        return None, None
    return cfg.url, cfg.token


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


def _sync_one(
    store: SqliteStore, table: str, rows: list[dict]
) -> tuple[int, int]:
    """Upsert rows into local table. Returns (seen, registered)."""
    if not rows:
        return 0, 0
    # Re-key JSON-stringified payload columns if present (the D1 export
    # round-trips them as strings; the writer expects strings too).
    cleaned = []
    for r in rows:
        row = {k: v for k, v in r.items() if v is not None}
        if not row.get("available_at"):
            # PIT hard gate — skip rows that would be rejected anyway.
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
) -> tuple[int, int, int, int, str | None]:
    """Pull one table end-to-end.

    Returns ``(pages, seen, registered, skipped, effective_since)``. The
    ``effective_since`` echoed back so callers can log the derived watermark
    alongside the explicit one.
    """
    cursor: str | int | None = None
    pages = seen = registered = skipped = 0
    while True:
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
        cursor = next_cursor
    return pages, seen, registered, skipped, since


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if not 1 <= args.page_limit <= 1000:
        print("[sync] --page-limit must be between 1 and 1000", file=sys.stderr)
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
    base = url.rstrip("/")
    total_seen = total_registered = total_skipped = 0
    failures: list[str] = []

    client = _new_http_client()
    try:
        for t in tables:
            if args.incremental:
                since = args.since or _derive_since(store, t)
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
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
