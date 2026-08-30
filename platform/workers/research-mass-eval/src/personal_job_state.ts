import { putBytesCreateOnly } from "./http";
import {
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID,
  PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
  personalIndexOverlayFamilyTerminalManifestKey,
} from "./personal_index_vol_overlay_2023_contract";
import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  isPersonalResearchJobId,
  personalResearchManifestKey,
} from "./personal_research_contract";
import { personalSnapshotManifestKey } from "./personal_snapshot_contract";
import {
  PERSONAL_OPTION_SIDECAR_KIND,
  PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
  personalOptionSidecarTerminalKey,
} from "./personal_option_sidecar_producer_contract";
import { personalVolAmPmPanelBuildTerminalKey } from "./personal_vol_am_pm_panel_writer_contract";
import { sha256Hex } from "./sha256";
import type { Env } from "./types";

export type PersonalJobKind =
  | "research"
  | "snapshot"
  | "svi"
  | "overlay"
  | "vol-panel"
  | "option-sidecar";

export const PERSONAL_JOB_TTL_MS = 180 * 60 * 1000;
const STATE_MAX_BYTES = 8 * 1024;
const TERMINAL_MAX_BYTES = 64 * 1024;

export type PersonalJobState = {
  job_id: string;
  request_digest: string;
  kind: PersonalJobKind;
  status: "SUBMITTED";
  submitted_at: string;
  expires_at: string;
  runner_version: string;
  deployment_id: string;
};

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

export function personalJobStateKey(kind: PersonalJobKind, jobId: string): string {
  if (!isPersonalResearchJobId(jobId)) {
    throw new Error("invalid personal job id");
  }
  if (kind === "snapshot") {
    return `research/personal/snapshot-builds/job=${jobId}/state.json`;
  }
  if (kind === "svi") {
    return `research/personal/svi-2023/job=${jobId}/state.json`;
  }
  if (kind === "overlay") {
    return `research/personal/index-vol-overlay-2023/job=${jobId}/state.json`;
  }
  if (kind === "vol-panel") {
    return `research/personal/vol-ratio-am-pm-v1/panel-builds/job=${jobId}/state.json`;
  }
  if (kind === PERSONAL_OPTION_SIDECAR_KIND) {
    return `research/personal/option-sidecar/job=${jobId}/state.json`;
  }
  return `research/personal/jobs/job=${jobId}/state.json`;
}

export function personalJobTerminalKey(kind: PersonalJobKind, jobId: string): string {
  if (kind === "snapshot") return personalSnapshotManifestKey(jobId);
  if (kind === "svi") {
    return `research/personal/svi-2023/job=${jobId}/manifest.json`;
  }
  if (kind === "overlay") {
    return `research/personal/index-vol-overlay-2023/job=${jobId}/manifest.json`;
  }
  if (kind === "vol-panel") {
    return personalVolAmPmPanelBuildTerminalKey(jobId);
  }
  if (kind === PERSONAL_OPTION_SIDECAR_KIND) {
    return personalOptionSidecarTerminalKey(jobId);
  }
  return personalResearchManifestKey(jobId);
}

export async function readSmallJson(
  bucket: R2Bucket,
  key: string,
  maximum: number,
): Promise<Record<string, unknown> | null> {
  const object = await bucket.get(key);
  if (!object || object.size > maximum) return null;
  try {
    const parsed: unknown = await object.json();
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export async function putCreateOnlyJson(
  bucket: R2Bucket,
  key: string,
  data: Record<string, unknown>,
  metadata: Record<string, string>,
): Promise<{ conflict: boolean; created: boolean; digest: string }> {
  const bytes = new TextEncoder().encode(JSON.stringify(data));
  const digest = `sha256:${await sha256Hex(bytes)}`;
  const result = await putBytesCreateOnly(bucket, key, bytes, {
    digest,
    contentType: "application/json; charset=utf-8",
    customMetadata: metadata,
  });
  return {
    conflict: result.conflict,
    created: result.created,
    digest: result.digest,
  };
}

export function submittedStateDocument(input: {
  jobId: string;
  requestDigest: string;
  kind: PersonalJobKind;
  now?: Date;
  deploymentId: string;
  runnerVersion?: string;
  ttlMs?: number;
}): PersonalJobState {
  const now = input.now ?? new Date();
  const ttlMs = input.ttlMs ?? PERSONAL_JOB_TTL_MS;
  return {
    job_id: input.jobId,
    request_digest: input.requestDigest,
    kind: input.kind,
    status: "SUBMITTED",
    submitted_at: now.toISOString(),
    expires_at: new Date(now.getTime() + ttlMs).toISOString(),
    runner_version: input.runnerVersion ?? PERSONAL_RESEARCH_RUNNER_VERSION,
    deployment_id: input.deploymentId,
  };
}

export async function writeSubmittedState(
  env: Env,
  document: PersonalJobState,
): Promise<Response | null> {
  const key = personalJobStateKey(document.kind, document.job_id);
  const existing = await readSmallJson(env.STRUCTURED_BUCKET, key, STATE_MAX_BYTES);
  if (existing) {
    if (existing.request_digest !== document.request_digest) {
      return responseJson(
        {
          ok: false,
          error: "job_id_conflict",
          job_id: document.job_id,
          go: false,
        },
        409,
      );
    }
    return null;
  }
  const put = await putCreateOnlyJson(
    env.STRUCTURED_BUCKET,
    key,
    document,
    {
      plane: "personal_job_state",
      job_id: document.job_id,
      request_digest: document.request_digest,
      kind: document.kind,
    },
  );
  if (put.conflict) {
    const raced = await readSmallJson(env.STRUCTURED_BUCKET, key, STATE_MAX_BYTES);
    if (raced && raced.request_digest === document.request_digest) return null;
    return responseJson(
      {
        ok: false,
        error: "job_id_conflict",
        job_id: document.job_id,
        go: false,
      },
      409,
    );
  }
  return null;
}

export function timeoutFailedTerminal(
  document: PersonalJobState,
  options: { error: string; now?: Date },
): Record<string, unknown> {
  const now = options.now ?? new Date();
  const error = options.error;
  const base: Record<string, unknown> = {
    version: document.runner_version,
    job_id: document.job_id,
    request_digest: document.request_digest,
    status: "FAILED",
    error,
    submitted_at: document.submitted_at,
    finished_at: now.toISOString(),
    runner_version: document.runner_version,
    deployment_id: document.deployment_id,
    go: false,
    automatic_promotion: false,
    live_orders_enabled: false,
  };
  if (document.kind === "snapshot") {
    return {
      ...base,
      research_state: "PERSONAL_DRAFT",
      completeness_claim: "NONE",
      controlled_live_eligibility: "FORBIDDEN",
    };
  }
  if (document.kind === "svi") {
    return {
      ...base,
      schema_version: "personal-svi-2023-manifest/v2",
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      not_a_pass: true,
    };
  }
  if (document.kind === "overlay") {
    return {
      ...base,
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      not_a_pass: true,
      single_stock_option_iv_used: false,
    };
  }
  if (document.kind === "vol-panel") {
    return {
      ...base,
      schema_version: "personal-vol-ratio-am-pm-panel-writer-manifest/v1",
      kind: "vol-panel",
      producer_id: "personal-vol-ratio-am-pm-panel-writer/v1",
      cohort_id: "personal-vol-ratio-am-pm-v1",
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      not_a_pass: true,
    };
  }
  if (document.kind === PERSONAL_OPTION_SIDECAR_KIND) {
    return {
      ...base,
      schema_version: "personal-n225-option-sidecar-manifest/v1",
      kind: PERSONAL_OPTION_SIDECAR_KIND,
      producer_id: "personal-n225-option-sidecar-producer/v1",
      cohort_id: "personal-n225-option-sidecar/v1",
      runner_version: document.runner_version || PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      not_a_pass: true,
    };
  }
  return base;
}

async function readTerminalDocument(
  env: Env,
  kind: PersonalJobKind,
  jobId: string,
): Promise<Record<string, unknown> | null> {
  if (kind === "overlay") {
    for (const cohort of [
      PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
      PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID,
    ] as const) {
      const found = await readSmallJson(
        env.STRUCTURED_BUCKET,
        personalIndexOverlayFamilyTerminalManifestKey(jobId, cohort),
        TERMINAL_MAX_BYTES,
      );
      if (found) return found;
    }
    return null;
  }
  return readSmallJson(
    env.STRUCTURED_BUCKET,
    personalJobTerminalKey(kind, jobId),
    TERMINAL_MAX_BYTES,
  );
}

export async function finalizeExpiredFailed(
  env: Env,
  kind: PersonalJobKind,
  jobId: string,
  now = new Date(),
): Promise<Record<string, unknown> | null> {
  const existingTerminal = await readTerminalDocument(env, kind, jobId);
  if (existingTerminal) return existingTerminal;
  const state = await readSmallJson(
    env.STRUCTURED_BUCKET,
    personalJobStateKey(kind, jobId),
    STATE_MAX_BYTES,
  );
  if (!state || state.status !== "SUBMITTED") return null;
  const expiresAt = Date.parse(String(state.expires_at ?? ""));
  if (!Number.isFinite(expiresAt) || expiresAt > now.getTime()) return null;
  const failed = timeoutFailedTerminal(state as unknown as PersonalJobState, {
    error: "personal job exceeded its durable lifetime without a terminal manifest",
    now,
  });
  await putCreateOnlyJson(
    env.STRUCTURED_BUCKET,
    personalJobTerminalKey(kind, jobId),
    failed,
    {
      plane: kind === "snapshot" ? "personal_snapshot" : "personal_research",
      job_id: jobId,
      request_digest: String(state.request_digest),
      status: "FAILED",
    },
  );
  return (await readTerminalDocument(env, kind, jobId)) ?? failed;
}

export async function durablePersonalJobStatus(
  env: Env,
  kind: PersonalJobKind,
  jobId: string,
  now = new Date(),
): Promise<Response> {
  const terminal = await readTerminalDocument(env, kind, jobId);
  if (terminal) {
    return responseJson({
      ok: terminal.status === "COMPLETED",
      durable: true,
      job: terminal,
      go: false,
      automatic_promotion: false,
      live_orders_enabled: false,
    });
  }
  const expired = await finalizeExpiredFailed(env, kind, jobId, now);
  if (expired) {
    return responseJson({
      ok: false,
      durable: true,
      job: expired,
      go: false,
      automatic_promotion: false,
      live_orders_enabled: false,
    });
  }
  const state = await readSmallJson(
    env.STRUCTURED_BUCKET,
    personalJobStateKey(kind, jobId),
    STATE_MAX_BYTES,
  );
  if (state) {
    return responseJson({
      ok: false,
      durable: true,
      job: { ...state, status: "PENDING" },
      go: false,
      automatic_promotion: false,
      live_orders_enabled: false,
    });
  }
  return responseJson(
    { ok: false, error: "job_not_found", job_id: jobId, go: false },
    404,
  );
}
