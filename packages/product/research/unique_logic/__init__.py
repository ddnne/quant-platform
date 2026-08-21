"""Unique-logic evaluators (candidate-grade daily MTM).

Declare a new hypothesis in ``specs/research_logics/*.yaml``. Add an
``evaluate_*_daily_mtm`` function in this package **only when the economics
are new**. Run via ``python -m research.unique_logic`` and record with
``scripts/record_research_eval.py`` (R2 + D1). Do not add
``scripts/run_wNN_*.py``.
"""
from research.unique_logic.catalog import catalog_spec, load_catalog_specs
from research.unique_logic.legacy import all_unique_logic_specs, wave_eval_modules

__all__ = [
    "all_unique_logic_specs",
    "catalog_spec",
    "load_catalog_specs",
    "wave_eval_modules",
    "w104",
    "w105",
    "w106",
    "w106b",
    "w107b",
    "w107c",
]


def __getattr__(name: str):
    if name in {"w104", "w105", "w106", "w106b", "w107b", "w107c"}:
        from importlib import import_module

        return import_module(f"research.unique_logic.{name}")
    raise AttributeError(name)
