"""Offline W78–W86 bar-eval surface (not CF SoT; no GO).

``evaluate_*_on_bars`` bodies. Local bar mirrors + SQLite only;
not Mass / READY / Phase7 / operational GO.
"""

from __future__ import annotations

from research.offline.bar_eval_flow_fund import (
    evaluate_cross_section_on_bars,
    evaluate_flow_demand_on_bars,
    evaluate_fundamentals_price_on_bars,
    evaluate_mf_flow_price_on_bars,
    evaluate_mf_value_mom_rate_on_bars,
)
from research.offline.bar_eval_hold import (
    evaluate_event_post_on_bars,
    evaluate_multi_day_hold_on_bars,
)
from research.offline.bar_eval_macro import (
    evaluate_macro_conditioned_on_bars,
    evaluate_rate_curve_xs_on_bars,
    evaluate_rate_level_xs_on_bars,
)
from research.offline.bar_eval_vol import (
    evaluate_nky_vol_abs_level_on_bars,
    evaluate_nky_vol_term_levels_on_bars,
    evaluate_nky_vol_term_ratio_on_bars,
    evaluate_opt225_vol_on_bars,
    evaluate_vol_risk_adjusted_on_bars,
)


__all__ = [
    "evaluate_cross_section_on_bars",
    "evaluate_event_post_on_bars",
    "evaluate_flow_demand_on_bars",
    "evaluate_fundamentals_price_on_bars",
    "evaluate_macro_conditioned_on_bars",
    "evaluate_mf_flow_price_on_bars",
    "evaluate_mf_value_mom_rate_on_bars",
    "evaluate_multi_day_hold_on_bars",
    "evaluate_nky_vol_abs_level_on_bars",
    "evaluate_nky_vol_term_levels_on_bars",
    "evaluate_nky_vol_term_ratio_on_bars",
    "evaluate_opt225_vol_on_bars",
    "evaluate_rate_curve_xs_on_bars",
    "evaluate_rate_level_xs_on_bars",
    "evaluate_vol_risk_adjusted_on_bars",
]
