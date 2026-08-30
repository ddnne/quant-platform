import { describe, expect, it } from "vitest";

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
  PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
  PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY,
  PERSONAL_INDEX_VOL_OVERLAY_AM_PM_CANDIDATE_IDS,
  personalIndexOverlayFamilyRunnerVersion,
  personalIndexOverlayFamilyTerminalManifestKey,
  personalIndexOverlayFamilyTerminalSchema,
  personalIndexSmileTransport2023AmPmInputManifestKey,
  personalIndexSmileTransport2023ArtifactKey,
  personalIndexSmileTransport2023InputManifestKey,
  personalIndexSmileTransport2023TerminalManifestKey,
  personalIndexVolOverlay2023AmPmArtifactKey,
  personalIndexVolOverlay2023AmPmInputManifestKey,
  personalIndexVolOverlay2023ArtifactKey,
  personalIndexVolOverlay2023InputManifestKey,
  personalIndexVolOverlay2023TerminalManifestKey,
  type PersonalIndexSmileTransport2023InputManifest,
  type PersonalIndexVolOverlay2023AmPmInputManifest,
  type PersonalIndexVolOverlay2023InputManifest,
} from "./personal_index_vol_overlay_2023_contract";
import { personalIndexVolOverlayR2Outbound } from "./personal_index_vol_overlay_r2";
import { personalResearchR2Outbound } from "./personal_research_r2";
import { sha256Hex } from "./sha256";

type Stored = { bytes: Uint8Array; etag: string; customMetadata: Record<string, string> };

class MemoryR2 {
  readonly values = new Map<string, Stored>();
  readonly writes: string[] = [];

  seed(key: string, bytes: Uint8Array, etag: string, customMetadata: Record<string, string> = {}) {
    this.values.set(key, { bytes, etag, customMetadata });
  }

  object(key: string, stored: Stored): R2ObjectBody {
    return {
      key,
      size: stored.bytes.byteLength,
      etag: stored.etag,
      httpEtag: `"${stored.etag}"`,
      uploaded: new Date(0),
      checksums: {} as R2Checksums,
      customMetadata: stored.customMetadata,
      httpMetadata: {},
      storageClass: "Standard",
      body: new ReadableStream({ start(controller) { controller.enqueue(stored.bytes); controller.close(); } }),
      arrayBuffer: async () => stored.bytes.slice().buffer,
      writeHttpMetadata() {},
    } as R2ObjectBody;
  }

  async get(key: string) {
    const value = this.values.get(key);
    return value ? this.object(key, value) : null;
  }

  async head(key: string) {
    const value = this.values.get(key);
    return value ? this.object(key, value) : null;
  }

  async put(key: string, value: ArrayBuffer | ArrayBufferView | string, options?: R2PutOptions) {
    if (options?.onlyIf && "etagDoesNotMatch" in options.onlyIf && this.values.has(key)) return null;
    const bytes = typeof value === "string"
      ? new TextEncoder().encode(value)
      : ArrayBuffer.isView(value)
        ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength).slice()
        : new Uint8Array(value).slice();
    const stored = { bytes, etag: `write-${this.writes.length}`, customMetadata: options?.customMetadata ?? {} };
    this.writes.push(key);
    this.values.set(key, stored);
    return this.object(key, stored);
  }

  asBucket(): R2Bucket { return this as unknown as R2Bucket; }
}

async function fixture() {
  const jobId = "overlay-r2";
  const rawKey = "structured/jsonl/derivatives_bars_daily_options_225/dt=2023-01-04/admitted.jsonl";
  const raw = new TextEncoder().encode("admitted raw");
  const inputKey = personalIndexVolOverlay2023InputManifestKey(jobId);
  const digest = (digit: string) => `sha256:${digit.repeat(64)}`;
  const input: PersonalIndexVolOverlay2023InputManifest = {
    schema_version: "personal-index-vol-overlay-2023-input/v1",
    job_id: jobId,
    cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
    runner_version: PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
    base: {
      job_id: "base-r2",
      result: { key: "research/personal/jobs/job=base-r2/result.tar.gz", etag: "base", size: 1, sha256: digest("1") },
      snapshot: { key: `research/personal/snapshots/sha256=${"2".repeat(64)}.sqlite`, etag: "snapshot", size: 1, raw_sha256: digest("2") },
      sleeve_artifact: {
        archive_member: `base-sleeve/${"3".repeat(64)}.json`,
        sha256: digest("3"),
      },
    },
    svi: {
      job_id: "svi-r2",
      request_digest: digest("4"),
      input_manifest: { key: "research/personal/svi-2023/job=svi-r2/input-manifest.json", etag: "svi-input", size: 1, sha256: digest("5") },
      feature: { key: "research/personal/svi-2023/job=svi-r2/features.jsonl", etag: "feature", size: 1, sha256: digest("6") },
      panel: { key: "research/mass_eval/panels_cache/panel.json", etag: "panel", size: 1, sha256: digest("8") },
      options: { days: [{ date: "2023-01-04", objects: [{ key: rawKey, etag: "raw", size: raw.byteLength, sha256: digest("9") }] }], object_count: 1, total_bytes: raw.byteLength },
    },
    fixed_window: { start: "2023-01-04", end: "2023-10-13", signal_start_policy: PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY, signal_end_policy: "LAST_SESSION_MINUS_TWO" },
    temporal_contract: { source_decision_cutoff_jst: "15:00:00+09:00", prepared_available_at: "SAME_DAY_23_59_59_JST", fill_timing: "next_close", first_pnl_interval: "fill_close_to_following_close", no_forward_fill: true },
    authority: { draft_only: true, screening_only: true, ready: false, mass: false, promotion: false, live_orders: false, go: false, single_stock_option_iv: "FORBIDDEN" },
  };
  const inputBytes = new TextEncoder().encode(JSON.stringify(input));
  const inputDigest = `sha256:${await sha256Hex(inputBytes)}`;
  const mem = new MemoryR2();
  mem.seed(inputKey, inputBytes, "input");
  mem.seed(rawKey, raw, "raw");
  const headers = {
    "x-overlay-job-id": jobId,
    "x-overlay-input-manifest-key": inputKey,
    "x-overlay-input-manifest-digest": inputDigest,
  };
  return { jobId, rawKey, raw, inputDigest, headers, mem };
}

function authority(fixed: Awaited<ReturnType<typeof fixture>>) {
  return {
    job_id: fixed.jobId,
    cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
    base_job_id: "base-r2",
    svi_job_id: "svi-r2",
    input_manifest_digest: fixed.inputDigest,
    draft_only: true,
    screening_only: true,
    ready: false,
    mass: false,
    promotion: false,
    live_orders: false,
    go: false,
    not_a_pass: true,
    single_stock_option_iv_used: false,
  };
}

async function put(
  fixed: Awaited<ReturnType<typeof fixture>>,
  kind: "prepared-panel" | "report" | "manifest",
  document: Record<string, unknown>,
) {
  const bytes = new TextEncoder().encode(JSON.stringify(document));
  const digest = `sha256:${await sha256Hex(bytes)}`;
  const key = kind === "manifest"
    ? personalIndexVolOverlay2023TerminalManifestKey(fixed.jobId)
    : personalIndexVolOverlay2023ArtifactKey(kind, digest);
  const response = await personalIndexVolOverlayR2Outbound(
    new Request(`http://research.r2/${key}`, {
      method: "PUT",
      headers: { ...fixed.headers, "content-length": String(bytes.byteLength), "x-content-sha256": digest },
      body: bytes,
    }),
    { STRUCTURED_BUCKET: fixed.mem.asBucket() },
    key,
  );
  return { response, digest, key };
}

describe("index-vol overlay exact-reference R2 capability", () => {
  it("serves an admitted raw object and rejects an unlisted sibling", async () => {
    const fixed = await fixture();
    const allowed = await personalIndexVolOverlayR2Outbound(
      new Request(`http://research.r2/${fixed.rawKey}`, { headers: fixed.headers }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      fixed.rawKey,
    );
    expect(allowed.status).toBe(200);
    expect(new Uint8Array(await allowed.arrayBuffer())).toEqual(fixed.raw);
    const deniedKey = fixed.rawKey.replace("admitted", "unlisted");
    const denied = await personalIndexVolOverlayR2Outbound(
      new Request(`http://research.r2/${deniedKey}`, { headers: fixed.headers }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      deniedKey,
    );
    expect(denied.status).toBe(403);
  });

  it("requires content-addressed children before the terminal and replays idempotently", async () => {
    const fixed = await fixture();
    const panelDoc = { schema_version: "personal-index-vol-overlay-prepared-panel/v1", ...authority(fixed) };
    const panelBytes = new TextEncoder().encode(JSON.stringify(panelDoc));
    const panelDigest = `sha256:${await sha256Hex(panelBytes)}`;
    const reportDoc = {
      schema_version: "personal-index-vol-overlay-report/v1",
      ...authority(fixed),
      prepared_panel_key: personalIndexVolOverlay2023ArtifactKey("prepared-panel", panelDigest),
      prepared_panel_sha256: panelDigest,
    };
    const reportBytes = new TextEncoder().encode(JSON.stringify(reportDoc));
    const reportDigest = `sha256:${await sha256Hex(reportBytes)}`;
    const terminalDoc = {
      schema_version: "personal-index-vol-overlay-manifest/v1",
      status: "COMPLETED",
      ...authority(fixed),
      runner_version: PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
      request_digest: `sha256:${"e".repeat(64)}`,
      prepared_panel_key: personalIndexVolOverlay2023ArtifactKey("prepared-panel", panelDigest),
      prepared_panel_sha256: panelDigest,
      report_key: personalIndexVolOverlay2023ArtifactKey("report", reportDigest),
      report_sha256: reportDigest,
    };
    expect((await put(fixed, "manifest", terminalDoc)).response.status).toBe(409);
    expect((await put(fixed, "report", reportDoc)).response.status).toBe(409);
    const panel = await put(fixed, "prepared-panel", panelDoc);
    const report = await put(fixed, "report", reportDoc);
    const terminal = await put(fixed, "manifest", terminalDoc);
    expect([panel.response.status, report.response.status, terminal.response.status]).toEqual([201, 201, 201]);
    expect(fixed.mem.writes).toEqual([panel.key, report.key, terminal.key]);
    expect((await put(fixed, "prepared-panel", panelDoc)).response.status).toBe(200);
    expect(fixed.mem.writes).toHaveLength(3);
  });
});

async function smileFixture() {
  const jobId = "smile-r2";
  const rawKey = "structured/jsonl/derivatives_bars_daily_options_225/dt=2023-01-04/admitted.jsonl";
  const raw = new TextEncoder().encode("admitted raw");
  const inputKey = personalIndexSmileTransport2023InputManifestKey(jobId);
  const digest = (digit: string) => `sha256:${digit.repeat(64)}`;
  const input: PersonalIndexSmileTransport2023InputManifest = {
    schema_version: "personal-index-smile-transport-2023-input/v2",
    job_id: jobId,
    cohort_id: PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID,
    runner_version: PERSONAL_INDEX_SMILE_TRANSPORT_2023_RUNNER_VERSION,
    base: {
      job_id: "base-r2",
      result: { key: "research/personal/jobs/job=base-r2/result.tar.gz", etag: "base", size: 1, sha256: digest("1") },
      snapshot: { key: `research/personal/snapshots/sha256=${"2".repeat(64)}.sqlite`, etag: "snapshot", size: 1, raw_sha256: digest("2") },
      sleeve_artifact: {
        archive_member: `base-sleeve/${"3".repeat(64)}.json`,
        sha256: digest("3"),
      },
    },
    svi: {
      job_id: "svi-r2",
      request_digest: digest("4"),
      input_manifest: { key: "research/personal/svi-2023/job=svi-r2/input-manifest.json", etag: "svi-input", size: 1, sha256: digest("5") },
      feature: { key: "research/personal/svi-2023/job=svi-r2/features.jsonl", etag: "feature", size: 1, sha256: digest("6") },
      panel: { key: "research/mass_eval/panels_cache/panel.json", etag: "panel", size: 1, sha256: digest("8") },
      options: { days: [{ date: "2023-01-04", objects: [{ key: rawKey, etag: "raw", size: raw.byteLength, sha256: digest("9") }] }], object_count: 1, total_bytes: raw.byteLength },
    },
    fixed_window: {
      start: "2023-01-04",
      end: "2023-10-13",
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
      downside_q: "actual_downside_smile_term_ratio/predicted_downside_smile_term_ratio-1",
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
    physical_potential: { metaphor_only: true, causal_claim: false },
    svi_features_jsonl: {
      trusted_for_transport: false,
      reason: "lacks_exact_expiry_svi_parameters_and_fit_bands",
    },
    authority: { draft_only: true, screening_only: true, ready: false, mass: false, promotion: false, live_orders: false, go: false, single_stock_option_iv: "FORBIDDEN" },
  };
  const inputBytes = new TextEncoder().encode(JSON.stringify(input));
  const inputDigest = `sha256:${await sha256Hex(inputBytes)}`;
  const mem = new MemoryR2();
  mem.seed(inputKey, inputBytes, "input");
  mem.seed(rawKey, raw, "raw");
  const headers = {
    "x-overlay-job-id": jobId,
    "x-overlay-input-manifest-key": inputKey,
    "x-overlay-input-manifest-digest": inputDigest,
  };
  return { jobId, rawKey, raw, inputDigest, headers, mem };
}

describe("index-smile-transport exact-reference R2 capability", () => {
  it("rejects v1 overlay schemas on the closed v2 terminal path", async () => {
    const fixed = await smileFixture();
    const panelDoc = {
      schema_version: "personal-index-vol-overlay-prepared-panel/v1",
      job_id: fixed.jobId,
      cohort_id: PERSONAL_INDEX_SMILE_TRANSPORT_2023_COHORT_ID,
      base_job_id: "base-r2",
      svi_job_id: "svi-r2",
      input_manifest_digest: fixed.inputDigest,
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
      not_a_pass: true,
      single_stock_option_iv_used: false,
    };
    const bytes = new TextEncoder().encode(JSON.stringify(panelDoc));
    const digest = `sha256:${await sha256Hex(bytes)}`;
    const key = personalIndexSmileTransport2023ArtifactKey("prepared-panel", digest);
    const denied = await personalIndexVolOverlayR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: { ...fixed.headers, "content-length": String(bytes.byteLength), "x-content-sha256": digest },
        body: bytes,
      }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      key,
    );
    expect(denied.status).toBe(400);
    const acceptedDoc = { ...panelDoc, schema_version: "personal-index-smile-transport-prepared-panel/v2" };
    const acceptedBytes = new TextEncoder().encode(JSON.stringify(acceptedDoc));
    const acceptedDigest = `sha256:${await sha256Hex(acceptedBytes)}`;
    const acceptedKey = personalIndexSmileTransport2023ArtifactKey("prepared-panel", acceptedDigest);
    const accepted = await personalIndexVolOverlayR2Outbound(
      new Request(`http://research.r2/${acceptedKey}`, {
        method: "PUT",
        headers: { ...fixed.headers, "content-length": String(acceptedBytes.byteLength), "x-content-sha256": acceptedDigest },
        body: acceptedBytes,
      }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      acceptedKey,
    );
    expect(accepted.status).toBe(201);
    expect(acceptedKey.startsWith("research/personal/index-smile-transport-2023/")).toBe(true);
    expect(personalIndexSmileTransport2023TerminalManifestKey(fixed.jobId)).not.toBe(
      personalIndexVolOverlay2023TerminalManifestKey(fixed.jobId),
    );
  });
});

async function amPmFixture() {
  const jobId = "overlay-am-pm-r2";
  const rawKey = "structured/jsonl/derivatives_bars_daily_options_225/dt=2023-01-04/admitted.jsonl";
  const raw = new TextEncoder().encode("admitted raw");
  const inputKey = personalIndexVolOverlay2023AmPmInputManifestKey(jobId);
  const digest = (digit: string) => `sha256:${digit.repeat(64)}`;
  const input: PersonalIndexVolOverlay2023AmPmInputManifest = {
    schema_version: "personal-index-vol-overlay-2023-am-pm-input/v1",
    job_id: jobId,
    cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
    runner_version: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_RUNNER_VERSION,
    base: {
      job_id: "base-r2",
      result: { key: "research/personal/jobs/job=base-r2/result.tar.gz", etag: "base", size: 1, sha256: digest("1") },
      snapshot: { key: `research/personal/snapshots/sha256=${"2".repeat(64)}.sqlite`, etag: "snapshot", size: 1, raw_sha256: digest("2") },
      sleeve_artifact: {
        archive_member: `base-sleeve/${"3".repeat(64)}.json`,
        sha256: digest("3"),
      },
    },
    svi: {
      job_id: "svi-r2",
      request_digest: digest("4"),
      input_manifest: { key: "research/personal/svi-2023/job=svi-r2/input-manifest.json", etag: "svi-input", size: 1, sha256: digest("5") },
      feature: { key: "research/personal/svi-2023/job=svi-r2/features.jsonl", etag: "feature", size: 1, sha256: digest("6") },
      panel: { key: "research/mass_eval/panels_cache/panel.json", etag: "panel", size: 1, sha256: digest("8") },
      options: { days: [{ date: "2023-01-04", objects: [{ key: rawKey, etag: "raw", size: raw.byteLength, sha256: digest("9") }] }], object_count: 1, total_bytes: raw.byteLength },
    },
    fixed_window: {
      start: "2023-01-04",
      end: "2023-10-13",
      signal_start_policy: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_SIGNAL_START_POLICY,
      signal_end_policy: "LAST_SESSION_MINUS_ONE",
    },
    temporal_contract: {
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
    },
    candidates: {
      ids: PERSONAL_INDEX_VOL_OVERLAY_AM_PM_CANDIDATE_IDS,
      selection: "NOT_PERFORMED",
      adaptive_model_switch: false,
    },
    selection: "NOT_PERFORMED",
    proxy_mapping: {
      executable_hedge_code: "13060",
      n225_etf_if_required: "13210",
      cash_index_executable_fill_claim: false,
      tracking_basis_risk: true,
    },
    authority: { draft_only: true, screening_only: true, ready: false, mass: false, promotion: false, live_orders: false, go: false, single_stock_option_iv: "FORBIDDEN" },
  };
  const inputBytes = new TextEncoder().encode(JSON.stringify(input));
  const inputDigest = `sha256:${await sha256Hex(inputBytes)}`;
  const mem = new MemoryR2();
  mem.seed(inputKey, inputBytes, "input");
  mem.seed(rawKey, raw, "raw");
  const headers = {
    "x-overlay-job-id": jobId,
    "x-overlay-input-manifest-key": inputKey,
    "x-overlay-input-manifest-digest": inputDigest,
  };
  return { jobId, rawKey, raw, inputDigest, headers, mem };
}

describe("index-vol overlay AM/PM exact-reference R2 capability", () => {
  it("rejects next-close overlay schemas on the AM/PM terminal path", async () => {
    const fixed = await amPmFixture();
    const panelDoc = {
      schema_version: "personal-index-vol-overlay-prepared-panel/v1",
      job_id: fixed.jobId,
      cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
      base_job_id: "base-r2",
      svi_job_id: "svi-r2",
      input_manifest_digest: fixed.inputDigest,
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
      not_a_pass: true,
      single_stock_option_iv_used: false,
    };
    const bytes = new TextEncoder().encode(JSON.stringify(panelDoc));
    const digest = `sha256:${await sha256Hex(bytes)}`;
    const key = personalIndexVolOverlay2023AmPmArtifactKey("prepared-panel", digest);
    const denied = await personalIndexVolOverlayR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: { ...fixed.headers, "content-length": String(bytes.byteLength), "x-content-sha256": digest },
        body: bytes,
      }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      key,
    );
    expect(denied.status).toBe(400);
    const acceptedDoc = { ...panelDoc, schema_version: "personal-index-vol-overlay-am-pm-prepared-panel/v1" };
    const acceptedBytes = new TextEncoder().encode(JSON.stringify(acceptedDoc));
    const acceptedDigest = `sha256:${await sha256Hex(acceptedBytes)}`;
    const acceptedKey = personalIndexVolOverlay2023AmPmArtifactKey("prepared-panel", acceptedDigest);
    const accepted = await personalIndexVolOverlayR2Outbound(
      new Request(`http://research.r2/${acceptedKey}`, {
        method: "PUT",
        headers: { ...fixed.headers, "content-length": String(acceptedBytes.byteLength), "x-content-sha256": acceptedDigest },
        body: acceptedBytes,
      }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      acceptedKey,
    );
    expect(accepted.status).toBe(201);
    expect(acceptedKey.startsWith("research/personal/index-vol-overlay-2023-am-pm/")).toBe(true);
  });
});

async function smileAmPmFixture() {
  const jobId = "smile-am-pm-r2";
  const rawKey = "structured/jsonl/derivatives_bars_daily_options_225/dt=2023-01-04/admitted.jsonl";
  const raw = new TextEncoder().encode("admitted raw");
  const inputKey = personalIndexSmileTransport2023AmPmInputManifestKey(jobId);
  const digest = (digit: string) => `sha256:${digit.repeat(64)}`;
  const input = {
    schema_version: "personal-index-smile-transport-2023-am-pm-input/v1",
    job_id: jobId,
    cohort_id: PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID,
    runner_version: PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_RUNNER_VERSION,
    base: {
      job_id: "base-r2",
      result: { key: "research/personal/jobs/job=base-r2/result.tar.gz", etag: "base", size: 1, sha256: digest("1") },
      snapshot: { key: `research/personal/snapshots/sha256=${"2".repeat(64)}.sqlite`, etag: "snapshot", size: 1, raw_sha256: digest("2") },
      sleeve_artifact: { archive_member: `base-sleeve/${"3".repeat(64)}.json`, sha256: digest("3") },
    },
    svi: {
      job_id: "svi-r2",
      request_digest: digest("4"),
      input_manifest: { key: "research/personal/svi-2023/job=svi-r2/input-manifest.json", etag: "svi-input", size: 1, sha256: digest("5") },
      feature: { key: "research/personal/svi-2023/job=svi-r2/features.jsonl", etag: "feature", size: 1, sha256: digest("6") },
      panel: { key: "research/mass_eval/panels_cache/panel.json", etag: "panel", size: 1, sha256: digest("8") },
      options: { days: [{ date: "2023-01-04", objects: [{ key: rawKey, etag: "raw", size: raw.byteLength, sha256: digest("9") }] }], object_count: 1, total_bytes: raw.byteLength },
    },
    fixed_window: {
      start: "2023-01-04",
      end: "2023-10-13",
      signal_start_policy: PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_SIGNAL_START_POLICY,
      signal_end_policy: "LAST_SESSION_MINUS_ONE",
    },
    temporal_contract: {
      source_decision_cutoff_jst: "11:30:00+09:00",
      equity_am_usable_by_jst: "12:30:00+09:00",
      prepared_available_at: "NO_LATER_THAN_D_12_30_JST",
      fill_timing: "d_pm_aadjc",
      first_pnl_interval: "d_pm_to_d_plus_1_pm",
      order_sizing: "d_am_price",
      option_signal_as_of: "through_d_minus_1",
      smile_transport_pair: "d_minus_2_to_d_minus_1",
      no_forward_fill: true,
      no_full_close_fallback: true,
      no_recovery_promotion: true,
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
      downside_q: "actual_downside_smile_term_ratio/predicted_downside_smile_term_ratio-1",
      downside_g: "clip(1/(1+q),0.5,1.0)",
      potential_minimum_M: "(abs(e_front)+abs(e_next))/2+abs(e_next-e_front)",
      potential_minimum_g: "clip(1/(1+M/0.10),0.5,1.0)",
      hedge_h: "clip(-g*beta_D,-1.5,1.5)",
    },
    gate: { min_common_valid_signal_days: 40 },
    physical_potential: { metaphor_only: true, causal_claim: false },
    svi_features_jsonl: { trusted_for_transport: false },
    selection: "NOT_PERFORMED",
    proxy_mapping: {
      executable_hedge_code: "13060",
      n225_etf_if_required: "13210",
      cash_index_executable_fill_claim: false,
      tracking_basis_risk: true,
    },
    authority: { draft_only: true, screening_only: true, ready: false, mass: false, promotion: false, live_orders: false, go: false, single_stock_option_iv: "FORBIDDEN" },
  };
  const inputBytes = new TextEncoder().encode(JSON.stringify(input));
  const inputDigest = `sha256:${await sha256Hex(inputBytes)}`;
  const mem = new MemoryR2();
  mem.seed(inputKey, inputBytes, "input");
  mem.seed(rawKey, raw, "raw");
  return {
    jobId,
    inputDigest,
    headers: {
      "x-overlay-job-id": jobId,
      "x-overlay-input-manifest-key": inputKey,
      "x-overlay-input-manifest-digest": inputDigest,
    },
    mem,
  };
}

describe("AM overlay/smile generic terminal verify-and-shutdown path", () => {
  it.each([
    ["overlay", PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID, amPmFixture] as const,
    ["smile", PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID, smileAmPmFixture] as const,
  ])("PUT-conflicts then GET-verifies the %s AM family", async (_label, cohortId, fixture) => {
    const fixed = await fixture();
    const requestDigest = `sha256:${"e".repeat(64)}`;
    const runner = personalIndexOverlayFamilyRunnerVersion(cohortId);
    const schema = personalIndexOverlayFamilyTerminalSchema(cohortId);
    const key = personalIndexOverlayFamilyTerminalManifestKey(fixed.jobId, cohortId);
    const terminal = {
      schema_version: schema,
      job_id: fixed.jobId,
      cohort_id: cohortId,
      base_job_id: "base-r2",
      svi_job_id: "svi-r2",
      input_manifest_digest: fixed.inputDigest,
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
      not_a_pass: true,
      single_stock_option_iv_used: false,
      status: "FAILED",
      runner_version: runner,
      request_digest: requestDigest,
    };
    const bytes = new TextEncoder().encode(JSON.stringify(terminal));
    const digest = `sha256:${await sha256Hex(bytes)}`;
    const env = { STRUCTURED_BUCKET: fixed.mem.asBucket() };
    const created = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: {
          ...fixed.headers,
          "content-length": String(bytes.byteLength),
          "x-content-sha256": digest,
        },
        body: bytes,
      }),
      env,
    );
    expect(created.status).toBe(201);
    const personal = {
      "x-personal-job-id": fixed.jobId,
      "x-personal-request-digest": requestDigest,
      "x-personal-runner-version": runner,
      "x-personal-job-kind": "overlay",
      "x-personal-cohort-id": cohortId,
    };
    const republish = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: {
          ...personal,
          "content-length": String(bytes.byteLength),
          "x-content-sha256": digest,
        },
        body: bytes,
      }),
      env,
    );
    expect(republish.status).toBe(200);
    const verified = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, { method: "GET", headers: personal }),
      env,
    );
    expect(verified.status).toBe(200);
    expect(await verified.json()).toEqual(terminal);
    const wrongFamily = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "GET",
        headers: {
          ...personal,
          "x-personal-cohort-id":
            cohortId === PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID
              ? PERSONAL_INDEX_SMILE_TRANSPORT_2023_AM_PM_COHORT_ID
              : PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID,
        },
      }),
      env,
    );
    expect(wrongFamily.status).toBe(403);
    const wrongDigest = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "GET",
        headers: { ...personal, "x-personal-request-digest": `sha256:${"f".repeat(64)}` },
      }),
      env,
    );
    expect(wrongDigest.status).toBe(403);
    const wrongKey = await personalResearchR2Outbound(
      new Request(
        `http://research.r2/${personalIndexOverlayFamilyTerminalManifestKey(fixed.jobId, PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID)}`,
        { method: "GET", headers: personal },
      ),
      env,
    );
    expect(wrongKey.status).toBe(403);
  });

  it("rejects malformed AM identity on create-only PUT without writing a terminal", async () => {
    const fixed = await amPmFixture();
    const cohortId = PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID;
    const key = personalIndexOverlayFamilyTerminalManifestKey(fixed.jobId, cohortId);
    const env = { STRUCTURED_BUCKET: fixed.mem.asBucket() };
    const poisoned = {
      schema_version: personalIndexOverlayFamilyTerminalSchema(cohortId),
      job_id: fixed.jobId,
      cohort_id: cohortId,
      base_job_id: "base-r2",
      svi_job_id: "svi-r2",
      input_manifest_digest: fixed.inputDigest,
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
      not_a_pass: true,
      single_stock_option_iv_used: false,
      status: "FAILED",
    };
    const bytes = new TextEncoder().encode(JSON.stringify(poisoned));
    const digest = `sha256:${await sha256Hex(bytes)}`;
    const familyPut = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: {
          ...fixed.headers,
          "content-length": String(bytes.byteLength),
          "x-content-sha256": digest,
        },
        body: bytes,
      }),
      env,
    );
    expect(familyPut.status).toBe(400);
    expect(fixed.mem.values.has(key)).toBe(false);
    const genericPut = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: {
          "content-length": String(bytes.byteLength),
          "x-content-sha256": digest,
          "x-personal-job-id": fixed.jobId,
          "x-personal-request-digest": `sha256:${"e".repeat(64)}`,
          "x-personal-runner-version": personalIndexOverlayFamilyRunnerVersion(cohortId),
          "x-personal-job-kind": "overlay",
          "x-personal-cohort-id": cohortId,
        },
        body: bytes,
      }),
      env,
    );
    expect(genericPut.status).toBe(400);
    expect(fixed.mem.values.has(key)).toBe(false);
  });

  it("creates a valid AM terminal that GET can verify for shutdown", async () => {
    const fixed = await amPmFixture();
    const cohortId = PERSONAL_INDEX_VOL_OVERLAY_2023_AM_PM_COHORT_ID;
    const runner = personalIndexOverlayFamilyRunnerVersion(cohortId);
    const requestDigest = `sha256:${"e".repeat(64)}`;
    const key = personalIndexOverlayFamilyTerminalManifestKey(fixed.jobId, cohortId);
    const terminal = {
      schema_version: personalIndexOverlayFamilyTerminalSchema(cohortId),
      job_id: fixed.jobId,
      cohort_id: cohortId,
      base_job_id: "base-r2",
      svi_job_id: "svi-r2",
      input_manifest_digest: fixed.inputDigest,
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
      not_a_pass: true,
      single_stock_option_iv_used: false,
      status: "FAILED",
      runner_version: runner,
      request_digest: requestDigest,
    };
    const bytes = new TextEncoder().encode(JSON.stringify(terminal));
    const digest = `sha256:${await sha256Hex(bytes)}`;
    const env = { STRUCTURED_BUCKET: fixed.mem.asBucket() };
    const created = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "PUT",
        headers: {
          "content-length": String(bytes.byteLength),
          "x-content-sha256": digest,
          "x-personal-job-id": fixed.jobId,
          "x-personal-request-digest": requestDigest,
          "x-personal-runner-version": runner,
          "x-personal-job-kind": "overlay",
          "x-personal-cohort-id": cohortId,
        },
        body: bytes,
      }),
      env,
    );
    expect(created.status).toBe(201);
    const verified = await personalResearchR2Outbound(
      new Request(`http://research.r2/${key}`, {
        method: "GET",
        headers: {
          "x-personal-job-id": fixed.jobId,
          "x-personal-request-digest": requestDigest,
          "x-personal-runner-version": runner,
          "x-personal-job-kind": "overlay",
          "x-personal-cohort-id": cohortId,
        },
      }),
      env,
    );
    expect(verified.status).toBe(200);
    expect(await verified.json()).toEqual(terminal);
  });
});
