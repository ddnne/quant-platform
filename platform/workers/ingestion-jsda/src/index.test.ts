import { afterEach, describe, expect, it } from "vitest";
import worker from "./index";

const RUN_TOKEN = "jsda-test-run-token-do-not-leak";

function testEnv(): {
  RAW_BUCKET: never;
  DB: never;
  INGESTION_RUN_TOKEN: string;
} {
  return {
    RAW_BUCKET: {} as never,
    DB: {} as never,
    INGESTION_RUN_TOKEN: RUN_TOKEN,
  };
}

function touchingEnv(
  overrides: { INGESTION_RUN_TOKEN?: string } = { INGESTION_RUN_TOKEN: RUN_TOKEN },
): {
  env: {
    RAW_BUCKET: never;
    DB: never;
    INGESTION_RUN_TOKEN?: string;
  };
  sql: string[];
  r2Ops: string[];
} {
  const sql: string[] = [];
  const r2Ops: string[] = [];
  return {
    env: {
      RAW_BUCKET: {
        head: async () => {
          r2Ops.push("head");
          throw new Error("unexpected R2 head");
        },
        put: async () => {
          r2Ops.push("put");
          throw new Error("unexpected R2 put");
        },
      } as never,
      DB: {
        prepare: (query: string) => {
          sql.push(query);
          throw new Error(`unexpected D1: ${query}`);
        },
      } as never,
      ...overrides,
    },
    sql,
    r2Ops,
  };
}

function postRun(headers: HeadersInit = {}): Request {
  return new Request("https://ingestion-jsda.test/v1/run", {
    method: "POST",
    headers,
  });
}

function assertNoLeakOrCoverage(body: string): void {
  expect(body).not.toContain(RUN_TOKEN);
  expect(body).not.toMatch(/INGESTION_RUN_TOKEN/i);
  expect(body).not.toContain("COMPLETE");
  expect(body).not.toContain("READY");
}

describe("ingestion-jsda handlers", () => {
  const originalFetch = globalThis.fetch;
  let fetchCalls = 0;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    fetchCalls = 0;
  });

  function rejectLiveFetch(): void {
    fetchCalls = 0;
    globalThis.fetch = (async () => {
      fetchCalls += 1;
      throw new Error("live JSDA HTML must not be fetched in unit tests");
    }) as typeof fetch;
  }

  it("exposes health fetch and scheduled cron handlers", () => {
    expect(typeof worker.fetch).toBe("function");
    expect(typeof worker.scheduled).toBe("function");
  });

  it("health and unauthorized run do not leak the run token", async () => {
    const env = testEnv();
    const health = await worker.fetch(
      new Request("https://ingestion-jsda.test/health"),
      env,
    );
    expect(health.status).toBe(200);
    const healthBody = await health.text();
    expect(healthBody).not.toContain(RUN_TOKEN);
    expect(healthBody).not.toContain("COMPLETE");
    const healthJson = JSON.parse(healthBody) as { ok?: boolean; worker?: string };
    expect(healthJson.ok).toBe(true);
    expect(healthJson.worker).toBe("ingestion-jsda");

    const run = await worker.fetch(
      new Request("https://ingestion-jsda.test/v1/run"),
      env,
    );
    expect(run.status).toBe(401);
    const runBody = await run.text();
    expect(runBody).not.toContain(RUN_TOKEN);
    expect(runBody).not.toMatch(/INGESTION_RUN_TOKEN/i);
    expect(runBody).not.toContain("COMPLETE");
  });

  it("POST /v1/run missing or wrong token is 401 and does not fetch or persist", async () => {
    rejectLiveFetch();

    const missing = touchingEnv();
    const missingRes = await worker.fetch(postRun(), missing.env);
    expect(missingRes.status).toBe(401);
    const missingBody = await missingRes.text();
    expect(JSON.parse(missingBody)).toEqual({ error: "unauthorized" });
    assertNoLeakOrCoverage(missingBody);
    expect(missing.sql).toEqual([]);
    expect(missing.r2Ops).toEqual([]);

    const wrong = touchingEnv();
    const wrongRes = await worker.fetch(
      postRun({ "X-Ingestion-Token": "wrong-token" }),
      wrong.env,
    );
    expect(wrongRes.status).toBe(401);
    const wrongBody = await wrongRes.text();
    expect(JSON.parse(wrongBody)).toEqual({ error: "unauthorized" });
    assertNoLeakOrCoverage(wrongBody);
    expect(wrong.sql).toEqual([]);
    expect(wrong.r2Ops).toEqual([]);
    expect(fetchCalls).toBe(0);
  });

  it("POST /v1/run with unbound INGESTION_RUN_TOKEN is 401 even when a header is sent", async () => {
    rejectLiveFetch();
    const { env, sql, r2Ops } = touchingEnv({});
    const res = await worker.fetch(
      postRun({ "X-Ingestion-Token": RUN_TOKEN }),
      env,
    );
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    assertNoLeakOrCoverage(body);
    expect(sql).toEqual([]);
    expect(r2Ops).toEqual([]);
    expect(fetchCalls).toBe(0);
  });
});
