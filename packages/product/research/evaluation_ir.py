"""Versioned Evaluation IR — single evaluation authority.

Candidate is not a free boolean and is not a second Python/TS policy copy.
Encode always calls ``job_candidate_grade``. Decode rejects unknown fields
and re-grades; a smuggled ``candidate: true`` cannot pass a partial job.

Readers of daily-path job dicts must not trust a stored ``candidate_grade``
boolean. Use ``candidate_from_job_artifact``: decode/re-grade ``evaluation_ir``
when present, else ``job_candidate_grade`` on counts.

Shared golden: ``specs/evaluation_ir/golden.jsonl`` is emitted by
``emit_evaluation_ir_golden`` (encoder-owned; not a second candidate policy).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from qp_paths import repo_root
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

GOLDEN_REL = Path("specs") / "evaluation_ir" / "golden.jsonl"


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


def candidate_from_job_artifact(job: Mapping[str, Any]) -> bool:
    """Re-grade a daily-path job dict. Never trust stored ``candidate_grade``."""
    if not isinstance(job, Mapping):
        raise ValueError("job artifact must be an object")
    if "evaluation_ir" in job:
        decoded = decode_evaluation_ir(job["evaluation_ir"])
        if isinstance(decoded, Mapping):
            return bool(decoded["candidate"])
        return bool(decoded.candidate)
    return job_candidate_grade(
        n_expected=_as_int(job.get("n_expected", 0), "n_expected"),
        n_cells=_as_int(job.get("n_cells", 0), "n_cells"),
        n_complete=_as_int(job.get("n_complete", 0), "n_complete"),
        n_collapsed=_as_int(job.get("n_collapsed", 0), "n_collapsed"),
        n_broken=_as_int(job.get("n_broken", 0), "n_broken"),
    )


def emit_golden_vector(
    *,
    vector_id: str,
    op: str = "roundtrip",
    forge: Mapping[str, Any] | None = None,
    expect_error: str | None = None,
    **args: Any,
) -> dict[str, Any]:
    """One golden row. ``candidate`` comes from encode, not a hand boolean."""
    encoded = encode_evaluation_ir(**args)
    if op == "decode":
        payload = dict(encoded)
        if forge:
            payload.update(dict(forge))
        if not expect_error:
            raise ValueError("decode golden rows require expect_error")
        return {
            "id": vector_id,
            "op": "decode",
            "payload": payload,
            "expect_error": str(expect_error),
        }
    if forge:
        raise ValueError("forge is only valid for decode golden rows")
    return {
        "id": vector_id,
        "op": "roundtrip",
        "args": dict(args),
        "expect": {
            "candidate": encoded["candidate"],
            "failure_reason": encoded["failure_reason"],
        },
    }


def emit_evaluation_ir_golden() -> list[dict[str, Any]]:
    """Encoder-owned golden corpus. Not a second candidate policy."""
    return [
        emit_golden_vector(
            vector_id="complete_pass",
            return_value=0.08,
            cost=0.02,
            turnover=0.15,
            coverage=1.0,
            collapsed=0,
            n_expected=4,
            n_cells=4,
            n_complete=4,
            n_collapsed=0,
            n_broken=0,
        ),
        emit_golden_vector(
            vector_id="partial_cells",
            return_value=0.12,
            cost=0.01,
            turnover=0.4,
            coverage=0.75,
            collapsed=0,
            n_expected=4,
            n_cells=4,
            n_complete=3,
        ),
        emit_golden_vector(
            vector_id="n_expected_zero",
            n_expected=0,
            n_cells=0,
            n_complete=0,
        ),
        emit_golden_vector(
            vector_id="collapsed",
            n_expected=4,
            n_cells=4,
            n_complete=4,
            n_collapsed=1,
        ),
        emit_golden_vector(
            vector_id="broken",
            n_expected=4,
            n_cells=4,
            n_complete=4,
            n_broken=1,
        ),
        emit_golden_vector(
            vector_id="n_cells_mismatch",
            n_expected=4,
            n_cells=3,
            n_complete=3,
        ),
        emit_golden_vector(
            vector_id="custom_failure_reason",
            n_expected=4,
            n_cells=4,
            n_complete=3,
            failure_reason="operator_halt",
        ),
        emit_golden_vector(
            vector_id="complete_clears_supplied_reason",
            n_expected=2,
            n_cells=2,
            n_complete=2,
            n_collapsed=0,
            n_broken=0,
            failure_reason="should_not_stick",
        ),
        emit_golden_vector(
            vector_id="unknown_field_reject",
            op="decode",
            expect_error="unknown field",
            forge={"go": True},
            return_value=0.0,
            cost=0.0,
            turnover=0.0,
            coverage=1.0,
            collapsed=0,
            n_expected=2,
            n_cells=2,
            n_complete=2,
        ),
        emit_golden_vector(
            vector_id="smuggled_candidate_partial",
            op="decode",
            expect_error="job_candidate_grade",
            forge={"candidate": True},
            n_expected=4,
            n_cells=4,
            n_complete=3,
        ),
    ]


def dumps_evaluation_ir_golden() -> str:
    return "".join(
        json.dumps(row, ensure_ascii=True, separators=(",", ":")) + "\n"
        for row in emit_evaluation_ir_golden()
    )


def write_evaluation_ir_golden(*, root: Path | None = None) -> Path:
    if root is None:
        cwd = Path.cwd().resolve()
        if (cwd / "pyproject.toml").is_file() and (cwd / "tests").is_dir():
            root = cwd
        else:
            root = repo_root()
    path = root / GOLDEN_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_evaluation_ir_golden(), encoding="utf-8")
    return path


__all__ = [
    "ALLOWED_FIELDS",
    "CANONICAL_FIELDS",
    "EVALUATION_IR_VERSION",
    "EvaluationIR",
    "GOLDEN_REL",
    "candidate_from_job_artifact",
    "decode_evaluation_ir",
    "dumps_evaluation_ir_golden",
    "emit_evaluation_ir_golden",
    "emit_golden_vector",
    "encode_evaluation_ir",
    "job_candidate_grade",
    "write_evaluation_ir_golden",
]


if __name__ == "__main__":
    print(write_evaluation_ir_golden())
