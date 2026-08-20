#!/usr/bin/env python3
"""W99 / w0819b Track B — true daily drawdown for xs_rank_ls_sticky.

PRIORITY: W98 ``max_dd_proxy=0`` came from **period-net cumsum** when all
period nets were positive. That is an **aggregation artifact**, not “no risk”.

This wave builds a **daily (holding-period mark-to-market) equity curve after
costs** on local ``real_mirrors``, then reports max DD / DD duration /
recovery / after-cost returns for windows:

  * w2017_2019
  * w2020_2022
  * w2023_2025

CF mass-eval returns period aggregates only — **no daily path**. Therefore
this script uses **local real_mirrors**, honestly labeled.

Policy (held)
-------------
* ``promote_as_main=False`` · ``go=False``
* **no** pin retune · **no** hold/mom micro-grid
* Mass NO-GO · READY 未宣言 · Phase7 OFF · continuous paper UNARMED
* Never claim period-net DD=0 means riskless

Examples
--------
    uv run python scripts/run_w99_sticky_daily_dd.py \\
        --out-dir .glm-logs/w0819b_w99_otc_sticky_dd/
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
OUT_DEFAULT = ROOT / ".glm-logs" / "w0819b_w99_otc_sticky_dd"
PROOF_DEFAULT = ROOT / "docs" / "proof" / "w0819b_w99_sticky_daily_dd_20260819.md"

LOGIC_ID = "xs_rank_ls_sticky"

# Shared catalog — do not fork windows in new wave scripts.
from research.eval_windows import (  # noqa: E402
    FROZEN_PIN_SNAPSHOT,
    HONEST_3Y_WINDOWS as W99_WINDOWS,
)
from research.daily_path_eval import (  # noqa: E402
    assert_frozen_pins_untouched as _assert_frozen_pins_untouched,
    dump_json as _dump,
    fmt as _fmt,
    load_shard_bars as _load_shard_bars,
    scalar_f as _scalar_f,
    summarize_path as _summarize_path,
)
from research.stats_metrics import equity_path_drawdown  # noqa: E402,F401

# W98 CF preferred period-net DD proxy (all-positive nets → 0 artifact).
W98_CF_PERIOD_NET_DD: dict[str, float] = {
    "w2017_2019": 0.0,
    "w2020_2022": 0.0,
    "w2023_2025": 0.0,
}
W98_CF_PERIOD_NETS: dict[str, list[float]] = {
    "w2017_2019": [0.022731, 0.002670],
    "w2020_2022": [0.003867],
    "w2023_2025": [0.028537, 0.016140],
}


def _period_net_dd_proxy(nets: Sequence[float | None]) -> dict[str, Any]:
    """Period-net cumsum DD proxy (W98 method) — aggregation grain only."""
    from research.stats_metrics import max_drawdown

    vals = [float(v) for v in nets if v is not None and math.isfinite(float(v))]
    if not vals:
        return {
            "max_dd": None,
            "abs_max_dd": None,
            "n": 0,
            "method": "period_net_cumsum_proxy",
            "all_positive": False,
        }
    dd = max_drawdown(vals)
    return {
        "max_dd": dd.get("max_dd"),
        "abs_max_dd": dd.get("abs_max_dd"),
        "n": len(vals),
        "period_nets": vals,
        "all_positive": all(v > 0 for v in vals),
        "method": "period_net_cumsum_proxy",
        "note": (
            "Aggregation artifact when all period nets > 0 → max_dd=0. "
            "NOT a daily equity-curve risk number. NOT riskless."
        ),
    }


def evaluate_xs_sticky_daily_mtm(
    bars_by_code: Mapping[str, Sequence[tuple[str, float]]],
    *,
    momentum_n: int = 5,
    hold_days: int = 10,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    one_way_cost: float = 0.001,
    signal_sign: int = 1,
) -> dict[str, Any]:
    """Daily mark-to-market equity path for sticky CS rank L-S after costs.

    Position construction matches ``evaluate_cross_section_on_bars`` sticky
    path (fixed_horizon hold of daily rank signs). Instead of scoring only
    multi-day forward returns at rebalance boundaries, this marks the held
    book to market **every session**.

    Cost convention (Python / local research):
      amortized = one_way / hold_days
      daily_cost_drag = amortized / hold_days when book active
      → over a full hold of H days, total drag ≈ amortized (matches period-net
        subtraction of amortized once per hold-period return).

    CF worker uses ``(2*one_way)/H`` amortized — different; this script is
    local_real_mirrors and uses the Python convention.
    """
    from features.class_signals import (
        amortized_one_way_cost,
        apply_sticky_hold,
        cross_section_rank_signs,
    )
    from research.class_hyp_eval import (
        evaluate_cross_section_on_bars,
        momentum_series,
    )

    n = int(momentum_n)
    h = int(hold_days)
    sgn = 1 if int(signal_sign) >= 0 else -1
    am_cost = float(amortized_one_way_cost(float(one_way_cost), h))
    daily_cost = float(am_cost) / float(h) if h > 0 else float(am_cost)

    by_date: dict[str, dict[str, float | None]] = {}
    dates_by_code: dict[str, list[str]] = {}
    closes_list: dict[str, list[float]] = {}
    close_by: dict[str, dict[str, float]] = {}

    for code, pairs in bars_by_code.items():
        pairs_l = list(pairs)
        if len(pairs_l) < n + 2:
            continue
        moms = momentum_series(pairs_l, n=n)
        for d, m in moms:
            by_date.setdefault(d, {})[code] = m
        dates_by_code[code] = [d for d, _ in pairs_l]
        closes_list[code] = [c for _, c in pairs_l]
        for d, c in pairs_l:
            close_by.setdefault(code, {})[d] = float(c)

    dates = sorted(by_date.keys())
    if len(dates) < 2:
        return {
            "status": "insufficient_dates",
            "n_days": len(dates),
            "daily_rows": [],
            "equities": [],
            "dates": [],
            "gross_daily": [],
            "net_daily": [],
        }

    # Per-code sticky held signs on each code's own date index.
    held_by_code_date: dict[str, dict[str, float | None]] = {}
    daily_rank: dict[str, dict[str, float | None]] = {c: {} for c in dates_by_code}
    for d in dates:
        ranks = cross_section_rank_signs(
            by_date.get(d) or {}, long_frac=long_frac, short_frac=short_frac
        )
        for code, sign in ranks.items():
            daily_rank.setdefault(code, {})[d] = sign

    for code, dlist in dates_by_code.items():
        entries = [daily_rank.get(code, {}).get(d) for d in dlist]
        held = apply_sticky_hold(entries, hold_days=h, rebalance_mode="fixed_horizon")
        held_by_code_date[code] = {
            dlist[i]: (None if held[i] is None else float(held[i]) * sgn)
            for i in range(len(dlist))
        }

    # Calendar union daily book MTM (equal-weight active names).
    daily_rows: list[dict[str, Any]] = []
    gross_daily: list[float] = []
    net_daily: list[float] = []
    eq_dates: list[str] = []
    equities: list[float] = []
    equity = 1.0

    # Start equity on first date with no return yet (mark day 0).
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
            pos = cmap.get(d_prev)  # position held through overnight into d
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

    # Period-grain reference (same bars) for contrast.
    period_ref = evaluate_cross_section_on_bars(
        bars_by_code,
        momentum_n=n,
        hold_days=h,
        long_frac=long_frac,
        short_frac=short_frac,
        one_way_cost=float(one_way_cost),
    )
    # Apply signal_sign to period net for reporting consistency.
    p_gross = _scalar_f(period_ref.get("gross_signed_mean_active"))
    p_net = _scalar_f(period_ref.get("net_one_way_mean_active"))
    if p_gross is not None and sgn < 0:
        p_gross = -p_gross
        p_net = (p_gross - am_cost) if p_gross is not None else None

    dd = equity_path_drawdown(equities, eq_dates)
    # Gross-only equity for cost-drag illustration
    g_eq = 1.0
    for g in gross_daily[1:]:
        g_eq *= 1.0 + g
    total_ret_net = dd.get("total_return")
    total_ret_gross = g_eq - 1.0

    active_days = sum(1 for r in daily_rows[1:] if int(r.get("n_active") or 0) > 0)
    mean_net = (
        sum(net_daily[1:]) / max(1, len(net_daily) - 1) if len(net_daily) > 1 else None
    )
    mean_gross = (
        sum(gross_daily[1:]) / max(1, len(gross_daily) - 1)
        if len(gross_daily) > 1
        else None
    )

    return {
        "status": "ok",
        "signal_id": "c21_xs_rank_ls_sticky_daily_mtm",
        "logic_id": LOGIC_ID,
        "momentum_n": n,
        "hold_days": h,
        "long_frac": float(long_frac),
        "short_frac": float(short_frac),
        "one_way_cost": float(one_way_cost),
        "amortized_one_way_cost": am_cost,
        "daily_cost_drag": daily_cost,
        "signal_sign": sgn,
        "n_codes": len(dates_by_code),
        "n_calendar_days": len(dates),
        "n_equity_points": len(equities),
        "n_active_days": active_days,
        "mean_gross_daily": mean_gross,
        "mean_net_daily": mean_net,
        "total_return_gross": total_ret_gross,
        "total_return_net": total_ret_net,
        "period_ref_gross_mean_active": p_gross,
        "period_ref_net_mean_active": p_net,
        "period_ref_n_active_positions": period_ref.get("n_active_positions"),
        "period_ref_activation_rate": (period_ref.get("occurrence") or {}).get(
            "activation_rate"
        ),
        "drawdown": dd,
        "dates": eq_dates,
        "equities": equities,
        "gross_daily": gross_daily,
        "net_daily": net_daily,
        "daily_rows": daily_rows,
        "cost_convention": (
            "python_local: daily_cost = (one_way/hold_days)/hold_days while active; "
            "over H active days ≈ amortized once (matches period-net am_cost)."
        ),
        "data_path": "local_real_mirrors",
        "note": (
            "Daily MTM of sticky CS L-S book after amortized cost drag. "
            "Research-only. Not READY / not Mass / not GO."
        ),
    }



def run_analysis(
    *,
    out_dir: Path,
    max_codes: int,
    max_days: int,
    one_way_cost: float,
    log,
) -> dict[str, Any]:
    from research.class_hyp_eval import DEFAULT_EVAL_CODES
    from research.mass_strategy_factory import LOGIC_TEMPLATES

    tpl = LOGIC_TEMPLATES[LOGIC_ID]
    params = dict(tpl.base_params)
    assert int(params["hold_days"]) == 10
    assert int(params["momentum_n"]) == 5

    codes = list(DEFAULT_EVAL_CODES)[: int(max_codes)]
    log(
        f"[w99] logic={LOGIC_ID} params={params} codes={len(codes)} "
        f"max_days={max_days} one_way={one_way_cost} path=local_real_mirrors"
    )

    shard_results: list[dict[str, Any]] = []
    window_results: list[dict[str, Any]] = []

    for w in W99_WINDOWS:
        wid = str(w["window_id"])
        log(f"[w99] window {wid} ({w['label']}) — {w['data_note']}")
        shard_packs: list[dict[str, Any]] = []
        stitch_dates: list[str] = []
        stitch_net: list[float] = []
        stitch_gross: list[float] = []
        local_period_nets: list[float] = []

        for shard in w["shards"]:
            loaded = _load_shard_bars(shard, codes=codes, max_days=max_days)
            pid = str(loaded["period_id"])
            if loaded.get("status") != "ok":
                log(f"[w99]   {pid}: {loaded.get('status')}")
                shard_packs.append(
                    {
                        "period_id": pid,
                        "window_id": wid,
                        "status": loaded.get("status"),
                        "bars_path": loaded.get("bars_path"),
                    }
                )
                continue
            pack = evaluate_xs_sticky_daily_mtm(
                loaded["bars"],
                momentum_n=int(params["momentum_n"]),
                hold_days=int(params["hold_days"]),
                long_frac=float(params["long_frac"]),
                short_frac=float(params["short_frac"]),
                one_way_cost=float(one_way_cost),
                signal_sign=1,
            )
            summary = _summarize_path(pack)
            row = {
                "period_id": pid,
                "window_id": wid,
                "year": loaded.get("year"),
                "period_start": loaded.get("period_start"),
                "period_end": loaded.get("period_end"),
                "bars_path": loaded.get("bars_path"),
                "n_codes": loaded.get("n_codes"),
                "n_days_max": loaded.get("n_days_max"),
                **summary,
                # Keep compact daily series for artifacts (not full rows in summary json)
                "dates": pack.get("dates"),
                "equities": pack.get("equities"),
                "net_daily": pack.get("net_daily"),
                "gross_daily": pack.get("gross_daily"),
                "drawdown": pack.get("drawdown"),
                "amortized_one_way_cost": pack.get("amortized_one_way_cost"),
                "daily_cost_drag": pack.get("daily_cost_drag"),
                "cost_convention": pack.get("cost_convention"),
            }
            shard_packs.append(row)
            shard_results.append(row)
            pnet = _scalar_f(pack.get("period_ref_net_mean_active"))
            if pnet is not None:
                local_period_nets.append(pnet)
            # Stitch: skip duplicate start mark when appending next shard
            dlist = list(pack.get("dates") or [])
            nlist = list(pack.get("net_daily") or [])
            glist = list(pack.get("gross_daily") or [])
            if not stitch_dates:
                stitch_dates = list(dlist)
                stitch_net = list(nlist)
                stitch_gross = list(glist)
            else:
                # Gap between shards: equity flat (no return) — dates not filled.
                stitch_dates.extend(dlist[1:])
                stitch_net.extend(nlist[1:])
                stitch_gross.extend(glist[1:])
            log(
                f"[w99]   {pid}: n={summary.get('n_equity_points')} "
                f"total_net={_fmt(summary.get('total_return_net'))} "
                f"max_dd={_fmt(summary.get('max_dd'))} "
                f"dd_dur={summary.get('dd_duration_days')} "
                f"recov={summary.get('recovery_days')} "
                f"period_net={_fmt(pnet)}"
            )

        # Window-stitched equity from concatenated daily nets (gap = omitted).
        if stitch_net:
            eq = 1.0
            equities = []
            for i, net in enumerate(stitch_net):
                if i == 0:
                    equities.append(eq)
                else:
                    eq = eq * (1.0 + float(net))
                    equities.append(eq)
            w_dd = equity_path_drawdown(equities, stitch_dates)
            g_eq = 1.0
            for i, g in enumerate(stitch_gross):
                if i == 0:
                    continue
                g_eq *= 1.0 + float(g)
            period_dd = _period_net_dd_proxy(local_period_nets)
            w_row = {
                "window_id": wid,
                "label": w["label"],
                "data_note": w["data_note"],
                "data_path": "local_real_mirrors",
                "n_shards_ok": sum(
                    1 for s in shard_packs if s.get("status") == "ok"
                ),
                "period_ids": [s.get("period_id") for s in shard_packs],
                "local_period_nets": local_period_nets,
                "period_net_dd_proxy": period_dd,
                "w98_cf_period_nets": list(W98_CF_PERIOD_NETS.get(wid) or []),
                "w98_cf_period_net_dd": W98_CF_PERIOD_NET_DD.get(wid),
                "n_equity_points": len(equities),
                "total_return_net": w_dd.get("total_return"),
                "total_return_gross": g_eq - 1.0,
                "mean_net_daily": (
                    sum(stitch_net[1:]) / max(1, len(stitch_net) - 1)
                    if len(stitch_net) > 1
                    else None
                ),
                "max_dd": w_dd.get("max_dd"),
                "abs_max_dd": w_dd.get("abs_max_dd"),
                "dd_duration_days": w_dd.get("dd_duration_days"),
                "recovery_days": w_dd.get("recovery_days"),
                "recovered": w_dd.get("recovered"),
                "peak_date": w_dd.get("peak_date"),
                "trough_date": w_dd.get("trough_date"),
                "recovery_date": w_dd.get("recovery_date"),
                "drawdown": w_dd,
                "shard_summaries": [_summarize_path(s) | {"period_id": s.get("period_id")} for s in shard_packs],
                "stitch_note": (
                    "Shards concatenated in calendar order; missing years "
                    "(e.g. 2018/2020/2022/2024) omitted — equity compounds "
                    "across available sessions only (no synthetic flat fill)."
                ),
            }
        else:
            w_row = {
                "window_id": wid,
                "label": w["label"],
                "data_note": w["data_note"],
                "data_path": "local_real_mirrors",
                "status": "no_ok_shards",
                "max_dd": None,
                "w98_cf_period_net_dd": W98_CF_PERIOD_NET_DD.get(wid),
            }
        window_results.append(w_row)

        # Per-window artifact (compact shard meta + full stitched path)
        shard_dump: list[dict[str, Any]] = []
        for s in shard_packs:
            compact = {
                k: v
                for k, v in s.items()
                if k
                not in (
                    "dates",
                    "equities",
                    "net_daily",
                    "gross_daily",
                    "daily_rows",
                )
            }
            if s.get("status") == "ok":
                eqs = list(s.get("equities") or [])
                compact["n_dates"] = len(s.get("dates") or [])
                compact["equity_start"] = eqs[0] if eqs else None
                compact["equity_end"] = eqs[-1] if eqs else None
            shard_dump.append(compact)
        _dump(
            out_dir / f"window_{wid}_daily.json",
            {
                "window": {
                    k: v
                    for k, v in w_row.items()
                    if k != "shard_summaries"
                },
                "shards": shard_dump,
                "stitched_dates": stitch_dates,
                "stitched_equities": (
                    __stitch_eq(stitch_net) if stitch_net else []
                ),
                "stitched_net_daily": stitch_net,
            },
        )

    return {
        "windows": window_results,
        "shards": [
            {
                k: v
                for k, v in s.items()
                if k not in ("dates", "equities", "net_daily", "gross_daily")
            }
            for s in shard_results
        ],
        "params": params,
        "codes": codes,
        "max_codes": int(max_codes),
        "max_days": int(max_days),
        "one_way_cost": float(one_way_cost),
    }


def __stitch_eq(nets: Sequence[float]) -> list[float]:
    eq = 1.0
    out = []
    for i, net in enumerate(nets):
        if i == 0:
            out.append(eq)
        else:
            eq = eq * (1.0 + float(net))
            out.append(eq)
    return out


def _contrast_table(windows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for w in windows:
        wid = str(w.get("window_id"))
        period_dd = w.get("period_net_dd_proxy") or {}
        rows.append(
            {
                "window": wid,
                "period_net_DD_w98_cf_artifact": W98_CF_PERIOD_NET_DD.get(wid),
                "period_net_DD_local_proxy": period_dd.get("max_dd"),
                "period_net_all_positive_local": period_dd.get("all_positive"),
                "daily_path_DD": w.get("max_dd"),
                "daily_path_abs_DD": w.get("abs_max_dd"),
                "daily_dd_duration_days": w.get("dd_duration_days"),
                "daily_recovery_days": w.get("recovery_days"),
                "daily_total_return_net": w.get("total_return_net"),
                "local_period_nets": w.get("local_period_nets"),
                "w98_cf_period_nets": w.get("w98_cf_period_nets"),
                "warning": (
                    "period_net_DD=0 is an aggregation artifact when all "
                    "period nets > 0 — NOT riskless. Use daily_path_DD."
                ),
            }
        )
    return {
        "title": "period_net_DD (=0 artifact) vs daily_path_DD",
        "rows": rows,
        "policy": (
            "Never claim period-net DD=0 means riskless. "
            "W98 CF preferred path had all-positive period nets → proxy DD=0."
        ),
    }


def _markdown(
    *,
    analysis: Mapping[str, Any],
    contrast: Mapping[str, Any],
    pins: Mapping[str, Any],
    git_sha: str | None,
) -> str:
    windows = list(analysis.get("windows") or [])
    lines = [
        "# W99 / w0819b Track B — `xs_rank_ls_sticky` true daily drawdown",
        "",
        f"**Logic:** `{LOGIC_ID}`  ",
        "**Data path:** `local_real_mirrors` (CF mass-eval cannot emit daily equity path)  ",
        f"**HEAD:** `{git_sha or 'n/a'}`  ",
        "**Policy:** `promote_as_main=false` · `go=false` · no pin retune · no hold/mom grid  ",
        "",
        "## Why this wave",
        "",
        "W98 reported `max_dd_proxy=0` from **period-net cumsum** while all CF period",
        "nets were positive. That is an **aggregation artifact**, **not** “no risk”.",
        "This wave builds a **daily mark-to-market** equity curve after costs and",
        "computes true path DD / duration / recovery.",
        "",
        "## Explicit stance (frozen)",
        "",
        "| field | value |",
        "|-------|-------|",
        "| promote_as_main | **False** |",
        "| go / go_eligible | **False** |",
        "| research_only | **True** |",
        "| hold/mom micro-grid | **not run** |",
        f"| 3-default pins untouched | **{pins.get('pins_untouched')}** |",
        "| Mass / READY / Phase7 / paper | NO-GO / 未宣言 / OFF / UNARMED |",
        "",
        "## Window table — daily path (after cost)",
        "",
        "| window | n_days | total_ret_net | total_ret_gross | mean_net_daily | max_dd | abs_dd | dd_dur | recovery | recovered | period_ref_nets |",
        "|--------|-------:|--------------:|----------------:|---------------:|-------:|-------:|-------:|---------:|:---------:|-----------------|",
    ]
    for w in windows:
        nets = w.get("local_period_nets") or []
        nets_s = ", ".join(f"{x:.6f}" for x in nets) if nets else "—"
        lines.append(
            f"| {w.get('window_id')} | {w.get('n_equity_points')} | "
            f"{_fmt(w.get('total_return_net'))} | {_fmt(w.get('total_return_gross'))} | "
            f"{_fmt(w.get('mean_net_daily'))} | {_fmt(w.get('max_dd'))} | "
            f"{_fmt(w.get('abs_max_dd'))} | {w.get('dd_duration_days')} | "
            f"{w.get('recovery_days') if w.get('recovery_days') is not None else '—'} | "
            f"{w.get('recovered')} | `{nets_s}` |"
        )

    lines += [
        "",
        "### Per-shard daily path",
        "",
        "| window | period_id | n_days | total_ret_net | max_dd | dd_dur | recovery | period_net_ref |",
        "|--------|-----------|-------:|--------------:|-------:|-------:|---------:|---------------:|",
    ]
    for w in windows:
        for s in w.get("shard_summaries") or []:
            lines.append(
                f"| {w.get('window_id')} | {s.get('period_id')} | "
                f"{s.get('n_equity_points')} | {_fmt(s.get('total_return_net'))} | "
                f"{_fmt(s.get('max_dd'))} | {s.get('dd_duration_days')} | "
                f"{s.get('recovery_days') if s.get('recovery_days') is not None else '—'} | "
                f"{_fmt(s.get('period_ref_net_mean_active'))} |"
            )

    lines += [
        "",
        "## Contrast — period_net_DD (=0 artifact) vs daily_path_DD",
        "",
        "| window | period_net_DD (W98 CF artifact) | period_net_DD (local proxy) | daily_path_DD | dd_dur | recovery | total_ret_net |",
        "|--------|--------------------------------:|----------------------------:|--------------:|-------:|---------:|--------------:|",
    ]
    for r in contrast.get("rows") or []:
        lines.append(
            f"| {r.get('window')} | {_fmt(r.get('period_net_DD_w98_cf_artifact'), 4)} | "
            f"{_fmt(r.get('period_net_DD_local_proxy'), 4)} | "
            f"{_fmt(r.get('daily_path_DD'))} | {r.get('daily_dd_duration_days')} | "
            f"{r.get('daily_recovery_days') if r.get('daily_recovery_days') is not None else '—'} | "
            f"{_fmt(r.get('daily_total_return_net'))} |"
        )

    lines += [
        "",
        "> **Warning:** period-net DD = 0 when all period nets are positive is an",
        "> **aggregation artifact**. It does **not** mean the strategy is riskless.",
        "> Use **daily_path_DD** (and duration / recovery) for path risk.",
        "",
        "## Method",
        "",
        "1. Load local `real_mirrors` bars for W98/W99 honest shards.",
        "2. Build CS momentum ranks → sticky `fixed_horizon` hold (hold=10, mom=5).",
        "3. Mark held L/S book to market **daily** (equal-weight active names).",
        "4. Subtract Python amortized daily cost drag while active.",
        "5. Equity curve peak-to-trough → max DD, duration, recovery.",
        "6. Contrast vs W98 CF period-net cumsum proxy (artifact = 0).",
        "",
        f"Params (catalog base, **not** a retune): `{analysis.get('params')}`.",
        f"Codes: first {analysis.get('max_codes')} of `DEFAULT_EVAL_CODES`; "
        f"max_days/shard={analysis.get('max_days')}.",
        "",
        "## Freezes held",
        "",
        "- promote_as_main = **false** · go = **false**",
        "- no hold/mom micro-grid · no 3-default pin retune",
        "- Mass NO-GO · READY 未宣言 · Phase7 OFF · continuous paper UNARMED",
        "",
    ]
    return "\n".join(lines)


def _write_proof(
    *,
    proof_path: Path,
    analysis: Mapping[str, Any],
    contrast: Mapping[str, Any],
    pins: Mapping[str, Any],
    git_sha: str | None,
    out_dir: Path,
) -> str:
    md = _markdown(
        analysis=analysis, contrast=contrast, pins=pins, git_sha=git_sha
    )
    # Proof wrapper with required honesty banner.
    try:
        rel_logs = str(out_dir.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        rel_logs = str(out_dir)
    body = "\n".join(
        [
            md,
            "",
            "## Artifacts",
            "",
            f"- Logs: [`{rel_logs}`](../../{rel_logs})",
            f"- Contrast JSON: `contrast_period_vs_daily.json`",
            f"- Window daily packs: `window_w*_daily.json`",
            "",
            "## Non-claims",
            "",
            "- No READY / Mass / GO / live / pin retune / hold-mom grid.",
            "- Local mirrors are **not** CF SoT; labeled `local_real_mirrors`.",
            "- Period-net DD=0 **must not** be read as riskless.",
            "",
        ]
    )
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(body, encoding="utf-8")
    return body


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=str, default=str(OUT_DEFAULT))
    p.add_argument("--proof", type=str, default=str(PROOF_DEFAULT))
    p.add_argument("--max-codes", type=int, default=15)
    p.add_argument("--max-days", type=int, default=200)
    p.add_argument("--one-way-cost", type=float, default=0.001)
    p.add_argument("--seed", type=int, default=890819)
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "w99_sticky_daily_dd.log"

    def log(msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    t0 = time.time()
    pins = _assert_frozen_pins_untouched()
    _dump(out_dir / "frozen_pins_assert.json", pins)
    log(f"[w99] pins_untouched={pins['pins_untouched']}")
    log(
        "[w99] promote_as_main=false go=false hold_mom_grid=false "
        "path=local_real_mirrors (CF has no daily equity path)"
    )

    analysis = run_analysis(
        out_dir=out_dir,
        max_codes=int(args.max_codes),
        max_days=int(args.max_days),
        one_way_cost=float(args.one_way_cost),
        log=log,
    )
    contrast = _contrast_table(analysis.get("windows") or [])
    _dump(out_dir / "contrast_period_vs_daily.json", contrast)
    _dump(out_dir / "window_table.json", analysis.get("windows"))
    _dump(out_dir / "shard_table.json", analysis.get("shards"))

    # git sha
    git_sha = None
    try:
        import subprocess

        git_sha = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
            ).strip()
        )
    except Exception:
        git_sha = None

    summary = {
        "wave": "W99 / w0819b",
        "track": "B_xs_rank_ls_sticky_daily_dd",
        "logic_id": LOGIC_ID,
        "data_path": "local_real_mirrors",
        "cf_daily_path": False,
        "cf_note": (
            "CF research-mass-eval returns period aggregates only; "
            "daily MTM equity curve computed on local real_mirrors."
        ),
        "promote_as_main": False,
        "go": False,
        "go_eligible": False,
        "research_only": True,
        "hold_mom_microgrid": False,
        "pins_untouched": pins.get("pins_untouched"),
        "pins_retuned": False,
        "params": analysis.get("params"),
        "max_codes": analysis.get("max_codes"),
        "max_days": analysis.get("max_days"),
        "one_way_cost": analysis.get("one_way_cost"),
        "windows": [
            {
                "window_id": w.get("window_id"),
                "max_dd": w.get("max_dd"),
                "abs_max_dd": w.get("abs_max_dd"),
                "dd_duration_days": w.get("dd_duration_days"),
                "recovery_days": w.get("recovery_days"),
                "total_return_net": w.get("total_return_net"),
                "w98_cf_period_net_dd": w.get("w98_cf_period_net_dd"),
                "period_net_dd_local": (w.get("period_net_dd_proxy") or {}).get(
                    "max_dd"
                ),
            }
            for w in (analysis.get("windows") or [])
        ],
        "contrast": contrast,
        "warning": (
            "period_net_DD=0 is an aggregation artifact — NOT riskless. "
            "Use daily_path_DD."
        ),
        "git_sha_at_run": git_sha,
        "wall_sec": round(time.time() - t0, 1),
        "implementer": "GLM5.3 / Grok Build",
    }
    _dump(out_dir / "summary.json", summary)

    md = _markdown(
        analysis=analysis, contrast=contrast, pins=pins, git_sha=git_sha
    )
    (out_dir / "sticky_daily_dd_table.md").write_text(md, encoding="utf-8")
    proof_path = Path(args.proof)
    _write_proof(
        proof_path=proof_path,
        analysis=analysis,
        contrast=contrast,
        pins=pins,
        git_sha=git_sha,
        out_dir=out_dir,
    )
    log(f"[w99] proof → {proof_path}")
    log(f"[w99] SUMMARY {json.dumps(summary, default=str)[:1500]}")
    for w in summary["windows"]:
        log(
            f"[w99] DD {w['window_id']}: daily={w['max_dd']} "
            f"dur={w['dd_duration_days']} recov={w['recovery_days']} "
            f"vs W98_CF_period_net_DD={w['w98_cf_period_net_dd']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
