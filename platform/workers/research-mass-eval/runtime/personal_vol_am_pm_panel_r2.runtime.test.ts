import { env } from "cloudflare:workers";
import { reset } from "cloudflare:test";
import { afterEach, describe, expect, it } from "vitest";

import { PERSONAL_RESEARCH_RUNNER_VERSION } from "../src/personal_research_contract";
import { PERSONAL_SNAPSHOT_FORMAT } from "../src/personal_snapshot_contract";
import { PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION } from "../src/personal_vol_am_pm_panel";
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
  type SnapshotInputLock,
} from "../src/personal_vol_am_pm_panel_writer_contract";
import { personalOptionSidecarObjectKey } from "../src/personal_option_sidecar_producer_contract";
import { personalVolAmPmPanelR2Outbound } from "../src/personal_vol_am_pm_panel_r2";
import { sha256Hex } from "../src/sha256";

const runtimeEnv = env as { STRUCTURED_BUCKET: R2Bucket };
const JOB_ID = "vol-panel-r2";

function digestDigit(digit: string): `sha256:${string}` {
  return `sha256:${digit.repeat(64)}`;
}

const sidecarKey = personalOptionSidecarObjectKey(digestDigit("9"));

async function seed(key: string, bytes: Uint8Array) {
  const stored = await runtimeEnv.STRUCTURED_BUCKET.put(key, bytes);
  if (!stored) throw new Error(`seed failed: ${key}`);
  return stored;
}

function snapshotLock(
  jobId: string,
  digit: string,
  periodId: string,
  start: string,
  end: string,
): SnapshotInputLock {
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
    format: PERSONAL_SNAPSHOT_FORMAT,
    runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
    manifest: { key: manifestKey, etag: `man-${digit}`, size: 8, sha256: digestDigit(digit) },
    snapshot: ref,
  };
}

async function fixture(jobId = JOB_ID) {
  const sidecarBytes = new Uint8Array([1, 2, 3, 4]);
  const sidecarObj = await seed(sidecarKey, sidecarBytes);
  const input: PersonalVolAmPmPanelWriterInputManifest = {
    schema_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_INPUT_SCHEMA,
    producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
    job_id: jobId,
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
    sidecar_producer: {
      job_id: "sidecar-one",
      terminal: {
        key: "research/personal/option-sidecar/job=sidecar-one/manifest.json",
        etag: "term-1",
        size: 8,
        sha256: digestDigit("8"),
      },
    },
    option_sidecars: {
      y2021_full: {
        period_id: "y2021_full",
        year: 2021,
        period_start: "2021-01-04",
        period_end: "2021-10-15",
        schema_version: "personal-n225-option-sidecar/v1",
        source_key: sidecarKey,
        etag: sidecarObj.etag,
        size: sidecarObj.size,
        sha256: digestDigit("9"),
        source: {
          dataset: "derivatives_bars_daily_options_225",
          version: "research-options-225-vol-series/v1.3",
          raw_input_digest: digestDigit("c"),
          calendar_digest: digestDigit("d"),
        },
      },
      y2023_full: {
        period_id: "y2023_full",
        year: 2023,
        period_start: "2023-01-04",
        period_end: "2023-10-13",
        schema_version: "personal-n225-option-sidecar/v1",
        source_key: personalOptionSidecarObjectKey(digestDigit("a")),
        etag: "side-2",
        size: 4,
        sha256: digestDigit("a"),
        source: {
          dataset: "derivatives_bars_daily_options_225",
          version: "research-options-225-vol-series/v1.3",
          raw_input_digest: digestDigit("c"),
          calendar_digest: digestDigit("d"),
        },
      },
      y2025_q4: {
        period_id: "y2025_q4",
        year: 2025,
        period_start: "2025-09-01",
        period_end: "2025-12-29",
        schema_version: "personal-n225-option-sidecar/v1",
        source_key: personalOptionSidecarObjectKey(digestDigit("b")),
        etag: "side-3",
        size: 4,
        sha256: digestDigit("b"),
        source: {
          dataset: "derivatives_bars_daily_options_225",
          version: "research-options-225-vol-series/v1.3",
          raw_input_digest: digestDigit("c"),
          calendar_digest: digestDigit("d"),
        },
      },
    },
  };
  const inputBytes = new TextEncoder().encode(JSON.stringify(input));
  const inputDigest = `sha256:${await sha256Hex(inputBytes)}`;
  await seed(personalVolAmPmPanelBuildInputKey(jobId), inputBytes);
  const headers = {
    "x-vol-panel-job-id": jobId,
    "x-vol-panel-input-manifest-key": personalVolAmPmPanelBuildInputKey(jobId),
    "x-vol-panel-input-manifest-digest": inputDigest,
  };
  return { headers, inputDigest, input };
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
    runtimeEnv,
    key,
  );
  return { response, digest, key, bytes };
}

describe("vol AM/PM panel writer R2 capability", () => {
  afterEach(() => reset());

  it("serves admitted sidecar evidence and rejects unlisted snapshot manifests", async () => {
    const fixed = await fixture();
    const allowed = await personalVolAmPmPanelR2Outbound(
      new Request(`http://research.r2/${sidecarKey}`, { headers: fixed.headers }),
      runtimeEnv,
      sidecarKey,
    );
    expect(allowed.status).toBe(200);
    expect(new Uint8Array(await allowed.arrayBuffer())).toEqual(new Uint8Array([1, 2, 3, 4]));
    const snapshotManifest = fixed.input.selection.manifest.key;
    const deniedManifest = await personalVolAmPmPanelR2Outbound(
      new Request(`http://research.r2/${snapshotManifest}`, { headers: fixed.headers }),
      runtimeEnv,
      snapshotManifest,
    );
    expect(deniedManifest.status).toBe(403);
    const denied = await personalVolAmPmPanelR2Outbound(
      new Request("http://research.r2/research/mass_eval/panels_cache/secret.json", {
        headers: fixed.headers,
      }),
      runtimeEnv,
      "research/mass_eval/panels_cache/secret.json",
    );
    expect(denied.status).toBe(403);
  });

  it("rejects a sidecar whose ETag changed after admission", async () => {
    const fixed = await fixture();
    await seed(sidecarKey, new Uint8Array([9, 9, 9, 9]));
    const response = await personalVolAmPmPanelR2Outbound(
      new Request(`http://research.r2/${sidecarKey}`, { headers: fixed.headers }),
      runtimeEnv,
      sidecarKey,
    );
    expect(response.status).toBe(409);
  });

  it("stores exact panel child bytes then a COMPLETE terminal with matching manifest bytes", async () => {
    const fixed = await fixture();
    const periods: Record<string, unknown> = {};
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(
        personalVolAmPmPanelBuildTerminalKey(JOB_ID),
      ),
    ).toBeNull();
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
      const stored = await runtimeEnv.STRUCTURED_BUCKET.get(panelPut.key);
      expect(stored).not.toBeNull();
      expect(stored!.size).toBe(panelPut.bytes.byteLength);
      expect(new Uint8Array(await stored!.arrayBuffer())).toEqual(panelPut.bytes);
      periods[period.period_id] = {
        panel_key: personalVolAmPmPanelObjectKey(panelPut.digest),
        panel_sha256: panelPut.digest,
        panel_size: panelPut.bytes.byteLength,
        common_valid_sha256: digestDigit("c"),
      };
    }

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
    const storedTerminal = await runtimeEnv.STRUCTURED_BUCKET.get(
      personalVolAmPmPanelBuildTerminalKey(JOB_ID),
    );
    expect(storedTerminal).not.toBeNull();
    expect(new Uint8Array(await storedTerminal!.arrayBuffer())).toEqual(created.bytes);
    const replay = await put(fixed, personalVolAmPmPanelBuildTerminalKey(JOB_ID), terminal);
    expect(replay.response.status).toBe(200);
    const conflict = await put(fixed, personalVolAmPmPanelBuildTerminalKey(JOB_ID), {
      ...terminal,
      error: "different",
    });
    expect(conflict.response.status).toBe(409);
    expect(new Uint8Array(await (await runtimeEnv.STRUCTURED_BUCKET.get(
      personalVolAmPmPanelBuildTerminalKey(JOB_ID),
    ))!.arrayBuffer())).toEqual(created.bytes);
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
    expect(
      await runtimeEnv.STRUCTURED_BUCKET.head(personalVolAmPmPanelObjectKey(lateDigest)),
    ).toBeNull();

    const rebuiltJob = "vol-panel-rebuild";
    const rebuilt = await fixture(rebuiltJob);
    const panel = { schema_version: PERSONAL_VOL_AM_PM_PANEL_SCHEMA_VERSION, period_id: "y2021_full", note: "corrected" };
    const panelBytes = new TextEncoder().encode(JSON.stringify(panel));
    const panelDigest = `sha256:${await sha256Hex(panelBytes)}`;
    const panelKey = personalVolAmPmPanelObjectKey(panelDigest);
    const response = await personalVolAmPmPanelR2Outbound(
      new Request(`http://research.r2/${panelKey}`, {
        method: "PUT",
        headers: {
          ...rebuilt.headers,
          "content-length": String(panelBytes.byteLength),
          "x-content-sha256": panelDigest,
        },
        body: panelBytes,
      }),
      runtimeEnv,
      panelKey,
    );
    expect(response.status).toBe(201);
    const stored = await runtimeEnv.STRUCTURED_BUCKET.get(panelKey);
    expect(stored).not.toBeNull();
    expect(new Uint8Array(await stored!.arrayBuffer())).toEqual(panelBytes);
  });
});
