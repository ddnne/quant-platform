import { describe, expect, it, vi } from "vitest";

import { dispatchMassEvalFetch } from "./http_routes";
import {
  buildPersonalIndexVolOverlay2023InputManifest,
  submitPersonalIndexVolOverlay2023,
} from "./personal_index_vol_overlay_2023";
import {
  PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
  PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY,
  parsePersonalIndexVolOverlay2023Request,
  personalIndexVolOverlay2023InputManifestKey,
} from "./personal_index_vol_overlay_2023_contract";
import {
  PERSONAL_RESEARCH_CONTAINER_NAME,
  PERSONAL_RESEARCH_RUNNER_VERSION,
  personalResearchCohortDigest,
  personalResearchManifestKey,
  personalResearchResultKey,
} from "./personal_research_contract";
import {
  PERSONAL_SVI_2023_COHORT_ID,
  PERSONAL_SVI_2023_PANEL_KEY,
  PERSONAL_SVI_2023_RUNNER_VERSION,
  PERSONAL_SVI_2023_STRATEGY_ID,
  personalSviFeatureKey,
  personalSviInputManifestKey,
  personalSviReportKey,
  personalSviTerminalManifestKey,
} from "./personal_svi_2023_contract";
import { sha256Hex } from "./sha256";
import type { Env } from "./types";

type Stored = {
  bytes: Uint8Array;
  etag: string;
  customMetadata: Record<string, string>;
};

class MemoryR2 {
  readonly values = new Map<string, Stored>();

  seed(key: string, value: unknown, metadata: Record<string, string> = {}) {
    const bytes = value instanceof Uint8Array
      ? value
      : new TextEncoder().encode(JSON.stringify(value));
    this.values.set(key, { bytes, etag: `etag-${this.values.size}`, customMetadata: metadata });
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
      json: async () => JSON.parse(new TextDecoder().decode(stored.bytes)),
      writeHttpMetadata() {},
    } as R2ObjectBody;
  }

  async get(key: string) {
    const stored = this.values.get(key);
    return stored ? this.object(key, stored) : null;
  }

  async head(key: string) {
    const stored = this.values.get(key);
    return stored ? this.object(key, stored) : null;
  }

  async put(key: string, value: ArrayBuffer | ArrayBufferView | string, options?: R2PutOptions) {
    if (options?.onlyIf && "etagDoesNotMatch" in options.onlyIf && this.values.has(key)) {
      return null;
    }
    const bytes = typeof value === "string"
      ? new TextEncoder().encode(value)
      : ArrayBuffer.isView(value)
        ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength).slice()
        : new Uint8Array(value).slice();
    const stored = { bytes, etag: `put-${this.values.size}`, customMetadata: options?.customMetadata ?? {} };
    this.values.set(key, stored);
    return this.object(key, stored);
  }

  asBucket(): R2Bucket {
    return this as unknown as R2Bucket;
  }
}

async function sources(
  baseVersion: string | null = PERSONAL_RESEARCH_RUNNER_VERSION,
) {
  const mem = new MemoryR2();
  const baseJobId = "base-continuous-2023";
  const sviJobId = "svi-existing-2023";
  const resultKey = personalResearchResultKey(baseJobId);
  const resultDigest = `sha256:${"1".repeat(64)}`;
  const snapshotDigest = `sha256:${"2".repeat(64)}`;
  const snapshotKey = `research/personal/snapshots/sha256=${"2".repeat(64)}.sqlite`;
  mem.seed(resultKey, new Uint8Array([1]), { sha256: resultDigest });
  mem.seed(snapshotKey, new Uint8Array([2]));
  const baseManifest: Record<string, unknown> = {
    status: "COMPLETED",
    job_id: baseJobId,
    cohort_id: "sector-relative-ls-v1",
    cohort_digest: personalResearchCohortDigest("sector-relative-ls-v1"),
    universe_id: "topix_all",
    result_key: resultKey,
    result_sha256: resultDigest,
    snapshot: { key: snapshotKey, sha256: snapshotDigest },
    base_sleeve_artifact: {
      archive_member: `base-sleeve/${"3".repeat(64)}.json`,
      sha256: `sha256:${"3".repeat(64)}`,
      schema_version: "personal-base-sleeve-reference/v1",
      artifact_schema_version: "personal-base-sleeve-source/v1",
      strategy_id: "personal_sector_balanced_four_factor_v1_ls",
      cohort_id: "sector-relative-ls-v1",
      universe_id: "topix_all",
      role: "INDEX_VOL_OVERLAY_BASE_SOURCE",
      ranking_role: "NON_CANDIDATE_NOT_RANKED",
      candidate_count_contribution: 0,
    },
  };
  if (baseVersion !== null) baseManifest.version = baseVersion;
  mem.seed(personalResearchManifestKey(baseJobId), baseManifest);

  const optionKey = "structured/jsonl/derivatives_bars_daily_options_225/dt=2023-01-04/source.jsonl";
  const sviInput = {
    schema_version: "personal-svi-2023-input/v2",
    job_id: sviJobId,
    cohort_id: PERSONAL_SVI_2023_COHORT_ID,
    runner_version: PERSONAL_SVI_2023_RUNNER_VERSION,
    panel: { key: PERSONAL_SVI_2023_PANEL_KEY, etag: "panel-etag", size: 10, sha256: `sha256:${"4".repeat(64)}` },
    options: {
      days: [{ date: "2023-01-04", objects: [{ key: optionKey, etag: "option-etag", size: 11, sha256: `sha256:${"5".repeat(64)}` }] }],
      object_count: 1,
      total_bytes: 11,
    },
    authority: { draft_only: true, screening_only: true, ready: false, mass: false, promotion: false, live_orders: false, go: false },
  };
  const inputKey = personalSviInputManifestKey(sviJobId);
  const inputBytes = new TextEncoder().encode(JSON.stringify(sviInput));
  const inputDigest = `sha256:${await sha256Hex(inputBytes)}`;
  mem.seed(inputKey, inputBytes, { sha256: inputDigest });
  const featureKey = personalSviFeatureKey(sviJobId);
  const reportKey = personalSviReportKey(sviJobId);
  const featureDigest = `sha256:${"6".repeat(64)}`;
  const reportDigest = `sha256:${"7".repeat(64)}`;
  mem.seed(featureKey, new Uint8Array([6]), { sha256: featureDigest });
  mem.seed(reportKey, new Uint8Array([7]), { sha256: reportDigest });
  mem.seed(personalSviTerminalManifestKey(sviJobId), {
    status: "COMPLETED",
    job_id: sviJobId,
    cohort_id: PERSONAL_SVI_2023_COHORT_ID,
    strategy_id: PERSONAL_SVI_2023_STRATEGY_ID,
    runner_version: PERSONAL_SVI_2023_RUNNER_VERSION,
    input_manifest_key: inputKey,
    input_manifest_digest: inputDigest,
    feature_key: featureKey,
    feature_sha256: featureDigest,
    report_key: reportKey,
    report_sha256: reportDigest,
    request_digest: `sha256:${"8".repeat(64)}`,
    draft_only: true,
    screening_only: true,
    ready: false,
    mass: false,
    promotion: false,
    live_orders: false,
    go: false,
  });
  return { mem, baseJobId, sviJobId, optionKey };
}

describe("fixed personal index-vol overlay admission", () => {
  it("accepts only the four external identity fields", () => {
    const request = {
      job_id: "overlay-one",
      cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
      base_job_id: "base-one",
      svi_job_id: "svi-one",
    };
    expect(parsePersonalIndexVolOverlay2023Request(request)).toMatchObject({ ok: true, value: request });
    expect(parsePersonalIndexVolOverlay2023Request({ ...request, threshold: 1 })).toMatchObject({ ok: false });
  });

  it("copies the exact nested SVI object inventory without listing prefixes", async () => {
    const fixed = await sources();
    const manifest = await buildPersonalIndexVolOverlay2023InputManifest(
      fixed.mem.asBucket(),
      {
        job_id: "overlay-admitted",
        cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
        base_job_id: fixed.baseJobId,
        svi_job_id: fixed.sviJobId,
      },
    );
    expect(manifest.svi.input_manifest.key).toBe(personalSviInputManifestKey(fixed.sviJobId));
    expect(manifest.svi.options.days[0]?.objects[0]?.key).toBe(fixed.optionKey);
    expect(manifest.fixed_window.signal_start_policy).toBe(PERSONAL_INDEX_VOL_OVERLAY_2023_SIGNAL_START_POLICY);
    expect(manifest.authority).toMatchObject({ draft_only: true, ready: false, mass: false, live_orders: false, single_stock_option_iv: "FORBIDDEN" });
  });

  it.each([
    ["legacy v9", "personal-cloud-runner/v9"],
    ["current v10", "personal-cloud-runner/v10"],
  ])("accepts the explicitly compatible %s base runner manifest", async (_label, baseVersion) => {
    const fixed = await sources(baseVersion);
    await expect(
      buildPersonalIndexVolOverlay2023InputManifest(
        fixed.mem.asBucket(),
        {
          job_id: `overlay-base-version-${baseVersion.slice(-2)}`,
          cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
          base_job_id: fixed.baseJobId,
          svi_job_id: fixed.sviJobId,
        },
      ),
    ).resolves.toMatchObject({ base: { job_id: fixed.baseJobId } });
  });

  it.each([
    ["missing", null],
    ["stale v8", "personal-cloud-runner/v8"],
    ["unknown future v11", "personal-cloud-runner/v11"],
  ])("rejects a %s base runner manifest", async (_label, baseVersion) => {
    const fixed = await sources(baseVersion);
    await expect(
      buildPersonalIndexVolOverlay2023InputManifest(
        fixed.mem.asBucket(),
        {
          job_id: "overlay-base-version-denied",
          cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
          base_job_id: fixed.baseJobId,
          svi_job_id: fixed.sviJobId,
        },
      ),
    ).rejects.toThrow("overlay_base_job_not_eligible");
  });

  it("writes the immutable input before dispatching the existing verified container", async () => {
    const fixed = await sources();
    const ready = JSON.stringify({ ok: true, service: PERSONAL_RESEARCH_RUNNER_VERSION });
    const container = {
      destroy: vi.fn(),
      fetch: vi.fn(async (request: Request) =>
        new URL(request.url).pathname === "/ready"
          ? new Response(ready, { headers: { "content-length": String(ready.length) } })
          : new Response("accepted", { status: 202 }),
      ),
    };
    const env = {
      STRUCTURED_BUCKET: fixed.mem.asBucket(),
      PERSONAL_RESEARCH_CONTAINER: { getByName: vi.fn(() => container) },
    } as unknown as Env;
    const response = await submitPersonalIndexVolOverlay2023(env, {
      job_id: "overlay-dispatch",
      cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID,
      base_job_id: fixed.baseJobId,
      svi_job_id: fixed.sviJobId,
    });
    expect(response.status).toBe(202);
    expect(env.PERSONAL_RESEARCH_CONTAINER!.getByName).toHaveBeenCalledWith(PERSONAL_RESEARCH_CONTAINER_NAME);
    expect(fixed.mem.values.has(personalIndexVolOverlay2023InputManifestKey("overlay-dispatch"))).toBe(true);
    const forwarded = container.fetch.mock.calls[1]?.[0] as Request;
    expect(new URL(forwarded.url).pathname).toBe("/v1/run-index-vol-overlay-2023");
    expect(await forwarded.json()).toMatchObject({ job_id: "overlay-dispatch", base_job_id: fixed.baseJobId, svi_job_id: fixed.sviJobId });
  });
});

const noMass = async () => { throw new Error("mass path must not run"); };

describe("personal index-vol overlay routes", () => {
  it("authenticates before parsing and dispatch", async () => {
    const submit = vi.fn();
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-index-vol-overlay-2023", { method: "POST", body: "{}" }),
      { MASS_EVAL_TOKEN: "secret", STRUCTURED_BUCKET: {} as R2Bucket, PERSONAL_RESEARCH_CONTAINER: {} as Env["PERSONAL_RESEARCH_CONTAINER"] } as Env,
      { runMassEval: noMass, runDailyPath: noMass, submitPersonalIndexVolOverlay2023: submit },
    );
    expect(response.status).toBe(401);
    expect(submit).not.toHaveBeenCalled();
  });

  it("routes closed POST and GET requests only", async () => {
    const submit = vi.fn(async () => new Response("accepted", { status: 202 }));
    const status = vi.fn(async () => new Response("status"));
    const env = { MASS_EVAL_TOKEN: "secret", STRUCTURED_BUCKET: {} as R2Bucket, PERSONAL_RESEARCH_CONTAINER: {} as Env["PERSONAL_RESEARCH_CONTAINER"] } as Env;
    const headers = { "content-type": "application/json", "x-mass-eval-token": "secret" };
    const request = { job_id: "overlay-route", cohort_id: PERSONAL_INDEX_VOL_OVERLAY_2023_COHORT_ID, base_job_id: "base-route", svi_job_id: "svi-route" };
    expect((await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-index-vol-overlay-2023", { method: "POST", headers, body: JSON.stringify(request) }),
      env,
      { runMassEval: noMass, runDailyPath: noMass, submitPersonalIndexVolOverlay2023: submit, personalIndexVolOverlay2023Status: status },
    )).status).toBe(202);
    expect(submit).toHaveBeenCalledWith(env, request);
    await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-index-vol-overlay-2023/jobs/overlay-route", { headers }),
      env,
      { runMassEval: noMass, runDailyPath: noMass, personalIndexVolOverlay2023Status: status },
    );
    expect(status).toHaveBeenCalledWith(env, "overlay-route");
  });
});
