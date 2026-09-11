import { createExecutionContext, waitOnExecutionContext } from "cloudflare:test";
import { afterEach, describe, expect, it, vi } from "vitest";
import worker from "../src/index";
import type { Env } from "../src/types";

const TOKEN = "secret";

function claimedGoEnv(): Env {
  const deny = (name: string): never => {
    throw new Error(`${name} must not be accessed`);
  };
  return {
    get STRUCTURED_BUCKET() {
      return deny("STRUCTURED_BUCKET");
    },
    get AI_GATEWAY() {
      return deny("AI_GATEWAY");
    },
    get PERSONAL_RESEARCH_CONTAINER() {
      return deny("PERSONAL_RESEARCH_CONTAINER");
    },
    MASS_EVAL_TOKEN: TOKEN,
    MASS_RESEARCH: "GO",
    PHASE7: "ON",
    READY_DECLARED: "true",
    OPERATIONAL_GO: "true",
    CONTINUOUS_PAPER: "ARMED",
    NETS_ONLY: "allow",
  } as unknown as Env;
}

async function callWorker(request: Request, env: Env): Promise<Response> {
  const ctx = createExecutionContext();
  const response = await worker.fetch(request, env, ctx);
  await waitOnExecutionContext(ctx);
  return response;
}

describe("retired routes cannot execute under claimed GO flags", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each([
    ["/v1/mass-eval", "mass_screen"],
    ["/v1/daily-path", "mass_screen"],
    ["/v1/propose-thesis", "generation"],
  ] as const)("%s GET 405, query-token 401, authed POST 403", async (path, capability) => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValue(new Error("external network is forbidden"));
    const env = claimedGoEnv();
    const url = `https://example.test${path}`;

    const getRes = await callWorker(new Request(url, { method: "GET" }), env);
    expect(getRes.status).toBe(405);
    expect(await getRes.json()).toEqual({ error: "POST required" });

    const queryRes = await callWorker(
      new Request(`${url}?token=secret`, { method: "POST" }),
      env,
    );
    expect(queryRes.status).toBe(401);
    expect(await queryRes.json()).toEqual({ error: "unauthorized" });

    const authed = new Request(url, {
      method: "POST",
      headers: { "content-type": "application/json", "X-Mass-Eval-Token": TOKEN },
      body: "{",
    });
    const authedRes = await callWorker(authed, env);
    expect(authed.bodyUsed).toBe(false);
    expect(authedRes.status).toBe(403);
    expect(await authedRes.json()).toEqual({
      ok: false,
      error: "capability_missing",
      capability,
      reasons: ["verified_readiness_missing"],
      go: false,
      not_a_pass: true,
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
