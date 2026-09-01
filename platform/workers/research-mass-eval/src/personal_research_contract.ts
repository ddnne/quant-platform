import { sha256Hex } from "./sha256";

export const PERSONAL_RESEARCH_RUNNER_VERSION = "personal-cloud-runner/v15";
export const PERSONAL_RESEARCH_RUNNER_SLOT = "v15";
export const PERSONAL_RESEARCH_LEGACY_CONTAINER_NAME = "personal-research-v12";
export const PERSONAL_SNAPSHOT_CONTAINER_NAME = "personal-snapshot-v16";
export const PERSONAL_SNAPSHOT_SOURCE_RUNNER_VERSIONS = [
  "personal-cloud-runner/v13",
  "personal-cloud-runner/v14",
  "personal-cloud-runner/v15",
] as const;
export type PersonalSnapshotSourceRunnerVersion =
  (typeof PERSONAL_SNAPSHOT_SOURCE_RUNNER_VERSIONS)[number];
export const PERSONAL_RESEARCH_MAX_PERIOD_DAYS = 7000;
export const PERSONAL_RESEARCH_MAX_CONCURRENT_JOBS = 8;
// Compressed R2/HTTP snapshot transport (gzip or legacy raw sqlite).
export const PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024 * 1024;
// Expanded sqlite after gunzip, and snapshot-builder physical cap.
export const PERSONAL_SNAPSHOT_MAX_DATABASE_BYTES = 5 * 1024 * 1024 * 1024;
export type PersonalContainerKind =
  | "research"
  | "svi"
  | "overlay"
  | "snapshot"
  | "vol-panel"
  | "option-sidecar";
export const PERSONAL_RESEARCH_LEGACY_COHORT_IDS = [
  "price-relative-v1",
  "fundamental-relative-v1",
  "diverse-core-v1",
  "compact-market-diverse-v1",
  "sector-relative-ls-v1",
] as const;
export const PERSONAL_RESEARCH_AM_PM_COHORT_IDS = [
  "price-relative-am-pm-v1",
  "fundamental-relative-am-pm-v1",
  "diverse-core-am-pm-v1",
  "compact-market-diverse-am-pm-v1",
  "sector-relative-ls-am-pm-v1",
] as const;
export const PERSONAL_RESEARCH_COHORT_IDS = [
  ...PERSONAL_RESEARCH_LEGACY_COHORT_IDS,
  ...PERSONAL_RESEARCH_AM_PM_COHORT_IDS,
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
const COMPACT_MARKET_COHORT_IDS = new Set([
  "compact-market-diverse-v1",
  "compact-market-diverse-am-pm-v1",
]);
export type PersonalResearchUniverseDecisionCutoff =
  | "session_close"
  | "morning_close";

const PERSONAL_RESEARCH_UNIVERSE_RULE_DIGESTS: Record<
  PersonalResearchUniverseDecisionCutoff,
  Record<PersonalResearchUniverseId, `sha256:${string}`>
> = {
  session_close: {
    topix_all:
      "sha256:7b88c89520a7cf751e7b63f160c16130183dba3c7c7e9c3a56660f3149c2c048",
    topix_core30:
      "sha256:f4f7436b5b9a296fa8606d677fbe2d199f1afd8d84dac186d607897b2480d3be",
    topix_large70:
      "sha256:984d9d9df1782b8dcd26f8c513e390e11adba08a5663601c67d247806088265b",
    topix_mid400:
      "sha256:802cbe1aa7f66ed7cc41606c6dd42985505cb5dec821c595e718f6defdaa8ca2",
    topix_small1:
      "sha256:a07600e0a63afe73c995f1c2e8f32c2bacb104699c88e91c88033ab1f75dbf01",
    topix_small2:
      "sha256:3a4f3dd47f65ad223ff6fbe18c9057afd75c725a0e592d9f683b8fdd9d98316e",
    topix_small:
      "sha256:b22d4420028a4cc4b3920f873c6e90194aef6961e04c46e239f83c13a876a71e",
    topix100:
      "sha256:5bfd1940e9b5dbf0eae44b4ca6ae357e8fada7eedb259ed4683e17a7bcda2b3b",
    topix500:
      "sha256:5034530267f4a358a80d9426fcfedfb1162b9f71c1024b54b4b39fe3547d53c6",
  },
  morning_close: {
    topix_all:
      "sha256:ba0c9af6b51121e6c27d660ccd28ae3e1a7c8af1ae3ffcff4986bf3f31247fd9",
    topix_core30:
      "sha256:efebd89f449432107fc967d33ac4fe8759e370ffc50f9b5ce7fdd82afb1aba23",
    topix_large70:
      "sha256:d5ee4eb7a64c7ecd855ffa662f89c984f6f3fcf570c36e701411ec10b51d2a1d",
    topix_mid400:
      "sha256:66161a0c625382cb582b23c9e6d899791142e3dbcbc2df1f0f71d2b6f4b15109",
    topix_small1:
      "sha256:4b4ba033407f136327746d7c072bc74f532f19fa1942a1f775fd35ab13473977",
    topix_small2:
      "sha256:9beea793736b46270350a98cbd20ebaf04bda38b63ebb087fe96be6b7b575162",
    topix_small:
      "sha256:59aff93c430e67fb89bc77bb374bc0eeddbd5ea18178b96ac09bd8ecd2b1d592",
    topix100:
      "sha256:bd4b5e33e76a1bf63fd1d7ddbbfb15141a36c4be92dc4f961c1b3a5b4e347eac",
    topix500:
      "sha256:8ca72cf8c134ad082605fd948cf005b73124643b106a68521174b009442046fb",
  },
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
  "price-relative-am-pm-v1":
    "sha256:34e304efb8ff848a268a1e563985d1456316edf1b9ca874eba7262377e17db93",
  "fundamental-relative-am-pm-v1":
    "sha256:9bc404066d3e705e085380a3c2f15bac41c8a24a931b12518ab92abbddcaf67f",
  "diverse-core-am-pm-v1":
    "sha256:77136481d8a6b20fb8dc8188b8d6adb2837050b8185a8f8abac92ca10811adde",
  "compact-market-diverse-am-pm-v1":
    "sha256:b1c96581aa3f24a9f4df65126c4dd8c443ddb965e7105f9bbea392e72e383eb0",
  "sector-relative-ls-am-pm-v1":
    "sha256:e12e65393985ab8b7cc2b0b922a362a055404777a49fda7250f735d47f0b073b",
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
  const compactCohort = COMPACT_MARKET_COHORT_IDS.has(cohortId);
  if (compactUniverse !== compactCohort) {
    return {
      ok: false,
      error: compactUniverse
        ? "compact TOPIX universes require compact-market-diverse-v1 or compact-market-diverse-am-pm-v1"
        : "compact-market-diverse cohorts require Core30, Large70, or TOPIX100",
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
  const inclusiveDays = dayNumber(end) - dayNumber(start) + 1;
  if (inclusiveDays < 2 || inclusiveDays > PERSONAL_RESEARCH_MAX_PERIOD_DAYS) {
    return {
      ok: false,
      error: `research period must be 2-${PERSONAL_RESEARCH_MAX_PERIOD_DAYS} inclusive calendar dates`,
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
    universe_rule_digest: personalResearchUniverseRuleDigest(
      request.universe_id,
      request.cohort_id,
    ),
  });
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}

export function personalResearchUniverseDecisionCutoff(
  cohortId: PersonalResearchCohortId,
): PersonalResearchUniverseDecisionCutoff {
  return PERSONAL_RESEARCH_AM_PM_COHORT_IDS.some((value) => value === cohortId)
    ? "morning_close"
    : "session_close";
}

export function personalResearchUniverseRuleDigest(
  universeId: PersonalResearchUniverseId,
  cohortId: PersonalResearchCohortId,
): `sha256:${string}` {
  return PERSONAL_RESEARCH_UNIVERSE_RULE_DIGESTS[
    personalResearchUniverseDecisionCutoff(cohortId)
  ][universeId];
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

export function personalSnapshotContainerName(): string {
  return PERSONAL_SNAPSHOT_CONTAINER_NAME;
}

export async function personalJobContainerName(
  kind: Exclude<PersonalContainerKind, "snapshot">,
  jobId: string,
): Promise<string> {
  if (!JOB_ID_RE.test(jobId)) {
    throw new Error("invalid personal container job id");
  }
  const digest = await sha256Hex(
    new TextEncoder().encode(
      `${PERSONAL_RESEARCH_RUNNER_VERSION}:${kind}:${jobId}`,
    ),
  );
  return `personal-${PERSONAL_RESEARCH_RUNNER_SLOT}-${kind}-${digest.slice(0, 24)}`;
}

export function isPersonalSnapshotSourceRunnerVersion(
  value: unknown,
): value is PersonalSnapshotSourceRunnerVersion {
  return (
    value === "personal-cloud-runner/v13" ||
    value === "personal-cloud-runner/v14" ||
    value === "personal-cloud-runner/v15"
  );
}
