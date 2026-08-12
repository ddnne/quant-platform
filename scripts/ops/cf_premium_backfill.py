#!/usr/bin/env python3
"""Drive CF premium backfill from contract-driven BackfillPlanner.

Does not hand-write dataset lists or history starts. Coverage Contract is SoT.
Existing shell driver is superseded for long-history closure.
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
import time
import urllib.error
import urllib.request
from pathlib import Path

# Repo root on path
ROOT = repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.backfill_planner import BackfillPlanner  # noqa: E402

def _token() -> str:
    path = Path(
        os.environ.get(
            "INGESTION_RUN_TOKEN_FILE",
            Path.home() / ".config/quant-platform/ingestion_run_token",
        )
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
            "User-Agent": "quant-platform-cf-backfill/1.0 (+ops planner)",
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

def main() -> int:
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
        help="Local research DB for skipping COMPLETE segments (optional)",
    )
    ap.add_argument("--sleep", type=float, default=8.0)
    ap.add_argument("--max-jobs", type=int, default=0, help="0 = no limit")
    ap.add_argument(
        "--plan-out",
        default=str(ROOT / ".glm-logs/cf-backfill/plan.json"),
    )
    ap.add_argument(
        "--state-out",
        default=str(ROOT / ".glm-logs/cf-backfill/planner_state.jsonl"),
    )
    ap.add_argument(
        "--datasets",
        default="",
        help="Optional comma filter AFTER contract inventory (debug only)",
    )
    args = ap.parse_args()

    planner = BackfillPlanner(db_path=args.db if Path(args.db).is_file() else None)
    plan = planner.plan()
    plan_path = Path(args.plan_out)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    print(
        f"plan jobs={len(plan.jobs)} contract={plan.contract_digest[:18]}… "
        f"cutoff={plan.cutoff}",
        flush=True,
    )

    allow = {d.strip() for d in args.datasets.split(",") if d.strip()}
    token = _token()
    state_path = Path(args.state_out)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    done = 0
    for job in plan.pending_jobs():
        if allow and job.dataset not in allow:
            continue
        if args.max_jobs and done >= args.max_jobs:
            break
        print(
            f"START {job.dataset} {job.requested_from}..{job.requested_to} "
            f"seg={job.segment_id}",
            flush=True,
        )
        job.attempt += 1
        job.state = "running"
        code, summary = _run_job(
            premium_url=args.premium_url,
            token=token,
            dataset=job.dataset,
            from_d=job.requested_from,
            to_d=job.requested_to,
        )
        job.apply_worker_summary(summary, http_status=code)
        print(
            f"DONE {job.dataset} {job.requested_from}..{job.requested_to} "
            f"-> {job.state} ({job.reason_code})",
            flush=True,
        )
        with state_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(job.to_dict()) + "\n")
        done += 1
        if job.state == "retry":
            time.sleep(max(args.sleep, 30.0))
        else:
            time.sleep(args.sleep)

    print(f"finished executed={done}", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
