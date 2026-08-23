/** Versioned Evaluation IR — single evaluation authority.

Candidate is not a free boolean and is not a second Python/TS policy copy.
Encode always calls jobCandidateGrade. Decode rejects unknown fields
and re-grades; a smuggled candidate:true cannot pass a partial job.

Shared golden: specs/evaluation_ir/golden.jsonl is emitted by Python
emit_evaluation_ir_golden / emit_golden_vector (encoder-owned).
Worker tests consume that file; jobCandidateGrade is the only TS grade.
Codec field SoT: specs/evaluation_ir/schema.json (Python encode/decode validates).
Worker encode/decode body is generated from schema properties into
evaluation_ir_codec.generated.ts. This file is the façade. Do not add a
second encode object. Decode does not load a JSON Schema engine; unknown
keys fail against ALLOWED_FIELDS generated from schema properties
(additionalProperties: false) and version must be evaluation-ir/v1.
Encode keys must equal ALLOWED_FIELDS (schema properties). There is no
second field list.
*/

import { jobCandidateGrade } from "./candidate";
import { ALLOWED_FIELDS } from "./evaluation_ir_allowed_fields.generated";

export { jobCandidateGrade, ALLOWED_FIELDS };
export {
  EVALUATION_IR_VERSION,
  decodeEvaluationIR,
  encodeEvaluationIR,
} from "./evaluation_ir_codec.generated";
export type {
  EvaluationIR,
  EvaluationIREncodeArgs,
  EvaluationIRPayload,
} from "./evaluation_ir_codec.generated";

/** Repo-relative path. Emitted by Python emit_evaluation_ir_golden. */
export const GOLDEN_REL = "specs/evaluation_ir/golden.jsonl";

/** Repo-relative codec SoT. Python encode/decode validate this file. */
export const SCHEMA_REL = "specs/evaluation_ir/schema.json";
