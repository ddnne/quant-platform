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

function authorizedEnv(bucket: R2Bucket): Env {
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

describe("POST /v1/children-then-manifest missing children[]", () => {
  it("authorized JSON {} is 400 children[] required and does not put", async () => {
    const putKeys: string[] = [];
    const bucket = {
      put(key: string) {
        putKeys.push(key);
        throw new Error("STRUCTURED_BUCKET.put must not run");
      },
    } as unknown as R2Bucket;
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/children-then-manifest", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Mass-Eval-Token": "secret",
        },
        body: "{}",
      }),
      authorizedEnv(bucket),
      noopHandlers,
    );
    expect(res.status).toBe(400);
    const payload = (await res.json()) as { error: string };
    expect(payload.error).toBe("children[] required");
    expect(putKeys).toEqual([]);
  });
});
