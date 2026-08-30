import { describe, expect, it, vi } from "vitest";

import { dispatchMassEvalFetch } from "./http_routes";
import type { Env } from "./types";

const SHA = "a".repeat(64);
const BODY = {
  cohort_id: "diverse-core-v1",
  job_id: "exact-four-route",
  snapshot_key: `research/personal/snapshots/sha256=${SHA}.sqlite`,
  snapshot_sha256: SHA,
  period_start: "2022-04-19",
  period_end: "2026-08-27",
  universe_id: "topix_all",
};

function env(): Env {
  return {
    MASS_EVAL_TOKEN: "secret",
    STRUCTURED_BUCKET: {} as R2Bucket,
    PERSONAL_RESEARCH_CONTAINER: {} as Env["PERSONAL_RESEARCH_CONTAINER"],
  } as Env;
}

const massHandlers = {
  runMassEval: vi.fn(),
  runDailyPath: vi.fn(),
};

describe("personal research HTTP route", () => {
  it("is token gated before parsing or Container dispatch", async () => {
    const submit = vi.fn();
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-research", {
        method: "POST",
        body: JSON.stringify(BODY),
      }),
      env(),
      { ...massHandlers, submitPersonalResearch: submit },
    );
    expect(response.status).toBe(401);
    expect(submit).not.toHaveBeenCalled();
  });

  it("dispatches only the validated closed request", async () => {
    const submit = vi.fn(async () => new Response("accepted", { status: 202 }));
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-research", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-mass-eval-token": "secret",
        },
        body: JSON.stringify(BODY),
      }),
      env(),
      { ...massHandlers, submitPersonalResearch: submit },
    );
    expect(response.status).toBe(202);
    expect(submit).toHaveBeenCalledWith(expect.anything(), BODY);
  });
});

describe("personal snapshot and batch HTTP routes", () => {
  it("token-gates snapshot build before dispatch", async () => {
    const submit = vi.fn();
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-snapshot-build", {
        method: "POST",
        body: JSON.stringify({
          job_id: "snap-1",
          period_start: "2023-01-01",
          period_end: "2024-12-31",
        }),
      }),
      env(),
      { ...massHandlers, submitPersonalSnapshotBuild: submit },
    );
    expect(response.status).toBe(401);
    expect(submit).not.toHaveBeenCalled();
  });

  it("rejects nine batch jobs before dispatch", async () => {
    const submit = vi.fn();
    const jobs = Array.from({ length: 9 }, (_, index) => ({
      ...BODY,
      job_id: `job-${index}`,
    }));
    const body = JSON.stringify({ jobs });
    const response = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/personal-research-batch", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": String(body.length),
          "x-mass-eval-token": "secret",
        },
        body,
      }),
      env(),
      { ...massHandlers, submitPersonalResearchJobs: submit },
    );
    expect(response.status).toBe(400);
    expect(submit).not.toHaveBeenCalled();
  });
});
