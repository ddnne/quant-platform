"""Small, deterministic feature-based strategies for Paper research."""

from __future__ import annotations

from .momentum import MomentumFeatureStrategy
from .return_1d import Return1dFeatureStrategy

__all__ = ["Return1dFeatureStrategy", "MomentumFeatureStrategy"]
