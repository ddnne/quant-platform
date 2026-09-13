import type {
  PilotReadyPublicationRpc,
  ReadyPublicationResult,
} from "../../ingestion-premium/src/pilot_ready_publication_rpc";
import {
  awaitUntilAborted,
  isContainerRequestTimeout,
  withRequestDeadline,
} from "./bounded_container_request";
import { putJsonCreateOnly } from "./http";
import { readSmallJson } from "./personal_job_state";
import { personalReceiptCandidatePublicationKey } from "./personal_receipt_candidate_contract";

export const RECEIPT_CANDIDATE_PUBLICATION_POINTER_FORMAT =
  "receipt-candidate-publication-pointer/v1";
const POINTER_MAX_BYTES = 64 * 1024;

export type PublicationEnv = {
  STRUCTURED_BUCKET: R2Bucket;
  ENVIRONMENT?: string;
  PILOT_READY_PUBLICATION?: PilotReadyPublicationRpc | Service;
  CF_VERSION_METADATA?: { id?: string };
};

export type ReceiptCandidatePublicationObservation = {
  historical: boolean;
  persisted: boolean;
  ready_declared: false;
  operational_go: false;
  job_id: string;
  environment?: "production" | "staging";
  deployment_id?: string;
  error?: string;
  pointer?: {
    format: typeof RECEIPT_CANDIDATE_PUBLICATION_POINTER_FORMAT;
    job_id: string;
    attestation_id: string;
    snapshot_id: string;
    immutable_db_digest: string;
    envelope_key: string;
    attestation_key: string;
  };
  attempt_status?: ReadyPublicationResult["status"];
};

export function configuredPublicationEnvironment(
  env: { ENVIRONMENT?: string },
): "production" | "staging" | null {
  const value = String(env.ENVIRONMENT ?? "");
  return value === "staging" || value === "production" ? value : null;
}

export function isCompletedPassTerminal(job: Record<string, unknown>): boolean {
  return job.status === "COMPLETED" && job.compiled_scope_status === "PASS";
}

function publicationRpc(
  binding: PublicationEnv["PILOT_READY_PUBLICATION"],
): PilotReadyPublicationRpc | undefined {
  if (
    binding !== undefined &&
    "publishAdmittedReceiptCandidate" in binding &&
    typeof binding.publishAdmittedReceiptCandidate === "function"
  ) {
    return binding;
  }
  return undefined;
}

function recordPublicationAttempt(
  observation: ReceiptCandidatePublicationObservation,
): void {
  console.log(
    JSON.stringify({
      event: "receipt_candidate_publication",
      job_id: observation.job_id,
      environment: observation.environment ?? null,
      deployment_id: observation.deployment_id ?? null,
      historical: observation.historical,
      persisted: observation.persisted,
      attempt_status: observation.attempt_status ?? null,
      reason: observation.error ?? null,
    }),
  );
}

function observationBase(
  env: PublicationEnv,
  jobId: string,
): Pick<
  ReceiptCandidatePublicationObservation,
  | "ready_declared"
  | "operational_go"
  | "job_id"
  | "environment"
  | "deployment_id"
> {
  const environment = configuredPublicationEnvironment(env);
  const deploymentId = env.CF_VERSION_METADATA?.id;
  return {
    ready_declared: false,
    operational_go: false,
    job_id: jobId,
    ...(environment ? { environment } : {}),
    ...(deploymentId ? { deployment_id: deploymentId } : {}),
  };
}

function pointerFrom(
  jobId: string,
  fields: {
    attestation_id: string;
    snapshot_id: string;
    immutable_db_digest: string;
    envelope_key: string;
    attestation_key: string;
  },
): NonNullable<ReceiptCandidatePublicationObservation["pointer"]> {
  return {
    format: RECEIPT_CANDIDATE_PUBLICATION_POINTER_FORMAT,
    job_id: jobId,
    attestation_id: fields.attestation_id,
    snapshot_id: fields.snapshot_id,
    immutable_db_digest: fields.immutable_db_digest,
    envelope_key: fields.envelope_key,
    attestation_key: fields.attestation_key,
  };
}

function historicalFromStored(
  env: PublicationEnv,
  jobId: string,
  stored: Record<string, unknown>,
): ReceiptCandidatePublicationObservation | null {
  if (
    stored.format !== RECEIPT_CANDIDATE_PUBLICATION_POINTER_FORMAT ||
    stored.job_id !== jobId ||
    typeof stored.attestation_id !== "string" ||
    typeof stored.snapshot_id !== "string" ||
    typeof stored.immutable_db_digest !== "string" ||
    typeof stored.envelope_key !== "string" ||
    typeof stored.attestation_key !== "string"
  ) {
    return null;
  }
  return {
    ...observationBase(env, jobId),
    historical: true,
    persisted: true,
    pointer: pointerFrom(jobId, {
      attestation_id: stored.attestation_id,
      snapshot_id: stored.snapshot_id,
      immutable_db_digest: stored.immutable_db_digest,
      envelope_key: stored.envelope_key,
      attestation_key: stored.attestation_key,
    }),
  };
}

export async function readStoredPublicationPointer(
  env: PublicationEnv,
  jobId: string,
): Promise<ReceiptCandidatePublicationObservation | null> {
  try {
    const stored = await readSmallJson(
      env.STRUCTURED_BUCKET,
      personalReceiptCandidatePublicationKey(jobId),
      POINTER_MAX_BYTES,
    );
    if (!stored) return null;
    return historicalFromStored(env, jobId, stored);
  } catch {
    return null;
  }
}

async function persistVerifiedPointer(
  env: PublicationEnv,
  jobId: string,
  result: Extract<ReadyPublicationResult, { ok: true }>,
): Promise<boolean> {
  try {
    const put = await putJsonCreateOnly(
      env.STRUCTURED_BUCKET,
      personalReceiptCandidatePublicationKey(jobId),
      {
        format: RECEIPT_CANDIDATE_PUBLICATION_POINTER_FORMAT,
        job_id: jobId,
        attestation_id: result.attestation_id,
        snapshot_id: result.snapshot_id,
        immutable_db_digest: result.immutable_db_digest,
        envelope_key: result.envelope_key,
        attestation_key: result.attestation_key,
        ready_declared: false,
        operational_go: false,
      },
    );
    return !put.conflict;
  } catch {
    return false;
  }
}

export async function publishAdmittedReceiptCandidatePointer(
  env: PublicationEnv,
  jobId: string,
): Promise<ReceiptCandidatePublicationObservation> {
  const pending = (error: string): ReceiptCandidatePublicationObservation => ({
    ...observationBase(env, jobId),
    historical: false,
    persisted: false,
    attempt_status: "PENDING",
    error,
  });
  try {
    return await withRequestDeadline(async (signal) => {
      const stored = await awaitUntilAborted(
        readStoredPublicationPointer(env, jobId),
        signal,
      );
      if (stored) return stored;
      const environment = configuredPublicationEnvironment(env);
      const rpc = publicationRpc(env.PILOT_READY_PUBLICATION);
      if (!environment || !rpc) {
        return pending("PILOT_READY_PUBLICATION unprovisioned");
      }
      const result = await awaitUntilAborted(
        rpc.publishAdmittedReceiptCandidate({ job_id: jobId, environment }),
        signal,
      );
      if (!result.ok) {
        return {
          ...observationBase(env, jobId),
          historical: false,
          persisted: false,
          attempt_status: result.status,
          error: result.error,
        };
      }
      const persisted = await awaitUntilAborted(
        persistVerifiedPointer(env, jobId, result),
        signal,
      );
      return {
        ...observationBase(env, jobId),
        historical: false,
        persisted,
        attempt_status: result.status,
        pointer: pointerFrom(jobId, result),
        ...(persisted ? {} : { error: "publication pointer persist failed" }),
      };
    });
  } catch (error) {
    return pending(
      isContainerRequestTimeout(error)
        ? "publication attempt timeout"
        : "publication attempt failed",
    );
  }
}

export async function maybePublishAfterAdmittedTerminal(
  env: PublicationEnv,
  manifest: Record<string, unknown>,
): Promise<void> {
  if (!isCompletedPassTerminal(manifest) || typeof manifest.job_id !== "string") {
    return;
  }
  try {
    recordPublicationAttempt(
      await publishAdmittedReceiptCandidatePointer(env, manifest.job_id),
    );
  } catch {
    recordPublicationAttempt({
      ...observationBase(env, manifest.job_id),
      historical: false,
      persisted: false,
      attempt_status: "PENDING",
      error: "publication attempt failed",
    });
  }
}
