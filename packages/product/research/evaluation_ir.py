"""Versioned Evaluation IR — single evaluation authority.

Field names and types: ``specs/evaluation_ir/schema.json`` (codec SoT).
Encode/decode validate against that schema. Unknown fields fail.
``version`` must be ``evaluation-ir/v1``.

Candidate is not a free boolean and is not a second Python/TS policy copy.
Encode always calls ``job_candidate_grade``. Decode re-grades; a smuggled
``candidate: true`` cannot pass a partial job. The schema does not encode
the grade predicate.

Readers of daily-path job dicts must not trust a stored ``candidate_grade``
boolean. Use ``candidate_from_job_artifact``: decode/re-grade ``evaluation_ir``
when present, else ``job_candidate_grade`` on counts.

Shared golden: ``specs/evaluation_ir/golden.jsonl`` is emitted by
``emit_evaluation_ir_golden`` (encoder-owned; not a second candidate policy).

Worker ``ALLOWED_FIELDS`` is emitted from this schema into
``evaluation_ir_allowed_fields.generated.ts``. Do not hand-edit that file.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from qp_paths import repo_root
from research.candidate_policy import job_candidate_grade

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

SCHEMA_REL = Path("specs") / "evaluation_ir" / "schema.json"
GOLDEN_REL = Path("specs") / "evaluation_ir" / "golden.jsonl"
ALLOWED_FIELDS_TS_REL = (
    Path("platform")
    / "workers"
    / "research-mass-eval"
    / "src"
    / "evaluation_ir_allowed_fields.generated.ts"
)

_SUPPORTED_SCHEMA_DIALECTS = frozenset(
    {
        "http://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft/2020-12/schema",
    }
)
_SCHEMA_ROOT_KEYS = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "title",
        "description",
        "type",
        "additionalProperties",
        "required",
        "properties",
    }
)
_SCHEMA_PROP_KEYS = frozenset(
    {"type", "const", "$comment", "description", "title"}
)

_SCHEMA: dict[str, Any] | None = None


def _schema_path(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / SCHEMA_REL


def _check_schema_document(schema: Mapping[str, Any]) -> None:
    dialect = schema.get("$schema")
    if dialect not in _SUPPORTED_SCHEMA_DIALECTS:
        raise ValueError(f"unsupported Evaluation IR schema dialect: {dialect!r}")
    extra = sorted(set(schema) - _SCHEMA_ROOT_KEYS)
    if extra:
        raise ValueError(f"Evaluation IR schema unknown keyword(s): {extra}")
    if schema.get("type") != "object":
        raise ValueError("Evaluation IR schema type must be object")
    if schema.get("additionalProperties") is not False:
        raise ValueError("Evaluation IR schema must set additionalProperties false")
    properties = schema.get("properties")
    if not isinstance(properties, Mapping) or not properties:
        raise ValueError("Evaluation IR schema properties must be a non-empty object")
    for name, spec in properties.items():
        if spec is True:
            continue
        if not isinstance(spec, Mapping):
            raise ValueError(f"Evaluation IR schema property {name!r} must be an object")
        unknown = sorted(set(spec) - _SCHEMA_PROP_KEYS)
        if unknown:
            raise ValueError(
                f"Evaluation IR schema property {name!r} unknown keyword(s): {unknown}"
            )
    version_spec = properties.get("version")
    if not isinstance(version_spec, Mapping) or "const" not in version_spec:
        raise ValueError("Evaluation IR schema version must declare const")
    required = schema.get("required")
    if not isinstance(required, list) or any(not isinstance(x, str) for x in required):
        raise ValueError("Evaluation IR schema required must be a list of strings")
    missing_canon = [name for name in CANONICAL_FIELDS if name not in properties]
    if missing_canon:
        raise ValueError(f"Evaluation IR schema missing canonical field(s): {missing_canon}")
    missing_grade = [name for name in _GRADE_FIELDS if name not in properties]
    if missing_grade:
        raise ValueError(f"Evaluation IR schema missing grade field(s): {missing_grade}")
    candidate_spec = properties.get("candidate")
    if isinstance(candidate_spec, Mapping) and "const" in candidate_spec:
        raise ValueError("Evaluation IR schema must not const-bind candidate")


def load_evaluation_ir_schema(*, root: Path | None = None) -> dict[str, Any]:
    """Load the codec SoT JSON Schema. Cached for the repo root."""
    global _SCHEMA
    if _SCHEMA is not None and root is None:
        return _SCHEMA
    path = _schema_path(root=root)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Evaluation IR schema must be an object")
    _check_schema_document(raw)
    if root is None:
        _SCHEMA = raw
    return raw


def _schema_type_ok(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, Mapping) and not isinstance(value, (str, bytes))
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise ValueError(f"unsupported JSON Schema type {type_name!r}")


def _check_schema_value(value: Any, spec: Mapping[str, Any] | bool, label: str) -> None:
    if spec is True:
        return
    declared = spec.get("type")
    if declared is not None:
        names = (declared,) if isinstance(declared, str) else tuple(declared)
        if not any(_schema_type_ok(value, name) for name in names):
            if names == ("integer",):
                raise ValueError(f"{label} must be an integer")
            raise ValueError(f"{label} must be {' or '.join(names)}")
    if "const" in spec and value != spec["const"]:
        if label == "version":
            raise ValueError(f"unsupported Evaluation IR version: {value!r}")
        raise ValueError(f"{label} must be {spec['const']!r}")


def validate_evaluation_ir_schema(payload: Any) -> None:
    """Closed-schema check from ``schema.json``. Does not grade candidate."""
    schema = load_evaluation_ir_schema()
    if not isinstance(payload, Mapping):
        raise ValueError("EvaluationIR must be an object")
    properties: Mapping[str, Any] = schema["properties"]
    unknown = sorted(set(payload) - set(properties))
    if unknown:
        raise ValueError(f"EvaluationIR unknown field(s): {unknown}")
    missing = [name for name in schema["required"] if name not in payload]
    if missing:
        raise ValueError(f"EvaluationIR missing {missing}")
    for name, spec in properties.items():
        if name not in payload:
            continue
        _check_schema_value(payload[name], spec, name)


EVALUATION_IR_SCHEMA: dict[str, Any] = load_evaluation_ir_schema()
EVALUATION_IR_VERSION: str = str(
    EVALUATION_IR_SCHEMA["properties"]["version"]["const"]
)
ALLOWED_FIELDS: frozenset[str] = frozenset(EVALUATION_IR_SCHEMA["properties"])


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
    encoded = {
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
    validate_evaluation_ir_schema(encoded)
    return encoded


def decode_evaluation_ir(payload: Mapping[str, Any]) -> EvaluationIR:
    """Closed-schema decode. Unknown fields fail. Candidate is re-graded."""
    validate_evaluation_ir_schema(payload)
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


def _eval_ir_root(*, root: Path | None = None) -> Path:
    if root is not None:
        return root
    cwd = Path.cwd().resolve()
    if (cwd / "pyproject.toml").is_file() and (cwd / "tests").is_dir():
        return cwd
    return repo_root()


def write_evaluation_ir_golden(*, root: Path | None = None) -> Path:
    path = _eval_ir_root(root=root) / GOLDEN_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_evaluation_ir_golden(), encoding="utf-8")
    return path


def evaluation_ir_allowed_fields_ts_path(*, root: Path | None = None) -> Path:
    return _eval_ir_root(root=root) / ALLOWED_FIELDS_TS_REL


def evaluation_ir_allowed_fields_ts_source(*, root: Path | None = None) -> str:
    """Emit Worker ALLOWED_FIELDS from schema.json properties. Not a grade policy."""
    schema = load_evaluation_ir_schema(root=_eval_ir_root(root=root))
    properties = schema["properties"]
    if not isinstance(properties, Mapping) or not properties:
        raise ValueError("Evaluation IR schema properties must be a non-empty object")
    fields = [str(name) for name in properties]
    inner = ",\n".join(f"  {json.dumps(name)}" for name in fields)
    return (
        "/// Generated by research.evaluation_ir from specs/evaluation_ir/schema.json. "
        "Do not edit by hand.\n"
        "/// Codec field SoT: schema.json properties. Worker decode uses this set "
        "(additionalProperties: false).\n"
        "\n"
        "export const ALLOWED_FIELDS: ReadonlySet<string> = new Set([\n"
        f"{inner},\n"
        "]);\n"
    )


def write_evaluation_ir_allowed_fields_ts(*, root: Path | None = None) -> Path:
    path = evaluation_ir_allowed_fields_ts_path(root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(evaluation_ir_allowed_fields_ts_source(root=root), encoding="utf-8")
    return path


def assert_evaluation_ir_allowed_fields_ts_frozen(*, root: Path | None = None) -> None:
    path = evaluation_ir_allowed_fields_ts_path(root=root)
    expected = evaluation_ir_allowed_fields_ts_source(root=root)
    if not path.is_file():
        raise ValueError(
            f"Evaluation IR ALLOWED_FIELDS artifact missing: {path}. "
            "Regenerate: python -m research.evaluation_ir"
        )
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        raise ValueError(
            "evaluation_ir_allowed_fields.generated.ts drifted from schema.json. "
            "Regenerate: python -m research.evaluation_ir"
        )


__all__ = [
    "ALLOWED_FIELDS",
    "ALLOWED_FIELDS_TS_REL",
    "CANONICAL_FIELDS",
    "EVALUATION_IR_SCHEMA",
    "EVALUATION_IR_VERSION",
    "EvaluationIR",
    "GOLDEN_REL",
    "SCHEMA_REL",
    "assert_evaluation_ir_allowed_fields_ts_frozen",
    "candidate_from_job_artifact",
    "decode_evaluation_ir",
    "dumps_evaluation_ir_golden",
    "emit_evaluation_ir_golden",
    "emit_golden_vector",
    "encode_evaluation_ir",
    "evaluation_ir_allowed_fields_ts_path",
    "evaluation_ir_allowed_fields_ts_source",
    "job_candidate_grade",
    "load_evaluation_ir_schema",
    "validate_evaluation_ir_schema",
    "write_evaluation_ir_allowed_fields_ts",
    "write_evaluation_ir_golden",
]


if __name__ == "__main__":
    print(write_evaluation_ir_golden())
    print(write_evaluation_ir_allowed_fields_ts())
