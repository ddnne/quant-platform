import { sha256Hex } from "./sha256";

export const PERSONAL_RESEARCH_RUNNER_VERSION = "personal-cloud-runner/v7";
export const PERSONAL_RESEARCH_CONTAINER_NAME = "personal-research-v7";
export const PERSONAL_RESEARCH_MAX_PERIOD_DAYS = 2200;
export const PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024;
export const PERSONAL_RESEARCH_COHORT_IDS = [
  "price-relative-v1",
  "fundamental-relative-v1",
  "diverse-core-v1",
  "compact-market-diverse-v1",
  "sector-relative-ls-v1",
] as const;
export const PERSONAL_RESEARCH_UNIVERSE_IDS = [
  "topix_all",
  "topix_core30",
  "topix_large70",
  "topix_mid400",
  "topix_small1",
  "topix_small2",
  "topix_small",
  "topix100",
  "topix500",
] as const;
const COMPACT_MARKET_UNIVERSE_IDS = new Set([
  "topix_core30",
  "topix_large70",
  "topix100",
]);
const PERSONAL_RESEARCH_UNIVERSE_RULE_DIGESTS: Record<
  PersonalResearchUniverseId,
  `sha256:${string}`
> = {
  topix_all: "sha256:7b88c89520a7cf751e7b63f160c16130183dba3c7c7e9c3a56660f3149c2c048",
  topix_core30: "sha256:f4f7436b5b9a296fa8606d677fbe2d199f1afd8d84dac186d607897b2480d3be",
  topix_large70: "sha256:984d9d9df1782b8dcd26f8c513e390e11adba08a5663601c67d247806088265b",
  topix_mid400: "sha256:802cbe1aa7f66ed7cc41606c6dd42985505cb5dec821c595e718f6defdaa8ca2",
  topix_small1: "sha256:a07600e0a63afe73c995f1c2e8f32c2bacb104699c88e91c88033ab1f75dbf01",
  topix_small2: "sha256:3a4f3dd47f65ad223ff6fbe18c9057afd75c725a0e592d9f683b8fdd9d98316e",
  topix_small: "sha256:b22d4420028a4cc4b3920f873c6e90194aef6961e04c46e239f83c13a876a71e",
  topix100: "sha256:5bfd1940e9b5dbf0eae44b4ca6ae357e8fada7eedb259ed4683e17a7bcda2b3b",
  topix500: "sha256:5034530267f4a358a80d9426fcfedfb1162b9f71c1024b54b4b39fe3547d53c6",
};

export type PersonalResearchCohortId =
  (typeof PERSONAL_RESEARCH_COHORT_IDS)[number];
export type PersonalResearchUniverseId =
  (typeof PERSONAL_RESEARCH_UNIVERSE_IDS)[number];

const PERSONAL_RESEARCH_COHORT_DIGESTS: Record<
  PersonalResearchCohortId,
  `sha256:${string}`
> = {
  "price-relative-v1":
    "sha256:013cf72dec3f9fe93b68132f8861eaa0555f08d418d9b00d80b8eb635e61c439",
  "fundamental-relative-v1":
    "sha256:c15acc9bbc44e2e5650f63a30be05351f7658145d393c995f20e102d1eff3001",
  "diverse-core-v1":
    "sha256:ea37baf3423e5d84e61d4c80c59bdfe8184342dd3dee28646bd339cd45085a84",
  "compact-market-diverse-v1":
    "sha256:e56ab7e48b1e59e583140ab7cf5382c93d40842cf946b6fb3bf06a75fe296682",
  "sector-relative-ls-v1":
    "sha256:584bbf0052ad1eee6ec31cacdf1298c13c8a59b9eb6928267935fc17e34289be",
};

const JOB_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const SHA256_RE = /^[0-9a-f]{64}$/;
const SNAPSHOT_KEY_RE =
  /^research\/personal\/snapshots\/sha256=([0-9a-f]{64})\.sqlite(?:\.gz)?$/;

export type PersonalResearchRequest = {
  cohort_id: PersonalResearchCohortId;
  universe_id: PersonalResearchUniverseId;
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
    "cohort_id",
    "job_id",
    "period_end",
    "period_start",
    "snapshot_key",
    "snapshot_sha256",
    "universe_id",
  ];
  const keys = Object.keys(raw).sort();
  if (JSON.stringify(keys) !== JSON.stringify(expected)) {
    return { ok: false, error: "personal research request fields are closed" };
  }

  const cohortId = raw.cohort_id;
  if (
    typeof cohortId !== "string" ||
    !PERSONAL_RESEARCH_COHORT_IDS.some((value) => value === cohortId)
  ) {
    return {
      ok: false,
      error: "cohort_id is not executable by personal cloud research",
    };
  }
  const jobId = typeof raw.job_id === "string" ? raw.job_id : "";
  if (!JOB_ID_RE.test(jobId)) {
    return { ok: false, error: "job_id is invalid" };
  }
  const universeId = raw.universe_id;
  if (
    typeof universeId !== "string" ||
    !PERSONAL_RESEARCH_UNIVERSE_IDS.some((value) => value === universeId)
  ) {
    return {
      ok: false,
      error: "universe_id is not executable by personal cloud research",
    };
  }
  const compactUniverse = COMPACT_MARKET_UNIVERSE_IDS.has(universeId);
  const compactCohort = cohortId === "compact-market-diverse-v1";
  if (compactUniverse !== compactCohort) {
    return {
      ok: false,
      error: compactUniverse
        ? "compact TOPIX universes require compact-market-diverse-v1"
        : "compact-market-diverse-v1 requires Core30, Large70, or TOPIX100",
    };
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
      cohort_id: cohortId as PersonalResearchCohortId,
      universe_id: universeId as PersonalResearchUniverseId,
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
    cohort_digest: personalResearchCohortDigest(request.cohort_id),
    cohort_id: request.cohort_id,
    job_id: request.job_id,
    period_end: request.period_end,
    period_start: request.period_start,
    runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
    snapshot_key: request.snapshot_key,
    snapshot_sha256: request.snapshot_sha256,
    universe_id: request.universe_id,
    universe_rule_digest: personalResearchUniverseRuleDigest(request.universe_id),
  });
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}

export function personalResearchUniverseRuleDigest(
  universeId: PersonalResearchUniverseId,
): `sha256:${string}` {
  return PERSONAL_RESEARCH_UNIVERSE_RULE_DIGESTS[universeId];
}

export function personalResearchCohortDigest(
  cohortId: PersonalResearchCohortId,
): `sha256:${string}` {
  return PERSONAL_RESEARCH_COHORT_DIGESTS[cohortId];
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
