#!/usr/bin/env python3
"""W95 / w0818e — promising-few re-eval (shape + any repaired).

Narrow to shape primary logics (+ level compare) and optional mom3 binds.
Do **not** retune 3 defaults. Do **not** blast dead rate/flow/fund logics.
Do **not** fix survivor count to exactly 2. CF r2_panels preferred.
fund_value_mom_agree_slow excluded (W95 demoted artifact).

Examples
--------
    uv run python scripts/run_w95_promising_reeval.py \\
        --out-dir .glm-logs/w0818e_w95_shape_factor_decomp/

    uv run python scripts/run_w95_promising_reeval.py --skip-deploy --skip-cf
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

W95_WINDOWS: tuple[dict[str, Any], ...] = (
    {
        "window_id": "w2017_2019",
        "label": "2017–2019",
        "data_note": "2018 mirror absent; y2017_q4 + y2019_full",
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
    },
    {
        "window_id": "w2020_2022",
        "label": "2020–2022",
        "data_note": "2020/2022 mirrors absent; y2021_full only",
        "shards": (
            {
                "period_id": "y2021_full",
                "year": 2021,
                "period_start": "2021-01-04",
                "period_end": "2021-10-15",
                "window_kind": "full_prefer",
            },
        ),
    },
    {
        "window_id": "w2023_2025",
        "label": "2023–2025",
        "data_note": "2024 mirror absent; y2023_full + y2025_q4",
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
    },
)

SHAPE_LOGIC_IDS: tuple[str, ...] = (
    "opt225_skew_abs_level",
    "opt225_cm_term_abs_level",
    "opt225_basevol_delta_abs",
)
LEVEL_LOGIC_IDS: tuple[str, ...] = ("opt225_basevol_abs_level",)
# Light anchors only (not frozen-default retune).
ANCHOR_LOGIC_IDS: tuple[str, ...] = (
    "xs_rank_ls_sticky",
    "mdh_sticky_momentum",
)
# Explicitly excluded (demoted / dead blast).
EXCLUDED_LOGIC_IDS: tuple[str, ...] = (
    "fund_value_mom_agree_slow",
    "macro_repo_rate_change",
    "macro_repo_rate_level",
    "flow_margin_pressure",
    "flow_margin_short_hard",
    "flow_margin_short_soft",
    "fund_value_only",
    "fund_value_mom_agree",
    "mf_value_mom_rate",
    "mf_flow_price",
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
    if lid.startswith("xs_") or "cross_section" in lid:
        return "anchor_xs"
    if lid.startswith("mdh_"):
        return "anchor_mdh"
    return "other"


def _row(r: Mapping[str, Any], *, window_id: str) -> dict[str, Any]:
    scr = r.get("screen") or {}
    lid = str(r.get("logic_id") or r.get("logic") or "")
    params = dict(r.get("params") or {})
    return {
        "window": window_id,
        "logic": lid,
        "bucket": _feature_bucket(lid),
        "variant": r.get("variant") or "default",
        "momentum_n": params.get("momentum_n"),
        "high_threshold": params.get("high_threshold"),
        "low_threshold": params.get("low_threshold"),
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
    }


def _markdown_table(rows: Sequence[Mapping[str, Any]]) -> str:
    header = (
        "| window | bucket | logic | variant | mom | mean_net | t | act | sign | surv |"
    )
    sep = "|---|---|---|---|---:|---:|---:|---:|---|---|"
    lines = [header, sep]
    for r in rows:
        mn, t, act = r.get("mean_net"), r.get("t"), r.get("act")
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        act_s = f"{act:.4f}" if isinstance(act, float) else "—"
        sign = r.get("sign")
        sign_s = "—" if sign is None else str(sign)
        mom = r.get("momentum_n")
        lines.append(
            f"| {r.get('window')} | {r.get('bucket')} | `{r.get('logic')}` | "
            f"{r.get('variant')} | {mom if mom is not None else '—'} | "
            f"{mn_s} | {t_s} | {act_s} | {sign_s} | {r.get('survived')} |"
        )
    return "\n".join(lines)


def _reaggregate_window_from_period_rows(
    result: Mapping[str, Any],
    *,
    keep_period_ids: set[str],
    near_zero_abs: float,
    min_activation: float,
) -> dict[str, Any]:
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
    t_stat = side.get("t_stat")
    if t_stat is None:
        t_stat = t_stat_vs_zero(side_nets)
    pack = {
        "strategy_id": result.get("strategy_id"),
        "logic_id": result.get("logic_id"),
        "family_id": result.get("family_id"),
        "params": result.get("params"),
        "variant": result.get("variant") or "default",
        "n_periods_ok": len(ok_rows),
        "n_periods_total": len(period_rows),
        "period_rows": period_rows,
        "mean_net": mean_net,
        "t_stat": t_stat,
        "sharpe_period": stats.get("sharpe") if isinstance(stats, Mapping) else None,
        "mean_activation": mean_activation,
        "chosen_sign": chosen_sign,
        "status": "evaluated" if ok_rows else "no_ok_periods",
    }
    scr = screen_strategy_result(
        pack, near_zero_abs=near_zero_abs, min_activation=min_activation
    )
    pack["screen"] = scr
    pack["survived"] = scr.get("survived")
    pack["reject_reasons"] = scr.get("reject_reasons")
    return pack


def _mom3_bind_extra_logics() -> list[dict[str, Any]]:
    """Few shape×CS binds as extra CF logics (distinct logic_id tags)."""
    from research.mass_strategy_factory import LOGIC_TEMPLATES

    out: list[dict[str, Any]] = []
    for lid in SHAPE_LOGIC_IDS:
        tpl = LOGIC_TEMPLATES[lid]
        params = dict(tpl.base_params)
        params["momentum_n"] = 3
        out.append(
            {
                "logic_id": f"{lid}__mom3",
                "family_id": tpl.family_id,
                "params": params,
                "thesis": f"{tpl.thesis} · W95 bind mom=3",
                "signal_definition": tpl.signal_definition,
                "position_rule": tpl.position_rule,
                "datasets_used": list(tpl.datasets_used),
                "variant": "bind_mom3",
            }
        )
    return out


def run_local(
    *,
    out_dir: Path,
    seed: int,
    max_codes: int,
    max_days: int,
    include_mom3_binds: bool,
    log,
) -> dict[str, Any]:
    from research.mass_strategy_factory import (
        FROZEN_DEFAULT_PATH,
        LOGIC_TEMPLATES,
        MassFactoryConfig,
        evaluate_one_strategy,
        load_batch_data_context,
        screen_strategy_result,
    )

    strategies: list[dict[str, Any]] = []
    for lid in list(SHAPE_LOGIC_IDS) + list(LEVEL_LOGIC_IDS):
        tpl = LOGIC_TEMPLATES[lid]
        strategies.append(
            {
                "strategy_id": f"msf_w95_reeval_{lid}",
                "logic_id": lid,
                "family_id": tpl.family_id,
                "params": dict(tpl.base_params),
                "variant": "default",
            }
        )
    if include_mom3_binds:
        for lid in SHAPE_LOGIC_IDS:
            tpl = LOGIC_TEMPLATES[lid]
            params = dict(tpl.base_params)
            params["momentum_n"] = 3
            strategies.append(
                {
                    "strategy_id": f"msf_w95_reeval_{lid}_mom3",
                    "logic_id": lid,
                    "family_id": tpl.family_id,
                    "params": params,
                    "variant": "bind_mom3",
                }
            )

    cfg = MassFactoryConfig(
        seed=int(seed),
        n=len(strategies),
        max_codes=int(max_codes),
        max_days_per_period=int(max_days),
        use_q4_periods=False,
    )
    rows_flat: list[dict[str, Any]] = []
    for w in W95_WINDOWS:
        wid = str(w["window_id"])
        periods = [dict(s) for s in w["shards"]]
        log(f"[w95] local reeval {wid} n_strats={len(strategies)}")
        ctx = load_batch_data_context(cfg, periods=periods, synthetic=False)
        for strat in strategies:
            res = evaluate_one_strategy(
                strat,
                ctx,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            res["params"] = dict(strat.get("params") or {})
            res["variant"] = strat.get("variant")
            res["t_stat"] = _scalar_t(res.get("t_stat"))
            scr = screen_strategy_result(
                res,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            res["screen"] = scr
            rows_flat.append(_row(res, window_id=wid))

    pack = {
        "wave": "W95 / w0818e",
        "track": "C_promising_few_reeval_local",
        "excluded": list(EXCLUDED_LOGIC_IDS),
        "include_mom3_binds": include_mom3_binds,
        "rows_flat": rows_flat,
        "markdown_table": _markdown_table(rows_flat),
        "n_survivors": sum(1 for r in rows_flat if r.get("survived")),
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
        "promote_as_main_candidate": False,
    }
    _dump(out_dir / "promising_reeval_local.json", pack)
    (out_dir / "promising_reeval_local_table.md").write_text(
        "# W95 promising-few local re-eval\n\n" + pack["markdown_table"] + "\n",
        encoding="utf-8",
    )
    return pack


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="W95 promising-few re-eval")
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0818e_w95_shape_factor_decomp"),
    )
    p.add_argument("--seed", type=int, default=870818)
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--mode", type=str, default="r2_panels", choices=["r2_panels", "synthetic"])
    p.add_argument("--skip-cf", action="store_true")
    p.add_argument("--skip-local", action="store_true")
    p.add_argument("--skip-deploy", action="store_true")
    p.add_argument("--include-mom3-binds", action="store_true", default=True)
    p.add_argument("--no-mom3-binds", action="store_true")
    p.add_argument(
        "--worker-url",
        type=str,
        default="https://quant-platform-research-mass-eval.taku-haga.workers.dev",
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Ensure series cache available (symlink from W94 if needed).
    prior = ROOT / ".glm-logs" / "w0818d_w94_opt_skew_thick"
    for name in (
        "skew_series.ndjson",
        "cm_term_series.ndjson",
        "basevol_delta_series.ndjson",
        "base_vol_series.ndjson",
        "atm_iv_series.ndjson",
        "spread_series.ndjson",
        "series_meta.json",
        "fullspan_stats.json",
        "skew_rule.json",
        "cm_term_rule.json",
        "basevol_delta_rule.json",
        "basevol_rule.json",
        "atm_iv_rule.json",
    ):
        src = prior / name
        dst = out_dir / name
        if src.is_file() and not dst.exists():
            try:
                dst.symlink_to(src.resolve())
            except OSError:
                dst.write_bytes(src.read_bytes())

    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    include_mom3 = bool(args.include_mom3_binds) and not bool(args.no_mom3_binds)

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    local_pack: dict[str, Any] = {}
    if not args.skip_local:
        local_pack = run_local(
            out_dir=out_dir,
            seed=int(args.seed),
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            include_mom3_binds=include_mom3,
            log=log,
        )
        log(f"[w95] local survivors={local_pack.get('n_survivors')}")

    cf_pack: dict[str, Any] = {}
    cf_summary: dict[str, Any] = {}
    if not args.skip_cf:
        from research.cf_mass_eval_job import (
            CF_MASS_EVAL_VERSION,
            run_cf_mass_eval_job,
            try_cf_mass_eval_status,
        )
        from research.mass_strategy_factory import MassFactoryConfig as _MFC

        status = try_cf_mass_eval_status()
        _dump(out_dir / "cf_status_reeval.json", status)
        job_id = f"w95-shape-{ts}"
        shards: list[dict[str, Any]] = []
        for w in W95_WINDOWS:
            for s in w["shards"]:
                shards.append(dict(s))
        logic_ids = list(SHAPE_LOGIC_IDS) + list(LEVEL_LOGIC_IDS) + list(ANCHOR_LOGIC_IDS)
        extra = _mom3_bind_extra_logics() if include_mom3 else []
        log(
            f"[w95] CF reeval job_id={job_id} mode={args.mode} "
            f"n_logics={len(logic_ids)}+extra={len(extra)}"
        )
        try:
            cf_max_days = min(int(args.max_days), 120)
            cf_pack = run_cf_mass_eval_job(
                job_id=job_id,
                logic_ids=logic_ids,
                extra_logics=extra,
                periods=shards,
                mode=str(args.mode),
                max_codes=int(args.max_codes),
                max_days=cf_max_days,
                seed=int(args.seed),
                worker_url=str(args.worker_url),
                deploy_if_needed=not bool(args.skip_deploy),
                staging_dir=out_dir / "panels_stage_reeval",
            )
        except Exception as exc:
            log(f"[w95] CF reeval failed: {exc}")
            cf_pack = {"status": "error", "error": str(exc), "job_id": job_id}
        _dump(out_dir / "cf_promising_reeval_job.json", cf_pack)

        wr = cf_pack.get("worker_response") or {}
        _cfg = _MFC()
        cf_rows: list[dict[str, Any]] = []
        for w in W95_WINDOWS:
            wid = str(w["window_id"])
            shard_ids = {s["period_id"] for s in w["shards"]}
            for r in wr.get("results") or []:
                lid = str(r.get("logic_id") or "")
                # Tag mom3 binds.
                variant = "bind_mom3" if lid.endswith("__mom3") else "default"
                base_lid = lid.replace("__mom3", "")
                if base_lid not in set(SHAPE_LOGIC_IDS) | set(LEVEL_LOGIC_IDS) | set(
                    ANCHOR_LOGIC_IDS
                ):
                    continue
                reagg = _reaggregate_window_from_period_rows(
                    {**r, "variant": variant, "logic_id": lid},
                    keep_period_ids=shard_ids,
                    near_zero_abs=_cfg.near_zero_abs,
                    min_activation=_cfg.min_activation,
                )
                row = _row(reagg, window_id=wid)
                cf_rows.append(row)

        cf_summary = {
            "wave": "W95 / w0818e",
            "track": "C_promising_few_reeval_cf",
            "job_id": cf_pack.get("job_id") or job_id,
            "status": cf_pack.get("status"),
            "mode": cf_pack.get("mode") or args.mode,
            "version": CF_MASS_EVAL_VERSION,
            "n_survivors_job": cf_pack.get("n_survivors"),
            "n_survivors_window_rows": sum(1 for r in cf_rows if r.get("survived")),
            "excluded": list(EXCLUDED_LOGIC_IDS),
            "include_mom3_binds": include_mom3,
            "rows_flat": cf_rows,
            "markdown_table": _markdown_table(cf_rows),
            "promote_as_main_candidate": False,
            "promotion_note": (
                "Shape logics remain research-only. Surviving window rows are "
                "not auto-promoted to main candidates. 3 defaults frozen. "
                "No smile≡level claim."
            ),
            "mass_research": "NO-GO",
            "operational_go": False,
            "ready_declared": False,
            "frozen_defaults_retuned": False,
        }
        _dump(out_dir / "cf_promising_reeval_summary.json", cf_summary)
        _dump(out_dir / "cf_promising_reeval_table.json", cf_rows)
        (out_dir / "cf_promising_reeval_table.md").write_text(
            "# W95 promising-few CF re-eval\n\n"
            + cf_summary["markdown_table"]
            + "\n",
            encoding="utf-8",
        )
        log(
            f"[w95] CF done status={cf_pack.get('status')} "
            f"job_surv={cf_pack.get('n_survivors')} "
            f"window_surv_rows={cf_summary['n_survivors_window_rows']}"
        )

    summary = {
        "wave": "W95 / w0818e",
        "track": "C_promising_few_reeval",
        "ts": ts,
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "local": {
            "n_survivors": local_pack.get("n_survivors"),
            "table": str(out_dir / "promising_reeval_local_table.md"),
        },
        "cf": {
            "job_id": cf_summary.get("job_id") or cf_pack.get("job_id"),
            "status": cf_summary.get("status") or cf_pack.get("status"),
            "mode": cf_summary.get("mode") or cf_pack.get("mode"),
            "n_survivors_job": cf_summary.get("n_survivors_job")
            or cf_pack.get("n_survivors"),
            "n_survivors_window_rows": cf_summary.get("n_survivors_window_rows"),
            "table": str(out_dir / "cf_promising_reeval_table.md"),
        },
        "excluded_demoted_or_dead": list(EXCLUDED_LOGIC_IDS),
        "promote_as_main_candidate": False,
        "fixed_survivor_count": None,  # deliberately not forced to 2
        "freezes": {
            "mass_research": "NO-GO",
            "phase7": "OFF",
            "ready_declared": False,
            "operational_go": False,
            "continuous_paper": "UNARMED",
            "frozen_defaults_retuned": False,
        },
    }
    _dump(out_dir / "promising_reeval_summary.json", summary)
    log(f"[w95] promising reeval done elapsed={summary['elapsed_sec']}s")
    ok = args.skip_cf or (cf_pack.get("status") in (None, "ok", "partial"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
