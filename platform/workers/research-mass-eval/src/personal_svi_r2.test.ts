import { describe, expect, it } from "vitest";

import {
  PERSONAL_SVI_2023_COHORT_ID,
  PERSONAL_SVI_2023_DECISION_CUTOFF,
  PERSONAL_SVI_2023_EQUITY_UNIVERSE,
  PERSONAL_SVI_2023_PANEL_KEY,
  PERSONAL_SVI_2023_RUNNER_VERSION,
  PERSONAL_SVI_2023_STRATEGY_ID,
  personalSviFeatureKey,
  personalSviInputManifestKey,
  personalSviJobRequestDigest,
  personalSviReportKey,
  personalSviTerminalManifestKey,
  type PersonalSviInputManifest,
} from "./personal_svi_2023_contract";
import { personalSviR2Outbound } from "./personal_svi_r2";
import { sha256Hex } from "./sha256";

type Stored = {
  bytes: Uint8Array;
  etag: string;
  customMetadata: Record<string, string>;
};

function body(key: string, stored: Stored): R2ObjectBody {
  return {
    key,
    version: "v1",
    size: stored.bytes.byteLength,
    etag: stored.etag,
    httpEtag: `"${stored.etag}"`,
    uploaded: new Date(0),
    checksums: {} as R2Checksums,
    customMetadata: stored.customMetadata,
    httpMetadata: {},
    range: undefined,
    storageClass: "Standard",
    ssecKeyMd5: undefined,
    body: new ReadableStream({
      start(controller) {
        controller.enqueue(stored.bytes);
        controller.close();
      },
    }),
    bodyUsed: false,
    arrayBuffer: async () => stored.bytes.slice().buffer,
    bytes: async () => stored.bytes.slice(),
    text: async () => new TextDecoder().decode(stored.bytes),
    json: async () => JSON.parse(new TextDecoder().decode(stored.bytes)),
    blob: async () => new Blob([stored.bytes]),
    writeHttpMetadata() {},
  } as R2ObjectBody;
}

class MemoryR2 {
  readonly objects = new Map<string, Stored>();
  readonly putOptions: Array<{ key: string; options?: R2PutOptions }> = [];

  seed(
    key: string,
    bytes: Uint8Array,
    etag: string,
    customMetadata: Record<string, string> = {},
  ): void {
    this.objects.set(key, { bytes, etag, customMetadata });
  }

  async get(key: string) {
    const stored = this.objects.get(key);
    return stored ? body(key, stored) : null;
  }

  async head(key: string) {
    const stored = this.objects.get(key);
    return stored ? body(key, stored) : null;
  }

  async put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string,
    options?: R2PutOptions,
  ) {
    this.putOptions.push({ key, options });
    if (
      options?.onlyIf &&
      "etagDoesNotMatch" in options.onlyIf &&
      options.onlyIf.etagDoesNotMatch === "*" &&
      this.objects.has(key)
    ) {
      return null;
    }
    const bytes =
      typeof value === "string"
        ? new TextEncoder().encode(value)
        : ArrayBuffer.isView(value)
          ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength).slice()
          : new Uint8Array(value).slice();
    const stored = {
      bytes,
      etag: `put-${this.putOptions.length}`,
      customMetadata: options?.customMetadata ?? {},
    };
    this.objects.set(key, stored);
    return body(key, stored);
  }

  asBucket(): R2Bucket {
    return this as unknown as R2Bucket;
  }
}

async function fixture() {
  const jobId = "svi-r2-closed";
  const inputKey = personalSviInputManifestKey(jobId);
  const optionKey =
    "structured/jsonl/derivatives_bars_daily_options_225/dt=2023-01-04/run.jsonl";
  const panelBytes = new Uint8Array([1, 2, 3]);
  const optionBytes = new Uint8Array([4, 5, 6]);
  const panelDigest = `sha256:${await sha256Hex(panelBytes)}`;
  const optionDigest = `sha256:${await sha256Hex(optionBytes)}`;
  const manifest: PersonalSviInputManifest = {
    schema_version: "personal-svi-2023-input/v2",
    job_id: jobId,
    cohort_id: PERSONAL_SVI_2023_COHORT_ID,
    runner_version: PERSONAL_SVI_2023_RUNNER_VERSION,
    strategy: {
      strategy_id: PERSONAL_SVI_2023_STRATEGY_ID,
      feature: "svi_atm_short_over_next_minus_one",
      thesis: "fixed test thesis",
      signal_lag_sessions: 1,
      hold_sessions: 10,
      one_way_cost: 0.001,
    },
    panel: {
      key: PERSONAL_SVI_2023_PANEL_KEY,
      etag: "panel-etag",
      size: panelBytes.byteLength,
      sha256: panelDigest,
    },
    equity_universe: PERSONAL_SVI_2023_EQUITY_UNIVERSE,
    options: {
      dataset: "derivatives_bars_daily_options_225",
      natural_key: ["Date", "Code"],
      days: [
        {
          date: "2023-01-04",
          objects: [
            {
              key: optionKey,
              etag: "option-etag",
              size: optionBytes.byteLength,
              sha256: optionDigest,
            },
          ],
        },
      ],
      object_count: 1,
      total_bytes: optionBytes.byteLength,
    },
    sessions: {
      warmup_sessions: 0,
      warmup_dates: [],
      evaluation_dates: ["2023-01-04"],
    },
    temporal_contract: {
      source_decision_cutoff_jst: PERSONAL_SVI_2023_DECISION_CUTOFF,
      signal_lag_sessions: 1,
      fill_timing: "next_close",
      first_pnl_interval: "fill_close_to_following_close",
    },
    authority: {
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
    },
  };
  const inputBytes = new TextEncoder().encode(JSON.stringify(manifest));
  const inputDigest = `sha256:${await sha256Hex(inputBytes)}`;
  const mem = new MemoryR2();
  mem.seed(inputKey, inputBytes, "manifest-etag");
  mem.seed(PERSONAL_SVI_2023_PANEL_KEY, panelBytes, "panel-etag");
  mem.seed(optionKey, optionBytes, "option-etag");
  const headers = {
    "x-svi-job-id": jobId,
    "x-svi-input-manifest-key": inputKey,
    "x-svi-input-manifest-digest": inputDigest,
  };
  return { jobId, inputKey, inputDigest, optionKey, optionBytes, headers, mem };
}

describe("manifest-constrained SVI Container R2 capability", () => {
  it("streams only manifest-listed input keys and rejects arbitrary structured data", async () => {
    const fixed = await fixture();
    const allowed = await personalSviR2Outbound(
      new Request(`http://research.r2/${fixed.optionKey}`, {
        headers: fixed.headers,
      }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      fixed.optionKey,
    );
    expect(allowed.status).toBe(200);
    expect(new Uint8Array(await allowed.arrayBuffer())).toEqual(fixed.optionBytes);

    const arbitrary =
      "structured/jsonl/derivatives_bars_daily_options_225/dt=2023-01-05/secret.jsonl";
    const denied = await personalSviR2Outbound(
      new Request(`http://research.r2/${arbitrary}`, { headers: fixed.headers }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      arbitrary,
    );
    expect(denied.status).toBe(403);
  });

  it("rejects an input whose ETag changed after Worker admission", async () => {
    const fixed = await fixture();
    fixed.mem.seed(fixed.optionKey, fixed.optionBytes, "mutated-etag");
    const response = await personalSviR2Outbound(
      new Request(`http://research.r2/${fixed.optionKey}`, {
        headers: fixed.headers,
      }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      fixed.optionKey,
    );
    expect(response.status).toBe(409);
  });

  it("creates feature, report and verified terminal manifest exactly once", async () => {
    const fixed = await fixture();
    async function put(key: string, value: unknown, contentType = "json") {
      const bytes = new TextEncoder().encode(
        contentType === "jsonl" ? String(value) : JSON.stringify(value),
      );
      const digest = `sha256:${await sha256Hex(bytes)}`;
      const response = await personalSviR2Outbound(
        new Request(`http://research.r2/${key}`, {
          method: "PUT",
          headers: {
            ...fixed.headers,
            "content-length": String(bytes.byteLength),
            "x-content-sha256": digest,
          },
          body: bytes,
        }),
        { STRUCTURED_BUCKET: fixed.mem.asBucket() },
        key,
      );
      return { response, digest, bytes };
    }

    const featureKey = personalSviFeatureKey(fixed.jobId);
    const feature = await put(featureKey, '{"date":"2023-01-04"}\n', "jsonl");
    expect(feature.response.status).toBe(201);
    const reportKey = personalSviReportKey(fixed.jobId);
    const report = await put(reportKey, {
      job_id: fixed.jobId,
      input_manifest_digest: fixed.inputDigest,
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
      not_a_pass: true,
    });
    expect(report.response.status).toBe(201);
    const manifestKey = personalSviTerminalManifestKey(fixed.jobId);
    const terminal = await put(manifestKey, {
      status: "COMPLETED",
      job_id: fixed.jobId,
      input_manifest_digest: fixed.inputDigest,
      feature_key: featureKey,
      feature_sha256: feature.digest,
      report_key: reportKey,
      report_sha256: report.digest,
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
      not_a_pass: true,
    });
    expect(terminal.response.status).toBe(201);
    expect(
      fixed.mem.putOptions.every(
        ({ options }) =>
          options?.onlyIf &&
          "etagDoesNotMatch" in options.onlyIf &&
          options.onlyIf.etagDoesNotMatch === "*",
      ),
    ).toBe(true);

    const replay = await put(featureKey, '{"date":"2023-01-04"}\n', "jsonl");
    expect(replay.response.status).toBe(200);
    expect(await replay.response.json()).toMatchObject({ created: false });
    const conflict = await put(featureKey, '{"date":"changed"}\n', "jsonl");
    expect(conflict.response.status).toBe(409);
  });

  it("rejects late child output creation after an exact FAILED terminal", async () => {
    const fixed = await fixture();
    const terminalKey = personalSviTerminalManifestKey(fixed.jobId);
    const terminal = {
      status: "FAILED",
      job_id: fixed.jobId,
      cohort_id: PERSONAL_SVI_2023_COHORT_ID,
      runner_version: PERSONAL_SVI_2023_RUNNER_VERSION,
      input_manifest_digest: fixed.inputDigest,
      request_digest: await personalSviJobRequestDigest(
        { job_id: fixed.jobId, cohort_id: PERSONAL_SVI_2023_COHORT_ID },
        fixed.inputDigest,
      ),
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
      not_a_pass: true,
    };
    fixed.mem.seed(
      terminalKey,
      new TextEncoder().encode(JSON.stringify(terminal)),
      "failed-terminal",
    );
    const featureKey = personalSviFeatureKey(fixed.jobId);
    const bytes = new TextEncoder().encode('{"date":"late"}\n');
    const response = await personalSviR2Outbound(
      new Request(`http://research.r2/${featureKey}`, {
        method: "PUT",
        headers: {
          ...fixed.headers,
          "content-length": String(bytes.byteLength),
          "x-content-sha256": `sha256:${await sha256Hex(bytes)}`,
        },
        body: bytes,
      }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      featureKey,
    );

    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({
      error: "SVI terminal already exists",
    });
    expect(fixed.mem.objects.has(featureKey)).toBe(false);
    expect(fixed.mem.putOptions).toHaveLength(0);
  });
});
