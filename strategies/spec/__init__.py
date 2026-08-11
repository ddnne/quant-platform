"""Declarative StrategySpec schema and safe interpreter."""

from .interpreter import StrategySpecStrategy, interpret_strategy_spec
from .schema import (
    FeatureRef,
    STRATEGY_SPEC_VERSION,
    StrategySpec,
    StrategySpecError,
    ThresholdRule,
    TopKRule,
)

__all__ = [
    "STRATEGY_SPEC_VERSION",
    "FeatureRef",
    "StrategySpec",
    "StrategySpecError",
    "StrategySpecStrategy",
    "ThresholdRule",
    "TopKRule",
    "interpret_strategy_spec",
]
