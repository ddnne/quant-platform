"""Shared freeze flags and occurrence floors for offline bar eval.

Not CF SoT; no GO.
"""

from __future__ import annotations

from typing import Any

from features.class_signals import (
    DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY,
    DEFAULT_MIN_EVENTS_PER_CODE_YEAR,
    DEFAULT_MIN_EVENTS_PER_TRADING_DAY,
)
from research.freezes import MASS_RESEARCH, PHASE7, READY_DECLARED

MIN_ACTIVATION_RATE_MULTIDAY: float = DEFAULT_MIN_ACTIVATION_RATE_MULTIDAY
MIN_EVENTS_PER_CODE_YEAR: float = DEFAULT_MIN_EVENTS_PER_CODE_YEAR
MIN_EVENTS_PER_TRADING_DAY: float = DEFAULT_MIN_EVENTS_PER_TRADING_DAY


def _freeze() -> dict[str, Any]:
    return {
        "mass_research": MASS_RESEARCH,
        "phase7": PHASE7,
        "ready_declared": READY_DECLARED,
        "operational_go": False,
        "connected_to_ready": False,
        "connected_to_mass": False,
        "significance_claimed": False,
        "edge_claimed": False,
        "s1_s5_unreject": False,
        "simple_daily_sign": False,
    }
