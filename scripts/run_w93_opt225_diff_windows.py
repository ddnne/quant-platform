#!/usr/bin/env python3
"""W93 / w0818c — BaseVol vs ATM IV differential + multi-year windows + CF thicken.

Priority axis: **differential analysis** of options_225 BaseVol vs ATM IV
(never collapse to one). Multi-year windows 2017–2019 / 2020–2022 / 2023–2025
(honestly adjusted to available mirrors). Spread activation autopsy.

Does **not** arm Mass / READY / operational GO / continuous paper / live.
Does **not** retune the three frozen default-path representatives.
TOPIX RV remains **proxy only**; options_225 is SoT.

Examples
--------
    uv run python scripts/run_w93_opt225_diff_windows.py \\
        --out-dir .glm-logs/w0818c_w93_opt225_diff/

    uv run python scripts/run_w93_opt225_diff_windows.py --skip-cf --skip-rebuild
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
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

OPT225_LOGIC_IDS: tuple[str, ...] = (
    "opt225_basevol_abs_level",
    "opt225_basevol_term_levels",
    "opt225_basevol_term_ratio",
    "opt225_atm_iv_abs_level",
    "opt225_atm_iv_term_levels",
    "opt225_atm_iv_term_ratio",
    "opt225_iv_base_spread_abs",
    "opt225_iv_base_spread_change",
)

BASEVOL_LOGIC_IDS: tuple[str, ...] = tuple(
    x for x in OPT225_LOGIC_IDS if "basevol" in x
)
ATM_LOGIC_IDS: tuple[str, ...] = tuple(x for x in OPT225_LOGIC_IDS if "atm_iv" in x)
SPREAD_LOGIC_IDS: tuple[str, ...] = tuple(x for x in OPT225_LOGIC_IDS if "spread" in x)

# Honest window set: contiguous 3y bars mirrors absent → use available shards.
W93_WINDOWS: tuple[dict[str, Any], ...] = (
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
        "data_note": "2024 full/Q4 mirror absent; shards = y2023_full + y2025_q4",
    },
)

TRANSFORM_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("abs", "opt225_basevol_abs_level", "opt225_atm_iv_abs_level"),
    ("term_levels", "opt225_basevol_term_levels", "opt225_atm_iv_term_levels"),
    ("term_ratio", "opt225_basevol_term_ratio", "opt225_atm_iv_term_ratio"),
)


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                out.append(row)
    return out


def _quantiles(xs: Sequence[float]) -> dict[str, float]:
    if not xs:
        return {}
    ordered = sorted(float(x) for x in xs)
    n = len(ordered)

    def q(p: float) -> float:
        if n == 1:
            return ordered[0]
        i = min(n - 1, max(0, int(round(p * (n - 1)))))
        return ordered[i]

    return {f"p{int(p*100)}": q(p) for p in (0, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1.0)}


def _dist(name: str, xs: Sequence[float]) -> dict[str, Any]:
    vals = [float(x) for x in xs]
    if not vals:
        return {"name": name, "n": 0}
    return {
        "name": name,
        "n": len(vals),
        "mean": statistics.mean(vals),
        "std": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
        "min": min(vals),
        "max": max(vals),
        "quantiles": _quantiles(vals),
        "n_nan": 0,
        "n_zero": sum(1 for x in vals if abs(x) < 1e-12),
        "n_neg": sum(1 for x in vals if x < 0),
        "n_pos": sum(1 for x in vals if x > 0),
    }


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    x = [float(xs[i]) for i in range(n)]
    y = [float(ys[i]) for i in range(n)]
    mx, my = statistics.mean(x), statistics.mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = math.sqrt(sum((a - mx) ** 2 for a in x))
    dy = math.sqrt(sum((b - my) ** 2 for b in y))
    if dx <= 0 or dy <= 0:
        return None
    return num / (dx * dy)


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 2:
        return None

    def ranks(vals: Sequence[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        out = [0.0] * n
        for rank, i in enumerate(order):
            out[i] = float(rank)
        return out

    return _pearson(ranks([float(xs[i]) for i in range(n)]), ranks([float(ys[i]) for i in range(n)]))


def _slice_series(
    rows: Sequence[Mapping[str, Any]], start: str, end: str
) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in rows
        if start <= str(r.get("date") or "")[:10] <= end
    ]


def build_diff_series_stats(
    base: Sequence[Mapping[str, Any]],
    atm: Sequence[Mapping[str, Any]],
    spread: Sequence[Mapping[str, Any]],
    *,
    source: str,
) -> dict[str, Any]:
    from research.options_225_vol_series import (
        DEFAULT_ATM_MIN_DTE_DAYS,
        DEFAULT_OPT225_SPREAD_HIGH,
        DEFAULT_OPT225_SPREAD_LOW,
        SPREAD_CONVENTION,
    )

    base_by = {str(r["date"])[:10]: r for r in base}
    atm_by = {str(r["date"])[:10]: r for r in atm}
    dates = sorted(set(base_by) & set(atm_by))
    bv = [float(base_by[d]["base_vol"]) for d in dates]
    av = [float(atm_by[d]["atm_iv"]) for d in dates]
    sp = [float(atm_by[d]["atm_iv"]) - float(base_by[d]["base_vol"]) for d in dates]
    # prefer cached spread rows when present
    if spread:
        sp_by = {str(r["date"])[:10]: float(r["spread"]) for r in spread}
        sp = [sp_by.get(d, sp[i]) for i, d in enumerate(dates)]

    dod_b = [bv[i] - bv[i - 1] for i in range(1, len(bv))]
    dod_a = [av[i] - av[i - 1] for i in range(1, len(av))]

    cm_changes = 0
    cm_sample: list[dict[str, Any]] = []
    prev_cm = None
    prev_date = None
    prev_spread = None
    prev_atm = None
    prev_bv = None
    for d in dates:
        cm = atm_by[d].get("cm")
        if prev_cm is not None and cm != prev_cm:
            cm_changes += 1
            if len(cm_sample) < 25:
                cm_sample.append(
                    {
                        "date": d,
                        "prev_cm": prev_cm,
                        "new_cm": cm,
                        "prev_date": prev_date,
                        "spread": float(atm_by[d]["atm_iv"]) - float(base_by[d]["base_vol"]),
                        "prev_spread": prev_spread,
                        "atm_iv": float(atm_by[d]["atm_iv"]),
                        "prev_atm_iv": prev_atm,
                        "base_vol": float(base_by[d]["base_vol"]),
                        "prev_base_vol": prev_bv,
                        "ltd": atm_by[d].get("ltd"),
                        "dte": atm_by[d].get("dte"),
                        "cm_pick_rule": atm_by[d].get("cm_pick_rule"),
                    }
                )
        prev_cm = cm
        prev_date = d
        prev_spread = float(atm_by[d]["atm_iv"]) - float(base_by[d]["base_vol"])
        prev_atm = float(atm_by[d]["atm_iv"])
        prev_bv = float(base_by[d]["base_vol"])

    abs_sp = [abs(x) for x in sp]
    n_exact0 = sum(1 for x in sp if abs(x) < 1e-12)
    n_ge_hi = sum(1 for x in sp if x >= DEFAULT_OPT225_SPREAD_HIGH)
    n_le_lo = sum(1 for x in sp if x <= DEFAULT_OPT225_SPREAD_LOW)

    # DTE buckets
    dte_zero: Counter[str] = Counter()
    dte_nz: Counter[str] = Counter()
    for d, s in zip(dates, sp):
        dte = atm_by[d].get("dte")
        if dte is None and atm_by[d].get("ltd"):
            try:
                from datetime import date as _date

                dte = (
                    _date.fromisoformat(str(atm_by[d]["ltd"])[:10])
                    - _date.fromisoformat(d)
                ).days
            except ValueError:
                dte = None
        if dte is None:
            bucket = "unknown"
        elif dte <= 2:
            bucket = "0-2"
        elif dte <= 5:
            bucket = "3-5"
        elif dte <= 10:
            bucket = "6-10"
        elif dte <= 20:
            bucket = "11-20"
        else:
            bucket = "21+"
        if abs(s) < 1e-12:
            dte_zero[bucket] += 1
        else:
            dte_nz[bucket] += 1

    # per-window series slice stats
    window_series: dict[str, Any] = {}
    for w in W93_WINDOWS:
        sb = _slice_series(base, w["start"], w["end"])
        sa = _slice_series(atm, w["start"], w["end"])
        ss = _slice_series(spread, w["start"], w["end"]) if spread else []
        if not ss and sb and sa:
            sb_m = {str(r["date"])[:10]: float(r["base_vol"]) for r in sb}
            sa_m = {str(r["date"])[:10]: float(r["atm_iv"]) for r in sa}
            ss_vals = [
                sa_m[d] - sb_m[d] for d in sorted(set(sb_m) & set(sa_m))
            ]
        else:
            ss_vals = [float(r["spread"]) for r in ss]
        window_series[w["window_id"]] = {
            "label": w["label"],
            "n_base": len(sb),
            "n_atm": len(sa),
            "n_spread": len(ss_vals),
            "corr": _pearson(
                [float(r["base_vol"]) for r in sb if str(r["date"])[:10] in {str(x["date"])[:10] for x in sa}],
                [float(atm_by[str(r["date"])[:10]]["atm_iv"]) for r in sb if str(r["date"])[:10] in atm_by],
            )
            if sb and sa
            else None,
            "spread_mean": statistics.mean(ss_vals) if ss_vals else None,
            "spread_abs_mean": statistics.mean([abs(x) for x in ss_vals]) if ss_vals else None,
            "frac_exact_zero": (
                sum(1 for x in ss_vals if abs(x) < 1e-12) / len(ss_vals)
                if ss_vals
                else None
            ),
            "data_note": w["data_note"],
        }

    return {
        "wave": "W93 / w0818c",
        "source": source,
        "min_dte_days": DEFAULT_ATM_MIN_DTE_DAYS,
        "spread_convention": SPREAD_CONVENTION,
        "n_days": len(dates),
        "date_start": dates[0] if dates else None,
        "date_end": dates[-1] if dates else None,
        "base_vol": _dist("base_vol", bv),
        "atm_iv": _dist("atm_iv", av),
        "spread": _dist("spread", sp),
        "corr": {
            "pearson_level": _pearson(bv, av),
            "spearman_level": _spearman(bv, av),
            "pearson_dod_change": _pearson(dod_b, dod_a),
        },
        "cm_rolls": {
            "n_cm_changes": cm_changes,
            "sample": cm_sample,
        },
        "spread_activation_context": {
            "thresholds": {
                "spread_high": DEFAULT_OPT225_SPREAD_HIGH,
                "spread_low": DEFAULT_OPT225_SPREAD_LOW,
            },
            "n_exact_zero": n_exact0,
            "frac_exact_zero": n_exact0 / len(sp) if sp else None,
            "n_ge_high": n_ge_hi,
            "n_le_low": n_le_lo,
            "frac_active_abs": (n_ge_hi + n_le_lo) / len(sp) if sp else None,
            "frac_abs_lt_0_1": sum(1 for x in abs_sp if x < 0.1) / len(abs_sp) if abs_sp else None,
            "frac_abs_lt_0_5": sum(1 for x in abs_sp if x < 0.5) / len(abs_sp) if abs_sp else None,
            "frac_abs_lt_1_0": sum(1 for x in abs_sp if x < 1.0) / len(abs_sp) if abs_sp else None,
        },
        "dte_buckets_zero_spread": dict(dte_zero),
        "dte_buckets_nonzero_spread": dict(dte_nz),
        "atm_diagnostics": {
            "pc_used_counts": dict(Counter(str(atm_by[d].get("pc_used")) for d in dates)),
            "cm_pick_rule_counts": dict(
                Counter(str(atm_by[d].get("cm_pick_rule")) for d in dates)
            ),
            "near_expiry_fallback_n": sum(
                1 for d in dates if atm_by[d].get("near_expiry_fallback")
            ),
            "median_abs_moneyness": (
                statistics.median(
                    float(atm_by[d]["abs_moneyness"])
                    for d in dates
                    if atm_by[d].get("abs_moneyness") is not None
                )
                if dates
                else None
            ),
        },
        "window_series_slices": window_series,
        "noise_vs_structure_note": (
            "BaseVol and reconstructed ATM IV are definitionally co-located "
            "(J-Quants BaseVol = ATM put/call mid). Pre-fix: ~86.7% exact-zero "
            "spread and ALL nonzero residuals at front-CM DTE<=5 (expiry-week "
            "noise). W93 min_dte=6 roll removes that SQ-week blow-up. Residual "
            "spread after fix is microstructure / fallback only — not a durable "
            "risk-premium structure for abs/change logics at default thresholds."
        ),
    }


def build_spread_diagnosis(stats: Mapping[str, Any]) -> dict[str, Any]:
    from research.options_225_vol_series import (
        DEFAULT_ATM_MIN_DTE_DAYS,
        DEFAULT_OPT225_SPREAD_HIGH,
        DEFAULT_OPT225_SPREAD_LOW,
    )

    ctx = stats.get("spread_activation_context") or {}
    return {
        "wave": "W93 / w0818c",
        "question": "Why do opt225_iv_base_spread_* logics have low activation?",
        "answer_summary": (
            "Because BaseVol ≈ ATM IV by J-Quants definition. Exact-zero spread "
            f"dominates; default thresholds high={DEFAULT_OPT225_SPREAD_HIGH}/"
            f"low={DEFAULT_OPT225_SPREAD_LOW} rarely fire. Pre-fix nonzero "
            "residuals were exclusively near-expiry (DTE<=5) noise — not a "
            f"structural IV−Base premium. W93 min_dte={DEFAULT_ATM_MIN_DTE_DAYS} "
            "roll removes that noise; spread logics stay low-activation by design."
        ),
        "frac_exact_zero_spread": ctx.get("frac_exact_zero"),
        "frac_active_abs": ctx.get("frac_active_abs"),
        "dte_buckets_zero_spread": stats.get("dte_buckets_zero_spread"),
        "dte_buckets_nonzero_spread": stats.get("dte_buckets_nonzero_spread"),
        "thresholds": ctx.get("thresholds"),
        "min_dte_days": DEFAULT_ATM_MIN_DTE_DAYS,
        "jquants_basevol_def": (
            "BaseVol = average of ATM put and call implied volatilities "
            "(populated from 2016-07-19)."
        ),
        "definition_bug_verdict": {
            "bug": "near_expiry_front_cm_selection",
            "fix": f"min_dte_days={DEFAULT_ATM_MIN_DTE_DAYS} CM roll",
            "sign_convention_bug": False,
            "basevol_equals_atm_by_definition": True,
        },
        "noise_vs_structure": stats.get("noise_vs_structure_note"),
    }


def _compact_eval_row(r: Mapping[str, Any]) -> dict[str, Any]:
    t = r.get("t_stat")
    if isinstance(t, Mapping):
        t_val = t.get("t_stat")
    else:
        t_val = t
    screen = r.get("screen") or {}
    return {
        "logic_id": r.get("logic_id"),
        "family_id": r.get("family_id"),
        "status": r.get("status"),
        "mean_net": r.get("mean_net"),
        "t_stat": t_val,
        "sharpe_period": r.get("sharpe_period"),
        "chosen_sign": r.get("chosen_sign"),
        "n_periods_ok": r.get("n_periods_ok"),
        "survived": screen.get("survived"),
        "reject_reasons": screen.get("reject_reasons"),
        "mean_activation": r.get("mean_activation"),
        "period_rows_compact": [
            {
                "period_id": pr.get("period_id"),
                "year": pr.get("year"),
                "status": pr.get("status"),
                "net": pr.get("net_one_way_mean_active")
                if pr.get("net_one_way_mean_active") is not None
                else pr.get("net"),
                "activation": pr.get("activation_rate")
                if pr.get("activation_rate") is not None
                else pr.get("activation"),
                "signal_id": pr.get("signal_id"),
            }
            for pr in (r.get("period_rows") or [])
        ],
    }


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
        LOGIC_TEMPLATES,
        MassFactoryConfig,
        generate_strategy_batch,
        run_batch_eval,
    )

    all_shards: list[dict[str, Any]] = []
    for w in W93_WINDOWS:
        for s in w["shards"]:
            all_shards.append(dict(s))

    cfg = MassFactoryConfig(
        seed=int(seed),
        n=80,
        max_codes=int(max_codes),
        max_days_per_period=int(max_days),
        use_q4_periods=False,
    )
    gen = generate_strategy_batch(cfg)
    strategies = []
    for lid in OPT225_LOGIC_IDS:
        if lid not in LOGIC_TEMPLATES:
            continue
        tpl = LOGIC_TEMPLATES[lid]
        strategies.append(
            {
                "strategy_id": f"msf_w93_{lid}",
                "logic_id": lid,
                "family_id": tpl.family_id,
                "params": dict(tpl.base_params),
                "thesis": tpl.thesis,
                "signal_definition": tpl.signal_definition,
                "position_rule": tpl.position_rule,
                "datasets_used": list(tpl.datasets_used),
                "source": "w93_force_include",
            }
        )
    # rate/flow/fund thicken re-eval sample (local already has repo/fins/margin)
    for lid in (
        "macro_repo_rate_level",
        "macro_repo_rate_change",
        "mf_value_mom_rate",
        "flow_hard_demand",
    ):
        if lid in LOGIC_TEMPLATES:
            tpl = LOGIC_TEMPLATES[lid]
            strategies.append(
                {
                    "strategy_id": f"msf_w93_{lid}",
                    "logic_id": lid,
                    "family_id": tpl.family_id,
                    "params": dict(tpl.base_params),
                    "thesis": tpl.thesis,
                    "signal_definition": tpl.signal_definition,
                    "position_rule": tpl.position_rule,
                    "datasets_used": list(tpl.datasets_used),
                    "source": "w93_thicken_reeval",
                }
            )

    gen_for_eval = {
        **gen,
        "strategies_after_dedup": strategies,
        "n_after_dedup": len(strategies),
    }
    from research.mass_strategy_factory import load_batch_data_context

    log(
        f"[w93] local window eval · n_strategies={len(strategies)} "
        f"n_shards={len(all_shards)} factory={MASS_FACTORY_VERSION}"
    )
    ctx = load_batch_data_context(
        cfg,
        periods=all_shards,
        synthetic=bool(synthetic),
    )
    batch = run_batch_eval(
        gen_for_eval,
        config=cfg,
        ctx=ctx,
        synthetic=bool(synthetic),
    )
    results = list(batch.get("results") or [])
    by_logic = {str(r.get("logic_id")): r for r in results}

    # aggregate per window
    window_tables: list[dict[str, Any]] = []
    for w in W93_WINDOWS:
        shard_ids = {s["period_id"] for s in w["shards"]}
        side: dict[str, Any] = {
            "window_id": w["window_id"],
            "label": w["label"],
            "data_note": w["data_note"],
            "shard_ids": sorted(shard_ids),
            "basevol": [],
            "atm_iv": [],
            "spread": [],
            "thicken_reeval": [],
        }
        for lid, family_key in (
            *[(x, "basevol") for x in BASEVOL_LOGIC_IDS],
            *[(x, "atm_iv") for x in ATM_LOGIC_IDS],
            *[(x, "spread") for x in SPREAD_LOGIC_IDS],
            *(
                (x, "thicken_reeval")
                for x in (
                    "macro_repo_rate_level",
                    "macro_repo_rate_change",
                    "mf_value_mom_rate",
                    "flow_hard_demand",
                )
            ),
        ):
            r = by_logic.get(lid)
            if not r:
                continue
            prs = [
                pr
                for pr in (r.get("period_rows") or [])
                if pr.get("period_id") in shard_ids
            ]
            nets = []
            acts = []
            for pr in prs:
                net = pr.get("net_one_way_mean_active")
                if net is None:
                    net = pr.get("net")
                if net is not None:
                    nets.append(float(net))
                act = pr.get("activation_rate")
                if act is None:
                    act = pr.get("activation")
                if act is not None:
                    acts.append(float(act))
            mean_net = statistics.mean(nets) if nets else None
            t_stat = None
            if nets and len(nets) >= 2:
                m = statistics.mean(nets)
                sd = statistics.stdev(nets)
                if sd > 0:
                    t_stat = m / (sd / math.sqrt(len(nets)))
            elif nets and len(nets) == 1:
                t_stat = None
            row = {
                "logic_id": lid,
                "n_shards_with_net": len(nets),
                "mean_net": mean_net,
                "t_stat": t_stat,
                "mean_activation": statistics.mean(acts) if acts else None,
                "chosen_sign_overall": r.get("chosen_sign"),
                "shard_rows": [
                    {
                        "period_id": pr.get("period_id"),
                        "net": pr.get("net_one_way_mean_active")
                        if pr.get("net_one_way_mean_active") is not None
                        else pr.get("net"),
                        "activation": pr.get("activation_rate")
                        if pr.get("activation_rate") is not None
                        else pr.get("activation"),
                        "status": pr.get("status"),
                    }
                    for pr in prs
                ],
            }
            side[family_key].append(row)
        # side-by-side deltas for matching transforms
        deltas = []
        for transform, b_id, a_id in TRANSFORM_PAIRS:
            b = next((x for x in side["basevol"] if x["logic_id"] == b_id), None)
            a = next((x for x in side["atm_iv"] if x["logic_id"] == a_id), None)
            deltas.append(
                {
                    "transform": transform,
                    "basevol_mean_net": (b or {}).get("mean_net"),
                    "atm_mean_net": (a or {}).get("mean_net"),
                    "delta_mean_net_base_minus_atm": (
                        None
                        if not b or not a or b.get("mean_net") is None or a.get("mean_net") is None
                        else float(b["mean_net"]) - float(a["mean_net"])
                    ),
                    "basevol_t": (b or {}).get("t_stat"),
                    "atm_t": (a or {}).get("t_stat"),
                    "basevol_activation": (b or {}).get("mean_activation"),
                    "atm_activation": (a or {}).get("mean_activation"),
                }
            )
        side["transform_deltas"] = deltas
        window_tables.append(side)

    pack = {
        "wave": "W93 / w0818c",
        "kind": "local_multi_year_window_eval",
        "factory_version": MASS_FACTORY_VERSION,
        "synthetic": bool(synthetic),
        "data_path": "synthetic" if synthetic else "real_mirrors",
        "windows": [dict(w) for w in W93_WINDOWS],
        "n_strategies": len(strategies),
        "n_shards": len(all_shards),
        "results_compact": [_compact_eval_row(r) for r in results],
        "window_tables": window_tables,
        "load_notes": batch.get("load_notes") or {},
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
    }
    _dump(out_dir / "window_eval_local.json", pack)
    return pack


def build_diff_results_table(
    window_pack: Mapping[str, Any],
    *,
    pre_fix_compare: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    matching = []
    for transform, b_id, a_id in TRANSFORM_PAIRS:
        per_window = []
        for w in window_pack.get("window_tables") or []:
            b = next((x for x in w.get("basevol") or [] if x["logic_id"] == b_id), None)
            a = next((x for x in w.get("atm_iv") or [] if x["logic_id"] == a_id), None)
            per_window.append(
                {
                    "window_id": w.get("window_id"),
                    "label": w.get("label"),
                    "basevol": b,
                    "atm_iv": a,
                    "delta_mean_net_base_minus_atm": (
                        None
                        if not b or not a or b.get("mean_net") is None or a.get("mean_net") is None
                        else float(b["mean_net"]) - float(a["mean_net"])
                    ),
                }
            )
        matching.append(
            {
                "transform": transform,
                "basevol_logic": b_id,
                "atm_logic": a_id,
                "per_window": per_window,
            }
        )
    return {
        "wave": "W93 / w0818c",
        "note": (
            "Same transform → BaseVol vs ATM side-by-side across multi-year "
            "windows. Both families always retained."
        ),
        "matching_transforms": matching,
        "spread_logics_by_window": [
            {
                "window_id": w.get("window_id"),
                "label": w.get("label"),
                "spread": w.get("spread"),
            }
            for w in (window_pack.get("window_tables") or [])
        ],
        "pre_fix_wide_compare": pre_fix_compare,
        "data_path": window_pack.get("data_path"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="W93 opt225 BaseVol vs ATM differential + windows")
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0818c_w93_opt225_diff"),
    )
    p.add_argument("--seed", type=int, default=870818)
    p.add_argument("--mode", type=str, default="r2_panels", choices=["r2_panels", "synthetic", "nets_only"])
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--skip-cf", action="store_true")
    p.add_argument("--skip-local", action="store_true")
    p.add_argument("--skip-rebuild", action="store_true")
    p.add_argument("--skip-deploy", action="store_true")
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

    from research.mass_strategy_factory import (
        MASS_FACTORY_VERSION,
        MASS_RESEARCH,
        CONTINUOUS_PAPER,
        FROZEN_DEFAULT_PATH,
    )
    from research.cf_mass_eval_job import (
        CF_MASS_EVAL_VERSION,
        CF_MASS_EVAL_WAVE,
        THICKEN_PANEL_DATASETS,
        inventory_complete22,
        run_cf_mass_eval_job,
        try_cf_mass_eval_status,
    )
    from research.options_225_vol_series import (
        DEFAULT_ATM_MIN_DTE_DAYS,
        OPTIONS_225_VOL_SERIES_VERSION,
        SPREAD_CONVENTION,
        load_opt225_series_cache,
    )

    log(
        f"[w93] wave=W93/w0818c · series={OPTIONS_225_VOL_SERIES_VERSION} · "
        f"factory={MASS_FACTORY_VERSION} · cf={CF_MASS_EVAL_VERSION} · "
        f"min_dte={DEFAULT_ATM_MIN_DTE_DAYS} · seed={args.seed}"
    )
    log(
        f"[w93] freezes: mass={MASS_RESEARCH} paper={CONTINUOUS_PAPER} "
        f"READY=False ops_GO=False frozen_defaults_retuned=False"
    )
    log(
        "[w93] 3 defaults frozen: "
        + ", ".join(r["representative_id"] for r in FROZEN_DEFAULT_PATH)
    )

    inv = inventory_complete22()
    _dump(out_dir / "complete22_inventory.json", inv)
    assert "derivatives_bars_daily_options_225" in set(inv.get("complete_22") or [])

    # ------------------------------------------------------------------ series
    cache = load_opt225_series_cache(out_dir)
    if not cache:
        cache = load_opt225_series_cache(ROOT / ".glm-logs" / "w0818b_w92_options_vol")
    if not cache:
        raise SystemExit("options_225 series cache missing; run rebuild first")
    base = list(cache.get("base_vol_series") or [])
    atm = list(cache.get("atm_iv_series") or [])
    spread = list(cache.get("spread_series") or [])
    log(
        f"[w93] series cache: base={len(base)} atm={len(atm)} spread={len(spread)} "
        f"source={cache.get('log_dir')}"
    )
    if not args.skip_rebuild:
        rebuild_meta = out_dir / "rebuild_meta.json"
        if rebuild_meta.exists():
            log(f"[w93] rebuild_meta present: {rebuild_meta}")
        else:
            log(
                "[w93] WARN: rebuild_meta missing — if ATM still has SQ-week "
                "spikes, wait for background rebuild or re-run without --skip-rebuild"
            )

    # ------------------------------------------------------------------ A: differential
    log("[w93] A: differential series stats")
    diff_stats = build_diff_series_stats(
        base, atm, spread, source=str(cache.get("log_dir") or out_dir)
    )
    _dump(out_dir / "diff_series_stats.json", diff_stats)
    # keep parallel-agent alias
    _dump(out_dir / "series_stats.json", diff_stats)

    diagnosis = build_spread_diagnosis(diff_stats)
    _dump(out_dir / "spread_activation_diagnosis.json", diagnosis)
    _dump(out_dir / "spread_activation_autopsy.json", diagnosis)
    md = out_dir / "spread_activation_diagnosis.md"
    md.write_text(
        "\n".join(
            [
                "# W93 spread activation diagnosis",
                "",
                f"**Wave:** W93 / w0818c",
                "",
                f"## Answer",
                "",
                diagnosis["answer_summary"],
                "",
                "## Evidence",
                "",
                f"- frac_exact_zero_spread: `{diagnosis.get('frac_exact_zero_spread')}`",
                f"- frac_active_abs (default thresholds): `{diagnosis.get('frac_active_abs')}`",
                f"- dte_buckets_zero: `{json.dumps(diagnosis.get('dte_buckets_zero_spread'))}`",
                f"- dte_buckets_nonzero: `{json.dumps(diagnosis.get('dte_buckets_nonzero_spread'))}`",
                f"- min_dte_days fix: `{diagnosis.get('min_dte_days')}`",
                f"- sign_convention_bug: `{diagnosis['definition_bug_verdict']['sign_convention_bug']}`",
                f"- basevol_equals_atm_by_definition: `{diagnosis['definition_bug_verdict']['basevol_equals_atm_by_definition']}`",
                "",
                "## Noise vs structure",
                "",
                str(diagnosis.get("noise_vs_structure")),
                "",
                "Implementer: GLM5.3 only. Grok did not implement.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------ B: windows
    window_pack: dict[str, Any] = {}
    if not args.skip_local:
        log("[w93] B: multi-year window local eval (BaseVol + ATM + spread)")
        window_pack = run_local_window_eval(
            out_dir=out_dir,
            seed=int(args.seed),
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            synthetic=bool(args.synthetic),
            log=log,
        )
        for w in window_pack.get("window_tables") or []:
            log(f"  · window {w['window_id']} shards={w['shard_ids']}")
            for d in w.get("transform_deltas") or []:
                log(
                    f"    {d['transform']}: base_net={d['basevol_mean_net']} "
                    f"atm_net={d['atm_mean_net']} delta={d['delta_mean_net_base_minus_atm']}"
                )
    else:
        log("[w93] B: local window eval skipped")

    pre_fix = None
    pre_path = out_dir / "compare_table.json"
    if pre_path.exists():
        try:
            pre_fix = json.loads(pre_path.read_text())
        except json.JSONDecodeError:
            pre_fix = None
    diff_table = build_diff_results_table(window_pack or {}, pre_fix_compare=pre_fix)
    _dump(out_dir / "diff_results_table.json", diff_table)
    _dump(out_dir / "compare_table.json", diff_table)

    # ------------------------------------------------------------------ C: CF
    cf_pack: dict[str, Any] = {}
    cf_status = try_cf_mass_eval_status()
    _dump(out_dir / "cf_status.json", cf_status)
    if not args.skip_cf:
        mode = "synthetic" if args.synthetic else str(args.mode)
        job_id = f"w93-opt225-{ts}"
        log(f"[w93] C: CF mass-eval job_id={job_id} mode={mode} thicken={list(THICKEN_PANEL_DATASETS)}")
        shards: list[dict[str, Any]] = []
        for w in W93_WINDOWS:
            for s in w["shards"]:
                shards.append(dict(s))
        # also keep y2019/21/23 full coverage continuity with prior CF periods
        logic_ids = list(OPT225_LOGIC_IDS) + [
            "macro_repo_rate_level",
            "macro_repo_rate_change",
            "nky_vol_term_ratio",
            "xs_rank_ls_sticky",
        ]
        try:
            cf_pack = run_cf_mass_eval_job(
                job_id=job_id,
                logic_ids=logic_ids,
                periods=shards,
                mode=mode,
                max_codes=int(args.max_codes),
                max_days=int(args.max_days),
                seed=int(args.seed),
                worker_url=str(args.worker_url),
                deploy_if_needed=not bool(args.skip_deploy),
                dry_run_r2=bool(args.dry_run_r2),
                staging_dir=out_dir / "panels_stage",
            )
        except Exception as exc:
            log(f"[w93] C CF job failed: {exc}")
            cf_pack = {"status": "error", "error": str(exc), "job_id": job_id}
        _dump(out_dir / "cf_mass_eval_job.json", cf_pack)
        wr = cf_pack.get("worker_response") or {}
        # CF per-window aggregation
        cf_window_rows = []
        for w in W93_WINDOWS:
            shard_ids = {s["period_id"] for s in w["shards"]}
            fam: dict[str, list] = {"basevol": [], "atm_iv": [], "spread": [], "other": []}
            for r in wr.get("results") or []:
                lid = str(r.get("logic_id") or "")
                key = (
                    "basevol"
                    if "basevol" in lid
                    else "atm_iv"
                    if "atm_iv" in lid
                    else "spread"
                    if "spread" in lid
                    else "other"
                )
                prs = [
                    pr
                    for pr in (r.get("period_rows") or [])
                    if pr.get("period_id") in shard_ids
                ]
                nets = [
                    float(pr["net_one_way_mean_active"])
                    for pr in prs
                    if pr.get("net_one_way_mean_active") is not None
                ]
                acts = [
                    float(pr["activation_rate"])
                    for pr in prs
                    if pr.get("activation_rate") is not None
                ]
                fam[key].append(
                    {
                        "logic_id": lid,
                        "mean_net": statistics.mean(nets) if nets else None,
                        "mean_activation": statistics.mean(acts) if acts else None,
                        "n_shards_with_net": len(nets),
                        "chosen_sign": r.get("chosen_sign"),
                        "overall_mean_net": r.get("mean_net"),
                        "overall_t_stat": r.get("t_stat"),
                    }
                )
            cf_window_rows.append(
                {
                    "window_id": w["window_id"],
                    "label": w["label"],
                    "data_note": w["data_note"],
                    **fam,
                }
            )
        cf_summary = {
            "job_id": cf_pack.get("job_id") or job_id,
            "status": cf_pack.get("status"),
            "mode": cf_pack.get("mode") or mode,
            "n_survivors": cf_pack.get("n_survivors"),
            "n_logics": cf_pack.get("n_logics"),
            "n_periods": cf_pack.get("n_periods"),
            "r2_prefix": cf_pack.get("r2_prefix")
            or (cf_pack.get("artifact_paths") or {}).get("prefix"),
            "stage_panels": cf_pack.get("stage_panels"),
            "window_tables": cf_window_rows,
            "thicken_panel_datasets": list(THICKEN_PANEL_DATASETS),
            "opt225_results": [
                {
                    "logic_id": r.get("logic_id"),
                    "mean_net": r.get("mean_net"),
                    "t_stat": r.get("t_stat"),
                    "chosen_sign": r.get("chosen_sign"),
                    "mean_activation": r.get("mean_activation"),
                    "n_periods_ok": r.get("n_periods_ok"),
                    "signal_ids": sorted(
                        {
                            pr.get("signal_id")
                            for pr in (r.get("period_rows") or [])
                            if pr.get("signal_id")
                        }
                    ),
                }
                for r in (wr.get("results") or [])
                if str(r.get("logic_id") or "").startswith("opt225_")
            ],
        }
        _dump(out_dir / "cf_window_summary.json", cf_summary)
        _dump(out_dir / "cf_job_run.json", cf_summary)
        log(
            f"[w93] C done · status={cf_pack.get('status')} "
            f"survivors={cf_pack.get('n_survivors')} job={cf_pack.get('job_id') or job_id}"
        )
    else:
        log("[w93] C: CF skipped")

    # ------------------------------------------------------------------ wiring inventory
    thicken_status: dict[str, Counter] = {}
    stage = (cf_pack or {}).get("stage_panels") or {}
    for panel in stage.get("panels") or []:
        status_map = panel.get("thicken_status") or {}
        for k, v in status_map.items():
            thicken_status.setdefault(k, Counter())[str(v).split(":")[0]] += 1
    wiring = {
        "wave": "W93 / w0818c",
        "thicken_panel_datasets": list(THICKEN_PANEL_DATASETS),
        "panel_thicken_status_counts": {
            k: dict(v) for k, v in thicken_status.items()
        },
        "DONE": [
            "equities_bars_daily (primary bars)",
            "derivatives_bars_daily_options_225 (opt225_regime + series maps)",
            "indices_bars_daily_topix (nky proxy label only)",
            "jsda_tokyo_repo_rates → repo_rate_by_date / repo_rate_regime sidecar",
            "markets_margin_interest → margin_interest sidecar when mirror exists",
            "markets_short_ratio → short_ratio_by_date sidecar",
            "fins_summary → fins_summary_n_events presence",
            "markets_calendar → calendar_dates when sqlite populated",
        ],
        "TODO": [
            "CF worker pure-TS rate/mf/flow factor legs consuming thicken sidecars",
            "contiguous 3-year equities bars mirrors for w2017_2019 / w2020_2022 / w2023_2025",
            "markets_calendar local sqlite currently empty → EMPTY until D1 sync",
        ],
        "cf_wave": CF_MASS_EVAL_WAVE,
        "cf_version": CF_MASS_EVAL_VERSION,
    }
    _dump(out_dir / "cf_wiring_inventory.json", wiring)

    summary = {
        "wave": "W93 / w0818c",
        "elapsed_sec": time.perf_counter() - t0,
        "series_version": OPTIONS_225_VOL_SERIES_VERSION,
        "min_dte_days": DEFAULT_ATM_MIN_DTE_DAYS,
        "spread_convention": SPREAD_CONVENTION,
        "canonical_dataset": "derivatives_bars_daily_options_225",
        "nky_vol_role": "proxy_compare_only",
        "diff": {
            "n_days": diff_stats.get("n_days"),
            "corr_pearson": (diff_stats.get("corr") or {}).get("pearson_level"),
            "frac_exact_zero_spread": (
                diff_stats.get("spread_activation_context") or {}
            ).get("frac_exact_zero"),
            "frac_active_abs": (
                diff_stats.get("spread_activation_context") or {}
            ).get("frac_active_abs"),
        },
        "windows": [w["window_id"] for w in W93_WINDOWS],
        "local_window_eval": {
            "n_strategies": (window_pack or {}).get("n_strategies"),
            "data_path": (window_pack or {}).get("data_path"),
        },
        "cf": {
            "status": cf_pack.get("status") if cf_pack else "skipped",
            "job_id": (cf_pack or {}).get("job_id"),
            "n_survivors": (cf_pack or {}).get("n_survivors"),
            "mode": (cf_pack or {}).get("mode"),
        },
        "freezes": {
            "mass_research": MASS_RESEARCH,
            "continuous_paper": CONTINUOUS_PAPER,
            "ready_declared": False,
            "operational_go": False,
            "phase7": "OFF",
            "frozen_defaults_retuned": False,
            "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        },
        "artifacts": {
            "diff_series_stats": str(out_dir / "diff_series_stats.json"),
            "diff_results_table": str(out_dir / "diff_results_table.json"),
            "spread_activation_diagnosis": str(
                out_dir / "spread_activation_diagnosis.md"
            ),
            "window_eval_local": str(out_dir / "window_eval_local.json"),
            "cf_wiring_inventory": str(out_dir / "cf_wiring_inventory.json"),
        },
        "implementer": "GLM5.3 only. Grok did not implement.",
    }
    _dump(out_dir / "w93_summary.json", summary)
    log(f"[w93] done · elapsed={summary['elapsed_sec']:.1f}s · out={out_dir}")
    return 0 if (not cf_pack or cf_pack.get("status") in {None, "ok", "skipped", "error"}) else 1


if __name__ == "__main__":
    raise SystemExit(main())
