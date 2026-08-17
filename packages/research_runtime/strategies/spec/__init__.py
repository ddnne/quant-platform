"""Declarative StrategySpec schema and safe interpreter."""

from .interpreter import StrategySpecStrategy, interpret_strategy_spec
from .schema import (
    CrossSectionRankRule,
    FeatureRef,
    REBALANCE_DAILY,
    REBALANCE_FIXED_HORIZON,
    STRATEGY_SPEC_VERSION,
    STRATEGY_SPEC_VERSION_V2,
    SUPPORTED_STRATEGY_SPEC_VERSIONS,
    StrategySpec,
    StrategySpecError,
    ThresholdRule,
    TopKRule,
    ValueMomentumAgreeRule,
)

__all__ = [
    "CrossSectionRankRule",
    "FeatureRef",
    "REBALANCE_DAILY",
    "REBALANCE_FIXED_HORIZON",
    "STRATEGY_SPEC_VERSION",
    "STRATEGY_SPEC_VERSION_V2",
    "SUPPORTED_STRATEGY_SPEC_VERSIONS",
    "StrategySpec",
    "StrategySpecError",
    "StrategySpecStrategy",
    "ThresholdRule",
    "TopKRule",
    "ValueMomentumAgreeRule",
    "interpret_strategy_spec",
]
