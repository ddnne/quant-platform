"""Job-level candidate grade. Partial/unknown is false. Not GO.

Python fanout and Worker daily_path must use the same predicate:
expected cells exist, all complete, none collapsed/broken.

Evaluation IR (research.evaluation_ir) must call this function; do not
copy the boolean into a third definition.
"""
from __future__ import annotations


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

