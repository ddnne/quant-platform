import { describe, expect, it } from "vitest";

import { PERSONAL_RESEARCH_RUNNER_VERSION } from "./personal_research_contract";
import { PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION } from "./personal_vol_am_pm_panel";
import {
  PERSONAL_VOL_AM_PM_COMMON_VALID_SCHEMA,
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
  personalVolAmPmStablePanelKey,
  type PersonalVolAmPmPanelWriterInputManifest,
} from "./personal_vol_am_pm_panel_writer_contract";
import { personalVolAmPmPanelR2Outbound } from "./personal_vol_am_pm_panel_r2";
import { PERSONAL_VOL_SOURCE_IDENTITY, PERSONAL_VOL_UNIVERSE_PROVENANCE } from "./personal_vol_research";
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
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(stored.bytes);
          controller.close();
        },
      }),
      arrayBuffer: async () => stored.bytes.slice().buffer,
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

  async put(key: string, value: ArrayBuffer | ArrayBufferView | string, options?: R2PutOptions) {
    if (
      options?.onlyIf &&
      "etagDoesNotMatch" in options.onlyIf &&
      this.values.has(key)
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
      etag: `write-${this.writes.length}`,
      customMetadata: options?.customMetadata ?? {},
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
    content_sha256: digestDigit(digit),
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
    calendar_start: start,
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
    equity_universe: PERSONAL_VOL_UNIVERSE_PROVENANCE,
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
        dataset: PERSONAL_VOL_SOURCE_IDENTITY.dataset,
        version: PERSONAL_VOL_SOURCE_IDENTITY.version,
        use: "opt225_regime_sidecar_only",
        bars_copied: false,
        calendar_copied: false,
      },
      y2023_full: {
        period_id: "y2023_full",
        source_key: sidecarKey.replace("y2021_full", "y2023_full"),
        etag: "side-2",
        size: 4,
        sha256: digestDigit("9"),
        dataset: PERSONAL_VOL_SOURCE_IDENTITY.dataset,
        version: PERSONAL_VOL_SOURCE_IDENTITY.version,
        use: "opt225_regime_sidecar_only",
        bars_copied: false,
        calendar_copied: false,
      },
      y2025_q4: {
        period_id: "y2025_q4",
        source_key: sidecarKey.replace("y2021_full", "y2025_q4"),
        etag: "side-3",
        size: 4,
        sha256: digestDigit("9"),
        dataset: PERSONAL_VOL_SOURCE_IDENTITY.dataset,
        version: PERSONAL_VOL_SOURCE_IDENTITY.version,
        use: "opt225_regime_sidecar_only",
        bars_copied: false,
        calendar_copied: false,
      },
    },
    authority: {
      draft_only: true,
      screening_only: true,
      ready: false,
      mass: false,
      promotion: false,
      live_orders: false,
      go: false,
      single_stock_option_iv: "FORBIDDEN",
      cash_index_executable_fill: false,
      adjc_fallback: false,
      ffill: false,
      synthetic_calendar: false,
      caller_provenance: false,
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

function authority() {
  return {
    producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
    cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
    draft_only: true,
    screening_only: true,
    ready: false,
    mass: false,
    promotion: false,
    live_orders: false,
    go: false,
    not_a_pass: true,
  };
}

async function put(
  fixed: Awaited<ReturnType<typeof fixture>>,
  key: string,
  document: unknown,
) {
  const bytes = new TextEncoder().encode(
    typeof document === "string" ? document : JSON.stringify(document),
  );
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
  it("serves admitted sidecar evidence and rejects unlisted keys", async () => {
    const fixed = await fixture();
    const allowed = await personalVolAmPmPanelR2Outbound(
      new Request(`http://research.r2/${sidecarKey}`, { headers: fixed.headers }),
      { STRUCTURED_BUCKET: fixed.mem.asBucket() },
      sidecarKey,
    );
    expect(allowed.status).toBe(200);
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

  it("requires content-addressed children before the terminal and replays matching bodies", async () => {
    const fixed = await fixture();
    const membership = {
      schema_version: "personal-vol-ratio-am-pm-membership/v1",
      codes: ["13010"],
    };
    const membershipDigest = `sha256:${await sha256Hex(
      new TextEncoder().encode(JSON.stringify(membership)),
    )}`;
    const membershipKey = personalVolAmPmPanelObjectKey(membershipDigest);
    const membershipOk = await put(fixed, membershipKey, membership);
    expect(membershipOk.response.status).toBe(201);

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
      const panelKey = personalVolAmPmPanelObjectKey(panelPut.digest);
      expect(
        (await put(fixed, personalVolAmPmStablePanelKey(period.period_id), panel)).response.status,
      ).toBe(201);
      const mask = { schema_version: PERSONAL_VOL_AM_PM_COMMON_VALID_SCHEMA, rows: [] };
      const maskPut = await put(
        fixed,
        personalVolAmPmPanelObjectKey(
          `sha256:${await sha256Hex(new TextEncoder().encode(JSON.stringify(mask)))}`,
        ),
        mask,
      );
      expect([201, 200]).toContain(maskPut.response.status);
      const maskKey = personalVolAmPmPanelObjectKey(maskPut.digest);
      periods[period.period_id] = {
        panel_key: panelKey,
        panel_sha256: panelPut.digest,
        stable_key: personalVolAmPmStablePanelKey(period.period_id),
        common_valid_key: maskKey,
        common_valid_sha256: maskPut.digest,
      };
    }

    const terminal = {
      schema_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_MANIFEST_SCHEMA,
      status: "COMPLETED",
      kind: PERSONAL_VOL_AM_PM_PANEL_WRITER_KIND,
      job_id: JOB_ID,
      runner_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
      input_manifest_digest: fixed.inputDigest,
      membership: { digest: membershipDigest, key: membershipKey },
      periods,
      ...authority(),
    };
    const tooSoon = await put(
      fixed,
      personalVolAmPmPanelBuildTerminalKey(JOB_ID),
      { ...terminal, membership: { digest: digestDigit("c"), key: personalVolAmPmPanelObjectKey(digestDigit("c")) } },
    );
    expect(tooSoon.response.status).toBe(409);
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
});
