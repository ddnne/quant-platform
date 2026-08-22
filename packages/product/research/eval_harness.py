"""Compatibility stub: smoke eval codes. Canonical SoT is daily_path / cf_*."""

from __future__ import annotations

from research.eval_universe import HARNESS_SMOKE_CODES

DEFAULT_EVAL_CODES: tuple[str, ...] = HARNESS_SMOKE_CODES

__all__ = [
    "DEFAULT_EVAL_CODES",
    "HARNESS_SMOKE_CODES",
]
