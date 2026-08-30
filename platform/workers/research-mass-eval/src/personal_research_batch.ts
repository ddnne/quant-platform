import {
  PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS,
  parsePersonalResearchRequest,
  personalResearchManifestKey,
  type PersonalResearchRequest,
} from "./personal_research_contract";
import type { Env } from "./types";

export const PERSONAL_RESEARCH_BATCH_MAX_BYTES = 64 * 1024;

export type PersonalResearchJobState =
  | "accepted"
  | "idempotent"
  | "rejected";

export type PersonalResearchBatchItem = {
  job_id: string;
  state: PersonalResearchJobState;
  status: number;
  body: unknown;
};

export type PersonalResearchBatchParseResult =
  | { ok: true; value: PersonalResearchRequest[] }
  | { ok: false; error: string };

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

export function parsePersonalResearchBatchRequest(
  body: unknown,
): PersonalResearchBatchParseResult {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, error: "body must be a JSON object" };
  }
  const raw = body as Record<string, unknown>;
  if (Object.keys(raw).sort().join(",") !== "jobs") {
    return { ok: false, error: "personal research batch fields are closed" };
  }
  if (!Array.isArray(raw.jobs)) {
    return { ok: false, error: "jobs must be an array" };
  }
  if (
    raw.jobs.length < 1 ||
    raw.jobs.length > PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS
  ) {
    return {
      ok: false,
      error: `batch must contain 1-${PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS} jobs`,
    };
  }
  const jobs: PersonalResearchRequest[] = [];
  const seen = new Set<string>();
  for (const item of raw.jobs) {
    const parsed = parsePersonalResearchRequest(item);
    if (!parsed.ok) return { ok: false, error: parsed.error };
    if (seen.has(parsed.value.job_id)) {
      return { ok: false, error: "job_id values must be unique" };
    }
    seen.add(parsed.value.job_id);
    jobs.push(parsed.value);
  }
  return { ok: true, value: jobs };
}

export async function classifyPersonalResearchSubmit(
  response: Response,
): Promise<{
  state: PersonalResearchJobState;
  status: number;
  body: unknown;
}> {
  const status = response.status;
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = { error: "invalid_container_response" };
  }
  const idempotent =
    typeof body === "object" &&
    body !== null &&
    "idempotent" in body &&
    (body as { idempotent?: unknown }).idempotent === true;
  if (idempotent && status >= 200 && status < 300) {
    return { state: "idempotent", status, body };
  }
  if (status >= 200 && status < 300) {
    return { state: "accepted", status, body };
  }
  return { state: "rejected", status, body };
}

async function durableJobSummary(
  env: Env,
  jobId: string,
): Promise<{ job_id: string; durable: boolean; job: Record<string, unknown> | null }> {
  const object = await env.STRUCTURED_BUCKET.get(personalResearchManifestKey(jobId));
  if (!object || object.size > 64 * 1024) {
    return { job_id: jobId, durable: false, job: null };
  }
  try {
    const parsed: unknown = await object.json();
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return { job_id: jobId, durable: false, job: null };
    }
    return { job_id: jobId, durable: true, job: parsed as Record<string, unknown> };
  } catch {
    return { job_id: jobId, durable: false, job: null };
  }
}

export async function personalResearchBatchStatus(
  env: Env,
  jobIds: string[],
): Promise<Response> {
  if (
    jobIds.length < 1 ||
    jobIds.length > PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS
  ) {
    return responseJson(
      {
        ok: false,
        error: `batch status must contain 1-${PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS} job ids`,
      },
      400,
    );
  }
  const jobs = await Promise.all(jobIds.map((jobId) => durableJobSummary(env, jobId)));
  return responseJson({
    ok: jobs.every((job) => job.durable && job.job?.status === "COMPLETED"),
    jobs,
    go: false,
    automatic_promotion: false,
    live_orders_enabled: false,
  });
}

export function personalResearchBatchJobIdsFromUrl(url: URL): string[] | null {
  const values = url.searchParams.getAll("job_id");
  if (values.length < 1) return [];
  return values;
}
