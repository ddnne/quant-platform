#!/usr/bin/env python3
"""W91 / w0818a — CF mass-eval real COMPLETE-22 multi-period data quality.

Track A: stage real multi-year equities_bars_daily panels (COMPLETE-backed
local R2 mirrors) → POST research-mass-eval with mode=r2_panels (default,
**not** synthetic) → write job artifacts under
quant-structured/research/mass_eval/job={id}/ + local log dir.

Does **not** arm Mass / READY / operational GO / continuous paper / live.
Does **not** retune the three frozen default-path representatives.

Examples
--------
    # Full W91 real multi-year path (default mode=r2_panels):
    .venv/bin/python scripts/run_w91_real_cf_mass_eval.py \\
        --out-dir .glm-logs/w0818a_w91_real_vol/

    # Dry-run stage only (no remote R2 / no invoke):
    .venv/bin/python scripts/run_w91_real_cf_mass_eval.py --dry-run --skip-deploy

    # Tip-only D1 path (honest gap: not multi-year):
    .venv/bin/python scripts/run_w91_real_cf_mass_eval.py --mode d1_bars
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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

ROOT = ensure_repo_root()


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="W91: real COMPLETE-22 multi-period CF mass-eval (r2_panels)"
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0818a_w91_real_vol"),
    )
    p.add_argument("--seed", type=int, default=910818)
    p.add_argument(
        "--mode",
        type=str,
        default="r2_panels",
        choices=["r2_panels", "d1_bars", "synthetic", "nets_only"],
        help="W91 default is r2_panels (real); synthetic only for smoke",
    )
    p.add_argument("--max-codes", type=int, default=12)
    p.add_argument("--max-days", type=int, default=120)
    p.add_argument(
        "--job-id",
        type=str,
        default=None,
        help="Optional stable job id (default w91-real-<utc>)",
    )
    p.add_argument(
        "--worker-url",
        type=str,
        default="https://quant-platform-research-mass-eval.taku-haga.workers.dev",
    )
    p.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Do not wrangler deploy (use already-deployed worker)",
    )
    p.add_argument(
        "--skip-invoke",
        action="store_true",
        help="Stage panels only; do not POST /v1/mass-eval",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Stage panel bodies locally only (no remote R2 put)",
    )
    p.add_argument(
        "--no-stage",
        action="store_true",
        help="Skip panel staging (only valid if panels already on R2)",
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    from research.cf_mass_eval_job import (
        ALLOWED_MODES,
        CF_BAR_NATIVE_LOGIC_IDS,
        CF_MASS_EVAL_VERSION,
        CF_MASS_EVAL_WAVE,
        COMPLETE_22_DATASETS,
        DEFAULT_REAL_MULTIYEAR_PERIODS,
        DEFAULT_W91_MODE,
        PRIMARY_BARS_DATASET,
        inventory_complete22,
        run_cf_mass_eval_job,
        try_cf_mass_eval_status,
    )
    from research.mass_strategy_factory import (
        CONTINUOUS_PAPER,
        MASS_RESEARCH,
    )

    if args.mode not in ALLOWED_MODES:
        log(f"[w91] invalid mode={args.mode}")
        return 2

    job_id = args.job_id or (
        f"w91-real-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    )

    log(
        f"[w91] {CF_MASS_EVAL_WAVE} · version={CF_MASS_EVAL_VERSION} · "
        f"mode={args.mode} (default={DEFAULT_W91_MODE}) · seed={args.seed}"
    )
    log(
        f"[w91] freezes: mass={MASS_RESEARCH} continuous_paper={CONTINUOUS_PAPER} "
        f"READY=False ops_GO=False frozen_defaults_retuned=False"
    )

    inv = inventory_complete22()
    _dump(out_dir / "complete22_inventory.json", inv)
    log(
        f"[w91] COMPLETE_22 n={inv['dataset_complete_n']} · "
        f"primary_bars={PRIMARY_BARS_DATASET} · "
        f"permanent_defer n={inv['permanent_defer_n']}"
    )

    periods = [dict(p) for p in DEFAULT_REAL_MULTIYEAR_PERIODS]
    period_ids = [p["period_id"] for p in periods]
    _dump(
        out_dir / "periods.json",
        {
            "n": len(periods),
            "period_ids": period_ids,
            "periods": periods,
            "note": (
                "≥6 multi-year windows; full-prefer 2015/19/21/23 + Q4 2017/25. "
                "Longer than W90 synthetic Q4-only smoke."
            ),
        },
    )
    log(f"[w91] periods ({len(period_ids)}): {period_ids}")

    status_helper = try_cf_mass_eval_status()
    _dump(out_dir / "cf_status_helper.json", status_helper)

    # Health probe (User-Agent required; bare urllib may 403 on workers.dev)
    health: dict = {}
    try:
        import urllib.request

        req = urllib.request.Request(
            args.worker_url.rstrip("/") + "/health",
            headers={"User-Agent": "quant-platform-w91-cf-mass-eval/1.0"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            health = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    _dump(out_dir / "cf_health_pre.json", health)
    log(
        f"[w91] worker health ok={health.get('ok')} "
        f"wave={health.get('wave')} modes={health.get('modes')}"
    )

    log(
        f"[w91] run job_id={job_id} mode={args.mode} "
        f"max_codes={args.max_codes} max_days={args.max_days} "
        f"stage={not args.no_stage} deploy={not args.skip_deploy}"
    )

    try:
        pack = run_cf_mass_eval_job(
            job_id=job_id,
            logic_ids=list(CF_BAR_NATIVE_LOGIC_IDS),
            periods=periods,
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            seed=int(args.seed),
            mode=str(args.mode),
            stage_panels=False if args.no_stage else None,
            worker_url=str(args.worker_url),
            deploy_if_needed=not bool(args.skip_deploy),
            mirror_r2_from_driver=False,  # worker writes R2; avoid double put
            dry_run_r2=bool(args.dry_run),
            staging_dir=out_dir / "staged_panels" if args.dry_run else None,
            skip_invoke=bool(args.skip_invoke) or bool(args.dry_run),
            timeout=300,
        )
    except Exception as exc:
        err = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "job_id": job_id,
            "mode": args.mode,
            "wave": CF_MASS_EVAL_WAVE,
        }
        _dump(out_dir / "cf_mass_eval_job.json", err)
        log(f"[w91] FAILED: {err['error']}")
        return 1

    _dump(out_dir / "cf_mass_eval_job.json", pack)
    if pack.get("stage_panels"):
        _dump(out_dir / "stage_panels.json", pack["stage_panels"])
    if pack.get("worker_response"):
        _dump(out_dir / "cf_mass_eval_response.json", pack["worker_response"])
    if pack.get("deploy"):
        _dump(out_dir / "deploy.json", pack["deploy"])

    # Compact run report
    stage = pack.get("stage_panels") or {}
    resp = pack.get("worker_response") or {}
    report = {
        "wave": CF_MASS_EVAL_WAVE,
        "version": CF_MASS_EVAL_VERSION,
        "job_id": pack.get("job_id"),
        "mode": pack.get("mode"),
        "status": pack.get("status"),
        "datasets_used": pack.get("datasets_used"),
        "complete_22": list(COMPLETE_22_DATASETS),
        "primary_bars": PRIMARY_BARS_DATASET,
        "period_ids": pack.get("period_ids"),
        "periods": pack.get("periods"),
        "n_logics": pack.get("n_logics"),
        "n_periods": pack.get("n_periods"),
        "n_eval_ok": pack.get("n_eval_ok") or pack.get("n_evaluated"),
        "n_survivors": pack.get("n_survivors"),
        "r2_prefix": pack.get("r2_prefix"),
        "r2_keys": pack.get("r2_keys"),
        "panels_prefix": pack.get("panels_prefix"),
        "stage_n_ok": stage.get("n_ok"),
        "stage_panels": stage.get("panels"),
        "worker_mode": resp.get("mode"),
        "worker_wall_time_ms": resp.get("wall_time_ms"),
        "panels_meta_notes": (
            (resp.get("r2_keys") or {}).get("panels_meta")
        ),
        "invoke_error": pack.get("invoke_error"),
        "wall_time_sec": pack.get("wall_time_sec"),
        "freezes": {
            "mass_research": MASS_RESEARCH,
            "ready_declared": False,
            "operational_go": False,
            "continuous_paper": CONTINUOUS_PAPER,
            "frozen_defaults_retuned": False,
        },
    }
    _dump(out_dir / "w91_run_report.json", report)

    wall = round(time.perf_counter() - t0, 3)
    log(
        f"[w91] done status={pack.get('status')} job_id={pack.get('job_id')} "
        f"mode={pack.get('mode')} n_logics={pack.get('n_logics')} "
        f"n_periods={pack.get('n_periods')} n_eval_ok={pack.get('n_eval_ok')} "
        f"n_survivors={pack.get('n_survivors')} "
        f"r2_prefix={pack.get('r2_prefix')} wall={wall}s"
    )
    if pack.get("invoke_error"):
        log(f"[w91] invoke_error={pack.get('invoke_error')}")
    if stage:
        log(
            f"[w91] staged panels n_ok={stage.get('n_ok')}/"
            f"{stage.get('n_periods')} prefix={stage.get('panels_prefix')}"
        )

    # Honest remaining gaps (written for STATUS.md assembly)
    gaps = {
        "wave": CF_MASS_EVAL_WAVE,
        "synthetic_remaining": [
            {
                "gap": "rate/mf factor legs not-yet-implemented on pure-TS CF path",
                "impact": (
                    "bar-native mdh/xs/vol evaluate on real panels; "
                    "rate/multi-factor families fall back to mdh-style or nets_only"
                ),
                "honest": True,
            },
            {
                "gap": "d1_bars is tip-only hot window (~2026-07..08), not multi-year",
                "impact": "multi-year real path requires mode=r2_panels staging",
                "honest": True,
            },
            {
                "gap": "panels staged from local COMPLETE-backed mirrors (W63/W64), "
                "not live full-history R2 scan inside the Worker",
                "impact": (
                    "real equities_bars_daily prices; codes×days subsampled "
                    f"(max_codes={args.max_codes}, max_days={args.max_days})"
                ),
                "honest": True,
            },
            {
                "gap": "indices panels not yet co-staged for index-relative logics on CF",
                "impact": "TOPIX-relative legs still prefer local class_hyp_eval",
                "honest": True,
            },
            {
                "gap": "synthetic mode still available for smoke; W91 default is r2_panels",
                "impact": "do not treat synthetic CF nets as real data quality",
                "honest": True,
            },
        ],
        "not_claimed": [
            "Mass / READY / operational GO",
            "continuous paper arming",
            "3 defaults retune",
            "live orders",
            "full-universe multi-year deep eval",
        ],
    }
    _dump(out_dir / "synthetic_gaps.json", gaps)

    ok = pack.get("status") == "ok" or (
        args.dry_run and (stage.get("n_ok") or 0) > 0
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
