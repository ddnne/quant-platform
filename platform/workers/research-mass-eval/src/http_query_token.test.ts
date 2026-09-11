import { describe, expect, it } from "vitest";
import { dispatchMassEvalFetch } from "./http_routes";
import type { Env } from "./types";

const TOKEN = "secret";

const noopHandlers = {};

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

describe("mutating routes ignore query token", () => {
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
