#!/usr/bin/env python3
"""Drive CF premium backfill from contract-driven BackfillPlanner + range batch scheduler.

Does not hand-write dataset lists or history starts. Coverage Contract is SoT.
Existing shell driver is superseded for long-history closure.

Default mode is **dry-run** (plan + queue only). Pass ``--execute`` to POST
``/v1/run``. Tokens are read from ``~/.config`` (or env path) and **never logged**.

Rate pools (explicit):
  * general — J-Quants Premium ~500/min (driver default 495 RPM, near ceiling)
  * fins    — fins_* separate budget (driver default 495 RPM, isolated bucket)

See ``docs/architecture/adr_historical_raw_acceleration.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
else:
    raise RuntimeError("scripts/_bootstrap.py not found")
from _bootstrap import ensure_repo_root  # noqa: E402

import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import date

ROOT = ensure_repo_root()

from ops.backfill_planner import (  # noqa: E402
    BackfillPlanner,
    PREMIUM_DRIVER_FINS_RPM,
    PREMIUM_DRIVER_GENERAL_RPM,
)
from ops.range_batch_scheduler import (  # noqa: E402
    DEFAULT_FINS_WORKERS,
    DEFAULT_GENERAL_WORKERS,
    DEFAULT_SLEEP_ON_RETRY_S,
    SCHEDULER_CONFIG,
    TRACK_A_DATASETS,
    RangeBatchScheduler,
    SchedulerConfig,
    estimate_dispatch_envelope,
    measure_dispatch_rpm,
)
from ingestion.jsda.official_index import (  # noqa: E402
    read_local_index_text as _read_index_text,
)


def _token() -> str:
    """Load ingestion run token. Never print or log the return value."""
    path = Path(
        os.environ.get(
            "INGESTION_RUN_TOKEN_FILE",
            Path.home() / ".config/quant-platform/ingestion_run_token",
        )
    )
    if not path.is_file():
        raise FileNotFoundError(
            f"ingestion run token file missing: {path} "
            "(set INGESTION_RUN_TOKEN_FILE; do not pass tokens on CLI)"
        )
    return path.read_text(encoding="utf-8").strip()


def _run_job(
    *,
    premium_url: str,
    token: str,
    dataset: str,
    from_d: str,
    to_d: str,
    timeout: int = 600,
) -> tuple[int, dict]:
    url = f"{premium_url.rstrip('/')}/v1/run?dataset={dataset}&from={from_d}&to={to_d}"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "X-Ingestion-Token": token.strip(),
            "User-Agent": "quant-platform-cf-backfill/1.1 (+range batch scheduler)",
            "Accept": "application/json",
        },
        data=b"",  # explicit empty body for POST
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            code = int(resp.status)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        code = int(exc.code)
    except Exception as exc:  # noqa: BLE001
        return 0, {"status": "fail", "error": str(exc)}
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {"status": "fail", "raw": body[:500]}
    # Prefer worker JSON summary; CF edge 403 HTML is not entitlement.
    if isinstance(payload, dict) and "summary" in payload:
        summary = payload["summary"]
        if not isinstance(summary, dict):
            summary = {"status": "fail", "detail": summary}
        return code, summary
    if code == 403 and ("<!DOCTYPE" in body or "<html" in body.lower()):
        return code, {
            "status": "fail",
            "error": "edge_forbidden",
            "detail": body[:200],
        }
    if code == 401 or (
        isinstance(payload, dict) and payload.get("error") == "unauthorized"
    ):
        return 401, {"status": "fail", "error": "unauthorized"}
    return code, {
        "status": "fail" if code != 200 else "pass",
        "detail": payload if payload else body[:300],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--premium-url",
        default=os.environ.get(
            "PREMIUM_URL",
            "https://quant-platform-ingestion-premium.taku-haga.workers.dev",
        ),
    )
    ap.add_argument(
        "--db",
        default=str(ROOT / "data/structured/ingestion.sqlite"),
        help="Local research DB for skipping COMPLETE segments (optional mirror)",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="Actually POST /v1/run (default: dry-run plan only)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Force dry-run even if --execute was set (wins)",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=0,
        help=f"General pool workers (0 = default {DEFAULT_GENERAL_WORKERS})",
    )
    ap.add_argument(
        "--fins-workers",
        type=int,
        default=0,
        help=f"Fins pool workers (0 = default {DEFAULT_FINS_WORKERS})",
    )
    ap.add_argument(
        "--general-rpm",
        type=float,
        default=PREMIUM_DRIVER_GENERAL_RPM,
        help=f"General pool RPM cap (default {PREMIUM_DRIVER_GENERAL_RPM}, near ~500/min)",
    )
    ap.add_argument(
        "--fins-rpm",
        type=float,
        default=PREMIUM_DRIVER_FINS_RPM,
        help=f"Fins pool RPM cap (default {PREMIUM_DRIVER_FINS_RPM}; separate budget)",
    )
    ap.add_argument(
        "--sleep-on-retry",
        type=float,
        default=DEFAULT_SLEEP_ON_RETRY_S,
        help=(
            f"Seconds to pause after HTTP 429/retryable fail before next job "
            f"(default {DEFAULT_SLEEP_ON_RETRY_S}; short recovery, not a deep park)"
        ),
    )
    ap.add_argument("--max-jobs", type=int, default=0, help="0 = no limit")
    ap.add_argument(
        "--plan-out",
        default=str(ROOT / ".glm-logs/cf-backfill/plan.json"),
    )
    ap.add_argument(
        "--queue-out",
        default=str(ROOT / ".glm-logs/cf-backfill/queue.json"),
    )
    ap.add_argument(
        "--state-out",
        default=str(ROOT / ".glm-logs/cf-backfill/planner_state.jsonl"),
    )
    ap.add_argument(
        "--datasets",
        default="",
        help="Optional comma filter AFTER contract inventory",
    )
    ap.add_argument("--from-date", default="", help="Inclusive lower bound YYYY-MM-DD")
    ap.add_argument("--to-date", default="", help="Inclusive upper bound YYYY-MM-DD")
    ap.add_argument(
        "--index-text",
        default=None,
        metavar="PATH",
        help=(
            "local official-archive index HTML. Omitted: index_text is None "
            "so OTC required set is fail-closed empty, not a calendar replay. "
            "Does not fetch live JSDA HTML."
        ),
    )
    ap.add_argument(
        "--track-a",
        action="store_true",
        help=f"Filter to Track A datasets: {', '.join(TRACK_A_DATASETS)}",
    )
    ap.add_argument(
        "--latest-only",
        action="store_true",
        help="Keep only the latest pending segment per dataset (e.g. margin refresh)",
    )
    ap.add_argument(
        "--cutoff",
        default="",
        help="Plan cutoff YYYY-MM-DD (default: yesterday UTC)",
    )
    ap.add_argument(
        "--chunk-days",
        type=int,
        default=7,
        help="When using --week-chunks, subdivide today-mode into N-day ranges (default 7)",
    )
    ap.add_argument(
        "--week-chunks",
        action="store_true",
        help=(
            "Force week/N-day chunks for today-mode datasets (equities_bars_daily). "
            "Avoids CF Worker resource limit 1102 on full calendar months. "
            "segment_id remains YYYY-MM for coverage identity."
        ),
    )
    args = ap.parse_args(argv)

    execute = bool(args.execute) and not bool(args.dry_run)
    ds_filter = [d.strip() for d in args.datasets.split(",") if d.strip()] or None
    cutoff = date.fromisoformat(args.cutoff[:10]) if args.cutoff else None

    try:
        index_text = _read_index_text(args.index_text)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", flush=True)
        return 1

    db_path = Path(args.db) if args.db else None
    planner = BackfillPlanner(
        cutoff=cutoff,
        db_path=db_path if db_path and db_path.is_file() else None,
        chunk_days_for_today_mode=int(args.chunk_days) if int(args.chunk_days) > 0 else 7,
        prefer_month_chunks_for_today=not bool(args.week_chunks),
    )
    plan = planner.plan(
        datasets=ds_filter,
        from_date=args.from_date or None,
        to_date=args.to_date or None,
        index_text=index_text,
    )
    plan_path = Path(args.plan_out)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")

    cfg = SchedulerConfig(
        general_rpm=float(args.general_rpm),
        fins_rpm=float(args.fins_rpm),
        general_workers=(
            int(args.workers) if args.workers > 0 else DEFAULT_GENERAL_WORKERS
        ),
        fins_workers=(
            int(args.fins_workers) if args.fins_workers > 0 else DEFAULT_FINS_WORKERS
        ),
        max_jobs=int(args.max_jobs),
        execute=execute,
        sleep_on_retry_s=max(0.0, float(args.sleep_on_retry)),
    )

    token = ""
    if execute:
        token = _token()
        if not token:
            print("ERROR: empty ingestion token", flush=True)
            return 2

    scheduler = RangeBatchScheduler(
        plan,
        config=cfg,
        run_job=_run_job if execute else None,
        premium_url=args.premium_url,
        token=token,
    )
    # Drop token from local scope after hand-off (scheduler holds it privately).
    token = ""

    result = scheduler.run(
        datasets=ds_filter,
        from_date=args.from_date or None,
        to_date=args.to_date or None,
        track_a=bool(args.track_a),
        latest_only=bool(args.latest_only),
        state_path=Path(args.state_out) if execute else None,
    )
    envelope = estimate_dispatch_envelope(
        scheduler.queue(
            datasets=ds_filter,
            from_date=args.from_date or None,
            to_date=args.to_date or None,
            track_a=bool(args.track_a),
            latest_only=bool(args.latest_only),
        ),
        general_rpm=cfg.general_rpm,
        fins_rpm=cfg.fins_rpm,
    )
    out = result.to_dict()
    out["dispatch_envelope"] = envelope
    host_rpm = measure_dispatch_rpm(result.executed) if result.executed else None
    if host_rpm is not None:
        out["host_dispatch_rpm"] = host_rpm
    out["scheduler_config_static"] = {
        k: SCHEDULER_CONFIG[k]
        for k in (
            "version",
            "rate_pools",
            "sleep_on_retry_s",
            "track_a_datasets",
            "date_range_batch_standard",
            "default_mode",
        )
    }
    # Belt-and-suspenders: never serialize secrets
    for banned in ("token", "authorization", "api_key", "secret"):
        out.pop(banned, None)

    queue_path = Path(args.queue_out)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"mode={result.mode} plan_jobs={len(plan.jobs)} queued={len(result.queued)} "
        f"executed={len(result.executed)} contract={plan.contract_digest[:18]}… "
        f"cutoff={plan.cutoff}",
        flush=True,
    )
    print(
        f"pools general={result.counts_by_pool.get('general', 0)} "
        f"fins={result.counts_by_pool.get('fins', 0)} "
        f"by_dataset={json.dumps(result.counts_by_dataset, sort_keys=True)}",
        flush=True,
    )
    print(
        f"dispatch_envelope={json.dumps(envelope, sort_keys=True)}",
        flush=True,
    )
    if host_rpm is not None:
        print(
            f"host_dispatch_rpm={json.dumps(host_rpm, sort_keys=True)}",
            flush=True,
        )
    print(f"plan_out={plan_path}", flush=True)
    print(f"queue_out={queue_path}", flush=True)
    if not execute:
        print(
            "dry-run complete (no /v1/run). Re-run with --execute to dispatch.",
            flush=True,
        )
    else:
        print(
            f"finished executed={len(result.executed)} states={result.counts_by_state}",
            flush=True,
        )
        print(
            "NOTE: worker pass != Coverage COMPLETE; seal only with raw+structured.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
