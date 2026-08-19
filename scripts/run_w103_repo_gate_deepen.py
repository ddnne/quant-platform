#!/usr/bin/env python3
"""W103 / w0819f Tracks B+C+D+E — repo-linked short cost + dispersion_gate deepen.

B. Minimal repo-linked short cost wiring
   Load date-matched ``jsda_tokyo_repo_rates`` (overnight) into bars-MTM
   short-leg daily drag for gate + sticky. Missing dates = gap/disclose
   (no invent / no ffill). Contrast table vs fixed-bp placeholder.
   Few candidates only. No cost over-tune ranking. No GO/main.

C. dispersion_gate deepen
   Main=gate, sticky=compare. Gate on/off returns/DD. Why 2023–25 activity
   higher. Coarse thresh sensitivity 2–3 pts only. With/without repo short
   if B works. No hold/mom grid. promote_as_main/go=false.

D. Constrained hyps continue (daily_path_DD required; weak-template OFF).
E. Pins frozen · MISDATE wait · projection FRESH. No GO/Mass/READY/live.

Examples
--------
    uv run python scripts/run_w103_repo_gate_deepen.py \\
        --out-dir .glm-logs/w0819f_w103_otc7_repo_gate/
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0819f_w103_otc7_repo_gate"
W100_LOG = ROOT / ".glm-logs" / "w0819c_w100_daily_path_dd_otc4"
W101_LOG = ROOT / ".glm-logs" / "w0819d_w101_otc5_dd_close"
W102_LOG = ROOT / ".glm-logs" / "w0819e_w102_otc6_event_rate_dd"
CF_WORKER_URL = "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
DB = ROOT / "data" / "structured" / "ingestion.sqlite"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402
import run_w102_dispersion_quality as w102  # noqa: E402

from research.stats_metrics import (  # noqa: E402
    equity_path_drawdown,
    evaluate_daily_path_dd_gate,
)

WAVE = "W103 / w0819f"
GATE_LOGIC = "xs_cs_dispersion_gate"
STICKY_LOGIC = "xs_rank_ls_sticky"
STICKY_STANCE = "STABLE_RESEARCH_ONLY"

GATE_SPEC: dict[str, Any] = {
    "logic_id": GATE_LOGIC,
    "family": "cross_section_relative",
    "kind": "cs_dispersion_gate",
    "hold_days": 10,
    "momentum_n": 5,
    "long_frac": 0.3,
    "short_frac": 0.3,
    "signal_sign": 1,
    "min_hist": 10,
    "catalog": False,
    "new_thesis": True,
    "why": "W100 thesis; W103 deepen (research-only; not main)",
}
STICKY_SPEC: dict[str, Any] = {
    "logic_id": STICKY_LOGIC,
    "family": "cross_section_relative",
    "kind": "cs_rank",
    "hold_days": 10,
    "momentum_n": 5,
    "long_frac": 0.3,
    "short_frac": 0.3,
    "signal_sign": 1,
    "catalog": True,
    "reference_only": True,
    "why": "STABLE_RESEARCH_ONLY comparison only; not re-promoted",
}

TX_BP = 10
SHORT_FRAC = 0.5
GROSS_LEVERAGE = 1.0
# Coarse thresh sensitivity ONLY (2–3 pts). Multiplier on trailing median.
THRESH_MULTS: tuple[float, ...] = (0.85, 1.00, 1.15)
REPO_TENOR = "overnight/翌日物/T+0"
REPO_START = "2016-01-01"  # windows start 2017; pad for hist

KNOWN_WEAK_THESIS = w100.KNOWN_WEAK_THESIS
KNOWN_DEMOTED_OR_WEAK = w100.KNOWN_DEMOTED_OR_WEAK
KNOWN_DAILY_PATH: dict[str, str] = {
    STICKY_LOGIC: "w103_deepen_this_wave",
    GATE_LOGIC: "w103_deepen_this_wave",
    "vol_risk_adjusted_mom": "w101_local_real_mirrors",
    "xs_rank_ls_daily": "w100_peer_cited",
    "xs_rank_mom_slow": "w100_peer_cited",
    "mdh_sticky_momentum": "w100_peer_cited",
    "event_post_disclosure_hold": "w102_event_rate_cited",
    "rate_curve_shape_xs": "w102_event_rate_cited",
}


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _fmt(v: Any, nd: int = 6) -> str:
    return w100._fmt(v, nd)


def _load_repo_series(*, required_dates: Sequence[str] | None = None) -> dict[str, Any]:
    """Date-matched overnight Tokyo repo → cost_models series (no ffill)."""
    from research.class_hyp_eval import load_repo_rows_from_sqlite
    from research.cost_models import load_repo_rate_series_from_rows

    rows = load_repo_rows_from_sqlite(
        DB, start=REPO_START, end=None, tenor_contains="overnight"
    )
    # Prefer exact overnight/翌日物/T+0 when present.
    filtered = [r for r in rows if str(r.get("tenor") or "") == REPO_TENOR]
    use_rows = filtered if filtered else rows
    series = load_repo_rate_series_from_rows(
        use_rows,
        required_dates=required_dates,
        tenor=REPO_TENOR if filtered else None,
        prefer_tenor=REPO_TENOR,
        source_label="local_sqlite_jsda_repo_rates",
    )
    series["tenor_preferred"] = REPO_TENOR
    series["n_rows_loaded"] = len(use_rows)
    series["wiring"] = "bars_mtm_short_leg_daily_drag"
    series["gap_policy"] = "disclose_only_no_ffill_no_invent"
    return series


def evaluate_cs_dispersion_gate_with_mask(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    thresh_mult: float = 1.0,
) -> dict[str, Any]:
    """Gate evaluator returning gate_on mask + optional thresh multiplier.

    ``on = disp >= (trailing_median * thresh_mult)`` when hist ready.
    Research-only; not a hold/mom grid.
    """
    from features.class_signals import apply_sticky_hold, cross_section_rank_signs
    from statistics import pstdev

    n = int(spec["momentum_n"])
    h = int(spec["hold_days"])
    lf = float(spec.get("long_frac") or 0.3)
    sf = float(spec.get("short_frac") or 0.3)
    sgn = 1 if int(spec.get("signal_sign") or 1) >= 0 else -1
    min_hist = int(spec.get("min_hist") or 10)
    mult = float(thresh_mult)
    panel = w100._panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
        }

    disp_hist: list[float] = []
    gate_on: dict[str, bool] = {}
    disp_by_date: dict[str, float] = {}
    thresh_by_date: dict[str, float | None] = {}
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_gated_off = 0
    for d in dates:
        moms = [m for m in (by_date.get(d) or {}).values() if m is not None]
        moms_f = [float(m) for m in moms if math.isfinite(float(m))]
        disp = float(pstdev(moms_f)) if len(moms_f) >= 2 else 0.0
        base_thresh = median(disp_hist) if len(disp_hist) >= min_hist else None
        thresh = (float(base_thresh) * mult) if base_thresh is not None else None
        on = True if thresh is None else disp >= float(thresh)
        gate_on[d] = on
        disp_by_date[d] = disp
        thresh_by_date[d] = thresh
        if not on:
            n_gated_off += 1
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        for code, sign in ranks.items():
            if not on:
                daily_rank.setdefault(code, {})[d] = 0.0
            else:
                daily_rank.setdefault(code, {})[d] = sign
        disp_hist.append(disp)

    held_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, dlist in dates_by_code.items():
        entries = [daily_rank.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        held_by_code_date[code] = {
            dlist[i]: (None if held[i] is None else float(held[i]) * sgn)
            for i in range(len(dlist))
        }
    pack = w100._held_book_daily_mtm(
        held_by_code_date=held_by_code_date,
        close_by=panel["close_by"],
        dates=dates,
        hold_days=h,
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra={
            "momentum_n": n,
            "long_frac": lf,
            "short_frac": sf,
            "signal_sign": sgn,
            "kind": spec.get("kind"),
            "new_thesis": True,
            "gate": "cs_mom_std_vs_trailing_median",
            "thresh_mult": mult,
            "min_hist": min_hist,
            "n_gated_off_days": n_gated_off,
            "n_gate_on_days": sum(1 for v in gate_on.values() if v),
            "promote_as_main": False,
            "go": False,
            "catalog": False,
        },
    )
    pack["gate_on_by_date"] = gate_on
    pack["disp_by_date"] = disp_by_date
    pack["thresh_by_date"] = thresh_by_date
    return pack


def median(xs: Sequence[float]) -> float:
    return float(statistics.median(xs))


def _apply_date_matched_short_drag(
    pack: Mapping[str, Any],
    *,
    repo_series: Mapping[str, Any] | None,
    spread_bp: float,
    short_fraction: float = SHORT_FRAC,
    mode: str = "repo_linked",
) -> dict[str, Any]:
    """Replay net path with date-matched (or fixed) short borrow drag.

    ``mode=repo_linked``: short_daily[t] = f(repo[t]+spread); gap days keep
    base net (no invent short cost). ``mode=fixed_bp``: constant annual bp
    = spread_bp (placeholder contrast).
    """
    from research.cost_models import (
        DEFAULT_TRADING_DAYS_PER_YEAR,
        lookup_repo_rate,
        short_borrow_daily_cost,
        short_borrow_daily_cost_from_repo,
    )

    dates = list(pack.get("dates") or [])
    gross = list(pack.get("gross_daily") or [])
    net0 = list(pack.get("net_daily") or [])
    drag = float(pack.get("daily_cost_drag") or 0.0)
    if not dates or not gross or len(gross) != len(dates):
        return {"status": "missing_path", "mode": mode}

    active = w102._active_mask(gross, net0, drag)
    gap_dates: list[str] = []
    applied_dates: list[str] = []
    extras: list[float] = []
    net1: list[float] = []
    eq = 1.0
    equities: list[float] = []

    for i, n in enumerate(net0):
        d = str(dates[i])[:10]
        if i == 0 or not active[i]:
            nn = float(n)
            extras.append(0.0)
        else:
            extra = 0.0
            if mode == "fixed_bp":
                extra = short_borrow_daily_cost(
                    short_borrow_annual_bp=float(spread_bp),
                    trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
                    short_fraction=short_fraction,
                )
                applied_dates.append(d)
            else:
                look = lookup_repo_rate(repo_series, d)
                if look.get("is_gap") or look.get("rate_pct") is None:
                    gap_dates.append(d)
                    extra = 0.0  # disclose gap; do not invent
                else:
                    extra = short_borrow_daily_cost_from_repo(
                        float(look["rate_pct"]),
                        short_fraction=short_fraction,
                        spread_bp=float(spread_bp),
                    )
                    applied_dates.append(d)
            nn = float(n) - float(extra)
            extras.append(float(extra))
        if i == 0:
            equities.append(eq)
            net1.append(0.0)
        else:
            eq = eq * (1.0 + nn)
            equities.append(eq)
            net1.append(nn)

    dd = equity_path_drawdown(equities, dates)
    gate = evaluate_daily_path_dd_gate(
        daily_path_dd=dd.get("max_dd"),
        dd_duration=dd.get("dd_duration_days"),
        recovered=dd.get("recovered"),
        recovery_days=dd.get("recovery_days"),
        total_ret_net=dd.get("total_return"),
        method="daily_equity_level_peak_to_trough",
    )
    rates = dict((repo_series or {}).get("rates_by_date") or {})
    applied_rates = [rates[d] for d in applied_dates if d in rates]
    return {
        "status": "ok",
        "mode": mode,
        "spread_bp": float(spread_bp),
        "short_fraction": short_fraction,
        "repo_linked": mode == "repo_linked",
        "rate_source": (
            "jsda_tokyo_repo_rates_date_matched"
            if mode == "repo_linked"
            else "fixed_bp_placeholder"
        ),
        "n_active_days": sum(1 for a in active if a),
        "n_short_cost_applied": len(applied_dates),
        "n_gaps": len(gap_dates),
        "gap_dates_sample": gap_dates[:20],
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "ffill_applied": False,
        "invent_fill": False,
        "mean_repo_pct_on_applied": (
            (sum(applied_rates) / len(applied_rates)) if applied_rates else None
        ),
        "mean_extra_daily": (
            (sum(extras[1:]) / max(1, len(extras) - 1)) if len(extras) > 1 else None
        ),
        "total_return_net": dd.get("total_return"),
        "daily_path_DD": dd.get("max_dd"),
        "dd_duration": dd.get("dd_duration_days"),
        "recovery_days": dd.get("recovery_days"),
        "recovered": dd.get("recovered"),
        "peak_date": dd.get("peak_date"),
        "trough_date": dd.get("trough_date"),
        "recovery_date": dd.get("recovery_date"),
        "daily_path_complete": gate.get("complete"),
        "n_equity_points": len(equities),
        "dates": dates,
        "equities": equities,
        "net_daily": net1,
        "promote_as_main": False,
        "go": False,
    }


def _segment_stats(
    dates: Sequence[str],
    net_daily: Sequence[float],
    mask_on: Sequence[bool],
) -> dict[str, Any]:
    """Returns/DD on gate-on vs gate-off calendar segments (research disclosure)."""
    on_nets: list[float] = []
    off_nets: list[float] = []
    on_dates: list[str] = []
    off_dates: list[str] = []
    for i in range(1, min(len(dates), len(net_daily), len(mask_on))):
        if mask_on[i]:
            on_nets.append(float(net_daily[i]))
            on_dates.append(str(dates[i])[:10])
        else:
            off_nets.append(float(net_daily[i]))
            off_dates.append(str(dates[i])[:10])

    def _path(nets: list[float], dts: list[str]) -> dict[str, Any]:
        if not nets:
            return {
                "n": 0,
                "mean_net": None,
                "total_ret": None,
                "daily_path_DD": None,
                "dd_duration": None,
                "recovered": None,
            }
        eq = 1.0
        eqs = [1.0]
        # synthetic equity over selected days only (disclosure, not tradable continuous)
        ed = [dts[0]]
        for j, r in enumerate(nets):
            eq = eq * (1.0 + r)
            eqs.append(eq)
            ed.append(dts[j])
        dd = equity_path_drawdown(eqs, ed)
        return {
            "n": len(nets),
            "mean_net": sum(nets) / len(nets),
            "total_ret": eq - 1.0,
            "daily_path_DD": dd.get("max_dd"),
            "dd_duration": dd.get("dd_duration_days"),
            "recovered": dd.get("recovered"),
            "note": (
                "Segment equity stitches selected days only — disclosure of "
                "conditional path character, not a continuous book."
            ),
        }

    return {
        "gate_on": _path(on_nets, on_dates if on_dates else [""]),
        "gate_off": _path(off_nets, off_dates if off_dates else [""]),
        "n_on": len(on_nets),
        "n_off": len(off_nets),
        "on_frac": (
            len(on_nets) / max(1, len(on_nets) + len(off_nets))
        ),
    }


def _eval_window_deep(
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    max_codes: int,
    max_days: int,
    log,
    thresh_mult: float = 1.0,
    keep_gate_mask: bool = False,
) -> dict[str, Any]:
    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(max_codes)]
    lid = str(spec["logic_id"])
    kind = str(spec.get("kind") or "")
    rows: list[dict[str, Any]] = []
    for w in w100.W100_WINDOWS:
        wid = str(w["window_id"])
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        stitch_gate_on: list[bool] = []
        stitch_disp: list[float | None] = []
        shard_summaries: list[dict[str, Any]] = []
        shard_activity: list[dict[str, Any]] = []
        shard_packs: list[dict[str, Any]] = []
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append({"period_id": pid, "status": loaded.get("status")})
                continue
            if kind == "cs_dispersion_gate":
                pack = evaluate_cs_dispersion_gate_with_mask(
                    loaded["bars"],
                    spec=spec,
                    one_way_cost=float(one_way_cost),
                    thresh_mult=float(thresh_mult),
                )
            else:
                pack = w100.evaluate_spec_on_bars(
                    loaded["bars"], spec=spec, one_way_cost=float(one_way_cost)
                )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            summary["thresh_mult"] = float(thresh_mult)
            shard_summaries.append(summary)
            act = w102._activity_from_pack(pack)
            act["period_id"] = pid
            shard_activity.append(act)
            dlist = list(pack.get("dates") or [])
            nlist = list(pack.get("net_daily") or [])
            glist = list(pack.get("gross_daily") or [])
            gate_map = dict(pack.get("gate_on_by_date") or {})
            disp_map = dict(pack.get("disp_by_date") or {})
            if not stitch_dates:
                stitch_dates = list(dlist)
                stitch_net = list(nlist)
                stitch_gross = list(glist)
                stitch_gate_on = [bool(gate_map.get(d, True)) for d in dlist]
                stitch_disp = [disp_map.get(d) for d in dlist]
            else:
                stitch_dates.extend(dlist[1:])
                stitch_net.extend(nlist[1:])
                stitch_gross.extend(glist[1:])
                stitch_gate_on.extend([bool(gate_map.get(d, True)) for d in dlist[1:]])
                stitch_disp.extend([disp_map.get(d) for d in dlist[1:]])
            shard_packs.append(
                {
                    "period_id": pid,
                    "dates": dlist,
                    "equities": list(pack.get("equities") or []),
                    "gross_daily": glist,
                    "net_daily": nlist,
                    "daily_cost_drag": pack.get("daily_cost_drag"),
                    "n_gated_off_days": pack.get("n_gated_off_days"),
                    "n_gate_on_days": pack.get("n_gate_on_days"),
                    "gate_on_by_date": gate_map if keep_gate_mask else None,
                }
            )
            log(
                f"[w103]   {lid} {wid}/{pid} thresh×{thresh_mult}: "
                f"n={summary.get('n_equity_points')} "
                f"DD={_fmt(summary.get('daily_path_DD'))} "
                f"net={_fmt(summary.get('total_return_net'))} "
                f"act={act.get('n_active_days')}/{act.get('n_calendar_days')}"
            )
        stitched = w100._stitch_net(stitch_net, stitch_dates)
        char = w102.dd_interval_character(
            stitched.get("equities") or [], stitch_dates
        )
        n_cal = max(0, len(stitch_dates) - 1)
        n_act = sum(int(a.get("n_active_days") or 0) for a in shard_activity)
        n_off = sum(
            int(a["n_gated_off_days"])
            for a in shard_activity
            if a.get("n_gated_off_days") is not None
        )
        n_on = sum(
            int(a["n_gate_on_days"])
            for a in shard_activity
            if a.get("n_gate_on_days") is not None
        )
        has_gate = any(a.get("n_gate_on_days") is not None for a in shard_activity)
        disp_vals = [float(x) for x in stitch_disp if x is not None]
        row: dict[str, Any] = {
            "logic_id": lid,
            "window": wid,
            "label": w["label"],
            "thresh_mult": float(thresh_mult),
            "n_days": stitched.get("n_equity_points"),
            "daily_path_DD": stitched.get("daily_path_DD"),
            "dd_duration": stitched.get("dd_duration"),
            "recovery_days": stitched.get("recovery_days"),
            "recovered": stitched.get("recovered"),
            "total_ret_net": stitched.get("total_return_net"),
            "peak_date": stitched.get("peak_date"),
            "trough_date": stitched.get("trough_date"),
            "recovery_date": stitched.get("recovery_date"),
            "daily_path_complete": (stitched.get("daily_path_dd_gate") or {}).get(
                "complete"
            ),
            "n_active_days": n_act,
            "n_calendar_days": n_cal,
            "active_frac": (n_act / n_cal) if n_cal else None,
            "n_gated_off_days": n_off if has_gate else None,
            "n_gate_on_days": n_on if has_gate else None,
            "gate_on_frac": (
                (n_on / (n_on + n_off)) if has_gate and (n_on + n_off) else None
            ),
            "disp_mean": (sum(disp_vals) / len(disp_vals)) if disp_vals else None,
            "disp_median": float(statistics.median(disp_vals)) if disp_vals else None,
            "dd_character": {
                k: char[k]
                for k in char
                if k != "episodes"
            },
            "n_dd_episodes": char.get("n_episodes"),
            "time_underwater_frac": char.get("time_underwater_frac"),
            "max_episode_duration": char.get("max_episode_duration"),
            "median_episode_duration": char.get("median_episode_duration"),
            "promote_as_main": False,
            "go": False,
            "stance": STICKY_STANCE if lid == STICKY_LOGIC else "RESEARCH_ONLY",
            "data_path": "local_real_mirrors",
            "one_way_cost": float(one_way_cost),
            "shard_summaries": shard_summaries,
            "_path": {
                "dates": stitch_dates,
                "equities": stitched.get("equities") or [],
                "net_daily": stitch_net,
                "gross_daily": stitch_gross,
                "gate_on": stitch_gate_on if has_gate else None,
                "disp": stitch_disp if has_gate else None,
                "shard_packs": shard_packs,
            },
        }
        if has_gate and stitch_gate_on:
            row["gate_on_off_segments"] = _segment_stats(
                stitch_dates, stitch_net, stitch_gate_on
            )
        rows.append(row)
    return {"logic_id": lid, "thresh_mult": float(thresh_mult), "table": rows}


def run_deepen(
    *,
    out_dir: Path,
    max_codes: int,
    max_days: int,
    log,
) -> dict[str, Any]:
    from research.cost_models import (
        DEFAULT_SHORT_BORROW_ANNUAL_BP,
        SHORT_BORROW_SPREAD_SENSITIVITY,
        build_leverage_short_cost_assumption,
        POSITION_STYLE_LONG_SHORT,
    )

    one_way = TX_BP / 10_000.0
    log(
        f"[w103/C] deepen main={GATE_LOGIC} compare={STICKY_LOGIC} "
        f"thresh_mults={list(THRESH_MULTS)} hold_mom_grid=false"
    )

    # --- base paths (thresh×1.0) keep masks ---
    base_by_logic: dict[str, dict[str, Any]] = {}
    for spec in (GATE_SPEC, STICKY_SPEC):
        pack = _eval_window_deep(
            spec=spec,
            one_way_cost=one_way,
            max_codes=max_codes,
            max_days=max_days,
            log=log,
            thresh_mult=1.0,
            keep_gate_mask=True,
        )
        base_by_logic[str(spec["logic_id"])] = pack
        slim = [
            {k: v for k, v in r.items() if not str(k).startswith("_")}
            for r in pack["table"]
        ]
        _dump(out_dir / f"deepen_{spec['logic_id']}_base.json", slim)

    # --- thresh sensitivity (gate only; 2–3 coarse pts) ---
    thresh_rows: list[dict[str, Any]] = []
    for mult in THRESH_MULTS:
        if abs(mult - 1.0) < 1e-12:
            pack = base_by_logic[GATE_LOGIC]
        else:
            pack = _eval_window_deep(
                spec=GATE_SPEC,
                one_way_cost=one_way,
                max_codes=max_codes,
                max_days=max_days,
                log=log,
                thresh_mult=float(mult),
                keep_gate_mask=False,
            )
        for r in pack["table"]:
            thresh_rows.append(
                {
                    "logic_id": GATE_LOGIC,
                    "window": r["window"],
                    "thresh_mult": r["thresh_mult"],
                    "daily_path_DD": r["daily_path_DD"],
                    "dd_duration": r["dd_duration"],
                    "recovery_days": r["recovery_days"],
                    "recovered": r["recovered"],
                    "total_ret_net": r["total_ret_net"],
                    "n_days": r["n_days"],
                    "active_frac": r["active_frac"],
                    "gate_on_frac": r["gate_on_frac"],
                    "n_gate_on_days": r["n_gate_on_days"],
                    "n_gated_off_days": r["n_gated_off_days"],
                    "disp_mean": r.get("disp_mean"),
                    "disp_median": r.get("disp_median"),
                    "daily_path_complete": r["daily_path_complete"],
                    "promote_as_main": False,
                    "go": False,
                    "note": (
                        "Coarse thresh sensitivity only (×0.85/1.00/1.15 on "
                        "trailing median). Not a hold/mom grid."
                    ),
                }
            )
    _dump(out_dir / "deepen_thresh_sensitivity.json", thresh_rows)

    # --- gate on/off + sticky conditional ---
    onoff_rows: list[dict[str, Any]] = []
    activity_why: list[dict[str, Any]] = []
    gate_table = base_by_logic[GATE_LOGIC]["table"]
    sticky_table = base_by_logic[STICKY_LOGIC]["table"]
    sticky_by_w = {r["window"]: r for r in sticky_table}
    for gr in gate_table:
        wid = gr["window"]
        gpath = gr.get("_path") or {}
        spath = (sticky_by_w.get(wid) or {}).get("_path") or {}
        g_on = list(gpath.get("gate_on") or [])
        g_dates = list(gpath.get("dates") or [])
        g_net = list(gpath.get("net_daily") or [])
        s_net = list(spath.get("net_daily") or [])
        s_dates = list(spath.get("dates") or [])
        # Align sticky to gate dates if needed
        if s_dates == g_dates and g_on:
            sticky_cond = _segment_stats(s_dates, s_net, g_on)
        else:
            sticky_cond = {
                "note": "date_align_miss",
                "gate_on": {},
                "gate_off": {},
            }
        gate_seg = gr.get("gate_on_off_segments") or {}
        onoff_rows.append(
            {
                "window": wid,
                "gate_book_segments": gate_seg,
                "sticky_conditional_on_gate_mask": sticky_cond,
                "gate_on_frac": gr.get("gate_on_frac"),
                "gate_active_frac": gr.get("active_frac"),
                "sticky_active_frac": (sticky_by_w.get(wid) or {}).get("active_frac"),
                "gate_daily_path_DD": gr.get("daily_path_DD"),
                "sticky_daily_path_DD": (sticky_by_w.get(wid) or {}).get(
                    "daily_path_DD"
                ),
                "promote_as_main": False,
                "go": False,
            }
        )
        disp_vals = [float(x) for x in (gpath.get("disp") or []) if x is not None]
        activity_why.append(
            {
                "window": wid,
                "gate_on_frac": gr.get("gate_on_frac"),
                "active_frac": gr.get("active_frac"),
                "disp_mean": gr.get("disp_mean"),
                "disp_median": gr.get("disp_median"),
                "disp_p75": (
                    float(statistics.quantiles(disp_vals, n=4)[2])
                    if len(disp_vals) >= 4
                    else None
                ),
                "n_gate_on_days": gr.get("n_gate_on_days"),
                "n_gated_off_days": gr.get("n_gated_off_days"),
                "why_note": (
                    "Higher activity when CS mom dispersion spends more time "
                    "at/above its PIT trailing median (gate_on_frac↑ → "
                    "active_frac↑). 2023–25 is not 'safer' — just more often on."
                ),
            }
        )
    _dump(out_dir / "deepen_gate_on_off.json", onoff_rows)
    _dump(out_dir / "deepen_activity_why.json", activity_why)

    # --- B: repo-linked short cost wiring ---
    all_dates: list[str] = []
    for pack in base_by_logic.values():
        for r in pack["table"]:
            all_dates.extend(list((r.get("_path") or {}).get("dates") or []))
    all_dates_u = sorted(set(str(d)[:10] for d in all_dates))
    repo_series = _load_repo_series(required_dates=all_dates_u)
    rates_map = dict(repo_series.get("rates_by_date") or {})
    meta = {
        k: repo_series.get(k)
        for k in (
            "kind",
            "version",
            "dataset",
            "table",
            "tenor",
            "tenor_preferred",
            "rate_type",
            "source_label",
            "n_obs",
            "n_rows_loaded",
            "n_gaps",
            "coverage_complete",
            "ffill_applied",
            "invent_fill",
            "gap_policy",
            "wiring",
        )
    }
    meta.update(
        {
            "gap_dates_sample": list(repo_series.get("gap_dates") or [])[:30],
            "n_required": len(all_dates_u),
            "present_required_n": len(repo_series.get("present_required_dates") or []),
            "rate_span": [min(rates_map), max(rates_map)] if rates_map else None,
        }
    )
    _dump(out_dir / "repo_series_meta.json", meta)

    repo_ok = int(repo_series.get("n_obs") or 0) > 0
    contrast_rows: list[dict[str, Any]] = []
    mid_spread = float(SHORT_BORROW_SPREAD_SENSITIVITY["mid"])

    if repo_ok:
        log(
            f"[w103/B] repo series n_obs={repo_series.get('n_obs')} "
            f"gaps_on_required={repo_series.get('n_gaps')} "
            f"tenor={REPO_TENOR} (no ffill)"
        )
        for lid, pack in base_by_logic.items():
            for r in pack["table"]:
                path = r.get("_path") or {}
                shard_packs = list(path.get("shard_packs") or [])
                if not shard_packs:
                    continue
                for mode in ("repo_linked", "fixed_bp"):
                    stitch_dates: list[str] = []
                    stitch_net: list[float] = []
                    gap_n = 0
                    applied_n = 0
                    for sp in shard_packs:
                        replay = _apply_date_matched_short_drag(
                            {
                                "dates": sp.get("dates") or [],
                                "gross_daily": sp.get("gross_daily") or [],
                                "net_daily": sp.get("net_daily") or [],
                                "daily_cost_drag": sp.get("daily_cost_drag") or 0.0,
                            },
                            repo_series=repo_series,
                            spread_bp=mid_spread,
                            short_fraction=SHORT_FRAC,
                            mode=mode,
                        )
                        gap_n += int(replay.get("n_gaps") or 0)
                        applied_n += int(replay.get("n_short_cost_applied") or 0)
                        dlist = list(replay.get("dates") or [])
                        nlist = list(replay.get("net_daily") or [])
                        if not stitch_dates:
                            stitch_dates = list(dlist)
                            stitch_net = list(nlist)
                        else:
                            stitch_dates.extend(dlist[1:])
                            stitch_net.extend(nlist[1:])
                    stitched = w100._stitch_net(stitch_net, stitch_dates)
                    contrast_rows.append(
                        {
                            "logic_id": lid,
                            "window": r["window"],
                            "mode": mode,
                            "spread_bp": mid_spread,
                            "short_fraction": SHORT_FRAC,
                            "gross_leverage": GROSS_LEVERAGE,
                            "daily_path_DD": stitched.get("daily_path_DD"),
                            "dd_duration": stitched.get("dd_duration"),
                            "recovery_days": stitched.get("recovery_days"),
                            "recovered": stitched.get("recovered"),
                            "total_ret_net": stitched.get("total_return_net"),
                            "n_days": stitched.get("n_equity_points"),
                            "daily_path_complete": (
                                stitched.get("daily_path_dd_gate") or {}
                            ).get("complete"),
                            "n_short_cost_applied": applied_n,
                            "n_gaps": gap_n,
                            "rate_source": (
                                "jsda_tokyo_repo_rates_date_matched"
                                if mode == "repo_linked"
                                else "fixed_bp_placeholder"
                            ),
                            "repo_linked": mode == "repo_linked",
                            "base_tx_only_DD": r.get("daily_path_DD"),
                            "base_tx_only_net": r.get("total_ret_net"),
                            "note": (
                                "Contrast only. mid spread=50bp. Gaps not invented. "
                                "Not a ranking-by-cost-tune. Not GO/main."
                            ),
                            "promote_as_main": False,
                            "go": False,
                        }
                    )
    else:
        log("[w103/B] repo series UNAVAILABLE — document inability; fixed-bp only")
        for lid, pack in base_by_logic.items():
            for r in pack["table"]:
                contrast_rows.append(
                    {
                        "logic_id": lid,
                        "window": r["window"],
                        "mode": "fixed_bp_only_repo_unavailable",
                        "repo_linked": False,
                        "inability_reason": "jsda_repo_rates empty or unloadable",
                        "daily_path_DD": r.get("daily_path_DD"),
                        "total_ret_net": r.get("total_ret_net"),
                        "promote_as_main": False,
                        "go": False,
                    }
                )

    _dump(out_dir / "repo_short_contrast_table.json", contrast_rows)

    lev_ass = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_SHORT,
        gross_leverage=GROSS_LEVERAGE,
        short_fraction=SHORT_FRAC,
        one_way_cost=one_way,
        uses_short=True,
        uses_leverage=False,
        short_borrow_sensitivity="mid",
        prefer_repo_linked=True,
        prefer_liquidity_linked=False,
        repo_rate_series=repo_series if repo_ok else None,
    )
    _dump(
        out_dir / "repo_short_assumption.json",
        {
            "position_style": POSITION_STYLE_LONG_SHORT,
            "gross_leverage": GROSS_LEVERAGE,
            "short_fraction": SHORT_FRAC,
            "uses_short": True,
            "uses_leverage": False,
            "short_borrow_placeholder_annual_bp": DEFAULT_SHORT_BORROW_ANNUAL_BP,
            "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
            "repo_linked_wired": bool(repo_ok),
            "repo_tenor": REPO_TENOR,
            "over_tune": False,
            "ranking_by_cost_tune": False,
            "assumption_repo_linked": lev_ass.get("repo_linked"),
            "assumption_complete": lev_ass.get("assumptions_complete"),
            "note": (
                "Minimal wiring of JSDA Tokyo overnight repo into bars-MTM "
                "short drag. Gaps disclosed. Contrast vs fixed 50bp mid. "
                "No cost over-tune ranking. Not GO/main."
            ),
        },
    )

    # compare table (base tx 10bp)
    compare: list[dict[str, Any]] = []
    for lid in (GATE_LOGIC, STICKY_LOGIC):
        for r in base_by_logic[lid]["table"]:
            compare.append(
                {
                    "logic_id": lid,
                    "window": r["window"],
                    "n_days": r["n_days"],
                    "daily_path_DD": r["daily_path_DD"],
                    "dd_duration": r["dd_duration"],
                    "recovery_days": r["recovery_days"],
                    "recovered": r["recovered"],
                    "total_ret_net": r["total_ret_net"],
                    "peak_date": r["peak_date"],
                    "trough_date": r["trough_date"],
                    "n_active_days": r["n_active_days"],
                    "active_frac": r["active_frac"],
                    "n_gated_off_days": r["n_gated_off_days"],
                    "n_gate_on_days": r["n_gate_on_days"],
                    "gate_on_frac": r["gate_on_frac"],
                    "disp_mean": r.get("disp_mean"),
                    "disp_median": r.get("disp_median"),
                    "daily_path_complete": r["daily_path_complete"],
                    "stance": r["stance"],
                    "promote_as_main": False,
                    "go": False,
                }
            )
    _dump(out_dir / "deepen_compare_table.json", compare)

    def _worst(lid: str) -> dict[str, Any]:
        rows = [r for r in compare if r["logic_id"] == lid]
        return min(rows, key=lambda x: float(x["daily_path_DD"] or 0.0))

    gate_worst = _worst(GATE_LOGIC)
    sticky_worst = _worst(STICKY_LOGIC)

    # with/without repo short headline (mid only; not pick-best)
    repo_mid = [
        r
        for r in contrast_rows
        if r.get("mode") == "repo_linked" and r.get("logic_id") == GATE_LOGIC
    ]
    fixed_mid = [
        r
        for r in contrast_rows
        if r.get("mode") == "fixed_bp" and r.get("logic_id") == GATE_LOGIC
    ]

    summary = {
        "wave": WAVE,
        "track": "B_repo_short + C_dispersion_deepen",
        "main_logic": GATE_LOGIC,
        "compare_logic": STICKY_LOGIC,
        "promote_as_main": False,
        "go": False,
        "hold_mom_microgrid": False,
        "full_catalog_grid": False,
        "cost_over_tune": False,
        "ranking_by_cost_tune": False,
        "gate_worst_window": gate_worst["window"],
        "gate_worst_daily_path_DD": gate_worst["daily_path_DD"],
        "sticky_worst_window": sticky_worst["window"],
        "sticky_worst_daily_path_DD": sticky_worst["daily_path_DD"],
        "sticky_stance": STICKY_STANCE,
        "thresh_mults": list(THRESH_MULTS),
        "repo_linked_wired": bool(repo_ok),
        "repo_tenor": REPO_TENOR,
        "repo_n_obs": repo_series.get("n_obs"),
        "repo_n_gaps_on_required": repo_series.get("n_gaps"),
        "uniformly_safer": False,
        "note_not_uniformly_safer": (
            "Gate is NOT uniformly safer than sticky. 2017–19 shallower DD; "
            "2023–25 often worse / more active. Better-in-some-windows ≠ main."
        ),
        "compare": compare,
        "thresh_sensitivity": thresh_rows,
        "repo_short_contrast": contrast_rows,
        "gate_repo_mid_rows": repo_mid,
        "gate_fixed_mid_rows": fixed_mid,
        "activity_why": activity_why,
    }
    _dump(out_dir / "deepen_summary.json", summary)
    log(
        f"[w103/C] gate worst DD={_fmt(gate_worst['daily_path_DD'])} "
        f"({gate_worst['window']}) sticky worst="
        f"{_fmt(sticky_worst['daily_path_DD'])} ({sticky_worst['window']}) "
        f"repo_wired={repo_ok} promote=false go=false"
    )
    return {
        "summary": summary,
        "compare": compare,
        "repo_ok": repo_ok,
        "repo_series": repo_series,
        "base_by_logic": base_by_logic,
        "contrast_rows": contrast_rows,
    }


def _cite_known_daily(
    logic_id: str,
    quality_compare: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    src = KNOWN_DAILY_PATH.get(logic_id)
    if not src:
        return None
    if src == "w103_deepen_this_wave":
        rows = [dict(r) for r in quality_compare if r.get("logic_id") == logic_id]
        complete = bool(rows) and all(bool(r.get("daily_path_complete")) for r in rows)
        return {
            "logic_id": logic_id,
            "daily_path_source": src,
            "daily_path_DD_required": True,
            "daily_path_complete": complete,
            "windows": rows,
            "promote_as_main": False,
            "go": False,
        }
    if src == "w101_local_real_mirrors":
        p = W101_LOG / "vol_risk_adjusted_mom_daily_dd.json"
        rows = json.loads(p.read_text()) if p.is_file() else []
        complete = bool(rows) and all(bool(r.get("daily_path_complete")) for r in rows)
        return {
            "logic_id": logic_id,
            "daily_path_source": src,
            "daily_path_DD_required": True,
            "daily_path_complete": complete,
            "windows": rows,
            "promote_as_main": False,
            "go": False,
        }
    if src == "w100_peer_cited":
        p = W100_LOG / "peer_daily_dd_table.json"
        table = json.loads(p.read_text()) if p.is_file() else []
        rows = [r for r in table if r.get("logic_id") == logic_id]
        complete = bool(rows) and all(bool(r.get("daily_path_complete")) for r in rows)
        return {
            "logic_id": logic_id,
            "daily_path_source": src,
            "daily_path_DD_required": True,
            "daily_path_complete": complete,
            "windows": rows,
            "promote_as_main": False,
            "go": False,
        }
    if src == "w102_event_rate_cited":
        # Cite W102 event/rate daily tables if present
        for name in (
            "event_post_disclosure_hold_daily_dd.json",
            "rate_curve_shape_xs_daily_dd.json",
            "event_rate_daily_dd_table.json",
        ):
            p = W102_LOG / name
            if not p.is_file():
                continue
            raw = json.loads(p.read_text())
            if isinstance(raw, list):
                rows = [r for r in raw if r.get("logic_id") == logic_id]
            elif isinstance(raw, dict):
                rows = [
                    r
                    for r in (raw.get("table") or raw.get("rows") or [])
                    if r.get("logic_id") == logic_id
                ]
            else:
                rows = []
            if rows:
                complete = all(bool(r.get("daily_path_complete")) for r in rows)
                return {
                    "logic_id": logic_id,
                    "daily_path_source": src,
                    "daily_path_DD_required": True,
                    "daily_path_complete": complete,
                    "windows": rows,
                    "promote_as_main": False,
                    "go": False,
                }
        return None
    return None


def run_hyp_pack(
    *,
    out_dir: Path,
    n_hyps: int,
    provider: str,
    model: str | None,
    seed: int,
    synthetic: bool,
    quality_compare: Sequence[Mapping[str, Any]],
    log,
) -> dict[str, Any]:
    from research.llm_hyp_generator import (
        LLM_HYP_VERSION,
        LLM_HYP_WAVE,
        detect_api_keys,
        generate_and_evaluate_hypotheses,
    )
    from research.mass_strategy_factory import (
        CONTINUOUS_PAPER,
        FROZEN_DEFAULT_PATH,
        MASS_RESEARCH,
    )

    keys = detect_api_keys()
    key_presence = {k: bool(v) for k, v in keys.items()}
    _dump(out_dir / "api_keys_present.json", key_presence)
    resolved_provider = provider
    if provider == "auto" and key_presence.get("xai"):
        resolved_provider = "xai"
    log(
        f"[w103/D] new pack n={n_hyps} provider={resolved_provider} "
        f"wave={LLM_HYP_WAVE} ver={LLM_HYP_VERSION} "
        f"weak_template_mapping=OFF not_a_count_race=True"
    )
    gen_eval = generate_and_evaluate_hypotheses(
        n=int(n_hyps),
        provider=None if resolved_provider == "auto" else resolved_provider,
        model=model,
        worker_url=CF_WORKER_URL,
        evaluate=True,
        synthetic=bool(synthetic),
        map_unknown_to_nearest_catalog=True,
    )
    gen_compact = {
        k: gen_eval[k]
        for k in gen_eval
        if k
        not in {
            "eval_results",
            "eval_screens",
            "proposals_for_eval",
            "accepted_proposals",
            "rejected_proposals",
        }
    }
    _dump(out_dir / "llm_hyp_generation.json", gen_compact)
    _dump(out_dir / "llm_hyp_proposals.json", gen_eval.get("proposals_for_eval") or [])
    _dump(out_dir / "llm_hyp_eval_ranking.json", gen_eval.get("eval_ranking") or [])
    _dump(out_dir / "llm_hyp_eval_screens.json", gen_eval.get("eval_screens") or [])
    _dump(out_dir / "llm_hyp_accepted_proposals.json", gen_eval.get("accepted_proposals") or [])
    _dump(out_dir / "llm_hyp_rejected_proposals.json", gen_eval.get("rejected_proposals") or [])

    n_proposed = int(gen_eval.get("n_proposed") or 0)
    n_accepted = int(gen_eval.get("n_accepted") or 0)
    n_survivors = int(gen_eval.get("n_survivors") or 0)
    theses = list(gen_eval.get("representative_theses") or [])
    n_skipped_weak = int(gen_eval.get("n_skipped_weak_catalog_map") or 0)

    demoted_weak_mapped: list[str] = []
    skipped_ids: list[str] = []
    mapped_ids: list[str] = []
    for p in gen_eval.get("proposals_for_eval") or []:
        if not isinstance(p, Mapping):
            continue
        if p.get("skipped_weak_catalog_map"):
            skipped_ids.append(str(p.get("skipped_weak_catalog_map")))
        lid = str(p.get("logic_id") or "")
        if p.get("eval_mapped_to_catalog") and lid in KNOWN_DEMOTED_OR_WEAK:
            mapped_ids.append(lid)

    survivor_daily: list[dict[str, Any]] = []
    for s in gen_eval.get("eval_screens") or []:
        if not isinstance(s, Mapping) or not s.get("survived"):
            continue
        lid = str(s.get("logic_id") or "")
        if lid in KNOWN_DEMOTED_OR_WEAK or lid in KNOWN_WEAK_THESIS:
            demoted_weak_mapped.append(lid)
        cited = _cite_known_daily(lid, quality_compare)
        if cited is not None:
            cited["survived_period_net_screen"] = True
            cited["mapped_from_period_net"] = True
            survivor_daily.append(cited)
            continue
        gate = evaluate_daily_path_dd_gate(period_net_dd=s.get("mean_net"))
        survivor_daily.append(
            {
                "logic_id": lid,
                "survived_period_net_screen": True,
                "daily_path_source": None,
                "daily_path_DD_required": True,
                "daily_path_complete": False,
                "incomplete_reason": (
                    "period-net eval screen only; daily_path_DD unmeasured "
                    "for this mapped logic. Incomplete — not main / not GO. "
                    "period_net_DD-only cannot pass."
                ),
                "gate": {
                    "complete": gate.get("complete"),
                    "fails": gate.get("fails"),
                    "warnings": gate.get("warnings"),
                    "period_net_dd_only_pass_forbidden": True,
                },
                "promote_as_main": False,
                "go": False,
            }
        )

    n_daily_complete = sum(1 for r in survivor_daily if r.get("daily_path_complete"))
    summary = {
        "wave": WAVE,
        "track": "D_new_failure_constrained_hyps",
        "provider": gen_eval.get("provider"),
        "model": gen_eval.get("model"),
        "llm_hyp_version": LLM_HYP_VERSION,
        "n_requested": int(n_hyps),
        "n_proposed": n_proposed,
        "n_accepted": n_accepted,
        "n_rejected_generation": n_proposed - n_accepted,
        "n_evaluated": gen_eval.get("n_evaluated"),
        "n_survivors": n_survivors,
        "n_survivors_daily_path_complete": n_daily_complete,
        "n_skipped_weak_catalog_map": n_skipped_weak or len(skipped_ids),
        "skipped_weak_catalog_targets": sorted(set(skipped_ids)),
        "weak_mapped_despite_off": sorted(set(mapped_ids)),
        "representative_theses": theses,
        "demoted_weak_mapped_survivors": sorted(set(demoted_weak_mapped)),
        "do_not_resurrect_as_main": True,
        "weak_template_mapping": "OFF",
        "reduce_weak_template_mapping": True,
        "not_a_count_race": True,
        "failure_mode_constraints": [
            "no_sign_flip_single_regime_reliance",
            "no_soft_eq_pressure",
            "no_low_var_t_trust",
            "no_window_only",
            "no_dual_options_level",
            "no_repolish_shape_rate_flow_demoted_fund_slow",
            "no_hold_mom_frac_grid",
            "weak_template_mapping_off",
            "daily_path_DD_required",
        ],
        "routed_through": "propose_profit_hypotheses",
        "gates": ["cost", "PIT", "low_var", "daily_path_DD"],
        "daily_path_DD_required": True,
        "period_net_dd_only_pass_forbidden": True,
        "survivor_daily_path": survivor_daily,
        "frozen_defaults_retuned": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "mass_research": MASS_RESEARCH,
        "continuous_paper": CONTINUOUS_PAPER,
        "promote_as_main": False,
        "go": False,
        "seed": int(seed),
        "note": (
            "Modest N. Weak-template mapping OFF. Period-net survival is not "
            "a pass. daily_path_DD required. Survivors research-only · not main/GO."
        ),
    }
    _dump(out_dir / "hyp_summary.json", summary)
    log(
        f"[w103/D] n_proposed={n_proposed} n_accepted={n_accepted} "
        f"n_survivors={n_survivors} daily_complete={n_daily_complete} "
        f"skipped_weak={summary['n_skipped_weak_catalog_map']} "
        f"model={gen_eval.get('model')}"
    )
    for th in theses[:8]:
        log(f"  · {th.get('logic_id')}: {str(th.get('thesis') or '')[:120]}")
    return {"summary": summary, "gen_eval": gen_eval}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--n-hyps", type=int, default=4)
    p.add_argument("--seed", type=int, default=8908193)
    p.add_argument("--provider", type=str, default="xai")
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-deepen", action="store_true")
    p.add_argument("--skip-misdate", action="store_true")
    p.add_argument("--skip-projection", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w103_repo_gate_deepen.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = w100._assert_frozen_pins_untouched()
    pins["note"] = "W103 deepen/repo/hyps must not mutate 3-default pins"
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w103] pins_untouched={pins['pins_untouched']}")
    log(
        "[w103] promote_as_main=false go=false hold_mom_grid=false "
        "weak_template_mapping=OFF cost_over_tune=false "
        "GLM implementer only. Grok did not implement."
    )

    deepen: dict[str, Any] | None = None
    if not args.skip_deepen:
        deepen = run_deepen(
            out_dir=out_dir,
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            log=log,
        )
    else:
        log("[w103/BC] deepen/repo skipped")

    hyp_pack: dict[str, Any] | None = None
    if not args.skip_hyps:
        hyp_pack = run_hyp_pack(
            out_dir=out_dir,
            n_hyps=int(args.n_hyps),
            provider=str(args.provider),
            model=args.model,
            seed=int(args.seed),
            synthetic=bool(args.synthetic),
            quality_compare=(deepen or {}).get("compare") or [],
            log=log,
        )
    else:
        log("[w103/D] hyps skipped")

    misdate: dict[str, Any] | None = None
    if not args.skip_misdate:
        misdate = w100.run_misdate_reprobe(out_dir=out_dir, log=log)
        if isinstance(misdate, dict):
            misdate["wave"] = WAVE
            _dump(out_dir / "master_misdate_probe.json", misdate)
    else:
        log("[w103/E] MISDATE skipped")

    projection: dict[str, Any] | None = None
    if not args.skip_projection:
        projection = w100.refresh_projection(out_dir=out_dir, log=log)
    else:
        log("[w103/E] projection skipped")

    pins_after = w100._assert_frozen_pins_untouched()
    pins_after["note"] = "W103 after deepen/repo/hyps; 3-default pins must match"
    _dump(out_dir / "frozen_pins_assert_after.json", pins_after)

    summary = {
        "wave": WAVE,
        "tracks": "B_repo_short + C_dispersion_deepen + D_hyps + E_pins_misdate_projection",
        "hold_mom_microgrid": False,
        "full_catalog_grid": False,
        "cost_over_tune": False,
        "ranking_by_cost_tune": False,
        "weak_template_mapping": "OFF",
        "not_a_count_race": True,
        "pins_untouched": pins_after.get("pins_untouched"),
        "deepen": (deepen or {}).get("summary") if deepen else None,
        "hyps": (hyp_pack or {}).get("summary") if hyp_pack else None,
        "misdate": {
            k: misdate.get(k)
            for k in (
                "action",
                "sealed_n",
                "before_after",
                "dataset_complete_claimed",
                "floor_raise_to_2008_05",
            )
        }
        if misdate
        else None,
        "projection": {
            "status": (projection or {}).get("status"),
            "returncode": (projection or {}).get("returncode"),
        }
        if projection
        else None,
        "promote_as_main": False,
        "go": False,
        "mass": "NO-GO",
        "ready": False,
        "continuous_paper": "UNARMED",
        "implementer": "GLM5.3",
        "orchestrator_implemented": False,
        "wall_sec": round(time.time() - t0, 1),
    }
    _dump(out_dir / "w103_bcde_summary.json", summary)
    log(
        f"[w103] done wall={summary['wall_sec']}s "
        f"pins={pins_after.get('pins_untouched')}"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
