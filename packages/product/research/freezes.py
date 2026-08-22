"""Research freeze surface: flags + 3-default pins.

Flags come from ``features.research_freezes``. Pin tuples live here so
``daily_path_eval`` / CF drivers do not import ``offline.factory``.
Do not retune the three representatives.
"""
from __future__ import annotations

import json
from typing import Any

from features.research_freezes import (
    COMPLETE_INVENT,
    CONNECTED_TO_MASS,
    CONNECTED_TO_MASS_RESEARCH_LOOP,
    CONNECTED_TO_READY,
    CONTINUOUS_PAPER,
    DENSIFY,
    EDGE_CLAIMED,
    GO,
    LIVE_ORDER_PATH_ENABLED,
    LIVE_ORDERS,
    LOCAL_SOT,
    MASS_GENERATE_SIGNALS,
    MASS_RESEARCH,
    MASS_RESEARCH_ENV_ARMING_SWITCHES,
    MASS_RESEARCH_STATUS,
    OPERATIONAL_GO,
    ORDER_EXECUTION,
    PAPER_CONTINUOUS,
    PAPER_SCHEDULER_ARMED,
    PHASE7,
    PHASE7_ENV_ARMING_SWITCHES,
    PHASE7_STATUS,
    PROMOTE_AS_MAIN,
    READY_DECLARED,
    READY_PUBLICATION,
    READY_PUBLICATION_STATUS,
    S1_S5_UNREJECT,
    SIGNIFICANCE_CLAIMED,
    SIMPLE_DAILY_SIGN,
    SIMPLE_DAILY_SIGN_AS_DIVERSITY,
)

# W83–W86 default-path representatives. Factory / unique_logic must not retune.
FROZEN_DEFAULT_PATH: tuple[dict[str, Any], ...] = (
    {
        "representative_id": "cross_section_hold_10",
        "family_id": "cross_section_relative",
        "hold_days": 10,
        "momentum_n": 5,
        "long_frac": 0.3,
        "short_frac": 0.3,
        "stance": "KEEP",
        "note": "W83–W86 default path; factory must not retune",
    },
    {
        "representative_id": "cross_section_hold_10_mom3",
        "family_id": "cross_section_relative",
        "hold_days": 10,
        "momentum_n": 3,
        "long_frac": 0.3,
        "short_frac": 0.3,
        "stance": "PROMOTE",
        "note": "W85 promote; factory must not retune",
    },
    {
        "representative_id": "fundamentals_hold_10",
        "family_id": "fundamentals_price",
        "hold_days": 10,
        "momentum_n": 10,
        "mode": "value_momentum_agree",
        "stance": "KEEP",
        "note": "W83–W86 default path; factory must not retune",
    },
)

FROZEN_PIN_SNAPSHOT: tuple[tuple[str, int, int | None, str], ...] = (
    ("cross_section_hold_10", 10, 5, "KEEP"),
    ("cross_section_hold_10_mom3", 10, 3, "PROMOTE"),
    ("fundamentals_hold_10", 10, 10, "KEEP"),
)


def assert_frozen_pins_untouched(
    *,
    note: str = "daily_path_eval must not mutate 3-default pins",
) -> dict[str, Any]:
    by_id = {r["representative_id"]: r for r in FROZEN_DEFAULT_PATH}
    ok = True
    details: list[dict[str, Any]] = []
    for rid, hold, mom, stance in FROZEN_PIN_SNAPSHOT:
        r = by_id.get(rid)
        if r is None:
            ok = False
            details.append({"representative_id": rid, "status": "MISSING"})
            continue
        match = (
            int(r.get("hold_days") or -1) == hold
            and int(r.get("momentum_n") or -1) == int(mom or -1)
            and str(r.get("stance") or "") == stance
        )
        if not match:
            ok = False
        details.append(
            {
                "representative_id": rid,
                "expected": {
                    "hold_days": hold,
                    "momentum_n": mom,
                    "stance": stance,
                },
                "actual": {
                    "hold_days": r.get("hold_days"),
                    "momentum_n": r.get("momentum_n"),
                    "stance": r.get("stance"),
                },
                "match": match,
            }
        )
    pack = {
        "pins_untouched": ok,
        "n_pins": len(FROZEN_DEFAULT_PATH),
        "details": details,
        "frozen_defaults_retuned": False,
        "note": note,
    }
    if not ok:
        raise RuntimeError(
            "FROZEN_DEFAULT_PATH drift — abort daily_path_eval: "
            + json.dumps(details, default=str)
        )
    return pack


def freeze_flags() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": OPERATIONAL_GO,
        "connected_to_ready": CONNECTED_TO_READY,
        "connected_to_mass": CONNECTED_TO_MASS,
        "edge_claimed": EDGE_CLAIMED,
        "significance_claimed": SIGNIFICANCE_CLAIMED,
        "s1_s5_unreject": S1_S5_UNREJECT,
        "simple_daily_sign_as_diversity": SIMPLE_DAILY_SIGN_AS_DIVERSITY,
        "continuous_paper": CONTINUOUS_PAPER,
        "live_orders": LIVE_ORDERS,
        "promote_as_main": PROMOTE_AS_MAIN,
        "go": GO,
        "frozen_default_path": [r["representative_id"] for r in FROZEN_DEFAULT_PATH],
        "frozen_defaults_retuned": False,
    }
