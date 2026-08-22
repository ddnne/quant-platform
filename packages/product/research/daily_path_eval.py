"""Candidate-grade daily MTM path helpers.

CF ``research-mass-eval`` returns period-net screens only (``n_survivors`` is
not a pass). Daily equity-curve drawdown lives here. Record via
``scripts/record_research_eval.py --put-r2``.

Does not arm Mass / READY / GO. Does not retune frozen default pins.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from contextvars import ContextVar
from typing import Any, Mapping, Sequence

_ADV_CTX: ContextVar[Mapping[str, float] | None] = ContextVar(
    "held_book_adv_by_code", default=None
)

from research.eval_windows import HONEST_3Y_WINDOWS
from research.freezes import assert_frozen_pins_untouched
from research.stats_metrics import (
    equity_path_drawdown,
    evaluate_daily_path_dd_gate,
)

def set_held_book_adv(adv_by_code: Mapping[str, float] | None):
    """Bind ADV for unique_logic callers that do not thread the arg."""
    return _ADV_CTX.set(adv_by_code)


def reset_held_book_adv(token) -> None:
    _ADV_CTX.reset(token)


EVAL_PROTOCOL: str = "daily_path_mtm_after_cost/v1"
R2_EVAL_PREFIX: str = "research/eval"


def dump_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def git_sha(*, cwd: Path | None = None) -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd) if cwd is not None else None,
            text=True,
        )
        return out.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def scalar_f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return fv if math.isfinite(fv) else None


def fmt(v: Any, nd: int = 6) -> str:
    x = scalar_f(v)
    return f"{x:.{nd}f}" if x is not None else "—"


def load_shard_bars(
    shard: Mapping[str, Any],
    *,
    codes: Sequence[str],
    max_days: int,
) -> dict[str, Any]:
    from research.class_hyp_eval import (
        bars_rich_to_close_panel,
        load_bars_ndjson_rich,
        resolve_bars_path,
    )

    pid = str(shard.get("period_id"))
    p_start = str(shard.get("period_start") or "")[:10] or None
    p_end = str(shard.get("period_end") or "")[:10] or None
    bars_path = resolve_bars_path(pid)
    if bars_path is None or not Path(bars_path).exists():
        return {
            "period_id": pid,
            "status": "missing_bars",
            "bars": {},
            "bars_path": None,
            "period_start": p_start,
            "period_end": p_end,
            "year": shard.get("year"),
        }
    rich = load_bars_ndjson_rich(
        bars_path,
        codes=list(codes),
        max_days=int(max_days),
        period_start=p_start,
        period_end=p_end,
    )
    bars = bars_rich_to_close_panel(rich)
    adv_by_code: dict[str, float] = {}
    for code, pairs in (rich or {}).items():
        vals: list[float] = []
        for _d, rec in pairs:
            if not isinstance(rec, dict):
                continue
            va = rec.get("Va")
            try:
                if va is not None:
                    vals.append(float(va))
                    continue
            except (TypeError, ValueError):
                pass
            try:
                vo = rec.get("Vo")
                px = rec.get("close")
                if vo is not None and px is not None:
                    vals.append(float(vo) * float(px))
            except (TypeError, ValueError):
                continue
        if vals:
            adv_by_code[str(code)] = sum(vals) / len(vals)
    return {
        "period_id": pid,
        "status": "ok" if bars else "empty_bars",
        "bars": bars,
        "adv_by_code": adv_by_code,
        "bars_path": str(bars_path),
        "period_start": p_start,
        "period_end": p_end,
        "year": shard.get("year"),
        "n_codes": len(bars),
        "n_days_max": max((len(v) for v in bars.values()), default=0),
    }


def summarize_path(pack: Mapping[str, Any]) -> dict[str, Any]:
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
        "period_ref_net_mean_active": pack.get("period_ref_net_mean_active"),
        "period_ref_gross_mean_active": pack.get("period_ref_gross_mean_active"),
        "daily_path_DD": dd.get("max_dd") if "daily_path_DD" not in pack else pack.get("daily_path_DD"),
        "max_dd": dd.get("max_dd"),
        "abs_max_dd": dd.get("abs_max_dd"),
        "dd_duration": dd.get("dd_duration_days"),
        "dd_duration_days": dd.get("dd_duration_days"),
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


def stitch_net(nets: Sequence[float], dates: Sequence[str]) -> dict[str, Any]:
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


def held_book_daily_mtm(
    *,
    held_by_code_date: Mapping[str, Mapping[str, float | None]],
    close_by: Mapping[str, Mapping[str, float]],
    dates: Sequence[str],
    hold_days: int,
    one_way_cost: float,
    logic_id: str,
    extra: Mapping[str, Any] | None = None,
    repo_by_date: Mapping[str, float] | None = None,
    adv_by_code: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Equal-weight daily MTM of a pre-built held book.

    Cost stack: amortized one-way tx + optional short-repo drag.
    When ``adv_by_code`` is present, both tx and repo drag are scaled by a
    liquidity bucket (ADV≥1e9×1.0, ≥1e8×1.5, else ×2.5). Missing ADV is
    disclosed as tx+repo only — never invented.
    """
    from features.class_signals import amortized_one_way_cost

    if adv_by_code is None and extra:
        raw_adv = extra.get("adv_by_code")
        if isinstance(raw_adv, Mapping):
            adv_by_code = raw_adv
    if adv_by_code is None:
        ctx_adv = _ADV_CTX.get()
        if isinstance(ctx_adv, Mapping):
            adv_by_code = ctx_adv
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
        n_short = 0
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
            if float(pos) < 0:
                n_short += 1
        n_active = len(contribs)
        if n_active == 0:
            g = 0.0
            cost_drag = 0.0
            net = 0.0
        else:
            g = float(sum(contribs) / n_active)
            liq = 1.0
            if adv_by_code:
                mults: list[float] = []
                for code, cmap in held_by_code_date.items():
                    pos = cmap.get(d_prev)
                    if not pos:
                        continue
                    adv = adv_by_code.get(code)
                    if adv is None:
                        continue
                    if float(adv) >= 1e9:
                        mults.append(1.0)
                    elif float(adv) >= 1e8:
                        mults.append(1.5)
                    else:
                        mults.append(2.5)
                if mults:
                    liq = sum(mults) / len(mults)
            short_drag = 0.0
            if n_short and repo_by_date is not None:
                repo = repo_by_date.get(d_prev)
                if repo is not None:
                    short_drag = (n_short / n_active) * (float(repo) / 100.0 / 252.0) * liq
            cost_drag = daily_cost * liq + short_drag
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


def panel_index(
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



