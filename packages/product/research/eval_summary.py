"""Family/logic flags from daily_path cells. Scores stay off Git.

Not a promote / GO. Candidate is occupancy-gated, never a pass.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

from research.eval_registry import is_daily_path_complete_cell, is_path_broken_cell, is_path_collapsed_cell

CANDIDATE_KEEP_SIMPLE: str = (
    "Simple occupancy-gated theses stay in the candidate pool for later "
    "combination/funds even when single-name t/Sharpe is modest. "
    "path_broken, path_collapsed, always_on, near_empty, and "
    "worker_body_missing are excluded."
)


def weakness_flags_from_summary(summary: Mapping[str, Any]) -> dict[str, list[str]]:
    """Read ``summary_family.json`` weakness flags. Does not execute a proposal."""
    out: dict[str, list[str]] = {}
    for row in summary.get("logics") or []:
        if not isinstance(row, Mapping):
            continue
        lid = str(row.get("logic_id") or "").strip()
        if not lid:
            continue
        flags = [str(x) for x in (row.get("flags") or [])]
        tag = str(row.get("tag") or "")
        if tag and tag not in flags:
            flags = [*flags, f"tag:{tag}"]
        if row.get("candidate") is False and "not_candidate" not in flags:
            flags.append("not_candidate")
        out[lid] = flags
    return out


def proposal_blocked_by_summary(
    payload: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> list[str]:
    flags = weakness_flags_from_summary(summary)
    reasons: list[str] = []
    parents = [str(x) for x in (payload.get("why_different_from") or [])]
    for parent in parents:
        pf = flags.get(parent) or []
        if "path_broken" in pf:
            reasons.append(f"parent_path_broken:{parent}")
        if "always_on" in pf and not payload.get("signal_definition"):
            reasons.append(f"parent_always_on_needs_new_signal:{parent}")
        if "not_candidate" in pf:
            reasons.append(f"parent_not_candidate:{parent}")
    return reasons


def summarize_daily_path_cells(
    cells: Sequence[Mapping[str, Any]],
    *,
    job_id: str,
) -> dict[str, Any]:
    """Family/logic flags from daily_path cells. Scores stay off Git."""
    from research.bar_native_specs import BAR_NATIVE_SPECS
    from research.unique_logic.constants import (
        ALWAYS_ON_CS_STICKY,
        ALWAYS_ON_OCCUPANCY_WARN,
        CANDIDATE_POLICY,
        CF_EVENT_DAILY_PATH_IDS,
        CF_NEW_CS_THESIS_IDS,
        CF_NEW_EVENT_THESIS_IDS,
        CS_LOGIC_IDS,
        NEAR_EMPTY_OCCUPANCY,
        RESEARCH_UNIQUE_LOGIC_IDS,
        TERM_STRUCTURE_REQUIRED,
        SPARSE_ON_15NAME_SHARD,
        WORKER_ISOLATE_LIMIT_IDS,
        countable_thesis_ids,
    )
    from research.unique_logic.worker_bodies import unique22_occupancy_park
    from research.unique_logic.near_duplicate import is_near_duplicate

    _countable = countable_thesis_ids()

    def _fam(lid: str) -> str:
        if lid in CF_NEW_EVENT_THESIS_IDS:
            return "event_new"
        if lid in CF_EVENT_DAILY_PATH_IDS:
            return "event"
        if lid in CF_NEW_CS_THESIS_IDS:
            return "cs_new"
        if lid in CS_LOGIC_IDS:
            return "unique_cs"
        if lid in BAR_NATIVE_SPECS:
            return "bar_native"
        return "other"

    by: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for c in cells:
        by[str(c.get("logic_id") or "")].append(c)

    def _mean(xs: list[Any]) -> float | None:
        vs = [float(x) for x in xs if x is not None]
        return (sum(vs) / len(vs)) if vs else None

    logics: list[dict[str, Any]] = []
    for lid, cs in by.items():
        if not lid:
            continue
        occs = [c.get("occupancy") if c.get("occupancy") is not None else c.get("occupancy_frac") for c in cs]
        nets = [c.get("total_ret_net") for c in cs]
        signs = [
            1 if (n or 0) > 1e-6 else (-1 if (n or 0) < -1e-6 else 0) for n in nets
        ]
        n_pos = sum(s > 0 for s in signs)
        n_neg = sum(s < 0 for s in signs)
        m_occ = _mean(occs)
        m_net = _mean(nets)
        paths = sorted(
            {
                str(c.get("eval_path") or "")
                for c in cs
                if c.get("eval_path")
            }
        )
        fallbacks = sorted(
            {
                str(c.get("path_fallback") or "")
                for c in cs
                if c.get("path_fallback")
            }
        )
        flags: list[str] = []
        if any(is_path_collapsed_cell(c) for c in cs):
            flags.append("path_collapsed")
        if any(is_path_broken_cell(c) for c in cs) or any(
            p in {"cs_generic", "mdh_generic"} for p in paths
        ) or any(
            str(f).startswith("path_broken") or str(f).startswith("mdh_empty")
            for f in fallbacks
        ):
            flags.append("path_broken")
        if m_occ is not None and m_occ >= ALWAYS_ON_OCCUPANCY_WARN:
            flags.append("always_on")
        if m_occ is not None and m_occ <= float(NEAR_EMPTY_OCCUPANCY):
            flags.append("near_empty")
        if lid in TERM_STRUCTURE_REQUIRED and (
            m_occ is None or m_occ <= float(NEAR_EMPTY_OCCUPANCY)
        ):
            flags.append("data_requirement_unmet")
        if lid in SPARSE_ON_15NAME_SHARD:
            flags.append("data_requirement_unmet")
        if is_near_duplicate(lid):
            flags.append("near_duplicate")
        if lid in ALWAYS_ON_CS_STICKY:
            flags.append("always_on_cs_sticky")
        if lid in WORKER_ISOLATE_LIMIT_IDS:
            flags.append("worker_isolate_limit")
        if lid in unique22_occupancy_park():
            flags.append("unique22_occupancy_mismatch")
        elif lid in RESEARCH_UNIQUE_LOGIC_IDS and lid not in _countable:
            flags.append("worker_body_missing")
        if m_net is not None and abs(m_net) < 1e-4:
            flags.append("near_zero_net")
        if n_pos >= 2 and n_neg >= 2:
            flags.append("sign_unstable")
        tag = "weak"
        if "path_collapsed" in flags:
            tag = "path_collapsed"
        elif "path_broken" in flags:
            tag = "path_broken"
        elif "always_on" in flags or "near_empty" in flags:
            tag = "suspicious"
        elif (
            m_net is not None
            and m_net > 0
            and n_pos >= 4
            and "sign_unstable" not in flags
            and "path_broken" not in flags
            and "always_on" not in flags
        ):
            tag = "strong"
        elif "sign_unstable" in flags:
            tag = "unstable"
        t_stats = [c.get("t_stat") for c in cs]
        sharpes = [c.get("sharpe_daily") for c in cs]
        dds = [c.get("daily_path_DD") for c in cs]
        exclude = set(CANDIDATE_POLICY["exclude"])  # type: ignore[arg-type]
        candidate = not bool(exclude.intersection(flags))
        logics.append(
            {
                "logic_id": lid,
                "family": _fam(lid),
                "n_windows": len(cs),
                "mean_occupancy": m_occ,
                "mean_total_ret_net": m_net,
                "mean_t_stat": _mean(t_stats),
                "mean_sharpe_daily": _mean(sharpes),
                "mean_daily_path_DD": _mean(dds),
                "n_pos_windows": n_pos,
                "n_neg_windows": n_neg,
                "eval_paths": paths,
                "path_fallbacks": fallbacks,
                "flags": flags,
                "tag": tag,
                "explore_flagged": tag == "strong",
                "candidate": candidate,
                "main_pool": candidate,
                "explore_only": True,
                "promote_as_main": False,
                "go": False,
            }
        )
    tags = Counter(r["tag"] for r in logics)
    fams = Counter(r["family"] for r in logics)
    cand_fams = Counter(r["family"] for r in logics if r.get("candidate"))
    return {
        "version": "eval-family-summary/v1",
        "job_id": job_id,
        "n_logics": len(logics),
        "n_cells": len(cells),
        "tag_counts": dict(tags),
        "family_counts": dict(fams),
        "n_strong": int(tags.get("strong") or 0),
        "n_weak": int(tags.get("weak") or 0),
        "n_suspicious": int(tags.get("suspicious") or 0),
        "n_unstable": int(tags.get("unstable") or 0),
        "n_path_broken": int(tags.get("path_broken") or 0),
        "n_path_collapsed": int(tags.get("path_collapsed") or 0),
        "n_always_on": sum(1 for r in logics if "always_on" in r["flags"]),
        "n_complete_cells": sum(1 for c in cells if is_daily_path_complete_cell(c)),
        "n_candidate_logics": sum(1 for r in logics if r.get("candidate")),
        "candidate_family_counts": dict(cand_fams),
        "n_near_empty": sum(1 for r in logics if "near_empty" in r["flags"]),
        "n_data_requirement_unmet": sum(
            1 for r in logics if "data_requirement_unmet" in r["flags"]
        ),
        "always_on_excluded_from_main": True,
        "near_empty_excluded_from_candidate": True,
        "path_broken_excluded_from_complete": True,
        "path_collapsed_excluded_from_complete": True,
        "path_collapsed_excluded_from_candidate": True,
        "strong_t_floor": None,
        "strong_sharpe_floor": None,
        "simple_strategies_kept_for_combinations": True,
        "candidate_policy": dict(CANDIDATE_POLICY),
        "always_on_warn": ALWAYS_ON_OCCUPANCY_WARN,
        "n_survivors_are_not_a_pass": True,
        "promote_as_main": False,
        "go": False,
        "logics": logics,
        "notes": (
            "candidate = not path_broken/collapsed/always_on/near_empty/"
            "data_requirement_unmet/near_duplicate/worker_body_missing. "
            "Simple gated theses stay for combinations. strong is an "
            "interest flag, never a promote."
        ),
    }
