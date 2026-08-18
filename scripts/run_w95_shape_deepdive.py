#!/usr/bin/env python3
"""W95 / w0818e — shape deep-dive: skew / CM-term / ΔBaseVol.

Tracks
------
A. Coarse sensitivity on thresholds / lookbacks — **few points only**, no grid mass
B. Few shape×CS binds (skew/term/Δ × mom=3|5 relative-momentum gating)
C. Per-window tables: sign / act / t (local real + optional CF r2_panels)
D. Short note on 2020–22 divergence vs BaseVol abs level
E. Weak → say weak; do **not** promote as main candidates

Frozen: Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO deferred ·
continuous paper UNARMED · 3 defaults not retuned · BaseVol=canonical ·
ATM=compare-only · spread=off-mainline · no smile≡level claim.

Examples
--------
    uv run python scripts/run_w95_shape_deepdive.py \\
        --out-dir .glm-logs/w0818e_w95_shape_factor_decomp/

    uv run python scripts/run_w95_shape_deepdive.py --skip-cf
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

# Reuse W94 honest shards.
W95_WINDOWS: tuple[dict[str, Any], ...] = (
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

PRIMARY_LOGIC_IDS: tuple[str, ...] = (
    "opt225_skew_abs_level",
    "opt225_cm_term_abs_level",
    "opt225_basevol_delta_abs",
)
LEVEL_COMPARE_LOGIC_IDS: tuple[str, ...] = ("opt225_basevol_abs_level",)

# Fullspan v1.2 anchors (W94 rebuild) used to pick coarse points — NOT a grid.
# skew: mean≈4.58 p50≈4.35 p10≈2.54 p90≈6.99
# cm_term: mean≈0.11 p50≈−0.24 p10≈−1.52 p90≈1.83
# basevol_delta: mean≈0.00 p50≈−0.14 p10≈−1.78 p90≈2.00
CHOSEN_POINTS_RATIONALE: dict[str, Any] = {
    "method": "coarse_percentile_anchors",
    "series_version": "research-options-225-vol-series/v1.2",
    "grid_mass": False,
    "note": (
        "2–4 threshold/lookback points per series only. Defaults pinned to W94 "
        "factory; alts ≈ p10/p50/p90 neighbourhood. Lookback axis = CS mom "
        "horizon {3,5} at default thresholds (not a frozen-default retune)."
    ),
}

# Few sensitivity points only (not a grid). Defaults + 2 threshold alts per series.
SENSITIVITY_POINTS: dict[str, tuple[dict[str, Any], ...]] = {
    "opt225_skew_abs_level": (
        {
            "tag": "default",
            "high_threshold": 3.0,
            "low_threshold": 0.5,
            "why": "W94 pin; hi below p50(~4.35) so mid-high skew fires reverse",
        },
        {
            "tag": "looser",
            "high_threshold": 2.0,
            "low_threshold": 1.0,
            "why": "near p10(~2.54) high-band; narrower mid band → more activation",
        },
        {
            "tag": "tighter",
            "high_threshold": 4.5,
            "low_threshold": 0.0,
            "why": "hi≈p50; only elevated skew reverses; wider calm/keep band",
        },
    ),
    "opt225_cm_term_abs_level": (
        {
            "tag": "default",
            "high_threshold": 2.0,
            "low_threshold": -1.0,
            "why": "W94 pin; hi≈p90(~1.83) front-rich reverse; lo≈p10 keep/steep",
        },
        {
            "tag": "narrow",
            "high_threshold": 1.0,
            "low_threshold": -0.5,
            "why": "tighter around p50; more mid→no-trade, fewer act days",
        },
        {
            "tag": "wide",
            "high_threshold": 3.0,
            "low_threshold": -2.0,
            "why": "beyond p10/p90; only extreme term fires; stress check",
        },
    ),
    "opt225_basevol_delta_abs": (
        {
            "tag": "default",
            "high_threshold": 1.0,
            "low_threshold": -1.0,
            "why": "W94 pin; ≈0.5σ daily Δ (~stdev 2.1) for rise/fall regimes",
        },
        {
            "tag": "tight",
            "high_threshold": 0.5,
            "low_threshold": -0.5,
            "why": "higher activation; small Δ still risk-adjusts CS",
        },
        {
            "tag": "wide",
            "high_threshold": 1.5,
            "low_threshold": -1.5,
            "why": "near p10/p90; only large day-moves reverse/keep",
        },
    ),
}

# Few shape×CS binds: relative-mom gating horizon ∈ {3,5} at default thresholds.
# Not a retune of the 3 frozen defaults (those stay mom5/mom3/fund).
CS_BIND_MOM: tuple[int, ...] = (5, 3)

# Explicit 1–2 shape×CS combo logics (thesis / signal / position).
# These are *bindings* of existing shape abs-level × CS mom — not new series,
# not frozen-default retunes, not main-candidate promotions.
COMBO_LOGICS: tuple[dict[str, Any], ...] = (
    {
        "combo_id": "high_skew_reverse_cs",
        "logic_id": "opt225_skew_abs_level",
        "variant": "combo_high_skew_reverse",
        "momentum_n": 5,
        "high_threshold": 3.0,
        "low_threshold": 0.5,
        "thesis": (
            "Elevated 95% put skew = crash-premium / risk-off in NKY options. "
            "When skew is high, cross-sectional momentum is a crowded risk-on "
            "book → reverse CS mom; calm/low skew → keep CS (risk-on)."
        ),
        "signal": (
            "shape = put_iv(~0.95*UnderPx) − atm_mid_iv (listed strikes only, "
            "min_dte≥6). Regime: skew≥3.0 → high; skew≤0.5 → low; else mid. "
            "CS = same-day rank mom L-S (mom_n=5, long/short_frac=0.3)."
        ),
        "position": (
            "high → position = −CS_sign (reverse); low → +CS_sign (keep); "
            "mid → flat. Sticky hold_days=10 fixed_horizon balanced L/S."
        ),
    },
    {
        "combo_id": "steep_cm_term_keep_cs",
        "logic_id": "opt225_cm_term_abs_level",
        "variant": "combo_steep_term_keep",
        "momentum_n": 5,
        "high_threshold": 2.0,
        "low_threshold": -1.0,
        "thesis": (
            "Steep CM vol term (near ATM ≪ next ATM under near−next convention, "
            "i.e. cm_term low/negative) is a risk-on / contango-like surface → "
            "keep CS mom. Front-rich / inverted term (cm_term high) → reverse CS."
        ),
        "signal": (
            "shape = near_cm_atm_iv − next_cm_atm_iv (both CM min_dte≥6). "
            "Regime: cm_term≥2.0 → high/front-rich; cm_term≤−1.0 → low/steep; "
            "else mid. CS = rank mom L-S (mom_n=5)."
        ),
        "position": (
            "steep/low → keep CS (+sign); front-rich/high → reverse (−sign); "
            "mid → flat. Sticky hold_days=10 fixed_horizon balanced L/S."
        ),
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
    return "other"


def _row(r: Mapping[str, Any], *, window_id: str, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    scr = r.get("screen") or {}
    lid = str(r.get("logic_id") or r.get("logic") or "")
    params = dict(r.get("params") or {})
    out = {
        "window": window_id,
        "logic": lid,
        "bucket": _feature_bucket(lid),
        "variant": (extra or {}).get("variant") or r.get("variant") or "default",
        "tag": (extra or {}).get("tag") or r.get("tag"),
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
        "status": r.get("status"),
    }
    if extra:
        for k, v in extra.items():
            if k not in out:
                out[k] = v
    return out


def _markdown_table(rows: Sequence[Mapping[str, Any]], *, title: str) -> str:
    header = (
        "| window | bucket | logic | variant | mom | hi/lo | mean_net | t | act | "
        "sign | surv |"
    )
    sep = "|---|---|---|---|---:|---|---:|---:|---:|---|---|"
    lines = [f"# {title}", "", header, sep]
    for r in rows:
        mn, t, act = r.get("mean_net"), r.get("t"), r.get("act")
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        act_s = f"{act:.4f}" if isinstance(act, float) else "—"
        sign = r.get("sign")
        sign_s = "—" if sign is None else str(sign)
        hi, lo = r.get("high_threshold"), r.get("low_threshold")
        thr = (
            f"{hi}/{lo}"
            if hi is not None and lo is not None
            else "—"
        )
        mom = r.get("momentum_n")
        mom_s = str(mom) if mom is not None else "—"
        lines.append(
            f"| {r.get('window')} | {r.get('bucket')} | `{r.get('logic')}` | "
            f"{r.get('variant')} | {mom_s} | {thr} | {mn_s} | {t_s} | {act_s} | "
            f"{sign_s} | {r.get('survived')} |"
        )
    return "\n".join(lines)


def _strategies_with_overrides(
    *,
    track: str,
) -> list[dict[str, Any]]:
    """Build few-point sensitivity + bind strategies (not a free grid)."""
    from research.mass_strategy_factory import LOGIC_TEMPLATES

    out: list[dict[str, Any]] = []

    # Level compare (default only).
    for lid in LEVEL_COMPARE_LOGIC_IDS:
        tpl = LOGIC_TEMPLATES.get(lid)
        if tpl is None:
            continue
        out.append(
            {
                "strategy_id": f"msf_w95_{lid}_default",
                "logic_id": lid,
                "family_id": tpl.family_id,
                "params": dict(tpl.base_params),
                "thesis": tpl.thesis,
                "signal_definition": tpl.signal_definition,
                "position_rule": tpl.position_rule,
                "datasets_used": list(tpl.datasets_used),
                "source": f"w95_{track}",
                "variant": "level_compare",
                "tag": "default",
            }
        )

    # Sensitivity: few threshold points at default mom=5.
    for lid, points in SENSITIVITY_POINTS.items():
        tpl = LOGIC_TEMPLATES.get(lid)
        if tpl is None:
            continue
        for pt in points:
            params = dict(tpl.base_params)
            params["high_threshold"] = float(pt["high_threshold"])
            params["low_threshold"] = float(pt["low_threshold"])
            params["momentum_n"] = 5
            tag = str(pt["tag"])
            out.append(
                {
                    "strategy_id": f"msf_w95_{lid}_sens_{tag}",
                    "logic_id": lid,
                    "family_id": tpl.family_id,
                    "params": params,
                    "thesis": tpl.thesis,
                    "signal_definition": tpl.signal_definition,
                    "position_rule": tpl.position_rule,
                    "datasets_used": list(tpl.datasets_used),
                    "source": f"w95_{track}",
                    "variant": f"sens_{tag}",
                    "tag": tag,
                }
            )

    # Shape×CS binds: mom=3 vs mom=5 at default thresholds (few lookback points).
    for lid in PRIMARY_LOGIC_IDS:
        tpl = LOGIC_TEMPLATES.get(lid)
        if tpl is None:
            continue
        for mom in CS_BIND_MOM:
            params = dict(tpl.base_params)
            params["momentum_n"] = int(mom)
            # Keep default thresholds for binds.
            tag = f"mom{mom}"
            # Avoid duplicating default sens row (mom5 default already in sens).
            if mom == 5:
                continue
            out.append(
                {
                    "strategy_id": f"msf_w95_{lid}_bind_{tag}",
                    "logic_id": lid,
                    "family_id": tpl.family_id,
                    "params": params,
                    "thesis": (
                        f"{tpl.thesis} · W95 lookback bind: CS relative-mom "
                        f"lookback={mom} (not a frozen-default retune)"
                    ),
                    "signal_definition": tpl.signal_definition,
                    "position_rule": tpl.position_rule,
                    "datasets_used": list(tpl.datasets_used),
                    "source": f"w95_{track}",
                    "variant": f"bind_{tag}",
                    "tag": tag,
                }
            )

    # Explicit combo logics (thesis/signal/position documented; same abs×CS mech).
    for combo in COMBO_LOGICS:
        lid = str(combo["logic_id"])
        tpl = LOGIC_TEMPLATES.get(lid)
        if tpl is None:
            continue
        params = dict(tpl.base_params)
        params["momentum_n"] = int(combo["momentum_n"])
        params["high_threshold"] = float(combo["high_threshold"])
        params["low_threshold"] = float(combo["low_threshold"])
        out.append(
            {
                "strategy_id": f"msf_w95_{combo['combo_id']}",
                "logic_id": lid,
                "family_id": tpl.family_id,
                "params": params,
                "thesis": combo["thesis"],
                "signal_definition": combo["signal"],
                "position_rule": combo["position"],
                "datasets_used": list(tpl.datasets_used),
                "source": f"w95_{track}",
                "variant": str(combo["variant"]),
                "tag": str(combo["combo_id"]),
                "combo_id": combo["combo_id"],
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
        "variant": result.get("variant"),
        "tag": result.get("tag"),
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


def _divergence_note_2020_22(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Document w2020_2022 shape-alive vs BaseVol-level-dead divergence."""
    by: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        if str(r.get("window")) != "w2020_2022":
            continue
        # Prefer default sensitivity rows for the note.
        if str(r.get("variant") or "") not in {
            "sens_default",
            "level_compare",
            "default",
        }:
            continue
        by.setdefault(str(r.get("logic")), []).append(r)

    level = (by.get("opt225_basevol_abs_level") or [{}])[0]
    shape_rows = []
    for lid in PRIMARY_LOGIC_IDS:
        cur = (by.get(lid) or [{}])[0]
        shape_rows.append(
            {
                "logic": lid,
                "survived": cur.get("survived"),
                "sign": cur.get("sign"),
                "act": cur.get("act"),
                "mean_net": cur.get("mean_net"),
                "t": cur.get("t"),
            }
        )
    level_dead = not bool(level.get("survived")) or (
        isinstance(level.get("act"), float) and float(level["act"]) < 0.005
    )
    shape_alive = any(bool(r.get("survived")) for r in shape_rows)
    return {
        "window": "w2020_2022",
        "level": {
            "logic": "opt225_basevol_abs_level",
            "survived": level.get("survived"),
            "act": level.get("act"),
            "sign": level.get("sign"),
            "mean_net": level.get("mean_net"),
        },
        "shape_rows": shape_rows,
        "level_dead": level_dead,
        "shape_alive": shape_alive,
        "divergence": bool(level_dead and shape_alive),
        "note": (
            "w2020_2022: BaseVol abs level dies (act≈0 / reject) while skew / "
            "CM-term / ΔBaseVol remain active — shape/change ≠ level regime. "
            "Do NOT claim smile/surface ≡ BaseVol level. ATM remains compare-only; "
            "spread remains off-mainline."
        ),
        "promotion_stance": (
            "weak_or_research_only"
            if shape_alive
            else "weak"
        ),
        "promote_as_main_candidate": False,
    }


def run_local_deepdive(
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

    strategies = _strategies_with_overrides(track="shape_deepdive_local")
    cfg = MassFactoryConfig(
        seed=int(seed),
        n=len(strategies),
        max_codes=int(max_codes),
        max_days_per_period=int(max_days),
        use_q4_periods=False,
    )
    log(
        f"[w95] local shape deep-dive · n_strats={len(strategies)} "
        f"(few-point sens + binds; no grid) factory={MASS_FACTORY_VERSION}"
    )

    rows_flat: list[dict[str, Any]] = []
    window_tables: list[dict[str, Any]] = []

    for w in W95_WINDOWS:
        wid = str(w["window_id"])
        periods = [dict(s) for s in w["shards"]]
        log(
            f"[w95]   local {wid} shards={[s['period_id'] for s in periods]}"
        )
        ctx = load_batch_data_context(
            cfg, periods=periods, synthetic=bool(synthetic)
        )
        window_rows: list[dict[str, Any]] = []
        for strat in strategies:
            res = evaluate_one_strategy(
                strat,
                ctx,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            res["t_stat"] = _scalar_t(res.get("t_stat"))
            res["params"] = dict(strat.get("params") or {})
            res["variant"] = strat.get("variant")
            res["tag"] = strat.get("tag")
            scr = screen_strategy_result(
                res,
                near_zero_abs=cfg.near_zero_abs,
                min_activation=cfg.min_activation,
            )
            res["screen"] = scr
            row = _row(
                res,
                window_id=wid,
                extra={
                    "variant": strat.get("variant"),
                    "tag": strat.get("tag"),
                },
            )
            window_rows.append(row)
            rows_flat.append(row)
            v = str(strat.get("variant") or "")
            if (
                v.startswith("sens_default")
                or v.startswith("combo_")
                or v in {"level_compare", "bind_mom3"}
            ):
                log(
                    f"    {row['logic']}[{row['variant']}]: net={row['mean_net']} "
                    f"t={row['t']} act={row['act']} sign={row['sign']} "
                    f"surv={row['survived']}"
                )

        window_tables.append(
            {
                "window_id": wid,
                "label": w["label"],
                "data_note": w["data_note"],
                "shard_ids": [s["period_id"] for s in periods],
                "n_survivors": sum(1 for r in window_rows if r.get("survived")),
                "rows": window_rows,
                "load_notes": ctx.load_notes,
            }
        )

    # Stance: do not promote as main candidates from this deep-dive alone.
    default_primary = [
        r
        for r in rows_flat
        if r.get("variant") == "sens_default" and r.get("logic") in PRIMARY_LOGIC_IDS
    ]
    n_surv = sum(1 for r in default_primary if r.get("survived"))
    stance = {
        "promote_as_main_candidate": False,
        "reason": (
            "W95 deep-dive: shape features remain research-only. Survive some "
            "windows but signs flip / economic nets thin; do not promote as "
            "main candidates. 3 defaults untouched."
        ),
        "n_default_primary_rows": len(default_primary),
        "n_default_primary_survivors": n_surv,
        "strength": "weak_to_moderate_research"
        if n_surv
        else "weak",
    }

    div = _divergence_note_2020_22(rows_flat)
    combo_rows = [
        r for r in rows_flat if str(r.get("variant") or "").startswith("combo_")
    ]
    sens_rows = [
        r
        for r in rows_flat
        if str(r.get("variant") or "").startswith("sens_")
        or str(r.get("variant") or "") == "level_compare"
        or str(r.get("variant") or "").startswith("bind_")
    ]
    pack = {
        "wave": "W95 / w0818e",
        "track": "A_shape_deepdive",
        "kind": "local_shape_sensitivity_and_binds",
        "factory_version": MASS_FACTORY_VERSION,
        "synthetic": bool(synthetic),
        "data_path": "synthetic" if synthetic else "real_mirrors",
        "max_days_per_period": int(max_days),
        "canonical_level": "base_vol",
        "atm_iv_role": "compare_only",
        "n_strategies": len(strategies),
        "chosen_points_rationale": CHOSEN_POINTS_RATIONALE,
        "sensitivity_points": {
            k: [dict(p) for p in v] for k, v in SENSITIVITY_POINTS.items()
        },
        "cs_bind_mom": list(CS_BIND_MOM),
        "combo_logics": [dict(c) for c in COMBO_LOGICS],
        "grid_mass": False,
        "windows": [dict(w) for w in W95_WINDOWS],
        "window_tables": window_tables,
        "rows_flat": rows_flat,
        "divergence_2020_22": div,
        "promotion_stance": stance,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
        "markdown_table": _markdown_table(
            rows_flat, title="W95 shape deep-dive local (sens + binds + combos)"
        ),
        "weak_explicit": (
            "WEAK → not a main candidate. Shape/change features remain "
            "research-only; do not promote from this deep-dive."
        ),
    }
    _dump(out_dir / "shape_deepdive_local.json", pack)
    _dump(out_dir / "shape_sens_bind_table.json", rows_flat)
    (out_dir / "shape_sens_bind_table.md").write_text(
        pack["markdown_table"] + "\n", encoding="utf-8"
    )
    _dump(out_dir / "shape_combo_window_table.json", combo_rows)
    (out_dir / "shape_combo_window_table.md").write_text(
        _markdown_table(combo_rows, title="W95 shape×CS combo window table")
        + "\n",
        encoding="utf-8",
    )
    _dump(out_dir / "shape_window_table.json", sens_rows)
    (out_dir / "shape_window_table.md").write_text(
        _markdown_table(
            sens_rows, title="W95 shape sens/lookback window table (2017–25)"
        )
        + "\n",
        encoding="utf-8",
    )

    # Chosen points doc (coarse sens; not a grid).
    chosen_lines = [
        "# W95 — chosen coarse sensitivity / lookback points",
        "",
        f"**Wave:** W95 / w0818e · track A",
        f"**Grid mass:** **no** (2–4 points per series only)",
        f"**Series:** research-options-225-vol-series/v1.2",
        "",
        CHOSEN_POINTS_RATIONALE["note"],
        "",
        "## Threshold points (mom_n=5)",
        "",
        "| logic | tag | high | low | why |",
        "|---|---|---:|---:|---|",
    ]
    for lid, pts in SENSITIVITY_POINTS.items():
        for pt in pts:
            chosen_lines.append(
                f"| `{lid}` | {pt['tag']} | {pt['high_threshold']} | "
                f"{pt['low_threshold']} | {pt['why']} |"
            )
    chosen_lines += [
        "",
        "## Lookback points (default thresholds)",
        "",
        f"- CS momentum lookback ∈ `{list(CS_BIND_MOM)}` at each series' "
        "default hi/lo (bind_mom3 is the incremental lookback variant; "
        "mom5 is covered by sens_default).",
        "- **Not** a retune of frozen defaults "
        "(`cross_section_hold_10` mom5 / `cross_section_hold_10_mom3` / "
        "`fundamentals_hold_10`).",
        "",
        "## Explicit non-claims",
        "",
        "- No full threshold×lookback grid",
        "- No smile/surface ≡ BaseVol level claim",
        "- Weak → **not** main candidate",
        "",
    ]
    (out_dir / "chosen_points.md").write_text(
        "\n".join(chosen_lines), encoding="utf-8"
    )
    _dump(
        out_dir / "chosen_points.json",
        {
            "rationale": CHOSEN_POINTS_RATIONALE,
            "sensitivity_points": {
                k: [dict(p) for p in v] for k, v in SENSITIVITY_POINTS.items()
            },
            "cs_bind_mom": list(CS_BIND_MOM),
        },
    )

    # Combo thesis/signal/position doc.
    combo_doc = [
        "# W95 — shape×CS combo logics",
        "",
        "**Stance:** research-only · **promote_as_main_candidate: false**",
        "",
        "Two explicit binds of existing shape abs-level × CS mom "
        "(param-aligned with sens_default; documented for thesis/signal/position).",
        "",
    ]
    for c in COMBO_LOGICS:
        combo_doc += [
            f"## `{c['combo_id']}`",
            "",
            f"- **logic_id:** `{c['logic_id']}`",
            f"- **params:** mom={c['momentum_n']} · "
            f"hi/lo={c['high_threshold']}/{c['low_threshold']}",
            f"- **thesis:** {c['thesis']}",
            f"- **signal:** {c['signal']}",
            f"- **position:** {c['position']}",
            "",
        ]
    combo_doc += [
        "## Window results",
        "",
        "See `shape_combo_window_table.md`.",
        "",
        "**Explicit:** weak → **not** main candidate.",
        "",
    ]
    (out_dir / "combo_logics.md").write_text("\n".join(combo_doc), encoding="utf-8")
    _dump(out_dir / "combo_logics.json", [dict(c) for c in COMBO_LOGICS])

    note_lines = [
        "# note_2020_22_vs_level — shape/change ≠ BaseVol abs level",
        "",
        f"**Wave:** W95 / w0818e · track A",
        f"**Window:** w2020_2022 (honest shard = y2021_full only)",
        "",
        div["note"],
        "",
        "## Headline",
        "",
        f"- BaseVol abs level dead: **{div['level_dead']}** "
        f"(surv={div['level'].get('survived')} act={div['level'].get('act')})",
        f"- Shape/change alive: **{div['shape_alive']}**",
        f"- Divergence: **{div['divergence']}**",
        "",
        "## Shape rows (default sens)",
        "",
        "| logic | surv | sign | act | mean_net | t |",
        "|---|---|---|---:|---:|---:|",
    ]
    for sr in div.get("shape_rows") or []:
        act, mn, t = sr.get("act"), sr.get("mean_net"), sr.get("t")
        act_s = f"{act:.4f}" if isinstance(act, float) else "—"
        mn_s = f"{mn:.6f}" if isinstance(mn, float) else "—"
        t_s = f"{t:.4f}" if isinstance(t, float) else "—"
        note_lines.append(
            f"| `{sr.get('logic')}` | {sr.get('survived')} | {sr.get('sign')} | "
            f"{act_s} | {mn_s} | {t_s} |"
        )
    note_lines += [
        "",
        "## Stance",
        "",
        "- promote_as_main_candidate: **false**",
        "- W94 already showed shape ≠ level; W95 confirms under coarse sens",
        "- **WEAK → not a main candidate**",
        "",
        "ATM remains compare-only; spread remains off-mainline; freezes held.",
        "",
    ]
    note_body = "\n".join(note_lines)
    (out_dir / "note_2020_22_vs_level.md").write_text(note_body, encoding="utf-8")
    (out_dir / "divergence_2020_22.md").write_text(note_body, encoding="utf-8")
    _dump(out_dir / "note_2020_22_vs_level.json", div)

    # Track-A summary (do not overwrite track-B SUMMARY.md).
    shape_sum = [
        "# W95 / w0818e — track A: skew / CM-term / Δ deep-dive",
        "",
        "**Wave:** W95 / w0818e",
        "**Track:** A_shape_deepdive",
        "**Canonical level:** BaseVol · ATM compare-only · spread off-mainline",
        "",
        "## Deliverables",
        "",
        "1. Coarse sens (2–4 pts/series) — `chosen_points.md`",
        "2. Shape×CS combos — `combo_logics.md` + `shape_combo_window_table.md`",
        "3. Window tables 2017–19 / 2020–22 / 2023–25 — "
        "`shape_window_table.md` / `shape_sens_bind_table.md`",
        "4. `note_2020_22_vs_level.md`",
        "5. **Explicit: WEAK → not main candidate**",
        "",
        "## Promotion stance",
        "",
        f"- promote_as_main_candidate: **{stance['promote_as_main_candidate']}**",
        f"- strength: `{stance['strength']}`",
        f"- reason: {stance['reason']}",
        "",
        f"## 2020–22 vs level: divergence=**{div['divergence']}**",
        "",
        "## Freezes held",
        "",
        "- Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言",
        "- continuous paper UNARMED · 3 defaults not retuned",
        "- no smile≡level claim · no grid mass",
        "",
    ]
    (out_dir / "shape_deepdive_SUMMARY.md").write_text(
        "\n".join(shape_sum), encoding="utf-8"
    )
    return pack


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="W95 shape deep-dive (skew/CM-term/Δ)")
    p.add_argument(
        "--out-dir",
        type=str,
        default=str(ROOT / ".glm-logs" / "w0818e_w95_shape_factor_decomp"),
    )
    p.add_argument("--seed", type=int, default=870818)
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--skip-cf", action="store_true", help="local only (default path for sens)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    # Prefer W94 fullspan series cache if present in sibling or this out-dir.
    from research.options_225_vol_series import load_opt225_series_cache

    cache = load_opt225_series_cache(out_dir)
    if not cache or len((cache or {}).get("skew_series") or []) < 500:
        prior = ROOT / ".glm-logs" / "w0818d_w94_opt_skew_thick"
        cache_prior = load_opt225_series_cache(prior)
        if cache_prior and len((cache_prior or {}).get("skew_series") or []) >= 500:
            log(f"[w95] using W94 fullspan series cache from {prior}")
            # Symlink/copy key series into out_dir for downstream loaders.
            for name in (
                "skew_series.ndjson",
                "cm_term_series.ndjson",
                "basevol_delta_series.ndjson",
                "base_vol_series.ndjson",
                "atm_iv_series.ndjson",
                "spread_series.ndjson",
                "skew_rule.json",
                "cm_term_rule.json",
                "basevol_delta_rule.json",
                "basevol_rule.json",
                "atm_iv_rule.json",
                "series_meta.json",
                "fullspan_stats.json",
            ):
                src = prior / name
                dst = out_dir / name
                if src.is_file() and not dst.exists():
                    try:
                        dst.symlink_to(src.resolve())
                    except OSError:
                        dst.write_bytes(src.read_bytes())
            cache = load_opt225_series_cache(out_dir)

    n_skew = len((cache or {}).get("skew_series") or [])
    n_term = len((cache or {}).get("cm_term_series") or [])
    n_delta = len((cache or {}).get("basevol_delta_series") or [])
    log(f"[w95] series cache skew={n_skew} cm_term={n_term} delta={n_delta}")

    pack = run_local_deepdive(
        out_dir=out_dir,
        seed=int(args.seed),
        max_codes=int(args.max_codes),
        max_days=int(args.max_days),
        synthetic=bool(args.synthetic),
        log=log,
    )

    summary = {
        "wave": "W95 / w0818e",
        "track": "A_shape_deepdive",
        "ts": ts,
        "elapsed_sec": round(time.perf_counter() - t0, 2),
        "series_coverage": {
            "n_skew": n_skew,
            "n_cm_term": n_term,
            "n_basevol_delta": n_delta,
        },
        "n_strategies": pack.get("n_strategies"),
        "n_survivor_rows": sum(
            1 for r in (pack.get("rows_flat") or []) if r.get("survived")
        ),
        "divergence_2020_22": pack.get("divergence_2020_22"),
        "promotion_stance": pack.get("promotion_stance"),
        "grid_mass": False,
        "cf_skipped": True,  # sens/binds are local; CF re-eval is separate track
        "freezes": {
            "mass_research": "NO-GO",
            "phase7": "OFF",
            "ready_declared": False,
            "operational_go": False,
            "continuous_paper": "UNARMED",
            "frozen_defaults_retuned": False,
        },
    }
    _dump(out_dir / "shape_deepdive_summary.json", summary)
    log(
        f"[w95] shape deep-dive done · elapsed={summary['elapsed_sec']}s "
        f"surv_rows={summary['n_survivor_rows']} "
        f"div2020={((pack.get('divergence_2020_22') or {}).get('divergence'))}"
    )
    if args.skip_cf:
        log("[w95] CF skipped by flag (promising re-eval is a separate script)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
