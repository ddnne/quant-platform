import { describe, expect, it } from "vitest";
import { authorized } from "./http";
import { dispatchMassEvalFetch } from "./http_routes";
import type { Env } from "./types";

const TOKEN = "secret";

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

async function expectUnauthorizedNoEval(res: Response) {
  expect(res.status).toBe(401);
  const body = await res.text();
  expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
  expect(body).not.toContain("COMPLETE");
}

describe("authorized ignores query token", () => {
  it("denies matching ?token= with no header", async () => {
    expect(
      await authorized(
        new Request("https://example.test/v1/mass-eval?token=secret", {
          method: "POST",
        }),
        "secret",
      ),
    ).toBe(false);
  });

  it("accepts matching X-Mass-Eval-Token header", async () => {
    expect(
      await authorized(
        new Request("https://example.test/v1/mass-eval", {
          method: "POST",
          headers: { "X-Mass-Eval-Token": TOKEN },
        }),
        TOKEN,
      ),
    ).toBe(true);
  });
});

describe("mutating routes ignore query token", () => {
  const env = denyByDefaultEnv({ MASS_EVAL_TOKEN: TOKEN });

  it("POST /v1/mass-eval?token=secret with no header is 401 and does not eval", async () => {
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/mass-eval?token=secret", {
        method: "POST",
      }),
      env,
      noopHandlers,
    );
    await expectUnauthorizedNoEval(res);
  });

  it("POST /v1/daily-path?token=secret with no header is 401 and does not eval", async () => {
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/daily-path?token=secret", {
        method: "POST",
      }),
      env,
      noopHandlers,
    );
    await expectUnauthorizedNoEval(res);
  });

  it("POST /v1/propose-thesis?token=secret with no header is 401 and does not eval", async () => {
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/propose-thesis?token=secret", {
        method: "POST",
      }),
      env,
      noopHandlers,
    );
    await expectUnauthorizedNoEval(res);
  });

  it("POST /v1/children-then-manifest?token=secret with no header is 401 not 503", async () => {
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/v1/children-then-manifest?token=secret", {
        method: "POST",
      }),
      denyByDefaultEnv({ MASS_EVAL_TOKEN: "secret" }),
      noopHandlers,
    );
    expect(res.status).not.toBe(503);
    await expectUnauthorizedNoEval(res);
  });
});
