import { describe, expect, it } from "vitest";

import { PERSONAL_RESEARCH_RUNNER_VERSION } from "./personal_research_contract";
import { PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION } from "./personal_vol_am_pm_panel";
import {
  PERSONAL_VOL_AM_PM_EVALUATION_PERIODS,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_MANIFEST_SCHEMA,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
  personalVolAmPmPanelBuildInputKey,
  personalVolAmPmPanelBuildTerminalKey,
  personalVolAmPmPanelObjectKey,
  type PersonalVolAmPmPanelWriterInputManifest,
} from "./personal_vol_am_pm_panel_writer_contract";
import { personalVolAmPmPanelR2Outbound } from "./personal_vol_am_pm_panel_r2";
import { sha256Hex } from "./sha256";

type Stored = {
  bytes: Uint8Array;
  etag: string;
  customMetadata: Record<string, string>;
  checksums: R2Checksums;
};

async function toBytes(
  value: ArrayBuffer | ArrayBufferView | string | ReadableStream<Uint8Array>,
): Promise<Uint8Array> {
  if (typeof value === "string") return new TextEncoder().encode(value);
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength).slice();
  }
  if (value instanceof ArrayBuffer) return new Uint8Array(value).slice();
  const reader = value.getReader();
  const chunks: Uint8Array[] = [];
  for (;;) {
    const { done, value: chunk } = await reader.read();
    if (done) break;
    if (chunk) chunks.push(chunk);
  }
  const total = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

class MemoryR2 {
  readonly values = new Map<string, Stored>();
  readonly writes: string[] = [];
  parsedBodies = 0;

  seed(key: string, bytes: Uint8Array, etag: string, customMetadata: Record<string, string> = {}) {
    this.values.set(key, { bytes, etag, customMetadata, checksums: {} as R2Checksums });
  }

  object(key: string, stored: Stored): R2ObjectBody {
    return {
      key,
      size: stored.bytes.byteLength,
      etag: stored.etag,
      httpEtag: `"${stored.etag}"`,
      uploaded: new Date(0),
      checksums: stored.checksums,
      customMetadata: stored.customMetadata,
      httpMetadata: {},
      storageClass: "Standard",
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(stored.bytes);
          controller.close();
        },
      }),
      arrayBuffer: async () => stored.bytes.slice().buffer,
      json: async () => {
        this.parsedBodies += 1;
        return JSON.parse(new TextDecoder().decode(stored.bytes));
      },
      writeHttpMetadata() {},
    } as R2ObjectBody;
  }

  async get(key: string) {
    const value = this.values.get(key);
    return value ? this.object(key, value) : null;
  }

  async head(key: string) {
    return this.get(key);
  }

  async put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string | ReadableStream,
    options?: R2PutOptions,
  ) {
    if (
      options?.onlyIf &&
      "etagDoesNotMatch" in options.onlyIf &&
      this.values.has(key)
    ) {
      return null;
    }
    const bytes = await toBytes(value as ArrayBuffer | ArrayBufferView | string | ReadableStream<Uint8Array>);
    const stored: Stored = {
      bytes,
      etag: `write-${this.writes.length}`,
      customMetadata: options?.customMetadata ?? {},
      checksums: options?.sha256
        ? ({ sha256: options.sha256 } as R2Checksums)
        : ({} as R2Checksums),
    };
    this.writes.push(key);
    this.values.set(key, stored);
    return this.object(key, stored);
  }

  asBucket(): R2Bucket {
    return this as unknown as R2Bucket;
  }
}

const JOB_ID = "vol-panel-r2";
const sidecarKey = "research/mass_eval/panels_cache/527c1065afe14601/panels/y2021_full.json";

function digestDigit(digit: string): `sha256:${string}` {
  return `sha256:${digit.repeat(64)}`;
}

function snapshotLock(jobId: string, digit: string, periodId: string, start: string, end: string) {
  const snapshotKey = `research/personal/snapshots/sha256=${digit.repeat(64)}.sqlite.gz`;
  const manifestKey = `research/personal/snapshot-builds/job=${jobId}/manifest.json`;
  const ref = {
    key: snapshotKey,
    etag: `snap-${digit}`,
    size: 3,
    sha256: digestDigit(digit),
    raw_sha256: digestDigit(digit),
    gzip_sha256: digestDigit(digit),
  };
  return {
    job_id: jobId,
    role: periodId === "y2019_selection" ? "selection_2019" : "evaluation_period",
    period_id: periodId,
    period_start: start,
    period_end: end,
    lookback_sessions: periodId === "y2019_selection" ? 0 : 61,
    format: "personal-draft-history/v4" as const,
    runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
    manifest: { key: manifestKey, etag: `man-${digit}`, size: 8, sha256: digestDigit(digit) },
    snapshot: ref,
  };
}

async function fixture() {
  const input: PersonalVolAmPmPanelWriterInputManifest = {
    schema_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA,
    producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
    job_id: JOB_ID,
    cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
    runner_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
    panel_schema: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
    required_lookback_sessions: 61,
    selection: snapshotLock("snap-2019", "1", "y2019_selection", "2019-01-01", "2019-10-21"),
    periods: {
      y2021_full: snapshotLock("snap-2021", "3", "y2021_full", "2021-01-04", "2021-10-15"),
      y2023_full: snapshotLock("snap-2023", "4", "y2023_full", "2023-01-04", "2023-10-13"),
      y2025_q4: snapshotLock("snap-2025", "5", "y2025_q4", "2025-09-01", "2025-12-29"),
    },
    option_sidecars: {
      y2021_full: {
        period_id: "y2021_full",
        source_key: sidecarKey,
        etag: "side-1",
        size: 4,
        sha256: digestDigit("9"),
      },
      y2023_full: {
        period_id: "y2023_full",
        source_key: sidecarKey.replace("y2021_full", "y2023_full"),
        etag: "side-2",
        size: 4,
        sha256: digestDigit("9"),
      },
      y2025_q4: {
        period_id: "y2025_q4",
        source_key: sidecarKey.replace("y2021_full", "y2025_q4"),
        etag: "side-3",
        size: 4,
        sha256: digestDigit("9"),
      },
    },
  };
  const inputBytes = new TextEncoder().encode(JSON.stringify(input));
  const inputDigest = `sha256:${await sha256Hex(inputBytes)}`;
  const mem = new MemoryR2();
  mem.seed(personalVolAmPmPanelBuildInputKey(JOB_ID), inputBytes, "input");
  mem.seed(sidecarKey, new Uint8Array([1, 2, 3, 4]), "side-1");
  const headers = {
    "x-vol-panel-job-id": JOB_ID,
    "x-vol-panel-input-manifest-key": personalVolAmPmPanelBuildInputKey(JOB_ID),
    "x-vol-panel-input-manifest-digest": inputDigest,
  };
  return { mem, headers, inputDigest, input };
}

async function put(
  fixed: Awaited<ReturnType<typeof fixture>>,
  key: string,
  document: unknown,
) {
  const bytes =
    typeof document === "string" || document instanceof Uint8Array
      ? typeof document === "string"
        ? new TextEncoder().encode(document)
        : document
      : new TextEncoder().encode(JSON.stringify(document));
  const digest = `sha256:${await sha256Hex(bytes)}`;
  const response = await personalVolAmPmPanelR2Outbound(
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
  return { response, digest, key, bytes };
}

describe("vol AM/PM panel writer R2 capability", () => {
  it("serves admitted sidecar evidence and rejects unlisted snapshot manifests", async () => {
    const fixed = await fixture();
    const allowed = await personalVolAmPmPanelR2Outbound(
      new Request(`http://research.r2/${sidecarKey}`, { headers: fixed.headers }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      sidecarKey,
    );
    expect(allowed.status).toBe(200);
    const snapshotManifest = fixed.input.selection.manifest.key;
    const deniedManifest = await personalVolAmPmPanelR2Outbound(
      new Request(`http://research.r2/${snapshotManifest}`, { headers: fixed.headers }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      snapshotManifest,
    );
    expect(deniedManifest.status).toBe(403);
    const denied = await personalVolAmPmPanelR2Outbound(
      new Request("http://research.r2/research/mass_eval/panels_cache/secret.json", {
        headers: fixed.headers,
      }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      "research/mass_eval/panels_cache/secret.json",
    );
    expect(denied.status).toBe(403);
  });

  it("rejects a sidecar whose ETag changed after admission", async () => {
    const fixed = await fixture();
    fixed.mem.seed(sidecarKey, new Uint8Array([1, 2, 3, 4]), "mutated");
    const response = await personalVolAmPmPanelR2Outbound(
      new Request(`http://research.r2/${sidecarKey}`, { headers: fixed.headers }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      sidecarKey,
    );
    expect(response.status).toBe(409);
  });

  it("streams a content-addressed panel without parsing it and verifies children by HEAD", async () => {
    const fixed = await fixture();
    const periods: Record<string, unknown> = {};
    for (const period of PERSONAL_VOL_AM_PM_EVALUATION_PERIODS) {
      const panel = {
        schema_version: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
        period_id: period.period_id,
        year: period.year,
        bars: { A: [{ date: "2023-09-01", MAdjC: 1, AAdjC: 1 }] },
      };
      const panelPut = await put(
        fixed,
        personalVolAmPmPanelObjectKey(
          `sha256:${await sha256Hex(new TextEncoder().encode(JSON.stringify(panel)))}`,
        ),
        panel,
      );
      expect([201, 200]).toContain(panelPut.response.status);
      periods[period.period_id] = {
        panel_key: personalVolAmPmPanelObjectKey(panelPut.digest),
        panel_sha256: panelPut.digest,
        panel_size: panelPut.bytes.byteLength,
        common_valid_sha256: digestDigit("c"),
      };
    }
    expect(fixed.mem.parsedBodies).toBe(0);

    const terminal = {
      schema_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_MANIFEST_SCHEMA,
      status: "COMPLETED",
      kind: PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND,
      job_id: JOB_ID,
      runner_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
      input_manifest_digest: fixed.inputDigest,
      producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
      cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
      go: false,
      membership: { codes: ["13010"], digest: digestDigit("a"), count: 1 },
      periods,
    };
    const created = await put(fixed, personalVolAmPmPanelBuildTerminalKey(JOB_ID), terminal);
    expect(created.response.status).toBe(201);
    expect(fixed.mem.writes.at(-1)).toBe(personalVolAmPmPanelBuildTerminalKey(JOB_ID));
    const replay = await put(fixed, personalVolAmPmPanelBuildTerminalKey(JOB_ID), terminal);
    expect(replay.response.status).toBe(200);
    const conflict = await put(fixed, personalVolAmPmPanelBuildTerminalKey(JOB_ID), {
      ...terminal,
      error: "different",
    });
    expect(conflict.response.status).toBe(409);
  });

  it("rejects a child write after a timeout terminal and allows a corrected rebuild without a stable alias", async () => {
    const fixed = await fixture();
    const timeout = {
      schema_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_MANIFEST_SCHEMA,
      status: "FAILED",
      kind: PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND,
      job_id: JOB_ID,
      runner_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
      input_manifest_digest: fixed.inputDigest,
      producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
      cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
      go: false,
      error: "timeout",
    };
    expect(
      (await put(fixed, personalVolAmPmPanelBuildTerminalKey(JOB_ID), timeout)).response.status,
    ).toBe(201);
    const late = {
      schema_version: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
      period_id: "y2021_full",
    };
    const lateBytes = new TextEncoder().encode(JSON.stringify(late));
    const lateDigest = `sha256:${await sha256Hex(lateBytes)}`;
    const afterTerminal = await put(
      fixed,
      personalVolAmPmPanelObjectKey(lateDigest),
      late,
    );
    expect(afterTerminal.response.status).toBe(409);

    const other = await fixture();
    other.input.job_id = "vol-panel-rebuild";
    const rebuilt = JSON.parse(JSON.stringify(other.input)) as PersonalVolAmPmPanelWriterInputManifest;
    rebuilt.job_id = "vol-panel-rebuild";
    const rebuiltBytes = new TextEncoder().encode(JSON.stringify(rebuilt));
    const rebuiltDigest = `sha256:${await sha256Hex(rebuiltBytes)}`;
    other.mem.seed(personalVolAmPmPanelBuildInputKey("vol-panel-rebuild"), rebuiltBytes, "input");
    const panel = { schema_version: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION, period_id: "y2021_full", note: "corrected" };
    const panelBytes = new TextEncoder().encode(JSON.stringify(panel));
    const panelDigest = `sha256:${await sha256Hex(panelBytes)}`;
    const headers = {
      "x-vol-panel-job-id": "vol-panel-rebuild",
      "x-vol-panel-input-manifest-key": personalVolAmPmPanelBuildInputKey("vol-panel-rebuild"),
      "x-vol-panel-input-manifest-digest": rebuiltDigest,
      "content-length": String(panelBytes.byteLength),
      "x-content-sha256": panelDigest,
    };
    const response = await personalVolAmPmPanelR2Outbound(
      new Request(`http://research.r2/${personalVolAmPmPanelObjectKey(panelDigest)}`, {
        method: "PUT",
        headers,
        body: panelBytes,
      }),
      { STRUCTURED_BUCKET: other.mem.asBucket() },
      personalVolAmPmPanelObjectKey(panelDigest),
    );
    expect(response.status).toBe(201);
    expect(personalVolAmPmPanelObjectKey(panelDigest)).not.toContain("/panels/y2021_full.json");
  });

  it("leaves a racing child as an unreferenced orphan instead of claiming atomic exclusion", async () => {
    const fixed = await fixture();
    const originalPut = fixed.mem.put.bind(fixed.mem);
    fixed.mem.put = async (key, value, options) => {
      const result = await originalPut(key, value, options);
      if (key.startsWith("research/personal/vol-ratio-am-pm-v1/objects/")) {
        const timeout = {
          schema_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_MANIFEST_SCHEMA,
          status: "FAILED",
          kind: PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND,
          job_id: JOB_ID,
          runner_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
          input_manifest_digest: fixed.inputDigest,
          producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
          cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
          go: false,
          error: "timeout",
        };
        const bytes = new TextEncoder().encode(JSON.stringify(timeout));
        fixed.mem.seed(
          personalVolAmPmPanelBuildTerminalKey(JOB_ID),
          bytes,
          "term-race",
          { sha256: `sha256:${await sha256Hex(bytes)}` },
        );
      }
      return result;
    };
    const late = {
      schema_version: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION,
      period_id: "y2021_full",
    };
    const lateBytes = new TextEncoder().encode(JSON.stringify(late));
    const lateDigest = `sha256:${await sha256Hex(lateBytes)}`;
    const lateKey = personalVolAmPmPanelObjectKey(lateDigest);
    const raced = await put(fixed, lateKey, late);
    expect(raced.response.status).toBe(409);
    expect(fixed.mem.values.has(lateKey)).toBe(true);
    expect(fixed.mem.values.has(personalVolAmPmPanelBuildTerminalKey(JOB_ID))).toBe(
      true,
    );
    const terminal = JSON.parse(
      new TextDecoder().decode(
        fixed.mem.values.get(personalVolAmPmPanelBuildTerminalKey(JOB_ID))!.bytes,
      ),
    ) as { periods?: Record<string, unknown> };
    expect(terminal.periods).toBeUndefined();
  });
});
