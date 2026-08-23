"""Golden vectors for the versioned Evaluation IR."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from research import evaluation_ir as ir_module
from research import evaluation_ir_emit as emit_module
from research.candidate_policy import job_candidate_grade
from research.evaluation_ir import (
    ALLOWED_FIELDS,
    ENCODE_KEYS,
    EVALUATION_IR_VERSION,
    SCHEMA_REL,
    assert_evaluation_ir_allowed_fields_ts_frozen,
    assert_evaluation_ir_codec_py_frozen,
    assert_evaluation_ir_codec_ts_frozen,
    assert_evaluation_ir_encode_keys_match_schema,
    candidate_from_job_artifact,
    decode_evaluation_ir,
    dumps_evaluation_ir_golden,
    emit_evaluation_ir_golden,
    encode_evaluation_ir,
    evaluation_ir_allowed_fields_ts_path,
    evaluation_ir_allowed_fields_ts_source,
    evaluation_ir_codec_py_path,
    evaluation_ir_codec_py_source,
    evaluation_ir_codec_ts_path,
    evaluation_ir_codec_ts_source,
    evaluation_ir_encode_keys,
    evaluation_ir_ts_encode_keys,
    evaluation_ir_ts_path,
    job_candidate_grade as ir_grade,
    load_evaluation_ir_schema,
    validate_evaluation_ir_schema,
)

GOLDEN_PATH = (
    Path(__file__).resolve().parents[1] / "specs" / "evaluation_ir" / "golden.jsonl"
)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / SCHEMA_REL
_GRADE_KEYS = ("n_expected", "n_cells", "n_complete", "n_collapsed", "n_broken")


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


def _counts(payload: Mapping[str, Any]) -> dict[str, int]:
    return {key: int(payload[key]) for key in _GRADE_KEYS}


def test_canonical_fields_and_version() -> None:
    assert EVALUATION_IR_VERSION == "evaluation-ir/v1"
    assert ir_grade is job_candidate_grade


def test_encode_keys_match_schema_properties() -> None:
    schema_keys = tuple(load_evaluation_ir_schema()["properties"])
    assert evaluation_ir_encode_keys() == schema_keys
    assert evaluation_ir_ts_encode_keys() == schema_keys
    assert set(evaluation_ir_encode_keys()) == ALLOWED_FIELDS
    codec_py = evaluation_ir_codec_py_source()
    assert "ENCODE_KEYS" in codec_py
    for key in schema_keys:
        assert json.dumps(key) in codec_py
    assert ENCODE_KEYS == schema_keys
    assert set(ENCODE_KEYS) == ALLOWED_FIELDS
    gen = ir_module._CODEC_PY
    assert ir_module.encode_evaluation_ir is gen.encode_evaluation_ir
    assert ir_module.decode_evaluation_ir is gen.decode_evaluation_ir
    assert ir_module.evaluation_ir_codec_ts_source is emit_module.evaluation_ir_codec_ts_source
    assert ir_module.evaluation_ir_codec_py_source is emit_module.evaluation_ir_codec_py_source
    assert (
        ir_module.evaluation_ir_allowed_fields_ts_source
        is emit_module.evaluation_ir_allowed_fields_ts_source
    )
    assert ir_module.assert_evaluation_ir_codec_ts_frozen is emit_module.assert_evaluation_ir_codec_ts_frozen
    assert ir_module.assert_evaluation_ir_codec_py_frozen is emit_module.assert_evaluation_ir_codec_py_frozen
    assert (
        ir_module.assert_evaluation_ir_allowed_fields_ts_frozen
        is emit_module.assert_evaluation_ir_allowed_fields_ts_frozen
    )
    assert tuple(gen.ENCODE_KEYS) == schema_keys
    assert_evaluation_ir_encode_keys_match_schema()
    worker_src = evaluation_ir_ts_path().read_text(encoding="utf-8")
    codec_src = evaluation_ir_codec_ts_path().read_text(encoding="utf-8")
    assert "CANONICAL_FIELDS" not in worker_src
    assert "CANONICAL_FIELDS" not in codec_src
    assert not hasattr(ir_module, "CANONICAL_FIELDS")
    assert "export function encodeEvaluationIR" not in worker_src
    assert "export function decodeEvaluationIR" not in worker_src
    drifted = codec_src.replace(
        "failure_reason: reason,",
        "failure_reason: reason,\n    extra_encode_key: true,",
        1,
    )
    with pytest.raises(ValueError, match="encode keys drifted"):
        assert_evaluation_ir_encode_keys_match_schema(ts_src=drifted)


def test_schema_is_codec_sot() -> None:
    schema = load_evaluation_ir_schema()
    assert SCHEMA_PATH.is_file()
    assert schema["$schema"] in {
        "http://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft/2020-12/schema",
    }
    assert schema["additionalProperties"] is False
    assert schema["properties"]["version"]["const"] == "evaluation-ir/v1"
    assert EVALUATION_IR_VERSION == schema["properties"]["version"]["const"]
    assert ALLOWED_FIELDS == frozenset(schema["properties"])
    generated = evaluation_ir_allowed_fields_ts_source()
    path = evaluation_ir_allowed_fields_ts_path()
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == generated
    header = generated.split("export const", 1)[0]
    assert "Do not edit by hand" in header
    assert "schema.json" in header
    assert_evaluation_ir_allowed_fields_ts_frozen()
    codec_generated = evaluation_ir_codec_ts_source()
    codec_path = evaluation_ir_codec_ts_path()
    assert codec_path.is_file()
    assert codec_path.read_text(encoding="utf-8") == codec_generated
    codec_header = codec_generated.split("export const", 1)[0]
    assert "Do not edit by hand" in codec_header
    assert "schema.json" in codec_header
    assert "jobCandidateGrade" in codec_generated
    assert "export function encodeEvaluationIR" in codec_generated
    assert "export function decodeEvaluationIR" in codec_generated
    assert_evaluation_ir_codec_ts_frozen()
    codec_py_generated = evaluation_ir_codec_py_source()
    codec_py_path = evaluation_ir_codec_py_path()
    assert codec_py_path.is_file()
    assert codec_py_path.read_text(encoding="utf-8") == codec_py_generated
    codec_py_header = codec_py_generated.split("EVALUATION_IR_VERSION", 1)[0]
    assert "Do not edit by hand" in codec_py_header
    assert "schema.json" in codec_py_header
    assert "job_candidate_grade" in codec_py_generated
    assert "def encode_evaluation_ir" in codec_py_generated
    assert "def decode_evaluation_ir" in codec_py_generated
    assert ENCODE_KEYS == tuple(schema["properties"])
    assert ALLOWED_FIELDS == frozenset(schema["properties"])
    assert_evaluation_ir_codec_py_frozen()
    worker = (
        Path(__file__).resolve().parents[1]
        / "platform"
        / "workers"
        / "research-mass-eval"
        / "src"
        / "evaluation_ir.ts"
    )
    worker_src = worker.read_text(encoding="utf-8")
    assert 'from "./evaluation_ir_allowed_fields.generated"' in worker_src
    assert 'from "./evaluation_ir_codec.generated"' in worker_src
    assert "CANONICAL_FIELDS" not in worker_src
    assert "export function encodeEvaluationIR" not in worker_src
    assert "export function decodeEvaluationIR" not in worker_src
    assert "jobCandidateGrade(" in codec_generated
    assert evaluation_ir_ts_path() == worker
    assert_evaluation_ir_encode_keys_match_schema()
    assert "const" not in schema["properties"]["candidate"]
    assert "if" not in schema
    assert "then" not in schema
    assert "allOf" not in schema


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


def test_golden_is_encoder_owned() -> None:
    emitted = emit_evaluation_ir_golden()
    assert _load_golden() == emitted
    assert GOLDEN_PATH.read_text(encoding="utf-8") == dumps_evaluation_ir_golden()
    ids = {row["id"] for row in emitted}
    assert {
        "n_expected_zero",
        "n_cells_mismatch",
        "collapsed",
        "broken",
        "smuggled_candidate_partial",
    } <= ids


@pytest.mark.parametrize("row", _load_golden(), ids=lambda row: row["id"])
def test_shared_golden_vectors(row: dict[str, Any]) -> None:
    if row["op"] == "decode":
        payload = row["payload"]
        with pytest.raises(ValueError, match=row["expect_error"]):
            decode_evaluation_ir(payload)
        grade = job_candidate_grade(**_counts(payload))
        if payload.get("candidate") is True and grade is False:
            assert row["expect_error"] == "job_candidate_grade"
        return
    encoded = encode_evaluation_ir(**row["args"])
    expect = row["expect"]
    grade = job_candidate_grade(**_counts(encoded))
    assert encoded["candidate"] is grade
    assert encoded["candidate"] is expect["candidate"]
    assert encoded["failure_reason"] == expect["failure_reason"]
    decoded = decode_evaluation_ir(encoded)
    assert decoded.candidate is grade
    assert decoded.failure_reason == expect["failure_reason"]
    assert decoded.to_dict() == encoded
    assert _canonical_digest(encoded) == _canonical_digest(decoded.to_dict())
    if grade is False:
        forged = dict(encoded)
        forged["candidate"] = True
        with pytest.raises(ValueError, match="job_candidate_grade"):
            decode_evaluation_ir(forged)


def test_encode_output_schema_validates() -> None:
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
    validate_evaluation_ir_schema(payload)
    with pytest.raises(ValueError, match="unknown field"):
        validate_evaluation_ir_schema({**payload, "go": True})
    with pytest.raises(ValueError, match="unsupported Evaluation IR version"):
        validate_evaluation_ir_schema({**payload, "version": "evaluation-ir/v0"})


@pytest.mark.parametrize("row", _load_golden(), ids=lambda row: row["id"])
def test_golden_rows_schema_validate(row: dict[str, Any]) -> None:
    if row["op"] == "decode":
        payload = row["payload"]
        extra = set(payload) - ALLOWED_FIELDS
        if extra:
            with pytest.raises(ValueError, match="unknown field"):
                validate_evaluation_ir_schema(payload)
            return
        validate_evaluation_ir_schema(payload)
        return
    encoded = encode_evaluation_ir(**row["args"])
    validate_evaluation_ir_schema(encoded)
