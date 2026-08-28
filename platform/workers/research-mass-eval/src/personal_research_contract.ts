import { sha256Hex } from "./sha256";

export const PERSONAL_RESEARCH_RUNNER_VERSION = "personal-cloud-runner/v1";
export const PERSONAL_RESEARCH_CONTAINER_NAME = "personal-research-singleton";
export const PERSONAL_RESEARCH_MAX_PERIOD_DAYS = 2200;
export const PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024;

const JOB_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const SNAPSHOT_KEY_RE =
  /^research\/personal\/snapshots\/sha256=([0-9a-f]{64})\.sqlite$/;

export type PersonalResearchRequest = {
  job_id: string;
  snapshot_key: string;
  snapshot_sha256: string;
  period_start: string;
  period_end: string;
};

export type PersonalResearchParseResult =
  | { ok: true; value: PersonalResearchRequest }
  | { ok: false; error: string };

function isoDay(value: unknown): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null;
  }
  const date = new Date(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(date.getTime())) return null;
  return date.toISOString().slice(0, 10) === value ? value : null;
}

function dayNumber(value: string): number {
  return Math.floor(new Date(`${value}T00:00:00.000Z`).getTime() / 86_400_000);
}

export function parsePersonalResearchRequest(
  body: unknown,
): PersonalResearchParseResult {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, error: "body must be a JSON object" };
  }
  const raw = body as Record<string, unknown>;
  const expected = [
    "job_id",
    "period_end",
    "period_start",
    "snapshot_key",
    "snapshot_sha256",
  ];
  const keys = Object.keys(raw).sort();
  if (JSON.stringify(keys) !== JSON.stringify(expected)) {
    return { ok: false, error: "personal research request fields are closed" };
  }

  const jobId = typeof raw.job_id === "string" ? raw.job_id : "";
  if (!JOB_ID_RE.test(jobId)) {
    return { ok: false, error: "job_id is invalid" };
  }
  const sha =
    typeof raw.snapshot_sha256 === "string" ? raw.snapshot_sha256 : "";
  if (!SHA256_RE.test(sha)) {
    return { ok: false, error: "snapshot_sha256 must be lowercase sha256 hex" };
  }
  const snapshotKey =
    typeof raw.snapshot_key === "string" ? raw.snapshot_key : "";
  const snapshotMatch = SNAPSHOT_KEY_RE.exec(snapshotKey);
  if (!snapshotMatch || snapshotMatch[1] !== sha) {
    return {
      ok: false,
      error: "snapshot_key must be the content-addressed personal snapshot key",
    };
  }
  const start = isoDay(raw.period_start);
  const end = isoDay(raw.period_end);
  if (!start || !end) {
    return { ok: false, error: "period_start and period_end must be ISO dates" };
  }
  const span = dayNumber(end) - dayNumber(start);
  if (span <= 0 || span > PERSONAL_RESEARCH_MAX_PERIOD_DAYS) {
    return {
      ok: false,
      error: `research period must be 1-${PERSONAL_RESEARCH_MAX_PERIOD_DAYS} days`,
    };
  }
  return {
    ok: true,
    value: {
      job_id: jobId,
      snapshot_key: snapshotKey,
      snapshot_sha256: sha,
      period_start: start,
      period_end: end,
    },
  };
}

export function personalResearchManifestKey(jobId: string): string {
  if (!JOB_ID_RE.test(jobId)) throw new Error("invalid personal research job id");
  return `research/personal/jobs/job=${jobId}/manifest.json`;
}

export function personalResearchResultKey(jobId: string): string {
  if (!JOB_ID_RE.test(jobId)) throw new Error("invalid personal research job id");
  return `research/personal/jobs/job=${jobId}/result.tar.gz`;
}

export async function personalResearchRequestDigest(
  request: PersonalResearchRequest,
): Promise<string> {
  const canonical = JSON.stringify({
    job_id: request.job_id,
    period_end: request.period_end,
    period_start: request.period_start,
    runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
    snapshot_key: request.snapshot_key,
    snapshot_sha256: request.snapshot_sha256,
  });
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}

export function personalResearchJobIdFromPath(pathname: string): string | null {
  const prefix = "/v1/personal-research/jobs/";
  if (!pathname.startsWith(prefix)) return null;
  const value = pathname.slice(prefix.length);
  return JOB_ID_RE.test(value) ? value : null;
}

export function isPersonalResearchSnapshotKey(key: string): boolean {
  return SNAPSHOT_KEY_RE.test(key);
}

export function isPersonalResearchJobId(value: string): boolean {
  return JOB_ID_RE.test(value);
}
