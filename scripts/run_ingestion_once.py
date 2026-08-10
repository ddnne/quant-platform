#!/usr/bin/env python3
"""Run one ingestion pass. Phase 1: local runtime is primary.

Examples
--------
  # Everything, local (needs JQUANTS_API_KEY / EDINETDB_API_KEY in env to do
  # those two; JSDA needs no key):
  python3 scripts/run_ingestion_once.py --source all --runtime local

  # Just JSDA (no key required):
  python3 scripts/run_ingestion_once.py --source jsda --runtime local

  # J-Quants daily bars for one code, a small date window:
  python3 scripts/run_ingestion_once.py --source jquants --code 8697 \\
      --from-date 2025-04-01 --to-date 2025-04-05

Runtime
-------
``--runtime local`` (default; env ``INGESTION_RUNTIME``) fetches for real.
``--runtime cloudflare`` does NOT fetch in Phase 1 — Pattern B keeps fetch on
local and Cloudflare reads storage only. Passing it exits cleanly (code 2).

Exit codes
----------
  0  run completed (at least one source fetched/registered)
  1  at least one source errored (fetch/parse/register failure)
  2  nothing executed (cloudflare runtime, or every source cleanly skipped,
     e.g. all API keys absent)

Secrets are read only from the environment, never echoed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make ``ingestion`` / ``storage`` importable when run as a plain script.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from ingestion.common.http import make_http_client, make_jquants_http  # noqa: E402
from ingestion.common.timeutil import now_jst  # noqa: E402
from ingestion.pipeline import (  # noqa: E402
    decide_exit,
    run_edinetdb,
    run_jsda,
    run_jquants,
)
from storage.sqlite_store import SqliteStore  # noqa: E402

_UA = "quant-platform-ingest/0.1 (+personal-research; JST)"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Phase 1 ingestion (one shot)")
    p.add_argument(
        "--source", choices=["jquants", "edinetdb", "jsda", "all"], default="all"
    )
    p.add_argument(
        "--runtime",
        choices=["local", "cloudflare"],
        default=os.environ.get("INGESTION_RUNTIME", "local"),
    )
    p.add_argument("--data-dir", default="data")
    p.add_argument("--db", default=None, help="SQLite path (default <data-dir>/structured/ingestion.sqlite)")
    p.add_argument("--code", default=None, help="J-Quants / EDINET code filter")
    p.add_argument("--from-date", dest="from_date", default=None)
    p.add_argument("--to-date", dest="to_date", default=None)
    p.add_argument(
        "--dataset", dest="dataset", action="append", default=None,
        help="J-Quants catalog dataset id (e.g. fins_dividend). Repeatable and/or "
             "comma-separated. Selects catalog-driven fetch into jquants_records.",
    )
    p.add_argument(
        "--mode", choices=["incremental", "backfill"], default="incremental",
        help="J-Quants catalog fetch mode (default incremental)",
    )
    p.add_argument(
        "--no-jquants-proxy", dest="no_jquants_proxy", action="store_true",
        help="force direct J-Quants fetch even when a CF proxy is configured",
    )
    p.add_argument(
        "--jsda-url", dest="jsda_url", default=None,
        help="explicit JSDA file URL (skip index scrape)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=int(os.environ.get("INGESTION_WORKERS", "8")),
        help="parallel workers for J-Quants jobs (datasets × date windows). "
             "Rate limit is shared (Premium ~500/min). Default 8.",
    )
    p.add_argument(
        "--chunk-days",
        type=int,
        default=int(os.environ.get("INGESTION_CHUNK_DAYS", "30")),
        help="split long from/to ranges into N-day grids for parallel backfill "
             "(J-Quants). Default 30.",
    )
    return p


def _parse_datasets(raw) -> list[str]:
    """Flatten repeated and comma-separated ``--dataset`` tokens."""
    if not raw:
        return []
    out: list[str] = []
    for tok in raw:
        for part in str(tok).split(","):
            s = part.strip()
            if s:
                out.append(s)
    return out


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    data_base = Path(args.data_dir)
    db_path = Path(args.db) if args.db else data_base / "structured" / "ingestion.sqlite"
    runtime = args.runtime
    today = now_jst()

    if runtime == "cloudflare":
        print(
            "[cloudflare] Fetch is not supported in Phase 1 "
            "(Pattern B: fetch on local, CF reads storage only)."
        )
        return 2

    http = make_http_client(runtime, user_agent=_UA)
    # J-Quants may route through the Cloudflare secret-proxy Worker (key held
    # on the Worker, not local). Auto: use the proxy when configured + local,
    # unless --no-jquants-proxy. Other sources keep using the plain `http`.
    jq_via_proxy = not args.no_jquants_proxy
    jq_http = make_jquants_http(
        runtime, via_cf_proxy=None if jq_via_proxy else False, user_agent=_UA
    )
    store = SqliteStore(db_path)
    jquants_key = os.environ.get("JQUANTS_API_KEY", "")
    edinetdb_key = os.environ.get("EDINETDB_API_KEY", "")

    using_jq_proxy = getattr(jq_http, "name", "") == "cf-jquants-proxy"
    if using_jq_proxy:
        print("[env] J-Quants via Cloudflare proxy (API key held on Worker).")
    elif jquants_key:
        print("[env] JQUANTS_API_KEY present (value hidden).")
    else:
        print("[env] JQUANTS_API_KEY absent — J-Quants will be skipped.")
    if edinetdb_key:
        print("[env] EDINETDB_API_KEY present (value hidden).")
    else:
        print("[env] EDINETDB_API_KEY absent — EDINET DB will be skipped.")

    datasets = _parse_datasets(args.dataset)
    if datasets:
        print(f"[jquants] catalog mode={args.mode} datasets={','.join(datasets)}")

    all_reports = []
    try:
        if args.source in ("jquants", "all"):
            reps = run_jquants(
                http=jq_http, store=store, api_key=jquants_key,
                data_base=data_base, today=today, runtime=runtime,
                code=args.code, date_from=args.from_date, date_to=args.to_date,
                datasets=datasets or None, mode=args.mode,
                max_workers=args.workers, chunk_days=args.chunk_days,
            )
            all_reports.extend(reps)
            for r in reps:
                print(r.summary())

        if args.source in ("edinetdb", "all"):
            reps = run_edinetdb(
                http=http, store=store, api_key=edinetdb_key,
                data_base=data_base, today=today, runtime=runtime,
                financial_codes=[args.code] if args.code else None,
            )
            all_reports.extend(reps)
            for r in reps:
                print(r.summary())

        if args.source in ("jsda", "all"):
            reps = run_jsda(
                http=http, store=store, data_base=data_base, today=today,
                runtime=runtime, target_url=args.jsda_url,
            )
            all_reports.extend(reps)
            for r in reps:
                print(r.summary())
    finally:
        store.close()
        for client in (http, jq_http):
            if hasattr(client, "close"):
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass

    print(f"[done] db={db_path}")
    return decide_exit(all_reports)


if __name__ == "__main__":
    sys.exit(main())
