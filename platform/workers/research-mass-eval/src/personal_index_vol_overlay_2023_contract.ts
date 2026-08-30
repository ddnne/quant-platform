import { sha256Hex } from "./sha256";

export const PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID =
  "personal-index-vol-overlay-2023-v1" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION =
  "personal-index-vol-overlay-cloud-runner/v1" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY =
  "2023-01-04" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY =
  "2023-10-13" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_INPUT_MAX_BYTES = 1024 * 1024;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_RESULT_MAX_BYTES = 32 * 1024 * 1024;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_TERMINAL_MAX_BYTES = 64 * 1024;

const JOB_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;

export type PersonalIndexVolOverlay2023Request = {
  job_id: string;
  cohort_id: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID;
  base_job_id: string;
  svi_job_id: string;
};

export type ImmutableInputReference = {
  key: string;
  etag: string;
  size: number;
  sha256: string;
};

export type SnapshotInputReference = {
  key: string;
  etag: string;
  size: number;
  raw_sha256: string;
};

export type PersonalIndexVolOverlay2023InputManifest = {
  schema_version: "personal-index-vol-overlay-2023-input/v1";
  job_id: string;
  cohort_id: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID;
  runner_version: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION;
  base: {
    job_id: string;
    result: ImmutableInputReference;
    snapshot: SnapshotInputReference;
    sleeve_artifact: {
      archive_member: string;
      sha256: string;
    };
  };
  svi: {
    job_id: string;
    request_digest: string;
    input_manifest: ImmutableInputReference;
    feature: ImmutableInputReference;
    panel: ImmutableInputReference;
    options: {
      days: Array<{ date: string; objects: ImmutableInputReference[] }>;
      object_count: number;
      total_bytes: number;
    };
  };
  fixed_window: {
    start: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY;
    end: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY;
    signal_start_policy: "MAX_126_SESSION_LOOKBACK";
    signal_end_policy: "LAST_SESSION_MINUS_TWO";
  };
  temporal_contract: {
    source_decision_cutoff_jst: "15:00:00+09:00";
    prepared_available_at: "SAME_DAY_23_59_59_JST";
    fill_timing: "next_close";
    first_pnl_interval: "fill_close_to_following_close";
    no_forward_fill: true;
  };
  authority: {
    draft_only: true;
    screening_only: true;
    ready: false;
    mass: false;
    promotion: false;
    live_orders: false;
    go: false;
    single_stock_option_iv: "FORBIDDEN";
  };
};

export function parsePersonalIndexVolOverlay2023Request(
  body: unknown,
):
  | { ok: true; value: PersonalIndexVolOverlay2023Request }
  | { ok: false; error: string } {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, error: "body must be a JSON object" };
  }
  const raw = body as Record<string, unknown>;
  const expected = ["base_job_id", "cohort_id", "job_id", "svi_job_id"];
  if (JSON.stringify(Object.keys(raw).sort()) !== JSON.stringify(expected)) {
    return {
      ok: false,
      error: "personal index-vol overlay request fields are closed",
    };
  }
  const jobId = typeof raw.job_id === "string" ? raw.job_id : "";
  const baseJobId =
    typeof raw.base_job_id === "string" ? raw.base_job_id : "";
  const sviJobId = typeof raw.svi_job_id === "string" ? raw.svi_job_id : "";
  if (![jobId, baseJobId, sviJobId].every((value) => JOB_ID_RE.test(value))) {
    return { ok: false, error: "job ids are invalid" };
  }
  if (raw.cohort_id !== PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID) {
    return {
      ok: false,
      error: `cohort_id must be ${PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID}`,
    };
  }
  return {
    ok: true,
    value: {
      job_id: jobId,
      cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
      base_job_id: baseJobId,
      svi_job_id: sviJobId,
    },
  };
}

function checkedJobId(jobId: string): string {
  if (!JOB_ID_RE.test(jobId)) throw new Error("invalid index-vol overlay job id");
  return jobId;
}

export function personalIndexVolOverlay2023Prefix(jobId: string): string {
  return `research/personal/index-vol-overlay-2023/job=${checkedJobId(jobId)}`;
}

export function personalIndexVolOverlay2023InputManifestKey(jobId: string): string {
  return `${personalIndexVolOverlay2023Prefix(jobId)}/input-manifest.json`;
}

export function personalIndexVolOverlay2023TerminalManifestKey(
  jobId: string,
): string {
  return `${personalIndexVolOverlay2023Prefix(jobId)}/manifest.json`;
}

export function personalIndexVolOverlay2023ArtifactKey(
  kind: "prepared-panel" | "report",
  digest: string,
): string {
  if (!DIGEST_RE.test(digest)) throw new Error("invalid overlay artifact digest");
  return `research/personal/index-vol-overlay-2023/artifacts/${kind}/sha256=${digest.slice("sha256:".length)}.json`;
}

export function personalIndexVolOverlay2023JobIdFromPath(
  pathname: string,
): string | null {
  const prefix = "/v1/personal-index-vol-overlay-2023/jobs/";
  if (!pathname.startsWith(prefix)) return null;
  const value = pathname.slice(prefix.length);
  return JOB_ID_RE.test(value) ? value : null;
}

export function isPersonalIndexVolOverlay2023JobId(value: string): boolean {
  return JOB_ID_RE.test(value);
}

export function isPersonalIndexVolOverlay2023Digest(value: string): boolean {
  return DIGEST_RE.test(value);
}

export async function personalIndexVolOverlay2023RequestDigest(
  request: PersonalIndexVolOverlay2023Request,
  inputManifestDigest: string,
): Promise<string> {
  if (!DIGEST_RE.test(inputManifestDigest)) {
    throw new Error("input manifest digest is invalid");
  }
  const canonical = JSON.stringify({
    base_job_id: request.base_job_id,
    cohort_id: request.cohort_id,
    input_manifest_digest: inputManifestDigest,
    input_manifest_key: personalIndexVolOverlay2023InputManifestKey(
      request.job_id,
    ),
    job_id: request.job_id,
    runner_version: PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
    svi_job_id: request.svi_job_id,
  });
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}
