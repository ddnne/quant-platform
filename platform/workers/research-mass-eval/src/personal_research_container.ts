import { Container, ContainerProxy } from "@cloudflare/containers";

import {
  PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS,
  PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES,
  PERSONAL_RESEARCH_RUNNER_VERSION,
  type PersonalResearchRequest,
  personalJobContainerName,
  personalResearchCohortDigest,
  personalResearchManifestKey,
  personalResearchRequestDigest,
  personalResearchResultKey,
  personalResearchUniverseRuleDigest,
} from "./personal_research_contract";
import {
  classifyPersonalResearchSubmit,
  type PersonalResearchBatchItem,
} from "./personal_research_batch";
import { personalHistorySourceOutbound } from "./personal_history_source";
import {
  durablePersonalJobStatus,
  submittedStateDocument,
  writeSubmittedState,
} from "./personal_job_state";
import { personalResearchR2Outbound } from "./personal_research_r2";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import type { Env } from "./types";

export { ContainerProxy };

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

export class PersonalResearchContainer extends Container<Env> {
  defaultPort = 8080;
  requiredPorts = [8080];
  pingEndpoint = "localhost/ready";
  // Hard outer guard. The service exits itself immediately after its terminal
  // manifest, so ordinary runs do not remain billable for this full window.
  sleepAfter = "180m";
  enableInternet = false;
}

// Assignment must go through Container's inherited static setter. A native
// `static outboundByHost = ...` class field shadows that setter and leaves the
// ContainerProxy registry empty, so every otherwise-allowed request returns
// the proxy's fail-closed 520 response.
PersonalResearchContainer.outboundByHost = {
  "research.r2": personalResearchR2Outbound,
  "history.source": personalHistorySourceOutbound,
};

type StoredManifest = Record<string, unknown> & {
  job_id?: unknown;
  request_digest?: unknown;
  status?: unknown;
};

async function storedManifest(
  env: Env,
  jobId: string,
): Promise<StoredManifest | null> {
  const object = await env.STRUCTURED_BUCKET.get(personalResearchManifestKey(jobId));
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

export async function submitPersonalResearch(
  env: Env,
  request: PersonalResearchRequest,
): Promise<Response> {
  const requestDigest = await personalResearchRequestDigest(request);
  const existing = await storedManifest(env, request.job_id);
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
      automatic_promotion: false,
      live_orders_enabled: false,
    });
  }
  const snapshot = await env.STRUCTURED_BUCKET.head(request.snapshot_key);
  if (!snapshot) {
    return responseJson(
      {
        ok: false,
        error: "personal_research_snapshot_not_found",
        job_id: request.job_id,
        go: false,
      },
      404,
    );
  }
  if (snapshot.size < 1 || snapshot.size > PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES) {
    return responseJson(
      {
        ok: false,
        error: "personal_research_snapshot_size_denied",
        job_id: request.job_id,
        maximum_bytes: PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES,
        go: false,
      },
      413,
    );
  }
  const submitted = submittedStateDocument({
    jobId: request.job_id,
    requestDigest,
    kind: "research",
    deploymentId: env.CF_VERSION_METADATA?.id ?? "unknown",
  });
  const conflict = await writeSubmittedState(env, submitted);
  if (conflict) return conflict;
  try {
    const target = await verifiedPersonalResearchContainer(
      env,
      await personalJobContainerName("research", request.job_id),
    );
    return await target.fetch(
      new Request("http://container/v1/run", {
        method: "POST",
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          ...request,
          cohort_digest: personalResearchCohortDigest(request.cohort_id),
          request_digest: requestDigest,
          result_key: personalResearchResultKey(request.job_id),
          manifest_key: personalResearchManifestKey(request.job_id),
          runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
          universe_rule_digest: personalResearchUniverseRuleDigest(
            request.universe_id,
          ),
        }),
      }),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return responseJson(
      {
        ok: false,
        error: "personal_research_container_unavailable",
        detail,
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
}

export async function submitPersonalResearchJobs(
  env: Env,
  requests: PersonalResearchRequest[],
): Promise<PersonalResearchBatchItem[]> {
  if (requests.length > PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS) {
    throw new Error("personal research concurrency cap exceeded");
  }
  const settled = await Promise.allSettled(
    requests.map(async (request) => {
      const response = await submitPersonalResearch(env, request);
      const classified = await classifyPersonalResearchSubmit(response);
      return {
        job_id: request.job_id,
        ...classified,
      };
    }),
  );
  return settled.map((item, index) => {
    if (item.status === "fulfilled") return item.value;
    return {
      job_id: requests[index]!.job_id,
      state: "rejected" as const,
      status: 503,
      body: {
        ok: false,
        error: "personal_research_container_unavailable",
        detail:
          item.reason instanceof Error ? item.reason.message : String(item.reason),
        job_id: requests[index]!.job_id,
        go: false,
      },
    };
  });
}

export async function personalResearchStatus(
  env: Env,
  jobId: string,
): Promise<Response> {
  return durablePersonalJobStatus(env, "research", jobId);
}
