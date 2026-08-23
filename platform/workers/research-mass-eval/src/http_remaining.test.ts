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

function denyByDefaultEnv(extra: Partial<Env> = {}): Env {
  return {
    STRUCTURED_BUCKET: {} as Env["STRUCTURED_BUCKET"],
    MASS_RESEARCH: "NO-GO",
    PHASE7: "OFF",
    READY_DECLARED: "false",
    OPERATIONAL_GO: "false",
    CONTINUOUS_PAPER: "UNARMED",
    ...extra,
  } as Env;
}

describe("unknown path", () => {
  it("GET /nope is 404 not found and does not run eval", async () => {
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/nope", { method: "GET" }),
      denyByDefaultEnv({ MASS_EVAL_TOKEN: "secret" }),
      noopHandlers,
    );
    expect(res.status).toBe(404);
    const body = (await res.json()) as { error: string; path: string };
    expect(body.error).toBe("not found");
    expect(body.path).toBe("/nope");
  });
});

describe("unbound MASS_EVAL_TOKEN", () => {
  it("POST /v1/mass-eval is 401 unauthorized and does not run eval", async () => {
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/mass-eval", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Mass-Eval-Token": "secret",
        },
        body: JSON.stringify({
          job_id: "unbound-token-pin",
          seed: 1,
          logics: [{ logic_id: "pin" }],
        }),
      }),
      denyByDefaultEnv(),
      noopHandlers,
    );
    expect(res.status).toBe(401);
    const body = (await res.json()) as { error: string };
    expect(body.error).toBe("unauthorized");
  });
});
