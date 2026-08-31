import {
  PERSONAL_RESEARCH_MAX_PERIOD_DAYS,
  PERSONAL_RESEARCH_RUNNER_VERSION,
  isPersonalResearchJobId,
} from "./personal_research_contract";
import { sha256Hex } from "./sha256";

export const PERSONAL_SNAPSHOT_FORMAT = "personal-draft-history/v7";
export const PERSONAL_SNAPSHOT_DEFAULT_LOOKBACK_SESSIONS = 10;
export const PERSONAL_SNAPSHOT_MAX_LOOKBACK_SESSIONS = 252;
export const PERSONAL_SNAPSHOT_MAX_REQUEST_BYTES = 8 * 1024;
export const PERSONAL_SNAPSHOT_MANIFEST_MAX_BYTES = 64 * 1024;

const REQUIRED_FIELDS = ["job_id", "period_end", "period_start"] as const;

export type PersonalSnapshotBuildRequest = {
  job_id: string;
  period_start: string;
  period_end: string;
  lookback_sessions: number;
};

export type PersonalSnapshotParseResult =
  | { ok: true; value: PersonalSnapshotBuildRequest }
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

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

function jstParts(now: Date): {
  year: number;
  month: number;
  day: number;
  minutes: number;
} {
  const shifted = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    minutes: shifted.getUTCHours() * 60 + shifted.getUTCMinutes(),
  };
}

export function jstToday(now = new Date()): string {
  const jst = jstParts(now);
  return `${jst.year}-${pad2(jst.month)}-${pad2(jst.day)}`;
}

/** Last fully closed JST calendar month-end the governed RPC will serve. */
export function lastClosedMonthEnd(now = new Date()): string {
  const jst = jstParts(now);
  let year = jst.year;
  let month = jst.month - 1;
  if (jst.day === 1 && jst.minutes < 60) month -= 1;
  if (month < 1) {
    month += 12;
    year -= 1;
  }
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

export function parsePersonalSnapshotBuildRequest(
  body: unknown,
  now = new Date(),
): PersonalSnapshotParseResult {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, error: "body must be a JSON object" };
  }
  const raw = body as Record<string, unknown>;
  const keys = Object.keys(raw).sort();
  const withLookback = [...REQUIRED_FIELDS, "lookback_sessions"].sort();
  const withoutLookback = [...REQUIRED_FIELDS].sort();
  const allowed =
    JSON.stringify(keys) === JSON.stringify(withLookback) ||
    JSON.stringify(keys) === JSON.stringify(withoutLookback);
  if (!allowed) {
    return { ok: false, error: "personal snapshot request fields are closed" };
  }
  const jobId = typeof raw.job_id === "string" ? raw.job_id : "";
  if (!isPersonalResearchJobId(jobId)) {
    return { ok: false, error: "job_id is invalid" };
  }
  const start = isoDay(raw.period_start);
  const end = isoDay(raw.period_end);
  if (!start || !end) {
    return { ok: false, error: "period_start and period_end must be ISO dates" };
  }
  const inclusiveDays = dayNumber(end) - dayNumber(start) + 1;
  if (inclusiveDays < 1 || inclusiveDays > PERSONAL_RESEARCH_MAX_PERIOD_DAYS) {
    return {
      ok: false,
      error: `snapshot period must be 1-${PERSONAL_RESEARCH_MAX_PERIOD_DAYS} inclusive calendar dates`,
    };
  }
  const today = jstToday(now);
  if (end > today) {
    return { ok: false, error: "period_end must not be in the future" };
  }
  const closedEnd = lastClosedMonthEnd(now);
  if (end > closedEnd) {
    return {
      ok: false,
      error: "period_end must be inside a closed J-Quants calendar month",
    };
  }
  let lookback = PERSONAL_SNAPSHOT_DEFAULT_LOOKBACK_SESSIONS;
  if ("lookback_sessions" in raw) {
    if (
      typeof raw.lookback_sessions !== "number" ||
      !Number.isInteger(raw.lookback_sessions) ||
      raw.lookback_sessions < 0 ||
      raw.lookback_sessions > PERSONAL_SNAPSHOT_MAX_LOOKBACK_SESSIONS
    ) {
      return {
        ok: false,
        error: `lookback_sessions must be 0-${PERSONAL_SNAPSHOT_MAX_LOOKBACK_SESSIONS}`,
      };
    }
    lookback = raw.lookback_sessions;
  }
  return {
    ok: true,
    value: {
      job_id: jobId,
      period_start: start,
      period_end: end,
      lookback_sessions: lookback,
    },
  };
}

export function personalSnapshotManifestKey(jobId: string): string {
  if (!isPersonalResearchJobId(jobId)) {
    throw new Error("invalid personal snapshot job id");
  }
  return `research/personal/snapshot-builds/job=${jobId}/manifest.json`;
}

export function personalSnapshotObjectKey(rawSha256Hex: string): string {
  if (!/^[0-9a-f]{64}$/.test(rawSha256Hex)) {
    throw new Error("invalid personal snapshot digest");
  }
  return `research/personal/snapshots/sha256=${rawSha256Hex}.sqlite.gz`;
}

export function isPersonalSnapshotManifestKey(key: string): boolean {
  return /^research\/personal\/snapshot-builds\/job=[a-z0-9][a-z0-9._-]{0,63}\/manifest\.json$/.test(
    key,
  );
}

export function personalSnapshotJobIdFromPath(pathname: string): string | null {
  const prefix = "/v1/personal-snapshot-build/";
  if (!pathname.startsWith(prefix)) return null;
  const value = pathname.slice(prefix.length);
  return isPersonalResearchJobId(value) ? value : null;
}

export async function personalSnapshotRequestDigest(
  request: PersonalSnapshotBuildRequest,
): Promise<string> {
  const canonical = JSON.stringify({
    format: PERSONAL_SNAPSHOT_FORMAT,
    job_id: request.job_id,
    lookback_sessions: request.lookback_sessions,
    period_end: request.period_end,
    period_start: request.period_start,
    runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
  });
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}
