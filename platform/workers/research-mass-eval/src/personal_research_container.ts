import { Container, ContainerProxy } from "@cloudflare/containers";

import {
  PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS,
  PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES,
  PERSONAL_RESEARCH_RUNNER_VERSION,
  parsePersonalResearchRequest,
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
import {
  CONTROLLED_LEASE_TTL_SECONDS,
  controlledPilotWriterR2Outbound,
} from "./controlled_pilot_container_r2";
import {
  CONTROLLED_R2_HOST,
  controlledPilotR2Outbound,
  denyControlledPilotR2Outbound,
} from "./controlled_pilot_r2";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import type { Env } from "./types";

export { ContainerProxy };

const CONTROLLED_JOB_STORAGE_KEY = "controlled_job_id";
const CONTROLLED_RESUME_DEADLINE_KEY = "controlled_resume_deadline";
const CONTROLLED_RESUME_DELAY_KEY = "controlled_resume_delay";
const CONTROLLED_RESUME_PHASE_KEY = "controlled_resume_phase";
const CONTROLLED_RESUME_NEXT_DUE_KEY = "controlled_resume_next_due";
const CONTROLLED_RESUME_CALLBACK = "resumeControlledPilot";
const CONTROLLED_RESUME_INITIAL_SECONDS = 5;
const CONTROLLED_RESUME_MAX_SECONDS = 60;
const CONTROLLED_RESUME_STALE_MS = CONTROLLED_RESUME_MAX_SECONDS * 2 * 1_000;
const CONTROLLED_OUTER_MS = 180 * 60 * 1_000;
const CONTROLLED_RESUME_WINDOW_MS =
  CONTROLLED_OUTER_MS + CONTROLLED_LEASE_TTL_SECONDS * 1_000;

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

  private async scheduleControlledRow(
    jobId: string,
    delay: number,
    nextDue: number,
  ): Promise<boolean> {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        await this.schedule(delay, CONTROLLED_RESUME_CALLBACK, {
          job_id: jobId,
          next_due: nextDue,
        });
        return true;
      } catch {}
    }
    return false;
  }

  private async scheduleControlledCallback(jobId: string, delay: number): Promise<void> {
    const nextDue = Date.now() + delay * 1_000;
    // Keep a second, same-generation watchdog behind the ordinary poll. The
    // first callback replaces the generation after it finishes; if its isolate
    // disappears mid-callback, the watchdog instead resumes the same job.
    const primary = await this.scheduleControlledRow(jobId, delay, nextDue);
    const watchdog = await this.scheduleControlledRow(
      jobId,
      delay + CONTROLLED_RESUME_MAX_SECONDS,
      nextDue,
    );
    if (!primary && !watchdog) throw new Error("controlled resume scheduler unavailable");
    // Publish only a generation for which the SDK confirmed at least one row.
    // Any ambiguous row from an earlier attempt is inert unless it has this
    // exact durable token.
    await this.ctx.storage.put(CONTROLLED_RESUME_NEXT_DUE_KEY, nextDue);
  }

  async scheduleControlledPilot(jobId: string): Promise<void> {
    const existing = await this.ctx.storage.get(CONTROLLED_JOB_STORAGE_KEY);
    if (existing !== undefined && existing !== jobId) {
      throw new Error("controlled scheduler job identity conflict");
    }
    if (existing === undefined) {
      await this.ctx.storage.put(CONTROLLED_JOB_STORAGE_KEY, jobId);
      await this.ctx.storage.put(
        CONTROLLED_RESUME_DEADLINE_KEY,
        Date.now() + CONTROLLED_RESUME_WINDOW_MS,
      );
      await this.ctx.storage.put(CONTROLLED_RESUME_DELAY_KEY, CONTROLLED_RESUME_INITIAL_SECONDS);
      await this.ctx.storage.delete(CONTROLLED_RESUME_PHASE_KEY);
    }
    const nextDue = await this.ctx.storage.get(CONTROLLED_RESUME_NEXT_DUE_KEY);
    if (typeof nextDue === "number" && Number.isFinite(nextDue) &&
        nextDue >= Date.now() - CONTROLLED_RESUME_STALE_MS) {
      return;
    }
    const storedDelay = await this.ctx.storage.get(CONTROLLED_RESUME_DELAY_KEY);
    const delay = typeof storedDelay === "number" && storedDelay >= CONTROLLED_RESUME_INITIAL_SECONDS
      ? Math.min(storedDelay, CONTROLLED_RESUME_MAX_SECONDS)
      : CONTROLLED_RESUME_INITIAL_SECONDS;
    await this.scheduleControlledCallback(jobId, delay);
  }

  private async clearControlledResume(): Promise<void> {
    this.deleteSchedules(CONTROLLED_RESUME_CALLBACK);
    await this.ctx.storage.delete([
      CONTROLLED_JOB_STORAGE_KEY,
      CONTROLLED_RESUME_DEADLINE_KEY,
      CONTROLLED_RESUME_DELAY_KEY,
      CONTROLLED_RESUME_PHASE_KEY,
      CONTROLLED_RESUME_NEXT_DUE_KEY,
    ]);
  }

  private async releaseControlledOutbound(): Promise<void> {
    let lastError: unknown;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        // The SDK refreshes the complete outbound configuration. Replace it in
        // one operation so two host removals cannot complete out of order.
        await this.setOutboundByHosts({});
        return;
      } catch (error) {
        lastError = error;
      }
    }
    throw lastError;
  }

  async resumeControlledPilot(payload: unknown): Promise<void> {
    const payloadJob = typeof payload === "object" && payload !== null &&
      Object.keys(payload).length === 2 && typeof (payload as { job_id?: unknown }).job_id === "string"
      ? (payload as { job_id: string }).job_id
      : "";
    const payloadDue = typeof payload === "object" && payload !== null &&
      typeof (payload as { next_due?: unknown }).next_due === "number" &&
      Number.isFinite((payload as { next_due: number }).next_due)
      ? (payload as { next_due: number }).next_due
      : Number.NaN;
    const jobId = await this.ctx.storage.get(CONTROLLED_JOB_STORAGE_KEY);
    const nextDue = await this.ctx.storage.get(CONTROLLED_RESUME_NEXT_DUE_KEY);
    if (!payloadJob || payloadJob !== jobId || payloadDue !== nextDue) return;
    // Rearm the same durable generation before any external RPC. Normal
    // completion replaces it below; an isolate crash leaves this watchdog to
    // continue autonomous recovery without an external status poll.
    if (!(await this.scheduleControlledRow(
      payloadJob,
      CONTROLLED_RESUME_MAX_SECONDS,
      payloadDue,
    ))) {
      throw new Error("controlled resume watchdog unavailable");
    }
    const deadline = await this.ctx.storage.get(CONTROLLED_RESUME_DEADLINE_KEY);
    const controlled = await import("./controlled_pilot");
    const now = Date.now();
    const cleanupAt = typeof deadline === "number"
      ? deadline - CONTROLLED_LEASE_TTL_SECONDS * 1_000
      : Number.NaN;
    if (!Number.isFinite(cleanupAt) || now >= cleanupAt) {
      let expired = false;
      let destroyed = false;
      let released = false;
      try {
        await controlled.expireControlledPilotJob(this.env, payloadJob, false);
        expired = true;
      } catch {
        // Cleanup is retried below without restarting execution.
      }
      try {
        await this.releaseControlledOutbound();
        released = true;
      } catch {
        // Do not discard the only durable cleanup retry.
      }
      try {
        await this.destroy();
        destroyed = true;
      } catch {
        // Resume state remains until both stop and capability cleanup succeed.
      }
      if (expired && destroyed && released) {
        await this.clearControlledResume();
      } else {
        await this.scheduleControlledCallback(payloadJob, CONTROLLED_RESUME_MAX_SECONDS);
      }
      return;
    }
    try {
      await controlled.runControlledPilotJob(this.env, payloadJob, false);
    } catch {
      // A transient Worker/RPC error is retried below within the fixed deadline.
    }
    let phase = "SUBMITTED";
    try {
      const response = await controlled.controlledPilotStatus(this.env, payloadJob);
      const body = await response.clone().json() as { status?: unknown };
      if (body.status === "FINALIZE_RETRY") {
        phase = "FINALIZE_RETRY";
        await this.releaseControlledOutbound();
      }
      if (response.status === 200 && (body.status === "COMPLETED" || body.status === "FAILED")) {
        try {
          await this.releaseControlledOutbound();
        } catch {
          await this.scheduleControlledCallback(payloadJob, CONTROLLED_RESUME_INITIAL_SECONDS);
          return;
        }
        await this.clearControlledResume();
        return;
      }
    } catch {
      // Status/R2 failures use the same bounded retry below.
    }
    const previousPhase = await this.ctx.storage.get(CONTROLLED_RESUME_PHASE_KEY);
    const previousDelay = await this.ctx.storage.get(CONTROLLED_RESUME_DELAY_KEY);
    const delay = previousPhase !== phase
      ? CONTROLLED_RESUME_INITIAL_SECONDS
      : Math.min(
          typeof previousDelay === "number" ? previousDelay * 2 : CONTROLLED_RESUME_INITIAL_SECONDS,
          CONTROLLED_RESUME_MAX_SECONDS,
        );
    await this.ctx.storage.put(CONTROLLED_RESUME_PHASE_KEY, phase);
    await this.ctx.storage.put(CONTROLLED_RESUME_DELAY_KEY, delay);
    await this.scheduleControlledCallback(payloadJob, delay);
  }
}

// Assignment must go through Container's inherited static setter. A native
// `static outboundByHost = ...` class field shadows that setter and leaves the
// ContainerProxy registry empty, so every otherwise-allowed request returns
// the proxy's fail-closed 520 response.
PersonalResearchContainer.outboundHandlers = {
  controlledPilotSnapshot: controlledPilotR2Outbound,
  controlledPilotWriter: controlledPilotWriterR2Outbound,
};
PersonalResearchContainer.outboundByHost = {
  "research.r2": personalResearchR2Outbound,
  [CONTROLLED_R2_HOST]: denyControlledPilotR2Outbound,
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
  const parsed = parsePersonalResearchRequest(request);
  if (!parsed.ok) {
    return responseJson({ ok: false, error: parsed.error, go: false }, 400);
  }
  request = parsed.value;
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
            request.cohort_id,
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
