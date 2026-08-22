"""Operational freeze flags (single source).

Mass / READY / Phase 7 / GO stay closed. Modules re-export these names;
they must not re-bind the values. Pins live in ``research.freezes``.
"""
from __future__ import annotations

MASS_RESEARCH: str = "NO-GO"
MASS_RESEARCH_STATUS: str = MASS_RESEARCH
PHASE7: str = "OFF"
PHASE7_STATUS: str = PHASE7
READY_DECLARED: bool = False
READY_PUBLICATION: str = "OFF"
READY_PUBLICATION_STATUS: str = READY_PUBLICATION
OPERATIONAL_GO: bool = False
CONNECTED_TO_READY: bool = False
CONNECTED_TO_MASS: bool = False
CONNECTED_TO_MASS_RESEARCH_LOOP: bool = False
EDGE_CLAIMED: bool = False
SIGNIFICANCE_CLAIMED: bool = False
S1_S5_UNREJECT: bool = False
SIMPLE_DAILY_SIGN: bool = False
SIMPLE_DAILY_SIGN_AS_DIVERSITY: bool = False
MASS_GENERATE_SIGNALS: bool = False
COMPLETE_INVENT: bool = False
ORDER_EXECUTION: bool = False
LIVE_ORDERS: bool = False
LIVE_ORDER_PATH_ENABLED: bool = False
CONTINUOUS_PAPER: str = "UNARMED"
PAPER_CONTINUOUS: bool = False
PAPER_SCHEDULER_ARMED: bool = False
DENSIFY: bool = False
LOCAL_SOT: bool = False
PROMOTE_AS_MAIN: bool = False
GO: bool = False

# No env/flag arming switches exist. Tests freeze the empty sets.
PHASE7_ENV_ARMING_SWITCHES: frozenset[str] = frozenset()
MASS_RESEARCH_ENV_ARMING_SWITCHES: frozenset[str] = frozenset()
