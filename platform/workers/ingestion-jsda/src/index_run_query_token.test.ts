import { afterEach, describe, expect, it } from "vitest";
import worker from "./index";

const RUN_TOKEN = "jsda-test-run-token-do-not-leak";

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

function assertNoLeakOrCoverage(body: string): void {
  expect(body).not.toContain(RUN_TOKEN);
  expect(body).not.toMatch(/INGESTION_RUN_TOKEN/i);
  expect(body).not.toContain("COMPLETE");
  expect(body).not.toContain("READY");
}

describe("ingestion-jsda POST /v1/run ignores query token", () => {
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

  it("POST /v1/run with only matching query token and no header is 401 and does not ingest", async () => {
    rejectLiveFetch();
    const { env, sql, r2Ops } = touchingEnv();
    const res = await worker.fetch(
      new Request(
        `https://ingestion-jsda.test/v1/run?token=${encodeURIComponent(RUN_TOKEN)}`,
        { method: "POST" },
      ),
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
