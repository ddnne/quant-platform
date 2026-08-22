"""Offline W78–W86 multi-year orchestration surface (not CF SoT; no GO).

Re-exports ``run_class_hyp_multi_year_eval`` from ``research.class_hyp_eval``.
Orchestration body stays in ``class_hyp_eval`` this turn. Local bar mirrors
+ SQLite only; not Mass / READY / Phase7 / operational GO.
"""

from __future__ import annotations

from research.class_hyp_eval import (
    DEFAULT_SQLITE,
    load_repo_rows_from_sqlite,
    run_class_hyp_multi_year_eval,
)

__all__ = [
    "DEFAULT_SQLITE",
    "load_repo_rows_from_sqlite",
    "run_class_hyp_multi_year_eval",
]
