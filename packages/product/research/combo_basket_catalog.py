"""Mechanical sleeve catalog. Equal-weight only. Not a promote / GO."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Any, Mapping, Sequence

from research.eval_flags import RECONSTITUTION_APPLY
from research.unique_logic.constants import (
    ALWAYS_ON_CS_STICKY,
    ALWAYS_ON_PARK_IDS,
    NEAR_EMPTY_PARK_IDS,
    PRI_FLOW_GATES,
    PRI_FUND_GATES,
    PRI_RATE_GATES,
    PROPOSE_CALENDAR_GATES,
    THIN_SLEEVE_EXCLUDE_IDS,
)

SLEEVE_THEME_GATES: dict[str, frozenset[str]] = {
    "basket_theme_fund": PRI_FUND_GATES,
    "basket_theme_flow": PRI_FLOW_GATES,
    "basket_event_fund": PRI_FUND_GATES,
    "basket_theme_repo": PRI_RATE_GATES,
    "basket_theme_invert": frozenset({"invert_curve"}),
}
KEEP_BOTH_SLEEVES_JOB: str = "eval-cf-dp-both-sleeves-20260824df"
FLOW_FIFTH_BLEND_THINNER_JOB: str = "eval-flow-5th-blend-20260824ek"
BLEND_THINNER_KEEP_IDS: frozenset[str] = frozenset(
    {
        "event_afterclose_uncrowded",
        "surprise_xs_peps_uncr",
    }
)
HUMAN_RECONSTITUTION_PENDING: tuple[str, ...] = (
    "basket_theme_fund",
    "basket_event_fund",
)

HISTORICAL_HEAD4_MEMBERS: tuple[str, ...] = (
    "event_afterclose_positive_eps",
    "event_ta_up_positive_eps",
    "surprise_xs_uncrowded_afterclose",
    "event_positive_eps_liq_high",
)

RETIRED_BASKET_RULES: frozenset[str] = frozenset(
    {
        "low_occupancy_band",
        "surprise_xs_only",
        "two_member_easing",
        "event_calendar_only",
    }
)
HISTORICAL_BASKET_RULES: frozenset[str] = frozenset(
    {
        "known_candidate_head",
        "event_family_only",
        "family_spread",
        "mid_occupancy_band",
        "cs_family_only",
    }
)
MECHANICAL_BASKETS: tuple[dict[str, object], ...] = (
    {
        "basket_id": "basket_head4",
        "rule": "known_candidate_head",
        "primary": False,
        "members": HISTORICAL_HEAD4_MEMBERS,
    },
    {
        "basket_id": "basket_event4",
        "rule": "event_family_only",
        "primary": False,
        "members": (
            "event_afterclose_positive_eps",
            "event_ta_up_positive_eps",
            "event_large_surprise_positive_eps",
            "event_eqar_high_positive_eps",
        ),
    },
    {
        "basket_id": "basket_family4",
        "rule": "family_spread",
        "primary": False,
        "members": (
            "event_ta_up_positive_eps",
            "surprise_xs_uncrowded_afterclose",
            "cs_eqar_high_easy",
            "surprise_xs_ta_up",
        ),
    },
    {
        "basket_id": "basket_midocc4",
        "rule": "mid_occupancy_band",
        "primary": False,
        "members": (
            "event_eqar_high_liq_high",
            "event_eps_up_uncrowded",
            "event_eqar_rising_ta_up_liq",
            "cs_repo3m_down",
        ),
    },
    {
        "basket_id": "basket_cs4",
        "rule": "cs_family_only",
        "primary": False,
        "members": (
            "cs_nky_vol_high_fade",
            "cs_eqar_high_easy",
            "cs_ta_up_easy",
            "cs_on_impulse",
        ),
    },
    {
        "basket_id": "basket_theme_fund",
        "rule": "fundamentals_sleeve",
        "primary": True,
        "members": (
            "event_ta_up_positive_eps",
            "event_large_surprise_positive_eps",
            "event_ac_peps_taup",
            "event_eqar_high_positive_eps",
            "event_positive_eps_liq_high",
        ),
    },
    {
        "basket_id": "basket_theme_flow",
        "rule": "margin_flow_sleeve",
        "primary": True,
        "members": (
            "event_positive_eps_uncrowded",
            "surprise_xs_ac_peps_taup",
            "surprise_xs_uncrowded_afterclose",
            "event_ta_up_uncrowded",
        ),
    },
    {
        "basket_id": "basket_theme_repo",
        "rule": "repo_rate_sleeve",
        "primary": False,
        "members": (
            "event_repo3m_down_pead",
            "surprise_xs_repo3m_down",
            "event_positive_eps_repo3m",
            "event_ta_up_repo3m_down",
        ),
    },
    {
        "basket_id": "basket_theme_invert",
        "rule": "invert_print_sleeve",
        "primary": False,
        "members": (
            "event_invert_positive_eps",
            "event_afterclose_invert",
            "event_ac_inv_peps",
            "event_invert_ta_up",
        ),
    },
    {
        "basket_id": "basket_event_fund",
        "rule": "event_fund_cross",
        "primary": True,
        "members": (
            "event_afterclose_positive_eps",
            "event_ta_up_positive_eps",
            "event_large_surprise_positive_eps",
            "surprise_xs_afterclose_ta_up",
            "event_ac_peps_taup",
        ),
    },
)

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
RETIRED_META_IDS: frozenset[str] = frozenset(
    {"meta_event4_flow", "meta_event4_fund", "meta_head_fund"}
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
    if any(m in ALWAYS_ON_CS_STICKY for m in ids):
        reasons.append("always_on_cs_member")
    if any(m in NEAR_EMPTY_PARK_IDS for m in ids):
        reasons.append("near_empty_member")
    if any(m in ALWAYS_ON_PARK_IDS for m in ids):
        reasons.append("always_on_member")
    if any(m in THIN_SLEEVE_EXCLUDE_IDS for m in ids):
        reasons.append("thin_sleeve_member")
    if any(_member_has_calendar(m) for m in ids):
        reasons.append("calendar_member")
    return reasons


def _spec_gates(logic_id: str) -> frozenset[str]:
    from research.unique_logic.catalog import catalog_spec, spec_gates

    return frozenset(spec_gates(catalog_spec(str(logic_id or ""))))


def _member_has_calendar(logic_id: str) -> bool:
    """True when a sleeve member is a weekday/calendar permutation."""
    lid = str(logic_id or "")
    if any(g in lid for g in PROPOSE_CALENDAR_GATES):
        return True
    return bool(PROPOSE_CALENDAR_GATES.intersection(_spec_gates(lid)))


def nested_parent_pairs(logic_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Detect A.gates ⊂ B.gates inside one sleeve. Does not reject. Not a pass.

    Nested 2-AND parents of a 3-AND sibling are recorded so reconstitution
    can see them. Existing primary sleeves stay valid until a reconstitution
    plan replaces them. Empty gate sets are skipped (not a parent of all).
    """
    ids = tuple(str(x).strip() for x in logic_ids if str(x).strip())
    return [dict(p) for p in _nested_parent_pairs_cached(ids)]


@lru_cache(maxsize=256)
def _nested_parent_pairs_cached(
    ids: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    gates_by = {lid: _spec_gates(lid) for lid in ids}
    out: list[dict[str, Any]] = []
    for parent in ids:
        gp = gates_by.get(parent) or frozenset()
        if not gp:
            continue
        for child in ids:
            if parent == child:
                continue
            gc = gates_by.get(child) or frozenset()
            if gp < gc:
                out.append(
                    {
                        "parent": parent,
                        "child": child,
                        "parent_gates": sorted(gp),
                        "child_gates": sorted(gc),
                    }
                )
    return tuple(out)


def would_nest_in_sleeve(candidate: str, members: Sequence[str]) -> bool:
    """True when adding candidate creates a nested parent pair. Detect only."""
    lid = str(candidate or "").strip()
    if not lid:
        return False
    rest = [str(x).strip() for x in members if str(x).strip() and str(x).strip() != lid]
    return bool(nested_parent_pairs([lid, *rest]))


@lru_cache(maxsize=1)
def primary_sleeve_member_ids() -> frozenset[str]:
    """Members of current primary sleeves. Historical deprecated sleeves excluded."""
    out: set[str] = set()
    for d in mechanical_basket_defs():
        if d.get("historical"):
            continue
        if not (d.get("primary") or d.get("primary_candidate")):
            continue
        out.update(str(x) for x in (d.get("members") or ()))
    return frozenset(out)


def replacement_reject_reasons(
    candidate: str,
    members: Sequence[str],
    *,
    theme_gates: Sequence[str] | None = None,
) -> list[str]:
    """Why a sleeve replacement is not adoptable. Does not mutate. Not a pass.

    1-AND soup, nested parents, calendar, and already-primary members are
    rejected. Optional theme_gates (e.g. PRI_FLOW_GATES) keep the sleeve on
    theme. Empty leftover occupancy is not a pass.
    """
    lid = str(candidate or "").strip()
    reasons: list[str] = []
    if not lid:
        reasons.append("empty_candidate")
        return reasons
    gates = _spec_gates(lid)
    if len(gates) < 2:
        reasons.append("one_and_soup")
    if would_nest_in_sleeve(lid, members):
        reasons.append("nested_parent")
    if _member_has_calendar(lid):
        reasons.append("calendar_member")
    if lid in primary_sleeve_member_ids() and lid not in {str(x) for x in members}:
        reasons.append("already_primary_member")
    if theme_gates is not None and not gates.intersection(str(g) for g in theme_gates):
        reasons.append("theme_gate_mismatch")
    return reasons


def reconstitution_options(
    logic_ids: Sequence[str],
    *,
    nested: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Drop nested parents or nested children. Does not mutate sleeves. Not a pass.

    apply_reject stays False until a human reconstitution replaces primary
    members. Empty leftover sleeves are recorded, not auto-filled.
    Pass ``nested`` from mechanical_basket_defs to skip a second gate walk.
    """
    ids = [str(x).strip() for x in logic_ids if str(x).strip()]
    nested_list = (
        [dict(p) for p in nested] if nested is not None else nested_parent_pairs(ids)
    )
    parents = {str(p.get("parent")) for p in nested_list}
    children = {str(p.get("child")) for p in nested_list}
    keep_children = [i for i in ids if i not in parents]
    keep_parents = [i for i in ids if i not in children]

    def _nested_among(keep: Sequence[str]) -> int:
        s = set(keep)
        return sum(
            1
            for p in nested_list
            if str(p.get("parent")) in s and str(p.get("child")) in s
        )

    return {
        "nested_parents": nested_list,
        "apply_reject": False,
        "drop_parents_keep_children": {
            "members": keep_children,
            "nested_parent_count": _nested_among(keep_children),
            "dropped": sorted(parents),
        },
        "drop_children_keep_parents": {
            "members": keep_parents,
            "nested_parent_count": _nested_among(keep_parents),
            "dropped": sorted(children),
        },
        "go": False,
        "not_a_pass": True,
    }


def reconstitution_plan() -> list[dict[str, Any]]:
    """Per-sleeve reconstitution options. Does not change members. Not a pass."""
    out: list[dict[str, Any]] = []
    for d in mechanical_basket_defs():
        opts = reconstitution_options(
            list(d.get("members") or ()),
            nested=d.get("nested_parents"),
        )
        nested_n = int(d.get("nested_parent_count") or 0)
        primary = bool(d.get("primary") or d.get("primary_candidate"))
        out.append(
            {
                "basket_id": d["basket_id"],
                "rule": d["rule"],
                "primary": bool(d.get("primary")),
                "historical": bool(d.get("historical")),
                "valid": bool(d.get("valid")),
                "needs_reconstitution": bool(primary and nested_n),
                **opts,
                "nested_parent_count": nested_n,
            }
        )
    return out


def active_reconstitution_plan() -> list[dict[str, Any]]:
    """Non-historical sleeves only. Historical stay in reconstitution_plan()."""
    return [p for p in reconstitution_plan() if not p.get("historical")]


def _min_lo(
    lid: str,
    mid: Mapping[str, float],
    liq: Mapping[str, float],
) -> float | None:
    if lid not in mid or lid not in liq:
        return None
    return min(float(mid[lid]), float(liq[lid]))


def _round4(raw: float | None) -> float | None:
    if raw is None:
        return None
    return round(float(raw), 4)


def _occ_summary(
    members: Sequence[str],
    mid: Mapping[str, float],
    liq: Mapping[str, float],
) -> dict[str, Any]:
    """Per-member occupancy. Mean is not a sleeve blend. Not GO."""
    ids = [str(x) for x in members if str(x).strip()]
    rows: list[dict[str, Any]] = []
    los: list[float] = []
    for lid in ids:
        a = mid.get(lid)
        b = liq.get(lid)
        lo = _min_lo(lid, mid, liq)
        if lo is not None:
            los.append(float(lo))
        rows.append(
            {
                "logic_id": lid,
                "mid_n_explore": _round4(None if a is None else float(a)),
                "liq_large": _round4(None if b is None else float(b)),
                "lo": _round4(lo),
            }
        )
    lo_pack: dict[str, float | int] | None = None
    if los:
        lo_pack = {
            "n": len(los),
            "min": round(min(los), 4),
            "mean": round(sum(los) / len(los), 4),
            "max": round(max(los), 4),
        }
    return {
        "members": ids,
        "n": len(ids),
        "by_id": rows,
        "lo": lo_pack,
        "occupancy_mean_not_a_blend": True,
        "go": False,
        "not_a_pass": True,
    }


def reconstitution_occupancy_preview(
    occupancy_by_track: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, Any]:
    """drop_parents vs drop_children occupancy from maps. Does not apply.

    Not a stitch blend. Does not fan out. Not GO.
    """
    occ = occupancy_by_track or {}
    mid = dict(occ.get("mid_n_explore") or {})
    liq = dict(occ.get("liq_large") or {})
    defs = {
        str(d["basket_id"]): d
        for d in mechanical_basket_defs()
        if not d.get("historical")
    }
    sleeves: list[dict[str, Any]] = []
    for p in active_reconstitution_plan():
        bid = str(p["basket_id"])
        members = [str(x) for x in (defs.get(bid, {}).get("members") or ())]
        drop_p = p.get("drop_parents_keep_children") or {}
        drop_c = p.get("drop_children_keep_parents") or {}
        keep_p = [str(x) for x in (drop_p.get("members") or ())]
        keep_c = [str(x) for x in (drop_c.get("members") or ())]
        sleeves.append(
            {
                "basket_id": bid,
                "primary": p.get("primary"),
                "needs_reconstitution": p.get("needs_reconstitution"),
                "nested_parent_count": int(p.get("nested_parent_count") or 0),
                "current": _occ_summary(members, mid, liq),
                "drop_parents_keep_children": {
                    **_occ_summary(keep_p, mid, liq),
                    "dropped": list(drop_p.get("dropped") or []),
                    "nested_parent_count": drop_p.get("nested_parent_count"),
                },
                "drop_children_keep_parents": {
                    **_occ_summary(keep_c, mid, liq),
                    "dropped": list(drop_c.get("dropped") or []),
                    "nested_parent_count": drop_c.get("nested_parent_count"),
                },
                "apply": bool(RECONSTITUTION_APPLY),
            }
        )
    pending = [
        s["basket_id"] for s in sleeves if s.get("needs_reconstitution")
    ]
    return {
        "version": "reconstitution-preview/v1",
        "keep_sleeves_job": KEEP_BOTH_SLEEVES_JOB,
        "flow_fifth_blend_thinner_job": FLOW_FIFTH_BLEND_THINNER_JOB,
        "do_not_restitch_blend": True,
        "human_choice_required": True,
        "human_pending": list(HUMAN_RECONSTITUTION_PENDING),
        "apply": bool(RECONSTITUTION_APPLY),
        "sleeves": sleeves,
        "go": False,
        "not_a_pass": True,
    }


def usable_sleeve_coverage(
    occupancy_by_track: Mapping[str, Mapping[str, float]] | None = None,
    *,
    candidate_cap: int = 12,
) -> dict[str, Any]:
    """Usable inventory vs KEEP sleeves. Detect-only. Does not apply. Not GO.

    Replacement candidates are on-theme n_ands>=2, non-nested, not already
    primary, and (for 5-member sleeves) thicker than the current weakest
    member. Invert is recorded primary=False and is not a replacement target.
    """
    from research.unique_logic.worker_bodies import (
        usable_inventory,
        usable_series_breakdown,
    )

    occ = occupancy_by_track or {}
    mid = dict(occ.get("mid_n_explore") or {})
    liq = dict(occ.get("liq_large") or {})
    inv = usable_inventory({"mid_n_explore": mid, "liq_large": liq})
    series = usable_series_breakdown({"mid_n_explore": mid, "liq_large": liq})
    usable = set(inv.get("usable_ids") or ())
    already = primary_sleeve_member_ids()
    sleeves: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    thinner_excluded: list[dict[str, Any]] = []
    seen_thinner: set[str] = set()
    for d in mechanical_basket_defs():
        if d.get("historical"):
            continue
        bid = str(d["basket_id"])
        members = [str(x) for x in (d.get("members") or ())]
        nested_n = int(d.get("nested_parent_count") or 0)
        primary = bool(d.get("primary"))
        member_lo = [_min_lo(m, mid, liq) for m in members]
        known_lo = [x for x in member_lo if x is not None]
        weakest = min(known_lo) if known_lo else None
        row = {
            "basket_id": bid,
            "rule": d.get("rule"),
            "primary": primary,
            "members": members,
            "n_members": len(members),
            "n_usable_members": sum(1 for m in members if m in usable),
            "nested_parent_count": nested_n,
            "needs_reconstitution": bool(primary and nested_n),
            "theme_gates": sorted(SLEEVE_THEME_GATES.get(bid, ())),
            "weakest_lo": weakest,
            "occupancy": _occ_summary(members, mid, liq),
        }
        sleeves.append(row)
        if not primary:
            continue
        theme = SLEEVE_THEME_GATES.get(bid)
        scored: list[tuple[float, str, list[str]]] = []
        for lid in usable:
            if lid in already:
                continue
            reasons = replacement_reject_reasons(
                lid, members, theme_gates=theme
            )
            lo = _min_lo(lid, mid, liq)
            if lid in BLEND_THINNER_KEEP_IDS:
                reasons = list(reasons) + ["blend_thinner_keep"]
                if lid not in seen_thinner:
                    seen_thinner.add(lid)
                    thinner_excluded.append(
                        {
                            "logic_id": lid,
                            "lo": _round4(lo),
                            "reason": "blend_thinner_keep",
                            "job": FLOW_FIFTH_BLEND_THINNER_JOB,
                            "apply": False,
                        }
                    )
            if lo is None:
                reasons = list(reasons) + ["occupancy_unclassified"]
            elif weakest is not None and lo <= weakest:
                reasons = list(reasons) + ["not_thicker_than_weakest"]
            if reasons:
                continue
            scored.append((float(lo), lid, []))
        scored.sort(reverse=True)
        for lo, lid, _ in scored[: max(0, int(candidate_cap))]:
            candidates.append(
                {
                    "basket_id": bid,
                    "logic_id": lid,
                    "lo": round(lo, 4),
                    "apply": False,
                }
            )
    return {
        "version": "series-sleeve/v1",
        "n_usable": inv.get("n_usable"),
        "family": inv.get("family"),
        "tag_counts": series.get("tag_counts"),
        "tag_combo": series.get("tag_combo"),
        "n_ands": series.get("n_ands"),
        "n_event_or_surprise_xs_3and": series.get("n_event_or_surprise_xs_3and"),
        "sleeves": sleeves,
        "replacement_candidates": candidates,
        "n_replacement_ok": len(candidates),
        "blend_thinner_excluded": thinner_excluded,
        "keep_sleeves_job": KEEP_BOTH_SLEEVES_JOB,
        "human_pending": list(HUMAN_RECONSTITUTION_PENDING),
        "apply": bool(RECONSTITUTION_APPLY),
        "invert_primary": False,
        "go": False,
        "not_a_pass": True,
    }


def equal_weights(n: int) -> list[float]:
    if n <= 0:
        return []
    w = 1.0 / float(n)
    return [w] * int(n)


def clear_basket_caches() -> None:
    """Drop sleeve caches after catalog writes. Not a second SoT."""
    _nested_parent_pairs_cached.cache_clear()
    _mechanical_basket_defs_cached.cache_clear()
    primary_sleeve_member_ids.cache_clear()


def mechanical_basket_defs() -> list[dict[str, Any]]:
    return [deepcopy(d) for d in _mechanical_basket_defs_cached()]


@lru_cache(maxsize=1)
def _mechanical_basket_defs_cached() -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    for raw in MECHANICAL_BASKETS:
        rule = str(raw.get("rule") or "mechanical")
        if rule in RETIRED_BASKET_RULES:
            continue
        members = tuple(str(x) for x in (raw.get("members") or ()))
        reasons = validate_basket_members(members)
        nested = nested_parent_pairs(members)
        prim = bool(raw.get("primary"))
        pc = bool(raw.get("primary_candidate")) or prim
        hist = rule in HISTORICAL_BASKET_RULES
        out.append(
            {
                "basket_id": str(raw["basket_id"]),
                "rule": rule,
                "primary": prim,
                "primary_candidate": pc,
                "historical": hist,
                "deprecated": hist,
                "members": list(members),
                "valid": not reasons,
                "reject": reasons,
                "nested_parents": nested,
                "nested_parent_count": len(nested),
                "promote_as_main": False,
                "go": False,
            }
        )
    return tuple(out)


def primary_mechanical_basket_defs() -> list[dict[str, Any]]:
    return [
        d
        for d in mechanical_basket_defs()
        if d.get("valid")
        and not d.get("historical")
        and (d.get("primary") or d.get("primary_candidate"))
    ]


def meta_basket_defs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    known = {d["basket_id"] for d in mechanical_basket_defs()}
    for raw in META_BASKETS:
        mid = str(raw["meta_id"])
        if mid in RETIRED_META_IDS:
            continue
        sleeves = tuple(str(x) for x in (raw.get("sleeves") or ()))
        reasons = []
        if not (2 <= len(sleeves) <= 3):
            reasons.append("need_2_or_3_sleeves")
        if len(set(sleeves)) != len(sleeves):
            reasons.append("duplicate_sleeves")
        if any(s not in known for s in sleeves):
            reasons.append("unknown_sleeve")
        out.append(
            {
                "meta_id": mid,
                "sleeves": list(sleeves),
                "valid": not reasons,
                "reject": reasons,
                "deprecated": False,
                "promote_as_main": False,
                "go": False,
                "not_a_pass": True,
            }
        )
    return out
