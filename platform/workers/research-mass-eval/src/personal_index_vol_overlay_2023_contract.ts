import { sha256Hex } from "./sha256";

export const PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID =
  "personal-index-vol-overlay-2023-v1" as const;
export const PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID =
  "personal-index-smile-transport-2023-v1" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID =
  "personal-index-vol-overlay-2023-am-pm-v1" as const;
export const PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID =
  "personal-index-smile-transport-2023-am-pm-v1" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION =
  "personal-index-vol-overlay-cloud-runner/v1" as const;
export const PERSONAL_INDEX_SMILE_TRANSPORT_2023_RUNNER_VERSION =
  "personal-index-smile-transport-cloud-runner/v1" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION =
  "personal-index-vol-overlay-am-pm-cloud-runner/v1" as const;
export const PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_RUNNER_VERSION =
  "personal-index-smile-transport-am-pm-cloud-runner/v1" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY =
  "2023-01-04" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY =
  "2023-10-13" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY =
  "RV20_20_RETURN_WARMUP_PLUS_INCLUSIVE_126_RATIO_HISTORY" as const;
export const PERSONAL_INDEX_SMILE_TRANSPORT_2023_SIGNAL_START_POLICY =
  "BETA_MIN_63_PAIRS_PLUS_OFFICIAL_D_MINUS_1_AND_D_PLUS_2" as const;
export const PERSONAL_INDEX_SMILE_TRANSPORT_CANDIDATE_IDS = [
  "n225_sticky_strike_downside_smile_term_surprise_v1",
  "n225_sticky_moneyness_downside_smile_term_surprise_v1",
  "n225_sticky_strike_potential_minimum_transport_v1",
  "n225_sticky_moneyness_potential_minimum_transport_v1",
] as const;
export const PERSONAL_INDEX_VOL_OVERLAY_AM_PM_CANDIDATE_IDS = [
  "n225_basevol_10_over_60_defensive_am_pm_v1",
  "n225_atmiv_over_topix_rv20_normalized_126_am_pm_v1",
  "n225_observed_front_over_next_atm_am_pm_v1",
  "n225_observed_downside_smile_front_over_next_am_pm_v1",
] as const;
export const PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS = [
  "n225_sticky_strike_downside_smile_term_surprise_am_pm_v1",
  "n225_sticky_moneyness_downside_smile_term_surprise_am_pm_v1",
  "n225_sticky_strike_potential_minimum_transport_am_pm_v1",
  "n225_sticky_moneyness_potential_minimum_transport_am_pm_v1",
] as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_SIGNAL_START_POLICY =
  "D_MINUS_1_OPTION_HISTORY_PLUS_D_AM_BETA_AND_D_PLUS_1_PM" as const;
export const PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_SIGNAL_START_POLICY =
  "BETA_MIN_63_PAIRS_PLUS_OFFICIAL_D_MINUS_2_AND_D_PLUS_1_PM" as const;
export const PERSONAL_INDEX_AM_PM_BASE_COHORT_ID =
  "sector-relative-ls-am-pm-v1" as const;
export const PERSONAL_INDEX_SMILE_TRANSPORT_CORE_VERSION =
  "research-options-225-smile-transport/v1" as const;
export const PERSONAL_INDEX_SMILE_TRANSPORT_CORE_MODULE =
  "packages/product/research/options_225_smile_transport.py" as const;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_INPUT_MAX_BYTES = 1024 * 1024;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_RESULT_MAX_BYTES = 32 * 1024 * 1024;
export const PERSONAL_INDEX_VOL_OVERLAY_2023_TERMINAL_MAX_BYTES = 64 * 1024;

const JOB_ID_RE = /^[a-z0-9][a-z0-9._-]{0,63}$/;
const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;

export type PersonalIndexVolOverlay2023CohortId =
  | typeof PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID
  | typeof PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID
  | typeof PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID
  | typeof PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID;

export type PersonalIndexVolOverlay2023Request = {
  job_id: string;
  cohort_id: PersonalIndexVolOverlay2023CohortId;
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

type OverlaySourceBlock = {
  job_id: string;
  result: ImmutableInputReference;
  snapshot: SnapshotInputReference;
  sleeve_artifact: {
    archive_member: string;
    sha256: string;
  };
};

type OverlaySviBlock = {
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

type OverlayAuthority = {
  draft_only: true;
  screening_only: true;
  ready: false;
  mass: false;
  promotion: false;
  live_orders: false;
  go: false;
  single_stock_option_iv: "FORBIDDEN";
};

export type PersonalIndexVolOverlay2023InputManifest = {
  schema_version: "personal-index-vol-overlay-2023-input/v1";
  job_id: string;
  cohort_id: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID;
  runner_version: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION;
  base: OverlaySourceBlock;
  svi: OverlaySviBlock;
  fixed_window: {
    start: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY;
    end: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY;
    signal_start_policy: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY;
    signal_end_policy: "LAST_SESSION_MINUS_TWO";
  };
  temporal_contract: {
    source_decision_cutoff_jst: "15:00:00+09:00";
    prepared_available_at: "SAME_DAY_23_59_59_JST";
    fill_timing: "next_close";
    first_pnl_interval: "fill_close_to_following_close";
    no_forward_fill: true;
  };
  authority: OverlayAuthority;
};

export type PersonalIndexSmileTransport2023InputManifest = {
  schema_version: "personal-index-smile-transport-2023-input/v2";
  job_id: string;
  cohort_id: typeof PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID;
  runner_version: typeof PERSONAL_INDEX_SMILE_TRANSPORT_2023_RUNNER_VERSION;
  base: OverlaySourceBlock;
  svi: OverlaySviBlock;
  fixed_window: {
    start: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY;
    end: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY;
    signal_start_policy: typeof PERSONAL_INDEX_SMILE_TRANSPORT_2023_SIGNAL_START_POLICY;
    signal_end_policy: "LAST_SESSION_MINUS_TWO";
  };
  temporal_contract: {
    source_decision_cutoff_jst: "15:00:00+09:00";
    prepared_available_at: "NO_EARLIER_THAN_D_23_59_59_JST";
    fill_timing: "next_close";
    first_pnl_interval: "fill_close_to_following_close";
    no_forward_fill: true;
    no_expiry_rank_substitution: true;
    no_extrapolation: true;
    d_minus_1_rule: "immediately_preceding_official_session";
  };
  candidates: {
    ids: typeof PERSONAL_INDEX_SMILE_TRANSPORT_CANDIDATE_IDS;
    sticky_models: ["sticky_strike", "sticky_moneyness"];
    families: ["downside_smile_term_surprise", "potential_minimum_transport"];
    selection: "NOT_PERFORMED";
    adaptive_model_switch: false;
  };
  formulas: {
    downside_q: "actual_downside_smile_term_ratio/predicted_downside_smile_term_ratio-1";
    downside_g: "clip(1/(1+q),0.5,1.0)";
    potential_minimum_M: "(abs(e_front)+abs(e_next))/2+abs(e_next-e_front)";
    potential_minimum_g: "clip(1/(1+M/0.10),0.5,1.0)";
    hedge_h: "clip(-g*beta_D,-1.5,1.5)";
  };
  gate: {
    min_common_valid_signal_days: 40;
    min_distinct_calendar_months: 4;
    common_invalid_policy: "flatten_g0_h0_at_d_plus_1_close_prior";
  };
  core: {
    version: typeof PERSONAL_INDEX_SMILE_TRANSPORT_CORE_VERSION;
    module: typeof PERSONAL_INDEX_SMILE_TRANSPORT_CORE_MODULE;
  };
  physical_potential: {
    metaphor_only: true;
    causal_claim: false;
  };
  svi_features_jsonl: {
    trusted_for_transport: false;
    reason: "lacks_exact_expiry_svi_parameters_and_fit_bands";
  };
  authority: OverlayAuthority;
};

type AmPmTemporalContract = {
  source_decision_cutoff_jst: "11:30:00+09:00";
  equity_am_usable_by_jst: "12:30:00+09:00";
  prepared_available_at: "NO_LATER_THAN_D_12_30_JST";
  fill_timing: "d_pm_aadjc";
  first_pnl_interval: "d_pm_to_d_plus_1_pm";
  order_sizing: "d_am_price";
  option_signal_as_of: "through_d_minus_1";
  no_forward_fill: true;
  no_full_close_fallback: true;
  no_recovery_promotion: true;
};

export type PersonalIndexVolOverlay2023AmPmInputManifest = {
  schema_version: "personal-index-vol-overlay-2023-am-pm-input/v1";
  job_id: string;
  cohort_id: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID;
  runner_version: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION;
  base: OverlaySourceBlock;
  svi: OverlaySviBlock;
  fixed_window: {
    start: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY;
    end: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY;
    signal_start_policy: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_SIGNAL_START_POLICY;
    signal_end_policy: "LAST_SESSION_MINUS_ONE";
  };
  temporal_contract: AmPmTemporalContract;
  candidates: {
    ids: typeof PERSONAL_INDEX_VOL_OVERLAY_AM_PM_CANDIDATE_IDS;
    selection: "NOT_PERFORMED";
    adaptive_model_switch: false;
  };
  selection: "NOT_PERFORMED";
  proxy_mapping: {
    executable_hedge_code: "13060";
    n225_etf_if_required: "13210";
    cash_index_executable_fill_claim: false;
    tracking_basis_risk: true;
  };
  authority: OverlayAuthority;
};

export type PersonalIndexSmileTransport2023AmPmInputManifest = {
  schema_version: "personal-index-smile-transport-2023-am-pm-input/v1";
  job_id: string;
  cohort_id: typeof PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID;
  runner_version: typeof PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_RUNNER_VERSION;
  base: OverlaySourceBlock;
  svi: OverlaySviBlock;
  fixed_window: {
    start: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY;
    end: typeof PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY;
    signal_start_policy: typeof PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_SIGNAL_START_POLICY;
    signal_end_policy: "LAST_SESSION_MINUS_ONE";
  };
  temporal_contract: AmPmTemporalContract & {
    smile_transport_pair: "d_minus_2_to_d_minus_1";
    no_expiry_rank_substitution: true;
    no_extrapolation: true;
    d_minus_1_rule: "immediately_preceding_official_session";
  };
  candidates: {
    ids: typeof PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS;
    sticky_models: ["sticky_strike", "sticky_moneyness"];
    families: ["downside_smile_term_surprise", "potential_minimum_transport"];
    selection: "NOT_PERFORMED";
    adaptive_model_switch: false;
  };
  formulas: {
    downside_q: "actual_downside_smile_term_ratio/predicted_downside_smile_term_ratio-1";
    downside_g: "clip(1/(1+q),0.5,1.0)";
    potential_minimum_M: "(abs(e_front)+abs(e_next))/2+abs(e_next-e_front)";
    potential_minimum_g: "clip(1/(1+M/0.10),0.5,1.0)";
    hedge_h: "clip(-g*beta_D,-1.5,1.5)";
  };
  gate: {
    min_common_valid_signal_days: 40;
    min_distinct_calendar_months: 4;
    common_invalid_policy: "flatten_g0_h0_at_d_pm";
  };
  core: {
    version: typeof PERSONAL_INDEX_SMILE_TRANSPORT_CORE_VERSION;
    module: typeof PERSONAL_INDEX_SMILE_TRANSPORT_CORE_MODULE;
  };
  physical_potential: {
    metaphor_only: true;
    causal_claim: false;
  };
  svi_features_jsonl: {
    trusted_for_transport: false;
    reason: "lacks_exact_expiry_svi_parameters_and_fit_bands";
  };
  selection: "NOT_PERFORMED";
  proxy_mapping: {
    executable_hedge_code: "13060";
    n225_etf_if_required: "13210";
    cash_index_executable_fill_claim: false;
    tracking_basis_risk: true;
  };
  authority: OverlayAuthority;
};

export type PersonalIndexOverlayFamilyInputManifest =
  | PersonalIndexVolOverlay2023InputManifest
  | PersonalIndexSmileTransport2023InputManifest
  | PersonalIndexVolOverlay2023AmPmInputManifest
  | PersonalIndexSmileTransport2023AmPmInputManifest;

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
  if (
    raw.cohort_id !== PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID &&
    raw.cohort_id !== PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID &&
    raw.cohort_id !== PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID &&
    raw.cohort_id !== PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID
  ) {
    return {
      ok: false,
      error: "cohort_id is not a closed 2023 overlay family identity",
    };
  }
  return {
    ok: true,
    value: {
      job_id: jobId,
      cohort_id: raw.cohort_id,
      base_job_id: baseJobId,
      svi_job_id: sviJobId,
    },
  };
}

export function isPersonalIndexSmileTransport2023Cohort(
  cohortId: string,
): cohortId is typeof PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID {
  return cohortId === PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID;
}

export function isPersonalIndexVolOverlay2023AmPmCohort(
  cohortId: string,
): cohortId is typeof PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID {
  return cohortId === PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID;
}

export function isPersonalIndexSmileTransport2023AmPmCohort(
  cohortId: string,
): cohortId is typeof PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID {
  return cohortId === PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID;
}

export function isPersonalIndexOverlayFamilyCohort(
  cohortId: string,
): cohortId is PersonalIndexVolOverlay2023CohortId {
  return (
    cohortId === PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID ||
    cohortId === PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID ||
    cohortId === PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID ||
    cohortId === PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID
  );
}

function checkedJobId(jobId: string): string {
  if (!JOB_ID_RE.test(jobId)) throw new Error("invalid index-vol overlay job id");
  return jobId;
}

export function personalIndexVolOverlay2023Prefix(jobId: string): string {
  return `research/personal/index-vol-overlay-2023/job=${checkedJobId(jobId)}`;
}

export function personalIndexSmileTransport2023Prefix(jobId: string): string {
  return `research/personal/index-smile-transport-2023/job=${checkedJobId(jobId)}`;
}

export function personalIndexVolOverlay2023AmPmPrefix(jobId: string): string {
  return `research/personal/index-vol-overlay-2023-am-pm/job=${checkedJobId(jobId)}`;
}

export function personalIndexSmileTransport2023AmPmPrefix(jobId: string): string {
  return `research/personal/index-smile-transport-2023-am-pm/job=${checkedJobId(jobId)}`;
}

export function personalIndexOverlayFamilyPrefix(
  jobId: string,
  cohortId: PersonalIndexVolOverlay2023CohortId,
): string {
  if (isPersonalIndexSmileTransport2023AmPmCohort(cohortId)) {
    return personalIndexSmileTransport2023AmPmPrefix(jobId);
  }
  if (isPersonalIndexVolOverlay2023AmPmCohort(cohortId)) {
    return personalIndexVolOverlay2023AmPmPrefix(jobId);
  }
  return isPersonalIndexSmileTransport2023Cohort(cohortId)
    ? personalIndexSmileTransport2023Prefix(jobId)
    : personalIndexVolOverlay2023Prefix(jobId);
}

export function personalIndexVolOverlay2023InputManifestKey(jobId: string): string {
  return `${personalIndexVolOverlay2023Prefix(jobId)}/input-manifest.json`;
}

export function personalIndexSmileTransport2023InputManifestKey(
  jobId: string,
): string {
  return `${personalIndexSmileTransport2023Prefix(jobId)}/input-manifest.json`;
}

export function personalIndexVolOverlay2023AmPmInputManifestKey(
  jobId: string,
): string {
  return `${personalIndexVolOverlay2023AmPmPrefix(jobId)}/input-manifest.json`;
}

export function personalIndexSmileTransport2023AmPmInputManifestKey(
  jobId: string,
): string {
  return `${personalIndexSmileTransport2023AmPmPrefix(jobId)}/input-manifest.json`;
}

export function personalIndexOverlayFamilyInputManifestKey(
  jobId: string,
  cohortId: PersonalIndexVolOverlay2023CohortId,
): string {
  return `${personalIndexOverlayFamilyPrefix(jobId, cohortId)}/input-manifest.json`;
}

export function personalIndexVolOverlay2023TerminalManifestKey(
  jobId: string,
): string {
  return `${personalIndexVolOverlay2023Prefix(jobId)}/manifest.json`;
}

export function personalIndexSmileTransport2023TerminalManifestKey(
  jobId: string,
): string {
  return `${personalIndexSmileTransport2023Prefix(jobId)}/manifest.json`;
}

export function personalIndexOverlayFamilyTerminalManifestKey(
  jobId: string,
  cohortId: PersonalIndexVolOverlay2023CohortId,
): string {
  return `${personalIndexOverlayFamilyPrefix(jobId, cohortId)}/manifest.json`;
}

export function personalIndexVolOverlay2023ArtifactKey(
  kind: "prepared-panel" | "report",
  digest: string,
): string {
  if (!DIGEST_RE.test(digest)) throw new Error("invalid overlay artifact digest");
  return `research/personal/index-vol-overlay-2023/artifacts/${kind}/sha256=${digest.slice("sha256:".length)}.json`;
}

export function personalIndexSmileTransport2023ArtifactKey(
  kind: "prepared-panel" | "report",
  digest: string,
): string {
  if (!DIGEST_RE.test(digest)) throw new Error("invalid overlay artifact digest");
  return `research/personal/index-smile-transport-2023/artifacts/${kind}/sha256=${digest.slice("sha256:".length)}.json`;
}

export function personalIndexVolOverlay2023AmPmArtifactKey(
  kind: "prepared-panel" | "report",
  digest: string,
): string {
  if (!DIGEST_RE.test(digest)) throw new Error("invalid overlay artifact digest");
  return `research/personal/index-vol-overlay-2023-am-pm/artifacts/${kind}/sha256=${digest.slice("sha256:".length)}.json`;
}

export function personalIndexSmileTransport2023AmPmArtifactKey(
  kind: "prepared-panel" | "report",
  digest: string,
): string {
  if (!DIGEST_RE.test(digest)) throw new Error("invalid overlay artifact digest");
  return `research/personal/index-smile-transport-2023-am-pm/artifacts/${kind}/sha256=${digest.slice("sha256:".length)}.json`;
}

export function personalIndexOverlayFamilyArtifactKey(
  kind: "prepared-panel" | "report",
  digest: string,
  cohortId: PersonalIndexVolOverlay2023CohortId,
): string {
  if (isPersonalIndexSmileTransport2023AmPmCohort(cohortId)) {
    return personalIndexSmileTransport2023AmPmArtifactKey(kind, digest);
  }
  if (isPersonalIndexVolOverlay2023AmPmCohort(cohortId)) {
    return personalIndexVolOverlay2023AmPmArtifactKey(kind, digest);
  }
  return isPersonalIndexSmileTransport2023Cohort(cohortId)
    ? personalIndexSmileTransport2023ArtifactKey(kind, digest)
    : personalIndexVolOverlay2023ArtifactKey(kind, digest);
}

export function personalIndexOverlayFamilyRunnerVersion(
  cohortId: PersonalIndexVolOverlay2023CohortId,
): string {
  if (isPersonalIndexSmileTransport2023AmPmCohort(cohortId)) {
    return PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_RUNNER_VERSION;
  }
  if (isPersonalIndexVolOverlay2023AmPmCohort(cohortId)) {
    return PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION;
  }
  return isPersonalIndexSmileTransport2023Cohort(cohortId)
    ? PERSONAL_INDEX_SMILE_TRANSPORT_2023_RUNNER_VERSION
    : PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION;
}

export function personalIndexOverlayFamilyTerminalSchema(
  cohortId: PersonalIndexVolOverlay2023CohortId,
): string {
  if (isPersonalIndexSmileTransport2023AmPmCohort(cohortId)) {
    return "personal-index-smile-transport-am-pm-manifest/v1";
  }
  if (isPersonalIndexVolOverlay2023AmPmCohort(cohortId)) {
    return "personal-index-vol-overlay-am-pm-manifest/v1";
  }
  return isPersonalIndexSmileTransport2023Cohort(cohortId)
    ? "personal-index-smile-transport-manifest/v2"
    : "personal-index-vol-overlay-manifest/v1";
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
    input_manifest_key: personalIndexOverlayFamilyInputManifestKey(
      request.job_id,
      request.cohort_id,
    ),
    job_id: request.job_id,
    runner_version: personalIndexOverlayFamilyRunnerVersion(request.cohort_id),
    svi_job_id: request.svi_job_id,
  });
  return `sha256:${await sha256Hex(new TextEncoder().encode(canonical))}`;
}
