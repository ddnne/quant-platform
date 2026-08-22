"""Equal-weight mini-combination of candidate-grade daily paths. Not a promote / GO."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from research.combo_basket_catalog import (
    DEFAULT_CANDIDATE_BASKET,
    META_BASKETS,
    RETIRED_BASKET_RULES,
    RETIRED_META_IDS,
    equal_weights,
    mechanical_basket_defs,
    meta_basket_defs,
    primary_mechanical_basket_defs,
    validate_basket_members,
)
from research.combo_basket_compare import (
    classify_sleeves_three_n,
    compare_basket_summaries,
    compare_headn_vs_liq,
    compare_mid_vs_liq,
)
from research.eval_registry import PROTOCOL_DAILY_PATH
from research.stats_metrics import equity_path_drawdown, evaluate_daily_path_dd_gate
from research.unique_logic.constants import (
    ALWAYS_ON_OCCUPANCY_WARN,
    NEAR_EMPTY_OCCUPANCY,
)

def blend_net_daily(
    series: Sequence[Sequence[float]],
    *,
    weights: Sequence[float] | None = None,
) -> list[float]:
    """Element-wise equal-weight (or supplied) average. Truncates to min length."""
    members = [list(s) for s in series if s]
    if not members:
        return []
    n = min(len(s) for s in members)
    ws = list(weights) if weights is not None else equal_weights(len(members))
    if len(ws) != len(members):
        ws = equal_weights(len(members))
    out: list[float] = []
    for i in range(n):
        out.append(sum(float(members[j][i]) * float(ws[j]) for j in range(len(members))))
    return out


def occupancy_in_candidate_band(occ: float | None) -> bool:
    if occ is None:
        return False
    return float(NEAR_EMPTY_OCCUPANCY) < float(occ) < float(ALWAYS_ON_OCCUPANCY_WARN)


def blend_window_cells(
    cells: Sequence[Mapping[str, Any]],
    *,
    basket_id: str,
    logic_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Blend member cells that share a window_id. Requires net_daily on cells."""
    by_win: dict[str, list[Mapping[str, Any]]] = {}
    want = set(logic_ids)
    for c in cells:
        lid = str(c.get("logic_id") or "")
        wid = str(c.get("window_id") or c.get("window") or "")
        if lid not in want or not wid:
            continue
        by_win.setdefault(wid, []).append(c)
    rows: list[dict[str, Any]] = []
    for wid, group in sorted(by_win.items()):
        present = {str(c.get("logic_id")): c for c in group}
        missing = [lid for lid in logic_ids if lid not in present]
        nets = []
        dates = None
        occs = []
        for lid in logic_ids:
            cell = present.get(lid)
            if cell is None:
                continue
            nd = cell.get("net_daily")
            if not isinstance(nd, list) or len(nd) < 2:
                continue
            nets.append([float(x) for x in nd])
            if dates is None:
                dates = list(cell.get("dates") or [])
            occ = cell.get("occupancy")
            if occ is None:
                occ = cell.get("occupancy_frac")
            if occ is not None:
                occs.append(float(occ))
        blended = blend_net_daily(nets)
        if len(blended) < 2:
            rows.append(
                {
                    "logic_id": basket_id,
                    "window_id": wid,
                    "window": wid,
                    "daily_path_complete": False,
                    "incomplete_reason": "missing_member_net_daily",
                    "missing_members": missing,
                    "survived": False,
                    "promote_as_main": False,
                    "go": False,
                }
            )
            continue
        eq = [1.0]
        e = 1.0
        for r in blended[1:]:
            e = e * (1.0 + float(r))
            eq.append(e)
        dlist = dates if dates and len(dates) == len(eq) else [str(i) for i in range(len(eq))]
        dd = equity_path_drawdown(eq, dlist)
        gate = evaluate_daily_path_dd_gate(
            daily_path_dd=dd.get("max_dd"),
            dd_duration=dd.get("dd_duration_days"),
            recovered=dd.get("recovered"),
            total_ret_net=dd.get("total_return"),
        )
        n_on = sum(1 for r in blended[1:] if abs(float(r)) > 1e-12)
        union_occ = (n_on / (len(blended) - 1)) if len(blended) > 1 else None
        mean_occ = (sum(occs) / len(occs)) if occs else None
        rows.append(
            {
                "logic_id": basket_id,
                "window_id": wid,
                "window": wid,
                "dates": dlist,
                "net_daily": blended,
                "occupancy": mean_occ,
                "occupancy_frac": mean_occ,
                "union_occupancy": union_occ,
                "mean_member_occupancy": mean_occ,
                "daily_path_DD": dd.get("max_dd"),
                "total_ret_net": dd.get("total_return"),
                "dd_duration": dd.get("dd_duration_days"),
                "recovered": dd.get("recovered"),
                "n_days": len(eq),
                "daily_path_complete": bool(gate.get("complete")),
                "eval_path": "equal_weight_basket",
                "members": list(logic_ids),
                "missing_members": missing,
                "weights": equal_weights(len(logic_ids)),
                "survived": False,
                "promote_as_main": False,
                "go": False,
                "candidate_grade": True,
                "period_net_dd_only_pass_forbidden": True,
                "t_stat": _t_stat(blended),
                "sharpe_daily": _sharpe(blended),
            }
        )
    return rows


def _mean_std(net_daily: Sequence[float]) -> tuple[float, float, int] | None:
    vs = [float(x) for x in list(net_daily)[1:] if x is not None]
    if len(vs) < 2:
        return None
    m = sum(vs) / len(vs)
    var = sum((x - m) ** 2 for x in vs) / (len(vs) - 1)
    if var <= 1e-18:
        return None
    return m, var ** 0.5, len(vs)


def _t_stat(net_daily: Sequence[float]) -> float | None:
    got = _mean_std(net_daily)
    return None if got is None else got[0] / (got[1] / (got[2] ** 0.5))


def _sharpe(net_daily: Sequence[float]) -> float | None:
    got = _mean_std(net_daily)
    return None if got is None else got[0] / got[1] * (252 ** 0.5)


def summarize_basket_trends(
    cells: Sequence[Mapping[str, Any]],
    *,
    job_id: str,
) -> dict[str, Any]:
    """Family/occupancy/sign structure for mechanical baskets. Not a pass."""
    from collections import defaultdict

    by: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for c in cells:
        lid = str(c.get("logic_id") or "")
        if lid:
            by[lid].append(c)
    defs = {d["basket_id"]: d for d in mechanical_basket_defs()}
    rows: list[dict[str, Any]] = []
    for bid, group in sorted(by.items()):
        spec = defs.get(bid) or {}
        occs = [
            c.get("occupancy") if c.get("occupancy") is not None else c.get("occupancy_frac")
            for c in group
        ]
        unions = [c.get("union_occupancy") for c in group]
        nets = [c.get("total_ret_net") for c in group]
        tstats = [c.get("t_stat") for c in group]
        sharpes = [c.get("sharpe_daily") for c in group]
        dds = [c.get("daily_path_DD") for c in group]
        signs = [
            1 if (n or 0) > 1e-6 else (-1 if (n or 0) < -1e-6 else 0) for n in nets
        ]
        n_pos = sum(s > 0 for s in signs)
        n_neg = sum(s < 0 for s in signs)
        m_occ = _mean(occs)
        flags: list[str] = []
        if m_occ is not None and m_occ >= ALWAYS_ON_OCCUPANCY_WARN:
            flags.append("always_on")
        if m_occ is not None and m_occ <= NEAR_EMPTY_OCCUPANCY:
            flags.append("near_empty")
        candidate = not bool(set(flags) & {"always_on", "near_empty"})
        rows.append(
            {
                "basket_id": bid,
                "rule": spec.get("rule") or "mechanical",
                "primary": bool(spec.get("primary")),
                "primary_candidate": bool(spec.get("primary_candidate")),
                "members": list(spec.get("members") or group[0].get("members") or []),
                "n_windows": len(group),
                "mean_member_occupancy": m_occ,
                "mean_union_occupancy": _mean(unions),
                "n_pos_windows": n_pos,
                "n_neg_windows": n_neg,
                "sign_stable": (n_pos >= 4 and n_neg == 0) or (n_neg >= 4 and n_pos == 0),
                "mean_t_stat": _mean(tstats),
                "mean_sharpe_daily": _mean(sharpes),
                "mean_daily_path_DD": _mean(dds),
                "mean_total_ret_net": _mean(nets),
                "window_net_signs": signs,
                "flags": flags,
                "candidate": candidate,
                "explore_only": True,
                "promote_as_main": False,
                "go": False,
            }
        )
    return {
        "version": "basket-trend-summary/v1",
        "job_id": job_id,
        "n_baskets": len(rows),
        "n_cells": len(cells),
        "not_a_pass": True,
        "n_survivors_are_not_a_pass": True,
        "promote_as_main": False,
        "go": False,
        "candidate_eval_sot": PROTOCOL_DAILY_PATH,
        "baskets": rows,
        "retired_rules": sorted(RETIRED_BASKET_RULES),
        "notes": "Mechanical equal-weight basket trends. Descriptive only; never a promote/GO.",
    }


def _mean(xs: Sequence[Any]) -> float | None:
    vs = [float(x) for x in xs if x is not None]
    return (sum(vs) / len(vs)) if vs else None


__all__ = [
    "DEFAULT_CANDIDATE_BASKET",
    "META_BASKETS",
    "RETIRED_BASKET_RULES",
    "RETIRED_META_IDS",
    "blend_net_daily",
    "blend_window_cells",
    "classify_sleeves_three_n",
    "compare_basket_summaries",
    "compare_headn_vs_liq",
    "compare_mid_vs_liq",
    "mechanical_basket_defs",
    "meta_basket_defs",
    "occupancy_in_candidate_band",
    "primary_mechanical_basket_defs",
    "summarize_basket_trends",
    "validate_basket_members",
]
