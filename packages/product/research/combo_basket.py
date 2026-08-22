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

# Mechanical 2–5 member baskets. No correlation optimization.
MECHANICAL_BASKETS: tuple[dict[str, object], ...] = (
    {
        "basket_id": "basket_head4",
        "rule": "known_candidate_head",
        "members": DEFAULT_CANDIDATE_BASKET,
    },
    {
        "basket_id": "basket_sparse4",
        "rule": "low_occupancy_band",
        "members": (
            "flow_disagree_midmonth",
            "event_friday_easing",
            "curve_steep_midmonth_cs",
            "fy_end_event_fade",
        ),
    },
    {
        "basket_id": "basket_family4",
        "rule": "family_spread",
        "members": (
            "event_tue_thu_easing",
            "surprise_xs_easing_change",
            "cs_easing_midmonth",
            "overnight_down_skip_monday_cs",
        ),
    },
    {
        "basket_id": "basket_midocc4",
        "rule": "mid_occupancy_band",
        "members": (
            "cs_tue_thu_down",
            "rate_up_tue_thu_cs",
            "surprise_xs_afterclose_easing",
            "cs_skip_monday",
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
            }
        )
    return rows


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


def mechanical_basket_defs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in MECHANICAL_BASKETS:
        members = tuple(str(x) for x in (raw.get("members") or ()))
        reasons = validate_basket_members(members)
        out.append(
            {
                "basket_id": str(raw["basket_id"]),
                "rule": str(raw.get("rule") or "mechanical"),
                "members": list(members),
                "weights": equal_weights(len(members)),
                "valid": not reasons,
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
