import { sha256Hex } from "./sha256";

export const PERSONAL_SVI_2023_COHORT_ID = "personal-svi-term-2023-v1" as const;
export const PERSONAL_SVI_2023_STRATEGY_ID =
  "svi-atm-term-ratio-momentum-switch" as const;
export const PERSONAL_SVI_2023_RUNNER_VERSION =
  "personal-svi-cloud-runner/v4" as const;
export const PERSONAL_SVI_2023_PANEL_KEY =
  "research/mass_eval/panels_cache/527c1065afe14601/panels/y2023_full.json" as const;
export const PERSONAL_SVI_2023_OPTIONS_ROOT =
  "structured/jsonl/derivatives_bars_daily_options_225" as const;
export const PERSONAL_SVI_2023_EARLIEST_DAY = "2023-01-04" as const;
export const PERSONAL_SVI_2023_LATEST_DAY = "2023-10-13" as const;
export const PERSONAL_SVI_2023_WARMUP_SESSIONS = 10;
export const PERSONAL_SVI_2023_MAX_SESSIONS = 180;
export const PERSONAL_SVI_2023_MAX_OBJECTS_PER_DAY = 8;
export const PERSONAL_SVI_2023_MAX_OBJECT_BYTES = 16 * 1024 * 1024;
export const PERSONAL_SVI_2023_MAX_INPUT_BYTES = 2 * 1024 * 1024 * 1024;
export const PERSONAL_SVI_2023_MAX_PANEL_BYTES = 64 * 1024 * 1024;
export const PERSONAL_SVI_2023_DECISION_CUTOFF =
  "15:00:00+09:00" as const;
export const PERSONAL_SVI_2023_EQUITY_UNIVERSE = {
  scope_id: "legacy-liq-large-adv100-2019-v1",
  selection_rule: "adv_desc_skip_missing_bars_and_fins",
  selection_reference_start: "2019-01-01",
  selection_reference_end: "2019-10-21",
  maximum_codes: 100,
  membership: "static_fixed_panel_codes",
  daily_pit_reconstitution: false,
  topix_scale_bound: false,
  comparable_to_personal_topix_factor_runs: false,
} as const;

const JOB_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;
const OPTIONS_KEY_RE =
  /^structured\/jsonl\/derivatives_bars_daily_options_225\/dt=(2023-\d{2}-\d{2})\/[A-Za-z0-9._-]+\.jsonl$/;

export type PersonalSvi2023Request = {
  job_id: string;
  cohort_id: typeof PERSONAL_SVI_2023_COHORT_ID;
};

export type PersonalSviInputObject = {
  key: string;
  etag: string;
  size: number;
  sha256: string;
};

export type PersonalSviInputDay = {
  date: string;
  objects: PersonalSviInputObject[];
};

export type PersonalSviInputManifest = {
  schema_version: "personal-svi-2023-input/v2";
  job_id: string;
  cohort_id: typeof PERSONAL_SVI_2023_COHORT_ID;
  runner_version: typeof PERSONAL_SVI_2023_RUNNER_VERSION;
  strategy: {
    strategy_id: typeof PERSONAL_SVI_2023_STRATEGY_ID;
    feature: "svi_atm_short_over_next_minus_one";
    thesis: string;
    signal_lag_sessions: 1;
    hold_sessions: 10;
    one_way_cost: 0.001;
  };
  panel: PersonalSviInputObject;
  equity_universe: typeof PERSONAL_SVI_2023_EQUITY_UNIVERSE;
  options: {
    dataset: "derivatives_bars_daily_options_225";
    natural_key: ["Date", "Code"];
    days: PersonalSviInputDay[];
    object_count: number;
    total_bytes: number;
  };
  sessions: {
    warmup_sessions: number;
    warmup_dates: string[];
    evaluation_dates: string[];
  };
  temporal_contract: {
    source_decision_cutoff_jst: typeof PERSONAL_SVI_2023_DECISION_CUTOFF;
    signal_lag_sessions: 1;
    fill_timing: "next_close";
    first_pnl_interval: "fill_close_to_following_close";
  };
  authority: {
    draft_only: true;
    screening_only: true;
    ready: false;
    mass: false;
    promotion: false;
    live_orders: false;
    go: false;
  };
};

export function parsePersonalSvi2023Request(
  body: unknown,
):
  | { ok: true; value: PersonalSvi2023Request }
  | { ok: false; error: string } {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return { ok: false, error: "body must be a JSON object" };
  }
  const raw = body as Record<string, unknown>;
  const allowed = new Set(["cohort_id", "job_id"]);
  const unknown = Object.keys(raw).filter((key) => !allowed.has(key));
  if (unknown.length > 0) {
    return { ok: false, error: `unknown fields: ${unknown.sort().join(",")}` };
  }
  const jobId = typeof raw.job_id === "string" ? raw.job_id : "";
  if (!JOB_ID_RE.test(jobId)) return { ok: false, error: "job_id is invalid" };
  const cohortId = raw.cohort_id ?? PERSONAL_SVI_2023_COHORT_ID;
  if (cohortId !== PERSONAL_SVI_2023_COHORT_ID) {
    return {
      ok: false,
      error: `cohort_id must be ${PERSONAL_SVI_2023_COHORT_ID}`,
    };
  }
  return {
    ok: true,
    value: { job_id: jobId, cohort_id: PERSONAL_SVI_2023_COHORT_ID },
  };
}

function checkedJobId(jobId: string): string {
  if (!JOB_ID_RE.test(jobId)) throw new Error("invalid personal SVI job id");
  return jobId;
}

export function personalSviPrefix(jobId: string): string {
  return `research/personal/svi-2023/job=${checkedJobId(jobId)}`;
}

export function personalSviInputManifestKey(jobId: string): string {
  return `${personalSviPrefix(jobId)}/input-manifest.json`;
}

export function personalSviFeatureKey(jobId: string): string {
  return `${personalSviPrefix(jobId)}/features.jsonl`;
}

export function personalSviReportKey(jobId: string): string {
  return `${personalSviPrefix(jobId)}/report.json`;
}

export function personalSviTerminalManifestKey(jobId: string): string {
  return `${personalSviPrefix(jobId)}/manifest.json`;
}

export function personalSviJobIdFromPath(pathname: string): string | null {
  const prefix = "/v1/personal-svi-2023/jobs/";
  if (!pathname.startsWith(prefix)) return null;
  const jobId = pathname.slice(prefix.length);
  return JOB_ID_RE.test(jobId) ? jobId : null;
}

export function optionsDayPrefix(day: string): string {
  if (
    !/^2023-\d{2}-\d{2}$/.test(day) ||
    day < PERSONAL_SVI_2023_EARLIEST_DAY ||
    day > PERSONAL_SVI_2023_LATEST_DAY
  ) {
    throw new Error("options day is outside the fixed 2023 window");
  }
  return `${PERSONAL_SVI_2023_OPTIONS_ROOT}/dt=${day}/`;
}

export function optionsDayFromKey(key: string): string | null {
  const match = OPTIONS_KEY_RE.exec(key);
  if (!match) return null;
  const day = match[1];
  return day >= PERSONAL_SVI_2023_EARLIEST_DAY &&
    day <= PERSONAL_SVI_2023_LATEST_DAY
    ? day
    : null;
}

export function isPersonalSviDigest(value: string): boolean {
  return DIGEST_RE.test(value);
}

export async function personalSviJobRequestDigest(
  request: PersonalSvi2023Request,
  inputManifestDigest: string,
): Promise<string> {
  if (!DIGEST_RE.test(inputManifestDigest)) {
    throw new Error("input manifest digest is invalid");
  }
  const canonical = JSON.stringify({
    cohort_id: request.cohort_id,
    input_manifest_digest: inputManifestDigest,
    input_manifest_key: personalSviInputManifestKey(request.job_id),
    job_id: request.job_id,
    runner_version: PERSONAL_SVI_2023_RUNNER_VERSION,
    strategy_id: PERSONAL_SVI_2023_STRATEGY_ID,
  });
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}

export function isPersonalSviJobId(value: string): boolean {
  return JOB_ID_RE.test(value);
}
