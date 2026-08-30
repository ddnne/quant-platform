import { putBytesCreateOnly } from "./http";
import {
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
  PERSONAL_INDEX_VOL_OVERLAY_2023_INPUT_MAX_BYTES,
  PERSONAL_INDEX_VOL_OVERLAY_2023_RESULT_MAX_BYTES,
  PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
  PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY,
  PERSONAL_INDEX_VOL_OVERLAY_2023_TERMINAL_MAX_BYTES,
  PERSONAL_INDEX_VOL_OVERLAY_AM_PM_CANDIDATE_IDS,
  isPersonalIndexSmileTransport2023AmPmCohort,
  isPersonalIndexSmileTransport2023Cohort,
  isPersonalIndexVolOverlay2023AmPmCohort,
  isPersonalIndexVolOverlay2023Digest,
  isPersonalIndexVolOverlay2023JobId,
  personalIndexOverlayFamilyArtifactKey,
  personalIndexOverlayFamilyRunnerVersion,
  personalIndexOverlayFamilyTerminalManifestKey,
  personalIndexOverlayFamilyTerminalSchema,
  personalIndexSmileTransport2023AmPmInputManifestKey,
  personalIndexSmileTransport2023InputManifestKey,
  personalIndexVolOverlay2023AmPmInputManifestKey,
  personalIndexVolOverlay2023InputManifestKey,
  type ImmutableInputReference,
  type PersonalIndexOverlayFamilyInputManifest,
  type PersonalIndexSmileTransport2023AmPmInputManifest,
  type PersonalIndexSmileTransport2023InputManifest,
  type PersonalIndexVolOverlay2023AmPmInputManifest,
  type PersonalIndexVolOverlay2023CohortId,
  type PersonalIndexVolOverlay2023InputManifest,
  type SnapshotInputReference,
} from "./personal_index_vol_overlay_2023_contract";
import { sha256Hex } from "./sha256";

type R2Env = { STRUCTURED_BUCKET: R2Bucket };
type Identity = {
  jobId: string;
  inputKey: string;
  inputDigest: string;
  cohortId: PersonalIndexVolOverlay2023CohortId;
};
type JsonObject = Record<string, unknown>;

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function identity(request: Request): Identity | null {
  const jobId = request.headers.get("x-overlay-job-id") ?? "";
  const inputKey = request.headers.get("x-overlay-input-manifest-key") ?? "";
  const inputDigest = request.headers.get("x-overlay-input-manifest-digest") ?? "";
  if (
    !isPersonalIndexVolOverlay2023JobId(jobId) ||
    !isPersonalIndexVolOverlay2023Digest(inputDigest)
  ) {
    return null;
  }
  if (inputKey === personalIndexVolOverlay2023InputManifestKey(jobId)) {
    return {
      jobId,
      inputKey,
      inputDigest,
      cohortId: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
    };
  }
  if (inputKey === personalIndexSmileTransport2023InputManifestKey(jobId)) {
    return {
      jobId,
      inputKey,
      inputDigest,
      cohortId: PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID,
    };
  }
  if (inputKey === personalIndexVolOverlay2023AmPmInputManifestKey(jobId)) {
    return {
      jobId,
      inputKey,
      inputDigest,
      cohortId: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
    };
  }
  if (inputKey === personalIndexSmileTransport2023AmPmInputManifestKey(jobId)) {
    return {
      jobId,
      inputKey,
      inputDigest,
      cohortId: PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID,
    };
  }
  return null;
}

function reference(value: unknown): value is ImmutableInputReference {
  return (
    isObject(value) &&
    typeof value.key === "string" &&
    typeof value.etag === "string" &&
    value.etag.length > 0 &&
    Number.isInteger(value.size) &&
    Number(value.size) > 0 &&
    typeof value.sha256 === "string" &&
    isPersonalIndexVolOverlay2023Digest(value.sha256)
  );
}

function snapshot(value: unknown): value is SnapshotInputReference {
  return (
    isObject(value) &&
    reference({ ...value, sha256: value.raw_sha256 }) &&
    /^research\/personal\/snapshots\/sha256=[0-9a-f]{64}\.sqlite(?:\.gz)?$/.test(
      String(value.key),
    ) &&
    String(value.key).includes(String(value.raw_sha256).slice(7))
  );
}

function sharedInputShape(value: JsonObject, expected: Identity): boolean {
  if (!isObject(value.base) || !isObject(value.svi)) return false;
  const { base, svi } = value;
  const optionDays = isObject(svi.options) ? svi.options.days : null;
  const authority = value.authority;
  return (
    value.job_id === expected.jobId &&
    value.cohort_id === expected.cohortId &&
    isPersonalIndexVolOverlay2023JobId(String(base.job_id ?? "")) &&
    reference(base.result) &&
    snapshot(base.snapshot) &&
    isObject(base.sleeve_artifact) &&
    typeof base.sleeve_artifact.archive_member === "string" &&
    typeof base.sleeve_artifact.sha256 === "string" &&
    isPersonalIndexVolOverlay2023JobId(String(svi.job_id ?? "")) &&
    reference(svi.input_manifest) &&
    reference(svi.feature) &&
    reference(svi.panel) &&
    Array.isArray(optionDays) &&
    optionDays.length > 0 &&
    optionDays.every(
      (day) =>
        isObject(day) &&
        typeof day.date === "string" &&
        Array.isArray(day.objects) &&
        day.objects.length > 0 &&
        day.objects.every(reference),
    ) &&
    isObject(value.fixed_window) &&
    value.fixed_window.start === "2023-01-04" &&
    value.fixed_window.end === "2023-10-13" &&
    (value.fixed_window.signal_end_policy === "LAST_SESSION_MINUS_TWO" ||
      value.fixed_window.signal_end_policy === "LAST_SESSION_MINUS_ONE") &&
    isObject(value.temporal_contract) &&
    value.temporal_contract.no_forward_fill === true &&
    isObject(authority) &&
    authority.draft_only === true &&
    authority.screening_only === true &&
    authority.ready === false &&
    authority.mass === false &&
    authority.promotion === false &&
    authority.live_orders === false &&
    authority.go === false &&
    authority.single_stock_option_iv === "FORBIDDEN"
  );
}

function overlayInputShape(
  value: unknown,
  expected: Identity,
): value is PersonalIndexVolOverlay2023InputManifest {
  if (!isObject(value) || expected.cohortId !== PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID) {
    return false;
  }
  return (
    sharedInputShape(value, expected) &&
    value.schema_version === "personal-index-vol-overlay-2023-input/v1" &&
    value.runner_version === PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION &&
    isObject(value.fixed_window) &&
    value.fixed_window.signal_start_policy ===
      PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY &&
    value.fixed_window.signal_end_policy === "LAST_SESSION_MINUS_TWO"
  );
}

function smileTransportInputShape(
  value: unknown,
  expected: Identity,
): value is PersonalIndexSmileTransport2023InputManifest {
  if (
    !isObject(value) ||
    expected.cohortId !== PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID
  ) {
    return false;
  }
  const candidates = value.candidates;
  const formulas = value.formulas;
  const gate = value.gate;
  const core = value.core;
  const physical = value.physical_potential;
  const sviFeatures = value.svi_features_jsonl;
  const temporal = value.temporal_contract;
  return (
    sharedInputShape(value, expected) &&
    value.schema_version === "personal-index-smile-transport-2023-input/v2" &&
    value.runner_version === PERSONAL_INDEX_SMILE_TRANSPORT_2023_RUNNER_VERSION &&
    isObject(value.fixed_window) &&
    value.fixed_window.signal_start_policy ===
      PERSONAL_INDEX_SMILE_TRANSPORT_2023_SIGNAL_START_POLICY &&
    value.fixed_window.signal_end_policy === "LAST_SESSION_MINUS_TWO" &&
    isObject(temporal) &&
    temporal.prepared_available_at === "NO_EARLIER_THAN_D_23_59_59_JST" &&
    temporal.no_expiry_rank_substitution === true &&
    temporal.no_extrapolation === true &&
    temporal.d_minus_1_rule === "immediately_preceding_official_session" &&
    isObject(candidates) &&
    JSON.stringify(candidates.ids) === JSON.stringify(PERSONAL_INDEX_SMILE_TRANSPORT_CANDIDATE_IDS) &&
    candidates.selection === "NOT_PERFORMED" &&
    candidates.adaptive_model_switch === false &&
    isObject(formulas) &&
    formulas.downside_g === "clip(1/(1+q),0.5,1.0)" &&
    formulas.potential_minimum_g === "clip(1/(1+M/0.10),0.5,1.0)" &&
    formulas.hedge_h === "clip(-g*beta_D,-1.5,1.5)" &&
    isObject(gate) &&
    gate.min_common_valid_signal_days === 40 &&
    gate.min_distinct_calendar_months === 4 &&
    isObject(core) &&
    core.version === PERSONAL_INDEX_SMILE_TRANSPORT_CORE_VERSION &&
    core.module === PERSONAL_INDEX_SMILE_TRANSPORT_CORE_MODULE &&
    isObject(physical) &&
    physical.metaphor_only === true &&
    physical.causal_claim === false &&
    isObject(sviFeatures) &&
    sviFeatures.trusted_for_transport === false
  );
}

function overlayAmPmInputShape(
  value: unknown,
  expected: Identity,
): value is PersonalIndexVolOverlay2023AmPmInputManifest {
  if (!isObject(value) || expected.cohortId !== PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID) {
    return false;
  }
  const temporal = value.temporal_contract;
  const candidates = value.candidates;
  const proxy = value.proxy_mapping;
  return (
    sharedInputShape(value, expected) &&
    value.schema_version === "personal-index-vol-overlay-2023-am-pm-input/v1" &&
    value.runner_version === PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION &&
    isObject(value.fixed_window) &&
    value.fixed_window.signal_start_policy ===
      PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_SIGNAL_START_POLICY &&
    value.fixed_window.signal_end_policy === "LAST_SESSION_MINUS_ONE" &&
    isObject(temporal) &&
    temporal.source_decision_cutoff_jst === "11:30:00+09:00" &&
    temporal.fill_timing === "d_pm_aadjc" &&
    isObject(candidates) &&
    JSON.stringify(candidates.ids) === JSON.stringify(PERSONAL_INDEX_VOL_OVERLAY_AM_PM_CANDIDATE_IDS) &&
    candidates.selection === "NOT_PERFORMED" &&
    value.selection === "NOT_PERFORMED" &&
    isObject(proxy) &&
    proxy.executable_hedge_code === "13060" &&
    proxy.cash_index_executable_fill_claim === false
  );
}

function smileTransportAmPmInputShape(
  value: unknown,
  expected: Identity,
): value is PersonalIndexSmileTransport2023AmPmInputManifest {
  if (
    !isObject(value) ||
    expected.cohortId !== PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID
  ) {
    return false;
  }
  const temporal = value.temporal_contract;
  const candidates = value.candidates;
  const proxy = value.proxy_mapping;
  return (
    sharedInputShape(value, expected) &&
    value.schema_version === "personal-index-smile-transport-2023-am-pm-input/v1" &&
    value.runner_version === PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_RUNNER_VERSION &&
    isObject(value.fixed_window) &&
    value.fixed_window.signal_start_policy ===
      PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_SIGNAL_START_POLICY &&
    value.fixed_window.signal_end_policy === "LAST_SESSION_MINUS_ONE" &&
    isObject(temporal) &&
    temporal.source_decision_cutoff_jst === "11:30:00+09:00" &&
    temporal.fill_timing === "d_pm_aadjc" &&
    temporal.smile_transport_pair === "d_minus_2_to_d_minus_1" &&
    isObject(candidates) &&
    JSON.stringify(candidates.ids) ===
      JSON.stringify(PERSONAL_INDEX_SMILE_TRANSPORT_AM_PM_CANDIDATE_IDS) &&
    candidates.selection === "NOT_PERFORMED" &&
    value.selection === "NOT_PERFORMED" &&
    isObject(proxy) &&
    proxy.executable_hedge_code === "13060" &&
    proxy.cash_index_executable_fill_claim === false
  );
}

function inputShape(
  value: unknown,
  expected: Identity,
): value is PersonalIndexOverlayFamilyInputManifest {
  return (
    overlayInputShape(value, expected) ||
    smileTransportInputShape(value, expected) ||
    overlayAmPmInputShape(value, expected) ||
    smileTransportAmPmInputShape(value, expected)
  );
}

async function readInput(
  env: R2Env,
  expected: Identity,
): Promise<{ manifest: PersonalIndexOverlayFamilyInputManifest; bytes: Uint8Array } | null> {
  const object = await env.STRUCTURED_BUCKET.get(expected.inputKey);
  if (!object || object.size < 1 || object.size > PERSONAL_INDEX_VOL_OVERLAY_2023_INPUT_MAX_BYTES) {
    return null;
  }
  const bytes = new Uint8Array(await object.arrayBuffer());
  if (`sha256:${await sha256Hex(bytes)}` !== expected.inputDigest) return null;
  try {
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
    return inputShape(parsed, expected) ? { manifest: parsed, bytes } : null;
  } catch {
    return null;
  }
}

function allowed(
  manifest: PersonalIndexOverlayFamilyInputManifest,
  key: string,
): ImmutableInputReference | SnapshotInputReference | null {
  const references = [
    manifest.base.result,
    manifest.base.snapshot,
    manifest.svi.input_manifest,
    manifest.svi.feature,
    manifest.svi.panel,
    ...manifest.svi.options.days.flatMap((day) => day.objects),
  ];
  return references.find((item) => item.key === key) ?? null;
}

async function getInput(
  request: Request,
  env: R2Env,
  key: string,
  expected: Identity,
): Promise<Response> {
  const input = await readInput(env, expected);
  if (!input) return json({ error: "overlay input manifest denied" }, 403);
  if (key === expected.inputKey) {
    return new Response(request.method === "HEAD" ? null : input.bytes, {
      headers: { "content-length": String(input.bytes.byteLength) },
    });
  }
  const listed = allowed(input.manifest, key);
  if (!listed) return json({ error: "overlay input key not listed" }, 403);
  const object = request.method === "HEAD"
    ? await env.STRUCTURED_BUCKET.head(key)
    : await env.STRUCTURED_BUCKET.get(key);
  if (!object) return json({ error: "overlay input missing" }, 404);
  if (object.etag !== listed.etag || object.size !== listed.size) {
    return json({ error: "overlay input changed after admission" }, 409);
  }
  const headers = new Headers({
    "content-length": String(object.size),
    etag: object.httpEtag,
  });
  object.writeHttpMetadata(headers);
  headers.delete("content-encoding");
  headers.set("content-length", String(object.size));
  return new Response(request.method === "HEAD" ? null : (object as R2ObjectBody).body, {
    headers,
  });
}

function declaredLength(request: Request, maximum: number): number | null {
  const raw = request.headers.get("content-length") ?? "";
  const value = /^\d+$/.test(raw) ? Number(raw) : 0;
  return Number.isSafeInteger(value) && value > 0 && value <= maximum ? value : null;
}

function outputKind(
  key: string,
  expected: Identity,
  digest: string,
): "prepared-panel" | "report" | "manifest" | null {
  if (key === personalIndexOverlayFamilyTerminalManifestKey(expected.jobId, expected.cohortId)) {
    return "manifest";
  }
  if (
    key ===
    personalIndexOverlayFamilyArtifactKey("prepared-panel", digest, expected.cohortId)
  ) {
    return "prepared-panel";
  }
  return key === personalIndexOverlayFamilyArtifactKey("report", digest, expected.cohortId)
    ? "report"
    : null;
}

function authority(
  value: JsonObject,
  expected: Identity,
  input: PersonalIndexOverlayFamilyInputManifest,
): boolean {
  return (
    value.job_id === expected.jobId &&
    value.cohort_id === expected.cohortId &&
    value.base_job_id === input.base.job_id &&
    value.svi_job_id === input.svi.job_id &&
    value.input_manifest_digest === expected.inputDigest &&
    value.draft_only === true &&
    value.screening_only === true &&
    value.ready === false &&
    value.mass === false &&
    value.promotion === false &&
    value.live_orders === false &&
    value.go === false &&
    value.not_a_pass === true &&
    value.single_stock_option_iv_used === false
  );
}

async function childrenExist(
  env: R2Env,
  terminal: JsonObject,
  expected: Identity,
): Promise<boolean> {
  const panelDigest = String(terminal.prepared_panel_sha256 ?? "");
  const reportDigest = String(terminal.report_sha256 ?? "");
  if (
    !isPersonalIndexVolOverlay2023Digest(panelDigest) ||
    !isPersonalIndexVolOverlay2023Digest(reportDigest) ||
    terminal.prepared_panel_key !==
      personalIndexOverlayFamilyArtifactKey(
        "prepared-panel",
        panelDigest,
        expected.cohortId,
      ) ||
    terminal.report_key !==
      personalIndexOverlayFamilyArtifactKey("report", reportDigest, expected.cohortId)
  ) {
    return false;
  }
  const [panel, report] = await Promise.all([
    env.STRUCTURED_BUCKET.head(String(terminal.prepared_panel_key)),
    env.STRUCTURED_BUCKET.head(String(terminal.report_key)),
  ]);
  return (
    panel?.customMetadata?.sha256 === panelDigest &&
    report?.customMetadata?.sha256 === reportDigest &&
    report?.customMetadata?.prepared_panel_key === terminal.prepared_panel_key &&
    report?.customMetadata?.prepared_panel_sha256 === panelDigest
  );
}

async function reportPanel(
  env: R2Env,
  report: JsonObject,
  expected: Identity,
): Promise<{ key: string; digest: string } | null> {
  const digest = String(report.prepared_panel_sha256 ?? "");
  const key = String(report.prepared_panel_key ?? "");
  if (
    !isPersonalIndexVolOverlay2023Digest(digest) ||
    key !==
      personalIndexOverlayFamilyArtifactKey("prepared-panel", digest, expected.cohortId)
  ) {
    return null;
  }
  const panel = await env.STRUCTURED_BUCKET.head(key);
  return panel?.customMetadata?.sha256 === digest ? { key, digest } : null;
}

async function putOutput(
  request: Request,
  env: R2Env,
  key: string,
  expected: Identity,
): Promise<Response> {
  const digest = request.headers.get("x-content-sha256") ?? "";
  if (!isPersonalIndexVolOverlay2023Digest(digest)) {
    return json({ error: "overlay output digest denied" }, 403);
  }
  const kind = outputKind(key, expected, digest);
  if (!kind) return json({ error: "overlay output key denied" }, 403);
  const maximum = kind === "manifest"
    ? PERSONAL_INDEX_VOL_OVERLAY_2023_TERMINAL_MAX_BYTES
    : PERSONAL_INDEX_VOL_OVERLAY_2023_RESULT_MAX_BYTES;
  const length = declaredLength(request, maximum);
  if (length === null) return json({ error: "overlay output length denied" }, 400);
  const input = await readInput(env, expected);
  if (!input) return json({ error: "overlay input manifest denied" }, 403);
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.byteLength !== length || `sha256:${await sha256Hex(bytes)}` !== digest) {
    return json({ error: "overlay output bytes mismatch" }, 400);
  }
  let document: unknown;
  try {
    document = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return json({ error: "overlay output must be JSON" }, 400);
  }
  const overlaySchemas = {
    "prepared-panel": "personal-index-vol-overlay-prepared-panel/v1",
    report: "personal-index-vol-overlay-report/v1",
    manifest: "personal-index-vol-overlay-manifest/v1",
  } as const;
  const smileSchemas = {
    "prepared-panel": "personal-index-smile-transport-prepared-panel/v2",
    report: "personal-index-smile-transport-report/v2",
    manifest: "personal-index-smile-transport-manifest/v2",
  } as const;
  const overlayAmPmSchemas = {
    "prepared-panel": "personal-index-vol-overlay-am-pm-prepared-panel/v1",
    report: "personal-index-vol-overlay-am-pm-report/v1",
    manifest: "personal-index-vol-overlay-am-pm-manifest/v1",
  } as const;
  const smileAmPmSchemas = {
    "prepared-panel": "personal-index-smile-transport-am-pm-prepared-panel/v1",
    report: "personal-index-smile-transport-am-pm-report/v1",
    manifest: "personal-index-smile-transport-am-pm-manifest/v1",
  } as const;
  const schemas = isPersonalIndexSmileTransport2023AmPmCohort(expected.cohortId)
    ? smileAmPmSchemas
    : isPersonalIndexVolOverlay2023AmPmCohort(expected.cohortId)
      ? overlayAmPmSchemas
      : isPersonalIndexSmileTransport2023Cohort(expected.cohortId)
        ? smileSchemas
        : overlaySchemas;
  if (!isObject(document) || document.schema_version !== schemas[kind] || !authority(document, expected, input.manifest)) {
    return json({ error: "overlay output contract mismatch" }, 400);
  }
  const panelReference = kind === "report" ? await reportPanel(env, document, expected) : null;
  if (kind === "report" && panelReference === null) {
    return json({ error: "overlay report panel mismatch" }, 409);
  }
  if (kind === "manifest") {
    if (document.status !== "COMPLETED" && document.status !== "FAILED") {
      return json({ error: "overlay manifest status denied" }, 400);
    }
    if (
      document.runner_version !==
        personalIndexOverlayFamilyRunnerVersion(expected.cohortId) ||
      document.schema_version !==
        personalIndexOverlayFamilyTerminalSchema(expected.cohortId) ||
      typeof document.request_digest !== "string" ||
      !isPersonalIndexVolOverlay2023Digest(document.request_digest)
    ) {
      return json({ error: "overlay output contract mismatch" }, 400);
    }
    if (document.status === "COMPLETED" && !(await childrenExist(env, document, expected))) {
      return json({ error: "overlay manifest children mismatch" }, 409);
    }
  }
  const stored = await putBytesCreateOnly(
    env.STRUCTURED_BUCKET,
    key,
    bytes,
    {
      digest,
      contentType: "application/json; charset=utf-8",
      customMetadata: {
        plane: isPersonalIndexSmileTransport2023AmPmCohort(expected.cohortId)
          ? "personal_index_smile_transport_2023_am_pm"
          : isPersonalIndexVolOverlay2023AmPmCohort(expected.cohortId)
            ? "personal_index_vol_overlay_2023_am_pm"
            : isPersonalIndexSmileTransport2023Cohort(expected.cohortId)
              ? "personal_index_smile_transport_2023"
              : "personal_index_vol_overlay_2023",
        kind,
        job_id: expected.jobId,
        input_manifest_digest: expected.inputDigest,
        ...(panelReference
          ? {
              prepared_panel_key: panelReference.key,
              prepared_panel_sha256: panelReference.digest,
            }
          : {}),
      },
    },
  );
  return stored.conflict
    ? json({ error: "immutable overlay output conflict" }, 409)
    : json({ ok: true, created: stored.created, key }, stored.created ? 201 : 200);
}

export function isPersonalIndexVolOverlayOutboundRequest(
  request: Request,
  key: string,
): boolean {
  return key.startsWith("research/personal/index-vol-overlay-2023/") ||
    key.startsWith("research/personal/index-smile-transport-2023/") ||
    key.startsWith("research/personal/index-vol-overlay-2023-am-pm/") ||
    key.startsWith("research/personal/index-smile-transport-2023-am-pm/") ||
    request.headers.has("x-overlay-job-id");
}

/** Exact-reference R2 capability used only by the existing private Container. */
export async function personalIndexVolOverlayR2Outbound(
  request: Request,
  env: R2Env,
  key: string,
): Promise<Response> {
  const expected = identity(request);
  if (!expected) return json({ error: "overlay R2 identity denied" }, 403);
  if (request.method === "GET" || request.method === "HEAD") {
    return getInput(request, env, key, expected);
  }
  return request.method === "PUT"
    ? putOutput(request, env, key, expected)
    : json({ error: "overlay R2 method denied" }, 403);
}
