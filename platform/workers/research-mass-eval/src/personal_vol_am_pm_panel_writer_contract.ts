import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  isPersonalResearchJobId,
} from "./personal_research_contract";
import {
  PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
  PERSONAL_VOL_AM_PM_PRODUCER_DEPENDENCY,
} from "./personal_vol_am_pm_panel";
import {
  PERSONAL_VOL_PANELS_PREFIX,
  PERSONAL_VOL_PERIODS,
  PERSONAL_VOL_UNIVERSE_PROVENANCE,
} from "./personal_vol_research";
import { sha256Hex } from "./sha256";

export const PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID =
  PERSONAL_VOL_AM_PM_PRODUCER_DEPENDENCY.producer_id;
export const PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND = "vol-panel" as const;
export const PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION =
  PERSONAL_RESEARCH_RUNNER_VERSION;
export const PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID =
  "personal-vol-ratio-am-pm-v1" as const;
export const PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA =
  "personal-vol-ratio-am-pm-panel-writer-input/v1" as const;
export const PERSONAL_VOL_AM_PM_PANEL_WRITER_MANIFEST_SCHEMA =
  "personal-vol-ratio-am-pm-panel-writer-manifest/v1" as const;
export const PERSONAL_VOL_AM_PM_COMMON_VALID_SCHEMA =
  "personal-vol-ratio-am-pm-common-valid/v1" as const;
export const PERSONAL_VOL_AM_PM_MEMBERSHIP_DIGEST_SCHEMA =
  "personal-vol-ratio-am-pm-membership/v1" as const;
export const PERSONAL_VOL_AM_PM_REQUIRED_LOOKBACK_SESSIONS = 61;
export const PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_REQUEST_BYTES = 8 * 1024;
export const PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_INPUT_BYTES = 512 * 1024;
export const PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_SNAPSHOT_MANIFEST_BYTES =
  64 * 1024;
export const PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_LEGACY_PANEL_BYTES =
  64 * 1024 * 1024;
// Fixed <=100-code, fixed-period AM/PM panel. 100 codes * ~320 sessions of
// compact MAdjC/AAdjC rows plus index-level option maps stay well under 8 MiB.
export const PERSONAL_VOL_AM_PM_PANEL_BUILD_MAX_PANEL_BYTES = 8 * 1024 * 1024;
export const PERSONAL_VOL_AM_PM_PANEL_BUILD_TERMINAL_MAX_BYTES = 64 * 1024;
export const PERSONAL_VOL_AM_PM_PANEL_TIMEOUT_GRACE_MS = 30 * 60 * 1000;
export const PERSONAL_VOL_AM_PM_SELECTION_PERIOD = {
  period_id: "y2019_selection",
  year: 2019,
  period_start: PERSONAL_VOL_UNIVERSE_PROVENANCE.selection_reference_start,
  period_end: PERSONAL_VOL_UNIVERSE_PROVENANCE.selection_reference_end,
} as const;
export const PERSONAL_VOL_AM_PM_EVALUATION_PERIODS = PERSONAL_VOL_PERIODS;
export const PERSONAL_VOL_AM_PM_LEGACY_OPTION_PANELS_PREFIX =
  PERSONAL_VOL_PANELS_PREFIX;
export const PERSONAL_VOL_AM_PM_OPTION_REBUILD_ERROR =
  "immutable raw option evidence must be rebuilt" as const;

const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;
const PERIOD_IDS = PERSONAL_VOL_PERIODS.map((period) => period.period_id);

export type PersonalVolAmPmEvaluationPeriodId =
  (typeof PERSONAL_VOL_PERIODS)[number]["period_id"];

export type PersonalVolAmPmPanelBuildRequest = {
  job_id: string;
  selection_snapshot_job_id: string;
  period_snapshot_job_ids: Record<PersonalVolAmPmEvaluationPeriodId, string>;
  sidecar_producer_job_id: string;
};

export type ImmutableObjectRef = {
  key: string;
  etag: string;
  size: number;
  sha256: string;
};

export type SnapshotInputLock = {
  job_id: string;
  role: "selection_2019" | "evaluation_period";
  period_id: string;
  period_start: string;
  period_end: string;
  lookback_sessions: number;
  format: "personal-draft-history/v4";
  runner_version: typeof PERSONAL_RESEARCH_RUNNER_VERSION;
  manifest: ImmutableObjectRef;
  snapshot: ImmutableObjectRef & {
    raw_sha256: string;
    gzip_sha256: string;
  };
};

export type OptionSidecarLock = {
  period_id: string;
  year: number;
  period_start: string;
  period_end: string;
  schema_version: string;
  source_key: string;
  etag: string;
  size: number;
  sha256: string;
  source: {
    dataset: string;
    version: string;
    raw_input_digest: string;
    calendar_digest: string;
  };
};

export type PersonalVolAmPmPanelWriterInputManifest = {
  schema_version: typeof PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA;
  producer_id: typeof PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID;
  job_id: string;
  cohort_id: typeof PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID;
  runner_version: typeof PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION;
  panel_schema: typeof PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION;
  required_lookback_sessions: typeof PERSONAL_VOL_AM_PM_REQUIRED_LOOKBACK_SESSIONS;
  selection: SnapshotInputLock;
  periods: Record<PersonalVolAmPmEvaluationPeriodId, SnapshotInputLock>;
  sidecar_producer: {
    job_id: string;
    terminal: ImmutableObjectRef;
  };
  option_sidecars: Record<PersonalVolAmPmEvaluationPeriodId, OptionSidecarLock>;
};

export const PERSONAL_VOL_AM_PM_COMMON_VALID_REASON_CODES = [
  "predecessor_session_missing",
  "d_minus_1_basevol_missing",
  "d_minus_1_atm_iv_missing",
  "d_minus_1_skew_missing",
  "d_minus_1_cm_term_ratio_missing",
  "equity_universe_empty",
  "missing_MAdjC",
  "missing_AAdjC",
  "missing_next_AAdjC",
  "next_session_missing",
] as const;

export type PersonalVolAmPmCommonValidReasonCode =
  (typeof PERSONAL_VOL_AM_PM_COMMON_VALID_REASON_CODES)[number];

export type PersonalVolAmPmCommonValidRow = {
  date: string;
  predecessor: string | null;
  predecessor_available: boolean;
  d_minus_1_basevol: boolean;
  d_minus_1_atm_iv: boolean;
  d_minus_1_skew: boolean;
  d_minus_1_cm_term_ratio: boolean;
  d_m_decision_valid: boolean;
  d_a_fill_valid: boolean;
  next_a_valuation_valid: boolean;
  common_valid: boolean;
  reasons: PersonalVolAmPmCommonValidReasonCode[];
};

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

export async function canonicalSha256(
  value: unknown,
): Promise<`sha256:${string}`> {
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonicalJson(value)))}`;
}

export function personalVolAmPmMembershipPayload(codes: string[]): {
  codes: string[];
  schema_version: typeof PERSONAL_VOL_AM_PM_MEMBERSHIP_DIGEST_SCHEMA;
} {
  return {
    codes: [...new Set(codes)].sort(),
    schema_version: PERSONAL_VOL_AM_PM_MEMBERSHIP_DIGEST_SCHEMA,
  };
}

export async function personalVolAmPmMembershipDigest(
  codes: string[],
): Promise<`sha256:${string}`> {
  return canonicalSha256(personalVolAmPmMembershipPayload(codes));
}

export async function personalVolAmPmCommonValidDigest(
  rows: PersonalVolAmPmCommonValidRow[],
): Promise<`sha256:${string}`> {
  return canonicalSha256({
    rows,
    schema_version: PERSONAL_VOL_AM_PM_COMMON_VALID_SCHEMA,
  });
}

export function parsePersonalVolAmPmPanelBuildRequest(
  body: unknown,
):
  | { ok: true; value: PersonalVolAmPmPanelBuildRequest }
  | { ok: false; error: string } {
  if (!isObject(body)) return { ok: false, error: "body must be a JSON object" };
  const allowed = new Set([
    "job_id",
    "selection_snapshot_job_id",
    "period_snapshot_job_ids",
    "sidecar_producer_job_id",
  ]);
  const unknown = Object.keys(body).filter((key) => !allowed.has(key));
  if (unknown.length) {
    return { ok: false, error: `unknown fields: ${unknown.sort().join(",")}` };
  }
  const jobId = typeof body.job_id === "string" ? body.job_id : "";
  if (!isPersonalResearchJobId(jobId)) {
    return { ok: false, error: "job_id is invalid" };
  }
  const selectionId =
    typeof body.selection_snapshot_job_id === "string"
      ? body.selection_snapshot_job_id
      : "";
  if (!isPersonalResearchJobId(selectionId)) {
    return { ok: false, error: "selection_snapshot_job_id is invalid" };
  }
  if (!isObject(body.period_snapshot_job_ids)) {
    return { ok: false, error: "period_snapshot_job_ids must be an object" };
  }
  const periodIds = Object.keys(body.period_snapshot_job_ids).sort();
  if (JSON.stringify(periodIds) !== JSON.stringify([...PERIOD_IDS].sort())) {
    return {
      ok: false,
      error: "period_snapshot_job_ids must name the three frozen evaluation periods",
    };
  }
  const period_snapshot_job_ids = {} as Record<
    PersonalVolAmPmEvaluationPeriodId,
    string
  >;
  const seen = new Set<string>([jobId, selectionId]);
  for (const period of PERSONAL_VOL_PERIODS) {
    const value = body.period_snapshot_job_ids[period.period_id];
    if (typeof value !== "string" || !isPersonalResearchJobId(value)) {
      return {
        ok: false,
        error: `period_snapshot_job_ids.${period.period_id} is invalid`,
      };
    }
    if (seen.has(value)) {
      return {
        ok: false,
        error: "snapshot job ids must be distinct immutable build identities",
      };
    }
    seen.add(value);
    period_snapshot_job_ids[period.period_id] = value;
  }
  const sidecarJobId =
    typeof body.sidecar_producer_job_id === "string"
      ? body.sidecar_producer_job_id
      : "";
  if (!isPersonalResearchJobId(sidecarJobId)) {
    return { ok: false, error: "sidecar_producer_job_id is invalid" };
  }
  if (seen.has(sidecarJobId)) {
    return {
      ok: false,
      error: "sidecar producer job id must be a distinct immutable identity",
    };
  }
  return {
    ok: true,
    value: {
      job_id: jobId,
      selection_snapshot_job_id: selectionId,
      period_snapshot_job_ids,
      sidecar_producer_job_id: sidecarJobId,
    },
  };
}

function checkedJobId(jobId: string): string {
  if (!isPersonalResearchJobId(jobId)) {
    throw new Error("invalid personal vol AM/PM panel-build job id");
  }
  return jobId;
}

export function personalVolAmPmPanelBuildPrefix(jobId: string): string {
  return `research/personal/vol-ratio-am-pm-v1/panel-builds/job=${checkedJobId(jobId)}`;
}

export function personalVolAmPmPanelBuildInputKey(jobId: string): string {
  return `${personalVolAmPmPanelBuildPrefix(jobId)}/input-manifest.json`;
}

export function personalVolAmPmPanelBuildTerminalKey(jobId: string): string {
  return `${personalVolAmPmPanelBuildPrefix(jobId)}/manifest.json`;
}

export function personalVolAmPmPanelObjectKey(digest: string): string {
  if (!DIGEST_RE.test(digest)) {
    throw new Error("invalid personal vol AM/PM panel digest");
  }
  return `research/personal/vol-ratio-am-pm-v1/objects/${digest}.json`;
}

export function personalVolAmPmLegacyOptionPanelKey(periodId: string): string {
  if (!PERIOD_IDS.includes(periodId)) {
    throw new Error("period is outside the frozen evaluation set");
  }
  return `${PERSONAL_VOL_AM_PM_LEGACY_OPTION_PANELS_PREFIX}/${periodId}.json`;
}

export function personalVolAmPmPanelBuildJobIdFromPath(
  pathname: string,
): string | null {
  const prefix = "/v1/personal-vol-am-pm-panel-build/jobs/";
  if (!pathname.startsWith(prefix)) return null;
  const jobId = pathname.slice(prefix.length);
  return isPersonalResearchJobId(jobId) ? jobId : null;
}

export function isPersonalVolAmPmPanelDigest(value: string): boolean {
  return DIGEST_RE.test(value);
}

export function inputManifestMatchesRequest(
  parsed: unknown,
  request: PersonalVolAmPmPanelBuildRequest,
): parsed is PersonalVolAmPmPanelWriterInputManifest {
  if (!isObject(parsed) || !isObject(parsed.selection) || !isObject(parsed.periods)) {
    return false;
  }
  if (
    parsed.schema_version !== PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA ||
    parsed.producer_id !== PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID ||
    parsed.job_id !== request.job_id ||
    parsed.cohort_id !== PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID ||
    parsed.runner_version !== PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION ||
    parsed.panel_schema !== PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION ||
    parsed.selection.job_id !== request.selection_snapshot_job_id ||
    !isObject(parsed.sidecar_producer) ||
    parsed.sidecar_producer.job_id !== request.sidecar_producer_job_id
  ) {
    return false;
  }
  for (const period of PERSONAL_VOL_PERIODS) {
    const locked = parsed.periods[period.period_id];
    if (
      !isObject(locked) ||
      locked.job_id !== request.period_snapshot_job_ids[period.period_id]
    ) {
      return false;
    }
  }
  return true;
}

export async function personalVolAmPmPanelBuildRequestDigest(
  request: PersonalVolAmPmPanelBuildRequest,
  inputManifestDigest: string,
): Promise<string> {
  if (!DIGEST_RE.test(inputManifestDigest)) {
    throw new Error("input manifest digest is invalid");
  }
  return canonicalSha256({
    input_manifest_digest: inputManifestDigest,
    input_manifest_key: personalVolAmPmPanelBuildInputKey(request.job_id),
    job_id: request.job_id,
    period_snapshot_job_ids: request.period_snapshot_job_ids,
    producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
    runner_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
    selection_snapshot_job_id: request.selection_snapshot_job_id,
    sidecar_producer_job_id: request.sidecar_producer_job_id,
  });
}
