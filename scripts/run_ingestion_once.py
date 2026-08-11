#!/usr/bin/env python3
"""Run one ingestion pass. Phase 1: local runtime is primary.

Examples
--------
  # Everything, local (J-Quants needs a key — CF proxy by default if a proxy
  # config exists, else JQUANTS_API_KEY in env; JSDA needs no key):
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

Secrets are resolved via :mod:`ingestion.common.secrets` (the Cloudflare
proxy when configured — key held on the Worker — or the ``JQUANTS_API_KEY``
env var for a direct call) and never echoed.
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
        help="J-Quants catalog dataset id (e.g. fins_dividend). Repeatable and/or "
             "comma-separated. Phase 3.5 also accepts the alias 'premiums' "
             "(the 23 Premium core closed-loop ids), 'addons' (minute/trades/"
             "TDnet), or 'all'. Selects catalog-driven fetch into jquants_records.",
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
        help="explicit JSDA bond-trade file URL (skip index scrape)",
    )
    p.add_argument(
        "--jsda-repo-url", dest="jsda_repo_url", default=None,
        help="explicit JSDA repo-rate (TRR) file URL (skip TRR index scrape)",
    )
    p.add_argument(
        "--jsda-only", dest="jsda_only", default=None,
        choices=["bond", "repo", "otc-reference"],
        help="run only one JSDA sub-source (bond trades or repo rates); "
             "otc-reference selects the governed 2002+ archive; default keeps "
             "the legacy bond + repo pass for compatibility",
    )
    p.add_argument(
        "--jsda-dataset", dest="jsda_dataset", default=None,
        choices=["otc-reference", "otc-corrections", "tokyo-repo"],
        help="explicit governed JSDA dataset selection",
    )
    p.add_argument(
        "--jsda-correction-id", dest="jsda_correction_ids",
        action="append", default=None,
        help="apply only this discovered OTC correction id (repeatable)",
    )
    p.add_argument(
        "--jsda-from-year", dest="jsda_from_year", type=int, default=2002,
        help="first governed OTC-reference archive year (default 2002)",
    )
    p.add_argument(
        "--jsda-to-year", dest="jsda_to_year", type=int, default=None,
        help="last governed OTC-reference archive year (default current year)",
    )
    p.add_argument(
        "--jsda-force", dest="jsda_force", action="store_true",
        help="re-fetch OTC segments even when an exact COMPLETE receipt exists",
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
    """Flatten repeated and comma-separated ``--dataset`` tokens.

    Recognizes two special tokens (Phase 3.5):
      * ``premiums`` -> expands to ``PREMIUM_CORE_DATASETS`` (23 ids)
      * ``addons``   -> expands to the catalog's addon group (5 ids)

    Any other token is treated as a literal catalog dataset id.
    """
    if not raw:
        return []
    # Imported lazily to keep --help cheap.
    from ingestion.jquants.catalog import (
        DATASETS,
        PREMIUM_CORE_DATASETS,
        list_datasets,
    )
    out: list[str] = []
    for tok in raw:
        for part in str(tok).split(","):
            s = part.strip()
            if not s:
                continue
            if s == "premiums":
                out.extend(PREMIUM_CORE_DATASETS)
            elif s == "addons":
                out.extend(list_datasets("addon"))
            elif s == "all":
                out.extend(list(DATASETS.keys()))
            else:
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
    unsafe_direct = os.environ.get("UNSAFE_DEV_DIRECT_JQUANTS", "").strip().lower()
    unsafe_direct = unsafe_direct in {"1", "true", "yes"}
    jquants_key = os.environ.get("JQUANTS_API_KEY", "") if unsafe_direct else ""

    using_jq_proxy = getattr(jq_http, "name", "") == "cf-jquants-proxy"
    if using_jq_proxy:
        print("[env] J-Quants via Cloudflare proxy (API key held on Worker).")
    elif jquants_key:
        print("[env] UNSAFE_DEV_DIRECT_JQUANTS enabled; local key value hidden.")
    elif os.environ.get("JQUANTS_API_KEY"):
        print(
            "[env] local JQUANTS_API_KEY ignored; set "
            "UNSAFE_DEV_DIRECT_JQUANTS=1 only for explicit unsafe dev use."
        )
    else:
        print("[env] JQUANTS_API_KEY absent — J-Quants will be skipped.")

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

        if args.source in ("jsda", "all"):
            otc_selected = (
                args.jsda_dataset == "otc-reference"
                or args.jsda_only == "otc-reference"
            )
            tokyo_repo_selected = args.jsda_dataset == "tokyo-repo"
            corrections_selected = args.jsda_dataset == "otc-corrections"
            legacy_selected = (
                args.jsda_dataset is None
                and not otc_selected
                and not tokyo_repo_selected
                and not corrections_selected
            )
            if legacy_selected:
                jsda_bond = args.jsda_only != "repo"
                jsda_repo = args.jsda_only != "bond"
                reps = run_jsda(
                    http=http, store=store, data_base=data_base, today=today,
                    runtime=runtime, target_url=args.jsda_url,
                    repo_target_url=args.jsda_repo_url,
                    bond=jsda_bond, repo=jsda_repo,
                )
                all_reports.extend(reps)
                for r in reps:
                    print(r.summary())
            if otc_selected:
                from ingestion.jsda.archive import run_otc_reference_backfill

                archive_report = run_otc_reference_backfill(
                    http=http,
                    store=store,
                    data_base=data_base,
                    from_year=args.jsda_from_year,
                    to_year=args.jsda_to_year,
                    force=args.jsda_force,
                )
                archive_run_report = archive_report.as_run_report()
                all_reports.append(archive_run_report)
                print(archive_run_report.summary())
            if tokyo_repo_selected:
                from ingestion.jsda.repo_archive import run_tokyo_repo_backfill

                repo_report = run_tokyo_repo_backfill(
                    http=http,
                    store=store,
                    data_base=data_base,
                    force=args.jsda_force,
                )
                repo_run_report = repo_report.as_run_report()
                all_reports.append(repo_run_report)
                print(repo_run_report.summary())
            if corrections_selected:
                from ingestion.jsda.corrections import run_otc_reference_corrections

                correction_report = run_otc_reference_corrections(
                    http=http,
                    store=store,
                    data_base=data_base,
                    correction_ids=args.jsda_correction_ids,
                    force=args.jsda_force,
                )
                correction_run_report = correction_report.as_run_report()
                all_reports.append(correction_run_report)
                print(correction_run_report.summary())
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
