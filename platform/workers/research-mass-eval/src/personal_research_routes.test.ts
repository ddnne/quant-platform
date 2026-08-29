import { describe, expect, it, vi } from "vitest";

import { dispatchMassEvalFetch } from "./http_routes";
import type { Env } from "./types";

const SHA = "a".repeat(64);
const BODY = {
  job_id: "exact-four-route",
  snapshot_key: `research/personal/snapshots/sha256=${SHA}.sqlite`,
  snapshot_sha256: SHA,
  period_start: "2022-04-19",
  period_end: "2026-08-27",
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
