#!/usr/bin/env python3
"""Run one ingestion pass. Phase 1: local runtime is primary.

Examples
--------
  # Everything, local. J-Quants needs a key (CF proxy by default if a proxy
  # config exists at ~/.config/quant-platform/, else JQUANTS_API_KEY in env);
  # JSDA needs no key:
  python3 scripts/run_ingestion_once.py --source all --runtime local

  # Just JSDA (no key required):
  python3 scripts/run_ingestion_once.py --source jsda --runtime local

  # J-Quants daily bars for one code, a small date window:
  python3 scripts/run_ingestion_once.py --source jquants --code 8697 \\
      --from-date 2025-04-01 --to-date 2025-04-05

  # J-Quants backfill of specific datasets (forwarded to the J-Quants catalog;
  # unrecognized datasets are ignored gracefully in Phase 1):
  python3 scripts/run_ingestion_once.py --source jquants --mode backfill \\
      --dataset listed_info --dataset daily_bars

Secrets
-------
J-Quants auth is resolved via :mod:`ingestion.common.secrets`: the Cloudflare
proxy wins when ``~/.config/quant-platform/ingestion-proxy.json`` exists (the
key then lives only on Cloudflare); otherwise the ``JQUANTS_API_KEY`` env var
is used for a direct call. Secret values are never echoed.

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
     e.g. no J-Quants key/proxy configured)
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

from ingestion.common.http import ProxyHttpClient, make_http_client  # noqa: E402
from ingestion.common.secrets import resolve_jquants  # noqa: E402
from ingestion.common.timeutil import now_jst  # noqa: E402
from ingestion.pipeline import (  # noqa: E402
    decide_exit,
    run_jsda,
    run_jquants,
)
from storage.sqlite_store import SqliteStore  # noqa: E402

_UA = "quant-platform-ingest/0.1 (+personal-research; JST)"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Phase 1 ingestion (one shot)")
    p.add_argument(
        "--source", choices=["jquants", "jsda", "all"], default="all"
    )
    p.add_argument(
        "--runtime",
        choices=["local", "cloudflare"],
        default=os.environ.get("INGESTION_RUNTIME", "local"),
    )
    p.add_argument("--data-dir", default="data")
    p.add_argument("--db", default=None, help="SQLite path (default <data-dir>/structured/ingestion.sqlite)")
    p.add_argument("--code", default=None, help="J-Quants code filter")
    p.add_argument("--from-date", dest="from_date", default=None)
    p.add_argument("--to-date", dest="to_date", default=None)
    p.add_argument(
        "--dataset", dest="dataset", action="append", default=None,
        help="J-Quants dataset name (pass-through to the catalog). Repeatable. "
             "Default: the core Phase 1 endpoints.",
    )
    p.add_argument(
        "--mode", choices=["backfill", "incremental"], default="incremental",
        help="J-Quants fetch mode (pass-through; default incremental).",
    )
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

    store = SqliteStore(db_path)

    # J-Quants auth: CF proxy (key held on Cloudflare) > env JQUANTS_API_KEY > none.
    auth = resolve_jquants()
    if auth.via == "proxy":
        print(
            "[env] J-Quants via Cloudflare proxy "
            "(JQUANTS_API_KEY held on Cloudflare; local key not required)."
        )
        http_jquants = ProxyHttpClient(auth.proxy, user_agent=_UA)
    else:
        http_jquants = make_http_client(runtime, user_agent=_UA)
        if auth.via == "env":
            print("[env] JQUANTS_API_KEY present (value hidden).")
        else:
            print("[env] no J-Quants key or proxy configured — J-Quants will be skipped.")

    # JSDA is always a direct local fetch (public statistics, no key).
    http_jsda = make_http_client(runtime, user_agent=_UA)

    all_reports = []
    try:
        if args.source in ("jquants", "all"):
            reps = run_jquants(
                http=http_jquants, store=store, api_key=auth.effective_api_key,
                data_base=data_base, today=today, runtime=runtime,
                code=args.code, date_from=args.from_date, date_to=args.to_date,
                datasets=args.dataset, mode=args.mode,
            )
            all_reports.extend(reps)
            for r in reps:
                print(r.summary())

        if args.source in ("jsda", "all"):
            reps = run_jsda(
                http=http_jsda, store=store, data_base=data_base, today=today,
                runtime=runtime, target_url=args.jsda_url,
            )
            all_reports.extend(reps)
            for r in reps:
                print(r.summary())
    finally:
        store.close()
        for client in (http_jquants, http_jsda):
            if hasattr(client, "close"):
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass

    print(f"[done] db={db_path}")
    return decide_exit(all_reports)


if __name__ == "__main__":
    sys.exit(main())
