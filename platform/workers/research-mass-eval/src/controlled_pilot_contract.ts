import contract from "../../../../specs/ready/controlled_pilot_v1.generated.json";
import { sha256Digest } from "./controlled_pilot_json";
import type { ControlledSessionScope } from "./ops_projection_ready";

export const CONTROLLED_PILOT_CONTRACT = contract;
export const CONTROLLED_PILOT_IDENTITY = contract.identity;
export const CONTROLLED_PILOT_RUNNER_VERSION = contract.runner_version;
export const CONTROLLED_PILOT_MAX_PARALLEL = contract.max_parallel;
export const CONTROLLED_PILOT_GENERATION = contract.generation;
export const CONTROLLED_PILOT_PLAN_COUNT = contract.plan_count;
export const CONTROLLED_CHILD_COUNT = contract.child_count;
export const CONTROLLED_FILL_CONTRACT_DIGEST = contract.fill_contract_digest;
export const CONTROLLED_FILL_EXECUTION_MODE = contract.fill_contract.execution_mode;
export const CONTROLLED_MAX_GROSS_WEIGHT_PPM = contract.max_gross_weight_ppm;
export const EXACT_FOUR_PLAN_IDS = contract.plan_ids as readonly string[];
export const EXACT_FOUR_DATASET_IDS = contract.dataset_ids as readonly string[];
export const EXACT_FOUR_PROFILE_ID = contract.profile_id;
export const EXACT_FOUR_PROFILE_VERSION = contract.profile_version;
export const EXACT_FOUR_PROFILE_DIGEST = contract.profile_digest;
export const EXACT_FOUR_PLAN_SET_DIGEST = contract.plan_set_digest;
export const EXACT_FOUR_CLOSURE_DIGEST = contract.dependency_closure_digest;
export const EXACT_FOUR_BINDING_DIGEST = contract.exact_four_binding_digest;
export const EXACT_FOUR_POLICY_DIGEST = contract.policy_digest;
export const EXACT_FOUR_BUDGET_SCOPE_DIGEST = contract.budget_scope_digest;
export const EXACT_FOUR_EXECUTION_LIMIT_SET_DIGEST = contract.execution_limit_set_digest;
export const EXACT_FOUR_UNIVERSE_RULE_DIGEST = contract.universe_rule_digest;
export const EXACT_FOUR_DATASET_MEMBERSHIP_DIGEST = contract.dataset_membership_digest;
export const EXACT_FOUR_COVERAGE_POLICY_VERSION = contract.coverage_policy_version;
export const EXACT_FOUR_COVERAGE_POLICY_DIGEST = contract.coverage_policy_digest;
export const CONTROLLED_READY_ENVELOPE_FORMAT =
  "controlled-pilot-ready-envelope/v1" as const;
export const CONTROLLED_TRADER_BATCH_FORMAT =
  "controlled-pilot-trader-authorization-batch/v2" as const;
export const CONTROLLED_SNAPSHOT_KEY_PREFIX =
  "research/controlled_pilot/v1/snapshots/";
export const CONTROLLED_READY_KEY_PREFIX =
  "research/controlled_pilot/v1/ready/";
export const CONTROLLED_JOB_KEY_PREFIX = "research/controlled_pilot/v1/jobs/";

const IDEMPOTENCY_RE = /^[a-z0-9][a-z0-9._-]{7,63}$/;
const ATTESTATION_RE = /^[a-zA-Z0-9._:-]{8,128}$/;
const SHA256_RE = /^sha256:[0-9a-f]{64}$/;

export type ControlledPilotRequest = {
  idempotency_key: string;
  ready_attestation_id: string;
  snapshot_id: string;
};

export type ControlledPhysicalSnapshot = {
  key: string;
  digest: string;
  size: number;
};

export type ControlledPilotJobSpec = {
  identity: typeof CONTROLLED_PILOT_IDENTITY;
  format: "controlled-pilot-job-spec/v1";
  job_id: string;
  idempotency_key: string;
  ready_attestation_id: string;
  ready_manifest_digest: string;
  signed_projection_document_digest: string;
  session_scope: ControlledSessionScope;
  snapshot_id: string;
  immutable_db_digest: string;
  snapshot_key: string;
  snapshot_size: number;
  fill_contract_digest: typeof CONTROLLED_FILL_CONTRACT_DIGEST;
  authorization_digest: string;
  request_digest: string;
  resolved_universe_digest: string;
  universe_rule_digest: typeof EXACT_FOUR_UNIVERSE_RULE_DIGEST;
  max_gross_weight_ppm: typeof CONTROLLED_MAX_GROSS_WEIGHT_PPM;
  manifest_key: string;
  execution_id: string;
  profile_digest: typeof EXACT_FOUR_PROFILE_DIGEST;
  plan_set_digest: typeof EXACT_FOUR_PLAN_SET_DIGEST;
  dependency_closure_digest: typeof EXACT_FOUR_CLOSURE_DIGEST;
  exact_four_binding_digest: typeof EXACT_FOUR_BINDING_DIGEST;
  runner_version: typeof CONTROLLED_PILOT_RUNNER_VERSION;
};

export type ParseControlledPilotRequest =
  | { ok: true; value: ControlledPilotRequest }
  | { ok: false; error: string };

const FORBIDDEN_KEYS = [
  "db_path",
  "snapshot_path",
  "snapshot_key",
  "r2_key",
  "plan_ids",
  "strategy_spec",
  "logics",
  "row_digest",
  "dataset_digest",
  "manifest_digest",
  "counts",
  "promotion",
  "automatic_promotion",
  "live_orders",
  "live_orders_enabled",
  "broker",
  "order",
  "generation",
  "mass",
  "ledger_path",
  "purpose_id",
  "immutable_db_digest",
] as const;

export const EXACT_FOUR_STRATEGY_BY_PLAN = Object.fromEntries(
  contract.plans.map((plan) => [plan.plan_id, plan.strategy_spec_id]),
) as Record<string, string>;

export const EXACT_FOUR_STRATEGY_SPEC_HASHES = Object.fromEntries(
  contract.plans.map((plan) => [plan.strategy_spec_id, plan.strategy_spec_hash]),
) as Record<string, string>;

export const EXACT_FOUR_PLAN_BINDING_DIGESTS = Object.fromEntries(
  contract.plans.map((plan) => [plan.plan_id, plan.plan_binding_digest]),
) as Record<string, string>;

export const EXACT_FOUR_STRATEGY_SPEC_VERSIONS = Object.fromEntries(
  contract.plans.map((plan) => [plan.plan_id, plan.strategy_spec_version]),
) as Record<string, string>;

export function parseControlledPilotRequest(
  body: unknown,
): ParseControlledPilotRequest {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, error: "body must be a JSON object" };
  }
  const rec = body as Record<string, unknown>;
  for (const key of FORBIDDEN_KEYS) {
    if (Object.prototype.hasOwnProperty.call(rec, key)) {
      return { ok: false, error: `caller cannot supply ${key}` };
    }
  }
  const allowed = new Set([
    "idempotency_key",
    "ready_attestation_id",
    "snapshot_id",
  ]);
  const extra = Object.keys(rec).filter((key) => !allowed.has(key));
  if (extra.length) {
    return { ok: false, error: `unknown field(s): ${extra.sort().join(",")}` };
  }
  const idempotency = String(rec.idempotency_key || "");
  const attestation = String(rec.ready_attestation_id || "");
  const snapshot = String(rec.snapshot_id || "");
  if (!IDEMPOTENCY_RE.test(idempotency)) {
    return { ok: false, error: "idempotency_key is invalid" };
  }
  if (!ATTESTATION_RE.test(attestation)) {
    return { ok: false, error: "ready_attestation_id is invalid" };
  }
  if (!SHA256_RE.test(snapshot)) {
    return { ok: false, error: "snapshot_id must be sha256" };
  }
  return {
    ok: true,
    value: {
      idempotency_key: idempotency,
      ready_attestation_id: attestation,
      snapshot_id: snapshot,
    },
  };
}

export function controlledPhysicalSnapshotKey(immutableDbDigest: string): string {
  if (!SHA256_RE.test(immutableDbDigest)) {
    throw new Error("physical snapshot digest must be sha256");
  }
  const hex = immutableDbDigest.slice("sha256:".length);
  return `${CONTROLLED_SNAPSHOT_KEY_PREFIX}sha256=${hex}.sqlite`;
}

export function controlledReadyKey(attestationId: string): string {
  return `${CONTROLLED_READY_KEY_PREFIX}${encodeURIComponent(attestationId)}.json`;
}

export function controlledJobPrefix(jobId: string): string {
  return `${CONTROLLED_JOB_KEY_PREFIX}${jobId}`;
}

export function controlledTraderAuthorizationKey(
  idempotencyKey: string,
  attestationId: string,
): string {
  return (
    `research/controlled_pilot/v1/authorizations/idempotency=${idempotencyKey}` +
    `/identity=${CONTROLLED_PILOT_IDENTITY}/ready=${encodeURIComponent(attestationId)}.json`
  );
}

export function controlledContainerTerminalKey(jobId: string): string {
  return `${controlledJobPrefix(jobId)}/container-terminal.json`;
}

export function controlledExecutionStageKey(jobId: string): string {
  return `${controlledJobPrefix(jobId)}/execution.json`;
}

export function controlledCandidateManifestKey(jobId: string): string {
  return `${controlledJobPrefix(jobId)}/candidate-manifest.json`;
}

export async function controlledPilotContainerName(
  idempotencyKey: string,
): Promise<string> {
  const digest = await sha256Digest(
    `${CONTROLLED_PILOT_IDENTITY}:container:${idempotencyKey}`,
  );
  return `p-${digest.slice("sha256:".length, "sha256:".length + 24)}`;
}

export async function controlledPilotExecutionId(
  jobId: string,
  requestDigest: string,
): Promise<string> {
  return sha256Digest(`${CONTROLLED_PILOT_IDENTITY}:execution:${jobId}:${requestDigest}`);
}

export function closedControlledPilotJobSpec(
  spec: Omit<
    ControlledPilotJobSpec,
    | "identity"
    | "format"
    | "fill_contract_digest"
    | "universe_rule_digest"
    | "max_gross_weight_ppm"
    | "profile_digest"
    | "plan_set_digest"
    | "dependency_closure_digest"
    | "exact_four_binding_digest"
    | "runner_version"
  >,
): ControlledPilotJobSpec {
  return {
    identity: CONTROLLED_PILOT_IDENTITY,
    format: "controlled-pilot-job-spec/v1",
    runner_version: CONTROLLED_PILOT_RUNNER_VERSION,
    fill_contract_digest: CONTROLLED_FILL_CONTRACT_DIGEST,
    universe_rule_digest: EXACT_FOUR_UNIVERSE_RULE_DIGEST,
    max_gross_weight_ppm: CONTROLLED_MAX_GROSS_WEIGHT_PPM,
    profile_digest: EXACT_FOUR_PROFILE_DIGEST,
    plan_set_digest: EXACT_FOUR_PLAN_SET_DIGEST,
    dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
    exact_four_binding_digest: EXACT_FOUR_BINDING_DIGEST,
    ...spec,
  };
}
