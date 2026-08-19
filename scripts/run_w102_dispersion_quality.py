#!/usr/bin/env python3
"""W102 / w0819e Tracks C+D+E — dispersion_gate quality + constrained hyps.

C. Quality deep-dive of ``xs_cs_dispersion_gate`` (research-only) vs
   ``xs_rank_ls_sticky`` (STABLE_RESEARCH_ONLY comparison only).
   Cost sensitivity · DD-interval character · activity.
   Optional leverage/short overlay is a *disclosure* (mid band + L/H
   table) — not a retune. NO hold/mom grid. promote_as_main=false · go=false.

D. New failure-constrained hyp pack in parallel.
   Weak-template mapping OFF. Propose → eval with daily_path_DD REQUIRED.
   Not a count race (modest N). Survivors research-only, not main/GO.

E. 3-default pins frozen. MISDATE wait. Projection FRESH.
   No GO / Mass / READY / live.

Examples
--------
    uv run python scripts/run_w102_dispersion_quality.py \\
        --out-dir .glm-logs/w0819e_w102_otc6_event_rate_dd/
"""
from __future__ import annotations

import argparse
import json
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0819e_w102_otc6_event_rate_dd"
W100_LOG = ROOT / ".glm-logs" / "w0819c_w100_daily_path_dd_otc4"
W101_LOG = ROOT / ".glm-logs" / "w0819d_w101_otc5_dd_close"
CF_WORKER_URL = "https://quant-platform-research-mass-eval.taku-haga.workers.dev"

if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402
import run_w100_peer_daily_dd as w100  # noqa: E402

from research.stats_metrics import (  # noqa: E402
    equity_path_drawdown,
    evaluate_daily_path_dd_gate,
)

WAVE = "W102 / w0819e"
GATE_LOGIC = "xs_cs_dispersion_gate"
STICKY_LOGIC = "xs_rank_ls_sticky"
STICKY_STANCE = "STABLE_RESEARCH_ONLY"

# Catalog-base params — NOT a hold/mom retune.
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
    "why": "W100 new thesis; quality deep-dive this wave (research-only)",
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

# Tx sensitivity only — three points, not a strategy grid.
TX_COST_BANDS_BP: tuple[int, ...] = (5, 10, 20)
BASE_TX_BP: int = 10

# Short overlay: disclosure bands, mid is the single overlay (no pick-best).
SHORT_FRAC: float = 0.5  # L-S book long=0.3 / short=0.3 → short share of active
# Leverage disclosure: dollar-neutral L-S, no extra borrowed cash.
GROSS_LEVERAGE: float = 1.0

KNOWN_WEAK_THESIS = w100.KNOWN_WEAK_THESIS
KNOWN_DEMOTED_OR_WEAK = w100.KNOWN_DEMOTED_OR_WEAK

# Logics that already have a complete daily_path_DD table (cite, do not invent).
KNOWN_DAILY_PATH: dict[str, str] = {
    STICKY_LOGIC: "w102_quality_this_wave",
    GATE_LOGIC: "w102_quality_this_wave",
    "vol_risk_adjusted_mom": "w101_local_real_mirrors",
    "xs_rank_ls_daily": "w100_peer_cited",
    "xs_rank_mom_slow": "w100_peer_cited",
    "mdh_sticky_momentum": "w100_peer_cited",
}


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _fmt(v: Any, nd: int = 6) -> str:
    return w100._fmt(v, nd)


def _pct(v: Any, nd: int = 1) -> str:
    x = w100._scalar_f(v)
    if x is None:
        return "—"
    return f"{x * 100:.{nd}f}%"


def _active_mask(
    gross_daily: Sequence[float],
    net_daily: Sequence[float],
    daily_cost_drag: float,
) -> list[bool]:
    """Infer active days from (gross − net) == tx drag (W99/W100 convention)."""
    drag = float(daily_cost_drag)
    out: list[bool] = []
    for i, (g, n) in enumerate(zip(gross_daily, net_daily)):
        if i == 0:
            out.append(False)
            continue
        if drag <= 0:
            out.append(abs(float(g)) > 1e-15)
            continue
        out.append(abs((float(g) - float(n)) - drag) < 1e-12)
    return out


def dd_interval_character(
    equities: Sequence[float],
    dates: Sequence[str],
) -> dict[str, Any]:
    """Episode-level underwater character (not just the single max DD)."""
    if not equities or len(equities) < 2:
        return {
            "n_episodes": 0,
            "n_unrecovered": 0,
            "time_underwater_frac": None,
            "max_episode_duration": None,
            "median_episode_duration": None,
            "max_episode_depth": None,
            "episodes": [],
        }
    eq = [float(x) for x in equities]
    dts = [str(d)[:10] for d in dates]
    peak = eq[0]
    peak_i = 0
    in_dd = False
    ep_start = 0
    ep_trough_i = 0
    ep_trough_v = eq[0]
    episodes: list[dict[str, Any]] = []
    n_under = 0
    for i, v in enumerate(eq):
        if v > peak + 1e-15:
            if in_dd:
                episodes.append(
                    {
                        "start_date": dts[ep_start],
                        "trough_date": dts[ep_trough_i],
                        "end_date": dts[i],
                        "duration_days": int(i - ep_start),
                        "trough_depth": float(ep_trough_v / eq[ep_start] - 1.0)
                        if eq[ep_start]
                        else None,
                        "recovered": True,
                    }
                )
                in_dd = False
            peak = v
            peak_i = i
            continue
        if v < peak - 1e-15:
            n_under += 1
            if not in_dd:
                in_dd = True
                ep_start = peak_i
                ep_trough_i = i
                ep_trough_v = v
            elif v < ep_trough_v:
                ep_trough_i = i
                ep_trough_v = v
    if in_dd:
        episodes.append(
            {
                "start_date": dts[ep_start],
                "trough_date": dts[ep_trough_i],
                "end_date": dts[-1],
                "duration_days": int(len(eq) - 1 - ep_start),
                "trough_depth": float(ep_trough_v / eq[ep_start] - 1.0)
                if eq[ep_start]
                else None,
                "recovered": False,
            }
        )
    durs = [int(e["duration_days"]) for e in episodes]
    depths = [
        float(e["trough_depth"])
        for e in episodes
        if e.get("trough_depth") is not None
    ]
    worst = equity_path_drawdown(eq, dts)
    return {
        "n_episodes": len(episodes),
        "n_unrecovered": sum(1 for e in episodes if not e.get("recovered")),
        "time_underwater_frac": (n_under / max(1, len(eq) - 1)) if eq else None,
        "n_underwater_days": n_under,
        "max_episode_duration": max(durs) if durs else 0,
        "median_episode_duration": (
            float(statistics.median(durs)) if durs else None
        ),
        "mean_episode_duration": (sum(durs) / len(durs)) if durs else None,
        "max_episode_depth": min(depths) if depths else None,
        "worst_peak_date": worst.get("peak_date"),
        "worst_trough_date": worst.get("trough_date"),
        "worst_recovery_date": worst.get("recovery_date"),
        "worst_dd_duration": worst.get("dd_duration_days"),
        "worst_recovery_days": worst.get("recovery_days"),
        "worst_recovered": worst.get("recovered"),
        "worst_daily_path_DD": worst.get("max_dd"),
        "episodes": episodes,
        "method": "running_peak_underwater_episodes",
        "note": (
            "Episodes are calendar stretches below the running peak. "
            "Distinct from the single max-DD interval."
        ),
    }


def _apply_extra_daily_drag(
    pack: Mapping[str, Any],
    extra_daily: float,
) -> dict[str, Any]:
    """Replay net path with an extra daily drag on active days only."""
    dates = list(pack.get("dates") or [])
    gross = list(pack.get("gross_daily") or [])
    net0 = list(pack.get("net_daily") or [])
    drag = float(pack.get("daily_cost_drag") or 0.0)
    if not dates or not gross or len(gross) != len(dates):
        return {"status": "missing_path"}
    active = _active_mask(gross, net0, drag)
    extra = float(extra_daily)
    net1: list[float] = []
    eq = 1.0
    equities: list[float] = []
    for i, n in enumerate(net0):
        if i == 0 or not active[i]:
            nn = float(n)
        else:
            nn = float(n) - extra
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
    return {
        "status": "ok",
        "extra_daily": extra,
        "n_active_days": sum(1 for a in active if a),
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
        "drawdown": dd,
    }


def _activity_from_pack(pack: Mapping[str, Any]) -> dict[str, Any]:
    dates = list(pack.get("dates") or [])
    gross = list(pack.get("gross_daily") or [])
    net = list(pack.get("net_daily") or [])
    drag = float(pack.get("daily_cost_drag") or 0.0)
    active = _active_mask(gross, net, drag) if dates and gross else []
    n_cal = max(0, len(dates) - 1)
    n_act = sum(1 for a in active if a)
    n_off = pack.get("n_gated_off_days")
    n_on = pack.get("n_gate_on_days")
    return {
        "n_calendar_days": n_cal,
        "n_active_days": n_act,
        "active_frac": (n_act / n_cal) if n_cal else None,
        "n_gated_off_days": n_off,
        "n_gate_on_days": n_on,
        "gate_on_frac": (
            (float(n_on) / float(n_on + n_off))
            if n_on is not None and n_off is not None and (n_on + n_off) > 0
            else None
        ),
        "n_codes": pack.get("n_codes"),
        "kind": pack.get("kind"),
    }


def _eval_window(
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
    max_codes: int,
    max_days: int,
    log,
    keep_path: bool,
) -> dict[str, Any]:
    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(max_codes)]
    lid = str(spec["logic_id"])
    rows: list[dict[str, Any]] = []
    for w in w100.W100_WINDOWS:
        wid = str(w["window_id"])
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        shard_summaries: list[dict[str, Any]] = []
        shard_activity: list[dict[str, Any]] = []
        shard_packs: list[dict[str, Any]] = []
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded.get("period_id"))
            if loaded.get("status") != "ok":
                shard_summaries.append({"period_id": pid, "status": loaded.get("status")})
                continue
            pack = w100.evaluate_spec_on_bars(
                loaded["bars"], spec=spec, one_way_cost=float(one_way_cost)
            )
            summary = w100._summarize_path(pack)
            summary["period_id"] = pid
            summary["window_id"] = wid
            shard_summaries.append(summary)
            act = _activity_from_pack(pack)
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
                f"[w102/C]   {lid} {wid}/{pid}: n={summary.get('n_equity_points')} "
                f"DD={_fmt(summary.get('daily_path_DD'))} "
                f"net={_fmt(summary.get('total_return_net'))} "
                f"act={act.get('n_active_days')}/{act.get('n_calendar_days')}"
            )
        stitched = w100._stitch_net(stitch_net, stitch_dates)
        char = dd_interval_character(
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
        row = {
            "logic_id": lid,
            "window": wid,
            "label": w["label"],
            "data_note": w["data_note"],
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
            "gate_on_frac": (n_on / (n_on + n_off)) if has_gate and (n_on + n_off) else None,
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
        rows.append(row)
    return {"logic_id": lid, "table": rows}


def run_quality_deepdive(
    *,
    out_dir: Path,
    max_codes: int,
    max_days: int,
    log,
) -> dict[str, Any]:
    from research.cost_models import (
        DEFAULT_SHORT_BORROW_ANNUAL_BP,
        DEFAULT_TRADING_DAYS_PER_YEAR,
        POSITION_STYLE_LONG_SHORT,
        SHORT_BORROW_SPREAD_SENSITIVITY,
        build_leverage_short_cost_assumption,
        short_borrow_daily_cost,
    )

    base_one_way = BASE_TX_BP / 10_000.0
    log(
        f"[w102/C] quality main={GATE_LOGIC} compare={STICKY_LOGIC} "
        f"tx_bands_bp={list(TX_COST_BANDS_BP)} hold_mom_grid=false"
    )

    base_by_logic: dict[str, dict[str, Any]] = {}
    for spec in (GATE_SPEC, STICKY_SPEC):
        pack = _eval_window(
            spec=spec,
            one_way_cost=base_one_way,
            max_codes=max_codes,
            max_days=max_days,
            log=log,
            keep_path=True,
        )
        base_by_logic[str(spec["logic_id"])] = pack
        slim = []
        for r in pack["table"]:
            slim.append({k: v for k, v in r.items() if not str(k).startswith("_")})
        _dump(out_dir / f"quality_{spec['logic_id']}_base.json", slim)

    # --- cost sensitivity: tx bands (re-eval; params frozen) ---
    tx_rows: list[dict[str, Any]] = []
    for bp in TX_COST_BANDS_BP:
        ow = float(bp) / 10_000.0
        for spec in (GATE_SPEC, STICKY_SPEC):
            if bp == BASE_TX_BP:
                pack = base_by_logic[str(spec["logic_id"])]
            else:
                pack = _eval_window(
                    spec=spec,
                    one_way_cost=ow,
                    max_codes=max_codes,
                    max_days=max_days,
                    log=log,
                    keep_path=False,
                )
            for r in pack["table"]:
                tx_rows.append(
                    {
                        "logic_id": r["logic_id"],
                        "window": r["window"],
                        "one_way_bp": bp,
                        "daily_path_DD": r["daily_path_DD"],
                        "dd_duration": r["dd_duration"],
                        "recovery_days": r["recovery_days"],
                        "recovered": r["recovered"],
                        "total_ret_net": r["total_ret_net"],
                        "n_days": r["n_days"],
                        "daily_path_complete": r["daily_path_complete"],
                        "promote_as_main": False,
                        "go": False,
                    }
                )
    _dump(out_dir / "quality_tx_cost_sensitivity.json", tx_rows)

    # --- short/leverage overlay (disclosure; mid only applied) ---
    lev_ass = build_leverage_short_cost_assumption(
        position_style=POSITION_STYLE_LONG_SHORT,
        gross_leverage=GROSS_LEVERAGE,
        short_fraction=SHORT_FRAC,
        one_way_cost=base_one_way,
        uses_short=True,
        uses_leverage=False,
        short_borrow_sensitivity="mid",
        prefer_repo_linked=False,  # no invent: no repo series wired here
        prefer_liquidity_linked=False,
    )
    short_overlay_rows: list[dict[str, Any]] = []
    short_band_rows: list[dict[str, Any]] = []
    for lid, pack in base_by_logic.items():
        for r in pack["table"]:
            path = r.get("_path") or {}
            shard_packs = list(path.get("shard_packs") or [])
            if not shard_packs:
                continue
            for label, spread_bp in SHORT_BORROW_SPREAD_SENSITIVITY.items():
                extra = short_borrow_daily_cost(
                    short_borrow_annual_bp=float(spread_bp),
                    trading_days_per_year=DEFAULT_TRADING_DAYS_PER_YEAR,
                    short_fraction=SHORT_FRAC,
                )
                # Replay each shard then stitch (same method as base).
                stitch_dates: list[str] = []
                stitch_net: list[float] = []
                for sp in shard_packs:
                    replay = _apply_extra_daily_drag(
                        {
                            "dates": sp.get("dates") or [],
                            "gross_daily": sp.get("gross_daily") or [],
                            "net_daily": sp.get("net_daily") or [],
                            "daily_cost_drag": sp.get("daily_cost_drag") or 0.0,
                        },
                        extra,
                    )
                    dlist = list(replay.get("dates") or [])
                    nlist = list(replay.get("net_daily") or [])
                    if not stitch_dates:
                        stitch_dates = list(dlist)
                        stitch_net = list(nlist)
                    else:
                        stitch_dates.extend(dlist[1:])
                        stitch_net.extend(nlist[1:])
                stitched = w100._stitch_net(stitch_net, stitch_dates)
                band_row = {
                    "logic_id": lid,
                    "window": r["window"],
                    "short_band": label,
                    "short_annual_bp": float(spread_bp),
                    "short_daily": extra,
                    "short_fraction": SHORT_FRAC,
                    "gross_leverage": GROSS_LEVERAGE,
                    "daily_path_DD": stitched.get("daily_path_DD"),
                    "dd_duration": stitched.get("dd_duration"),
                    "recovery_days": stitched.get("recovery_days"),
                    "recovered": stitched.get("recovered"),
                    "total_ret_net": stitched.get("total_return_net"),
                    "n_days": stitched.get("n_equity_points"),
                    "daily_path_complete": (stitched.get("daily_path_dd_gate") or {}).get(
                        "complete"
                    ),
                    "rate_source": "fixed_bp_placeholder",
                    "repo_linked": False,
                    "note": (
                        "Disclosure overlay. mid=50bp annual placeholder "
                        "(no repo series wired; gaps not invented). "
                        "Not a retune / not pick-best."
                    ),
                    "promote_as_main": False,
                    "go": False,
                }
                short_band_rows.append(band_row)
                if label == "mid":
                    short_overlay_rows.append(band_row)
    _dump(out_dir / "quality_short_cost_overlay.json", short_overlay_rows)
    _dump(out_dir / "quality_short_cost_bands.json", short_band_rows)
    _dump(
        out_dir / "quality_leverage_short_assumption.json",
        {
            "position_style": POSITION_STYLE_LONG_SHORT,
            "gross_leverage": GROSS_LEVERAGE,
            "short_fraction": SHORT_FRAC,
            "uses_short": True,
            "uses_leverage": False,
            "financing_daily": 0.0,
            "short_borrow_placeholder_annual_bp": DEFAULT_SHORT_BORROW_ANNUAL_BP,
            "sensitivity_bands_bp": dict(SHORT_BORROW_SPREAD_SENSITIVITY),
            "repo_linked": False,
            "liquidity_linked": False,
            "over_tune": False,
            "assumption": {
                k: lev_ass.get(k)
                for k in (
                    "position_style",
                    "gross_leverage",
                    "short_fraction",
                    "uses_short",
                    "uses_leverage",
                    "assumptions_complete",
                    "missing_disclosure",
                    "transaction",
                    "short_borrow",
                    "financing",
                    "repo_linked",
                    "liquidity_linked",
                )
                if k in lev_ass
            },
            "note": (
                "CS L-S book is already dollar-neutral (gross_leverage=1). "
                "No extra leverage applied. Short overlay uses the fixed "
                "50bp mid placeholder because a date-matched repo series "
                "is not wired into this bars-MTM path. Gaps not invented."
            ),
        },
    )

    # compact compare table (base 10bp, tx only — matches W100 method)
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
                    "recovery_date": r["recovery_date"],
                    "n_active_days": r["n_active_days"],
                    "active_frac": r["active_frac"],
                    "n_gated_off_days": r["n_gated_off_days"],
                    "n_gate_on_days": r["n_gate_on_days"],
                    "gate_on_frac": r["gate_on_frac"],
                    "n_dd_episodes": r["n_dd_episodes"],
                    "time_underwater_frac": r["time_underwater_frac"],
                    "max_episode_duration": r["max_episode_duration"],
                    "median_episode_duration": r["median_episode_duration"],
                    "daily_path_complete": r["daily_path_complete"],
                    "stance": r["stance"],
                    "promote_as_main": False,
                    "go": False,
                }
            )
    _dump(out_dir / "quality_compare_table.json", compare)

    episodes_out: dict[str, Any] = {}
    for lid in (GATE_LOGIC, STICKY_LOGIC):
        episodes_out[lid] = {
            r["window"]: r.get("_episodes") or []
            for r in base_by_logic[lid]["table"]
        }
    _dump(out_dir / "quality_dd_episodes.json", episodes_out)

    # headline numbers
    def _worst(lid: str) -> dict[str, Any]:
        rows = [r for r in compare if r["logic_id"] == lid]
        worst = min(rows, key=lambda x: float(x["daily_path_DD"] or 0.0))
        return worst

    gate_worst = _worst(GATE_LOGIC)
    sticky_worst = _worst(STICKY_LOGIC)
    summary = {
        "wave": WAVE,
        "track": "C_dispersion_quality",
        "main_logic": GATE_LOGIC,
        "compare_logic": STICKY_LOGIC,
        "promote_as_main": False,
        "go": False,
        "hold_mom_microgrid": False,
        "full_catalog_grid": False,
        "cost_over_tune": False,
        "gate_worst_window": gate_worst["window"],
        "gate_worst_daily_path_DD": gate_worst["daily_path_DD"],
        "sticky_worst_window": sticky_worst["window"],
        "sticky_worst_daily_path_DD": sticky_worst["daily_path_DD"],
        "sticky_stance": STICKY_STANCE,
        "tx_cost_bands_bp": list(TX_COST_BANDS_BP),
        "short_overlay": "mid_50bp_placeholder_disclosure",
        "leverage_applied": False,
        "data_path": "local_real_mirrors",
        "compare": compare,
        "tx_sensitivity": tx_rows,
        "short_overlay_mid": short_overlay_rows,
    }
    _dump(out_dir / "quality_summary.json", summary)
    log(
        f"[w102/C] gate worst DD={_fmt(gate_worst['daily_path_DD'])} "
        f"({gate_worst['window']}) sticky worst="
        f"{_fmt(sticky_worst['daily_path_DD'])} ({sticky_worst['window']}) "
        f"promote=false go=false"
    )
    return {
        "summary": summary,
        "compare": compare,
        "base_by_logic": {
            lid: {
                "table": [
                    {k: v for k, v in r.items() if not str(k).startswith("_")}
                    for r in pack["table"]
                ]
            }
            for lid, pack in base_by_logic.items()
        },
    }


def _cite_known_daily(
    logic_id: str,
    quality_compare: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    src = KNOWN_DAILY_PATH.get(logic_id)
    if not src:
        return None
    if src == "w102_quality_this_wave":
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
        f"[w102/D] new pack n={n_hyps} provider={resolved_provider} "
        f"wave={LLM_HYP_WAVE} ver={LLM_HYP_VERSION} "
        f"weak_template_mapping=OFF not_a_count_race=True"
    )
    # Weak-template mapping OFF: generate_and_evaluate_hypotheses already
    # skips known-weak catalog targets (rate_abs_level / flow_margin_* /
    # fund_slow / opt level / repo level). We keep that skip and additionally
    # refuse to treat a weak-mapped survivor as a pass.
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
            "Modest N. Weak-template mapping OFF (known-weak catalog "
            "targets not remapped). Period-net survival is not a pass. "
            "Not a count race — survivors stay research-only."
        ),
    }
    _dump(out_dir / "hyp_summary.json", summary)
    log(
        f"[w102/D] n_proposed={n_proposed} n_accepted={n_accepted} "
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
    p.add_argument("--seed", type=int, default=8908192)
    p.add_argument("--provider", type=str, default="xai")
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-quality", action="store_true")
    p.add_argument("--skip-misdate", action="store_true")
    p.add_argument("--skip-projection", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w102_dispersion_quality.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = w100._assert_frozen_pins_untouched()
    pins["note"] = "W102 quality/hyps must not mutate 3-default pins"
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w102] pins_untouched={pins['pins_untouched']}")
    log(
        "[w102] promote_as_main=false go=false hold_mom_grid=false "
        "weak_template_mapping=OFF GLM implementer only. "
        "Grok did not implement."
    )

    quality: dict[str, Any] | None = None
    if not args.skip_quality:
        quality = run_quality_deepdive(
            out_dir=out_dir,
            max_codes=int(args.max_codes),
            max_days=int(args.max_days),
            log=log,
        )
    else:
        log("[w102/C] quality skipped")

    hyp_pack: dict[str, Any] | None = None
    if not args.skip_hyps:
        hyp_pack = run_hyp_pack(
            out_dir=out_dir,
            n_hyps=int(args.n_hyps),
            provider=str(args.provider),
            model=args.model,
            seed=int(args.seed),
            synthetic=bool(args.synthetic),
            quality_compare=(quality or {}).get("compare") or [],
            log=log,
        )
    else:
        log("[w102/D] hyps skipped")

    misdate: dict[str, Any] | None = None
    if not args.skip_misdate:
        misdate = w100.run_misdate_reprobe(out_dir=out_dir, log=log)
        if isinstance(misdate, dict):
            misdate["wave"] = WAVE
            _dump(out_dir / "master_misdate_probe.json", misdate)
    else:
        log("[w102/E] MISDATE skipped")

    projection: dict[str, Any] | None = None
    if not args.skip_projection:
        projection = w100.refresh_projection(out_dir=out_dir, log=log)
    else:
        log("[w102/E] projection skipped")

    pins_after = w100._assert_frozen_pins_untouched()
    pins_after["note"] = "W102 after quality/hyps; 3-default pins must match"
    _dump(out_dir / "frozen_pins_assert_after.json", pins_after)

    summary = {
        "wave": WAVE,
        "tracks": "C_dispersion_quality + D_hyps + E_pins_misdate_projection",
        "hold_mom_microgrid": False,
        "full_catalog_grid": False,
        "cost_over_tune": False,
        "weak_template_mapping": "OFF",
        "not_a_count_race": True,
        "pins_untouched": pins_after.get("pins_untouched"),
        "quality": (quality or {}).get("summary") if quality else None,
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
    _dump(out_dir / "w102_cd_summary.json", summary)
    log(
        f"[w102] done wall={summary['wall_sec']}s "
        f"pins={pins_after.get('pins_untouched')}"
    )
    return 0 if pins_after.get("pins_untouched") else 2


if __name__ == "__main__":
    raise SystemExit(main())
