#!/usr/bin/env python3
"""W100 / w0819c Tracks C+D+E+F — peer daily_path_DD + constrained hyps.

C. Small research-only major candidates besides xs_rank_ls_sticky.
   Same daily MTM-after-cost method as W99. NO full grid. NO hold/mom grid.
   Table: daily_path_DD / dd_duration / recovery / total_ret_net.
   None promoted to main / GO.

D. xs_rank_ls_sticky stays STABLE_RESEARCH_ONLY.
   promote_as_main=false · go=false · no hold/mom grid.

E. Failure-constrained hyp generation (modest N). Avoid weak-template mapping.
   If a new thesis is implemented, evaluate it WITH daily_path_DD required.
   Survivors stay research-only.

F. Optional master MISDATE re-probe (no fake COMPLETE). Projection FRESH if
   the existing script allows. Residual docs written by the caller.

Freezes held: Mass=NO-GO · READY=false · ops GO=false · continuous paper
UNARMED · 3-default pins untouched · no GO/live.

Examples
--------
    uv run python scripts/run_w100_peer_daily_dd.py \\
        --out-dir .glm-logs/w0819c_w100_daily_path_dd_otc4/
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0819c_w100_daily_path_dd_otc4"
CF_WORKER_URL = (
    "https://quant-platform-research-mass-eval.taku-haga.workers.dev"
)

# Import W99 windows / sticky MTM / shard loader / pin assert (same method).
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
import run_w99_sticky_daily_dd as w99  # noqa: E402

from research.stats_metrics import (  # noqa: E402
    evaluate_daily_path_dd_gate,
    equity_path_drawdown,
)

W100_WINDOWS = w99.W99_WINDOWS
FROZEN_PIN_SNAPSHOT = w99.FROZEN_PIN_SNAPSHOT

STICKY_LOGIC_ID = "xs_rank_ls_sticky"
STICKY_STANCE = "STABLE_RESEARCH_ONLY"

# Small set of research-only majors besides sticky. Catalog templates only
# (distinct position construction / info horizon) + one new thesis.
# NOT a hold/mom/frac grid. NOT frozen-default pin clones (mom3 omitted).
PEER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "logic_id": "xs_rank_ls_daily",
        "family": "cross_section_relative",
        "kind": "cs_rank",
        "hold_days": 1,
        "momentum_n": 5,
        "long_frac": 0.3,
        "short_frac": 0.3,
        "signal_sign": 1,
        "catalog": True,
        "why": "same CS L-S family, daily rebalance (higher turnover vs sticky)",
    },
    {
        "logic_id": "xs_rank_mom_slow",
        "family": "cross_section_relative",
        "kind": "cs_rank",
        "hold_days": 10,
        "momentum_n": 20,
        "long_frac": 0.3,
        "short_frac": 0.3,
        "signal_sign": 1,
        "catalog": True,
        "why": "catalog slow-rank CS (mom=20 structural pin, not a free grid)",
    },
    {
        "logic_id": "mdh_sticky_momentum",
        "family": "multi_day_hold",
        "kind": "mdh_sign",
        "hold_days": 10,
        "momentum_n": 10,
        "signal_sign": 1,
        "catalog": True,
        "why": "time-series sticky mom (own-sign) vs CS relative book",
    },
    {
        "logic_id": "xs_cs_dispersion_gate",
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
        "why": (
            "NEW: CS L-S sticky only when today's mom dispersion is at/above "
            "its PIT trailing median (high-dispersion regime). Not a hold/mom "
            "grid and not a weak-template remap."
        ),
    },
)

STICKY_SPEC: dict[str, Any] = {
    "logic_id": STICKY_LOGIC_ID,
    "family": "cross_section_relative",
    "kind": "cs_rank",
    "hold_days": 10,
    "momentum_n": 5,
    "long_frac": 0.3,
    "short_frac": 0.3,
    "signal_sign": 1,
    "catalog": True,
    "reference_only": True,
    "why": "W99 reference; STABLE_RESEARCH_ONLY; not re-promoted",
}

KNOWN_WEAK_THESIS: frozenset[str] = frozenset(
    {
        "rate_abs_level_xs",
        "flow_margin_short_hard",
    }
)
KNOWN_DEMOTED_OR_WEAK: frozenset[str] = frozenset(
    {
        "rate_abs_level_xs",
        "flow_margin_short_hard",
        "flow_margin_short_soft",
        "flow_margin_pressure",
        "fund_value_mom_agree_slow",
        "opt225_skew_abs_level",
        "opt225_cm_term_abs_level",
        "opt225_basevol_delta_abs",
        "macro_repo_rate_level",
    }
)

MISDATE_MONTHS = [
    f"{y:04d}-{m:02d}"
    for y, months in [(2006, range(8, 13)), (2007, range(1, 13)), (2008, range(1, 5))]
    for m in months
]


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _scalar_f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return fv if math.isfinite(fv) else None


def _fmt(v: Any, nd: int = 6) -> str:
    x = _scalar_f(v)
    return f"{x:.{nd}f}" if x is not None else "—"


def _assert_frozen_pins_untouched() -> dict[str, Any]:
    pack = w99._assert_frozen_pins_untouched()
    pack["note"] = "W100 peer daily DD / hyps must not mutate 3-default pins"
    return pack


def _held_book_daily_mtm(
    *,
    held_by_code_date: Mapping[str, Mapping[str, float | None]],
    close_by: Mapping[str, Mapping[str, float]],
    dates: Sequence[str],
    hold_days: int,
    one_way_cost: float,
    logic_id: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Equal-weight daily MTM of a pre-built held book (W99 cost convention)."""
    from features.class_signals import amortized_one_way_cost

    h = int(hold_days)
    am_cost = float(amortized_one_way_cost(float(one_way_cost), h))
    daily_cost = float(am_cost) / float(h) if h > 0 else float(am_cost)

    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": logic_id,
            "n_days": len(dates),
            "dates": [],
            "equities": [],
            "gross_daily": [],
            "net_daily": [],
        }

    daily_rows: list[dict[str, Any]] = []
    gross_daily: list[float] = []
    net_daily: list[float] = []
    eq_dates: list[str] = []
    equities: list[float] = []
    equity = 1.0
    eq_dates.append(dates[0])
    equities.append(equity)
    gross_daily.append(0.0)
    net_daily.append(0.0)
    daily_rows.append(
        {
            "date": dates[0],
            "gross": 0.0,
            "net": 0.0,
            "n_active": 0,
            "cost_drag": 0.0,
            "equity": equity,
            "note": "start_mark",
        }
    )

    for i in range(1, len(dates)):
        d_prev = dates[i - 1]
        d = dates[i]
        contribs: list[float] = []
        for code, cmap in held_by_code_date.items():
            pos = cmap.get(d_prev)
            if pos is None or pos == 0.0:
                continue
            c0 = close_by.get(code, {}).get(d_prev)
            c1 = close_by.get(code, {}).get(d)
            if c0 is None or c1 is None or c0 == 0:
                continue
            r1 = (float(c1) / float(c0)) - 1.0
            contribs.append(float(pos) * r1)
        n_active = len(contribs)
        if n_active == 0:
            g = 0.0
            cost_drag = 0.0
            net = 0.0
        else:
            g = float(sum(contribs) / n_active)
            cost_drag = daily_cost
            net = g - cost_drag
        equity = equity * (1.0 + net)
        gross_daily.append(g)
        net_daily.append(net)
        eq_dates.append(d)
        equities.append(equity)
        daily_rows.append(
            {
                "date": d,
                "gross": g,
                "net": net,
                "n_active": n_active,
                "cost_drag": cost_drag,
                "equity": equity,
            }
        )

    dd = equity_path_drawdown(equities, eq_dates)
    g_eq = 1.0
    for g in gross_daily[1:]:
        g_eq *= 1.0 + g
    active_days = sum(1 for r in daily_rows[1:] if int(r.get("n_active") or 0) > 0)
    mean_net = (
        sum(net_daily[1:]) / max(1, len(net_daily) - 1) if len(net_daily) > 1 else None
    )
    mean_gross = (
        sum(gross_daily[1:]) / max(1, len(gross_daily) - 1)
        if len(gross_daily) > 1
        else None
    )
    gate = evaluate_daily_path_dd_gate(
        daily_path_dd=dd.get("max_dd"),
        dd_duration=dd.get("dd_duration_days"),
        recovered=dd.get("recovered"),
        recovery_days=dd.get("recovery_days"),
        total_ret_net=dd.get("total_return"),
        method="daily_equity_level_peak_to_trough",
    )
    out = {
        "status": "ok",
        "logic_id": logic_id,
        "hold_days": h,
        "one_way_cost": float(one_way_cost),
        "amortized_one_way_cost": am_cost,
        "daily_cost_drag": daily_cost,
        "n_codes": len(held_by_code_date),
        "n_calendar_days": len(dates),
        "n_equity_points": len(equities),
        "n_active_days": active_days,
        "mean_gross_daily": mean_gross,
        "mean_net_daily": mean_net,
        "total_return_gross": g_eq - 1.0,
        "total_return_net": dd.get("total_return"),
        "drawdown": dd,
        "daily_path_dd_gate": {
            "complete": gate.get("complete"),
            "measured": gate.get("measured"),
            "fails": gate.get("fails"),
            "warnings": gate.get("warnings"),
            "period_net_dd_only_pass_forbidden": True,
        },
        "dates": eq_dates,
        "equities": equities,
        "gross_daily": gross_daily,
        "net_daily": net_daily,
        "cost_convention": (
            "python_local: daily_cost = (one_way/hold_days)/hold_days while active; "
            "over H active days ≈ amortized once (matches period-net am_cost)."
        ),
        "data_path": "local_real_mirrors",
        "promote_as_main": False,
        "go": False,
        "research_only": True,
        "note": (
            "Daily MTM after amortized cost drag. Research-only. "
            "Not READY / not Mass / not GO."
        ),
    }
    if extra:
        out.update(dict(extra))
    return out


def _panel_index(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    momentum_n: int,
) -> dict[str, Any]:
    from research.class_hyp_eval import momentum_series

    n = int(momentum_n)
    by_date: dict[str, dict[str, float | None]] = {}
    dates_by_code: dict[str, list[str]] = {}
    close_by: dict[str, dict[str, float]] = {}
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        if len(pairs_l) < n + 2:
            continue
        moms = momentum_series(pairs_l, n=n)
        for d, m in moms:
            by_date.setdefault(d, {})[code] = m
        dates_by_code[code] = [d for d, _ in pairs_l]
        for d, c in pairs_l:
            close_by.setdefault(code, {})[d] = float(c)
    dates = sorted(by_date.keys())
    return {
        "by_date": by_date,
        "dates_by_code": dates_by_code,
        "close_by": close_by,
        "dates": dates,
        "momentum_n": n,
    }


def evaluate_cs_rank_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    from features.class_signals import apply_sticky_hold, cross_section_rank_signs

    n = int(spec["momentum_n"])
    h = int(spec["hold_days"])
    lf = float(spec.get("long_frac") or 0.3)
    sf = float(spec.get("short_frac") or 0.3)
    sgn = 1 if int(spec.get("signal_sign") or 1) >= 0 else -1
    panel = _panel_index(bars_by_code, momentum_n=n)
    dates = panel["dates"]
    dates_by_code = panel["dates_by_code"]
    by_date = panel["by_date"]
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "logic_id": spec["logic_id"],
            "n_days": len(dates),
        }

    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=lf, short_frac=sf
        )
        for code, sign in ranks.items():
            daily_rank.setdefault(code, {})[d] = sign

    held_by_code_date: dict[str, dict[str, float | None]] = {}
    for code, dlist in dates_by_code.items():
        entries = [daily_rank.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        held_by_code_date[code] = {
            dlist[i]: (None if held[i] is None else float(held[i]) * sgn)
            for i in range(len(dlist))
        }
    return _held_book_daily_mtm(
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
        },
    )


def evaluate_mdh_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    from features.class_signals import apply_sticky_hold, sign_from_numeric
    from research.class_hyp_eval import momentum_series

    n = int(spec["momentum_n"])
    h = int(spec["hold_days"])
    sgn = 1 if int(spec.get("signal_sign") or 1) >= 0 else -1
    dates_by_code: dict[str, list[str]] = {}
    close_by: dict[str, dict[str, float]] = {}
    held_by_code_date: dict[str, dict[str, float | None]] = {}
    calendar: set[str] = set()
    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        if len(pairs_l) < n + 2:
            continue
        moms = momentum_series(pairs_l, n=n)
        mom_by_d = {d: m for d, m in moms}
        dlist = [d for d, _ in pairs_l]
        entries = [sign_from_numeric(mom_by_d.get(d)) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        held_by_code_date[code] = {
            dlist[i]: (None if held[i] is None else float(held[i]) * sgn)
            for i in range(len(dlist))
        }
        dates_by_code[code] = dlist
        for d, c in pairs_l:
            close_by.setdefault(code, {})[d] = float(c)
            calendar.add(d)
    dates = sorted(calendar)
    return _held_book_daily_mtm(
        held_by_code_date=held_by_code_date,
        close_by=close_by,
        dates=dates,
        hold_days=h,
        one_way_cost=one_way_cost,
        logic_id=str(spec["logic_id"]),
        extra={
            "momentum_n": n,
            "signal_sign": sgn,
            "kind": spec.get("kind"),
            "n_codes": len(dates_by_code),
        },
    )


def evaluate_cs_dispersion_gate_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    """CS L-S sticky gated by PIT trailing-median of CS mom std.

    Thesis: relative-strength L-S is compensation for cross-sectional
    dispersion; when dispersion is compressed the book is noise → flat.
    Trailing median uses dates strictly before today (PIT).
    """
    from features.class_signals import apply_sticky_hold, cross_section_rank_signs
    from statistics import pstdev

    n = int(spec["momentum_n"])
    h = int(spec["hold_days"])
    lf = float(spec.get("long_frac") or 0.3)
    sf = float(spec.get("short_frac") or 0.3)
    sgn = 1 if int(spec.get("signal_sign") or 1) >= 0 else -1
    min_hist = int(spec.get("min_hist") or 10)
    panel = _panel_index(bars_by_code, momentum_n=n)
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
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    n_gated_off = 0
    for d in dates:
        moms = [m for m in (by_date.get(d) or {}).values() if m is not None]
        moms_f = [float(m) for m in moms if math.isfinite(float(m))]
        disp = float(pstdev(moms_f)) if len(moms_f) >= 2 else 0.0
        thresh = median(disp_hist) if len(disp_hist) >= min_hist else None
        on = True if thresh is None else disp >= float(thresh)
        gate_on[d] = on
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
    return _held_book_daily_mtm(
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
            "min_hist": min_hist,
            "n_gated_off_days": n_gated_off,
            "n_gate_on_days": sum(1 for v in gate_on.values() if v),
            "promote_as_main": False,
            "go": False,
            "catalog": False,
        },
    )


def evaluate_spec_on_bars(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    spec: Mapping[str, Any],
    one_way_cost: float,
) -> dict[str, Any]:
    kind = str(spec.get("kind") or "")
    if kind == "mdh_sign":
        return evaluate_mdh_daily_mtm(
            bars_by_code, spec=spec, one_way_cost=one_way_cost
        )
    if kind == "cs_dispersion_gate":
        return evaluate_cs_dispersion_gate_daily_mtm(
            bars_by_code, spec=spec, one_way_cost=one_way_cost
        )
    return evaluate_cs_rank_daily_mtm(
        bars_by_code, spec=spec, one_way_cost=one_way_cost
    )


def _summarize_path(pack: Mapping[str, Any]) -> dict[str, Any]:
    dd = pack.get("drawdown") or {}
    gate = pack.get("daily_path_dd_gate") or {}
    return {
        "status": pack.get("status"),
        "logic_id": pack.get("logic_id"),
        "n_equity_points": pack.get("n_equity_points"),
        "n_active_days": pack.get("n_active_days"),
        "mean_gross_daily": pack.get("mean_gross_daily"),
        "mean_net_daily": pack.get("mean_net_daily"),
        "total_return_gross": pack.get("total_return_gross"),
        "total_return_net": pack.get("total_return_net"),
        "daily_path_DD": dd.get("max_dd"),
        "abs_max_dd": dd.get("abs_max_dd"),
        "dd_duration": dd.get("dd_duration_days"),
        "recovery_days": dd.get("recovery_days"),
        "recovered": dd.get("recovered"),
        "peak_date": dd.get("peak_date"),
        "trough_date": dd.get("trough_date"),
        "recovery_date": dd.get("recovery_date"),
        "daily_path_measured": gate.get("measured"),
        "daily_path_complete": gate.get("complete"),
        "data_path": pack.get("data_path"),
        "n_gated_off_days": pack.get("n_gated_off_days"),
        "n_gate_on_days": pack.get("n_gate_on_days"),
    }


def _stitch_net(nets: Sequence[float], dates: Sequence[str]) -> dict[str, Any]:
    if not nets:
        return {
            "n_equity_points": 0,
            "total_return_net": None,
            "daily_path_DD": None,
        }
    eq = 1.0
    equities: list[float] = []
    for i, net in enumerate(nets):
        if i == 0:
            equities.append(eq)
        else:
            eq = eq * (1.0 + float(net))
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
        "abs_max_dd": dd.get("abs_max_dd"),
        "dd_duration": dd.get("dd_duration_days"),
        "recovery_days": dd.get("recovery_days"),
        "recovered": dd.get("recovered"),
        "peak_date": dd.get("peak_date"),
        "trough_date": dd.get("trough_date"),
        "recovery_date": dd.get("recovery_date"),
        "drawdown": dd,
        "daily_path_dd_gate": {
            "complete": gate.get("complete"),
            "measured": gate.get("measured"),
            "fails": gate.get("fails"),
            "warnings": gate.get("warnings"),
        },
        "equities": equities,
        "dates": list(dates),
    }


def run_peer_daily_dd(
    *,
    out_dir: Path,
    max_codes: int,
    max_days: int,
    one_way_cost: float,
    log,
) -> dict[str, Any]:
    from research.class_hyp_eval import DEFAULT_EVAL_CODES

    codes = list(DEFAULT_EVAL_CODES)[: int(max_codes)]
    specs = (STICKY_SPEC, *PEER_SPECS)
    log(
        f"[w100/C] peers={[s['logic_id'] for s in PEER_SPECS]} "
        f"sticky_ref={STICKY_LOGIC_ID} codes={len(codes)} "
        f"max_days={max_days} one_way={one_way_cost} path=local_real_mirrors"
    )
    log(
        "[w100/D] sticky STABLE_RESEARCH_ONLY promote_as_main=false go=false "
        "hold_mom_grid=false"
    )

    logic_window_rows: list[dict[str, Any]] = []
    logic_tables: dict[str, list[dict[str, Any]]] = {s["logic_id"]: [] for s in specs}

    for w in W100_WINDOWS:
        wid = str(w["window_id"])
        log(f"[w100/C] window {wid} ({w['label']}) — {w['data_note']}")
        shard_bars: list[dict[str, Any]] = []
        for shard in w["shards"]:
            loaded = w99._load_shard_bars(shard, codes=codes, max_days=max_days)
            shard_bars.append(loaded)
            if loaded.get("status") != "ok":
                log(f"[w100/C]   {loaded.get('period_id')}: {loaded.get('status')}")

        for spec in specs:
            lid = str(spec["logic_id"])
            stitch_dates: list[str] = []
            stitch_net: list[float] = []
            stitch_gross: list[float] = []
            shard_summaries: list[dict[str, Any]] = []
            for loaded in shard_bars:
                pid = str(loaded.get("period_id"))
                if loaded.get("status") != "ok":
                    shard_summaries.append(
                        {"period_id": pid, "status": loaded.get("status")}
                    )
                    continue
                pack = evaluate_spec_on_bars(
                    loaded["bars"], spec=spec, one_way_cost=float(one_way_cost)
                )
                summary = _summarize_path(pack)
                summary["period_id"] = pid
                summary["window_id"] = wid
                shard_summaries.append(summary)
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
                log(
                    f"[w100/C]   {lid} {pid}: n={summary.get('n_equity_points')} "
                    f"total_net={_fmt(summary.get('total_return_net'))} "
                    f"daily_path_DD={_fmt(summary.get('daily_path_DD'))} "
                    f"dd_dur={summary.get('dd_duration')} "
                    f"recov={summary.get('recovery_days')}"
                )

            stitched = _stitch_net(stitch_net, stitch_dates)
            g_eq = 1.0
            for i, g in enumerate(stitch_gross):
                if i == 0:
                    continue
                g_eq *= 1.0 + float(g)
            row = {
                "logic_id": lid,
                "window_id": wid,
                "label": w["label"],
                "data_note": w["data_note"],
                "data_path": "local_real_mirrors",
                "catalog": bool(spec.get("catalog")),
                "new_thesis": bool(spec.get("new_thesis")),
                "reference_only": bool(spec.get("reference_only")),
                "why": spec.get("why"),
                "hold_days": spec.get("hold_days"),
                "momentum_n": spec.get("momentum_n"),
                "kind": spec.get("kind"),
                "promote_as_main": False,
                "go": False,
                "research_only": True,
                "stance": (
                    STICKY_STANCE if lid == STICKY_LOGIC_ID else "RESEARCH_ONLY"
                ),
                "n_shards_ok": sum(
                    1 for s in shard_summaries if s.get("status") == "ok"
                ),
                "n_equity_points": stitched.get("n_equity_points"),
                "total_return_net": stitched.get("total_return_net"),
                "total_return_gross": g_eq - 1.0 if stitch_gross else None,
                "mean_net_daily": (
                    sum(stitch_net[1:]) / max(1, len(stitch_net) - 1)
                    if len(stitch_net) > 1
                    else None
                ),
                "daily_path_DD": stitched.get("daily_path_DD"),
                "abs_max_dd": stitched.get("abs_max_dd"),
                "dd_duration": stitched.get("dd_duration"),
                "recovery_days": stitched.get("recovery_days"),
                "recovered": stitched.get("recovered"),
                "peak_date": stitched.get("peak_date"),
                "trough_date": stitched.get("trough_date"),
                "recovery_date": stitched.get("recovery_date"),
                "daily_path_complete": (stitched.get("daily_path_dd_gate") or {}).get(
                    "complete"
                ),
                "shard_summaries": shard_summaries,
                "warning": (
                    "period_net_DD=0 is an aggregation artifact — NOT riskless. "
                    "Use daily_path_DD."
                ),
            }
            logic_window_rows.append(row)
            logic_tables[lid].append(row)
            _dump(
                out_dir / f"peer_{lid}_{wid}.json",
                {
                    k: v
                    for k, v in row.items()
                    if k != "shard_summaries"
                }
                | {"shard_summaries": shard_summaries},
            )

    compact_table: list[dict[str, Any]] = []
    for row in logic_window_rows:
        compact_table.append(
            {
                "logic_id": row["logic_id"],
                "window": row["window_id"],
                "n_days": row["n_equity_points"],
                "daily_path_DD": row["daily_path_DD"],
                "dd_duration": row["dd_duration"],
                "recovery_days": row["recovery_days"],
                "recovered": row["recovered"],
                "total_ret_net": row["total_return_net"],
                "daily_path_complete": row["daily_path_complete"],
                "promote_as_main": False,
                "go": False,
                "stance": row["stance"],
                "new_thesis": row["new_thesis"],
                "reference_only": row["reference_only"],
            }
        )
    _dump(out_dir / "peer_daily_dd_table.json", compact_table)
    _dump(out_dir / "peer_window_rows.json", logic_window_rows)
    return {
        "table": compact_table,
        "windows": logic_window_rows,
        "logic_ids": [s["logic_id"] for s in specs],
        "peer_logic_ids": [s["logic_id"] for s in PEER_SPECS],
        "sticky": {
            "logic_id": STICKY_LOGIC_ID,
            "stance": STICKY_STANCE,
            "promote_as_main": False,
            "go": False,
            "hold_mom_microgrid": False,
        },
        "codes": codes,
        "max_codes": int(max_codes),
        "max_days": int(max_days),
        "one_way_cost": float(one_way_cost),
        "n_peers": len(PEER_SPECS),
        "full_grid": False,
        "hold_mom_microgrid": False,
    }


def run_track_e_hyps(
    *,
    out_dir: Path,
    n_hyps: int,
    provider: str,
    model: str | None,
    seed: int,
    synthetic: bool,
    cf_url: str,
    peer_table: Sequence[Mapping[str, Any]],
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
        f"[w100/E] generating n={n_hyps} provider={resolved_provider} "
        f"wave={LLM_HYP_WAVE} ver={LLM_HYP_VERSION} "
        f"reduce_weak_template_mapping=True"
    )

    gen_eval = generate_and_evaluate_hypotheses(
        n=int(n_hyps),
        provider=None if resolved_provider == "auto" else resolved_provider,
        model=model,
        worker_url=cf_url,
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
    n_gen_rejected = n_proposed - n_accepted
    n_eval_rejected = len(gen_eval.get("rejected_proposals") or [])
    n_survivors = int(gen_eval.get("n_survivors") or 0)
    theses = list(gen_eval.get("representative_theses") or [])
    n_skipped_weak = int(gen_eval.get("n_skipped_weak_catalog_map") or 0)

    demoted_weak_mapped: list[str] = []
    for s in gen_eval.get("eval_screens") or []:
        if not isinstance(s, Mapping) or not s.get("survived"):
            continue
        lid = str(s.get("logic_id") or "")
        if lid in KNOWN_DEMOTED_OR_WEAK or lid in KNOWN_WEAK_THESIS:
            demoted_weak_mapped.append(lid)

    skipped_ids: list[str] = []
    mapped_ids: list[str] = []
    for p in gen_eval.get("proposals_for_eval") or []:
        if not isinstance(p, Mapping):
            continue
        if p.get("skipped_weak_catalog_map"):
            skipped_ids.append(str(p.get("skipped_weak_catalog_map")))
        if p.get("eval_mapped_to_catalog") and p.get("logic_id") in KNOWN_DEMOTED_OR_WEAK:
            mapped_ids.append(str(p.get("logic_id")))

    # Attach daily_path_DD for survivors that share a peer/sticky logic.
    by_logic_window: dict[str, list[dict[str, Any]]] = {}
    for row in peer_table:
        by_logic_window.setdefault(str(row.get("logic_id")), []).append(dict(row))

    survivor_daily: list[dict[str, Any]] = []
    for s in gen_eval.get("eval_screens") or []:
        if not isinstance(s, Mapping) or not s.get("survived"):
            continue
        lid = str(s.get("logic_id") or "")
        peer_rows = by_logic_window.get(lid) or []
        if peer_rows:
            daily_pack = {
                "logic_id": lid,
                "survived_period_net_screen": True,
                "daily_path_source": "w100_peer_or_sticky_same_logic",
                "windows": peer_rows,
                "daily_path_DD_required": True,
                "promote_as_main": False,
                "go": False,
            }
            # Gate: all windows must have daily measured.
            all_complete = all(bool(r.get("daily_path_complete")) for r in peer_rows)
            daily_pack["daily_path_complete"] = all_complete
        else:
            # Honest: period-net screen without daily path = incomplete.
            gate = evaluate_daily_path_dd_gate(period_net_dd=s.get("mean_net"))
            daily_pack = {
                "logic_id": lid,
                "survived_period_net_screen": True,
                "daily_path_source": None,
                "daily_path_DD_required": True,
                "daily_path_complete": False,
                "incomplete_reason": (
                    "period-net eval screen only; daily_path_DD unmeasured "
                    "on local_real_mirrors for this mapped logic. "
                    "Incomplete — not main / not GO."
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
        survivor_daily.append(daily_pack)

    # New implemented thesis (dispersion gate) already has daily_path_DD.
    new_thesis_daily = [
        r
        for r in peer_table
        if r.get("logic_id") == "xs_cs_dispersion_gate"
    ]

    summary = {
        "wave": "W100 / w0819c",
        "track": "E_constrained_hyp_gen",
        "provider": gen_eval.get("provider"),
        "model": gen_eval.get("model"),
        "llm_hyp_version": LLM_HYP_VERSION,
        "n_requested": int(n_hyps),
        "n_proposed": n_proposed,
        "n_accepted": n_accepted,
        "n_rejected_generation": n_gen_rejected,
        "n_rejected_evaluator": n_eval_rejected,
        "n_rejected": n_gen_rejected + n_eval_rejected,
        "n_evaluated": gen_eval.get("n_evaluated"),
        "n_survivors": n_survivors,
        "n_skipped_weak_catalog_map": n_skipped_weak or len(skipped_ids),
        "skipped_weak_catalog_targets": sorted(set(skipped_ids)),
        "weak_mapped_despite_reduce": sorted(set(mapped_ids)),
        "representative_theses": theses,
        "demoted_weak_mapped_survivors": sorted(set(demoted_weak_mapped)),
        "do_not_resurrect_as_main": True,
        "reduce_weak_template_mapping": True,
        "failure_mode_constraints": [
            "no_sign_flip_single_regime_reliance",
            "no_soft_eq_pressure",
            "no_low_var_t_trust",
            "no_window_only",
            "no_dual_options_level",
            "no_repolish_shape_rate_flow_demoted_fund_slow",
            "no_hold_mom_frac_grid",
            "reduce_map_onto_known_weak_templates",
        ],
        "routed_through": "propose_profit_hypotheses",
        "gates": ["cost", "PIT", "low_var", "daily_path_DD"],
        "daily_path_DD_required": True,
        "implemented_new_thesis": {
            "logic_id": "xs_cs_dispersion_gate",
            "daily_path_DD_required": True,
            "daily_path_complete": bool(new_thesis_daily)
            and all(bool(r.get("daily_path_complete")) for r in new_thesis_daily),
            "windows": new_thesis_daily,
            "promote_as_main": False,
            "go": False,
            "catalog": False,
            "research_only": True,
        },
        "survivor_daily_path": survivor_daily,
        "frozen_defaults_retuned": False,
        "frozen_defaults": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "mass_research": MASS_RESEARCH,
        "continuous_paper": CONTINUOUS_PAPER,
        "promote_as_main": False,
        "go": False,
        "seed": int(seed),
    }
    _dump(out_dir / "hyp_summary.json", summary)
    log(
        f"[w100/E] n_proposed={n_proposed} n_accepted={n_accepted} "
        f"n_rejected={summary['n_rejected']} "
        f"(gen={n_gen_rejected}+eval={n_eval_rejected}) "
        f"n_survivors={n_survivors} n_skipped_weak_map="
        f"{summary['n_skipped_weak_catalog_map']} model={gen_eval.get('model')}"
    )
    for th in theses[:8]:
        log(
            f"  · {th.get('logic_id')}: "
            f"{str(th.get('thesis') or '')[:120]}"
        )
    log(
        "[w100/E] new thesis xs_cs_dispersion_gate evaluated WITH daily_path_DD; "
        "survivors research-only; promote_as_main=false go=false"
    )
    return {"summary": summary, "gen_eval": gen_eval}


def _page_rows(page_path: Path) -> list[dict]:
    raw = page_path.read_bytes()
    if not raw or len(raw.strip()) < 8:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    return []


def _dates_in_rows(rows: list[dict]) -> set[str]:
    out: set[str] = set()
    for r in rows:
        d = r.get("Date") or r.get("date")
        if d:
            out.add(str(d)[:10])
    return out


def run_misdate_reprobe(*, out_dir: Path, log) -> dict[str, Any]:
    """Optional re-probe. Never invent COMPLETE / never raise floor."""
    from data_contracts.permanent_defer import (
        MASTER_COVERAGE_POLICY,
        master_band_for_segment,
        master_pre_plan_descope,
    )

    db = ROOT / "data" / "structured" / "ingestion.sqlite"
    prior_pages = ROOT / ".glm-logs" / "w0815b_g10_master" / "pages"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = conn.execute(
        """
        SELECT segment_id, status, receipt_run_id
        FROM coverage_segments
        WHERE dataset='equities_master'
        ORDER BY segment_id
        """
    ).fetchall()
    conn.close()
    complete = [r for r in rows if r[1] == "COMPLETE"]
    partial = [r for r in rows if r[1] == "PARTIAL"]
    island = [r for r in complete if r[0] >= "2008-05"]
    island_partial = [r for r in partial if r[0] >= "2008-05"]
    mis = [r for r in partial if "2006-08" <= r[0] <= "2008-04"]
    audit = {
        "complete_n": len(complete),
        "partial_n": len(partial),
        "post_island_complete_n": len(island),
        "post_island_span": [island[0][0], island[-1][0]] if island else None,
        "post_island_partial_holes": [r[0] for r in island_partial],
        "misdate_n": len(mis),
        "pre_plan_descope": True,
    }

    date_ctr: Counter[str] = Counter()
    n_pages = 0
    n_rows = 0
    if prior_pages.is_dir():
        for p in sorted(prior_pages.glob("*")):
            if not p.is_file() or p.stat().st_size < 8:
                continue
            prow = _page_rows(p)
            if not prow:
                continue
            n_pages += 1
            n_rows += len(prow)
            for d in _dates_in_rows(prow):
                date_ctr[d] += 1
    by_month = {m: 0 for m in MISDATE_MONTHS}
    for d, c in date_ctr.items():
        m = d[:7]
        if m in by_month:
            by_month[m] += c
    sealable_cache = [m for m, n in by_month.items() if n > 0]
    prior = {
        "n_pages_parsed": n_pages,
        "n_rows": n_rows,
        "n_unique_dates": len(date_ctr),
        "top_dates": date_ctr.most_common(8),
        "sealable_misdate_months_from_cache": sealable_cache,
        "window_ok_any": bool(sealable_cache),
        "verdict": (
            "NO_IN_WINDOW_DATE_IN_PRIOR_CACHE"
            if not sealable_cache
            else "HAS_IN_WINDOW_DATE — investigate seal"
        ),
    }

    live: dict[str, Any]
    sample_days = [
        "2006-08-15",
        "2007-03-15",
        "2007-09-14",
        "2008-01-15",
        "2008-04-15",
    ]
    try:
        from ingestion.jquants.client import JQuantsClient

        client = JQuantsClient()
        results = []
        for day in sample_days:
            try:
                info = client.listed_info(date=day)
                live_rows = (
                    info
                    if isinstance(info, list)
                    else (info.get("info") or info.get("data") or [])
                )
                dates = _dates_in_rows(live_rows if isinstance(live_rows, list) else [])
                wok = sum(1 for d in dates if d[:7] == day[:7])
                results.append(
                    {
                        "day": day,
                        "status": "ok",
                        "n_rows": len(live_rows) if isinstance(live_rows, list) else None,
                        "n_unique_dates": len(dates),
                        "window_ok": wok,
                        "sealable": wok > 0,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append({"day": day, "status": "fail", "error": str(exc)[:240]})
        sealable = [r for r in results if r.get("sealable")]
        live = {
            "status": "probed",
            "sample_days": sample_days,
            "results": results,
            "n_sealable": len(sealable),
            "verdict": (
                "SEAL_CANDIDATES"
                if sealable
                else "NO_IN_WINDOW_DATE — keep MISDATE PARTIAL"
            ),
        }
    except Exception as exc:  # noqa: BLE001
        live = {"status": "probe_unavailable", "error": str(exc)[:400]}

    n_sealable = int(live.get("n_sealable") or 0)
    action = "KEEP_PARTIAL_NO_SEAL"
    if n_sealable > 0:
        action = "SEAL_CANDIDATES_PRESENT_BUT_MANUAL_REVIEW"
    sealed_n = 0  # never auto-seal in this probe
    pack = {
        "wave": "W100 / w0819c",
        "track": "F_equities_master_misdate",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": MASTER_COVERAGE_POLICY,
        "band_examples": {
            "2005-01": master_band_for_segment("2005-01"),
            "2007-01": master_band_for_segment("2007-01"),
            "2008-05": master_band_for_segment("2008-05"),
            "pre_plan_descope_2005": master_pre_plan_descope("2005-01"),
        },
        "before_after": {
            "complete": audit["complete_n"],
            "partial": audit["partial_n"],
            "delta_complete": 0,
            "misdate_partial": audit["misdate_n"],
        },
        "audit": audit,
        "prior_cache": prior,
        "live": live,
        "action": action,
        "sealed_n": sealed_n,
        "floor_raise_to_2008_05": False,
        "dataset_complete_claimed": False,
        "note": (
            "Optional re-probe only. No in-window Date → KEEP PARTIAL. "
            "Do not fake COMPLETE. Do not raise floor."
        ),
    }
    _dump(out_dir / "master_misdate_probe.json", pack)
    log(
        f"[w100/F] MISDATE action={action} complete={audit['complete_n']} "
        f"partial={audit['partial_n']} misdate={audit['misdate_n']} "
        f"sealed={sealed_n} live={live.get('verdict') or live.get('status')}"
    )
    return pack


def refresh_projection(*, out_dir: Path, log) -> dict[str, Any]:
    """Refresh ops projection FRESH via existing script (no segment rewrite)."""
    script = ROOT / "scripts" / "ops_reeval_freshness.py"
    if not script.is_file():
        pack = {"status": "script_missing", "path": str(script)}
        _dump(out_dir / "ops_reeval_freshness.json", pack)
        log("[w100/F] projection script missing — skip")
        return pack
    log("[w100/F] ops_reeval_freshness (targeted FRESH; coverage_segments untouched)")
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    pack = {
        "status": "ok" if proc.returncode == 0 else "fail",
        "returncode": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
        "note": "targeted freshness; coverage_segments untouched; Mass NO-GO",
    }
    _dump(out_dir / "ops_reeval_freshness.json", pack)
    (out_dir / "ops_reeval_freshness.log").write_text(
        (proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8"
    )
    log(f"[w100/F] projection status={pack['status']} rc={proc.returncode}")
    return pack


def _markdown_peer_table(analysis: Mapping[str, Any]) -> str:
    rows = list(analysis.get("table") or [])
    lines = [
        "# W100 / w0819c Track C — peer daily_path_DD (research-only)",
        "",
        "**Data path:** `local_real_mirrors`  ",
        "**Method:** daily MTM after cost (W99 `run_w99_sticky_daily_dd.py`)  ",
        "**Policy:** `promote_as_main=false` · `go=false` · no pin retune · no hold/mom grid  ",
        f"**Sticky:** `{STICKY_LOGIC_ID}` **{STICKY_STANCE}** (reference; not re-promoted)  ",
        "**Implementer:** GLM5.3 only. Grok did **not** implement.",
        "",
        "## Candidates (small set · no full grid)",
        "",
        "| logic | kind | catalog | why |",
        "|-------|------|:-------:|-----|",
        f"| `{STICKY_LOGIC_ID}` | cs_rank hold=10 mom=5 | yes | W99 reference · STABLE_RESEARCH_ONLY |",
    ]
    for s in PEER_SPECS:
        lines.append(
            f"| `{s['logic_id']}` | {s['kind']} hold={s['hold_days']} mom={s['momentum_n']} | "
            f"{'yes' if s.get('catalog') else 'NEW'} | {s['why']} |"
        )
    lines += [
        "",
        "## Daily path table (after cost)",
        "",
        "| logic | window | n_days | daily_path_DD | dd_duration | recovery | recovered | total_ret_net | stance |",
        "|-------|--------|-------:|--------------:|------------:|---------:|:---------:|--------------:|--------|",
    ]
    for r in rows:
        recov = r.get("recovery_days")
        recov_s = "—" if recov is None else str(recov)
        lines.append(
            f"| `{r.get('logic_id')}` | {r.get('window')} | {r.get('n_days')} | "
            f"{_fmt(r.get('daily_path_DD'))} | {r.get('dd_duration')} | {recov_s} | "
            f"{r.get('recovered')} | {_fmt(r.get('total_ret_net'))} | {r.get('stance')} |"
        )
    lines += [
        "",
        "> **Warning:** period-net DD = 0 when all period nets are positive is an",
        "> **aggregation artifact**. It does **not** mean the strategy is riskless.",
        "> Use **daily_path_DD** (and duration / recovery / total_ret_net).",
        "",
        "## Stance (frozen)",
        "",
        "| field | value |",
        "|-------|-------|",
        "| promote_as_main | **False** (all rows) |",
        "| go / go_eligible | **False** |",
        f"| `{STICKY_LOGIC_ID}` | **{STICKY_STANCE}** |",
        "| hold/mom micro-grid | **not run** |",
        "| full catalog grid | **not run** |",
        "| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--one-way-cost", type=float, default=0.001)
    p.add_argument("--n-hyps", type=int, default=6)
    p.add_argument("--seed", type=int, default=890819)
    p.add_argument("--provider", type=str, default="xai")
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--skip-hyps", action="store_true")
    p.add_argument("--skip-misdate", action="store_true")
    p.add_argument("--skip-projection", action="store_true")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w100_peer_daily_dd.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w100] pins_untouched={pins['pins_untouched']}")
    log(
        "[w100] promote_as_main=false go=false hold_mom_grid=false "
        "path=local_real_mirrors GLM implementer only. Grok did not implement."
    )

    analysis = run_peer_daily_dd(
        out_dir=out_dir,
        max_codes=int(args.max_codes),
        max_days=int(args.max_days),
        one_way_cost=float(args.one_way_cost),
        log=log,
    )
    md = _markdown_peer_table(analysis)
    (out_dir / "peer_daily_dd_table.md").write_text(md, encoding="utf-8")

    hyp_pack: dict[str, Any] | None = None
    if not args.skip_hyps:
        hyp_pack = run_track_e_hyps(
            out_dir=out_dir,
            n_hyps=int(args.n_hyps),
            provider=str(args.provider),
            model=args.model,
            seed=int(args.seed),
            synthetic=bool(args.synthetic),
            cf_url=CF_WORKER_URL,
            peer_table=analysis.get("table") or [],
            log=log,
        )
    else:
        log("[w100/E] hyps skipped")

    misdate: dict[str, Any] | None = None
    if not args.skip_misdate:
        misdate = run_misdate_reprobe(out_dir=out_dir, log=log)
    else:
        log("[w100/F] MISDATE skipped")

    projection: dict[str, Any] | None = None
    if not args.skip_projection:
        projection = refresh_projection(out_dir=out_dir, log=log)
    else:
        log("[w100/F] projection skipped")

    git_sha = None
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
        ).strip()
    except Exception:
        git_sha = None

    pins_after = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert_after.json", pins_after)

    summary = {
        "wave": "W100 / w0819c",
        "tracks": "C_peer_daily_dd + D_sticky_stable + E_hyps + F_misdate_proj",
        "data_path": "local_real_mirrors",
        "promote_as_main": False,
        "go": False,
        "go_eligible": False,
        "research_only": True,
        "hold_mom_microgrid": False,
        "full_grid": False,
        "sticky": analysis.get("sticky"),
        "pins_untouched": pins_after.get("pins_untouched"),
        "pins_retuned": False,
        "peer_logic_ids": analysis.get("peer_logic_ids"),
        "table": analysis.get("table"),
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
        "warning": (
            "period_net_DD=0 is an aggregation artifact — NOT riskless. "
            "Use daily_path_DD."
        ),
        "git_sha_at_run": git_sha,
        "wall_sec": round(time.time() - t0, 1),
        "implementer": "GLM5.3 only. Grok did not implement.",
    }
    _dump(out_dir / "summary.json", summary)
    log(f"[w100] SUMMARY wall_sec={summary['wall_sec']} sha={git_sha}")
    log("[w100] GLM implementer only. Grok did not implement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
