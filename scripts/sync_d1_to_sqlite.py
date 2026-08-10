#!/usr/bin/env python3
"""Phase 3.5 S6 — sync Cloudflare D1 → local SQLite for `pit.get_*`.

Pulls the structured fact tables from the ingestion-premium Worker
(`/v1/export/d1`) and upserts them into a local SQLite DB shaped exactly like
`storage/schema.py` (so `pit.get_*` reads work without code changes).

Offline-safety: with no `--url` and no proxy config, the script exits with
code 2 (nothing fetched) and never touches the network.

Examples
--------
  # All tables, default proxy config (~/.config/quant-platform/* or env):
  python3 scripts/sync_d1_to_sqlite.py \\
      --db data/structured/ingestion.sqlite

  # One table:
  python3 scripts/sync_d1_to_sqlite.py --table jquants_records \\
      --db data/structured/ingestion.sqlite

  # Explicit URL+token (do not commit these):
  python3 scripts/sync_d1_to_sqlite.py \\
      --url https://quant-platform-ingestion-premium.<acct>.workers.dev \\
      --token "$INGESTION_PROXY_TOKEN" \\
      --db data/structured/ingestion.sqlite
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

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
        "--no-proxy-config",
        dest="no_proxy_config",
        action="store_true",
        help="Ignore ~/.config/quant-platform/ proxy config.",
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


def _http_get_json(url: str, token: str) -> dict:
    """Fetch JSON from the worker. Uses httpx lazily."""
    try:
        import httpx  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("httpx is required for sync (pip install httpx)") from exc

    headers = {"X-Ingestion-Token": token} if token else {}
    with httpx.Client(timeout=120.0) as client:
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


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
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
    total_seen = total_registered = 0
    failures: list[str] = []

    try:
        for t in tables:
            endpoint = f"{base}/v1/export/d1?table={t}"
            try:
                payload = _http_get_json(endpoint, token or "")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{t}: {exc}")
                print(f"[sync] {t} FAILED: {exc}", file=sys.stderr)
                continue
            rows = payload.get("rows") or []
            seen, registered = _sync_one(store, t, rows)
            total_seen += seen
            total_registered += registered
            print(f"[sync] {t}: seen={seen} registered={registered}")
    finally:
        store.close()

    print(
        f"[sync] done db={args.db} seen={total_seen} "
        f"registered={total_registered} failures={len(failures)}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
