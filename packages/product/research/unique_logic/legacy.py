"""Compatibility aliases for unique_logic evaluators.

Factory and tests import through this module. Implementations live in
``research.unique_logic.w104`` … ``w107c``, not ``scripts/run_w*``.
"""
from __future__ import annotations

import importlib
from typing import Any


def wave_eval_modules() -> dict[str, Any]:
    return {
        "w104": importlib.import_module("research.unique_logic.w104"),
        "w105": importlib.import_module("research.unique_logic.w105"),
        "w106": importlib.import_module("research.unique_logic.w106"),
        "w106b": importlib.import_module("research.unique_logic.w106b"),
        "w107b": importlib.import_module("research.unique_logic.w107b"),
        "w107c": importlib.import_module("research.unique_logic.w107c"),
    }


def all_unique_logic_specs() -> list[dict[str, Any]]:
    mods = wave_eval_modules()
    out: list[dict[str, Any]] = []
    for key in ("w104", "w105", "w106b", "w107b"):
        out.extend(list(getattr(mods[key], "NEW_UNIQUE_LOGIC", ()) or ()))
    out.extend(list(getattr(mods["w106"], "NEW_LS_VARIANTS", ()) or ()))
    out.extend(list(getattr(mods["w107c"], "ADAPTIVE_VARIANTS", ()) or ()))
    return out
