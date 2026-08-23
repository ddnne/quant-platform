"""Equal-weight mini-combination of candidate-grade daily paths. Not a promote / GO."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from research.combo_basket_catalog import (
    META_BASKETS,
    RETIRED_BASKET_RULES,
    active_reconstitution_plan,
    equal_weights,
    mechanical_basket_defs,
    reconstitution_occupancy_preview,
    usable_sleeve_coverage,
)
from research.candidate_policy import job_candidate_grade
from research.eval_registry import (
    PROTOCOL_DAILY_PATH,
    is_daily_path_complete_cell,
    is_path_broken_cell,
    is_path_collapsed_cell,
)
from research.stats_metrics import equity_path_drawdown, evaluate_daily_path_dd_gate
from research.unique_logic.constants import (
    ALWAYS_ON_OCCUPANCY_WARN,
    NEAR_EMPTY_OCCUPANCY,
    USABLE_OCCUPANCY_MIN,
)
from research.unique_logic.worker_bodies import cell_occupancy


def blend_net_daily(series: Sequence[Sequence[float]]) -> list[float]:
    """Element-wise equal-weight average. Truncates to min length."""
    members = [list(s) for s in series if s]
    if not members:
        return []
    n = min(len(s) for s in members)
    w = 1.0 / float(len(members))
    return [
        sum(float(members[j][i]) for j in range(len(members))) * w for i in range(n)
    ]


def occupancy_in_candidate_band(occ: float | None) -> bool:
    """True for material-band occupancy. Thin (≤0.12) is not candidate blend."""
    if occ is None:
        return False
    return float(USABLE_OCCUPANCY_MIN) < float(occ) < float(ALWAYS_ON_OCCUPANCY_WARN)


def blend_window_cells(
    cells: Sequence[Mapping[str, Any]],
    *,
    basket_id: str,
    logic_ids: Sequence[str],
) -> list[dict[str, Any]]:
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
            occ = cell_occupancy(cell)
            if occ is not None:
                occs.append(occ)
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
                    "candidate_grade": False,
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
                "candidate_grade": job_candidate_grade(
                    n_expected=1,
                    n_cells=1,
                    n_complete=1 if bool(gate.get("complete")) and not missing else 0,
                    n_collapsed=0,
                    n_broken=0,
                )
                and not missing,
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


def primary_sleeve_and_meta_cells(
    cells: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Equal-weight primary sleeves + active metas. Not a pass."""
    sleeve_cells: list[dict[str, Any]] = []
    for d in mechanical_basket_defs():
        if d.get("historical") or not d.get("primary"):
            continue
        sleeve_cells.extend(
            blend_window_cells(
                cells,
                basket_id=str(d["basket_id"]),
                logic_ids=list(d.get("members") or ()),
            )
        )
    meta_cells: list[dict[str, Any]] = []
    for m in META_BASKETS:
        meta_cells.extend(
            blend_window_cells(
                sleeve_cells,
                basket_id=str(m["meta_id"]),
                logic_ids=list(m.get("sleeves") or ()),
            )
        )
    return sleeve_cells + meta_cells


def summarize_basket_trends(
    cells: Sequence[Mapping[str, Any]],
    *,
    job_id: str,
) -> dict[str, Any]:
    by: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for c in cells:
        lid = str(c.get("logic_id") or "")
        if lid:
            by[lid].append(c)
    defs = {d["basket_id"]: d for d in mechanical_basket_defs()}
    rows: list[dict[str, Any]] = []
    for bid, group in sorted(by.items()):
        spec = defs.get(bid) or {}
        occs = [cell_occupancy(c) for c in group]
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
        hist = bool(spec.get("historical") or spec.get("deprecated"))
        n_expected = len(group)
        grade = job_candidate_grade(
            n_expected=n_expected,
            n_cells=n_expected,
            n_complete=sum(1 for c in group if is_daily_path_complete_cell(c)),
            n_collapsed=sum(1 for c in group if is_path_collapsed_cell(c)),
            n_broken=sum(1 for c in group if is_path_broken_cell(c)),
        )
        candidate = bool(grade) and (not hist) and not bool(
            set(flags) & {"always_on", "near_empty"}
        )
        if hist:
            flags.append("historical")
        rows.append(
            {
                "basket_id": bid,
                "rule": spec.get("rule") or "mechanical",
                "primary": bool(spec.get("primary")),
                "primary_candidate": bool(spec.get("primary_candidate")),
                "historical": bool(spec.get("historical")),
                "deprecated": bool(spec.get("deprecated")),
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


def filter_cells_honest_windows(
    cells: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep HONEST 3y windows and their shards. Drops y2015_full. Not a pass."""
    from research.eval_windows import honest_window_ids

    want = honest_window_ids()
    out: list[dict[str, Any]] = []
    for c in cells:
        if not isinstance(c, Mapping):
            continue
        wid = str(c.get("window_id") or c.get("window") or "").strip()
        if wid in want:
            out.append(dict(c))
    return out


def stitch_cells_honest_windows(
    cells: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Concatenate HONEST shards into 3 window_ids. Does not invent missing years.

    Already-stitched cells (window_id in HONEST 3y catalog) win over shard concat.
    Occupancy is length-weighted across present shards. Not a pass.
    """
    from research.eval_windows import HONEST_3Y_WINDOWS

    catalog = {str(w["window_id"]) for w in HONEST_3Y_WINDOWS}
    by_lid: dict[str, dict[str, Mapping[str, Any]]] = {}
    for c in cells:
        if not isinstance(c, Mapping):
            continue
        lid = str(c.get("logic_id") or "").strip()
        wid = str(c.get("window_id") or c.get("window") or "").strip()
        nd = c.get("net_daily")
        if not lid or not wid or not isinstance(nd, list) or len(nd) < 2:
            continue
        by_lid.setdefault(lid, {})[wid] = c
    out: list[dict[str, Any]] = []
    for lid, by_win in by_lid.items():
        for spec in HONEST_3Y_WINDOWS:
            wid = str(spec["window_id"])
            if wid in by_win:
                out.append(dict(by_win[wid]))
                continue
            shards = [
                str(s.get("period_id"))
                for s in (spec.get("shards") or ())
                if isinstance(s, Mapping) and s.get("period_id")
            ]
            present = [by_win[s] for s in shards if s in by_win]
            if not present:
                continue
            nets: list[float] = []
            dates: list[str] = []
            occ_w = 0.0
            occ_n = 0.0
            for cell in present:
                nd = [float(x) for x in (cell.get("net_daily") or [])]
                dd = [str(x) for x in (cell.get("dates") or [])]
                if len(dd) != len(nd):
                    dd = [str(i) for i in range(len(nd))]
                nets.extend(nd)
                dates.extend(dd)
                occ = cell_occupancy(cell)
                n_days = max(1, len(nd) - 1)
                if occ is not None:
                    occ_w += float(occ) * n_days
                    occ_n += n_days
            mean_occ = (occ_w / occ_n) if occ_n else None
            stitched = dict(present[0])
            stitched["logic_id"] = lid
            stitched["window_id"] = wid
            stitched["window"] = wid
            stitched["net_daily"] = nets
            stitched["dates"] = dates
            stitched["occupancy"] = mean_occ
            stitched["occupancy_frac"] = mean_occ
            stitched["n_days"] = len(nets)
            stitched["missing_shards"] = [s for s in shards if s not in by_win]
            stitched["stitched_from"] = [
                str(c.get("window_id") or c.get("window")) for c in present
            ]
            out.append(stitched)
    return out


def blend_option_summary(
    cells: Sequence[Mapping[str, Any]],
    *,
    basket_id: str,
    logic_ids: Sequence[str],
    honest: bool = False,
    stitch: bool = False,
) -> dict[str, Any]:
    """Compact equal-weight blend stats. Drops net_daily. Not a pass."""
    used: Sequence[Mapping[str, Any]]
    if stitch:
        used = stitch_cells_honest_windows(cells)
    elif honest:
        used = filter_cells_honest_windows(cells)
    else:
        used = list(cells)
    rows = blend_window_cells(used, basket_id=basket_id, logic_ids=logic_ids)
    complete = [r for r in rows if r.get("daily_path_complete")]
    missing: set[str] = set()
    for r in rows:
        missing.update(str(x) for x in (r.get("missing_members") or ()) if str(x))
    occs = [r.get("occupancy") for r in complete]
    dds = [r.get("daily_path_DD") for r in complete]
    nets = [r.get("total_ret_net") for r in complete]
    return {
        "basket_id": basket_id,
        "members": list(logic_ids),
        "n_windows": len(rows),
        "n_complete": len(complete),
        "missing_members": sorted(missing),
        "occupancy_mean": _mean(occs),
        "daily_path_DD_min": (min(float(x) for x in dds if x is not None) if any(x is not None for x in dds) else None),
        "total_ret_net_mean": _mean(nets),
        "apply": False,
        "honest_windows": bool(honest or stitch),
        "stitched": bool(stitch),
        "go": False,
        "not_a_pass": True,
    }


__all__ = [
    "blend_net_daily",
    "blend_window_cells",
    "blend_option_summary",
    "filter_cells_honest_windows",
    "stitch_cells_honest_windows",
    "occupancy_in_candidate_band",
    "active_reconstitution_plan",
    "usable_sleeve_coverage",
    "reconstitution_occupancy_preview",
    "primary_sleeve_and_meta_cells",
    "summarize_basket_trends",
]
