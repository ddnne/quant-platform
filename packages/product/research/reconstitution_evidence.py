"""Comparison artifact for human reconstitution. Does not apply. Not GO.

Emits both drop_parents and drop_children cuts for the two pending KEEP
24df sleeves. Does not flip RECONSTITUTION_APPLY. Does not mutate members.
Does not invent Sharpe. Live R2 put is refused; dry_run stages only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from research.eval_flags import (
    CATALOG_AND_PLUS_N_STOPPED,
    CURRENT_EVAL_WAVE,
    EVENT_THREE_AND_PLUS_N_STOPPED,
    RECONSTITUTION_APPLY,
)

EVIDENCE_VERSION: str = "reconstitution-evidence/v1"
DEFAULT_RECOMMENDED_CHOICE: str = "drop_children_keep_parents"
DEFAULT_RECOMMENDED_REASON: str = (
    "prefer simple 2-condition hypotheses; avoid 3-AND overfit; "
    "keep occupancy/breadth; do not shrink event fund to 2"
)
# Event-fund drop_parents is 5→2; that cut is not "clearly better" on breadth.
MIN_SLEEVE_BREADTH_FOR_CLEAR_BETTER: int = 4
COMPARISON_METRIC_KEYS: tuple[str, ...] = (
    "net_return",
    "net_sharpe",
    "max_dd",
    "turnover",
    "cost",
    "occupancy",
    "parent_child_correlation",
    "incremental_contribution",
    "residual_alpha",
    "regime_stability",
    "mid_n_explore",
    "liq_large",
)
OPTION_KEYS: tuple[str, ...] = (
    "drop_parents_keep_children",
    "drop_children_keep_parents",
)


def empty_metric_slots() -> dict[str, Any]:
    """All comparison metrics as None. Callers fill only observed values."""
    return {k: None for k in COMPARISON_METRIC_KEYS}


def _round4(raw: float | None) -> float | None:
    if raw is None:
        return None
    return round(float(raw), 4)


def _mean(values: Sequence[Any]) -> float | None:
    nums = [float(x) for x in values if x is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _n_ands(logic_id: str) -> int:
    from research.combo_basket_catalog import _spec_gates

    return len(_spec_gates(logic_id))


def _has_net_daily(cells_by_track: Mapping[str, Sequence[Mapping[str, Any]]]) -> bool:
    for cells in cells_by_track.values():
        for cell in cells or ():
            if not isinstance(cell, Mapping):
                continue
            nd = cell.get("net_daily")
            if isinstance(nd, list) and len(nd) >= 2:
                return True
    return False


def _keep_cell_names(job: str) -> dict[str, str]:
    return {
        "mid_n_explore": f"{job}-mid_n_explore_cells.json",
        "liq_large": f"{job}-liq_large_cells.json",
    }


def load_keep_job_cells(root: str | Path, *, job: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Load KEEP 24df daily-path cells if those two files exist. Not a pass."""
    from research.combo_basket_catalog import KEEP_BOTH_SLEEVES_JOB

    job_id = job or KEEP_BOTH_SLEEVES_JOB
    base = Path(root)
    out: dict[str, list[dict[str, Any]]] = {"mid_n_explore": [], "liq_large": []}
    for track, name in _keep_cell_names(job_id).items():
        path = base / name
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, list):
            continue
        out[track] = [c for c in raw if isinstance(c, dict)]
    return out


def _occ_fill(summary: Mapping[str, Any]) -> dict[str, float | None]:
    lo = summary.get("lo")
    occupancy = None
    if isinstance(lo, Mapping) and lo.get("mean") is not None:
        occupancy = _round4(float(lo["mean"]))
    rows = [r for r in (summary.get("by_id") or []) if isinstance(r, Mapping)]
    mid = _round4(_mean([r.get("mid_n_explore") for r in rows]))
    liq = _round4(_mean([r.get("liq_large") for r in rows]))
    return {"occupancy": occupancy, "mid_n_explore": mid, "liq_large": liq}


def _metrics_from_cells(
    cells: Sequence[Mapping[str, Any]],
    *,
    basket_id: str,
    members: Sequence[str],
) -> dict[str, Any]:
    """Honest blend stats from net_daily cells. Missing → None. Not a pass."""
    slots = empty_metric_slots()
    if not cells:
        return slots
    from research.combo_basket import blend_window_cells

    rows = blend_window_cells(cells, basket_id=basket_id, logic_ids=list(members))
    usable = [r for r in rows if r.get("net_daily")]
    if not usable:
        return slots
    dds = [r.get("daily_path_DD") for r in usable if r.get("daily_path_DD") is not None]
    slots["net_return"] = _round4(_mean([r.get("total_ret_net") for r in usable]))
    slots["net_sharpe"] = _round4(_mean([r.get("sharpe_daily") for r in usable]))
    slots["max_dd"] = _round4(min(float(x) for x in dds) if dds else None)
    slots["occupancy"] = _round4(_mean([r.get("occupancy") for r in usable]))
    return slots


def _economics_clearly_better(
    drop_parents: Mapping[str, Any],
    drop_children: Mapping[str, Any],
) -> bool:
    """True only with complete economics and no breadth shrink below 4.

    Occupancy-only / missing Sharpe is not clearly better. Not apply.
    """
    if int(drop_parents.get("sleeve_breadth") or 0) < MIN_SLEEVE_BREADTH_FOR_CLEAR_BETTER:
        return False
    pm = dict(drop_parents.get("metrics") or {})
    cm = dict(drop_children.get("metrics") or {})
    p_sh, c_sh = pm.get("net_sharpe"), cm.get("net_sharpe")
    p_ret, c_ret = pm.get("net_return"), cm.get("net_return")
    p_dd, c_dd = pm.get("max_dd"), cm.get("max_dd")
    if None in (p_sh, c_sh, p_ret, c_ret, p_dd, c_dd):
        return False
    return float(p_sh) > float(c_sh) and float(p_ret) > float(c_ret) and float(p_dd) >= float(c_dd)


def _option_row(
    *,
    basket_id: str,
    raw: Mapping[str, Any],
    nested: Sequence[Mapping[str, Any]],
    cells_by_track: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    members = [str(x) for x in (raw.get("members") or ())]
    dropped = [str(x) for x in (raw.get("dropped") or ())]
    metrics = empty_metric_slots()
    metrics.update(_occ_fill(raw))
    by_track: dict[str, dict[str, Any]] = {}
    for track, cells in cells_by_track.items():
        filled = _metrics_from_cells(cells, basket_id=basket_id, members=members)
        by_track[track] = filled
        if filled.get("net_sharpe") is not None and metrics.get("net_sharpe") is None:
            # Single-track fill only; do not average mid vs liq into a Sharpe.
            if sum(1 for t, c in cells_by_track.items() if _has_net_daily({t: c})) == 1:
                for key in COMPARISON_METRIC_KEYS:
                    if key in ("occupancy", "mid_n_explore", "liq_large"):
                        continue
                    if filled.get(key) is not None:
                        metrics[key] = filled[key]
    return {
        "members": members,
        "dropped": list(dropped),
        "n": len(members),
        "sleeve_breadth": len(members),
        "nested_parent_count": raw.get("nested_parent_count"),
        "n_ands": {lid: _n_ands(lid) for lid in members},
        "nested_parents": [
            {"parent": p.get("parent"), "child": p.get("child")}
            for p in nested
            if str(p.get("parent")) in set(members) and str(p.get("child")) in set(members)
        ],
        "metrics": metrics,
        "by_track": by_track,
        "occupancy_mean_not_a_blend": True,
        "apply": bool(RECONSTITUTION_APPLY),
        "go": False,
        "not_a_pass": True,
    }


def reconstitution_evidence_pack(
    occupancy_by_track: Mapping[str, Mapping[str, float]] | None = None,
    *,
    cells_root: str | Path | None = None,
    cells_by_track: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """drop_parents vs drop_children comparison artifact. Does not apply.

    Default recommended_choice is drop_children_keep_parents when economics
    are not clearly better. Missing live cells → local_schema_only / r2_missing
    with Sharpe left None.
    """
    from research.combo_basket_catalog import (
        FLOW_FIFTH_BLEND_THINNER_JOB,
        HUMAN_RECONSTITUTION_PENDING,
        KEEP_BOTH_SLEEVES_JOB,
        reconstitution_occupancy_preview,
        reconstitution_plan,
    )

    preview = reconstitution_occupancy_preview(occupancy_by_track)
    plan = {p["basket_id"]: p for p in reconstitution_plan()}
    loaded: dict[str, list[dict[str, Any]]] = {"mid_n_explore": [], "liq_large": []}
    if cells_by_track is not None:
        loaded = {
            "mid_n_explore": [dict(c) for c in (cells_by_track.get("mid_n_explore") or [])],
            "liq_large": [dict(c) for c in (cells_by_track.get("liq_large") or [])],
        }
        evidence_status = "cells_present" if _has_net_daily(loaded) else "r2_missing"
    elif cells_root is not None:
        loaded = load_keep_job_cells(cells_root, job=KEEP_BOTH_SLEEVES_JOB)
        evidence_status = "cells_present" if _has_net_daily(loaded) else "r2_missing"
    else:
        evidence_status = "local_schema_only"

    pending = list(HUMAN_RECONSTITUTION_PENDING)
    sleeves: list[dict[str, Any]] = []
    by_preview = {s["basket_id"]: s for s in (preview.get("sleeves") or [])}
    all_clear = True
    for bid in pending:
        prev = by_preview.get(bid) or {}
        row_plan = plan.get(bid) or {}
        nested = list(row_plan.get("nested_parents") or prev.get("nested_parents") or [])
        current_members = [str(x) for x in ((prev.get("current") or {}).get("members") or ())]
        drop_p = _option_row(
            basket_id=bid,
            raw=prev.get("drop_parents_keep_children") or row_plan.get("drop_parents_keep_children") or {},
            nested=nested,
            cells_by_track=loaded,
        )
        drop_c = _option_row(
            basket_id=bid,
            raw=prev.get("drop_children_keep_parents") or row_plan.get("drop_children_keep_parents") or {},
            nested=nested,
            cells_by_track=loaded,
        )
        current_metrics = empty_metric_slots()
        current_metrics.update(_occ_fill(prev.get("current") or {}))
        clear = _economics_clearly_better(drop_p, drop_c)
        all_clear = all_clear and clear
        sleeves.append(
            {
                "basket_id": bid,
                "primary": prev.get("primary", True),
                "needs_reconstitution": bool(prev.get("needs_reconstitution", True)),
                "nested_parent_count": int(prev.get("nested_parent_count") or len(nested) or 0),
                "nested_parents": [
                    {"parent": p.get("parent"), "child": p.get("child")}
                    for p in nested
                ],
                "current": {
                    "members": current_members,
                    "n": len(current_members),
                    "sleeve_breadth": len(current_members),
                    "n_ands": {lid: _n_ands(lid) for lid in current_members},
                    "metrics": current_metrics,
                    "occupancy_mean_not_a_blend": True,
                },
                "drop_parents_keep_children": drop_p,
                "drop_children_keep_parents": drop_c,
                "economics_clearly_better": clear,
                "apply": bool(RECONSTITUTION_APPLY),
                "go": False,
                "not_a_pass": True,
            }
        )

    economics_clearly_better = bool(sleeves) and all_clear
    recommended = (
        "drop_parents_keep_children"
        if economics_clearly_better
        else DEFAULT_RECOMMENDED_CHOICE
    )
    return {
        "version": EVIDENCE_VERSION,
        "keep_sleeves_job": KEEP_BOTH_SLEEVES_JOB,
        "flow_fifth_blend_thinner_job": FLOW_FIFTH_BLEND_THINNER_JOB,
        "human_pending": pending,
        "options": list(OPTION_KEYS),
        "metric_keys": list(COMPARISON_METRIC_KEYS),
        "evidence_status": evidence_status,
        "recommended_choice": recommended,
        "recommended_choice_is_not_apply": True,
        "reason": DEFAULT_RECOMMENDED_REASON,
        "economics_clearly_better": economics_clearly_better,
        "do_not_auto_choose": True,
        "human_only_drop_parents_vs_drop_children": True,
        "human_choice_required": True,
        "do_not_restitch_blend": True,
        "do_not_invent_sharpe": True,
        "multiple_testing_context": {
            "n_sleeves": len(pending),
            "n_cuts_per_sleeve": len(OPTION_KEYS),
            "nested_pairs_are_not_independent": True,
            "catalog_and_plus_n_stopped": bool(CATALOG_AND_PLUS_N_STOPPED),
            "event_three_and_plus_n_stopped": bool(EVENT_THREE_AND_PLUS_N_STOPPED),
            "occupancy_mean_is_not_a_score": True,
            "do_not_pick_cut_from_preview": True,
        },
        "sleeves": sleeves,
        "apply": bool(RECONSTITUTION_APPLY),
        "go": False,
        "not_a_pass": True,
    }


def write_reconstitution_evidence_pack(
    occupancy_by_track: Mapping[str, Mapping[str, float]] | None = None,
    *,
    wave: str | None = None,
    root: str | Path | None = None,
    cells_root: str | Path | None = None,
    cells_by_track: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    dry_run: bool = True,
    put_r2: bool = False,
    staging_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Write local JSON. dry_run stages R2 payload. Never live-puts."""
    if put_r2 and not dry_run:
        raise ValueError(
            "reconstitution evidence never live-puts R2; pass dry_run=True"
        )
    from research.combo_basket_catalog import KEEP_BOTH_SLEEVES_JOB

    pack = reconstitution_evidence_pack(
        occupancy_by_track,
        cells_root=cells_root,
        cells_by_track=cells_by_track,
    )
    wave_id = str(wave or CURRENT_EVAL_WAVE)
    job = f"eval-reconstitution-evidence-{wave_id}"
    if root is not None:
        ops = Path(root)
        ops.mkdir(parents=True, exist_ok=True)
    else:
        from qp_paths import repo_root

        ops = repo_root() / "data" / "ops" / "research_eval"
        ops.mkdir(parents=True, exist_ok=True)
    body = json.dumps(pack, ensure_ascii=True, indent=2, default=str)
    path = ops / f"{job}.json"
    path.write_text(body, encoding="utf-8")
    put: dict[str, Any] | None = None
    if dry_run:
        from research.cf_mass_eval_stage import RESEARCH_ARTIFACT_BUCKET
        from research.r2_io import put_research_artifact

        put = put_research_artifact(
            RESEARCH_ARTIFACT_BUCKET,
            f"research/eval/job={job}/reconstitution_evidence.json",
            body.encode("utf-8"),
            dry_run=True,
            staging_dir=staging_dir,
        )
    return {
        "job_id": job,
        "path": str(path),
        "keep_sleeves_job": KEEP_BOTH_SLEEVES_JOB,
        "pack": pack,
        "put": put,
        "dry_run": True,
        "put_r2": False,
        "apply": bool(pack.get("apply")) and bool(RECONSTITUTION_APPLY),
        "go": False,
        "not_a_pass": True,
    }


def main() -> int:
    pack = reconstitution_evidence_pack()
    print(json.dumps(pack, ensure_ascii=True, indent=2, default=str))
    apply_ok = pack.get("apply") is False
    go_ok = pack.get("go") is False
    both = all(
        "drop_parents_keep_children" in s and "drop_children_keep_parents" in s
        for s in (pack.get("sleeves") or [])
    )
    return 0 if apply_ok and go_ok and both else 2


if __name__ == "__main__":
    raise SystemExit(main())
