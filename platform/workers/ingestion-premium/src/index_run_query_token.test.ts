import { afterEach, describe, expect, it } from "vitest";
import worker, { type Env } from "./index";

const EXPORT_TOKEN = "premium-test-export-token-do-not-leak";
const API_KEY = "premium-test-jquants-key-do-not-leak";

function stubD1(): D1Database {
  const stmt = {
    bind: (..._args: unknown[]) => stmt,
    first: async () => null,
    all: async () => ({ results: [], success: true, meta: {} }),
    run: async () => ({ success: true, meta: {} }),
  };
  return { prepare: (_sql: string) => stmt } as unknown as D1Database;
}

function testEnv(overrides: Partial<Env> = {}): Env {
  return {
    JQUANTS_API_KEY: API_KEY,
    INGESTION_RUN_TOKEN: "premium-test-run-token-do-not-leak",
    DATA_EXPORT_TOKEN: EXPORT_TOKEN,
    RAW_BUCKET: {} as R2Bucket,
    STRUCTURED_BUCKET: {} as R2Bucket,
    DB: stubD1(),
    ...overrides,
  };
}

function throwingBucket(): R2Bucket {
  return {
    async put() {
      throw new Error("unexpected R2 put");
    },
  } as unknown as R2Bucket;
}

function guardedEnv(): Env {
  return testEnv({
    DB: {
      prepare() {
        throw new Error("unexpected D1 prepare");
      },
    } as unknown as D1Database,
    RAW_BUCKET: throwingBucket(),
    STRUCTURED_BUCKET: throwingBucket(),
  });
}

describe("ingestion-premium mutating routes ignore query token", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("POST /v1/run with only matching query token and no header is 401 and does not ingest", async () => {
    globalThis.fetch = (async () => {
      throw new Error("unexpected fetch");
    }) as typeof fetch;
    const env = guardedEnv();
    const res = await worker.fetch(
      new Request(
        `https://ingestion-premium.test/v1/run?token=${encodeURIComponent(env.INGESTION_RUN_TOKEN!)}`,
        { method: "POST" },
      ),
      env,
    );
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    expect(body).not.toContain("COMPLETE");
    expect(body).not.toContain(env.INGESTION_RUN_TOKEN);
  });

  it("POST /v1/admin/rebuild-natural-keys-v2 with only matching query token and no header is 401", async () => {
    const env = guardedEnv();
    const res = await worker.fetch(
      new Request(
        `https://ingestion-premium.test/v1/admin/rebuild-natural-keys-v2?token=${encodeURIComponent(env.INGESTION_RUN_TOKEN!)}`,
        { method: "POST" },
      ),
      env,
    );
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    expect(body).not.toContain("COMPLETE");
    expect(body).not.toContain(env.INGESTION_RUN_TOKEN);
  });
});
