"""Unique-logic evaluators (candidate-grade daily MTM). Does not GO."""
from __future__ import annotations

from importlib import import_module
from typing import Any

from research.unique_logic.catalog import load_catalog_specs

__all__ = [
    "adaptive",
    "all_unique_logic_specs",
    "cross_section",
    "cs_overlays",
    "event",
    "event_filters",
    "event_sides",
    "load_catalog_specs",
]


def all_unique_logic_specs() -> list[dict[str, Any]]:
    """Catalog specs (compiled map when YAML is absent). Not GO."""
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
