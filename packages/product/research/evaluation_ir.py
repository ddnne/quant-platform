"""Versioned Evaluation IR — single evaluation authority.

Candidate is not a free boolean and is not a second Python/TS policy copy.
Encode always calls ``job_candidate_grade``. Decode rejects unknown fields
and re-grades; a smuggled ``candidate: true`` cannot pass a partial job.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from research.candidate_policy import job_candidate_grade

EVALUATION_IR_VERSION: str = "evaluation-ir/v1"

CANONICAL_FIELDS: tuple[str, ...] = (
    "return",
    "cost",
    "turnover",
    "coverage",
    "collapsed",
    "candidate",
    "failure_reason",
)

_GRADE_FIELDS: tuple[str, ...] = (
    "n_expected",
    "n_cells",
    "n_complete",
    "n_collapsed",
    "n_broken",
)

ALLOWED_FIELDS: frozenset[str] = frozenset(
    ("version",) + CANONICAL_FIELDS + _GRADE_FIELDS
)


def _grade_failure_reason(
    *,
    n_expected: int,
    n_cells: int,
    n_complete: int,
    n_collapsed: int,
    n_broken: int,
) -> str | None:
    if int(n_expected) <= 0:
        return "n_expected_nonpositive"
    if int(n_cells) != int(n_expected):
        return "n_cells_mismatch"
    if int(n_complete) != int(n_expected):
        return "partial_incomplete"
    if int(n_collapsed) > 0:
        return "collapsed"
    if int(n_broken) > 0:
        return "broken"
    return None


def _as_int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc


@dataclass(frozen=True)
class EvaluationIR:
    """Closed-schema evaluation record. ``candidate`` is graded, not declared."""

    return_value: Any
    cost: Any
    turnover: Any
    coverage: Any
    collapsed: Any
    candidate: bool
    failure_reason: str | None
    n_expected: int
    n_cells: int
    n_complete: int
    n_collapsed: int = 0
    n_broken: int = 0
    version: str = EVALUATION_IR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return encode_evaluation_ir(
            return_value=self.return_value,
            cost=self.cost,
            turnover=self.turnover,
            coverage=self.coverage,
            collapsed=self.collapsed,
            n_expected=self.n_expected,
            n_cells=self.n_cells,
            n_complete=self.n_complete,
            n_collapsed=self.n_collapsed,
            n_broken=self.n_broken,
            failure_reason=self.failure_reason,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvaluationIR":
        return decode_evaluation_ir(payload)


def encode_evaluation_ir(
    *,
    return_value: Any = None,
    cost: Any = None,
    turnover: Any = None,
    coverage: Any = None,
    collapsed: Any = 0,
    n_expected: int,
    n_cells: int,
    n_complete: int,
    n_collapsed: int = 0,
    n_broken: int = 0,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    """Encode canonical fields. ``candidate`` is ``job_candidate_grade`` only."""
    n_expected_i = _as_int(n_expected, "n_expected")
    n_cells_i = _as_int(n_cells, "n_cells")
    n_complete_i = _as_int(n_complete, "n_complete")
    n_collapsed_i = _as_int(n_collapsed, "n_collapsed")
    n_broken_i = _as_int(n_broken, "n_broken")
    candidate = job_candidate_grade(
        n_expected=n_expected_i,
        n_cells=n_cells_i,
        n_complete=n_complete_i,
        n_collapsed=n_collapsed_i,
        n_broken=n_broken_i,
    )
    graded_reason = _grade_failure_reason(
        n_expected=n_expected_i,
        n_cells=n_cells_i,
        n_complete=n_complete_i,
        n_collapsed=n_collapsed_i,
        n_broken=n_broken_i,
    )
    if candidate:
        reason: str | None = None
    elif failure_reason:
        reason = str(failure_reason)
    else:
        reason = graded_reason
    return {
        "version": EVALUATION_IR_VERSION,
        "return": return_value,
        "cost": cost,
        "turnover": turnover,
        "coverage": coverage,
        "collapsed": collapsed,
        "candidate": candidate,
        "failure_reason": reason,
        "n_expected": n_expected_i,
        "n_cells": n_cells_i,
        "n_complete": n_complete_i,
        "n_collapsed": n_collapsed_i,
        "n_broken": n_broken_i,
    }


def decode_evaluation_ir(payload: Mapping[str, Any]) -> EvaluationIR:
    """Closed-schema decode. Unknown fields fail. Candidate is re-graded."""
    if not isinstance(payload, Mapping):
        raise ValueError("EvaluationIR must be an object")
    unknown = sorted(set(payload) - ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"EvaluationIR unknown field(s): {unknown}")
    version = str(payload.get("version") or EVALUATION_IR_VERSION)
    if version != EVALUATION_IR_VERSION:
        raise ValueError(f"unsupported Evaluation IR version: {version!r}")
    missing = [name for name in ("n_expected", "n_cells", "n_complete") if name not in payload]
    if missing:
        raise ValueError(f"EvaluationIR missing {missing}")
    n_expected = _as_int(payload["n_expected"], "n_expected")
    n_cells = _as_int(payload["n_cells"], "n_cells")
    n_complete = _as_int(payload["n_complete"], "n_complete")
    n_collapsed = _as_int(payload.get("n_collapsed", 0), "n_collapsed")
    n_broken = _as_int(payload.get("n_broken", 0), "n_broken")
    candidate = job_candidate_grade(
        n_expected=n_expected,
        n_cells=n_cells,
        n_complete=n_complete,
        n_collapsed=n_collapsed,
        n_broken=n_broken,
    )
    stored = payload.get("candidate")
    if stored is not None and bool(stored) is not candidate:
        raise ValueError("candidate must equal job_candidate_grade")
    reason = payload.get("failure_reason")
    if candidate:
        failure_reason = None
    elif reason is None or reason == "":
        failure_reason = _grade_failure_reason(
            n_expected=n_expected,
            n_cells=n_cells,
            n_complete=n_complete,
            n_collapsed=n_collapsed,
            n_broken=n_broken,
        )
    else:
        failure_reason = str(reason)
    return EvaluationIR(
        return_value=payload.get("return"),
        cost=payload.get("cost"),
        turnover=payload.get("turnover"),
        coverage=payload.get("coverage"),
        collapsed=payload.get("collapsed", 0),
        candidate=candidate,
        failure_reason=failure_reason,
        n_expected=n_expected,
        n_cells=n_cells,
        n_complete=n_complete,
        n_collapsed=n_collapsed,
        n_broken=n_broken,
        version=EVALUATION_IR_VERSION,
    )


__all__ = [
    "ALLOWED_FIELDS",
    "CANONICAL_FIELDS",
    "EVALUATION_IR_VERSION",
    "EvaluationIR",
    "decode_evaluation_ir",
    "encode_evaluation_ir",
    "job_candidate_grade",
]
