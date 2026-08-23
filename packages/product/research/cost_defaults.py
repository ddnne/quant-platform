"""Shared 10bp one-way cost default. Not a trading model. Not GO.

Live cost math stays in cost_models.py. This module is the single literal
so holding_metrics / robustness_gate / paper_candidate_adapt do not each
re-define 0.001.
"""

from __future__ import annotations

DEFAULT_ONE_WAY_COST_BP: float = 10.0
DEFAULT_ONE_WAY_COST: float = DEFAULT_ONE_WAY_COST_BP / 10_000.0  # 0.001

__all__ = ["DEFAULT_ONE_WAY_COST", "DEFAULT_ONE_WAY_COST_BP"]
