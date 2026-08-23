"""Mechanical sleeve catalog. Equal-weight only. Not a promote / GO."""
from __future__ import annotations

from typing import Any, Sequence

from research.unique_logic.constants import (
    ALWAYS_ON_CS_STICKY,
    ALWAYS_ON_PARK_IDS,
    NEAR_EMPTY_PARK_IDS,
    THIN_SLEEVE_EXCLUDE_IDS,
)

DEFAULT_CANDIDATE_BASKET: tuple[str, ...] = (
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
MECHANICAL_BASKETS: tuple[dict[str, object], ...] = (
    {
        "basket_id": "basket_head4",
        "rule": "known_candidate_head",
        "primary": False,
        "members": DEFAULT_CANDIDATE_BASKET,
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
    return reasons


def equal_weights(n: int) -> list[float]:
    if n <= 0:
        return []
    w = 1.0 / float(n)
    return [w] * int(n)


def mechanical_basket_defs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in MECHANICAL_BASKETS:
        rule = str(raw.get("rule") or "mechanical")
        if rule in RETIRED_BASKET_RULES:
            continue
        members = tuple(str(x) for x in (raw.get("members") or ()))
        reasons = validate_basket_members(members)
        prim = bool(raw.get("primary"))
        pc = bool(raw.get("primary_candidate")) or prim
        out.append(
            {
                "basket_id": str(raw["basket_id"]),
                "rule": rule,
                "primary": prim,
                "primary_candidate": pc,
                "deprecated": False,
                "members": list(members),
                "valid": not reasons,
                "reject": reasons,
                "promote_as_main": False,
                "go": False,
            }
        )
    return out


def primary_mechanical_basket_defs() -> list[dict[str, Any]]:
    return [
        d
        for d in mechanical_basket_defs()
        if d.get("valid") and (d.get("primary") or d.get("primary_candidate"))
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
