/** Versioned Evaluation IR — single evaluation authority.

Candidate is not a free boolean and is not a second Python/TS policy copy.
Encode always calls jobCandidateGrade. Decode rejects unknown fields
and re-grades; a smuggled candidate:true cannot pass a partial job.

Shared golden: specs/evaluation_ir/golden.jsonl is emitted by Python
emit_evaluation_ir_golden / emit_golden_vector (encoder-owned).
Worker tests consume that file; jobCandidateGrade is the only TS grade.
Codec field SoT: specs/evaluation_ir/schema.json (Python encode/decode validates).
Worker decode does not load a JSON Schema engine; unknown keys fail against
ALLOWED_FIELDS generated from schema properties (additionalProperties: false)
and version must be evaluation-ir/v1. Encode keys must equal ALLOWED_FIELDS
(schema properties). There is no second field list.
*/

import { jobCandidateGrade } from "./candidate";
import { ALLOWED_FIELDS } from "./evaluation_ir_allowed_fields.generated";

export { jobCandidateGrade, ALLOWED_FIELDS };

export const EVALUATION_IR_VERSION = "evaluation-ir/v1";

/** Repo-relative path. Emitted by Python emit_evaluation_ir_golden. */
export const GOLDEN_REL = "specs/evaluation_ir/golden.jsonl";

/** Repo-relative codec SoT. Python encode/decode validate this file. */
export const SCHEMA_REL = "specs/evaluation_ir/schema.json";

export type EvaluationIRPayload = {
  version: string;
  return: unknown;
  cost: unknown;
  turnover: unknown;
  coverage: unknown;
  collapsed: unknown;
  candidate: boolean;
  failure_reason: string | null;
  n_expected: number;
  n_cells: number;
  n_complete: number;
  n_collapsed: number;
  n_broken: number;
};

export type EvaluationIREncodeArgs = {
  return_value?: unknown;
  cost?: unknown;
  turnover?: unknown;
  coverage?: unknown;
  collapsed?: unknown;
  n_expected: number;
  n_cells: number;
  n_complete: number;
  n_collapsed?: number;
  n_broken?: number;
  failure_reason?: string | null;
};

export type EvaluationIR = {
  return_value: unknown;
  cost: unknown;
  turnover: unknown;
  coverage: unknown;
  collapsed: unknown;
  candidate: boolean;
  failure_reason: string | null;
  n_expected: number;
  n_cells: number;
  n_complete: number;
  n_collapsed: number;
  n_broken: number;
  version: string;
  toDict: () => EvaluationIRPayload;
};

function asInt(value: unknown, label: string): number {
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.trunc(value);
  }
  if (typeof value === "string" && /^-?\d+$/.test(value.trim())) {
    return Number.parseInt(value.trim(), 10);
  }
  throw new Error(`${label} must be an integer`);
}

function gradeFailureReason(args: {
  n_expected: number;
  n_cells: number;
  n_complete: number;
  n_collapsed: number;
  n_broken: number;
}): string | null {
  if (args.n_expected <= 0) return "n_expected_nonpositive";
  if (args.n_cells !== args.n_expected) return "n_cells_mismatch";
  if (args.n_complete !== args.n_expected) return "partial_incomplete";
  if (args.n_collapsed > 0) return "collapsed";
  if (args.n_broken > 0) return "broken";
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertEncodeKeys(encoded: EvaluationIRPayload): EvaluationIRPayload {
  const keys = Object.keys(encoded);
  if (
    keys.length !== ALLOWED_FIELDS.size ||
    keys.some((key) => !ALLOWED_FIELDS.has(key))
  ) {
    throw new Error(
      `encode keys drifted from schema.json: ${keys.join(", ")}`,
    );
  }
  return encoded;
}

/** Encode schema properties. candidate is jobCandidateGrade only. */
export function encodeEvaluationIR(
  args: EvaluationIREncodeArgs,
): EvaluationIRPayload {
  const n_expected = asInt(args.n_expected, "n_expected");
  const n_cells = asInt(args.n_cells, "n_cells");
  const n_complete = asInt(args.n_complete, "n_complete");
  const n_collapsed = asInt(args.n_collapsed ?? 0, "n_collapsed");
  const n_broken = asInt(args.n_broken ?? 0, "n_broken");
  const candidate = jobCandidateGrade({
    n_expected,
    n_cells,
    n_complete,
    n_collapsed,
    n_broken,
  });
  const gradedReason = gradeFailureReason({
    n_expected,
    n_cells,
    n_complete,
    n_collapsed,
    n_broken,
  });
  let reason: string | null;
  if (candidate) {
    reason = null;
  } else if (args.failure_reason) {
    reason = String(args.failure_reason);
  } else {
    reason = gradedReason;
  }
  return assertEncodeKeys({
    version: EVALUATION_IR_VERSION,
    return: args.return_value ?? null,
    cost: args.cost ?? null,
    turnover: args.turnover ?? null,
    coverage: args.coverage ?? null,
    collapsed: args.collapsed ?? 0,
    candidate,
    failure_reason: reason,
    n_expected,
    n_cells,
    n_complete,
    n_collapsed,
    n_broken,
  });
}

/** Closed-schema decode. Unknown fields fail. Candidate is re-graded. */
export function decodeEvaluationIR(payload: unknown): EvaluationIR {
  if (!isRecord(payload)) {
    throw new Error("EvaluationIR must be an object");
  }
  const unknown = Object.keys(payload)
    .filter((key) => !ALLOWED_FIELDS.has(key))
    .sort();
  if (unknown.length > 0) {
    throw new Error(`EvaluationIR unknown field(s): ${unknown.join(", ")}`);
  }
  if (payload.version !== EVALUATION_IR_VERSION) {
    throw new Error(
      `unsupported Evaluation IR version: ${JSON.stringify(payload.version)}`,
    );
  }
  const missing = ["n_expected", "n_cells", "n_complete"].filter(
    (name) => !(name in payload),
  );
  if (missing.length > 0) {
    throw new Error(`EvaluationIR missing ${missing.join(", ")}`);
  }
  const n_expected = asInt(payload.n_expected, "n_expected");
  const n_cells = asInt(payload.n_cells, "n_cells");
  const n_complete = asInt(payload.n_complete, "n_complete");
  const n_collapsed = asInt(
    "n_collapsed" in payload ? payload.n_collapsed : 0,
    "n_collapsed",
  );
  const n_broken = asInt(
    "n_broken" in payload ? payload.n_broken : 0,
    "n_broken",
  );
  const candidate = jobCandidateGrade({
    n_expected,
    n_cells,
    n_complete,
    n_collapsed,
    n_broken,
  });
  const stored = payload.candidate;
  if (stored != null && Boolean(stored) !== candidate) {
    throw new Error("candidate must equal job_candidate_grade");
  }
  const reason = payload.failure_reason;
  let failure_reason: string | null;
  if (candidate) {
    failure_reason = null;
  } else if (reason == null || reason === "") {
    failure_reason = gradeFailureReason({
      n_expected,
      n_cells,
      n_complete,
      n_collapsed,
      n_broken,
    });
  } else {
    failure_reason = String(reason);
  }
  const ir = {
    return_value: payload.return,
    cost: payload.cost,
    turnover: payload.turnover,
    coverage: payload.coverage,
    collapsed: "collapsed" in payload ? payload.collapsed : 0,
    candidate,
    failure_reason,
    n_expected,
    n_cells,
    n_complete,
    n_collapsed,
    n_broken,
    version: EVALUATION_IR_VERSION,
  };
  return {
    ...ir,
    toDict: () =>
      encodeEvaluationIR({
        return_value: ir.return_value,
        cost: ir.cost,
        turnover: ir.turnover,
        coverage: ir.coverage,
        collapsed: ir.collapsed,
        n_expected: ir.n_expected,
        n_cells: ir.n_cells,
        n_complete: ir.n_complete,
        n_collapsed: ir.n_collapsed,
        n_broken: ir.n_broken,
        failure_reason: ir.failure_reason,
      }),
  };
}
