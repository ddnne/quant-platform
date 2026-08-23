import { describe, expect, it } from "vitest";
import { dispatchMassEvalFetch } from "./http_routes";
import type { Env } from "./types";

const noopHandlers = {
  runMassEval: async () => {
    throw new Error("mass-eval must not run");
  },
  runDailyPath: async () => {
    throw new Error("daily-path must not run");
  },
};

function denyByDefaultEnv(bucket: R2Bucket): Env {
  return {
    STRUCTURED_BUCKET: bucket,
    MASS_EVAL_TOKEN: "secret",
    MASS_RESEARCH: "NO-GO",
    PHASE7: "OFF",
    READY_DECLARED: "false",
    OPERATIONAL_GO: "false",
    CONTINUOUS_PAPER: "UNARMED",
  } as Env;
}

type CapabilityDenied = {
  ok: boolean;
  error: string;
  capability: string;
  go: boolean;
  not_a_pass: boolean;
};

describe("POST /v1/mass-eval nets_only", () => {
  it("returns 403 capability_missing mass_screen, not a nets_only screen", async () => {
    const bucket = {
      put() {
        throw new Error("STRUCTURED_BUCKET.put must not run");
      },
    } as unknown as R2Bucket;
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/mass-eval", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Mass-Eval-Token": "secret",
        },
        body: JSON.stringify({
          job_id: "nets-only-http-pin",
          seed: 1,
          logics: [{ logic_id: "pin" }],
          mode: "nets_only",
        }),
      }),
      denyByDefaultEnv(bucket),
      noopHandlers,
    );
    expect(res.status).toBe(403);
    const payload = (await res.json()) as CapabilityDenied;
    expect(payload.ok).toBe(false);
    expect(payload.error).toBe("capability_missing");
    expect(payload.capability).toBe("mass_screen");
    expect(payload.go).toBe(false);
    expect(payload.not_a_pass).toBe(true);
  });
});
