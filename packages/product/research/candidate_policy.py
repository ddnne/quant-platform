"""Job-level candidate grade. Partial/unknown is false. Not GO.

Python fanout and Worker daily_path must use the same predicate:
expected cells exist, all complete, none collapsed/broken.

Evaluation IR (research.evaluation_ir) must call this function; do not
copy the boolean into a third definition.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def job_candidate_grade(
    *,
    n_expected: int,
    n_cells: int,
    n_complete: int,
    n_collapsed: int = 0,
    n_broken: int = 0,
) -> bool:
    if int(n_expected) <= 0:
        return False
    if int(n_cells) != int(n_expected):
        return False
    if int(n_complete) != int(n_expected):
        return False
    if int(n_collapsed) > 0 or int(n_broken) > 0:
        return False
    return True


def cells_candidate_counts(cells: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    n_complete = 0
    n_collapsed = 0
    n_broken = 0
    for cell in cells:
        if not isinstance(cell, Mapping):
            continue
        broken = (
            cell.get("path_fallback") == "path_broken"
            or cell.get("eval_path") == "path_broken"
        )
        fallback = str(cell.get("path_fallback") or "")
        collapsed = "path_collapsed" in fallback or str(
            cell.get("skip_reason") or ""
        ).startswith("unique_unsupported")
        if broken:
            n_broken += 1
        if collapsed:
            n_collapsed += 1
        if cell.get("daily_path_complete") is True and not broken and not collapsed:
            n_complete += 1
    return {
        "n_cells": len(list(cells)),
        "n_complete": n_complete,
        "n_collapsed": n_collapsed,
        "n_broken": n_broken,
    }
