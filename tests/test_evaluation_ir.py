"""Golden vectors for the versioned Evaluation IR."""
from __future__ import annotations

import pytest

from research.candidate_policy import job_candidate_grade
from research.evaluation_ir import (
    CANONICAL_FIELDS,
    EVALUATION_IR_VERSION,
    decode_evaluation_ir,
    encode_evaluation_ir,
    job_candidate_grade as ir_grade,
)


def test_canonical_fields_and_version() -> None:
    assert EVALUATION_IR_VERSION == "evaluation-ir/v1"
    assert CANONICAL_FIELDS == (
        "return",
        "cost",
        "turnover",
        "coverage",
        "collapsed",
        "candidate",
        "failure_reason",
    )
    assert ir_grade is job_candidate_grade


def test_partial_job_candidate_false() -> None:
    payload = encode_evaluation_ir(
        return_value=0.12,
        cost=0.01,
        turnover=0.40,
        coverage=0.75,
        collapsed=0,
        n_expected=4,
        n_cells=4,
        n_complete=3,
    )
    assert payload["version"] == EVALUATION_IR_VERSION
    assert payload["candidate"] is False
    assert payload["failure_reason"] == "partial_incomplete"
    decoded = decode_evaluation_ir(payload)
    assert decoded.candidate is False
    assert decoded.return_value == 0.12


def test_complete_job_candidate_true() -> None:
    payload = encode_evaluation_ir(
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
    )
    assert payload["candidate"] is True
    assert payload["failure_reason"] is None
    decoded = decode_evaluation_ir(payload)
    assert decoded.candidate is True
    assert decoded.to_dict()["candidate"] is True


def test_collapsed_or_broken_or_empty_expected_is_false() -> None:
    assert (
        encode_evaluation_ir(
            n_expected=4, n_cells=4, n_complete=4, n_collapsed=1
        )["candidate"]
        is False
    )
    assert (
        encode_evaluation_ir(
            n_expected=4, n_cells=4, n_complete=4, n_broken=1
        )["candidate"]
        is False
    )
    assert (
        encode_evaluation_ir(n_expected=0, n_cells=0, n_complete=0)["candidate"]
        is False
    )
    assert (
        encode_evaluation_ir(n_expected=4, n_cells=3, n_complete=3)["candidate"]
        is False
    )


def test_unknown_field_rejected() -> None:
    good = encode_evaluation_ir(
        return_value=0.0,
        cost=0.0,
        turnover=0.0,
        coverage=1.0,
        collapsed=0,
        n_expected=2,
        n_cells=2,
        n_complete=2,
    )
    with pytest.raises(ValueError, match="unknown field"):
        decode_evaluation_ir({**good, "go": True})
    with pytest.raises(ValueError, match="unknown field"):
        decode_evaluation_ir({**good, "operator_override": True})


def test_smuggled_candidate_true_on_partial_rejected() -> None:
    partial = encode_evaluation_ir(
        n_expected=4, n_cells=4, n_complete=3
    )
    forged = dict(partial)
    forged["candidate"] = True
    with pytest.raises(ValueError, match="job_candidate_grade"):
        decode_evaluation_ir(forged)
