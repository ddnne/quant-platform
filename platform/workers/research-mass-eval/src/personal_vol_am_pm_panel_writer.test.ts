import { describe, expect, it, vi } from "vitest";

import { dispatchMassEvalFetch } from "./http_routes";
import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  personalJobContainerName,
} from "./personal_research_contract";
import { personalSnapshotManifestKey } from "./personal_snapshot_contract";
import { PERSONAL_VOL_PERIODS } from "./personal_vol_research";
import { PERSONAL_JOB_TTL_MS } from "./personal_job_state";
import {
  PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
  PERSONAL_VOL_AM_PM_PANEL_TIMEOUT_GRACE_MS,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
  PERSONAL_VOL_AM_PM_SELECTION_PERIOD,
  parsePersonalVolAmPmPanelBuildRequest,
  personalVolAmPmPanelBuildInputKey,
  personalVolAmPmPanelBuildTerminalKey,
  type PersonalVolAmPmPanelBuildRequest,
} from "./personal_vol_am_pm_panel_writer_contract";
import {
  buildPersonalVolAmPmPanelInputManifest,
  submitPersonalVolAmPmPanelBuild,
} from "./personal_vol_am_pm_panel_writer";
import {
  PERSONAL_OPTION_SIDECAR_COHORT_ID,
  PERSONAL_OPTION_SIDECAR_DATASET,
  PERSONAL_OPTION_SIDECAR_KIND,
  PERSONAL_OPTION_SIDECAR_MANIFEST_SCHEMA,
  PERSONAL_OPTION_SIDECAR_OBJECT_SCHEMA,
  PERSONAL_OPTION_SIDECAR_PERIODS,
  PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
  PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
  PERSONAL_OPTION_SIDECAR_SOURCE_VERSION,
  personalOptionSidecarObjectKey,
  personalOptionSidecarTerminalKey,
} from "./personal_option_sidecar_producer_contract";
import { sha256Hex } from "./sha256";
import type { Env } from "./types";

function runnerReadyResponse(): Response {
  const body = JSON.stringify({
    ok: true,
    service: PERSONAL_RESEARCH_RUNNER_VERSION,
  });
  return new Response(body, {
    status: 200,
    headers: {
      "content-length": String(new TextEncoder().encode(body).byteLength),
      "content-type": "application/json; charset=utf-8",
    },
  });
}

function admittedContainer() {
  const destroy = vi.fn(async () => undefined);
  const fetch = vi.fn(async (request: Request) =>
    new URL(request.url).pathname === "/ready"
      ? runnerReadyResponse()
      : new Response('{"accepted":true}', { status: 202 }),
  );
  return { destroy, fetch };
}

type Stored = {
  bytes: Uint8Array;
  etag: string;
  customMetadata: Record<string, string>;
};

class MemoryR2 {
  readonly values = new Map<string, Stored>();
  readonly writes: string[] = [];

  seed(
    key: string,
    value: unknown,
    etag = `etag-${key}`,
    customMetadata: Record<string, string> = {},
  ) {
    const bytes =
      typeof value === "string"
        ? new TextEncoder().encode(value)
        : value instanceof Uint8Array
          ? value
          : new TextEncoder().encode(JSON.stringify(value));
    this.values.set(key, { bytes, etag, customMetadata });
  }

  object(key: string, stored: Stored) {
    return {
      key,
      size: stored.bytes.byteLength,
      etag: stored.etag,
      customMetadata: stored.customMetadata,
      json: async () => JSON.parse(new TextDecoder().decode(stored.bytes)),
      arrayBuffer: async () => stored.bytes.slice().buffer,
    };
  }

  async get(key: string) {
    const stored = this.values.get(key);
    return stored ? this.object(key, stored) : null;
  }

  async head(key: string) {
    const stored = this.values.get(key);
    return stored ? this.object(key, stored) : null;
  }

  async put(
    key: string,
    value: ArrayBuffer | ArrayBufferView | string,
    options?: R2PutOptions,
  ) {
    if (
      options?.onlyIf &&
      "etagDoesNotMatch" in options.onlyIf &&
      options.onlyIf.etagDoesNotMatch === "*" &&
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
    this.values.set(key, {
      bytes,
      etag: `put-${this.writes.length}`,
      customMetadata: options?.customMetadata ?? {},
    });
    this.writes.push(key);
    return this.object(key, this.values.get(key)!);
  }

  asBucket(): R2Bucket {
    return this as unknown as R2Bucket;
  }
}

function digestDigit(digit: string): `sha256:${string}` {
  return `sha256:${digit.repeat(64)}`;
}

function optionSidecar(
  period: (typeof PERSONAL_OPTION_SIDECAR_PERIODS)[number],
  includeBars = true,
): Record<string, unknown> {
  const point = { [period.period_start]: 1 };
  const rolling = { rv_short_by_date: point, rv_long_by_date: point, rv_abs_by_date: point };
  const raw = digestDigit(period.period_id === "y2021_full" ? "6" : period.period_id === "y2023_full" ? "7" : "8");
  const calendar = digestDigit(period.period_id === "y2021_full" ? "9" : period.period_id === "y2023_full" ? "a" : "b");
  return {
    schema_version: PERSONAL_OPTION_SIDECAR_OBJECT_SCHEMA,
    period_id: period.period_id,
    year: period.year,
    period_start: period.period_start,
    period_end: period.period_end,
    opt225_regime: {
      source: {
        dataset: PERSONAL_OPTION_SIDECAR_DATASET,
        version: PERSONAL_OPTION_SIDECAR_SOURCE_VERSION,
        raw_input_digest: raw,
        calendar_digest: calendar,
      },
      basevol: rolling,
      atm_iv: rolling,
      skew: rolling,
      cm_term_ratio: { rv_abs_by_date: point },
    },
    ...(includeBars
      ? {
          bars: { A: [[period.period_start, 100]] },
          calendar: { dates: [period.period_start] },
        }
      : {}),
  };
}

async function seedSnapshot(
  mem: MemoryR2,
  jobId: string,
  periodStart: string,
  periodEnd: string,
  rawDigit: string,
  lookback: number,
) {
  const raw = digestDigit(rawDigit);
  const gzip = digestDigit(rawDigit === "1" ? "2" : rawDigit);
  const snapshotKey = `research/personal/snapshots/sha256=${rawDigit.repeat(64)}.sqlite.gz`;
  mem.seed(
    snapshotKey,
    new Uint8Array([1, 2, 3]),
    `snap-${jobId}`,
    {
      format: "personal-draft-history/v4",
      raw_sha256: raw,
      sha256: gzip,
    },
  );
  mem.seed(personalSnapshotManifestKey(jobId), {
    status: "COMPLETED",
    job_id: jobId,
    format: "personal-draft-history/v4",
    runner_version: PERSONAL_RESEARCH_RUNNER_VERSION,
    period_start: periodStart,
    period_end: periodEnd,
    lookback_sessions: lookback,
    raw_sha256: raw,
    gzip_sha256: gzip,
    snapshot_key: snapshotKey,
  });
}

const REQUEST: PersonalVolAmPmPanelBuildRequest = {
  job_id: "vol-panel-one",
  selection_snapshot_job_id: "snap-2019",
  sidecar_producer_job_id: "sidecar-one",
  period_snapshot_job_ids: {
    y2021_full: "snap-2021",
    y2023_full: "snap-2023",
    y2025_q4: "snap-2025",
  },
};

async function seedClosedInputs(
  mem: MemoryR2,
  mutate?: (period: (typeof PERSONAL_OPTION_SIDECAR_PERIODS)[number], sidecar: Record<string, unknown>) => Record<string, unknown>,
) {
  await seedSnapshot(
    mem,
    REQUEST.selection_snapshot_job_id,
    PERSONAL_VOL_AM_PM_SELECTION_PERIOD.period_start,
    PERSONAL_VOL_AM_PM_SELECTION_PERIOD.period_end,
    "1",
    0,
  );
  const digits = ["3", "4", "5"] as const;
  const sidecars: Record<string, unknown> = {};
  for (const [index, period] of PERSONAL_OPTION_SIDECAR_PERIODS.entries()) {
    await seedSnapshot(
      mem,
      REQUEST.period_snapshot_job_ids[period.period_id],
      period.period_start,
      period.period_end,
      digits[index]!,
      61,
    );
    const sidecar = mutate ? mutate(period, optionSidecar(period)) : optionSidecar(period);
    const sidecarBytes = new TextEncoder().encode(JSON.stringify(sidecar));
    const sidecarDigest = `sha256:${await sha256Hex(sidecarBytes)}`;
    const sidecarKey = personalOptionSidecarObjectKey(sidecarDigest);
    mem.seed(sidecarKey, sidecarBytes, `etag-${period.period_id}`, {
      sha256: sidecarDigest,
    });
    sidecars[period.period_id] = {
      period_id: period.period_id,
      year: period.year,
      period_start: period.period_start,
      period_end: period.period_end,
      key: sidecarKey,
      sha256: sidecarDigest,
      size: sidecarBytes.byteLength,
      raw_input_digest: (sidecar.opt225_regime as { source: { raw_input_digest: string } }).source.raw_input_digest,
      calendar_digest: (sidecar.opt225_regime as { source: { calendar_digest: string } }).source.calendar_digest,
    };
  }
  const terminal = {
    schema_version: PERSONAL_OPTION_SIDECAR_MANIFEST_SCHEMA,
    status: "COMPLETED",
    kind: PERSONAL_OPTION_SIDECAR_KIND,
    producer_id: PERSONAL_OPTION_SIDECAR_PRODUCER_ID,
    cohort_id: PERSONAL_OPTION_SIDECAR_COHORT_ID,
    job_id: REQUEST.sidecar_producer_job_id,
    runner_version: PERSONAL_OPTION_SIDECAR_RUNNER_VERSION,
    sidecars,
  };
  mem.seed(personalOptionSidecarTerminalKey(REQUEST.sidecar_producer_job_id), terminal);
}

const noMass = async () => {
  throw new Error("mass path must not run");
};

describe("closed personal vol AM/PM panel-build request", () => {
  it("accepts only the three immutable snapshot job ids", () => {
    expect(parsePersonalVolAmPmPanelBuildRequest(REQUEST)).toEqual({
      ok: true,
      value: REQUEST,
    });
    expect(
      parsePersonalVolAmPmPanelBuildRequest({ ...REQUEST, panel_key: "x" }),
    ).toMatchObject({ ok: false, error: expect.stringContaining("unknown") });
    expect(
      parsePersonalVolAmPmPanelBuildRequest({
        ...REQUEST,
        sidecar_key: "research/mass_eval/panels_cache/x.json",
      }),
    ).toMatchObject({ ok: false, error: expect.stringContaining("unknown") });
    expect(
      parsePersonalVolAmPmPanelBuildRequest({
        job_id: REQUEST.job_id,
        selection_snapshot_job_id: REQUEST.selection_snapshot_job_id,
        period_snapshot_job_ids: REQUEST.period_snapshot_job_ids,
      }),
    ).toMatchObject({ ok: false, error: "sidecar_producer_job_id is invalid" });
    expect(
      parsePersonalVolAmPmPanelBuildRequest({
        ...REQUEST,
        period_snapshot_job_ids: {
          ...REQUEST.period_snapshot_job_ids,
          y2021_full: "snap-2019",
        },
      }),
    ).toMatchObject({ ok: false });
    expect(
      parsePersonalVolAmPmPanelBuildRequest({
        ...REQUEST,
        sidecar_producer_terminal_digest: digestDigit("c"),
      }),
    ).toMatchObject({ ok: false, error: expect.stringContaining("unknown") });
  });

  it("locks v4 snapshots and sidecar child top-level identity from GET", async () => {
    const mem = new MemoryR2();
    await seedClosedInputs(mem);
    const got: string[] = [];
    const originalGet = mem.get.bind(mem);
    mem.get = async (key: string) => {
      got.push(key);
      return originalGet(key);
    };
    const input = await buildPersonalVolAmPmPanelInputManifest(mem.asBucket(), REQUEST);
    expect(input.runner_version).toBe("personal-cloud-runner/v13");
    expect(input.required_lookback_sessions).toBe(61);
    expect(input.selection.snapshot.raw_sha256).toBe(digestDigit("1"));
    expect(got.some((key) => key.includes("panels_cache"))).toBe(false);
    expect(got.some((key) => key.includes("/option-sidecar/job=sidecar-one/manifest.json"))).toBe(
      true,
    );
    expect(got.some((key) => key.includes("/option-sidecar/objects/"))).toBe(true);
    for (const period of PERSONAL_VOL_PERIODS) {
      expect(input.periods[period.period_id].lookback_sessions).toBeGreaterThanOrEqual(61);
      expect(input.option_sidecars[period.period_id].source_key).toMatch(
        /^research\/personal\/option-sidecar\/objects\/sha256:[0-9a-f]{64}\.json$/,
      );
      expect(input.option_sidecars[period.period_id].period_id).toBe(period.period_id);
      expect(input.option_sidecars[period.period_id].year).toBe(period.year);
      expect(input.option_sidecars[period.period_id].source.dataset).toBe(
        PERSONAL_OPTION_SIDECAR_DATASET,
      );
      expect(input.sidecar_producer.job_id).toBe(REQUEST.sidecar_producer_job_id);
    }
    const keys = PERSONAL_VOL_PERIODS.map(
      (period) => input.option_sidecars[period.period_id].source_key,
    );
    expect(new Set(keys).size).toBe(3);
  });

  it("rejects a sidecar child whose period identity does not match the lock", async () => {
    const mem = new MemoryR2();
    await seedClosedInputs(mem, (period, sidecar) =>
      period.period_id === "y2021_full" ? { ...sidecar, period_id: "y2023_full" } : sidecar,
    );
    await expect(
      buildPersonalVolAmPmPanelInputManifest(mem.asBucket(), REQUEST),
    ).rejects.toMatchObject({ code: "vol_am_pm_panel_sidecar_child_period_mismatch" });
  });

  it("rejects reusing the same sidecar child for all three periods", async () => {
    const mem = new MemoryR2();
    await seedClosedInputs(mem);
    const terminalKey = personalOptionSidecarTerminalKey(REQUEST.sidecar_producer_job_id);
    const terminal = JSON.parse(
      new TextDecoder().decode(mem.values.get(terminalKey)!.bytes),
    ) as { sidecars: Record<string, Record<string, unknown>> };
    const first = terminal.sidecars.y2021_full;
    terminal.sidecars.y2023_full = {
      ...terminal.sidecars.y2023_full,
      key: first.key,
      sha256: first.sha256,
      size: first.size,
    };
    terminal.sidecars.y2025_q4 = {
      ...terminal.sidecars.y2025_q4,
      key: first.key,
      sha256: first.sha256,
      size: first.size,
    };
    mem.seed(terminalKey, terminal);
    await expect(
      buildPersonalVolAmPmPanelInputManifest(mem.asBucket(), REQUEST),
    ).rejects.toMatchObject({ code: "vol_am_pm_panel_sidecar_child_reused" });
  });

  it("writes the input manifest before dispatching the existing v13 Container", async () => {
    const mem = new MemoryR2();
    await seedClosedInputs(mem);
    const container = admittedContainer();
    const env = {
      STRUCTURED_BUCKET: mem.asBucket(),
      PERSONAL_RESEARCH_CONTAINER: { getByName: vi.fn(() => container) },
    } as unknown as Env;
    const response = await submitPersonalVolAmPmPanelBuild(env, REQUEST);
    expect(response.status).toBe(202);
    expect(container.fetch).toHaveBeenCalledTimes(2);
    expect(new URL(container.fetch.mock.calls[0]![0].url).pathname).toBe("/ready");
    expect(env.PERSONAL_RESEARCH_CONTAINER.getByName).toHaveBeenCalledWith(
      await personalJobContainerName("vol-panel", REQUEST.job_id),
    );
    expect(mem.values.has(personalVolAmPmPanelBuildInputKey(REQUEST.job_id))).toBe(true);
    const forwarded = container.fetch.mock.calls[1]![0] as Request;
    expect(await forwarded.json()).toMatchObject({
      cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
      job_id: REQUEST.job_id,
      producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
      runner_version: PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
      manifest_key: personalVolAmPmPanelBuildTerminalKey(REQUEST.job_id),
    });
  });

  it("is idempotent for a matching terminal and conflicts on a different body", async () => {
    const mem = new MemoryR2();
    await seedClosedInputs(mem);
    const input = await buildPersonalVolAmPmPanelInputManifest(mem.asBucket(), REQUEST);
    const inputKey = personalVolAmPmPanelBuildInputKey(REQUEST.job_id);
    mem.seed(inputKey, input);
    const inputDigest = `sha256:${await sha256Hex(mem.values.get(inputKey)!.bytes)}`;
    mem.seed(personalVolAmPmPanelBuildTerminalKey(REQUEST.job_id), {
      status: "COMPLETED",
      job_id: REQUEST.job_id,
      producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
      cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
      input_manifest_digest: inputDigest,
    });
    const env = { STRUCTURED_BUCKET: mem.asBucket() } as Env;
    const again = await submitPersonalVolAmPmPanelBuild(env, REQUEST);
    expect(again.status).toBe(200);
    expect(await again.json()).toMatchObject({ ok: true, idempotent: true });
    mem.seed(personalVolAmPmPanelBuildTerminalKey(REQUEST.job_id), {
      status: "COMPLETED",
      job_id: REQUEST.job_id,
      producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
      cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
    });
    const missingDigest = await submitPersonalVolAmPmPanelBuild(env, REQUEST);
    expect(missingDigest.status).toBe(409);
    const conflict = await submitPersonalVolAmPmPanelBuild(env, {
      ...REQUEST,
      selection_snapshot_job_id: "snap-other",
    });
    expect(conflict.status).toBe(409);
  });

  it("reuses the locked input and redispatches the same snapshot job ids", async () => {
    const mem = new MemoryR2();
    await seedClosedInputs(mem);
    const first = admittedContainer();
    const env = {
      STRUCTURED_BUCKET: mem.asBucket(),
      PERSONAL_RESEARCH_CONTAINER: { getByName: vi.fn(() => first) },
    } as unknown as Env;
    expect((await submitPersonalVolAmPmPanelBuild(env, REQUEST)).status).toBe(202);
    const inputKey = personalVolAmPmPanelBuildInputKey(REQUEST.job_id);
    const locked = JSON.parse(
      new TextDecoder().decode(mem.values.get(inputKey)!.bytes),
    ) as { option_sidecars: Record<string, { etag: string }> };
    const originalEtag = locked.option_sidecars.y2021_full.etag;
    mem.seed(
      locked.option_sidecars.y2021_full.source_key,
      new Uint8Array([9, 9, 9]),
      "mutated-etag",
      { sha256: digestDigit("f") },
    );
    const second = admittedContainer();
    env.PERSONAL_RESEARCH_CONTAINER.getByName = vi.fn(() => second);
    expect((await submitPersonalVolAmPmPanelBuild(env, REQUEST)).status).toBe(202);
    expect(second.fetch).toHaveBeenCalledTimes(2);
    expect(mem.writes.filter((key) => key === inputKey)).toHaveLength(1);
    const reused = JSON.parse(
      new TextDecoder().decode(mem.values.get(inputKey)!.bytes),
    ) as { option_sidecars: Record<string, { etag: string }> };
    expect(reused.option_sidecars.y2021_full.etag).toBe(originalEtag);
    const state = JSON.parse(
      new TextDecoder().decode(
        mem.values.get(
          `research/personal/vol-ratio-am-pm-v1/panel-builds/job=${REQUEST.job_id}/state.json`,
        )!.bytes,
      ),
    ) as { submitted_at: string; expires_at: string };
    expect(Date.parse(state.expires_at) - Date.parse(state.submitted_at)).toBe(
      PERSONAL_JOB_TTL_MS + PERSONAL_VOL_AM_PM_PANEL_TIMEOUT_GRACE_MS,
    );
  });
});

describe("POST /v1/personal-vol-am-pm-panel-build", () => {
  it("authenticates before parsing or dispatch", async () => {
    const submit = vi.fn();
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-vol-am-pm-panel-build", {
        method: "POST",
        body: JSON.stringify(REQUEST),
      }),
      {
        MASS_EVAL_TOKEN: "secret",
        STRUCTURED_BUCKET: {} as R2Bucket,
        PERSONAL_RESEARCH_CONTAINER: {} as Env["PERSONAL_RESEARCH_CONTAINER"],
      } as Env,
      { runMassEval: noMass, runDailyPath: noMass, submitPersonalVolAmPmPanelBuild: submit },
    );
    expect(response.status).toBe(401);
    expect(submit).not.toHaveBeenCalled();
  });

  it("routes closed POST and GET requests only", async () => {
    const submit = vi.fn(async () => new Response("accepted", { status: 202 }));
    const status = vi.fn(async () => new Response("status"));
    const env = {
      MASS_EVAL_TOKEN: "secret",
      STRUCTURED_BUCKET: {} as R2Bucket,
      PERSONAL_RESEARCH_CONTAINER: {} as Env["PERSONAL_RESEARCH_CONTAINER"],
    } as Env;
    const headers = {
      "content-type": "application/json",
      "content-length": String(JSON.stringify(REQUEST).length),
      "x-mass-eval-token": "secret",
    };
    expect(
      (
        await dispatchMassEvalFetch(
          new Request("https://example.test/v1/personal-vol-am-pm-panel-build", {
            method: "POST",
            headers,
            body: JSON.stringify(REQUEST),
          }),
          env,
          {
            runMassEval: noMass,
            runDailyPath: noMass,
            submitPersonalVolAmPmPanelBuild: submit,
            personalVolAmPmPanelBuildStatus: status,
          },
        )
      ).status,
    ).toBe(202);
    expect(submit).toHaveBeenCalledWith(env, REQUEST);
    await dispatchMassEvalFetch(
      new Request(
        "https://example.test/v1/personal-vol-am-pm-panel-build/jobs/vol-panel-one",
        { headers },
      ),
      env,
      { runMassEval: noMass, runDailyPath: noMass, personalVolAmPmPanelBuildStatus: status },
    );
    expect(status).toHaveBeenCalledWith(env, "vol-panel-one");
  });
});
