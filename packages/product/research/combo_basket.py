"""Equal-weight mini-combination of candidate-grade daily paths.

Picks 2–5 occupancy-gated theses and blends their ``net_daily`` series
per window. Not a promote / GO. Schema is the extension point for later
risk-parity weights.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from research.daily_path_eval import git_sha
from research.eval_registry import PROTOCOL_DAILY_PATH, summarize_daily_path_cells
from research.stats_metrics import equity_path_drawdown, evaluate_daily_path_dd_gate
from research.unique_logic.constants import (
    ALWAYS_ON_CS_STICKY,
    ALWAYS_ON_OCCUPANCY_WARN,
    NEAR_EMPTY_OCCUPANCY,
)

BASKET_SCHEMA_VERSION: str = "research-combo-basket/v1"
DEFAULT_CANDIDATE_BASKET: tuple[str, ...] = (
    "event_easing_uncrowded",
    "event_friday_skip",
    "cs_skip_monday",
    "overnight_down_cs_follow",
)

# Lessons (descriptive, never a pass):
# univ50 vs univ80 cross-sleeve (same members, not a single-job call):
# - fundamentals_sleeve / margin_flow_sleeve: 4/2 at both — keep primary_candidate
# - event_fund_cross: 4/2 then 3/3 — keep, mixed not a 2/4 flip
# - known_candidate_head / event_family_only / family_spread: 5/1 or 4/2 at 50,
#   2/4 at 80 — universe-unstable, drop primary_candidate
# - repo_rate_sleeve: 4/2 then 2/4 — redesigned members; demote if still weak
# - surprise_xs_only / two_member_easing / low_occupancy_band — retired
# Candidate occupancy is sleeve mean, not union. No correlation optimization. No GO.
RETIRED_BASKET_RULES: frozenset[str] = frozenset(
    {"low_occupancy_band", "surprise_xs_only", "two_member_easing"}
)
DEPRECATED_MECHANICAL_BASKETS: tuple[dict[str, object], ...] = (
    {
        "basket_id": "basket_sparse4",
        "rule": "low_occupancy_band",
        "deprecated": True,
        "deprecated_reason": (
            "eval-cf-dp-baskets8-20260822a: 1 pos / 5 neg; "
            "unconditional low-occupancy mix is systematically weak"
        ),
        "members": (
            "flow_disagree_midmonth",
            "event_friday_easing",
            "curve_steep_midmonth_cs",
            "fy_end_event_fade",
        ),
    },
    {
        "basket_id": "basket_surprise3",
        "rule": "surprise_xs_only",
        "deprecated": True,
        "deprecated_reason": (
            "eval-cf-dp-baskets50-20260822a: 2 pos / 4 neg; "
            "surprise-only mix is systematically weak"
        ),
        "members": (
            "surprise_xs_easing_change",
            "surprise_xs_afterclose_easing",
            "surprise_xs_skip_monday",
        ),
    },
    {
        "basket_id": "basket_pair_easing",
        "rule": "two_member_easing",
        "deprecated": True,
        "deprecated_reason": (
            "eval-cf-dp-baskets50-20260822a: 3/3, lowest sleeve occupancy; "
            "thin two-member easing pair"
        ),
        "members": (
            "event_easing_midmonth",
            "cs_easing_midmonth",
        ),
    },
)
MECHANICAL_BASKETS: tuple[dict[str, object], ...] = (
    {
        "basket_id": "basket_head4",
        "rule": "known_candidate_head",
        "primary": False,
        "primary_candidate": False,
        "members": DEFAULT_CANDIDATE_BASKET,
    },
    {
        "basket_id": "basket_event4",
        "rule": "event_family_only",
        "primary": False,
        "primary_candidate": False,
        "members": (
            "event_easing_uncrowded",
            "event_friday_skip",
            "event_tue_thu_easing",
            "event_afterclose_easing",
        ),
    },
    {
        "basket_id": "basket_family4",
        "rule": "family_spread",
        "primary": False,
        "primary_candidate": False,
        "members": (
            "event_tue_thu_easing",
            "surprise_xs_easing_change",
            "cs_easing_midmonth",
            "overnight_down_skip_monday_cs",
        ),
    },
    {
        "basket_id": "basket_event_cal4",
        "rule": "event_calendar_only",
        "primary": False,
        "primary_candidate": False,
        "members": (
            "event_skip_monday",
            "event_friday_skip",
            "event_tue_thu_only",
            "event_first_half_month",
        ),
    },
    {
        "basket_id": "basket_midocc4",
        "rule": "mid_occupancy_band",
        "primary": False,
        "members": (
            "cs_tue_thu_down",
            "rate_up_tue_thu_cs",
            "surprise_xs_afterclose_easing",
            "cs_skip_monday",
        ),
    },
    {
        "basket_id": "basket_cs4",
        "rule": "cs_family_only",
        "primary": False,
        "members": (
            "cs_skip_monday",
            "cs_easing_midmonth",
            "overnight_down_cs_follow",
            "cs_tue_thu_down",
        ),
    },
    {
        "basket_id": "basket_theme_fund",
        "rule": "fundamentals_sleeve",
        "primary": True,
        "primary_candidate": True,
        "members": (
            "event_eqar_high_liq_high",
            "event_eqar_high_pead",
            "event_ta_up_liq_high",
            "cs_eqar_high_margin_down",
        ),
    },
    {
        "basket_id": "basket_theme_flow",
        "rule": "margin_flow_sleeve",
        "primary": True,
        "primary_candidate": True,
        "members": (
            "cs_margin_up_chase",
            "event_margin_down_liq_high",
            "event_margin_delta_fade",
        ),
    },
    {
        "basket_id": "basket_theme_repo",
        "rule": "repo_rate_sleeve",
        "primary": False,
        "primary_candidate": False,
        "members": (
            "event_repo3m_down_pead",
            "event_overnight_p10_pead",
            "cs_repo3m_down_easy",
            "event_eqar_high_repo3m_down",
        ),
    },
    {
        "basket_id": "basket_event_fund",
        "rule": "event_fund_cross",
        "primary": True,
        "primary_candidate": True,
        "members": (
            "event_eqar_high_liq_high",
            "event_positive_eps_liq_high",
            "event_cheap_pb_liq_high",
        ),
    },
)


def validate_basket_members(logic_ids: Sequence[str]) -> list[str]:
    ids = [str(x).strip() for x in logic_ids if str(x).strip()]
    reasons: list[str] = []
    if len(ids) < 2:
        reasons.append("need_at_least_2_members")
    if len(ids) > 5:
        reasons.append("need_at_most_5_members")
    if len(set(ids)) != len(ids):
        reasons.append("duplicate_members")
    return reasons


def equal_weights(n: int) -> list[float]:
    if n <= 0:
        return []
    w = 1.0 / float(n)
    return [w] * int(n)


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


def _occupancy_ok(occ: float | None) -> bool:
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


def _t_stat(net_daily: Sequence[float]) -> float | None:
    vs = [float(x) for x in list(net_daily)[1:] if x is not None]
    if len(vs) < 2:
        return None
    m = sum(vs) / len(vs)
    var = sum((x - m) ** 2 for x in vs) / (len(vs) - 1)
    if var <= 1e-18:
        return None
    return m / ((var ** 0.5) / (len(vs) ** 0.5))


def _sharpe(net_daily: Sequence[float]) -> float | None:
    vs = [float(x) for x in list(net_daily)[1:] if x is not None]
    if len(vs) < 2:
        return None
    m = sum(vs) / len(vs)
    var = sum((x - m) ** 2 for x in vs) / (len(vs) - 1)
    if var <= 1e-18:
        return None
    return m / (var ** 0.5) * (252 ** 0.5)


def run_combo_basket_job(
    *,
    job_id: str,
    logic_ids: Sequence[str] | None = None,
    panels_prefix: str | None = None,
    member_job_id: str | None = None,
) -> dict[str, Any]:
    """Fan-out member daily_paths (or reuse cells) and record a blended basket."""
    from pathlib import Path

    from qp_paths import repo_root
    from research.cf_daily_path_job import run_cf_daily_path_fanout

    ids = list(logic_ids or DEFAULT_CANDIDATE_BASKET)
    reasons = validate_basket_members(ids)
    if reasons:
        raise ValueError(",".join(reasons))
    basket_id = "basket_" + "_".join(ids[:2])
    pack = run_cf_daily_path_fanout(
        job_id=member_job_id or f"{job_id}__members",
        logic_ids=ids,
        panels_prefix=panels_prefix,
    )
    cells = list(pack.get("cells") or [])
    if not cells and pack.get("table_path"):
        from pathlib import Path as P

        tp = P(str(pack["table_path"]))
        if tp.is_file():
            cells = json.loads(tp.read_text(encoding="utf-8"))
    blended = blend_window_cells(cells, basket_id=basket_id, logic_ids=ids)
    summary = summarize_daily_path_cells(blended, job_id=job_id)
    out_dir = repo_root() / "data" / "ops" / "research_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    table_path = out_dir / f"{job_id}_cells.json"
    table_path.write_text(json.dumps(blended, indent=2, default=str) + "\n")
    return {
        "version": BASKET_SCHEMA_VERSION,
        "job_id": job_id,
        "protocol": PROTOCOL_DAILY_PATH,
        "basket_id": basket_id,
        "members": ids,
        "weights": equal_weights(len(ids)),
        "n_member_cells": len(cells),
        "n_basket_cells": len(blended),
        "member_fanout": {
            "job_id": pack.get("job_id"),
            "n_cells": pack.get("n_cells"),
            "n_daily_path_complete": pack.get("n_daily_path_complete"),
            "n_errors": pack.get("n_errors"),
        },
        "table_path": str(table_path),
        "summary": {
            "n_candidate_logics": summary.get("n_candidate_logics"),
            "n_always_on": summary.get("n_always_on"),
            "n_near_empty": summary.get("n_near_empty"),
        },
        "git_sha": git_sha(cwd=repo_root()),
        "promote_as_main": False,
        "go": False,
        "notes": (
            "Equal-weight blend of candidate-grade daily net_daily series. "
            "Not a promotion. Occupancy of the blend is days with non-zero "
            "blended net, not a member always_on."
        ),
    }


def occupancy_in_candidate_band(occ: float | None) -> bool:
    return _occupancy_ok(occ)


def primary_mechanical_basket_defs() -> list[dict[str, Any]]:
    """Primary / primary_candidate mechanical rules. Retired stay out. Not GO."""
    return [
        d
        for d in mechanical_basket_defs()
        if d.get("valid") and (d.get("primary") or d.get("primary_candidate"))
    ]


def blend_primary_baskets(
    cells: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in primary_mechanical_basket_defs():
        rows.extend(
            blend_window_cells(
                cells,
                basket_id=spec["basket_id"],
                logic_ids=spec["members"],
            )
        )
    return rows


def mechanical_basket_defs(*, include_deprecated: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    src: tuple[dict[str, object], ...] = MECHANICAL_BASKETS
    if include_deprecated:
        src = MECHANICAL_BASKETS + DEPRECATED_MECHANICAL_BASKETS
    for raw in src:
        rule = str(raw.get("rule") or "mechanical")
        deprecated = bool(raw.get("deprecated")) or rule in RETIRED_BASKET_RULES
        if deprecated and not include_deprecated:
            continue
        members = tuple(str(x) for x in (raw.get("members") or ()))
        reasons = validate_basket_members(members)
        if any(m in ALWAYS_ON_CS_STICKY for m in members):
            reasons.append("always_on_cs_member")
        pc = bool(raw.get("primary_candidate")) and not deprecated
        prim = bool(raw.get("primary")) and not deprecated
        out.append(
            {
                "basket_id": str(raw["basket_id"]),
                "rule": rule,
                "primary": prim,
                "primary_candidate": pc or prim,
                "deprecated": deprecated,
                "deprecated_reason": raw.get("deprecated_reason"),
                "members": list(members),
                "weights": equal_weights(len(members)),
                "valid": not reasons and not deprecated,
                "reject": reasons,
                "promote_as_main": False,
                "go": False,
            }
        )
    return out


def blend_mechanical_baskets(
    cells: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Blend every mechanical basket from a shared member-cell pool."""
    rows: list[dict[str, Any]] = []
    for spec in mechanical_basket_defs():
        if not spec["valid"]:
            continue
        rows.extend(
            blend_window_cells(
                cells,
                basket_id=spec["basket_id"],
                logic_ids=spec["members"],
            )
        )
    return rows


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
        "notes": (
            "Mechanical equal-weight basket trends for later fund design. "
            "t/Sharpe/DD are descriptive only and never a promote/GO. "
            "low_occupancy_band retired after baskets8 (systematically weak). "
            "Candidate occupancy is sleeve mean, not union."
        ),
    }


def _mean(xs: Sequence[Any]) -> float | None:
    vs = [float(x) for x in xs if x is not None]
    return (sum(vs) / len(vs)) if vs else None


# Equal-weight blends of mechanical sleeves. Not GO. No correlation weights.
# univ100 summary_meta: event4/head metas 2/4 or contaminate flipped sleeves — retired.
# Keep fund+flow / fund+event. Secondary: flow+event, three-sleeve.
META_BASKETS: tuple[dict[str, object], ...] = (
    {
        "meta_id": "meta_fund_flow",
        "sleeves": ("basket_theme_fund", "basket_theme_flow"),
    },
    {
        "meta_id": "meta_fund_event",
        "sleeves": ("basket_theme_fund", "basket_event_fund"),
    },
    {
        "meta_id": "meta_fund_flow_event",
        "sleeves": (
            "basket_theme_fund",
            "basket_theme_flow",
            "basket_event_fund",
        ),
    },
)
META_SECONDARY: tuple[dict[str, object], ...] = (
    {
        "meta_id": "meta_flow_event",
        "sleeves": ("basket_theme_flow", "basket_event_fund"),
        "secondary": True,
    },
)
DEPRECATED_META_BASKETS: tuple[dict[str, object], ...] = (
    {
        "meta_id": "meta_event4_flow",
        "sleeves": ("basket_event4", "basket_theme_flow"),
        "deprecated": True,
        "deprecated_reason": "eval-cf-dp-baskets100: 2 pos / 4 neg; uses demoted event4",
    },
    {
        "meta_id": "meta_event4_fund",
        "sleeves": ("basket_event4", "basket_theme_fund"),
        "deprecated": True,
        "deprecated_reason": "eval-cf-dp-baskets100: uses demoted event4 sleeve",
    },
    {
        "meta_id": "meta_head_fund",
        "sleeves": ("basket_head4", "basket_theme_fund"),
        "deprecated": True,
        "deprecated_reason": "eval-cf-dp-baskets100: uses universe-unstable head4",
    },
)
RETIRED_META_IDS: frozenset[str] = frozenset(
    str(d["meta_id"]) for d in DEPRECATED_META_BASKETS
)


def meta_basket_defs(*, include_secondary: bool = False, include_deprecated: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    known = {d["basket_id"] for d in mechanical_basket_defs()}
    src: tuple[dict[str, object], ...] = META_BASKETS
    if include_secondary:
        src = META_BASKETS + META_SECONDARY
    if include_deprecated:
        src = src + DEPRECATED_META_BASKETS
    for raw in src:
        sleeves = tuple(str(x) for x in (raw.get("sleeves") or ()))
        reasons = []
        if not (2 <= len(sleeves) <= 3):
            reasons.append("need_2_or_3_sleeves")
        if len(set(sleeves)) != len(sleeves):
            reasons.append("duplicate_sleeves")
        missing = [s for s in sleeves if s not in known]
        if missing:
            reasons.append("unknown_sleeve")
        deprecated = bool(raw.get("deprecated")) or str(raw.get("meta_id")) in RETIRED_META_IDS
        if deprecated and not include_deprecated:
            continue
        out.append(
            {
                "meta_id": str(raw["meta_id"]),
                "sleeves": list(sleeves),
                "weights": equal_weights(len(sleeves)),
                "valid": not reasons and not deprecated,
                "reject": reasons,
                "secondary": bool(raw.get("secondary")),
                "deprecated": deprecated,
                "deprecated_reason": raw.get("deprecated_reason"),
                "promote_as_main": False,
                "go": False,
                "not_a_pass": True,
            }
        )
    return out


def blend_meta_baskets(sleeve_cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Equal-weight blend of sleeve basket net_daily series. Not a pass."""
    rows: list[dict[str, Any]] = []
    for spec in meta_basket_defs():
        if not spec["valid"]:
            continue
        rows.extend(
            blend_window_cells(
                sleeve_cells,
                basket_id=spec["meta_id"],
                logic_ids=spec["sleeves"],
            )
        )
    return rows


def compare_basket_summaries(
    summary_a: Mapping[str, Any],
    summary_b: Mapping[str, Any],
    *,
    label_a: str,
    label_b: str,
) -> dict[str, Any]:
    """Classify sleeves as stable / flipped / mixed. Scores stay off Git."""
    by_a = {
        str(r.get("basket_id")): r
        for r in (summary_a.get("baskets") or [])
        if r.get("basket_id")
    }
    by_b = {
        str(r.get("basket_id")): r
        for r in (summary_b.get("baskets") or [])
        if r.get("basket_id")
    }
    rows: list[dict[str, Any]] = []
    for bid in sorted(set(by_a) | set(by_b)):
        a = by_a.get(bid) or {}
        b = by_b.get(bid) or {}
        pa, na = int(a.get("n_pos_windows") or 0), int(a.get("n_neg_windows") or 0)
        pb, nb = int(b.get("n_pos_windows") or 0), int(b.get("n_neg_windows") or 0)
        maj_a = 1 if pa > na else (-1 if na > pa else 0)
        maj_b = 1 if pb > nb else (-1 if nb > pb else 0)
        if maj_a == 0 or maj_b == 0:
            kind = "mixed"
        elif maj_a != maj_b:
            kind = "flipped"
        else:
            kind = "stable_majority"
        rows.append(
            {
                "basket_id": bid,
                "rule": a.get("rule") or b.get("rule"),
                "class": kind,
                label_a: {"n_pos": pa, "n_neg": na},
                label_b: {"n_pos": pb, "n_neg": nb},
                "primary_candidate_now": bool(
                    (b.get("primary_candidate") if b else a.get("primary_candidate"))
                ),
            }
        )
    stable = [r["basket_id"] for r in rows if r["class"] == "stable_majority"]
    flipped = [r["basket_id"] for r in rows if r["class"] == "flipped"]
    mixed = [r["basket_id"] for r in rows if r["class"] == "mixed"]
    return {
        "version": "sleeve-universe-stability/v1",
        "label_a": label_a,
        "label_b": label_b,
        "stable_majority": stable,
        "flipped": flipped,
        "mixed": mixed,
        "preferred_materials": [
            "basket_theme_fund",
            "basket_theme_flow",
        ],
        "sleeves": rows,
        "promote_as_main": False,
        "go": False,
        "not_a_pass": True,
        "notes": (
            "Single-universe 4/2 is not a stability call. "
            "theme_fund / theme_flow kept 4/2 on both univ50 and univ80."
        ),
    }


def classify_sleeves_three_n(
    summary_50: Mapping[str, Any],
    summary_80: Mapping[str, Any],
    summary_100: Mapping[str, Any],
) -> dict[str, Any]:
    """stable_mid / dilutes_at_large / unstable. A 100-only print is not stable."""

    def _rows(summary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(r.get("basket_id")): r
            for r in (summary.get("baskets") or [])
            if r.get("basket_id")
        }

    def _maj(row: Mapping[str, Any] | None) -> int:
        if not row:
            return 0
        p, n = int(row.get("n_pos_windows") or 0), int(row.get("n_neg_windows") or 0)
        if p > n:
            return 1
        if n > p:
            return -1
        return 0

    a, b, c = _rows(summary_50), _rows(summary_80), _rows(summary_100)
    ids = sorted(set(a) | set(b) | set(c))
    sleeves: list[dict[str, Any]] = []
    stable_mid: list[str] = []
    dilutes: list[str] = []
    unstable: list[str] = []
    for bid in ids:
        m50, m80, m100 = _maj(a.get(bid)), _maj(b.get(bid)), _maj(c.get(bid))
        # Mid-N agreement with a positive majority, then 100 goes mixed/flip.
        mid_ok = m50 == m80 == 1
        large_dilute = mid_ok and m100 != 1
        flipped = (m50 != 0 and m80 != 0 and m50 != m80) or (
            m50 == 1 and m80 == -1
        )
        if flipped or (m50 == 1 and m80 == 1 and m100 == -1):
            kind = "unstable"
            unstable.append(bid)
        elif large_dilute:
            kind = "dilutes_at_large"
            dilutes.append(bid)
            if mid_ok:
                stable_mid.append(bid)
        elif mid_ok and m100 == 1:
            kind = "stable_mid"
            stable_mid.append(bid)
        else:
            kind = "unstable" if (m50 != 0 and m80 != 0 and m50 != m80) else "mixed"
            if kind == "unstable":
                unstable.append(bid)
        sleeves.append(
            {
                "basket_id": bid,
                "class": kind,
                "univ50_maj": m50,
                "univ80_maj": m80,
                "univ100_maj": m100,
                "univ50": {
                    "n_pos": int((a.get(bid) or {}).get("n_pos_windows") or 0),
                    "n_neg": int((a.get(bid) or {}).get("n_neg_windows") or 0),
                },
                "univ80": {
                    "n_pos": int((b.get(bid) or {}).get("n_pos_windows") or 0),
                    "n_neg": int((b.get(bid) or {}).get("n_neg_windows") or 0),
                },
                "univ100": {
                    "n_pos": int((c.get(bid) or {}).get("n_pos_windows") or 0),
                    "n_neg": int((c.get(bid) or {}).get("n_neg_windows") or 0),
                },
            }
        )
    return {
        "version": "sleeve-universe-stability/v2",
        "stable_mid": stable_mid,
        "dilutes_at_large": dilutes,
        "unstable": unstable,
        "preferred_materials": ["basket_theme_fund", "basket_theme_flow"],
        "sleeves": sleeves,
        "univ100_is_not_stable": True,
        "promote_as_main": False,
        "go": False,
        "not_a_pass": True,
        "notes": (
            "theme_fund/flow are stable_mid (4/2 at 50 and 80) and "
            "dilute_at_large (3/3 at 100). A 100-only print is never stable."
        ),
        "primary_candidate_notes": {
            "basket_theme_fund": (
                "keep primary_candidate: relatively better at mid-N; "
                "dilutes at 100; not a pass / not GO"
            ),
            "basket_theme_flow": (
                "keep primary_candidate: relatively better at mid-N; "
                "dilutes at 100; not a pass / not GO"
            ),
            "basket_event_fund": (
                "keep primary_candidate as fund-cross material; mixed at "
                "80/100; not a pass / not GO"
            ),
        },
        "primary_candidate_is_not_a_pass": True,
    }


COMPARE_COMPOSITION_IDS: tuple[str, ...] = (
    "basket_theme_fund",
    "basket_theme_flow",
    "basket_event_fund",
    "meta_fund_flow",
    "meta_fund_event",
    "meta_fund_flow_event",
)


def _index_composition(summary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in list(summary.get("baskets") or []) + list(summary.get("metas") or []):
        if not isinstance(r, Mapping):
            continue
        bid = str(r.get("basket_id") or r.get("meta_id") or "")
        if bid:
            out[bid] = dict(r)
    return out


def _majority_sign(n_pos: int, n_neg: int) -> int:
    if n_pos > n_neg:
        return 1
    if n_neg > n_pos:
        return -1
    return 0


def _compare_composition_rows(
    summary_a: Mapping[str, Any],
    summary_b: Mapping[str, Any],
    *,
    ids: Sequence[str],
    label_a: str,
    label_b: str,
    a_better_class: str,
    b_better_class: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    a = _index_composition(summary_a)
    b = _index_composition(summary_b)
    rows: list[dict[str, Any]] = []
    b_majority_better: list[str] = []
    for bid in ids:
        ha, hb = a.get(bid) or {}, b.get(bid) or {}
        pa, na = int(ha.get("n_pos_windows") or 0), int(ha.get("n_neg_windows") or 0)
        pb, nb = int(hb.get("n_pos_windows") or 0), int(hb.get("n_neg_windows") or 0)
        maj_a = _majority_sign(pa, na)
        maj_b = _majority_sign(pb, nb)
        if maj_a == 0 and maj_b == 0:
            kind = "both_mixed"
        elif maj_a == maj_b:
            kind = "same_majority"
        elif maj_b == 1 and maj_a != 1:
            kind = b_better_class
            b_majority_better.append(bid)
        elif maj_a == 1 and maj_b != 1:
            kind = a_better_class
        else:
            kind = "diverged"
        rows.append(
            {
                "id": bid,
                "class": kind,
                label_a: {"n_pos": pa, "n_neg": na, "maj": maj_a},
                label_b: {"n_pos": pb, "n_neg": nb, "maj": maj_b},
            }
        )
    return rows, b_majority_better


def compare_headn_vs_liq(
    summary_headn: Mapping[str, Any],
    summary_liq: Mapping[str, Any],
    *,
    ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Same sleeves/metas across head-N 100 vs ADV liq100. Not a pass."""
    want = tuple(ids) if ids is not None else COMPARE_COMPOSITION_IDS
    rows, liq_majority_better = _compare_composition_rows(
        summary_headn,
        summary_liq,
        ids=want,
        label_a="head_n",
        label_b="liq",
        a_better_class="headn_majority_better",
        b_better_class="liq_majority_better",
    )
    return {
        "version": "composition-compare/v1",
        "head_n_job": summary_headn.get("job_id"),
        "liq_job": summary_liq.get("job_id"),
        "ids": list(want),
        "liq_majority_better": liq_majority_better,
        "rows": rows,
        "liq_print_is_not_stable": True,
        "not_a_pass": True,
        "go": False,
        "promote_as_main": False,
        "notes": (
            "ADV composition vs head-N on the same sleeve/meta set. "
            "A liq 4/2 (or 5/1) is not a stability or pass call."
        ),
    }


def compare_mid_vs_liq(
    summary_mid: Mapping[str, Any],
    summary_liq: Mapping[str, Any],
    *,
    ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Same sleeves/metas across mid_n_explore vs ADV liq_large. Not a pass."""
    want = tuple(ids) if ids is not None else COMPARE_COMPOSITION_IDS
    rows, liq_majority_better = _compare_composition_rows(
        summary_mid,
        summary_liq,
        ids=want,
        label_a="mid_n",
        label_b="liq",
        a_better_class="mid_majority_better",
        b_better_class="liq_majority_better",
    )
    return {
        "version": "composition-compare/v2",
        "mid_n_job": summary_mid.get("job_id"),
        "liq_job": summary_liq.get("job_id"),
        "ids": list(want),
        "liq_majority_better": liq_majority_better,
        "rows": rows,
        "liq_print_is_not_stable": True,
        "not_a_pass": True,
        "go": False,
        "promote_as_main": False,
        "notes": (
            "ADV mid_n_explore vs liq_large on the same sleeve/meta set "
            "(refreshed ADV sleeve members). A liq 4/2 or 5/1 is not a "
            "stability or pass call."
        ),
    }


def summarize_meta_trends(
    cells: Sequence[Mapping[str, Any]],
    *,
    job_id: str,
) -> dict[str, Any]:
    """Active meta-basket trend. Not a pass. Retired metas stay out."""
    pack = summarize_basket_trends(cells, job_id=job_id)
    pack["version"] = "meta-basket-trend-summary/v1"
    pack["not_a_pass"] = True
    pack["retired_meta_ids"] = sorted(RETIRED_META_IDS)
    pack["active_meta_ids"] = [d["meta_id"] for d in meta_basket_defs()]
    pack["secondary_meta_ids"] = [d["meta_id"] for d in META_SECONDARY]
    pack["notes"] = (
        "Fund+flow / fund+event / fund+flow+event stay on the active line. "
        "event4/head metas retired. flow+event is secondary. Not a pass."
    )
    return pack
