import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  PERSONAL_SNAPSHOT_CONTAINER_NAME,
  PERSONAL_SNAPSHOT_MAX_DATABASE_BYTES,
} from "./personal_research_contract";
import {
  PERSONAL_SNAPSHOT_FORMAT,
  type PersonalSnapshotBuildRequest,
  personalSnapshotManifestKey,
  personalSnapshotRequestDigest,
} from "./personal_snapshot_contract";
import {
  durablePersonalJobStatus,
  submittedStateDocument,
  writeSubmittedState,
} from "./personal_job_state";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import type { Env } from "./types";

type StoredManifest = Record<string, unknown> & {
  job_id?: unknown;
  request_digest?: unknown;
  status?: unknown;
};

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function acquisitionEnvironment(env: Env): "production" | "staging" | null {
  const value = String(env.ENVIRONMENT ?? "");
  if (value === "staging" || value === "production") return value;
  return null;
}

async function storedSnapshotManifest(
  env: Env,
  jobId: string,
): Promise<StoredManifest | null> {
  const object = await env.STRUCTURED_BUCKET.get(personalSnapshotManifestKey(jobId));
  if (!object || object.size > 64 * 1024) return null;
  try {
    const parsed: unknown = await object.json();
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as StoredManifest)
      : null;
  } catch {
    return null;
  }
}

export async function submitPersonalSnapshotBuild(
  env: Env,
  request: PersonalSnapshotBuildRequest,
): Promise<Response> {
  const requestDigest = await personalSnapshotRequestDigest(request);
  const existing = await storedSnapshotManifest(env, request.job_id);
  if (existing) {
    if (existing.request_digest !== requestDigest) {
      return responseJson(
        { ok: false, error: "job_id_conflict", job_id: request.job_id, go: false },
        409,
      );
    }
    return responseJson({
      ok: existing.status === "COMPLETED",
      idempotent: true,
      job: existing,
      go: false,
      research_state: "PERSONAL_DRAFT",
      completeness_claim: "NONE",
      controlled_live_eligibility: "FORBIDDEN",
    });
  }
  const environment = acquisitionEnvironment(env);
  if (!environment || !env.JQUANTS_ACQUISITION) {
    return responseJson(
      {
        ok: false,
        error: "personal_snapshot_acquisition_unavailable",
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
  const submitted = submittedStateDocument({
    jobId: request.job_id,
    requestDigest,
    kind: "snapshot",
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
      new Request("http://container/v1/build-snapshot", {
        method: "POST",
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          deployment_id: env.CF_VERSION_METADATA?.id ?? "unknown",
          environment,
          format: PERSONAL_SNAPSHOT_FORMAT,
          job_id: request.job_id,
          lookback_sessions: request.lookback_sessions,
          manifest_key: personalSnapshotManifestKey(request.job_id),
          max_database_bytes: PERSONAL_SNAPSHOT_MAX_DATABASE_BYTES,
          period_end: request.period_end,
          period_start: request.period_start,
          request_digest: requestDigest,
          runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
        }),
      }),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return responseJson(
      {
        ok: false,
        error: "personal_snapshot_container_unavailable",
        detail,
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
}

export async function personalSnapshotBuildStatus(
  env: Env,
  jobId: string,
): Promise<Response> {
  return durablePersonalJobStatus(env, "snapshot", jobId);
}
