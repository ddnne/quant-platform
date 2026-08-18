#!/usr/bin/env python3
"""W94 / w0818d track C — thick-panel rate/flow/fund/mf multi-year window evals.

Consumes W93 thicken sidecars on CF pure-TS:
  * macro_repo_*  ← repo_rate_regime
  * flow_margin_* ← flow_regime (margin ± short)
  * fund_*        ← fund_regime (fins_summary)
  * mf_*          ← fund/flow/repo combination

Missing sidecars → disclosed MDH fallback (`c21_lite_fallback_mdh:…`),
never silent. Same honest windows as W93 (2017–19 / 2020–22 / 2023–25 shards).

Does **not** arm Mass / READY / operational GO / continuous paper / live.
Does **not** retune the three frozen default-path representatives.
TOPIX RV remains **proxy only**.

Examples
--------
    uv run python scripts/run_w94_thick_factor_windows.py \\
        --out-dir .glm-logs/w0818d_w94_opt_skew_thick/

    uv run python scripts/run_w94_thick_factor_windows.py --skip-cf --local-real
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
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

# Same honest window set as W93 (contiguous 3y bars mirrors absent).
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

RATE_LOGIC_IDS: tuple[str, ...] = (
    "macro_repo_rate_change",
    "macro_repo_rate_level",
)
FLOW_LOGIC_IDS: tuple[str, ...] = (
    "flow_margin_pressure",
    "flow_margin_short_hard",
    "flow_margin_short_soft",
)
FUND_LOGIC_IDS: tuple[str, ...] = (
    "fund_value_only",
    "fund_value_mom_agree",
    "fund_value_mom_agree_slow",
)
MF_LOGIC_IDS: tuple[str, ...] = (
    "mf_value_mom_rate",
    "mf_flow_price",
)
# Light bar-native anchors for comparison (not retuned defaults).
ANCHOR_LOGIC_IDS: tuple[str, ...] = (
    "mdh_sticky_momentum",
    "xs_rank_ls_sticky",
)

THICK_FACTOR_LOGIC_IDS: tuple[str, ...] = (
    RATE_LOGIC_IDS + FLOW_LOGIC_IDS + FUND_LOGIC_IDS + MF_LOGIC_IDS + ANCHOR_LOGIC_IDS
)


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8"
    )


def _scalar_f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _scalar_t(v: Any) -> float | None:
    return _scalar_f(v)


def _family_bucket(logic_id: str) -> str:
    lid = str(logic_id or "")
    if lid.startswith("macro_repo_"):
        return "rate"
    if lid.startswith("flow_margin_"):
        return "flow"
    if lid.startswith("fund_"):
        return "fund"
    if lid.startswith("mf_"):
        return "mf"
    return "anchor"


def _compact_row(r: Mapping[str, Any], *, window_id: str | None = None) -> dict[str, Any]:
    scr = r.get("screen") or {}
    lid = str(r.get("logic_id") or r.get("logic") or "")
    out = {
        "logic_id": lid,
        "family_id": r.get("family_id") or r.get("family"),
        "bucket": _family_bucket(lid),
        "status": r.get("status"),
        "mean_net": _scalar_f(r.get("mean_net")),
        "t_stat": _scalar_t(r.get("t_stat") if "t_stat" in r else r.get("t")),
        "sharpe_period": _scalar_f(r.get("sharpe_period")),
        "mean_activation": _scalar_f(
            r.get("mean_activation") if "mean_activation" in r else r.get("act")
        ),
        "chosen_sign": r.get("chosen_sign") if "chosen_sign" in r else r.get("sign"),
        "n_periods_ok": r.get("n_periods_ok"),
        "n_periods_total": r.get("n_periods_total"),
        "survived": bool(scr.get("survived"))
        if "survived" in scr
        else bool(r.get("survived")),
        "reject_reasons": list(
            scr.get("reject_reasons") or r.get("reject_reasons") or []
        ),
        "signal_id_sample": None,
    }
    if window_id is not None:
        out["window"] = window_id
    prows = list(r.get("period_rows") or [])
    if prows:
        out["signal_id_sample"] = prows[0].get("signal_id")
        # Collect distinct signal_ids across periods (disclose MDH fallback).
        sids = sorted(
            {
                str(p.get("signal_id"))
                for p in prows
                if p.get("signal_id")
            }
        )
        out["signal_ids"] = sids
        out["mdh_fallback_periods"] = sum(
            1
            for p in prows
            if str(p.get("signal_id") or "").startswith("c21_lite_fallback_mdh:")
        )
        out["sidecar_consumed_periods"] = sum(
            1
            for p in prows
            if p.get("signal_id")
            and not str(p.get("signal_id")).startswith("c21_lite_fallback_mdh:")
            and p.get("status") == "ok"
        )
    return out


def _markdown_table(rows: Sequence[Mapping[str, Any]]) -> str:
    header = (
        "| window | bucket | logic | mean_net | t | act | sign | survived | "
        "signal_id | mdh_fb |"
    )
    sep = "|---|---|---|---:|---:|---:|---|---|---|---:|"
    lines = [header, sep]
    for r in rows:
        mn, t, act = r.get("mean_net"), r.get("t_stat"), r.get("mean_activation")
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        act_s = f"{act:.4f}" if isinstance(act, float) else "—"
        sign = r.get("chosen_sign")
        sign_s = "—" if sign is None else str(sign)
        sid = r.get("signal_id_sample") or (
            (r.get("signal_ids") or [None])[0] if r.get("signal_ids") else None
        )
        sid_s = str(sid)[:48] if sid else "—"
        mdh = r.get("mdh_fallback_periods")
        mdh_s = str(mdh) if mdh is not None else "—"
        lines.append(
            f"| {r.get('window', '—')} | {r.get('bucket')} | `{r.get('logic_id')}` | "
            f"{mn_s} | {t_s} | {act_s} | {sign_s} | {r.get('survived')} | "
            f"`{sid_s}` | {mdh_s} |"
        )
    return "\n".join(lines)


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
    from research.stats_metrics import sample_mean, t_stat_vs_zero

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
    side_nets = list(side.get("period_nets") or nets)
    mean_net = side.get("mean_net")
    if mean_net is None:
        mean_net = sample_mean(nets)
    mean_gross = sample_mean(grosses)
    t_stat = side.get("t_stat")
    if t_stat is None:
        t_stat = t_stat_vs_zero(side_nets)
    sharpe = side.get("sharpe")

    probe = {
        "strategy_id": result.get("strategy_id"),
        "logic_id": result.get("logic_id"),
        "family_id": result.get("family_id"),
        "status": "evaluated" if ok_rows else "no_ok_periods",
        "mean_gross": mean_gross,
        "mean_net": mean_net,
        "t_stat": t_stat,
        "sharpe_period": sharpe,
        "mean_activation": mean_activation,
        "chosen_sign": chosen_sign,
        "n_periods_ok": len(ok_rows),
        "n_periods_total": len(period_rows),
        "period_rows": period_rows,
        "params": dict(result.get("params") or {}),
        "errors": [],
    }
    scr = screen_strategy_result(
        probe,
        near_zero_abs=near_zero_abs,
        min_activation=min_activation,
    )
    probe["screen"] = scr
    probe["survived"] = bool(scr.get("survived"))
    probe["reject_reasons"] = list(scr.get("reject_reasons") or [])
    return probe


def _run_local_real(
    *,
    logic_ids: Sequence[str],
    periods: Sequence[Mapping[str, Any]],
    max_codes: int,
    max_days: int,
    seed: int,
) -> dict[str, Any]:
    """Optional local factory corroboration on same periods (not CF)."""
    from research.mass_strategy_factory import (
        LOGIC_TEMPLATES,
        MassFactoryConfig,
        evaluate_one_strategy,
        load_batch_data_context,
    )

    cfg = MassFactoryConfig(
        seed=seed,
        n=len(logic_ids),
        max_codes=max_codes,
        max_days_per_period=max_days,
        use_q4_periods=False,
    )
    ctx = load_batch_data_context(cfg, synthetic=False)
    results: list[dict[str, Any]] = []
    for i, lid in enumerate(logic_ids):
        tpl = LOGIC_TEMPLATES.get(lid)
        if tpl is None:
            continue
        strat = {
            "strategy_id": f"msf_w94_{lid}",
            "logic_id": lid,
            "family_id": tpl.family_id,
            "params": dict(tpl.base_params),
            "thesis": tpl.thesis,
            "signal_definition": tpl.signal_definition,
            "position_rule": tpl.position_rule,
            "datasets_used": list(tpl.datasets_used),
            "source": "w94_track_c_local_real",
            "index": i,
        }
        try:
            # Prefer period-filtered eval when ctx supports custom periods.
            out = evaluate_one_strategy(strat, ctx=ctx, config=cfg)
            if periods:
                # Re-screen over requested shards only when period_rows present.
                keep = {str(p.get("period_id")) for p in periods}
                out = _reaggregate_window_from_period_rows(
                    out,
                    keep_period_ids=keep,
                    near_zero_abs=cfg.near_zero_abs,
                    min_activation=cfg.min_activation,
                )
            results.append(out)
        except Exception as exc:  # pragma: no cover - best effort
            results.append(
                {
                    "logic_id": lid,
                    "status": "error",
                    "error": str(exc),
                    "survived": False,
                }
            )
    return {
        "status": "ok",
        "n_logics": len(results),
        "results": results,
        "source": "local_factory",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="W94: thick-panel rate/flow/fund/mf multi-year window evals"
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
        choices=["r2_panels", "d1_bars", "synthetic", "nets_only"],
    )
    p.add_argument("--skip-cf", action="store_true")
    p.add_argument("--skip-deploy", action="store_true")
    p.add_argument("--local-real", action="store_true")
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=120)
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

    from research.cf_mass_eval_job import (
        CF_MASS_EVAL_VERSION,
        CF_MASS_EVAL_WAVE,
        THICKEN_PANEL_DATASETS,
        build_real_period_panel,
        inventory_cf_panel_wiring,
        inventory_complete22,
        run_cf_mass_eval_job,
        try_cf_mass_eval_status,
    )
    from research.mass_strategy_factory import (
        CONTINUOUS_PAPER,
        FROZEN_DEFAULT_PATH,
        MASS_RESEARCH,
        MassFactoryConfig,
        PHASE7,
    )

    job_id = f"w94-thick-{ts}"
    mode = str(args.mode)
    shards: list[dict[str, Any]] = []
    for w in W94_WINDOWS:
        for s in w["shards"]:
            shards.append(dict(s))

    log(f"[w94] wave={CF_MASS_EVAL_WAVE} version={CF_MASS_EVAL_VERSION}")
    log(f"[w94] job_id={job_id} mode={mode} out={out_dir}")
    log(
        f"[w94] logics rate={list(RATE_LOGIC_IDS)} flow={list(FLOW_LOGIC_IDS)} "
        f"fund={list(FUND_LOGIC_IDS)} mf={list(MF_LOGIC_IDS)}"
    )
    log(f"[w94] freezes: mass={MASS_RESEARCH} paper={CONTINUOUS_PAPER} phase7={PHASE7}")

    # ------------------------------------------------------------------ A. wiring
    inv22 = inventory_complete22()
    wiring = inventory_cf_panel_wiring()
    _dump(out_dir / "complete22_inventory.json", inv22)
    _dump(out_dir / "cf_wiring_inventory.json", wiring)
    log(
        f"[w94] A: wiring counts={wiring.get('status_counts')} "
        f"thicken={wiring.get('thicken_panel_datasets')}"
    )
    for ds in (
        "jsda_tokyo_repo_rates",
        "markets_margin_interest",
        "markets_short_ratio",
        "fins_summary",
    ):
        row = (wiring.get("datasets") or {}).get(ds) or {}
        log(f"  · {ds}: {row.get('status')}")

    # ------------------------------------------------------------------ B. sample panel
    sample = build_real_period_panel(
        dict(shards[0]),
        max_codes=int(args.max_codes),
        max_days=min(60, int(args.max_days)),
    )
    sample_meta = {
        k: sample.get(k)
        for k in (
            "period_id",
            "status",
            "n_codes",
            "n_days",
            "source",
            "panel_thicken",
            "thicken_counts",
            "thicken_done",
            "thicken_status",
            "thicken_consumed_on_cf",
            "thicken_todo",
        )
    }
    sample_meta["repo_n_rates"] = (sample.get("repo_rate_regime") or {}).get(
        "n_rates"
    )
    sample_meta["flow_n_codes"] = (sample.get("flow_regime") or {}).get("n_codes")
    sample_meta["fund_n_events"] = (sample.get("fund_regime") or {}).get(
        "n_events"
    )
    _dump(out_dir / "sample_thickened_panel_meta.json", sample_meta)
    log(
        f"[w94] B: sample {sample_meta.get('period_id')} "
        f"status={sample_meta.get('status')} "
        f"repo={sample_meta.get('repo_n_rates')} "
        f"flow={sample_meta.get('flow_n_codes')} "
        f"fund_events={sample_meta.get('fund_n_events')}"
    )

    _dump(
        out_dir / "window_definitions.json",
        {
            "wave": CF_MASS_EVAL_WAVE,
            "windows": [dict(w) for w in W94_WINDOWS],
            "logic_ids": list(THICK_FACTOR_LOGIC_IDS),
            "buckets": {
                "rate": list(RATE_LOGIC_IDS),
                "flow": list(FLOW_LOGIC_IDS),
                "fund": list(FUND_LOGIC_IDS),
                "mf": list(MF_LOGIC_IDS),
                "anchor": list(ANCHOR_LOGIC_IDS),
            },
        },
    )

    # ------------------------------------------------------------------ C. CF job
    cf_pack: dict[str, Any] = {}
    cf_status = try_cf_mass_eval_status()
    _dump(out_dir / "cf_status_pre.json", cf_status)
    job_ids: list[str] = []

    if not args.skip_cf:
        log(
            f"[w94] C: CF mass-eval job_id={job_id} mode={mode} "
            f"thicken={list(THICKEN_PANEL_DATASETS)} n_logics={len(THICK_FACTOR_LOGIC_IDS)} "
            f"n_shards={len(shards)}"
        )
        try:
            cf_pack = run_cf_mass_eval_job(
                job_id=job_id,
                logic_ids=list(THICK_FACTOR_LOGIC_IDS),
                periods=shards,
                mode=mode,
                max_codes=int(args.max_codes),
                max_days=min(int(args.max_days), 120),
                seed=int(args.seed),
                worker_url=str(args.worker_url),
                deploy_if_needed=not bool(args.skip_deploy),
                dry_run_r2=bool(args.dry_run_r2),
                staging_dir=out_dir / "panels_stage" if args.dry_run_r2 else None,
                stage_panels=(mode == "r2_panels"),
            )
        except Exception as exc:
            log(f"[w94] C CF job failed: {exc}")
            cf_pack = {
                "status": "error",
                "error": str(exc),
                "job_id": job_id,
                "mode": mode,
            }
        _dump(out_dir / "cf_mass_eval_job.json", cf_pack)
        jid = str(cf_pack.get("job_id") or job_id)
        job_ids.append(jid)
        wr = cf_pack.get("worker_response") or {}
        if not wr and isinstance(cf_pack.get("results"), list):
            wr = cf_pack
        if wr:
            _dump(out_dir / "cf_mass_eval_response.json", wr)

        cfg = MassFactoryConfig()
        window_tables: list[dict[str, Any]] = []
        rows_flat: list[dict[str, Any]] = []
        signal_counter: Counter[str] = Counter()
        mdh_counter: Counter[str] = Counter()

        for w in W94_WINDOWS:
            wid = str(w["window_id"])
            shard_ids = {s["period_id"] for s in w["shards"]}
            buckets: dict[str, list] = {
                "rate": [],
                "flow": [],
                "fund": [],
                "mf": [],
                "anchor": [],
            }
            for r in wr.get("results") or []:
                lid = str(r.get("logic_id") or "")
                if not lid:
                    continue
                reagg = _reaggregate_window_from_period_rows(
                    r,
                    keep_period_ids=shard_ids,
                    near_zero_abs=cfg.near_zero_abs,
                    min_activation=cfg.min_activation,
                )
                row = _compact_row(reagg, window_id=wid)
                # Prefer full-job signal ids from original result period rows
                # filtered to this window.
                orig_prows = [
                    p
                    for p in (r.get("period_rows") or [])
                    if str(p.get("period_id") or "") in shard_ids
                ]
                sids = sorted(
                    {
                        str(p.get("signal_id"))
                        for p in orig_prows
                        if p.get("signal_id")
                    }
                )
                row["signal_ids"] = sids
                row["signal_id_sample"] = sids[0] if sids else None
                row["mdh_fallback_periods"] = sum(
                    1
                    for p in orig_prows
                    if str(p.get("signal_id") or "").startswith(
                        "c21_lite_fallback_mdh:"
                    )
                )
                row["sidecar_consumed_periods"] = sum(
                    1
                    for p in orig_prows
                    if p.get("signal_id")
                    and not str(p.get("signal_id")).startswith(
                        "c21_lite_fallback_mdh:"
                    )
                    and p.get("status") == "ok"
                )
                for sid in sids:
                    signal_counter[sid] += 1
                    if sid.startswith("c21_lite_fallback_mdh:"):
                        mdh_counter[sid] += 1
                buckets[row["bucket"]].append(row)
                rows_flat.append(row)

            window_tables.append(
                {
                    "window_id": wid,
                    "label": w["label"],
                    "data_note": w["data_note"],
                    "shard_ids": sorted(shard_ids),
                    "n_survivors": sum(1 for r in rows_flat if r.get("window") == wid and r.get("survived")),
                    **{k: v for k, v in buckets.items()},
                }
            )

        by_bucket_all = {
            b: [r for r in rows_flat if r.get("bucket") == b]
            for b in ("rate", "flow", "fund", "mf", "anchor")
        }
        cf_window_summary = {
            "wave": CF_MASS_EVAL_WAVE,
            "version": CF_MASS_EVAL_VERSION,
            "track": "C_thick_factor_windows",
            "job_id": jid,
            "job_ids": list(job_ids),
            "status": cf_pack.get("status"),
            "mode": cf_pack.get("mode") or mode,
            "n_survivors": cf_pack.get("n_survivors"),
            "n_logics": cf_pack.get("n_logics"),
            "n_periods": cf_pack.get("n_periods"),
            "r2_prefix": cf_pack.get("r2_prefix")
            or (cf_pack.get("artifact_paths") or {}).get("prefix"),
            "stage_panels": {
                "n_ok": (cf_pack.get("stage_panels") or {}).get("n_ok"),
                "n_periods": (cf_pack.get("stage_panels") or {}).get("n_periods"),
                "panels_prefix": (cf_pack.get("stage_panels") or {}).get(
                    "panels_prefix"
                ),
            },
            "window_tables": window_tables,
            "rows_flat": rows_flat,
            "by_bucket": {
                k: [_compact_row(r) for r in v] for k, v in by_bucket_all.items()
            },
            "signal_id_counts": dict(signal_counter),
            "mdh_fallback_counts": dict(mdh_counter),
            "markdown_table": _markdown_table(rows_flat),
            "thicken_panel_datasets": list(THICKEN_PANEL_DATASETS),
            "mdh_fallback_policy": (
                "Missing thicken sidecar → signal_id "
                "c21_lite_fallback_mdh:<family>; never silent."
            ),
            "freezes": {
                "mass_research": MASS_RESEARCH,
                "phase7": PHASE7,
                "ready_declared": False,
                "operational_go": False,
                "continuous_paper": CONTINUOUS_PAPER,
                "frozen_defaults_retuned": False,
            },
        }
        _dump(out_dir / "cf_window_summary.json", cf_window_summary)
        _dump(out_dir / "cf_window_table.json", {"rows": rows_flat})
        (out_dir / "cf_window_table.md").write_text(
            "# W94 thick-factor CF window table\n\n"
            + cf_window_summary["markdown_table"]
            + "\n",
            encoding="utf-8",
        )
        for bucket in ("rate", "flow", "fund", "mf"):
            brows = by_bucket_all[bucket]
            _dump(
                out_dir / f"cf_{bucket}_table.json",
                {"bucket": bucket, "rows": brows},
            )
            (out_dir / f"cf_{bucket}_table.md").write_text(
                f"# W94 CF {bucket} window table\n\n"
                + _markdown_table(brows)
                + "\n",
                encoding="utf-8",
            )
            log(f"[w94] C table {bucket}: n={len(brows)}")
            for r in brows:
                log(
                    f"  · {r.get('window')} {r.get('logic_id')}: "
                    f"net={r.get('mean_net')} t={r.get('t_stat')} "
                    f"surv={r.get('survived')} sid={r.get('signal_id_sample')} "
                    f"mdh_fb={r.get('mdh_fallback_periods')}"
                )

        log(
            f"[w94] C done · status={cf_pack.get('status')} "
            f"job_id={jid} n_survivors={cf_pack.get('n_survivors')} "
            f"signal_ids={dict(signal_counter)} "
            f"mdh_fb={dict(mdh_counter)}"
        )
        try:
            st = try_cf_mass_eval_status()
            st = {**st, "job_id": jid, "worker_url": args.worker_url}
            _dump(out_dir / "cf_status.json", st)
        except Exception as exc:
            _dump(out_dir / "cf_status.json", {"error": str(exc), "job_id": jid})
    else:
        log("[w94] C: CF skipped")

    # ------------------------------------------------------------------ D. optional local
    local_pack: dict[str, Any] = {}
    if args.local_real:
        log("[w94] D: local real corroboration")
        try:
            local_pack = _run_local_real(
                logic_ids=list(THICK_FACTOR_LOGIC_IDS),
                periods=shards,
                max_codes=int(args.max_codes),
                max_days=min(int(args.max_days), 80),
                seed=int(args.seed),
            )
        except Exception as exc:
            log(f"[w94] D local failed: {exc}")
            local_pack = {"status": "error", "error": str(exc)}
        _dump(out_dir / "local_real_eval.json", local_pack)
        local_rows = [
            _compact_row(r) for r in (local_pack.get("results") or [])
        ]
        _dump(out_dir / "local_real_table.json", {"rows": local_rows})
        (out_dir / "local_real_table.md").write_text(
            "# W94 local real thick-factor table\n\n"
            + _markdown_table(
                [{**r, "window": "all_shards"} for r in local_rows]
            )
            + "\n",
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ summary
    primary = "cf_r2_panels" if (cf_pack and cf_pack.get("status") in {"ok", "completed", "success"}) else (
        "local_real" if local_pack else "cf_skipped_or_failed"
    )
    summary = {
        "wave": CF_MASS_EVAL_WAVE,
        "version": CF_MASS_EVAL_VERSION,
        "track": "C_thick_factor_windows",
        "job_ids": job_ids,
        "mode": mode,
        "status": cf_pack.get("status") if cf_pack else "cf_skipped",
        "primary_source": primary,
        "wiring_counts": wiring.get("status_counts"),
        "sample_panel": sample_meta,
        "n_logics": cf_pack.get("n_logics") if cf_pack else len(THICK_FACTOR_LOGIC_IDS),
        "n_periods": cf_pack.get("n_periods") if cf_pack else len(shards),
        "n_survivors": cf_pack.get("n_survivors"),
        "windows": [w["window_id"] for w in W94_WINDOWS],
        "logic_buckets": {
            "rate": list(RATE_LOGIC_IDS),
            "flow": list(FLOW_LOGIC_IDS),
            "fund": list(FUND_LOGIC_IDS),
            "mf": list(MF_LOGIC_IDS),
            "anchor": list(ANCHOR_LOGIC_IDS),
        },
        "thicken_panel_datasets": list(THICKEN_PANEL_DATASETS),
        "mdh_fallback_policy": (
            "Missing thicken sidecar → c21_lite_fallback_mdh:<family>; never silent."
        ),
        "freezes": {
            "mass_research": MASS_RESEARCH,
            "phase7": PHASE7,
            "ready_declared": False,
            "operational_go": False,
            "continuous_paper": CONTINUOUS_PAPER,
            "frozen_defaults_retuned": False,
            "frozen_default_path": [
                (
                    r.get("representative_id")
                    if isinstance(r, dict)
                    else str(r)
                )
                for r in (
                    FROZEN_DEFAULT_PATH.values()
                    if isinstance(FROZEN_DEFAULT_PATH, dict)
                    else list(FROZEN_DEFAULT_PATH)
                )
            ],
            "topix_proxy_only": True,
        },
        "elapsed_sec": round(time.perf_counter() - t0, 3),
        "ts": ts,
        "note": (
            "W94 track C: CF pure-TS rate/flow/fund/mf consume W93 thicken "
            "sidecars on r2_panels. TOPIX proxy only. Mass/READY/ops GO closed. "
            "3 defaults frozen."
        ),
    }
    _dump(out_dir / "w94_summary.json", summary)
    (out_dir / "SUMMARY.md").write_text(
        "\n".join(
            [
                "# W94 / w0818d track C — thick-factor windows",
                "",
                f"**Wave:** {CF_MASS_EVAL_WAVE}",
                f"**Version:** {CF_MASS_EVAL_VERSION}",
                f"**Job IDs:** {', '.join(job_ids) or '—'}",
                f"**Mode:** {mode}",
                f"**Status:** {summary['status']}",
                f"**Primary:** {primary}",
                f"**Survivors:** {summary.get('n_survivors')}",
                "",
                "## Freezes held",
                "",
                "- Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言",
                "- continuous paper UNARMED · 3 defaults not retuned",
                "- TOPIX proxy only",
                "",
                "## MDH fallback policy",
                "",
                summary["mdh_fallback_policy"],
                "",
                f"See `cf_window_table.md` and `cf_{{rate,flow,fund,mf}}_table.md`.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    log(
        f"[w94] done · elapsed={summary['elapsed_sec']:.1f}s · out={out_dir} "
        f"job_ids={job_ids} primary={primary}"
    )
    ok = args.skip_cf or summary["status"] in {"ok", "completed", "success"}
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
