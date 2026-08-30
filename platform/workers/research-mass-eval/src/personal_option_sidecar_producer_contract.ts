import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  isPersonalResearchJobId,
} from "./personal_research_contract";
import {
  PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY,
  PERSONAL_VOL_AM_PM_SESSION_DATES_DIGEST_SCHEMA,
} from "./personal_vol_am_pm_panel";
import { PERSONAL_VOL_SOURCE_IDENTITY } from "./personal_vol_research";
import { sha256Hex } from "./sha256";

export const PERSONAL_OPTION_SIDECAR_KIND = "option-sidecar" as const;
export const PERSONAL_OPTION_SIDECAR_PRODUCER_ID =
  "personal-n225-option-sidecar-producer/v1" as const;
export const PERSONAL_OPTION_SIDECAR_COHORT_ID =
  "personal-n225-option-sidecar/v1" as const;
export const PERSONAL_OPTION_SIDECAR_RUNNER_VERSION =
  PERSONAL_RESEARCH_RUNNER_VERSION;
export const PERSONAL_OPTION_SIDECAR_INPUT_SCHEMA =
  "personal-n225-option-sidecar-input/v1" as const;
export const PERSONAL_OPTION_SIDECAR_MANIFEST_SCHEMA =
  "personal-n225-option-sidecar-manifest/v1" as const;
export const PERSONAL_OPTION_SIDECAR_OBJECT_SCHEMA =
  "personal-n225-option-sidecar/v1" as const;
export const PERSONAL_OPTION_SIDECAR_OPTIONS_ROOT =
  "structured/jsonl/derivatives_bars_daily_options_225" as const;
export const PERSONAL_OPTION_SIDECAR_CALENDAR_ROOT =
  "structured/jsonl/markets_calendar" as const;
export const PERSONAL_OPTION_SIDECAR_DATASET =
  PERSONAL_VOL_SOURCE_IDENTITY.dataset;
export const PERSONAL_OPTION_SIDECAR_SOURCE_VERSION =
  PERSONAL_VOL_SOURCE_IDENTITY.version;
export const PERSONAL_OPTION_SIDECAR_WARMUP_SESSIONS = 61;
export const PERSONAL_OPTION_SIDECAR_RECORDS_SCHEMA = "jquants_records/v1" as const;
export const PERSONAL_OPTION_SIDECAR_MAX_REQUEST_BYTES = 8 * 1024;
export const PERSONAL_OPTION_SIDECAR_MAX_OBJECTS_PER_DAY = 8;
export const PERSONAL_OPTION_SIDECAR_MAX_OBJECT_BYTES = 16 * 1024 * 1024;
export const PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_OBJECT_BYTES = 64 * 1024;
export const PERSONAL_OPTION_SIDECAR_MAX_INPUT_BYTES = 2 * 1024 * 1024;
export const PERSONAL_OPTION_SIDECAR_MAX_OUTPUT_BYTES = 8 * 1024 * 1024;
export const PERSONAL_OPTION_SIDECAR_TERMINAL_MAX_BYTES = 64 * 1024;
export const PERSONAL_OPTION_SIDECAR_TIMEOUT_GRACE_MS = 30 * 60 * 1000;

// Live staging inventory for the exact three frozen periods (design-cap source).
export const PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_OBJECTS = 651;
export const PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_DATES = 650;
export const PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_ROWS = 3_031_214;
export const PERSONAL_OPTION_SIDECAR_LIVE_OPTIONS_BYTES = 3_419_223_324;
export const PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_OBJECTS = 33;
export const PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_ROWS = 960;
export const PERSONAL_OPTION_SIDECAR_LIVE_CALENDAR_BYTES = 318_720;

// 5 GiB / 4M rows sit above 3.419 GB / 3.031M live and below a 12 GB all-rows OOM.
export const PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_OBJECTS = 1024;
export const PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_ROWS = 4_000_000;
export const PERSONAL_OPTION_SIDECAR_MAX_OPTIONS_BYTES = 5 * 1024 * 1024 * 1024;
export const PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_SCAN_OBJECTS = 512;
export const PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_SCAN_BYTES = 4 * 1024 * 1024;
export const PERSONAL_OPTION_SIDECAR_MAX_CALENDAR_PERIOD_OBJECTS = 64;

export const PERSONAL_OPTION_SIDECAR_DUPLICATE_RESOLUTION = {
  natural_key: ["Date", "Code"],
  compare: ["ingested_at", "object_key", "line_index"],
  winner: "lexicographic_max",
} as const;

export const PERSONAL_OPTION_SIDECAR_AUTHORITY = {
  draft_only: true,
  screening_only: true,
  ready: false,
  mass: false,
  promotion: false,
  live_orders: false,
  go: false,
  not_a_pass: true,
} as const;

export const PERSONAL_OPTION_SIDECAR_PERIODS = [
  {
    period_id: "y2021_full",
    year: 2021,
    raw_start: "2020-10-05",
    period_start: "2021-01-04",
    period_end: "2021-10-15",
    evaluation_sessions: 193,
    warmup_sessions: PERSONAL_OPTION_SIDECAR_WARMUP_SESSIONS,
  },
  {
    period_id: "y2023_full",
    year: 2023,
    raw_start: "2022-10-04",
    period_start: "2023-01-04",
    period_end: "2023-10-13",
    evaluation_sessions: 193,
    warmup_sessions: PERSONAL_OPTION_SIDECAR_WARMUP_SESSIONS,
  },
  {
    period_id: "y2025_q4",
    year: 2025,
    raw_start: "2025-06-04",
    period_start: "2025-09-01",
    period_end: "2025-12-29",
    evaluation_sessions: 81,
    warmup_sessions: PERSONAL_OPTION_SIDECAR_WARMUP_SESSIONS,
  },
] as const;

export type PersonalOptionSidecarPeriodId =
  (typeof PERSONAL_OPTION_SIDECAR_PERIODS)[number]["period_id"];

export type PersonalOptionSidecarPeriod =
  (typeof PERSONAL_OPTION_SIDECAR_PERIODS)[number];

export type PersonalOptionSidecarProduceRequest = {
  job_id: string;
};

export type StructuredObjectRef = {
  key: string;
  etag: string;
  size: number;
  sha256: string;
  dataset: string;
  run_id: string;
  date: string;
  schema: string;
  count: number;
  bytes: number;
};

export type StructuredDayLock = {
  date: string;
  objects: StructuredObjectRef[];
};

export type OptionSidecarPeriodLock = {
  period_id: PersonalOptionSidecarPeriodId;
  year: number;
  raw_start: string;
  period_start: string;
  period_end: string;
  warmup_sessions: number;
  evaluation_sessions: number;
  warmup_dates: string[];
  evaluation_dates: string[];
  calendar_digest: string;
  raw_input_digest: string;
  calendar: StructuredObjectRef[];
  options: StructuredDayLock[];
};

export type PersonalOptionSidecarInputManifest = {
  schema_version: typeof PERSONAL_OPTION_SIDECAR_INPUT_SCHEMA;
  producer_id: typeof PERSONAL_OPTION_SIDECAR_PRODUCER_ID;
  job_id: string;
  cohort_id: typeof PERSONAL_OPTION_SIDECAR_COHORT_ID;
  runner_version: typeof PERSONAL_OPTION_SIDECAR_RUNNER_VERSION;
  dataset: typeof PERSONAL_OPTION_SIDECAR_DATASET;
  source_version: typeof PERSONAL_OPTION_SIDECAR_SOURCE_VERSION;
  duplicate_resolution: typeof PERSONAL_OPTION_SIDECAR_DUPLICATE_RESOLUTION;
  session_calendar: typeof PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY;
  periods: Record<PersonalOptionSidecarPeriodId, OptionSidecarPeriodLock>;
};

const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;
const OPTIONS_KEY_RE =
  /^structured\/jsonl\/derivatives_bars_daily_options_225\/dt=(\d{4}-\d{2}-\d{2})\/[A-Za-z0-9._-]+\.jsonl$/;
const CALENDAR_KEY_RE =
  /^structured\/jsonl\/markets_calendar\/dt=(\d{4}-\d{2}-\d{2})\/[A-Za-z0-9._-]+\.jsonl$/;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isPersonalOptionSidecarDigest(value: string): boolean {
  return DIGEST_RE.test(value);
}

export function parsePersonalOptionSidecarProduceRequest(
  body: unknown,
):
  | { ok: true; value: PersonalOptionSidecarProduceRequest }
  | { ok: false; error: string } {
  if (!isObject(body)) return { ok: false, error: "body must be a JSON object" };
  const unknown = Object.keys(body).filter((key) => key !== "job_id");
  if (unknown.length > 0) {
    return { ok: false, error: `unknown fields: ${unknown.sort().join(",")}` };
  }
  const jobId = typeof body.job_id === "string" ? body.job_id : "";
  if (!isPersonalResearchJobId(jobId)) {
    return { ok: false, error: "job_id is invalid" };
  }
  return { ok: true, value: { job_id: jobId } };
}

function checkedJobId(jobId: string): string {
  if (!isPersonalResearchJobId(jobId)) {
    throw new Error("invalid personal option sidecar job id");
  }
  return jobId;
}

export function personalOptionSidecarPrefix(jobId: string): string {
  return `research/personal/option-sidecar/job=${checkedJobId(jobId)}`;
}

export function personalOptionSidecarInputKey(jobId: string): string {
  return `${personalOptionSidecarPrefix(jobId)}/input-manifest.json`;
}

export function personalOptionSidecarTerminalKey(jobId: string): string {
  return `${personalOptionSidecarPrefix(jobId)}/manifest.json`;
}

export function personalOptionSidecarObjectKey(digest: string): string {
  if (!DIGEST_RE.test(digest)) {
    throw new Error("invalid personal option sidecar digest");
  }
  return `research/personal/option-sidecar/objects/${digest}.json`;
}

export function personalOptionSidecarJobIdFromPath(
  pathname: string,
): string | null {
  const prefix = "/v1/personal-option-sidecar-produce/jobs/";
  if (!pathname.startsWith(prefix)) return null;
  const jobId = pathname.slice(prefix.length);
  return isPersonalResearchJobId(jobId) ? jobId : null;
}

export function optionsDayFromKey(key: string): string | null {
  const match = OPTIONS_KEY_RE.exec(key);
  return match ? match[1] : null;
}

export function calendarDayFromKey(key: string): string | null {
  const match = CALENDAR_KEY_RE.exec(key);
  return match ? match[1] : null;
}

export function optionsDayPrefix(day: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) {
    throw new Error("options day is invalid");
  }
  return `${PERSONAL_OPTION_SIDECAR_OPTIONS_ROOT}/dt=${day}/`;
}

export function calendarDayPrefix(day: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) {
    throw new Error("calendar day is invalid");
  }
  return `${PERSONAL_OPTION_SIDECAR_CALENDAR_ROOT}/dt=${day}/`;
}

export function calendarRootPrefix(): string {
  return `${PERSONAL_OPTION_SIDECAR_CALENDAR_ROOT}/`;
}

export function monthStartDay(day: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) {
    throw new Error("calendar day is invalid");
  }
  return `${day.slice(0, 7)}-01`;
}

export function addIsoDays(day: string, delta: number): string {
  const date = new Date(`${day}T00:00:00.000Z`);
  date.setUTCDate(date.getUTCDate() + delta);
  return date.toISOString().slice(0, 10);
}

export function isoDaysInclusive(start: string, end: string): string[] {
  if (start > end) return [];
  const out: string[] = [];
  for (let day = start; day <= end; day = addIsoDays(day, 1)) out.push(day);
  return out;
}

export function periodById(
  periodId: string,
): PersonalOptionSidecarPeriod | null {
  return (
    PERSONAL_OPTION_SIDECAR_PERIODS.find(
      (period) => period.period_id === periodId,
    ) ?? null
  );
}

export function splitFrozenSessions(
  period: PersonalOptionSidecarPeriod,
  tradingDates: string[],
):
  | { ok: true; warmup: string[]; evaluation: string[] }
  | { ok: false; error: string } {
  const ordered = [...new Set(tradingDates)].sort();
  if (ordered.length !== tradingDates.length) {
    return { ok: false, error: "option_sidecar_calendar_dates_not_unique" };
  }
  const warmup = ordered.filter(
    (day) => day >= period.raw_start && day < period.period_start,
  );
  const evaluation = ordered.filter(
    (day) => day >= period.period_start && day <= period.period_end,
  );
  if (
    ordered[0] !== period.raw_start ||
    ordered[ordered.length - 1] !== period.period_end ||
    warmup.length !== period.warmup_sessions ||
    evaluation.length !== period.evaluation_sessions ||
    warmup[0] !== period.raw_start ||
    evaluation[0] !== period.period_start ||
    evaluation[evaluation.length - 1] !== period.period_end ||
    ordered.length !== period.warmup_sessions + period.evaluation_sessions ||
    JSON.stringify(ordered) !== JSON.stringify([...warmup, ...evaluation])
  ) {
    return { ok: false, error: "option_sidecar_calendar_closure_failed" };
  }
  return { ok: true, warmup, evaluation };
}

export function samplePinnedDates(
  start: string,
  end: string,
  count: number,
): string[] {
  const all = isoDaysInclusive(start, end);
  if (count < 2 || all.length < count) {
    throw new Error("pinned date window is too short");
  }
  if (all.length === count) return all;
  const drop = all.length - count;
  const dropAt = new Set<number>();
  for (let index = 0; index < drop; index += 1) {
    dropAt.add(1 + Math.floor((index * (all.length - 2)) / drop));
  }
  return all.filter((_, index) => !dropAt.has(index));
}

export async function canonicalSha256(value: unknown): Promise<`sha256:${string}`> {
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonicalJson(value)))}`;
}

export function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean" || typeof value === "number") {
    if (typeof value === "number" && !Number.isFinite(value)) {
      throw new Error("canonical json rejects non-finite numbers");
    }
    return JSON.stringify(value);
  }
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  if (!isObject(value)) {
    throw new Error("canonical json rejects this value");
  }
  const keys = Object.keys(value).sort();
  return `{${keys
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
    .join(",")}}`;
}

export async function personalOptionSidecarRequestDigest(
  request: PersonalOptionSidecarProduceRequest,
  inputManifestDigest: string,
): Promise<string> {
  if (!DIGEST_RE.test(inputManifestDigest)) {
    throw new Error("input manifest digest is invalid");
  }
  return canonicalSha256({
    cohort_id: PERSONAL_OPTION_SIDECAR_COHORT_ID,
    duplicate_resolution: PERSONAL_OPTION_SIDECAR_DUPLICATE_RESOLUTION,
    input_manifest_digest: inputManifestDigest,
    input_manifest_key: personalOptionSidecarInputKey(request.job_id),
    job_id: request.job_id,
    periods: PERSONAL_OPTION_SIDECAR_PERIODS.map((period) => period.period_id),
    producer_id: PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
    runner_version: PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
  });
}

export async function calendarDatesDigest(dates: string[]): Promise<`sha256:${string}`> {
  return canonicalSha256({
    ordered_session_dates: dates,
    schema_version: PERSONAL_VOL_AM_PM_SESSION_DATES_DIGEST_SCHEMA,
  });
}

export { PERSONAL_VOL_AM_PM_SESSION_CALENDAR_IDENTITY };
