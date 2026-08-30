import { describe, expect, it, vi } from "vitest";

import { dispatchMassEvalFetch } from "./http_routes";
import {
  PERSONAL_RESEARCH_RUNNER_VERSION,
  personalJobContainerName,
} from "./personal_research_contract";
import { personalSnapshotManifestKey } from "./personal_snapshot_contract";
import {
  PERSONAL_VOL_PERIODS,
  PERSONAL_VOL_SOURCE_IDENTITY,
} from "./personal_vol_research";
import {
  PERSONAL_VOL_AM_PM_EVALUATION_PERIODS,
  PERSONAL_VOL_AM_PM_OPTION_REBUILD_ERROR,
  PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
  PERSONAL_VOL_AM_PM_PANEL_WRITER_RUNNER_VERSION,
  PERSONAL_VOL_AM_PM_SELECTION_PERIOD,
  parsePersonalVolAmPmPanelBuildRequest,
  personalVolAmPmLegacyOptionPanelKey,
  personalVolAmPmPanelBuildInputKey,
  personalVolAmPmPanelBuildTerminalKey,
  type PersonalVolAmPmPanelBuildRequest,
} from "./personal_vol_am_pm_panel_writer_contract";
import {
  buildPersonalVolAmPmPanelInputManifest,
  submitPersonalVolAmPmPanelBuild,
} from "./personal_vol_am_pm_panel_writer";
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
    return this.get(key);
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

function optionSidecar(includeBars = true): Record<string, unknown> {
  const point = { "2021-01-04": 1 };
  const rolling = { rv_short_by_date: point, rv_long_by_date: point, rv_abs_by_date: point };
  return {
    opt225_regime: {
      source: PERSONAL_VOL_SOURCE_IDENTITY,
      basevol: rolling,
      atm_iv: rolling,
      skew: rolling,
      cm_term_ratio: { rv_abs_by_date: point },
    },
    ...(includeBars
      ? {
          bars: { A: [["2021-01-04", 100]] },
          calendar: { dates: ["2021-01-04"] },
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
    calendar_start: periodStart,
  });
}

const REQUEST: PersonalVolAmPmPanelBuildRequest = {
  job_id: "vol-panel-one",
  selection_snapshot_job_id: "snap-2019",
  period_snapshot_job_ids: {
    y2021_full: "snap-2021",
    y2023_full: "snap-2023",
    y2025_q4: "snap-2025",
  },
};

async function seedClosedInputs(mem: MemoryR2, sidecar: Record<string, unknown> = optionSidecar()) {
  await seedSnapshot(
    mem,
    REQUEST.selection_snapshot_job_id,
    PERSONAL_VOL_AM_PM_SELECTION_PERIOD.period_start,
    PERSONAL_VOL_AM_PM_SELECTION_PERIOD.period_end,
    "1",
    0,
  );
  const digits = ["3", "4", "5"] as const;
  for (const [index, period] of PERSONAL_VOL_AM_PM_EVALUATION_PERIODS.entries()) {
    await seedSnapshot(
      mem,
      REQUEST.period_snapshot_job_ids[period.period_id],
      period.period_start!,
      period.period_end!,
      digits[index]!,
      61,
    );
    mem.seed(personalVolAmPmLegacyOptionPanelKey(period.period_id), sidecar);
  }
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
        period_snapshot_job_ids: {
          ...REQUEST.period_snapshot_job_ids,
          y2021_full: "snap-2019",
        },
      }),
    ).toMatchObject({ ok: false });
  });

  it("locks v4 snapshots, typed M/A authority, and N225 sidecar-only evidence", async () => {
    const mem = new MemoryR2();
    await seedClosedInputs(mem);
    const input = await buildPersonalVolAmPmPanelInputManifest(mem.asBucket(), REQUEST);
    expect(input.runner_version).toBe("personal-cloud-runner/v13");
    expect(input.required_lookback_sessions).toBe(61);
    expect(input.authority.single_stock_option_iv).toBe("FORBIDDEN");
    expect(input.authority.adjc_fallback).toBe(false);
    expect(input.authority.synthetic_calendar).toBe(false);
    expect(input.selection.snapshot.raw_sha256).toBe(digestDigit("1"));
    for (const period of PERSONAL_VOL_PERIODS) {
      expect(input.periods[period.period_id].lookback_sessions).toBeGreaterThanOrEqual(61);
      expect(input.option_sidecars[period.period_id]).toMatchObject({
        dataset: PERSONAL_VOL_SOURCE_IDENTITY.dataset,
        use: "opt225_regime_sidecar_only",
        bars_copied: false,
        calendar_copied: false,
      });
    }
  });

  it("fails closed when the sidecar is missing N225 option evidence", async () => {
    const mem = new MemoryR2();
    await seedClosedInputs(mem, { bars: { A: [["2021-01-04", 1]] } });
    await expect(
      buildPersonalVolAmPmPanelInputManifest(mem.asBucket(), REQUEST),
    ).rejects.toMatchObject({ code: PERSONAL_VOL_AM_PM_OPTION_REBUILD_ERROR });
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
    mem.seed(personalVolAmPmPanelBuildInputKey(REQUEST.job_id), input);
    mem.seed(personalVolAmPmPanelBuildTerminalKey(REQUEST.job_id), {
      status: "COMPLETED",
      job_id: REQUEST.job_id,
      producer_id: PERSONAL_VOL_AM_PM_PANEL_WRITER_PRODUCER_ID,
      cohort_id: PERSONAL_VOL_AM_PM_PANEL_BUILD_COHORT_ID,
    });
    const env = { STRUCTURED_BUCKET: mem.asBucket() } as Env;
    const again = await submitPersonalVolAmPmPanelBuild(env, REQUEST);
    expect(again.status).toBe(200);
    expect(await again.json()).toMatchObject({ ok: true, idempotent: true });
    const conflict = await submitPersonalVolAmPmPanelBuild(env, {
      ...REQUEST,
      selection_snapshot_job_id: "snap-other",
    });
    expect(conflict.status).toBe(409);
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
