import { env } from "cloudflare:workers";
import { reset } from "cloudflare:test";
import { afterEach, describe, expect, it, vi } from "vitest";

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
} from "../src/personal_svi_2023_contract";
import { personalSviR2Outbound } from "../src/personal_svi_r2";
import { sha256Hex } from "../src/sha256";

const runtimeEnv = env as { STRUCTURED_BUCKET: R2Bucket };

async function seed(key: string, bytes: Uint8Array) {
  const stored = await runtimeEnv.STRUCTURED_BUCKET.put(key, bytes);
  if (!stored) throw new Error(`seed failed: ${key}`);
  return stored;
}

async function fixture() {
  const jobId = "svi-r2-closed";
  const inputKey = personalSviInputManifestKey(jobId);
  const optionKey =
    "structured/jsonl/derivatives_bars_daily_options_225/dt=2023-01-04/run.jsonl";
  const panelBytes = new Uint8Array([1, 2, 3]);
  const optionBytes = new Uint8Array([4, 5, 6]);
  const panelObj = await seed(PERSONAL_SVI_2023_PANEL_KEY, panelBytes);
  const optionObj = await seed(optionKey, optionBytes);
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
      etag: panelObj.etag,
      size: panelObj.size,
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
              etag: optionObj.etag,
              size: optionObj.size,
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
  await seed(inputKey, inputBytes);
  return {
    jobId,
    inputDigest,
    optionKey,
    optionBytes,
    headers: {
      "x-svi-job-id": jobId,
      "x-svi-input-manifest-key": inputKey,
      "x-svi-input-manifest-digest": inputDigest,
    },
  };
}

async function put(
  fixed: Awaited<ReturnType<typeof fixture>>,
  key: string,
  value: unknown,
  contentType = "json",
) {
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
    runtimeEnv,
    key,
  );
  return { response, digest, bytes };
}

describe("manifest-constrained SVI Container R2 capability", () => {
  afterEach(() => reset());

  it("streams only manifest-listed input keys and rejects arbitrary structured data", async () => {
    const fixed = await fixture();
    const allowed = await personalSviR2Outbound(
      new Request(`http://research.r2/${fixed.optionKey}`, { headers: fixed.headers }),
      runtimeEnv,
      fixed.optionKey,
    );
    expect(allowed.status).toBe(200);
    expect(new Uint8Array(await allowed.arrayBuffer())).toEqual(fixed.optionBytes);
    const arbitrary =
      "structured/jsonl/derivatives_bars_daily_options_225/dt=2023-01-05/secret.jsonl";
    const denied = await personalSviR2Outbound(
      new Request(`http://research.r2/${arbitrary}`, { headers: fixed.headers }),
      runtimeEnv,
      arbitrary,
    );
    expect(denied.status).toBe(403);
  });

  it("rejects an input whose ETag changed after Worker admission", async () => {
    const fixed = await fixture();
    await seed(fixed.optionKey, new Uint8Array([9, 9, 9]));
    const response = await personalSviR2Outbound(
      new Request(`http://research.r2/${fixed.optionKey}`, { headers: fixed.headers }),
      runtimeEnv,
      fixed.optionKey,
    );
    expect(response.status).toBe(409);
  });

  it("creates feature, report and verified terminal manifest exactly once", async () => {
    const fixed = await fixture();
    const featureKey = personalSviFeatureKey(fixed.jobId);
    const putSpy = vi.spyOn(runtimeEnv.STRUCTURED_BUCKET, "put");
    try {
      const feature = await put(fixed, featureKey, '{"date":"2023-01-04"}\n', "jsonl");
      expect(feature.response.status).toBe(201);
      expect(new Uint8Array(await (await runtimeEnv.STRUCTURED_BUCKET.get(featureKey))!.arrayBuffer())).toEqual(
        feature.bytes,
      );
      const reportKey = personalSviReportKey(fixed.jobId);
      const report = await put(fixed, reportKey, {
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
      expect(new Uint8Array(await (await runtimeEnv.STRUCTURED_BUCKET.get(reportKey))!.arrayBuffer())).toEqual(
        report.bytes,
      );
      const manifestKey = personalSviTerminalManifestKey(fixed.jobId);
      const terminal = await put(fixed, manifestKey, {
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
      expect(new Uint8Array(await (await runtimeEnv.STRUCTURED_BUCKET.get(manifestKey))!.arrayBuffer())).toEqual(
        terminal.bytes,
      );
      expect(putSpy.mock.calls.map((call) => call[2]?.onlyIf)).toEqual([
        { etagDoesNotMatch: "*" },
        { etagDoesNotMatch: "*" },
        { etagDoesNotMatch: "*" },
      ]);
      const replay = await put(fixed, featureKey, '{"date":"2023-01-04"}\n', "jsonl");
      expect(replay.response.status).toBe(200);
      expect(await replay.response.json()).toMatchObject({ created: false });
      const conflict = await put(fixed, featureKey, '{"date":"changed"}\n', "jsonl");
      expect(conflict.response.status).toBe(409);
      expect(new Uint8Array(await (await runtimeEnv.STRUCTURED_BUCKET.get(featureKey))!.arrayBuffer())).toEqual(
        feature.bytes,
      );
    } finally {
      putSpy.mockRestore();
    }
  });

  it("rejects late child output creation after an exact FAILED terminal", async () => {
    const fixed = await fixture();
    const terminalKey = personalSviTerminalManifestKey(fixed.jobId);
    const failed = await put(fixed, terminalKey, {
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
    });
    expect(failed.response.status).toBe(201);
    const featureKey = personalSviFeatureKey(fixed.jobId);
    const late = await put(fixed, featureKey, '{"date":"late"}\n', "jsonl");
    expect(late.response.status).toBe(409);
    expect(await late.response.json()).toEqual({ error: "SVI terminal already exists" });
    expect(await runtimeEnv.STRUCTURED_BUCKET.head(featureKey)).toBeNull();
  });
});
