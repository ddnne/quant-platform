import { describe, expect, it } from "vitest";

import {
  PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
  PERSONAL_INDEX_VOL_OVERLAY_2023_RUNNER_VERSION,
  PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY,
  personalIndexVolOverlay2023ArtifactKey,
  personalIndexVolOverlay2023InputManifestKey,
  personalIndexVolOverlay2023TerminalManifestKey,
  type PersonalIndexVolOverlay2023InputManifest,
} from "./personal_index_vol_overlay_2023_contract";
import { personalIndexVolOverlayR2Outbound } from "./personal_index_vol_overlay_r2";
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
