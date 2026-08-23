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

function denyByDefaultEnv(): Env {
  return {
    STRUCTURED_BUCKET: {} as Env["STRUCTURED_BUCKET"],
    MASS_EVAL_TOKEN: "secret",
    MASS_RESEARCH: "NO-GO",
    PHASE7: "OFF",
    READY_DECLARED: "false",
    OPERATIONAL_GO: "false",
    CONTINUOUS_PAPER: "UNARMED",
  } as Env;
}

type HealthBody = {
  ok?: boolean;
  service?: string;
  version?: string;
  go?: boolean;
  status?: string;
};

function assertHealthNotGo(res: Response, payload: HealthBody, raw: string) {
  expect(res.status).toBe(200);
  expect(String(payload.service ?? "")).toContain("research-mass-eval");
  expect(payload.go).not.toBe(true);
  expect(raw).not.toMatch(/"go"\s*:\s*true/);
  expect(raw).not.toMatch(/\bREADY\b/);
  expect(raw).not.toMatch(/Coverage COMPLETE/);
  expect(payload.status).not.toBe("READY");
  expect(payload.status).not.toBe("COMPLETE");
}

describe("GET /health deny-by-default", () => {
  it("returns 200 with service name and is not a GO", async () => {
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/health", { method: "GET" }),
      denyByDefaultEnv(),
      noopHandlers,
    );
    const raw = await res.text();
    const payload = JSON.parse(raw) as HealthBody;
    assertHealthNotGo(res, payload, raw);
  });
});

describe("GET / deny-by-default", () => {
  it("returns 200 with service name and is not a GO", async () => {
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/", { method: "GET" }),
      denyByDefaultEnv(),
      noopHandlers,
    );
    const raw = await res.text();
    const payload = JSON.parse(raw) as HealthBody;
    assertHealthNotGo(res, payload, raw);
  });
});

describe("POST /health", () => {
  it("rejects with 405", async () => {
    const res = await dispatchMassEvalFetch(
      new Request("https://example.test/health", { method: "POST" }),
      denyByDefaultEnv(),
      noopHandlers,
    );
    expect(res.status).toBe(405);
  });
});
