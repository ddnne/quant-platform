#!/usr/bin/env python3
"""Drive CF premium backfill from contract-driven BackfillPlanner + range batch scheduler.

Does not hand-write dataset lists or history starts. Coverage Contract is SoT.
Existing shell driver is superseded for long-history closure.

Default mode is **dry-run** (plan + queue only). Pass ``--execute`` to POST
``/v1/run``. Tokens are read from ``~/.config`` (or env path) and **never logged**.

Rate pools (explicit):
  * general — J-Quants Premium ~500/min (driver default 480 RPM)
  * fins    — fins_* separate budget (driver default 480 RPM, isolated bucket)

See ``docs/architecture/adr_historical_raw_acceleration.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap repo root onto sys.path before importing qp_paths (plain script runs).
for _parent in Path(__file__).resolve().parents:
    if (_parent / "qp_paths.py").is_file() and (_parent / "pyproject.toml").is_file():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break
else:
    raise RuntimeError("quant-platform repo root not found from script")

from qp_paths import repo_root
import argparse
import json
import os
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

# Repo root on path
ROOT = repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.backfill_planner import (  # noqa: E402
    BackfillPlanner,
    PREMIUM_DRIVER_FINS_RPM,
    PREMIUM_DRIVER_GENERAL_RPM,
)
from ops.range_batch_scheduler import (  # noqa: E402
    SCHEDULER_CONFIG,
    TRACK_A_DATASETS,
    RangeBatchScheduler,
    SchedulerConfig,
    estimate_dispatch_envelope,
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
        help="General pool workers (0 = config default)",
    )
    ap.add_argument(
        "--fins-workers",
        type=int,
        default=0,
        help="Fins pool workers (0 = config default)",
    )
    ap.add_argument(
        "--general-rpm",
        type=float,
        default=PREMIUM_DRIVER_GENERAL_RPM,
        help=f"General pool RPM cap (default {PREMIUM_DRIVER_GENERAL_RPM}, under ~500/min)",
    )
    ap.add_argument(
        "--fins-rpm",
        type=float,
        default=PREMIUM_DRIVER_FINS_RPM,
        help=f"Fins pool RPM cap (default {PREMIUM_DRIVER_FINS_RPM}; separate budget)",
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
    args = ap.parse_args(argv)

    execute = bool(args.execute) and not bool(args.dry_run)
    ds_filter = [d.strip() for d in args.datasets.split(",") if d.strip()] or None
    cutoff = date.fromisoformat(args.cutoff[:10]) if args.cutoff else None

    db_path = Path(args.db) if args.db else None
    planner = BackfillPlanner(
        cutoff=cutoff,
        db_path=db_path if db_path and db_path.is_file() else None,
    )
    plan = planner.plan(
        datasets=ds_filter,
        from_date=args.from_date or None,
        to_date=args.to_date or None,
    )
    plan_path = Path(args.plan_out)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")

    cfg = SchedulerConfig(
        general_rpm=float(args.general_rpm),
        fins_rpm=float(args.fins_rpm),
        general_workers=int(args.workers) if args.workers > 0 else 4,
        fins_workers=int(args.fins_workers) if args.fins_workers > 0 else 2,
        max_jobs=int(args.max_jobs),
        execute=execute,
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
    out["scheduler_config_static"] = {
        k: SCHEDULER_CONFIG[k]
        for k in (
            "version",
            "rate_pools",
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
