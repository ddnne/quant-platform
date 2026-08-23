"""Golden vectors for the versioned Evaluation IR."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from research.candidate_policy import job_candidate_grade
from research.evaluation_ir import (
    CANONICAL_FIELDS,
    EVALUATION_IR_VERSION,
    candidate_from_job_artifact,
    decode_evaluation_ir,
    encode_evaluation_ir,
    job_candidate_grade as ir_grade,
)

GOLDEN_PATH = (
    Path(__file__).resolve().parents[1] / "specs" / "evaluation_ir" / "golden.jsonl"
)


def _load_golden() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


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


def test_encode_candidate_is_job_candidate_grade() -> None:
    """cf_daily_path_job assigns candidate_grade from encode_evaluation_ir."""
    complete = dict(
        n_expected=4, n_cells=4, n_complete=4, n_collapsed=0, n_broken=0
    )
    partial = dict(n_expected=4, n_cells=4, n_complete=3)
    assert encode_evaluation_ir(**complete)["candidate"] is job_candidate_grade(
        **complete
    )
    assert encode_evaluation_ir(**partial)["candidate"] is job_candidate_grade(
        **partial
    )


def test_job_artifact_forged_candidate_true_with_partial_ir_rejected() -> None:
    """Stored candidate_grade true cannot pass; partial IR candidate is re-graded."""
    partial = encode_evaluation_ir(n_expected=4, n_cells=4, n_complete=3)
    forged_ir = dict(partial)
    forged_ir["candidate"] = True
    with pytest.raises(ValueError, match="job_candidate_grade"):
        candidate_from_job_artifact(
            {"candidate_grade": True, "evaluation_ir": forged_ir}
        )
    honest_partial = {
        "candidate_grade": True,
        "evaluation_ir": partial,
        "go": False,
        "survived": False,
        "promote_as_main": False,
    }
    assert candidate_from_job_artifact(honest_partial) is False


def test_job_artifact_missing_ir_falls_back_to_counts() -> None:
    complete_counts = dict(
        n_expected=4, n_cells=4, n_complete=4, n_collapsed=0, n_broken=0
    )
    partial_counts = dict(n_expected=4, n_cells=4, n_complete=3)
    assert (
        candidate_from_job_artifact(
            {**complete_counts, "candidate_grade": False}
        )
        is job_candidate_grade(**complete_counts)
        is True
    )
    assert (
        candidate_from_job_artifact(
            {**partial_counts, "candidate_grade": True}
        )
        is job_candidate_grade(**partial_counts)
        is False
    )


def test_job_artifact_unknown_ir_field_rejected() -> None:
    good = encode_evaluation_ir(
        n_expected=2, n_cells=2, n_complete=2
    )
    with pytest.raises(ValueError, match="unknown field"):
        candidate_from_job_artifact(
            {"candidate_grade": True, "evaluation_ir": {**good, "go": True}}
        )


@pytest.mark.parametrize("row", _load_golden(), ids=lambda row: row["id"])
def test_shared_golden_vectors(row: dict[str, Any]) -> None:
    if row["op"] == "decode":
        with pytest.raises(ValueError, match=row["expect_error"]):
            decode_evaluation_ir(row["payload"])
        return
    encoded = encode_evaluation_ir(**row["args"])
    expect = row["expect"]
    assert encoded["candidate"] is expect["candidate"]
    assert encoded["failure_reason"] == expect["failure_reason"]
    decoded = decode_evaluation_ir(encoded)
    assert decoded.candidate is expect["candidate"]
    assert decoded.failure_reason == expect["failure_reason"]
    assert _canonical_digest(encoded) == _canonical_digest(decoded.to_dict())
