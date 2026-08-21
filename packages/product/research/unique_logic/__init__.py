"""Unique-logic evaluators (candidate-grade daily MTM).

Declare a new hypothesis in ``specs/research_logics/*.yaml``. Add an
``evaluate_*_daily_mtm`` function in this package **only when the economics
are new**. Run via ``python -m research.unique_logic`` and record with
``scripts/record_research_eval.py`` (R2 + D1). Do not add
``scripts/run_wNN_*.py``.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

from research.unique_logic.catalog import catalog_spec, load_catalog_specs

__all__ = [
    "adaptive",
    "all_unique_logic_specs",
    "catalog_spec",
    "cross_section",
    "cs_overlays",
    "event",
    "event_filters",
    "event_sides",
    "load_catalog_specs",
]


def all_unique_logic_specs() -> list[dict[str, Any]]:
    from research.unique_logic import (
        adaptive,
        cross_section,
        cs_overlays,
        event,
        event_filters,
        event_sides,
    )

    out: list[dict[str, Any]] = []
    out.extend(list(event.NEW_UNIQUE_LOGIC))
    out.extend(list(event_filters.NEW_UNIQUE_LOGIC))
    out.extend(list(cross_section.NEW_UNIQUE_LOGIC))
    out.extend(list(event_sides.NEW_LS_VARIANTS))
    out.extend(list(cs_overlays.NEW_UNIQUE_LOGIC))
    out.extend(list(adaptive.ADAPTIVE_VARIANTS))
    return out


def __getattr__(name: str):
    if name in {
        "adaptive",
        "cross_section",
        "cs_overlays",
        "event",
        "event_filters",
        "event_sides",
    }:
        return import_module(f"research.unique_logic.{name}")
    raise AttributeError(name)
