"""Mechanical sleeve catalog. Equal-weight only. Not a promote / GO.

Primary sleeves stay fund / flow / event-fund. No correlation weights.
"""
from __future__ import annotations

from typing import Any, Sequence

from research.unique_logic.constants import ALWAYS_ON_CS_STICKY

DEFAULT_CANDIDATE_BASKET: tuple[str, ...] = (
    "event_easing_uncrowded",
    "event_friday_skip",
    "cs_skip_monday",
    "overnight_down_cs_follow",
)

# Candidate occupancy is sleeve mean, not union. No correlation weights. No GO.
RETIRED_BASKET_RULES: frozenset[str] = frozenset(
    {"low_occupancy_band", "surprise_xs_only", "two_member_easing"}
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

# Equal-weight 2–3 sleeve blends. Not GO. No correlation weights.
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
        if any(m in ALWAYS_ON_CS_STICKY for m in members):
            reasons.append("always_on_cs_member")
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
                "weights": equal_weights(len(members)),
                "valid": not reasons,
                "reject": reasons,
                "promote_as_main": False,
                "go": False,
            }
        )
    return out


def primary_mechanical_basket_defs() -> list[dict[str, Any]]:
    """Primary / primary_candidate mechanical rules. Retired stay out. Not GO."""
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
                "weights": equal_weights(len(sleeves)),
                "valid": not reasons,
                "reject": reasons,
                "deprecated": False,
                "promote_as_main": False,
                "go": False,
                "not_a_pass": True,
            }
        )
    return out
