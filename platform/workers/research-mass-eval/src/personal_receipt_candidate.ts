import { json } from "./http";
import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  PERSONAL_SNAPSHOT_CONTAINER_NAME,
  PERSONAL_SNAPSHOT_MAX_DATABASE_BYTES,
} from "./personal_research_contract";
import {
  EXACT_FOUR_CLOSURE_DIGEST,
  EXACT_FOUR_PROFILE_DIGEST,
  EXACT_FOUR_PROFILE_ID,
} from "./controlled_pilot_contract";
import {
  RECEIPT_CANDIDATE_FORMAT,
  type ReceiptCandidateRequest,
  personalReceiptCandidateManifestKey,
  receiptCandidateRequestDigest,
} from "./personal_receipt_candidate_contract";
import {
  durablePersonalJobStatus,
  readSmallJson,
  submittedStateDocument,
  writeSubmittedState,
} from "./personal_job_state";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import type { Env } from "./types";

const TERMINAL_MAX_BYTES = 64 * 1024;

function configuredEnvironment(env: Env): "production" | "staging" | null {
  const value = String(env.ENVIRONMENT ?? "");
  if (value === "staging" || value === "production") return value;
  return null;
}

export async function submitPersonalReceiptCandidate(
  env: Env,
  request: ReceiptCandidateRequest,
): Promise<Response> {
  const requestDigest = await receiptCandidateRequestDigest(request);
  const existing = await readSmallJson(
    env.STRUCTURED_BUCKET,
    personalReceiptCandidateManifestKey(request.job_id),
    TERMINAL_MAX_BYTES,
  );
  if (existing) {
    if (existing.request_digest !== requestDigest) {
      return json(
        { ok: false, error: "job_id_conflict", job_id: request.job_id, go: false },
        409,
      );
    }
    return json({
      ok: existing.status === "COMPLETED",
      idempotent: true,
      job: existing,
      go: false,
      pending_ready: true,
      ready: false,
    });
  }
  const environment = configuredEnvironment(env);
  if (!environment || !env.INGESTION_PREMIUM) {
    return json(
      {
        ok: false,
        error: "receipt_candidate_product_unavailable",
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
  const submitted = submittedStateDocument({
    jobId: request.job_id,
    requestDigest,
    kind: "receipt-candidate",
    deploymentId: env.CF_VERSION_METADATA?.id ?? "unknown",
  });
  const conflict = await writeSubmittedState(env, submitted);
  if (conflict) return conflict;
  try {
    const target = await verifiedPersonalResearchContainer(
      env,
      PERSONAL_SNAPSHOT_CONTAINER_NAME,
    );
    return await target.fetch(
      new Request("http://container/v1/materialize-receipt-candidate", {
        method: "POST",
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          deployment_id: env.CF_VERSION_METADATA?.id ?? "unknown",
          dependency_closure_digest: EXACT_FOUR_CLOSURE_DIGEST,
          environment,
          format: RECEIPT_CANDIDATE_FORMAT,
          job_id: request.job_id,
          manifest_key: personalReceiptCandidateManifestKey(request.job_id),
          max_database_bytes: PERSONAL_SNAPSHOT_MAX_DATABASE_BYTES,
          profile_digest: EXACT_FOUR_PROFILE_DIGEST,
          profile_id: EXACT_FOUR_PROFILE_ID,
          request_digest: requestDigest,
          runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
          segments: request.segments,
        }),
      }),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return json(
      {
        ok: false,
        error: "receipt_candidate_container_unavailable",
        detail,
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
}

export async function personalReceiptCandidateStatus(
  env: Env,
  jobId: string,
): Promise<Response> {
  return durablePersonalJobStatus(env, "receipt-candidate", jobId);
}
