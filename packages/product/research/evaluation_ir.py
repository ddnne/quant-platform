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
``evaluation_ir_allowed_fields.generated.ts``. Worker encode/decode body is
emitted into ``evaluation_ir_codec.generated.ts``. Do not hand-edit those
files. ``evaluation_ir.ts`` is the façade. Encode keys (Python and Worker)
must equal schema properties; CI freeze-checks that lock. There is no
second field list.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from qp_paths import repo_root
from research.candidate_policy import job_candidate_grade

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
CODEC_TS_REL = (
    Path("platform")
    / "workers"
    / "research-mass-eval"
    / "src"
    / "evaluation_ir_codec.generated.ts"
)
EVALUATION_IR_TS_REL = (
    Path("platform") / "workers" / "research-mass-eval" / "src" / "evaluation_ir.ts"
)
# Worker encode object values. Keys must equal schema.json properties.
_TS_ENCODE_VALUE_EXPR: dict[str, str] = {
    "version": "EVALUATION_IR_VERSION",
    "return": "args.return_value ?? null",
    "cost": "args.cost ?? null",
    "turnover": "args.turnover ?? null",
    "coverage": "args.coverage ?? null",
    "collapsed": "args.collapsed ?? 0",
    "candidate": "candidate",
    "failure_reason": "reason",
    "n_expected": "n_expected",
    "n_cells": "n_cells",
    "n_complete": "n_complete",
    "n_collapsed": "n_collapsed",
    "n_broken": "n_broken",
}
_TS_OBJECT_KEY_RE = re.compile(
    r"""^(?:(?P<quoted>["'])(?P<quoted_key>[A-Za-z_][\w]*)(?P=quoted)|(?P<key>[A-Za-z_][\w]*))\s*(?::|,|$)?"""
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
    """Encode schema properties. ``candidate`` is ``job_candidate_grade`` only."""
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


def evaluation_ir_codec_ts_path(*, root: Path | None = None) -> Path:
    return _eval_ir_root(root=root) / CODEC_TS_REL


def _ts_schema_prop_type(name: str, spec: Mapping[str, Any] | bool) -> str:
    if spec is True:
        return "unknown"
    if not isinstance(spec, Mapping):
        raise ValueError(f"Evaluation IR schema property {name!r} must be an object")
    declared = spec.get("type")
    if declared is None:
        return "unknown"
    names = (declared,) if isinstance(declared, str) else tuple(declared)
    mapping = {
        "string": "string",
        "boolean": "boolean",
        "integer": "number",
        "number": "number",
        "null": "null",
        "object": "Record<string, unknown>",
        "array": "unknown[]",
    }
    parts: list[str] = []
    for type_name in names:
        mapped = mapping.get(str(type_name))
        if mapped is None:
            raise ValueError(
                f"Evaluation IR schema property {name!r} unsupported type {type_name!r}"
            )
        parts.append(mapped)
    return " | ".join(parts)


def _ts_encode_value_exprs(properties: Mapping[str, Any]) -> list[tuple[str, str]]:
    names = [str(name) for name in properties]
    missing = [name for name in names if name not in _TS_ENCODE_VALUE_EXPR]
    extra = sorted(set(_TS_ENCODE_VALUE_EXPR) - set(names))
    if missing or extra:
        raise ValueError(
            "TS encode value map must equal schema.json properties: "
            f"missing={missing} extra={extra}"
        )
    return [(name, _TS_ENCODE_VALUE_EXPR[name]) for name in names]


def evaluation_ir_codec_ts_source(*, root: Path | None = None) -> str:
    """Emit Worker encode/decode from schema.json properties. Not a grade policy."""
    schema = load_evaluation_ir_schema(root=_eval_ir_root(root=root))
    properties = schema["properties"]
    if not isinstance(properties, Mapping) or not properties:
        raise ValueError("Evaluation IR schema properties must be a non-empty object")
    version = properties["version"]["const"]
    if not isinstance(version, str) or not version:
        raise ValueError("Evaluation IR schema version const must be a string")
    payload_fields = "\n".join(
        f"  {name}: {_ts_schema_prop_type(name, spec)};"
        for name, spec in properties.items()
    )
    encode_fields = ",\n".join(
        f"    {name}: {expr}" for name, expr in _ts_encode_value_exprs(properties)
    )
    version_lit = json.dumps(version)
    return (
        "/// Generated by research.evaluation_ir from specs/evaluation_ir/schema.json. "
        "Do not edit by hand.\n"
        "/// Codec field SoT: schema.json properties. Encode object keys are those "
        "properties in order.\n"
        "/// Grade is jobCandidateGrade only. Unknown fields fail. version const "
        f"{version}.\n"
        "\n"
        'import { jobCandidateGrade } from "./candidate";\n'
        'import { ALLOWED_FIELDS } from "./evaluation_ir_allowed_fields.generated";\n'
        "\n"
        f"export const EVALUATION_IR_VERSION = {version_lit};\n"
        "\n"
        "export type EvaluationIRPayload = {\n"
        f"{payload_fields}\n"
        "};\n"
        "\n"
        "export type EvaluationIREncodeArgs = {\n"
        "  return_value?: unknown;\n"
        "  cost?: unknown;\n"
        "  turnover?: unknown;\n"
        "  coverage?: unknown;\n"
        "  collapsed?: unknown;\n"
        "  n_expected: number;\n"
        "  n_cells: number;\n"
        "  n_complete: number;\n"
        "  n_collapsed?: number;\n"
        "  n_broken?: number;\n"
        "  failure_reason?: string | null;\n"
        "};\n"
        "\n"
        "export type EvaluationIR = {\n"
        "  return_value: unknown;\n"
        "  cost: unknown;\n"
        "  turnover: unknown;\n"
        "  coverage: unknown;\n"
        "  collapsed: unknown;\n"
        "  candidate: boolean;\n"
        "  failure_reason: string | null;\n"
        "  n_expected: number;\n"
        "  n_cells: number;\n"
        "  n_complete: number;\n"
        "  n_collapsed: number;\n"
        "  n_broken: number;\n"
        "  version: string;\n"
        "  toDict: () => EvaluationIRPayload;\n"
        "};\n"
        "\n"
        "function asInt(value: unknown, label: string): number {\n"
        '  if (typeof value === "boolean") return value ? 1 : 0;\n'
        '  if (typeof value === "number" && Number.isFinite(value)) {\n'
        "    return Math.trunc(value);\n"
        "  }\n"
        '  if (typeof value === "string" && /^-?\\d+$/.test(value.trim())) {\n'
        "    return Number.parseInt(value.trim(), 10);\n"
        "  }\n"
        "  throw new Error(`${label} must be an integer`);\n"
        "}\n"
        "\n"
        "function gradeFailureReason(args: {\n"
        "  n_expected: number;\n"
        "  n_cells: number;\n"
        "  n_complete: number;\n"
        "  n_collapsed: number;\n"
        "  n_broken: number;\n"
        "}): string | null {\n"
        '  if (args.n_expected <= 0) return "n_expected_nonpositive";\n'
        '  if (args.n_cells !== args.n_expected) return "n_cells_mismatch";\n'
        '  if (args.n_complete !== args.n_expected) return "partial_incomplete";\n'
        '  if (args.n_collapsed > 0) return "collapsed";\n'
        '  if (args.n_broken > 0) return "broken";\n'
        "  return null;\n"
        "}\n"
        "\n"
        "function isRecord(value: unknown): value is Record<string, unknown> {\n"
        '  return typeof value === "object" && value !== null && !Array.isArray(value);\n'
        "}\n"
        "\n"
        "function assertEncodeKeys(encoded: EvaluationIRPayload): EvaluationIRPayload {\n"
        "  const keys = Object.keys(encoded);\n"
        "  if (\n"
        "    keys.length !== ALLOWED_FIELDS.size ||\n"
        "    keys.some((key) => !ALLOWED_FIELDS.has(key))\n"
        "  ) {\n"
        "    throw new Error(\n"
        "      `encode keys drifted from schema.json: ${keys.join(\", \")}`,\n"
        "    );\n"
        "  }\n"
        "  return encoded;\n"
        "}\n"
        "\n"
        "/** Encode schema properties. candidate is jobCandidateGrade only. */\n"
        "export function encodeEvaluationIR(\n"
        "  args: EvaluationIREncodeArgs,\n"
        "): EvaluationIRPayload {\n"
        '  const n_expected = asInt(args.n_expected, "n_expected");\n'
        '  const n_cells = asInt(args.n_cells, "n_cells");\n'
        '  const n_complete = asInt(args.n_complete, "n_complete");\n'
        '  const n_collapsed = asInt(args.n_collapsed ?? 0, "n_collapsed");\n'
        '  const n_broken = asInt(args.n_broken ?? 0, "n_broken");\n'
        "  const candidate = jobCandidateGrade({\n"
        "    n_expected,\n"
        "    n_cells,\n"
        "    n_complete,\n"
        "    n_collapsed,\n"
        "    n_broken,\n"
        "  });\n"
        "  const gradedReason = gradeFailureReason({\n"
        "    n_expected,\n"
        "    n_cells,\n"
        "    n_complete,\n"
        "    n_collapsed,\n"
        "    n_broken,\n"
        "  });\n"
        "  let reason: string | null;\n"
        "  if (candidate) {\n"
        "    reason = null;\n"
        "  } else if (args.failure_reason) {\n"
        "    reason = String(args.failure_reason);\n"
        "  } else {\n"
        "    reason = gradedReason;\n"
        "  }\n"
        "  return assertEncodeKeys({\n"
        f"{encode_fields},\n"
        "  });\n"
        "}\n"
        "\n"
        "/** Closed-schema decode. Unknown fields fail. Candidate is re-graded. */\n"
        "export function decodeEvaluationIR(payload: unknown): EvaluationIR {\n"
        "  if (!isRecord(payload)) {\n"
        '    throw new Error("EvaluationIR must be an object");\n'
        "  }\n"
        "  const unknown = Object.keys(payload)\n"
        "    .filter((key) => !ALLOWED_FIELDS.has(key))\n"
        "    .sort();\n"
        "  if (unknown.length > 0) {\n"
        '    throw new Error(`EvaluationIR unknown field(s): ${unknown.join(", ")}`);\n'
        "  }\n"
        "  if (payload.version !== EVALUATION_IR_VERSION) {\n"
        "    throw new Error(\n"
        "      `unsupported Evaluation IR version: ${JSON.stringify(payload.version)}`,\n"
        "    );\n"
        "  }\n"
        '  const missing = ["n_expected", "n_cells", "n_complete"].filter(\n'
        "    (name) => !(name in payload),\n"
        "  );\n"
        "  if (missing.length > 0) {\n"
        '    throw new Error(`EvaluationIR missing ${missing.join(", ")}`);\n'
        "  }\n"
        '  const n_expected = asInt(payload.n_expected, "n_expected");\n'
        '  const n_cells = asInt(payload.n_cells, "n_cells");\n'
        '  const n_complete = asInt(payload.n_complete, "n_complete");\n'
        "  const n_collapsed = asInt(\n"
        '    "n_collapsed" in payload ? payload.n_collapsed : 0,\n'
        '    "n_collapsed",\n'
        "  );\n"
        "  const n_broken = asInt(\n"
        '    "n_broken" in payload ? payload.n_broken : 0,\n'
        '    "n_broken",\n'
        "  );\n"
        "  const candidate = jobCandidateGrade({\n"
        "    n_expected,\n"
        "    n_cells,\n"
        "    n_complete,\n"
        "    n_collapsed,\n"
        "    n_broken,\n"
        "  });\n"
        "  const stored = payload.candidate;\n"
        "  if (stored != null && Boolean(stored) !== candidate) {\n"
        '    throw new Error("candidate must equal job_candidate_grade");\n'
        "  }\n"
        "  const reason = payload.failure_reason;\n"
        "  let failure_reason: string | null;\n"
        "  if (candidate) {\n"
        "    failure_reason = null;\n"
        '  } else if (reason == null || reason === "") {\n'
        "    failure_reason = gradeFailureReason({\n"
        "      n_expected,\n"
        "      n_cells,\n"
        "      n_complete,\n"
        "      n_collapsed,\n"
        "      n_broken,\n"
        "    });\n"
        "  } else {\n"
        "    failure_reason = String(reason);\n"
        "  }\n"
        "  const ir = {\n"
        "    return_value: payload.return,\n"
        "    cost: payload.cost,\n"
        "    turnover: payload.turnover,\n"
        "    coverage: payload.coverage,\n"
        '    collapsed: "collapsed" in payload ? payload.collapsed : 0,\n'
        "    candidate,\n"
        "    failure_reason,\n"
        "    n_expected,\n"
        "    n_cells,\n"
        "    n_complete,\n"
        "    n_collapsed,\n"
        "    n_broken,\n"
        "    version: EVALUATION_IR_VERSION,\n"
        "  };\n"
        "  return {\n"
        "    ...ir,\n"
        "    toDict: () =>\n"
        "      encodeEvaluationIR({\n"
        "        return_value: ir.return_value,\n"
        "        cost: ir.cost,\n"
        "        turnover: ir.turnover,\n"
        "        coverage: ir.coverage,\n"
        "        collapsed: ir.collapsed,\n"
        "        n_expected: ir.n_expected,\n"
        "        n_cells: ir.n_cells,\n"
        "        n_complete: ir.n_complete,\n"
        "        n_collapsed: ir.n_collapsed,\n"
        "        n_broken: ir.n_broken,\n"
        "        failure_reason: ir.failure_reason,\n"
        "      }),\n"
        "  };\n"
        "}\n"
    )


def write_evaluation_ir_codec_ts(*, root: Path | None = None) -> Path:
    path = evaluation_ir_codec_ts_path(root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(evaluation_ir_codec_ts_source(root=root), encoding="utf-8")
    return path


def assert_evaluation_ir_codec_ts_frozen(*, root: Path | None = None) -> None:
    path = evaluation_ir_codec_ts_path(root=root)
    expected = evaluation_ir_codec_ts_source(root=root)
    if not path.is_file():
        raise ValueError(
            f"Evaluation IR codec artifact missing: {path}. "
            "Regenerate: python -m research.evaluation_ir"
        )
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        raise ValueError(
            "evaluation_ir_codec.generated.ts drifted from schema.json. "
            "Regenerate: python -m research.evaluation_ir"
        )


def evaluation_ir_ts_path(*, root: Path | None = None) -> Path:
    return _eval_ir_root(root=root) / EVALUATION_IR_TS_REL


def _ts_brace_block(src: str, open_index: int) -> str:
    if open_index < 0 or open_index >= len(src) or src[open_index] != "{":
        raise ValueError("Evaluation IR TS: expected '{'")
    depth = 0
    in_str: str | None = None
    escape = False
    i = open_index
    n = len(src)
    while i < n:
        ch = src[i]
        if in_str is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
        elif ch in ('"', "'", "`"):
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[open_index : i + 1]
        i += 1
    raise ValueError("Evaluation IR TS: unbalanced braces")


def _ts_object_literal_keys(literal: str) -> tuple[str, ...]:
    text = literal.strip()
    if not (text.startswith("{") and text.endswith("}")):
        raise ValueError("Evaluation IR TS encode return is not an object literal")
    keys: list[str] = []
    for raw in text[1:-1].splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if "//" in line:
            line = line.split("//", 1)[0].strip()
        line = line.rstrip(",").strip()
        if not line:
            continue
        if line.startswith("..."):
            raise ValueError("Evaluation IR TS encode return must not use spread")
        match = _TS_OBJECT_KEY_RE.match(line)
        if match is None:
            raise ValueError(f"Evaluation IR TS cannot parse encode key from {raw!r}")
        name = match.group("quoted_key") or match.group("key")
        if not name:
            raise ValueError(f"Evaluation IR TS cannot parse encode key from {raw!r}")
        keys.append(name)
    if not keys:
        raise ValueError("Evaluation IR TS encode return has no keys")
    return tuple(keys)


def evaluation_ir_ts_encode_keys(
    *, root: Path | None = None, src: str | None = None
) -> tuple[str, ...]:
    """Ordered keys from Worker encodeEvaluationIR. Not a grade policy."""
    text = src
    if text is None:
        path = evaluation_ir_codec_ts_path(root=root)
        if not path.is_file():
            raise ValueError(f"Evaluation IR worker codec missing: {path}")
        text = path.read_text(encoding="utf-8")
    marker = "export function encodeEvaluationIR"
    start = text.find(marker)
    if start < 0:
        raise ValueError("encodeEvaluationIR not found in evaluation_ir_codec.generated.ts")
    body_open = text.find("{", start)
    body = _ts_brace_block(text, body_open)
    if "jobCandidateGrade(" not in body:
        raise ValueError("encodeEvaluationIR must call jobCandidateGrade")
    ret = body.find("return assertEncodeKeys")
    if ret < 0:
        ret = body.find("return")
    if ret < 0:
        raise ValueError("encodeEvaluationIR has no return")
    obj_open = body.find("{", ret)
    return _ts_object_literal_keys(_ts_brace_block(body, obj_open))


def evaluation_ir_encode_keys() -> tuple[str, ...]:
    """Ordered keys from Python encode_evaluation_ir. Must equal schema properties."""
    return tuple(encode_evaluation_ir(n_expected=1, n_cells=1, n_complete=1))


def assert_evaluation_ir_encode_keys_match_schema(
    *, root: Path | None = None, ts_src: str | None = None
) -> None:
    """Fail CI if Python or Worker encode keys drift from schema.json properties."""
    schema = load_evaluation_ir_schema(root=root)
    schema_keys = tuple(str(name) for name in schema["properties"])
    py_keys = evaluation_ir_encode_keys()
    ts_keys = evaluation_ir_ts_encode_keys(root=root, src=ts_src)
    if py_keys != schema_keys:
        raise ValueError(
            "Python encode keys drifted from schema.json properties: "
            f"{list(py_keys)} != {list(schema_keys)}"
        )
    if ts_keys != schema_keys:
        raise ValueError(
            "evaluation_ir_codec.generated.ts encode keys drifted from schema.json "
            f"properties: {list(ts_keys)} != {list(schema_keys)}"
        )


__all__ = [
    "ALLOWED_FIELDS",
    "ALLOWED_FIELDS_TS_REL",
    "CODEC_TS_REL",
    "EVALUATION_IR_SCHEMA",
    "EVALUATION_IR_TS_REL",
    "EVALUATION_IR_VERSION",
    "EvaluationIR",
    "GOLDEN_REL",
    "SCHEMA_REL",
    "assert_evaluation_ir_allowed_fields_ts_frozen",
    "assert_evaluation_ir_codec_ts_frozen",
    "assert_evaluation_ir_encode_keys_match_schema",
    "candidate_from_job_artifact",
    "decode_evaluation_ir",
    "dumps_evaluation_ir_golden",
    "emit_evaluation_ir_golden",
    "emit_golden_vector",
    "encode_evaluation_ir",
    "evaluation_ir_allowed_fields_ts_path",
    "evaluation_ir_allowed_fields_ts_source",
    "evaluation_ir_codec_ts_path",
    "evaluation_ir_codec_ts_source",
    "evaluation_ir_encode_keys",
    "evaluation_ir_ts_encode_keys",
    "evaluation_ir_ts_path",
    "job_candidate_grade",
    "load_evaluation_ir_schema",
    "validate_evaluation_ir_schema",
    "write_evaluation_ir_allowed_fields_ts",
    "write_evaluation_ir_codec_ts",
    "write_evaluation_ir_golden",
]


if __name__ == "__main__":
    print(write_evaluation_ir_golden())
    print(write_evaluation_ir_allowed_fields_ts())
    print(write_evaluation_ir_codec_ts())
