"""Unique-logic evaluators (candidate-grade daily MTM).

YAML in ``specs/research_logics`` is the declaration SoT. Add
``evaluate_*_daily_mtm`` only when the economics are new. Does not GO.
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
    """YAML catalog is the runtime declaration SoT."""
    return load_catalog_specs()


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
