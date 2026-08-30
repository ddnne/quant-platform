import { putJsonCreateOnly, serializedJsonBytes } from "./http";
import {
  PERSONAL_INDEX_AM_PM_BASE_COHORT_ID,
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID,
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_RUNNER_VERSION,
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_SIGNAL_START_POLICY,
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID,
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_RUNNER_VERSION,
  PERSONAL_INDEX_SMILE_TRANSPORT_2023_SIGNAL_START_POLICY,
  PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS,
  PERSONAL_INDEX_SMILE_TRANSPORT_CANDIDATE_IDS,
  PERSONAL_INDEX_SMILE_TRANSPORT_CORE_MODULE,
  PERSONAL_INDEX_SMILE_TRANSPORT_CORE_VERSION,
  PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
  PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION,
  PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_SIGNAL_START_POLICY,
  PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
  PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY,
  PERSONAL_INDEX_VOL_OVERLAY_2023_INPUT_MAX_BYTES,
  PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY,
  PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
  PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY,
  PERSONAL_INDEX_VOL_OVERLAY_AM_PM_CANDIDATE_IDS,
  isPersonalIndexSmileTransport2023AmPmCohort,
  isPersonalIndexSmileTransport2023Cohort,
  isPersonalIndexVolOverlay2023AmPmCohort,
  personalIndexOverlayFamilyInputManifestKey,
  personalIndexOverlayFamilyRunnerVersion,
  personalIndexOverlayFamilyTerminalManifestKey,
  personalIndexVolOverlay2023RequestDigest,
  type ImmutableInputReference,
  type PersonalIndexOverlayFamilyInputManifest,
  type PersonalIndexSmileTransport2023AmPmInputManifest,
  type PersonalIndexSmileTransport2023InputManifest,
  type PersonalIndexVolOverlay2023AmPmInputManifest,
  type PersonalIndexVolOverlay2023InputManifest,
  type PersonalIndexVolOverlay2023Request,
  type SnapshotInputReference,
} from "./personal_index_vol_overlay_2023_contract";
import {
  PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES,
  isPersonalResearchSnapshotKey,
  personalResearchCohortDigest,
  personalResearchManifestKey,
  personalResearchResultKey,
} from "./personal_research_contract";
import { verifiedPersonalResearchContainer } from "./personal_research_runner";
import {
  PERSONAL_SVI_2023_COHORT_ID,
  PERSONAL_SVI_2023_PANEL_KEY,
  PERSONAL_SVI_2023_RUNNER_VERSION,
  PERSONAL_SVI_2023_STRATEGY_ID,
  optionsDayFromKey,
  personalSviFeatureKey,
  personalSviInputManifestKey,
  personalSviTerminalManifestKey,
} from "./personal_svi_2023_contract";
import { sha256Hex } from "./sha256";
import type { Env } from "./types";

const BASE_COHORT_ID = "sector-relative-ls-v1" as const;
const BASE_UNIVERSE_ID = "topix_all" as const;
const BASE_RESULT_MAX_BYTES = 512 * 1024 * 1024;
const SVI_FEATURE_MAX_BYTES = 8 * 1024 * 1024;
const SOURCE_MANIFEST_MAX_BYTES = 512 * 1024;
const DIGEST_RE = /^sha256:[0-9a-f]{64}$/;
const OVERLAY_COMPATIBLE_BASE_RUNNER_VERSIONS: ReadonlySet<string> = new Set([
  "personal-cloud-runner/v9",
  "personal-cloud-runner/v10",
  "personal-cloud-runner/v11",
  "personal-cloud-runner/v12",
]);

type JsonObject = Record<string, unknown>;

function responseJson(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fail(code: string): never {
  throw Object.assign(new Error(code), { code });
}

async function boundedJson(
  bucket: R2Bucket,
  key: string,
  maximumBytes: number,
): Promise<{ document: JsonObject; object: R2Object; digest: string }> {
  const head = await bucket.head(key);
  if (!head) fail("overlay_source_missing");
  if (head.size < 1 || head.size > maximumBytes) {
    fail("overlay_source_size_denied");
  }
  const body = await bucket.get(key);
  if (!body || body.etag !== head.etag || body.size !== head.size) {
    fail("overlay_source_changed_during_admission");
  }
  const bytes = new Uint8Array(await body.arrayBuffer());
  if (bytes.byteLength !== head.size) fail("overlay_source_length_mismatch");
  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    fail("overlay_source_invalid_json");
  }
  if (!isObject(parsed)) fail("overlay_source_invalid_document");
  return {
    document: parsed,
    object: head,
    digest: `sha256:${await sha256Hex(bytes)}`,
  };
}

function immutableReference(
  object: R2Object,
  expectedKey: string,
  expectedDigest: string,
  maximumBytes: number,
): ImmutableInputReference {
  if (
    object.key !== expectedKey ||
    object.size < 1 ||
    object.size > maximumBytes ||
    !DIGEST_RE.test(expectedDigest) ||
    object.customMetadata?.sha256 !== expectedDigest
  ) {
    fail("overlay_source_reference_invalid");
  }
  return {
    key: expectedKey,
    etag: object.etag,
    size: object.size,
    sha256: expectedDigest,
  };
}

function sleeveReference(value: unknown): PersonalIndexVolOverlay2023InputManifest["base"]["sleeve_artifact"] {
  if (!isObject(value)) fail("overlay_base_sleeve_reference_missing");
  const reference = {
    archive_member: value.archive_member,
    sha256: value.sha256,
  };
  if (
    typeof reference.archive_member !== "string" ||
    !/^base-sleeve\/[0-9a-f]{64}\.json$/.test(reference.archive_member) ||
    !DIGEST_RE.test(String(reference.sha256 ?? "")) ||
    reference.archive_member !== `base-sleeve/${String(reference.sha256).slice("sha256:".length)}.json`
  ) {
    fail("overlay_base_sleeve_reference_invalid");
  }
  return reference as PersonalIndexVolOverlay2023InputManifest["base"]["sleeve_artifact"];
}

async function baseInputs(
  bucket: R2Bucket,
  baseJobId: string,
  family: "legacy" | "am-pm" = "legacy",
): Promise<PersonalIndexVolOverlay2023InputManifest["base"]> {
  const key = personalResearchManifestKey(baseJobId);
  const { document: manifest } = await boundedJson(
    bucket,
    key,
    SOURCE_MANIFEST_MAX_BYTES,
  );
  const resultDigest = String(manifest.result_sha256 ?? "");
  const resultKey = personalResearchResultKey(baseJobId);
  const snapshot = manifest.snapshot;
  const sleeve = manifest.base_sleeve_artifact;
  const amPmEligible =
    family === "am-pm" &&
    manifest.cohort_id === PERSONAL_INDEX_AM_PM_BASE_COHORT_ID &&
    DIGEST_RE.test(String(manifest.cohort_digest ?? "")) &&
    (manifest.execution_mode === "am_pm" ||
      (isObject(sleeve) &&
        sleeve.artifact_schema_version === "personal-base-sleeve-source-am-pm/v1"));
  const legacyEligible =
    family === "legacy" &&
    manifest.cohort_id === BASE_COHORT_ID &&
    manifest.cohort_digest === personalResearchCohortDigest(BASE_COHORT_ID);
  if (
    manifest.status !== "COMPLETED" ||
    !OVERLAY_COMPATIBLE_BASE_RUNNER_VERSIONS.has(String(manifest.version ?? "")) ||
    manifest.job_id !== baseJobId ||
    !amPmEligible && !legacyEligible ||
    (family === "am-pm" && manifest.execution_mode === "next_close") ||
    manifest.universe_id !== BASE_UNIVERSE_ID ||
    manifest.result_key !== resultKey ||
    !DIGEST_RE.test(resultDigest) ||
    !isObject(snapshot) ||
    typeof snapshot.key !== "string" ||
    typeof snapshot.sha256 !== "string" ||
    !isPersonalResearchSnapshotKey(snapshot.key) ||
    !DIGEST_RE.test(snapshot.sha256)
  ) {
    fail("overlay_base_job_not_eligible");
  }
  const [resultHead, snapshotHead] = await Promise.all([
    bucket.head(resultKey),
    bucket.head(snapshot.key),
  ]);
  if (!resultHead || !snapshotHead) fail("overlay_base_object_missing");
  const result = immutableReference(
    resultHead,
    resultKey,
    resultDigest,
    BASE_RESULT_MAX_BYTES,
  );
  if (
    snapshotHead.key !== snapshot.key ||
    snapshotHead.size < 1 ||
    snapshotHead.size > PERSONAL_RESEARCH_MAX_SNAPSHOT_BYTES
  ) {
    fail("overlay_base_snapshot_invalid");
  }
  const snapshotReference: SnapshotInputReference = {
    key: snapshot.key,
    etag: snapshotHead.etag,
    size: snapshotHead.size,
    raw_sha256: snapshot.sha256,
  };
  return {
    job_id: baseJobId,
    result,
    snapshot: snapshotReference,
    sleeve_artifact: sleeveReference(manifest.base_sleeve_artifact),
  };
}

async function referencedHead(
  bucket: R2Bucket,
  key: string,
  digest: string,
  maximumBytes: number,
): Promise<ImmutableInputReference> {
  const object = await bucket.head(key);
  if (!object) fail("overlay_svi_object_missing");
  return immutableReference(object, key, digest, maximumBytes);
}

function copiedReference(value: unknown, day?: string): ImmutableInputReference {
  if (!isObject(value)) fail("overlay_svi_option_reference_invalid");
  const copied = {
    key: value.key,
    etag: value.etag,
    size: value.size,
    sha256: value.sha256,
  };
  if (
    typeof copied.key !== "string" ||
    (day !== undefined && optionsDayFromKey(copied.key) !== day) ||
    typeof copied.etag !== "string" ||
    copied.etag.length < 1 ||
    !Number.isInteger(copied.size) ||
    Number(copied.size) < 1 ||
    typeof copied.sha256 !== "string" ||
    !DIGEST_RE.test(copied.sha256)
  ) {
    fail("overlay_svi_option_reference_invalid");
  }
  return copied as ImmutableInputReference;
}

async function sviInputs(
  bucket: R2Bucket,
  sviJobId: string,
): Promise<PersonalIndexVolOverlay2023InputManifest["svi"]> {
  const terminalKey = personalSviTerminalManifestKey(sviJobId);
  const { document: terminal } = await boundedJson(
    bucket,
    terminalKey,
    SOURCE_MANIFEST_MAX_BYTES,
  );
  const inputKey = personalSviInputManifestKey(sviJobId);
  const featureKey = personalSviFeatureKey(sviJobId);
  const inputDigest = String(terminal.input_manifest_digest ?? "");
  const featureDigest = String(terminal.feature_sha256 ?? "");
  const reportDigest = String(terminal.report_sha256 ?? "");
  const requestDigest = String(terminal.request_digest ?? "");
  if (
    terminal.status !== "COMPLETED" ||
    terminal.job_id !== sviJobId ||
    terminal.cohort_id !== PERSONAL_SVI_2023_COHORT_ID ||
    terminal.strategy_id !== PERSONAL_SVI_2023_STRATEGY_ID ||
    terminal.runner_version !== PERSONAL_SVI_2023_RUNNER_VERSION ||
    terminal.input_manifest_key !== inputKey ||
    terminal.feature_key !== featureKey ||
    terminal.report_key !== `research/personal/svi-2023/job=${sviJobId}/report.json` ||
    ![inputDigest, featureDigest, reportDigest, requestDigest].every((value) =>
      DIGEST_RE.test(value),
    ) ||
    terminal.draft_only !== true ||
    terminal.screening_only !== true ||
    terminal.ready !== false ||
    terminal.mass !== false ||
    terminal.promotion !== false ||
    terminal.live_orders !== false ||
    terminal.go !== false
  ) {
    fail("overlay_svi_job_not_eligible");
  }
  const [loadedInput, feature] = await Promise.all([
    boundedJson(
      bucket,
      inputKey,
      PERSONAL_INDEX_VOL_OVERLAY_2023_INPUT_MAX_BYTES * 4,
    ),
    referencedHead(bucket, featureKey, featureDigest, SVI_FEATURE_MAX_BYTES),
  ]);
  if (loadedInput.digest !== inputDigest) {
    fail("overlay_svi_input_manifest_digest_mismatch");
  }
  const source = loadedInput.document;
  const panel = source.panel;
  const options = source.options;
  const authority = source.authority;
  if (
    source.schema_version !== "personal-svi-2023-input/v2" ||
    source.job_id !== sviJobId ||
    source.cohort_id !== PERSONAL_SVI_2023_COHORT_ID ||
    source.runner_version !== PERSONAL_SVI_2023_RUNNER_VERSION ||
    !isObject(panel) ||
    panel.key !== PERSONAL_SVI_2023_PANEL_KEY ||
    !isObject(options) ||
    !Array.isArray(options.days) ||
    options.days.length < 1 ||
    !isObject(authority) ||
    authority.draft_only !== true ||
    authority.screening_only !== true ||
    authority.ready !== false ||
    authority.mass !== false ||
    authority.promotion !== false ||
    authority.live_orders !== false ||
    authority.go !== false
  ) {
    fail("overlay_svi_input_manifest_not_eligible");
  }
  const panelReference = copiedReference(panel);
  const optionDays: Array<{ date: string; objects: ImmutableInputReference[] }> = [];
  let objectCount = 0;
  let totalBytes = 0;
  for (const rawDay of options.days) {
    if (!isObject(rawDay) || typeof rawDay.date !== "string" || !Array.isArray(rawDay.objects)) {
      fail("overlay_svi_option_reference_invalid");
    }
    const day = rawDay.date;
    const objects = rawDay.objects.map((value) => copiedReference(value, day));
    objectCount += objects.length;
    totalBytes += objects.reduce((sum, value) => sum + value.size, 0);
    if (objects.length < 1) fail("overlay_svi_option_reference_invalid");
    optionDays.push({ date: day, objects });
  }
  if (
    options.object_count !== objectCount ||
    options.total_bytes !== totalBytes ||
    optionDays.some((value, index) => index > 0 && value.date <= optionDays[index - 1].date)
  ) {
    fail("overlay_svi_option_inventory_mismatch");
  }
  const inputManifest = immutableReference(
    loadedInput.object,
    inputKey,
    inputDigest,
    PERSONAL_INDEX_VOL_OVERLAY_2023_INPUT_MAX_BYTES * 4,
  );
  return {
    job_id: sviJobId,
    request_digest: requestDigest,
    input_manifest: inputManifest,
    feature,
    panel: panelReference,
    options: {
      days: optionDays,
      object_count: objectCount,
      total_bytes: totalBytes,
    },
  };
}

const OVERLAY_AUTHORITY = {
  draft_only: true,
  screening_only: true,
  ready: false,
  mass: false,
  promotion: false,
  live_orders: false,
  go: false,
  single_stock_option_iv: "FORBIDDEN",
} as const;

const AM_PM_PROXY_MAPPING = {
  executable_hedge_code: "13060",
  n225_etf_if_required: "13210",
  cash_index_executable_fill_claim: false,
  tracking_basis_risk: true,
} as const;

const AM_PM_TEMPORAL = {
  source_decision_cutoff_jst: "11:30:00+09:00",
  equity_am_usable_by_jst: "12:30:00+09:00",
  prepared_available_at: "NO_LATER_THAN_D_12_30_JST",
  fill_timing: "d_pm_aadjc",
  first_pnl_interval: "d_pm_to_d_plus_1_pm",
  order_sizing: "d_am_price",
  option_signal_as_of: "through_d_minus_1",
  no_forward_fill: true,
  no_full_close_fallback: true,
  no_recovery_promotion: true,
} as const;

export async function buildPersonalIndexVolOverlay2023InputManifest(
  bucket: R2Bucket,
  request: PersonalIndexVolOverlay2023Request,
): Promise<PersonalIndexOverlayFamilyInputManifest> {
  const amPmFamily =
    isPersonalIndexVolOverlay2023AmPmCohort(request.cohort_id) ||
    isPersonalIndexSmileTransport2023AmPmCohort(request.cohort_id);
  const [base, svi] = await Promise.all([
    baseInputs(bucket, request.base_job_id, amPmFamily ? "am-pm" : "legacy"),
    sviInputs(bucket, request.svi_job_id),
  ]);
  if (isPersonalIndexSmileTransport2023AmPmCohort(request.cohort_id)) {
    const smile: PersonalIndexSmileTransport2023AmPmInputManifest = {
      schema_version: "personal-index-smile-transport-2023-am-pm-input/v1",
      job_id: request.job_id,
      cohort_id: PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID,
      runner_version: PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_RUNNER_VERSION,
      base,
      svi,
      fixed_window: {
        start: PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY,
        end: PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY,
        signal_start_policy: PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_SIGNAL_START_POLICY,
        signal_end_policy: "LAST_SESSION_MINUS_ONE",
      },
      temporal_contract: {
        ...AM_PM_TEMPORAL,
        smile_transport_pair: "d_minus_2_to_d_minus_1",
        no_expiry_rank_substitution: true,
        no_extrapolation: true,
        d_minus_1_rule: "immediately_preceding_official_session",
      },
      candidates: {
        ids: PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS,
        sticky_models: ["sticky_strike", "sticky_moneyness"],
        families: ["downside_smile_term_surprise", "potential_minimum_transport"],
        selection: "NOT_PERFORMED",
        adaptive_model_switch: false,
      },
      formulas: {
        downside_q:
          "actual_downside_smile_term_ratio/predicted_downside_smile_term_ratio-1",
        downside_g: "clip(1/(1+q),0.5,1.0)",
        potential_minimum_M: "(abs(e_front)+abs(e_next))/2+abs(e_next-e_front)",
        potential_minimum_g: "clip(1/(1+M/0.10),0.5,1.0)",
        hedge_h: "clip(-g*beta_D,-1.5,1.5)",
      },
      gate: {
        min_common_valid_signal_days: 40,
        min_distinct_calendar_months: 4,
        common_invalid_policy: "flatten_g0_h0_at_d_pm",
      },
      core: {
        version: PERSONAL_INDEX_SMILE_TRANSPORT_CORE_VERSION,
        module: PERSONAL_INDEX_SMILE_TRANSPORT_CORE_MODULE,
      },
      physical_potential: {
        metaphor_only: true,
        causal_claim: false,
      },
      svi_features_jsonl: {
        trusted_for_transport: false,
        reason: "lacks_exact_expiry_svi_parameters_and_fit_bands",
      },
      selection: "NOT_PERFORMED",
      proxy_mapping: AM_PM_PROXY_MAPPING,
      authority: OVERLAY_AUTHORITY,
    };
    return smile;
  }
  if (isPersonalIndexVolOverlay2023AmPmCohort(request.cohort_id)) {
    const overlay: PersonalIndexVolOverlay2023AmPmInputManifest = {
      schema_version: "personal-index-vol-overlay-2023-am-pm-input/v1",
      job_id: request.job_id,
      cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
      runner_version: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION,
      base,
      svi,
      fixed_window: {
        start: PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY,
        end: PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY,
        signal_start_policy: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_SIGNAL_START_POLICY,
        signal_end_policy: "LAST_SESSION_MINUS_ONE",
      },
      temporal_contract: AM_PM_TEMPORAL,
      candidates: {
        ids: PERSONAL_INDEX_VOL_OVERLAY_AM_PM_CANDIDATE_IDS,
        selection: "NOT_PERFORMED",
        adaptive_model_switch: false,
      },
      selection: "NOT_PERFORMED",
      proxy_mapping: AM_PM_PROXY_MAPPING,
      authority: OVERLAY_AUTHORITY,
    };
    return overlay;
  }
  if (isPersonalIndexSmileTransport2023Cohort(request.cohort_id)) {
    const smile: PersonalIndexSmileTransport2023InputManifest = {
      schema_version: "personal-index-smile-transport-2023-input/v2",
      job_id: request.job_id,
      cohort_id: PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID,
      runner_version: PERSONAL_INDEX_SMILE_TRANSPORT_2023_RUNNER_VERSION,
      base,
      svi,
      fixed_window: {
        start: PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY,
        end: PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY,
        signal_start_policy: PERSONAL_INDEX_SMILE_TRANSPORT_2023_SIGNAL_START_POLICY,
        signal_end_policy: "LAST_SESSION_MINUS_TWO",
      },
      temporal_contract: {
        source_decision_cutoff_jst: "15:00:00+09:00",
        prepared_available_at: "NO_EARLIER_THAN_D_23_59_59_JST",
        fill_timing: "next_close",
        first_pnl_interval: "fill_close_to_following_close",
        no_forward_fill: true,
        no_expiry_rank_substitution: true,
        no_extrapolation: true,
        d_minus_1_rule: "immediately_preceding_official_session",
      },
      candidates: {
        ids: PERSONAL_INDEX_SMILE_TRANSPORT_CANDIDATE_IDS,
        sticky_models: ["sticky_strike", "sticky_moneyness"],
        families: ["downside_smile_term_surprise", "potential_minimum_transport"],
        selection: "NOT_PERFORMED",
        adaptive_model_switch: false,
      },
      formulas: {
        downside_q:
          "actual_downside_smile_term_ratio/predicted_downside_smile_term_ratio-1",
        downside_g: "clip(1/(1+q),0.5,1.0)",
        potential_minimum_M: "(abs(e_front)+abs(e_next))/2+abs(e_next-e_front)",
        potential_minimum_g: "clip(1/(1+M/0.10),0.5,1.0)",
        hedge_h: "clip(-g*beta_D,-1.5,1.5)",
      },
      gate: {
        min_common_valid_signal_days: 40,
        min_distinct_calendar_months: 4,
        common_invalid_policy: "flatten_g0_h0_at_d_plus_1_close_prior",
      },
      core: {
        version: PERSONAL_INDEX_SMILE_TRANSPORT_CORE_VERSION,
        module: PERSONAL_INDEX_SMILE_TRANSPORT_CORE_MODULE,
      },
      physical_potential: {
        metaphor_only: true,
        causal_claim: false,
      },
      svi_features_jsonl: {
        trusted_for_transport: false,
        reason: "lacks_exact_expiry_svi_parameters_and_fit_bands",
      },
      authority: OVERLAY_AUTHORITY,
    };
    return smile;
  }
  const overlay: PersonalIndexVolOverlay2023InputManifest = {
    schema_version: "personal-index-vol-overlay-2023-input/v1",
    job_id: request.job_id,
    cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
    runner_version: PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
    base,
    svi,
    fixed_window: {
      start: PERSONAL_INDEX_VOL_OVERLAY_2023_EARLIEST_DAY,
      end: PERSONAL_INDEX_VOL_OVERLAY_2023_LATEST_DAY,
      signal_start_policy: PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY,
      signal_end_policy: "LAST_SESSION_MINUS_TWO",
    },
    temporal_contract: {
      source_decision_cutoff_jst: "15:00:00+09:00",
      prepared_available_at: "SAME_DAY_23_59_59_JST",
      fill_timing: "next_close",
      first_pnl_interval: "fill_close_to_following_close",
      no_forward_fill: true,
    },
    authority: OVERLAY_AUTHORITY,
  };
  return overlay;
}

type StoredTerminal = JsonObject & {
  status?: unknown;
};

async function readTerminal(
  env: Env,
  key: string,
): Promise<StoredTerminal | null> {
  const object = await env.STRUCTURED_BUCKET.get(key);
  if (!object || object.size > 64 * 1024) return null;
  try {
    const parsed: unknown = await object.json();
    return isObject(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

async function storedTerminal(
  env: Env,
  jobId: string,
): Promise<StoredTerminal | null> {
  const overlay = await readTerminal(
    env,
    personalIndexOverlayFamilyTerminalManifestKey(
      jobId,
      PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
    ),
  );
  if (overlay) return overlay;
  const smile = await readTerminal(
    env,
    personalIndexOverlayFamilyTerminalManifestKey(
      jobId,
      PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID,
    ),
  );
  if (smile) return smile;
  const overlayAmPm = await readTerminal(
    env,
    personalIndexOverlayFamilyTerminalManifestKey(
      jobId,
      PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
    ),
  );
  if (overlayAmPm) return overlayAmPm;
  return readTerminal(
    env,
    personalIndexOverlayFamilyTerminalManifestKey(
      jobId,
      PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID,
    ),
  );
}

function sameRequest(
  terminal: StoredTerminal,
  request: PersonalIndexVolOverlay2023Request,
): boolean {
  return (
    terminal.job_id === request.job_id &&
    terminal.cohort_id === request.cohort_id &&
    terminal.base_job_id === request.base_job_id &&
    terminal.svi_job_id === request.svi_job_id
  );
}

export async function submitPersonalIndexVolOverlay2023(
  env: Env,
  request: PersonalIndexVolOverlay2023Request,
): Promise<Response> {
  const terminalBeforeAdmission = await storedTerminal(env, request.job_id);
  if (terminalBeforeAdmission) {
    if (!sameRequest(terminalBeforeAdmission, request)) {
      return responseJson(
        { ok: false, error: "job_id_conflict", job_id: request.job_id, go: false },
        409,
      );
    }
    return responseJson({
      ok: terminalBeforeAdmission.status === "COMPLETED",
      idempotent: true,
      job: terminalBeforeAdmission,
      draft_only: true,
      screening_only: true,
      go: false,
    });
  }
  let input: PersonalIndexOverlayFamilyInputManifest;
  try {
    input = await buildPersonalIndexVolOverlay2023InputManifest(
      env.STRUCTURED_BUCKET,
      request,
    );
  } catch (error) {
    const code =
      (error as { code?: string }).code ?? "overlay_input_admission_failed";
    return responseJson(
      { ok: false, error: code, job_id: request.job_id, go: false },
      409,
    );
  }
  if (
    serializedJsonBytes(input).byteLength >
    PERSONAL_INDEX_VOL_OVERLAY_2023_INPUT_MAX_BYTES
  ) {
    return responseJson(
      {
        ok: false,
        error: "overlay_input_manifest_size_denied",
        job_id: request.job_id,
        go: false,
      },
      409,
    );
  }
  const inputKey = personalIndexOverlayFamilyInputManifestKey(
    request.job_id,
    request.cohort_id,
  );
  const inputPut = await putJsonCreateOnly(env.STRUCTURED_BUCKET, inputKey, input);
  if (inputPut.conflict) {
    return responseJson(
      { ok: false, error: "input_manifest_conflict", job_id: request.job_id, go: false },
      409,
    );
  }
  const existing = await storedTerminal(env, request.job_id);
  if (existing) {
    if (!sameRequest(existing, request) || existing.input_manifest_digest !== inputPut.digest) {
      return responseJson(
        { ok: false, error: "job_id_conflict", job_id: request.job_id, go: false },
        409,
      );
    }
    return responseJson({
      ok: existing.status === "COMPLETED",
      idempotent: true,
      job: existing,
      draft_only: true,
      screening_only: true,
      go: false,
    });
  }
  const requestDigest = await personalIndexVolOverlay2023RequestDigest(
    request,
    inputPut.digest,
  );
  try {
    const target = await verifiedPersonalResearchContainer(env);
    return await target.fetch(
      new Request("http://container/v1/run-index-vol-overlay-2023", {
        method: "POST",
        headers: { "content-type": "application/json; charset=utf-8" },
        body: JSON.stringify({
          base_job_id: request.base_job_id,
          cohort_id: request.cohort_id,
          input_manifest_digest: inputPut.digest,
          input_manifest_key: inputKey,
          job_id: request.job_id,
          manifest_key: personalIndexOverlayFamilyTerminalManifestKey(
            request.job_id,
            request.cohort_id,
          ),
          request_digest: requestDigest,
          runner_version: personalIndexOverlayFamilyRunnerVersion(
            request.cohort_id,
          ),
          svi_job_id: request.svi_job_id,
        }),
      }),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return responseJson(
      {
        ok: false,
        error: "personal_index_vol_overlay_container_unavailable",
        detail,
        job_id: request.job_id,
        go: false,
      },
      503,
    );
  }
}

export async function personalIndexVolOverlay2023Status(
  env: Env,
  jobId: string,
): Promise<Response> {
  const terminal = await storedTerminal(env, jobId);
  if (terminal) {
    return responseJson({
      ok: terminal.status === "COMPLETED",
      durable: true,
      job: terminal,
      draft_only: true,
      screening_only: true,
      go: false,
    });
  }
  try {
    const target = await verifiedPersonalResearchContainer(env);
    return await target.fetch(
      new Request(`http://container/v1/jobs/${encodeURIComponent(jobId)}`),
    );
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return responseJson(
      { ok: false, error: "personal_index_vol_overlay_status_unavailable", detail, go: false },
      503,
    );
  }
}
