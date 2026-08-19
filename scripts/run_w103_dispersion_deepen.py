#!/usr/bin/env python3
"""W103 / w0819f Tracks C+D — dispersion_gate deepen + constrained hyps.

C. Deeper dive of ``xs_cs_dispersion_gate`` (research-only; no GO):
   * Gate on/off interval returns & daily DD (sticky comparison only)
   * Explain higher activity in w2023_2025 (dispersion drivers)
   * Coarse thresh sensitivity — 3 points only (thresh_mult 0.9/1.0/1.1;
     no grid mass / no hold-mom grid)
   * If local jsda_repo_rates exists: with/without repo-linked short contrast
     (W78/W85 parallel-track model; gaps disclosed, never invent-filled)
   promote_as_main=false · go=false · never claim uniformly safe

D. Failure-constrained hyps (modest N). Weak-template mapping OFF.
   Propose → eval with daily_path_DD REQUIRED. Survivors research-only.

Examples
--------
    uv run python scripts/run_w103_dispersion_deepen.py \\
        --out-dir .glm-logs/w0819f_w103_otc7_repo_gate/
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
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
SQLITE_PATH = ROOT / "data" / "structured" / "ingestion.sqlite"

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

GATE_SPEC_BASE: dict[str, Any] = {
    "logic_id": GATE_LOGIC,
    "family": "cross_section_relative",
    "kind": "cs_dispersion_gate",
    "hold_days": 10,
    "momentum_n": 5,
    "long_frac": 0.3,
    "short_frac": 0.3,
    "signal_sign": 1,
    "min_hist": 10,
    "thresh_mult": 1.0,
    "catalog": False,
    "new_thesis": True,
    "why": "W100 thesis; W103 deepen (research-only; not uniformly safer)",
}
STICKY_SPEC: dict[str, Any] = dict(w102.STICKY_SPEC)

# Coarse thresh sensitivity — 3 points ONLY. Not a grid.
THRESH_MULT_POINTS: tuple[tuple[str, float, str], ...] = (
    ("looser_0p9", 0.9, "trailing median ×0.9 → more gate-on"),
    ("base_1p0", 1.0, "catalog/base trailing median (W100/W102)"),
    ("tighter_1p1", 1.1, "trailing median ×1.1 → fewer gate-on"),
)
BASE_TX_BP: int = 10
SHORT_FRAC: float = 0.5
GROSS_LEVERAGE: float = 1.0
REPO_PREFER_TENOR: str = "overnight/翌日物/T+0"

KNOWN_WEAK_THESIS = w100.KNOWN_WEAK_THESIS
KNOWN_DEMOTED_OR_WEAK = w100.KNOWN_DEMOTED_OR_WEAK

KNOWN_DAILY_PATH: dict[str, str] = {
    STICKY_LOGIC: "w103_deepen_this_wave",
    GATE_LOGIC: "w103_deepen_this_wave",
    "vol_risk_adjusted_mom": "w101_local_real_mirrors",
    "xs_rank_ls_daily": "w100_peer_cited",
    "xs_rank_mom_slow": "w100_peer_cited",
    "mdh_sticky_momentum": "w100_peer_cited",
    "event_post_disclosure_hold": "w102_track_b_event_rate",
    "rate_curve_shape_xs": "w102_track_b_event_rate",
}


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _fmt(v: Any, nd: int = 6) -> str:
    return w100._fmt(v, nd)


def _pctile(vals: Sequence[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(float(x) for x in vals)
    if not s:
        return None
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (float(p) / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return s[lo]
    w = k - lo
    return s[lo] * (1.0 - w) + s[hi] * w


def _path_stats_from_nets(
    nets: Sequence[float],
    dates: Sequence[str],
) -> dict[str, Any]:
    if not nets or not dates or len(nets) != len(dates):
        return {
            "n_equity_points": 0,
            "total_return_net": None,
            "daily_path_DD": None,
            "daily_path_complete": False,
        }
    eq = 1.0
    equities: list[float] = []
    for i, n in enumerate(nets):
        if i == 0:
            equities.append(eq)
        else:
            eq = eq * (1.0 + float(n))
            equities.append(eq)
    dd = equity_path_drawdown(equities, list(dates))
    gate = evaluate_daily_path_dd_gate(
        daily_path_dd=dd.get("max_dd"),
        dd_duration=dd.get("dd_duration_days"),
        recovered=dd.get("recovered"),
        recovery_days=dd.get("recovery_days"),
        total_ret_net=dd.get("total_return"),
        method="daily_equity_level_peak_to_trough",
    )
    return {
        "n_equity_points": len(equities),
        "total_return_net": dd.get("total_return"),
        "daily_path_DD": dd.get("max_dd"),
        "dd_duration": dd.get("dd_duration_days"),
        "recovery_days": dd.get("recovery_days"),
        "recovered": dd.get("recovered"),
        "peak_date": dd.get("peak_date"),
        "trough_date": dd.get("trough_date"),
        "recovery_date": dd.get("recovery_date"),
        "daily_path_complete": gate.get("complete"),
        "equities": equities,
    }


def _run_lengths(flags: Sequence[bool]) -> dict[str, Any]:
    runs_on: list[int] = []
    runs_off: list[int] = []
    if not flags:
        return {
            "n_on_runs": 0,
            "n_off_runs": 0,
            "mean_on_run": None,
            "mean_off_run": None,
            "max_on_run": None,
            "max_off_run": None,
        }
    cur = flags[0]
    length = 1
    for f in flags[1:]:
        if f == cur:
            length += 1
        else:
            (runs_on if cur else runs_off).append(length)
            cur = f
            length = 1
    (runs_on if cur else runs_off).append(length)
    return {
        "n_on_runs": len(runs_on),
        "n_off_runs": len(runs_off),
        "mean_on_run": (sum(runs_on) / len(runs_on)) if runs_on else None,
        "mean_off_run": (sum(runs_off) / len(runs_off)) if runs_off else None,
        "max_on_run": max(runs_on) if runs_on else None,
        "max_off_run": max(runs_off) if runs_off else None,
        "median_on_run": (
            float(statistics.median(runs_on)) if runs_on else None
        ),
        "median_off_run": (
            float(statistics.median(runs_off)) if runs_off else None
        ),
    }


def _eval_window_diag(
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    max_codes: int,
    max_days: int,
    log,
    keep_path: bool,
    keep_gate_diag: bool,
) -> dict[str, Any]:
    """Like w102._eval_window but can keep gate diagnostics."""
    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(max_codes)]
    lid = str(spec["logic_id"])
    spec_local = dict(spec)
    if keep_gate_diag:
        spec_local["keep_gate_diag"] = True
    rows: list[dict[str, Any]] = []
    for w in w100.W100_WINDOWS:
        wid = str(w["window_id"])
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        stitch_gate_on: dict[str, bool] = {}
        stitch_disp: dict[str, float] = {}
        stitch_thresh: dict[str, float | None] = {}
        shard_summaries: list[dict[str, Any]] = []
        shard_activity: list[dict[str, Any]] = []
        shard_packs: list[dict[str, Any]] = []
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append(
                    {"period_id": pid, "status": loaded.get("status")}
                )
                continue
            pack = w100.evaluate_spec_on_bars(
                loaded["bars"], spec=spec_local, one_way_cost=float(one_way_cost)
            )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            summary["thresh_mult"] = pack.get("thresh_mult")
            shard_summaries.append(summary)
            act = w102._activity_from_pack(pack)
            act["period_id"] = pid
            shard_activity.append(act)
            dlist = list(pack.get("dates") or [])
            nlist = list(pack.get("net_daily") or [])
            glist = list(pack.get("gross_daily") or [])
            if not stitch_dates:
                stitch_dates = list(dlist)
                stitch_net = list(nlist)
                stitch_gross = list(glist)
            else:
                stitch_dates.extend(dlist[1:])
                stitch_net.extend(nlist[1:])
                stitch_gross.extend(glist[1:])
            if keep_gate_diag:
                go = pack.get("gate_on_by_date") or {}
                dd = pack.get("disp_by_date") or {}
                th = pack.get("thresh_by_date") or {}
                for d in dlist:
                    if d in go:
                        stitch_gate_on[d] = bool(go[d])
                    if d in dd:
                        stitch_disp[d] = float(dd[d])
                    if d in th:
                        stitch_thresh[d] = th[d]
            if keep_path:
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
                    }
                )
            log(
                f"[w103/C]   {lid} thr={spec_local.get('thresh_mult', 1.0)} "
                f"{wid}/{pid}: n={summary.get('n_equity_points')} "
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
        row: dict[str, Any] = {
            "logic_id": lid,
            "window": wid,
            "label": w["label"],
            "data_note": w["data_note"],
            "thresh_mult": float(spec_local.get("thresh_mult") or 1.0),
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
        }
        if keep_path:
            row["_path"] = {
                "dates": stitch_dates,
                "equities": stitched.get("equities") or [],
                "net_daily": stitch_net,
                "gross_daily": stitch_gross,
                "shard_packs": shard_packs,
            }
            row["_episodes"] = char.get("episodes") or []
        if keep_gate_diag:
            row["_gate_diag"] = {
                "gate_on_by_date": stitch_gate_on,
                "disp_by_date": stitch_disp,
                "thresh_by_date": stitch_thresh,
            }
        rows.append(row)
    return {"logic_id": lid, "table": rows}


def _conditional_path_from_sticky(
    *,
    sticky_dates: Sequence[str],
    sticky_net: Sequence[float],
    gate_on_by_date: Mapping[str, bool],
    keep_when_on: bool,
) -> dict[str, Any]:
    """Replay sticky nets only on gate-on (or gate-off) days; else flat."""
    nets: list[float] = []
    n_kept = 0
    n_flat = 0
    for i, d in enumerate(sticky_dates):
        if i == 0:
            nets.append(0.0)
            continue
        # Position from prior day drives today's return (W99/W100 MTM).
        prior = sticky_dates[i - 1]
        on = bool(gate_on_by_date.get(prior, False))
        keep = on if keep_when_on else (not on)
        if keep:
            nets.append(float(sticky_net[i]))
            n_kept += 1
        else:
            nets.append(0.0)
            n_flat += 1
    stats = _path_stats_from_nets(nets, sticky_dates)
    return {
        "mode": "gate_on_days" if keep_when_on else "gate_off_days",
        "n_kept_days": n_kept,
        "n_flat_days": n_flat,
        "total_return_net": stats.get("total_return_net"),
        "daily_path_DD": stats.get("daily_path_DD"),
        "dd_duration": stats.get("dd_duration"),
        "recovery_days": stats.get("recovery_days"),
        "recovered": stats.get("recovered"),
        "peak_date": stats.get("peak_date"),
        "trough_date": stats.get("trough_date"),
        "recovery_date": stats.get("recovery_date"),
        "daily_path_complete": stats.get("daily_path_complete"),
        "n_equity_points": stats.get("n_equity_points"),
        "note": (
            "Sticky CS L-S daily net kept only when prior-day dispersion gate "
            f"was {'ON' if keep_when_on else 'OFF'}; else flat. "
            "Interval returns & daily_path_DD of the conditional book."
        ),
    }


def _gate_interval_returns(
    *,
    sticky_dates: Sequence[str],
    sticky_net: Sequence[float],
    gate_on_by_date: Mapping[str, bool],
) -> dict[str, Any]:
    """Per contiguous gate-on / gate-off interval: cum ret + interval DD."""
    if len(sticky_dates) < 2:
        return {"on_intervals": [], "off_intervals": []}

    def _intervals(want_on: bool) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        i = 1
        while i < len(sticky_dates):
            prior = sticky_dates[i - 1]
            if bool(gate_on_by_date.get(prior, False)) != want_on:
                i += 1
                continue
            start_i = i
            eq = 1.0
            peak = 1.0
            trough = 1.0
            trough_i = i
            while i < len(sticky_dates):
                prior = sticky_dates[i - 1]
                if bool(gate_on_by_date.get(prior, False)) != want_on:
                    break
                eq = eq * (1.0 + float(sticky_net[i]))
                if eq > peak:
                    peak = eq
                if eq < trough:
                    trough = eq
                    trough_i = i
                i += 1
            end_i = i - 1
            out.append(
                {
                    "start_date": sticky_dates[start_i],
                    "end_date": sticky_dates[end_i],
                    "n_days": int(end_i - start_i + 1),
                    "cum_ret": eq - 1.0,
                    "interval_DD": (trough / peak - 1.0) if peak else None,
                    "trough_date": sticky_dates[trough_i],
                    "gate_state": "ON" if want_on else "OFF",
                }
            )
        return out

    on_iv = _intervals(True)
    off_iv = _intervals(False)

    def _summ(ivs: list[dict[str, Any]]) -> dict[str, Any]:
        if not ivs:
            return {
                "n_intervals": 0,
                "mean_cum_ret": None,
                "median_cum_ret": None,
                "worst_cum_ret": None,
                "worst_interval_DD": None,
                "mean_n_days": None,
            }
        rets = [float(x["cum_ret"]) for x in ivs]
        dds = [
            float(x["interval_DD"])
            for x in ivs
            if x.get("interval_DD") is not None
        ]
        nd = [int(x["n_days"]) for x in ivs]
        return {
            "n_intervals": len(ivs),
            "mean_cum_ret": sum(rets) / len(rets),
            "median_cum_ret": float(statistics.median(rets)),
            "worst_cum_ret": min(rets),
            "worst_interval_DD": min(dds) if dds else None,
            "mean_n_days": sum(nd) / len(nd),
            "max_n_days": max(nd),
        }

    return {
        "on_intervals": on_iv,
        "off_intervals": off_iv,
        "on_summary": _summ(on_iv),
        "off_summary": _summ(off_iv),
    }


def _disp_driver_stats(
    *,
    window: str,
    gate_diag: Mapping[str, Any],
    gate_row: Mapping[str, Any],
) -> dict[str, Any]:
    disp_map = gate_diag.get("disp_by_date") or {}
    thresh_map = gate_diag.get("thresh_by_date") or {}
    on_map = gate_diag.get("gate_on_by_date") or {}
    dates = sorted(disp_map.keys())
    disps = [float(disp_map[d]) for d in dates]
    threshs = [
        float(thresh_map[d])
        for d in dates
        if thresh_map.get(d) is not None
    ]
    flags = [bool(on_map.get(d, False)) for d in dates]
    # Excess vs trailing thresh (positive → gate tends ON)
    excess: list[float] = []
    for d in dates:
        th = thresh_map.get(d)
        if th is None:
            continue
        excess.append(float(disp_map[d]) - float(th))
    runs = _run_lengths(flags)
    return {
        "window": window,
        "n_scored_days": len(dates),
        "disp_mean": (sum(disps) / len(disps)) if disps else None,
        "disp_median": float(statistics.median(disps)) if disps else None,
        "disp_p10": _pctile(disps, 10),
        "disp_p90": _pctile(disps, 90),
        "disp_std": float(statistics.pstdev(disps)) if len(disps) >= 2 else None,
        "thresh_mean": (sum(threshs) / len(threshs)) if threshs else None,
        "thresh_median": float(statistics.median(threshs)) if threshs else None,
        "excess_mean": (sum(excess) / len(excess)) if excess else None,
        "excess_median": float(statistics.median(excess)) if excess else None,
        "frac_excess_pos": (
            sum(1 for e in excess if e >= 0) / len(excess) if excess else None
        ),
        "gate_on_frac": gate_row.get("gate_on_frac"),
        "active_frac": gate_row.get("active_frac"),
        "n_gate_on_days": gate_row.get("n_gate_on_days"),
        "n_gated_off_days": gate_row.get("n_gated_off_days"),
        "run_lengths": runs,
        "promote_as_main": False,
        "go": False,
    }


def _load_repo_series(
    required_dates: Sequence[str],
) -> dict[str, Any]:
    from research.cost_models import load_repo_rate_series_from_rows

    if not SQLITE_PATH.is_file():
        return {
            "status": "missing_sqlite",
            "repo_linked": False,
            "n_obs": 0,
            "gap_dates": list(required_dates),
            "n_gaps": len(required_dates),
            "rates_by_date": {},
        }
    con = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    try:
        if not required_dates:
            rows_raw = con.execute(
                "SELECT as_of_date, tenor, rate_type, rate FROM jsda_repo_rates"
            ).fetchall()
        else:
            lo = min(required_dates)
            hi = max(required_dates)
            rows_raw = con.execute(
                "SELECT as_of_date, tenor, rate_type, rate FROM jsda_repo_rates "
                "WHERE as_of_date BETWEEN ? AND ?",
                (lo, hi),
            ).fetchall()
    finally:
        con.close()
    rows = [
        {
            "as_of_date": r[0],
            "tenor": r[1],
            "rate_type": r[2],
            "rate": r[3],
        }
        for r in rows_raw
    ]
    series = load_repo_rate_series_from_rows(
        rows,
        required_dates=list(required_dates),
        prefer_tenor=REPO_PREFER_TENOR,
        source_label="local_sqlite_jsda_repo_rates",
    )
    series["status"] = "ok" if int(series.get("n_obs") or 0) > 0 else "empty"
    series["repo_linked"] = int(series.get("n_obs") or 0) > 0
    series["sqlite_path"] = str(SQLITE_PATH)
    series["prefer_tenor"] = REPO_PREFER_TENOR
    return series


def _apply_repo_short_drag(
    pack_path: Mapping[str, Any],
    *,
    repo_series: Mapping[str, Any],
    spread_bp: float,
    short_fraction: float,
) -> dict[str, Any]:
    """Date-matched repo+spread short drag on active days; gaps → no invent."""
    from research.cost_models import (
        lookup_repo_rate,
        short_borrow_daily_cost,
        short_borrow_daily_cost_from_repo,
    )

    dates = list(pack_path.get("dates") or [])
    gross = list(pack_path.get("gross_daily") or [])
    net0 = list(pack_path.get("net_daily") or [])
    drag = float(pack_path.get("daily_cost_drag") or 0.0)
    if not dates or not gross or len(gross) != len(dates):
        return {"status": "missing_path", "repo_linked_applied": False}
    active = w102._active_mask(gross, net0, drag)
    rates = dict(repo_series.get("rates_by_date") or {})
    # Fixed mid placeholder for with/without contrast baseline.
    fixed_extra = short_borrow_daily_cost(
        short_borrow_annual_bp=float(spread_bp),
        short_fraction=float(short_fraction),
    )

    net_repo: list[float] = []
    net_fixed: list[float] = []
    eq_repo = 1.0
    eq_fixed = 1.0
    eq_none = 1.0
    equities_repo: list[float] = []
    equities_fixed: list[float] = []
    equities_none: list[float] = []
    n_repo_applied = 0
    n_gap = 0
    n_active = 0
    for i, n in enumerate(net0):
        if i == 0 or not active[i]:
            nn_repo = float(n)
            nn_fixed = float(n)
            nn_none = float(n)
        else:
            n_active += 1
            # Prior-day position → today's return; match repo to prior date
            # when available, else today (same-day PIT ok for overnight).
            d_look = dates[i - 1] if i > 0 else dates[i]
            hit = lookup_repo_rate({"rates_by_date": rates}, d_look)
            if hit.get("is_gap") or hit.get("rate_pct") is None:
                # Gap: do not invent — leave tx-only net (disclose).
                nn_repo = float(n)
                n_gap += 1
            else:
                extra = short_borrow_daily_cost_from_repo(
                    float(hit["rate_pct"]),
                    short_fraction=float(short_fraction),
                    spread_bp=float(spread_bp),
                )
                nn_repo = float(n) - float(extra)
                n_repo_applied += 1
            nn_fixed = float(n) - float(fixed_extra)
            nn_none = float(n)
        if i == 0:
            equities_repo.append(eq_repo)
            equities_fixed.append(eq_fixed)
            equities_none.append(eq_none)
            net_repo.append(0.0)
            net_fixed.append(0.0)
        else:
            eq_repo = eq_repo * (1.0 + nn_repo)
            eq_fixed = eq_fixed * (1.0 + nn_fixed)
            eq_none = eq_none * (1.0 + nn_none)
            equities_repo.append(eq_repo)
            equities_fixed.append(eq_fixed)
            equities_none.append(eq_none)
            net_repo.append(nn_repo)
            net_fixed.append(nn_fixed)

    def _summ(equities: list[float], label: str) -> dict[str, Any]:
        dd = equity_path_drawdown(equities, dates)
        gate = evaluate_daily_path_dd_gate(
            daily_path_dd=dd.get("max_dd"),
            dd_duration=dd.get("dd_duration_days"),
            recovered=dd.get("recovered"),
            recovery_days=dd.get("recovery_days"),
            total_ret_net=dd.get("total_return"),
            method="daily_equity_level_peak_to_trough",
        )
        return {
            "label": label,
            "total_return_net": dd.get("total_return"),
            "daily_path_DD": dd.get("max_dd"),
            "dd_duration": dd.get("dd_duration_days"),
            "recovery_days": dd.get("recovery_days"),
            "recovered": dd.get("recovered"),
            "peak_date": dd.get("peak_date"),
            "trough_date": dd.get("trough_date"),
            "daily_path_complete": gate.get("complete"),
        }

    return {
        "status": "ok",
        "spread_bp": float(spread_bp),
        "short_fraction": float(short_fraction),
        "n_active_days": n_active,
        "n_repo_applied": n_repo_applied,
        "n_repo_gaps_on_active": n_gap,
        "repo_gap_frac_active": (n_gap / n_active) if n_active else None,
        "without_short": _summ(equities_none, "tx_only_no_short"),
        "with_fixed_placeholder": _summ(
            equities_fixed, "fixed_bp_placeholder_mid"
        ),
        "with_repo_linked": _summ(equities_repo, "repo_plus_spread_mid"),
        "repo_linked": True,
        "invent_fill": False,
        "ffill_applied": False,
        "promote_as_main": False,
        "go": False,
    }


def run_deepen(
    *,
    out_dir: Path,
    max_codes: int,
    max_days: int,
    log,
) -> dict[str, Any]:
    from research.cost_models import (
        DEFAULT_SHORT_BORROW_SPREAD_BP,
        SHORT_BORROW_SPREAD_SENSITIVITY,
    )

    base_one_way = BASE_TX_BP / 10_000.0
    log(
        f"[w103/C] deepen main={GATE_LOGIC} compare={STICKY_LOGIC} "
        f"thresh_points={[t[0] for t in THRESH_MULT_POINTS]} "
        f"hold_mom_grid=false promote=false go=false"
    )

    # --- base gate (diag) + sticky ---
    gate_spec = dict(GATE_SPEC_BASE)
    gate_spec["keep_gate_diag"] = True
    gate_pack = _eval_window_diag(
        spec=gate_spec,
        one_way_cost=base_one_way,
        max_codes=max_codes,
        max_days=max_days,
        log=log,
        keep_path=True,
        keep_gate_diag=True,
    )
    sticky_pack = _eval_window_diag(
        spec=STICKY_SPEC,
        one_way_cost=base_one_way,
        max_codes=max_codes,
        max_days=max_days,
        log=log,
        keep_path=True,
        keep_gate_diag=False,
    )

    base_compare: list[dict[str, Any]] = []
    for pack in (gate_pack, sticky_pack):
        for r in pack["table"]:
            base_compare.append(
                {
                    k: v
                    for k, v in r.items()
                    if not str(k).startswith("_")
                }
            )
    _dump(out_dir / "deepen_base_compare.json", base_compare)

    # --- gate on/off interval returns & conditional DD ---
    onoff_rows: list[dict[str, Any]] = []
    interval_by_window: dict[str, Any] = {}
    sticky_by_window = {r["window"]: r for r in sticky_pack["table"]}
    for gr in gate_pack["table"]:
        wid = str(gr["window"])
        sr = sticky_by_window.get(wid) or {}
        gdiag = gr.get("_gate_diag") or {}
        spath = sr.get("_path") or {}
        s_dates = list(spath.get("dates") or [])
        s_net = list(spath.get("net_daily") or [])
        on_map = gdiag.get("gate_on_by_date") or {}
        if not s_dates or not on_map:
            continue
        cond_on = _conditional_path_from_sticky(
            sticky_dates=s_dates,
            sticky_net=s_net,
            gate_on_by_date=on_map,
            keep_when_on=True,
        )
        cond_off = _conditional_path_from_sticky(
            sticky_dates=s_dates,
            sticky_net=s_net,
            gate_on_by_date=on_map,
            keep_when_on=False,
        )
        intervals = _gate_interval_returns(
            sticky_dates=s_dates,
            sticky_net=s_net,
            gate_on_by_date=on_map,
        )
        # Compact intervals for dump (drop long lists in summary row)
        interval_by_window[wid] = {
            "on_summary": intervals["on_summary"],
            "off_summary": intervals["off_summary"],
            "worst_on_intervals": sorted(
                intervals["on_intervals"],
                key=lambda x: float(x.get("cum_ret") or 0.0),
            )[:3],
            "worst_off_intervals": sorted(
                intervals["off_intervals"],
                key=lambda x: float(x.get("cum_ret") or 0.0),
            )[:3],
            "best_on_intervals": sorted(
                intervals["on_intervals"],
                key=lambda x: float(x.get("cum_ret") or 0.0),
                reverse=True,
            )[:3],
            "n_on_intervals": len(intervals["on_intervals"]),
            "n_off_intervals": len(intervals["off_intervals"]),
        }
        onoff_rows.append(
            {
                "window": wid,
                "gate_on_frac": gr.get("gate_on_frac"),
                "gate_active_frac": gr.get("active_frac"),
                "gate_total_ret_net": gr.get("total_ret_net"),
                "gate_daily_path_DD": gr.get("daily_path_DD"),
                "sticky_total_ret_net": sr.get("total_ret_net"),
                "sticky_daily_path_DD": sr.get("daily_path_DD"),
                "sticky_on_gate_on_days": cond_on,
                "sticky_on_gate_off_days": cond_off,
                "interval_summary": {
                    "on": intervals["on_summary"],
                    "off": intervals["off_summary"],
                },
                "promote_as_main": False,
                "go": False,
                "uniformly_safer": False,
            }
        )
    _dump(out_dir / "deepen_gate_onoff_returns.json", onoff_rows)
    _dump(out_dir / "deepen_gate_intervals.json", interval_by_window)

    # --- activity drivers (esp. w2023_2025) ---
    driver_rows: list[dict[str, Any]] = []
    for gr in gate_pack["table"]:
        driver_rows.append(
            _disp_driver_stats(
                window=str(gr["window"]),
                gate_diag=gr.get("_gate_diag") or {},
                gate_row=gr,
            )
        )
    # Cross-window explanation block
    by_w = {r["window"]: r for r in driver_rows}
    w23 = by_w.get("w2023_2025") or {}
    w17 = by_w.get("w2017_2019") or {}
    w20 = by_w.get("w2020_2022") or {}
    activity_explain = {
        "focus_window": "w2023_2025",
        "observation": (
            "Gate active_frac and gate_on_frac are highest in w2023_2025 "
            f"(active={_fmt(w23.get('active_frac'), 3)}, "
            f"gate_on={_fmt(w23.get('gate_on_frac'), 3)}) vs "
            f"w2017_2019 (active={_fmt(w17.get('active_frac'), 3)}, "
            f"gate_on={_fmt(w17.get('gate_on_frac'), 3)}) / "
            f"w2020_2022 (active={_fmt(w20.get('active_frac'), 3)}, "
            f"gate_on={_fmt(w20.get('gate_on_frac'), 3)})."
        ),
        "drivers": {
            "disp_mean": {
                "w2017_2019": w17.get("disp_mean"),
                "w2020_2022": w20.get("disp_mean"),
                "w2023_2025": w23.get("disp_mean"),
            },
            "disp_median": {
                "w2017_2019": w17.get("disp_median"),
                "w2020_2022": w20.get("disp_median"),
                "w2023_2025": w23.get("disp_median"),
            },
            "disp_p90": {
                "w2017_2019": w17.get("disp_p90"),
                "w2020_2022": w20.get("disp_p90"),
                "w2023_2025": w23.get("disp_p90"),
            },
            "excess_mean_vs_trailing_thresh": {
                "w2017_2019": w17.get("excess_mean"),
                "w2020_2022": w20.get("excess_mean"),
                "w2023_2025": w23.get("excess_mean"),
            },
            "frac_days_disp_ge_thresh": {
                "w2017_2019": w17.get("frac_excess_pos"),
                "w2020_2022": w20.get("frac_excess_pos"),
                "w2023_2025": w23.get("frac_excess_pos"),
            },
            "mean_gate_on_run_days": {
                "w2017_2019": (w17.get("run_lengths") or {}).get("mean_on_run"),
                "w2020_2022": (w20.get("run_lengths") or {}).get("mean_on_run"),
                "w2023_2025": (w23.get("run_lengths") or {}).get("mean_on_run"),
            },
            "max_gate_on_run_days": {
                "w2017_2019": (w17.get("run_lengths") or {}).get("max_on_run"),
                "w2020_2022": (w20.get("run_lengths") or {}).get("max_on_run"),
                "w2023_2025": (w23.get("run_lengths") or {}).get("max_on_run"),
            },
        },
        "interpretation": (
            "Higher 2023–25 activity is driven by more days with CS mom-std "
            "at/above the PIT trailing median (higher frac_excess_pos / "
            "gate_on_frac), plus longer contiguous gate-on runs — not by a "
            "hold/mom retune. Elevated dispersion regimes keep the gate open; "
            "the book therefore looks more like sticky and inherits sticky-like "
            "path DD (W102: gate worst −11.4% slightly deeper than sticky "
            "−10.8% in the same window). Not uniformly safer."
        ),
        "promote_as_main": False,
        "go": False,
        "uniformly_safer": False,
    }
    _dump(out_dir / "deepen_activity_drivers.json", driver_rows)
    _dump(out_dir / "deepen_activity_explain_w2023_2025.json", activity_explain)

    # --- coarse thresh sensitivity (3 points) ---
    thresh_rows: list[dict[str, Any]] = []
    for tag, mult, why in THRESH_MULT_POINTS:
        spec = dict(GATE_SPEC_BASE)
        spec["thresh_mult"] = float(mult)
        spec["logic_id"] = GATE_LOGIC  # same id; tag separates rows
        if abs(float(mult) - 1.0) < 1e-12:
            pack = gate_pack  # reuse base
        else:
            pack = _eval_window_diag(
                spec=spec,
                one_way_cost=base_one_way,
                max_codes=max_codes,
                max_days=max_days,
                log=log,
                keep_path=False,
                keep_gate_diag=False,
            )
        for r in pack["table"]:
            thresh_rows.append(
                {
                    "tag": tag,
                    "thresh_mult": float(mult),
                    "why": why,
                    "logic_id": GATE_LOGIC,
                    "window": r["window"],
                    "daily_path_DD": r["daily_path_DD"],
                    "dd_duration": r["dd_duration"],
                    "recovery_days": r["recovery_days"],
                    "recovered": r["recovered"],
                    "total_ret_net": r["total_ret_net"],
                    "n_days": r["n_days"],
                    "n_active_days": r["n_active_days"],
                    "active_frac": r["active_frac"],
                    "n_gate_on_days": r["n_gate_on_days"],
                    "gate_on_frac": r["gate_on_frac"],
                    "daily_path_complete": r["daily_path_complete"],
                    "promote_as_main": False,
                    "go": False,
                    "grid_mass": False,
                }
            )
    # Sticky reference rows (no thresh) for side-by-side
    for r in sticky_pack["table"]:
        thresh_rows.append(
            {
                "tag": "sticky_reference",
                "thresh_mult": None,
                "why": "STABLE_RESEARCH_ONLY comparison only",
                "logic_id": STICKY_LOGIC,
                "window": r["window"],
                "daily_path_DD": r["daily_path_DD"],
                "dd_duration": r["dd_duration"],
                "recovery_days": r["recovery_days"],
                "recovered": r["recovered"],
                "total_ret_net": r["total_ret_net"],
                "n_days": r["n_days"],
                "n_active_days": r["n_active_days"],
                "active_frac": r["active_frac"],
                "n_gate_on_days": None,
                "gate_on_frac": None,
                "daily_path_complete": r["daily_path_complete"],
                "promote_as_main": False,
                "go": False,
                "grid_mass": False,
            }
        )
    _dump(out_dir / "deepen_thresh_sensitivity.json", thresh_rows)

    # --- repo short with/without contrast (if series exists) ---
    all_dates: list[str] = []
    for r in gate_pack["table"]:
        all_dates.extend(list((r.get("_path") or {}).get("dates") or []))
    for r in sticky_pack["table"]:
        all_dates.extend(list((r.get("_path") or {}).get("dates") or []))
    req_dates = sorted({str(d)[:10] for d in all_dates if d})
    repo_series = _load_repo_series(req_dates)
    _dump(
        out_dir / "deepen_repo_series_meta.json",
        {
            k: repo_series.get(k)
            for k in (
                "status",
                "repo_linked",
                "n_obs",
                "n_gaps",
                "coverage_complete",
                "tenor",
                "rate_type",
                "prefer_tenor",
                "source_label",
                "ffill_applied",
                "invent_fill",
                "gap_policy",
                "sqlite_path",
                "n_input_rows",
                "n_dates_from_rows",
            )
            if k in repo_series or True
        },
    )
    repo_contrast_rows: list[dict[str, Any]] = []
    repo_available = bool(repo_series.get("repo_linked"))
    if repo_available:
        log(
            f"[w103/C] repo series available n_obs={repo_series.get('n_obs')} "
            f"gaps={repo_series.get('n_gaps')} tenor={repo_series.get('tenor')}"
        )
        mid_spread = float(
            SHORT_BORROW_SPREAD_SENSITIVITY.get(
                "mid", DEFAULT_SHORT_BORROW_SPREAD_BP
            )
        )
        for lid, pack in (
            (GATE_LOGIC, gate_pack),
            (STICKY_LOGIC, sticky_pack),
        ):
            for r in pack["table"]:
                path = r.get("_path") or {}
                # Stitch-level path (already combined); apply drag on stitched
                # active mask. For shard fidelity we could loop shard_packs —
                # stitched is consistent with W102 base method.
                replay = _apply_repo_short_drag(
                    {
                        "dates": path.get("dates") or [],
                        "gross_daily": path.get("gross_daily") or [],
                        "net_daily": path.get("net_daily") or [],
                        "daily_cost_drag": (
                            # reconstruct from first shard if present
                            (path.get("shard_packs") or [{}])[0].get(
                                "daily_cost_drag"
                            )
                            or 0.0
                        ),
                    },
                    repo_series=repo_series,
                    spread_bp=mid_spread,
                    short_fraction=SHORT_FRAC,
                )
                # Fix daily_cost_drag from any shard_pack
                sps = list(path.get("shard_packs") or [])
                if sps:
                    # Prefer replaying per-shard then stitch (matches W102)
                    stitch_dates_r: list[str] = []
                    stitch_net_repo: list[float] = []
                    stitch_net_fixed: list[float] = []
                    stitch_net_none: list[float] = []
                    n_applied = 0
                    n_gap = 0
                    n_act = 0
                    from research.cost_models import (
                        lookup_repo_rate,
                        short_borrow_daily_cost,
                        short_borrow_daily_cost_from_repo,
                    )

                    fixed_extra = short_borrow_daily_cost(
                        short_borrow_annual_bp=mid_spread,
                        short_fraction=SHORT_FRAC,
                    )
                    rates = dict(repo_series.get("rates_by_date") or {})
                    for sp in sps:
                        dlist = list(sp.get("dates") or [])
                        glist = list(sp.get("gross_daily") or [])
                        nlist = list(sp.get("net_daily") or [])
                        drag = float(sp.get("daily_cost_drag") or 0.0)
                        active = w102._active_mask(glist, nlist, drag)
                        net_r: list[float] = []
                        net_f: list[float] = []
                        net_n: list[float] = []
                        for i, n in enumerate(nlist):
                            if i == 0 or not active[i]:
                                net_r.append(float(n) if i == 0 else float(n))
                                net_f.append(float(n) if i == 0 else float(n))
                                net_n.append(float(n) if i == 0 else float(n))
                                if i == 0:
                                    net_r[-1] = 0.0
                                    net_f[-1] = 0.0
                                    net_n[-1] = 0.0
                                continue
                            n_act += 1
                            d_look = dlist[i - 1]
                            hit = lookup_repo_rate(
                                {"rates_by_date": rates}, d_look
                            )
                            if hit.get("is_gap") or hit.get("rate_pct") is None:
                                net_r.append(float(n))
                                n_gap += 1
                            else:
                                extra = short_borrow_daily_cost_from_repo(
                                    float(hit["rate_pct"]),
                                    short_fraction=SHORT_FRAC,
                                    spread_bp=mid_spread,
                                )
                                net_r.append(float(n) - float(extra))
                                n_applied += 1
                            net_f.append(float(n) - float(fixed_extra))
                            net_n.append(float(n))
                        if not stitch_dates_r:
                            stitch_dates_r = list(dlist)
                            stitch_net_repo = list(net_r)
                            stitch_net_fixed = list(net_f)
                            stitch_net_none = list(net_n)
                        else:
                            stitch_dates_r.extend(dlist[1:])
                            stitch_net_repo.extend(net_r[1:])
                            stitch_net_fixed.extend(net_f[1:])
                            stitch_net_none.extend(net_n[1:])

                    def _s(nets: list[float], label: str) -> dict[str, Any]:
                        st = w100._stitch_net(nets, stitch_dates_r)
                        return {
                            "label": label,
                            "total_return_net": st.get("total_return_net"),
                            "daily_path_DD": st.get("daily_path_DD"),
                            "dd_duration": st.get("dd_duration"),
                            "recovery_days": st.get("recovery_days"),
                            "recovered": st.get("recovered"),
                            "peak_date": st.get("peak_date"),
                            "trough_date": st.get("trough_date"),
                            "daily_path_complete": (
                                st.get("daily_path_dd_gate") or {}
                            ).get("complete"),
                        }

                    replay = {
                        "status": "ok",
                        "spread_bp": mid_spread,
                        "short_fraction": SHORT_FRAC,
                        "n_active_days": n_act,
                        "n_repo_applied": n_applied,
                        "n_repo_gaps_on_active": n_gap,
                        "repo_gap_frac_active": (
                            (n_gap / n_act) if n_act else None
                        ),
                        "without_short": _s(
                            stitch_net_none, "tx_only_no_short"
                        ),
                        "with_fixed_placeholder": _s(
                            stitch_net_fixed, "fixed_bp_placeholder_mid"
                        ),
                        "with_repo_linked": _s(
                            stitch_net_repo, "repo_plus_spread_mid"
                        ),
                        "repo_linked": True,
                        "invent_fill": False,
                        "ffill_applied": False,
                        "promote_as_main": False,
                        "go": False,
                    }
                repo_contrast_rows.append(
                    {
                        "logic_id": lid,
                        "window": r["window"],
                        **replay,
                    }
                )
    else:
        log("[w103/C] repo series NOT available — skip with/without contrast")
        repo_contrast_rows.append(
            {
                "status": "skipped_no_repo_series",
                "repo_linked": False,
                "note": (
                    "jsda_repo_rates not loadable; fixed-bp placeholder "
                    "remains the W102 disclosure. Gaps not invented."
                ),
                "promote_as_main": False,
                "go": False,
            }
        )
    _dump(out_dir / "deepen_repo_short_contrast.json", repo_contrast_rows)

    # --- headline ---
    def _worst(lid: str) -> dict[str, Any]:
        rows = [r for r in base_compare if r["logic_id"] == lid]
        return min(rows, key=lambda x: float(x["daily_path_DD"] or 0.0))

    gate_worst = _worst(GATE_LOGIC)
    sticky_worst = _worst(STICKY_LOGIC)
    # Uniformly safer ⇒ gate daily_path_DD less negative than sticky on ALL windows.
    # We compute the check but NEVER claim it (hard-set claimed=false below).
    uniform_safe = True
    for wid in ("w2017_2019", "w2020_2022", "w2023_2025"):
        g = next(
            (
                r
                for r in base_compare
                if r["logic_id"] == GATE_LOGIC and r["window"] == wid
            ),
            None,
        )
        s = next(
            (
                r
                for r in base_compare
                if r["logic_id"] == STICKY_LOGIC and r["window"] == wid
            ),
            None,
        )
        if not g or not s:
            uniform_safe = False
            break
        if float(g["daily_path_DD"] or 0) < float(s["daily_path_DD"] or 0):
            # gate deeper (more negative) DD → not safer on this window
            uniform_safe = False
            break

    summary = {
        "wave": WAVE,
        "track": "C_dispersion_deepen",
        "main_logic": GATE_LOGIC,
        "compare_logic": STICKY_LOGIC,
        "promote_as_main": False,
        "go": False,
        "hold_mom_microgrid": False,
        "full_catalog_grid": False,
        "thresh_grid_mass": False,
        "thresh_points": [t[0] for t in THRESH_MULT_POINTS],
        "cost_over_tune": False,
        "gate_worst_window": gate_worst["window"],
        "gate_worst_daily_path_DD": gate_worst["daily_path_DD"],
        "sticky_worst_window": sticky_worst["window"],
        "sticky_worst_daily_path_DD": sticky_worst["daily_path_DD"],
        "sticky_stance": STICKY_STANCE,
        "uniformly_safer_than_sticky": False,  # hard-set; never claim
        "uniformly_safer_check_result": bool(uniform_safe),
        "activity_explain_focus": "w2023_2025",
        "repo_short_contrast": bool(repo_available),
        "data_path": "local_real_mirrors",
        "extends": "scripts/run_w102_dispersion_quality.py",
        "note": (
            "Deepen only. Gate on/off returns, activity drivers, coarse "
            "thresh (3 pts), sticky compare, optional repo short contrast. "
            "promote_as_main=false · go=false · never claim uniformly safe."
        ),
    }
    _dump(out_dir / "deepen_summary.json", summary)
    log(
        f"[w103/C] gate worst DD={_fmt(gate_worst['daily_path_DD'])} "
        f"({gate_worst['window']}) sticky worst="
        f"{_fmt(sticky_worst['daily_path_DD'])} ({sticky_worst['window']}) "
        f"uniformly_safer_check={uniform_safe} claimed=false "
        f"repo_contrast={repo_available} promote=false go=false"
    )
    return {
        "summary": summary,
        "compare": base_compare,
        "onoff": onoff_rows,
        "activity_explain": activity_explain,
        "drivers": driver_rows,
        "thresh": thresh_rows,
        "repo_contrast": repo_contrast_rows,
        "gate_pack": gate_pack,
        "sticky_pack": sticky_pack,
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
        complete = bool(rows) and all(
            bool(r.get("daily_path_complete")) for r in rows
        )
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
        complete = bool(rows) and all(
            bool(r.get("daily_path_complete")) for r in rows
        )
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
        complete = bool(rows) and all(
            bool(r.get("daily_path_complete")) for r in rows
        )
        return {
            "logic_id": logic_id,
            "daily_path_source": src,
            "daily_path_DD_required": True,
            "daily_path_complete": complete,
            "windows": rows,
            "promote_as_main": False,
            "go": False,
        }
    if src == "w102_track_b_event_rate":
        p = W102_LOG / "event_rate_daily_dd_table.json"
        table = json.loads(p.read_text()) if p.is_file() else []
        rows = [r for r in table if r.get("logic_id") == logic_id]
        if not rows:
            # fallback to per-logic files
            alt = W102_LOG / f"{logic_id}_daily_dd.json"
            rows = json.loads(alt.read_text()) if alt.is_file() else []
        complete = bool(rows) and all(
            bool(r.get("daily_path_complete")) for r in rows
        )
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
        f"weak_template_mapping=OFF not_a_count_race=True "
        f"daily_path_DD_required=True seed={seed}"
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
    _dump(
        out_dir / "llm_hyp_accepted_proposals.json",
        gen_eval.get("accepted_proposals") or [],
    )
    _dump(
        out_dir / "llm_hyp_rejected_proposals.json",
        gen_eval.get("rejected_proposals") or [],
    )

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

    n_daily_complete = sum(
        1 for r in survivor_daily if r.get("daily_path_complete")
    )
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
            "a pass. daily_path_DD required. Survivors research-only — not "
            "main / not GO. Not a count race."
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
    log_path = out_dir / "w103_dispersion_deepen.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = w100._assert_frozen_pins_untouched()
    pins["note"] = "W103 deepen/hyps must not mutate 3-default pins"
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w103] pins_untouched={pins['pins_untouched']}")
    log(
        "[w103] promote_as_main=false go=false hold_mom_grid=false "
        "thresh_grid_mass=false weak_template_mapping=OFF "
        "never_claim_uniformly_safe=true "
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
        log("[w103/C] deepen skipped")

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
    pins_after["note"] = "W103 after deepen/hyps; 3-default pins must match"
    _dump(out_dir / "frozen_pins_assert_after.json", pins_after)

    summary = {
        "wave": WAVE,
        "tracks": "C_dispersion_deepen + D_hyps",
        "hold_mom_microgrid": False,
        "full_catalog_grid": False,
        "thresh_grid_mass": False,
        "cost_over_tune": False,
        "weak_template_mapping": "OFF",
        "not_a_count_race": True,
        "uniformly_safer_claimed": False,
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
    _dump(out_dir / "w103_cd_summary.json", summary)
    log(
        f"[w103] done wall={summary['wall_sec']}s "
        f"pins={pins_after.get('pins_untouched')}"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
