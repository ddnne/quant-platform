#!/usr/bin/env python3
"""W94 / w0818d — multi-year window eval of skew / CM-term / ΔBaseVol logics.

Evaluates:
  * opt225_skew_abs_level
  * opt225_cm_term_abs_level
  * opt225_basevol_delta_abs

Plus BaseVol abs level as failure-mode compare (canonical level regime).
ATM / spread dual-eval is off-mainline (compare-only / non-informative).

Honest windows (same shards as W93):
  w2017_2019 / w2020_2022 / w2023_2025

CF r2_panels preferred + local real corroboration.
Does **not** arm Mass / READY / operational GO / continuous paper / live.
Does **not** retune the three frozen default-path representatives.
Does **not** claim smile/surface identical to level regime.

Examples
--------
    uv run python scripts/run_w94_opt_skew_windows.py \\
        --out-dir .glm-logs/w0818d_w94_opt_skew_thick/

    uv run python scripts/run_w94_opt_skew_windows.py --skip-cf
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

_here = Path(__file__).resolve().parent
for _d in (_here, _here.parent):
    if (_d / "_bootstrap.py").is_file():
        if str(_d) not in sys.path:
            sys.path.insert(0, str(_d))
        break
else:
    raise RuntimeError("scripts/_bootstrap.py not found")
from _bootstrap import ensure_repo_root

ROOT = ensure_repo_root()

# Primary W94 logics under eval.
SKEW_LOGIC_IDS: tuple[str, ...] = (
    "opt225_skew_abs_level",
    "opt225_cm_term_abs_level",
    "opt225_basevol_delta_abs",
)
# Canonical level compare (failure-mode reference; not dual-ATM).
LEVEL_COMPARE_LOGIC_IDS: tuple[str, ...] = (
    "opt225_basevol_abs_level",
)
# Off-mainline dual-eval (documented residual only; not claimed identical surface).
OFF_MAINLINE_LOGIC_IDS: tuple[str, ...] = (
    "opt225_atm_iv_abs_level",
    "opt225_iv_base_spread_abs",
)

EVAL_LOGIC_IDS: tuple[str, ...] = SKEW_LOGIC_IDS + LEVEL_COMPARE_LOGIC_IDS

# Same honest window set as W93/W94 track C.
W94_WINDOWS: tuple[dict[str, Any], ...] = (
    {
        "window_id": "w2017_2019",
        "label": "2017–2019",
        "start": "2017-01-01",
        "end": "2019-12-31",
        "shards": (
            {
                "period_id": "y2017_q4",
                "year": 2017,
                "period_start": "2017-09-01",
                "period_end": "2017-12-29",
                "window_kind": "q4",
            },
            {
                "period_id": "y2019_full",
                "year": 2019,
                "period_start": "2019-01-04",
                "period_end": "2019-10-18",
                "window_kind": "full_prefer",
            },
        ),
        "data_note": "2018 full/Q4 mirror absent; shards = y2017_q4 + y2019_full",
    },
    {
        "window_id": "w2020_2022",
        "label": "2020–2022",
        "start": "2020-01-01",
        "end": "2022-12-31",
        "shards": (
            {
                "period_id": "y2021_full",
                "year": 2021,
                "period_start": "2021-01-04",
                "period_end": "2021-10-15",
                "window_kind": "full_prefer",
            },
        ),
        "data_note": "2020/2022 bars mirrors absent; shard = y2021_full only",
    },
    {
        "window_id": "w2023_2025",
        "label": "2023–2025",
        "start": "2023-01-01",
        "end": "2025-12-31",
        "shards": (
            {
                "period_id": "y2023_full",
                "year": 2023,
                "period_start": "2023-01-04",
                "period_end": "2023-10-13",
                "window_kind": "full_prefer",
            },
            {
                "period_id": "y2025_q4",
                "year": 2025,
                "period_start": "2025-09-01",
                "period_end": "2025-12-29",
                "window_kind": "q4",
            },
        ),
        "data_note": "2024 full mirror absent; shards = y2023_full + y2025_q4",
    },
)


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")


def _scalar_f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return fv if math.isfinite(fv) else None


def _scalar_t(t: Any) -> float | None:
    if t is None:
        return None
    if isinstance(t, Mapping):
        return _scalar_f(t.get("t_stat"))
    return _scalar_f(t)


def _feature_bucket(logic_id: str) -> str:
    lid = str(logic_id or "")
    if "skew" in lid:
        return "skew"
    if "cm_term" in lid:
        return "cm_term"
    if "basevol_delta" in lid:
        return "basevol_delta"
    if "basevol" in lid:
        return "basevol_level"
    if "atm_iv" in lid:
        return "atm_iv_off_mainline"
    if "spread" in lid:
        return "spread_off_mainline"
    return "other"


def _row(r: Mapping[str, Any], *, window_id: str) -> dict[str, Any]:
    scr = r.get("screen") or {}
    lid = str(r.get("logic_id") or r.get("logic") or "")
    return {
        "window": window_id,
        "logic": lid,
        "bucket": _feature_bucket(lid),
        "family": r.get("family_id") or r.get("family") or "options_vol_regime",
        "mean_net": _scalar_f(r.get("mean_net")),
        "t": _scalar_t(r.get("t_stat") if "t_stat" in r else r.get("t")),
        "act": _scalar_f(
            r.get("mean_activation") if "mean_activation" in r else r.get("act")
        ),
        "sign": r.get("chosen_sign") if "chosen_sign" in r else r.get("sign"),
        "survived": bool(scr.get("survived"))
        if "survived" in scr
        else bool(r.get("survived")),
        "reject_reasons": list(
            scr.get("reject_reasons") or r.get("reject_reasons") or []
        ),
        "n_periods_ok": r.get("n_periods_ok"),
        "n_periods_total": r.get("n_periods_total"),
        "status": r.get("status"),
    }


def _markdown_window_table(rows: Sequence[Mapping[str, Any]]) -> str:
    header = (
        "| window | bucket | logic | mean_net | t | act | sign | survived | rejects |"
    )
    sep = "|---|---|---|---:|---:|---:|---|---|---|"
    lines = [header, sep]
    for r in rows:
        mn, t, act = r.get("mean_net"), r.get("t"), r.get("act")
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        act_s = f"{act:.4f}" if isinstance(act, float) else "—"
        sign = r.get("sign")
        sign_s = "—" if sign is None else str(sign)
        rejects = ",".join(str(x) for x in (r.get("reject_reasons") or [])[:3]) or "—"
        lines.append(
            f"| {r.get('window')} | {r.get('bucket')} | `{r.get('logic')}` | "
            f"{mn_s} | {t_s} | {act_s} | {sign_s} | {r.get('survived')} | {rejects} |"
        )
    return "\n".join(lines)


def _strategies(logic_ids: Sequence[str], *, source: str) -> list[dict[str, Any]]:
    from research.mass_strategy_factory import LOGIC_TEMPLATES

    out: list[dict[str, Any]] = []
    for lid in logic_ids:
        tpl = LOGIC_TEMPLATES.get(lid)
        if tpl is None:
            continue
        out.append(
            {
                "strategy_id": f"msf_w94_{lid}",
                "logic_id": lid,
                "family_id": tpl.family_id,
                "params": dict(tpl.base_params),
                "thesis": tpl.thesis,
                "signal_definition": tpl.signal_definition,
                "position_rule": tpl.position_rule,
                "datasets_used": list(tpl.datasets_used),
                "source": source,
            }
        )
    return out


def _reaggregate_window_from_period_rows(
    result: Mapping[str, Any],
    *,
    keep_period_ids: set[str],
    near_zero_abs: float,
    min_activation: float,
) -> dict[str, Any]:
    """Recompute window-level mean_net/t/act/sign/screen over shard subset."""
    from research.mass_strategy_factory import screen_strategy_result
    from research.sign_selection import (
        SIGN_INVERTED,
        SIGN_ORIGINAL,
        choose_sign,
        evaluate_sign_both_sides,
    )
    from research.stats_metrics import period_stats_report, sample_mean, t_stat_vs_zero

    period_rows = [
        dict(r)
        for r in (result.get("period_rows") or [])
        if str(r.get("period_id") or "") in keep_period_ids
    ]
    ok_rows = [r for r in period_rows if r.get("status") == "ok"]
    grosses = [r.get("gross_signed_mean_active") for r in ok_rows]
    nets = [r.get("net_one_way_mean_active") for r in ok_rows]
    costs = [r.get("amortized_one_way_cost") for r in ok_rows]
    pids = [str(r.get("period_id")) for r in ok_rows]

    hold = None
    for r in ok_rows:
        if r.get("hold_days") is not None:
            hold = int(r["hold_days"])
            break

    act_rates: list[float] = []
    for r in ok_rows:
        ar = r.get("activation_rate")
        if ar is None:
            occ = r.get("occurrence") or {}
            ar = occ.get("activation_rate")
        if ar is not None:
            try:
                act_rates.append(float(ar))
            except (TypeError, ValueError):
                pass
    mean_activation = sample_mean(act_rates)

    both = evaluate_sign_both_sides(
        period_grosses=grosses,
        period_nets=nets,
        amortized_costs=costs if any(c is not None for c in costs) else None,
        period_ids=pids,
        hold_days=hold,
        near_zero_abs=near_zero_abs,
    )
    choice = choose_sign(both, near_zero_abs=near_zero_abs)
    chosen_sign = choice.get("chosen_sign")
    side_key = (
        "original"
        if chosen_sign == SIGN_ORIGINAL
        else ("inverted" if chosen_sign == SIGN_INVERTED else "original")
    )
    side = dict(both.get(side_key) or {})
    side_nets = list(side.get("nets") or side.get("period_nets") or nets)
    stats = period_stats_report(side_nets)
    mean_net = side.get("mean_net")
    if mean_net is None:
        mean_net = sample_mean(nets)
    mean_gross = sample_mean(grosses)
    t_stat = side.get("t_stat")
    if t_stat is None:
        t_stat = t_stat_vs_zero(side_nets)

    pack = {
        "strategy_id": result.get("strategy_id"),
        "logic_id": result.get("logic_id"),
        "family_id": result.get("family_id") or "options_vol_regime",
        "params": result.get("params"),
        "n_periods_ok": len(ok_rows),
        "n_periods_total": len(period_rows),
        "period_rows": period_rows,
        "mean_gross": mean_gross,
        "mean_net": mean_net,
        "t_stat": t_stat,
        "sharpe_period": stats.get("sharpe") if isinstance(stats, Mapping) else None,
        "mean_activation": mean_activation,
        "sign_selection": {
            "chosen_sign": chosen_sign,
            "decision": choice.get("decision"),
            "reason": choice.get("reason"),
        },
        "chosen_sign": chosen_sign,
        "errors": [],
        "status": "evaluated" if ok_rows else "no_ok_periods",
    }
    scr = screen_strategy_result(
        pack, near_zero_abs=near_zero_abs, min_activation=min_activation
    )
    pack["screen"] = scr
    pack["survived"] = scr.get("survived")
    pack["reject_reasons"] = scr.get("reject_reasons")
    return pack


def run_local_window_eval(
    *,
    out_dir: Path,
    seed: int,
    max_codes: int,
    max_days: int,
    synthetic: bool,
    log,
) -> dict[str, Any]:
    from research.mass_strategy_factory import (
        MASS_FACTORY_VERSION,
        FROZEN_DEFAULT_PATH,
        MassFactoryConfig,
        evaluate_one_strategy,
        load_batch_data_context,
        screen_strategy_result,
    )

    strategies = _strategies(EVAL_LOGIC_IDS, source="w94_skew_window_local")
    cfg = MassFactoryConfig(
        seed=int(seed),
        n=len(strategies),
        max_codes=int(max_codes),
        max_days_per_period=int(max_days),
        use_q4_periods=False,
    )
    log(
        f"[w94] local per-window eval · n_logics={len(strategies)} "
        f"max_days={max_days} factory={MASS_FACTORY_VERSION} path=real_mirrors"
    )

    window_tables: list[dict[str, Any]] = []
    rows_flat: list[dict[str, Any]] = []
    results_all: list[dict[str, Any]] = []

    for w in W94_WINDOWS:
        wid = str(w["window_id"])
        periods = [dict(s) for s in w["shards"]]
        log(
            f"[w94]   local {wid} shards={[s['period_id'] for s in periods]} "
            f"note={w['data_note']}"
        )
        ctx = load_batch_data_context(
            cfg, periods=periods, synthetic=bool(synthetic)
        )
        window_results: list[dict[str, Any]] = []
        for strat in strategies:
            res = evaluate_one_strategy(
                strat,
                ctx,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            res["t_stat"] = _scalar_t(res.get("t_stat"))
            scr = screen_strategy_result(
                res,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            res["screen"] = scr
            window_results.append(res)
            results_all.append({**res, "window_id": wid})
            row = _row(res, window_id=wid)
            rows_flat.append(row)
            log(
                f"    {row['logic']}: net={row['mean_net']} act={row['act']} "
                f"sign={row['sign']} surv={row['survived']} "
                f"rej={row['reject_reasons']}"
            )

        side = {
            "window_id": wid,
            "label": w["label"],
            "start": w["start"],
            "end": w["end"],
            "data_note": w["data_note"],
            "short_disclose": True,
            "shard_ids": [s["period_id"] for s in periods],
            "rows": [_row(r, window_id=wid) for r in window_results],
            "n_survivors": sum(
                1 for r in window_results if (r.get("screen") or {}).get("survived")
            ),
            "load_notes": ctx.load_notes,
        }
        window_tables.append(side)

    pack = {
        "wave": "W94 / w0818d",
        "track": "B_skew_term_delta_multi_year_windows",
        "kind": "local_multi_year_window_eval",
        "factory_version": MASS_FACTORY_VERSION,
        "synthetic": bool(synthetic),
        "data_path": "synthetic" if synthetic else "real_mirrors",
        "max_days_per_period": int(max_days),
        "canonical_level": "base_vol",
        "atm_iv_role": "compare_only",
        "primary_logics": list(SKEW_LOGIC_IDS),
        "level_compare_logics": list(LEVEL_COMPARE_LOGIC_IDS),
        "off_mainline_dual_eval": list(OFF_MAINLINE_LOGIC_IDS),
        "off_mainline_note": (
            "BaseVol = canonical level; ATM = compare-only alias; "
            "spread = non-informative at frozen thresholds. "
            "Do NOT claim smile/surface identical to level regime."
        ),
        "iv_fields_available_from": "2016-07-19",
        "windows": [dict(w) for w in W94_WINDOWS],
        "n_strategies": len(strategies),
        "n_shards": sum(len(w["shards"]) for w in W94_WINDOWS),
        "window_tables": window_tables,
        "rows_flat": rows_flat,
        "markdown_table": _markdown_window_table(rows_flat),
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
        "failure_mode_vs_level": _failure_mode_compare(rows_flat),
    }
    _dump(out_dir / "skew_window_eval_local.json", pack)
    _dump(out_dir / "skew_local_window_table.json", rows_flat)
    (out_dir / "skew_local_window_table.md").write_text(
        "# W94 skew/term/Δ local window table\n\n"
        + pack["markdown_table"]
        + "\n",
        encoding="utf-8",
    )
    return pack


def _failure_mode_compare(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare primary logics' survival/sign/activation vs BaseVol abs level."""
    by_w: dict[str, dict[str, Mapping[str, Any]]] = {}
    for r in rows:
        by_w.setdefault(str(r.get("window")), {})[str(r.get("logic"))] = r
    out: list[dict[str, Any]] = []
    for wid, logics in by_w.items():
        level = logics.get("opt225_basevol_abs_level") or {}
        for lid in SKEW_LOGIC_IDS:
            cur = logics.get(lid) or {}
            out.append(
                {
                    "window": wid,
                    "logic": lid,
                    "logic_survived": cur.get("survived"),
                    "logic_sign": cur.get("sign"),
                    "logic_act": cur.get("act"),
                    "logic_mean_net": cur.get("mean_net"),
                    "logic_rejects": cur.get("reject_reasons"),
                    "level_survived": level.get("survived"),
                    "level_sign": level.get("sign"),
                    "level_act": level.get("act"),
                    "level_mean_net": level.get("mean_net"),
                    "sign_matches_level": (
                        None
                        if cur.get("sign") is None or level.get("sign") is None
                        else cur.get("sign") == level.get("sign")
                    ),
                    "both_survived": bool(cur.get("survived"))
                    and bool(level.get("survived")),
                    "note": (
                        "skew/term/Δ are shape/change features — not claimed "
                        "identical to BaseVol abs level regime"
                    ),
                }
            )
    return {"rows": out, "canonical_level": "base_vol"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="W94: skew/CM-term/ΔBaseVol multi-year window evals"
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0818d_w94_opt_skew_thick"),
    )
    p.add_argument("--seed", type=int, default=870818)
    p.add_argument(
        "--mode",
        type=str,
        default="r2_panels",
        choices=["r2_panels", "synthetic", "nets_only"],
    )
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--skip-cf", action="store_true")
    p.add_argument("--skip-local", action="store_true")
    p.add_argument("--skip-deploy", action="store_true")
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument(
        "--worker-url",
        type=str,
        default="https://quant-platform-research-mass-eval.taku-haga.workers.dev",
    )
    p.add_argument("--dry-run-r2", action="store_true")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    # Verify series cache has fullspan skew/cm_term.
    from research.options_225_vol_series import load_opt225_series_cache
    from research.class_hyp_eval import load_opt225_regime_bundle_for_eval

    cache = load_opt225_series_cache(out_dir)
    n_skew = len((cache or {}).get("skew_series") or [])
    n_term = len((cache or {}).get("cm_term_series") or [])
    n_delta = len((cache or {}).get("basevol_delta_series") or [])
    log(f"[w94] series cache skew={n_skew} cm_term={n_term} delta={n_delta}")
    if n_skew < 500 or n_term < 500:
        log(
            "[w94] WARNING: skew/cm_term look sample-sized; "
            "prefer fullspan rebuild before window claims"
        )
    regime = load_opt225_regime_bundle_for_eval(log_dir=out_dir)
    if regime:
        _dump(
            out_dir / "opt225_regime_coverage.json",
            {
                "canonical_level": regime.get("canonical_level"),
                "atm_iv_role": regime.get("atm_iv_role"),
                "n_basevol": (regime.get("basevol") or {}).get("n_obs_level"),
                "n_atm_iv": (regime.get("atm_iv") or {}).get("n_obs_level"),
                "n_skew": (regime.get("skew") or {}).get("n_obs_level"),
                "n_cm_term": (regime.get("cm_term") or {}).get("n_obs_level"),
                "n_basevol_delta": (regime.get("basevol_delta") or {}).get(
                    "n_obs_level"
                ),
                "skew_convention": regime.get("skew_convention"),
                "cm_term_convention": regime.get("cm_term_convention"),
                "basevol_delta_convention": regime.get("basevol_delta_convention"),
            },
        )

    window_pack: dict[str, Any] = {}
    if not args.skip_local:
        log("[w94] B: multi-year window local eval (skew + cm_term + ΔBaseVol)")
        window_pack = run_local_window_eval(
            out_dir=out_dir,
            seed=int(args.seed),
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            synthetic=bool(args.synthetic),
            log=log,
        )
    else:
        log("[w94] B: local window eval skipped")

    # ------------------------------------------------------------------ CF
    cf_pack: dict[str, Any] = {}
    cf_summary: dict[str, Any] = {}
    from research.cf_mass_eval_job import (
        CF_MASS_EVAL_VERSION,
        run_cf_mass_eval_job,
        try_cf_mass_eval_status,
    )

    cf_status = try_cf_mass_eval_status()
    _dump(out_dir / "cf_status_skew.json", cf_status)
    if not args.skip_cf:
        mode = "synthetic" if args.synthetic else str(args.mode)
        job_id = f"w94-skew-{ts}"
        log(f"[w94] C: CF mass-eval job_id={job_id} mode={mode}")
        shards: list[dict[str, Any]] = []
        for w in W94_WINDOWS:
            for s in w["shards"]:
                shards.append(dict(s))
        # Primary + level compare + light anchors (not retuned defaults).
        logic_ids = list(EVAL_LOGIC_IDS) + [
            "xs_rank_ls_sticky",
            "mdh_sticky_momentum",
        ]
        try:
            cf_max_days = min(int(args.max_days), 120)
            cf_pack = run_cf_mass_eval_job(
                job_id=job_id,
                logic_ids=logic_ids,
                periods=shards,
                mode=mode,
                max_codes=int(args.max_codes),
                max_days=cf_max_days,
                seed=int(args.seed),
                worker_url=str(args.worker_url),
                deploy_if_needed=not bool(args.skip_deploy),
                dry_run_r2=bool(args.dry_run_r2),
                staging_dir=out_dir / "panels_stage_skew",
            )
        except Exception as exc:
            log(f"[w94] C CF job failed: {exc}")
            cf_pack = {"status": "error", "error": str(exc), "job_id": job_id}
        _dump(out_dir / "cf_skew_mass_eval_job.json", cf_pack)
        wr = cf_pack.get("worker_response") or {}
        from research.mass_strategy_factory import MassFactoryConfig as _MFC

        _cfg = _MFC()
        cf_rows_flat: list[dict[str, Any]] = []
        cf_window_rows: list[dict[str, Any]] = []
        for w in W94_WINDOWS:
            wid = str(w["window_id"])
            shard_ids = {s["period_id"] for s in w["shards"]}
            window_opt_rows: list[dict[str, Any]] = []
            for r in wr.get("results") or []:
                lid = str(r.get("logic_id") or "")
                if lid not in EVAL_LOGIC_IDS and not lid.startswith("opt225_"):
                    continue
                if lid not in set(EVAL_LOGIC_IDS):
                    # ignore off-primary opt225 if worker returned extras
                    if lid not in EVAL_LOGIC_IDS:
                        continue
                reagg = _reaggregate_window_from_period_rows(
                    r,
                    keep_period_ids=shard_ids,
                    near_zero_abs=_cfg.near_zero_abs,
                    min_activation=_cfg.min_activation,
                )
                row = _row(reagg, window_id=wid)
                window_opt_rows.append(row)
            cf_window_rows.append(
                {
                    "window_id": wid,
                    "label": w["label"],
                    "data_note": w["data_note"],
                    "shard_ids": sorted(shard_ids),
                    "rows": window_opt_rows,
                    "n_survivors": sum(1 for r in window_opt_rows if r.get("survived")),
                }
            )
            cf_rows_flat.extend(window_opt_rows)
        jid = cf_pack.get("job_id") or job_id
        cf_summary = {
            "wave": "W94 / w0818d",
            "track": "B_skew_term_delta_multi_year_windows",
            "job_id": jid,
            "job_ids": [jid],
            "status": cf_pack.get("status"),
            "mode": cf_pack.get("mode") or mode,
            "version": CF_MASS_EVAL_VERSION,
            "n_survivors": cf_pack.get("n_survivors"),
            "n_logics": cf_pack.get("n_logics"),
            "n_periods": cf_pack.get("n_periods"),
            "r2_prefix": cf_pack.get("r2_prefix")
            or (cf_pack.get("artifact_paths") or {}).get("prefix"),
            "stage_panels": {
                "n_ok": (cf_pack.get("stage_panels") or {}).get("n_ok"),
                "n_periods": (cf_pack.get("stage_panels") or {}).get("n_periods"),
                "opt225_n_skew": (
                    (cf_pack.get("stage_panels") or {}).get("opt225_n_skew")
                ),
            },
            "canonical_level": "base_vol",
            "atm_iv_role": "compare_only",
            "primary_logics": list(SKEW_LOGIC_IDS),
            "window_tables": cf_window_rows,
            "rows_flat": cf_rows_flat,
            "markdown_table": _markdown_window_table(cf_rows_flat),
            "failure_mode_vs_level": _failure_mode_compare(cf_rows_flat),
            "opt225_results": [
                {
                    "logic_id": r.get("logic_id"),
                    "mean_net": r.get("mean_net"),
                    "t_stat": r.get("t_stat"),
                    "chosen_sign": r.get("chosen_sign"),
                    "mean_activation": r.get("mean_activation"),
                    "n_periods_ok": r.get("n_periods_ok"),
                    "survived": (r.get("screen") or {}).get("survived"),
                }
                for r in (wr.get("results") or [])
                if str(r.get("logic_id") or "") in set(logic_ids)
            ],
            "mass_research": "NO-GO",
            "operational_go": False,
            "ready_declared": False,
            "frozen_defaults_retuned": False,
        }
        _dump(out_dir / "cf_skew_window_summary.json", cf_summary)
        _dump(out_dir / "cf_skew_window_table.json", cf_rows_flat)
        (out_dir / "cf_skew_window_table.md").write_text(
            "# W94 skew/term/Δ CF window table\n\n"
            + cf_summary["markdown_table"]
            + "\n",
            encoding="utf-8",
        )
        log(
            f"[w94] C done · status={cf_pack.get('status')} "
            f"survivors={cf_pack.get('n_survivors')} job={jid}"
        )
    else:
        log("[w94] C: CF skipped")

    elapsed = round(time.perf_counter() - t0, 2)
    summary = {
        "wave": "W94 / w0818d",
        "track": "B_skew_term_delta_multi_year_windows",
        "ts": ts,
        "elapsed_sec": elapsed,
        "canonical_level": "base_vol",
        "atm_iv_role": "compare_only",
        "primary_logics": list(SKEW_LOGIC_IDS),
        "level_compare_logics": list(LEVEL_COMPARE_LOGIC_IDS),
        "off_mainline_dual_eval": {
            "logics": list(OFF_MAINLINE_LOGIC_IDS),
            "status": "off_mainline",
            "note": (
                "BaseVol canonical; ATM alias/compare-only; spread non-informative. "
                "Do not claim smile/surface identical."
            ),
        },
        "series_coverage": {
            "n_skew": n_skew,
            "n_cm_term": n_term,
            "n_basevol_delta": n_delta,
        },
        "local": {
            "n_survivors": sum(
                1 for r in (window_pack.get("rows_flat") or []) if r.get("survived")
            ),
            "rows_path": str(out_dir / "skew_local_window_table.md"),
        },
        "cf": {
            "job_id": cf_summary.get("job_id"),
            "status": cf_summary.get("status") or cf_pack.get("status"),
            "mode": cf_summary.get("mode") or cf_pack.get("mode"),
            "n_survivors": cf_summary.get("n_survivors") or cf_pack.get("n_survivors"),
            "rows_path": str(out_dir / "cf_skew_window_table.md"),
        },
        "freezes": {
            "mass_research": "NO-GO",
            "phase7": "OFF",
            "ready_declared": False,
            "operational_go": False,
            "continuous_paper": "UNARMED",
            "frozen_defaults_retuned": False,
        },
    }
    _dump(out_dir / "skew_window_summary.json", summary)
    (out_dir / "skew_window_SUMMARY.md").write_text(
        "\n".join(
            [
                "# W94 skew / CM-term / ΔBaseVol multi-year windows",
                "",
                f"**Wave:** W94 / w0818d",
                f"**Job:** `{summary['cf'].get('job_id')}`",
                f"**Mode:** {summary['cf'].get('mode')}",
                f"**CF status:** {summary['cf'].get('status')}",
                f"**Canonical level:** BaseVol · ATM compare-only",
                "",
                "## Freezes held",
                "",
                "- Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言",
                "- continuous paper UNARMED · 3 defaults not retuned",
                "- Do **not** claim smile/surface identical to level regime",
                "",
                "## Tables",
                "",
                "See `skew_local_window_table.md` and `cf_skew_window_table.md`.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    log(f"[w94] done elapsed={elapsed}s summary → {out_dir / 'skew_window_summary.json'}")
    return 0 if (args.skip_cf or (cf_pack.get("status") in (None, "ok", "partial"))) else 1


if __name__ == "__main__":
    raise SystemExit(main())
