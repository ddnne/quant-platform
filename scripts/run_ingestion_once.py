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

from ingestion.common.http import make_http_client  # noqa: E402
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
        "--jsda-url", dest="jsda_url", default=None,
        help="explicit JSDA file URL (skip index scrape)",
    )
    return p


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
    store = SqliteStore(db_path)
    jquants_key = os.environ.get("JQUANTS_API_KEY", "")
    edinetdb_key = os.environ.get("EDINETDB_API_KEY", "")

    if jquants_key:
        print("[env] JQUANTS_API_KEY present (value hidden).")
    else:
        print("[env] JQUANTS_API_KEY absent — J-Quants will be skipped.")
    if edinetdb_key:
        print("[env] EDINETDB_API_KEY present (value hidden).")
    else:
        print("[env] EDINETDB_API_KEY absent — EDINET DB will be skipped.")

    all_reports = []
    try:
        if args.source in ("jquants", "all"):
            reps = run_jquants(
                http=http, store=store, api_key=jquants_key,
                data_base=data_base, today=today, runtime=runtime,
                code=args.code, date_from=args.from_date, date_to=args.to_date,
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
        if hasattr(http, "close"):
            try:
                http.close()
            except Exception:  # noqa: BLE001
                pass

    print(f"[done] db={db_path}")
    return decide_exit(all_reports)


if __name__ == "__main__":
    sys.exit(main())
