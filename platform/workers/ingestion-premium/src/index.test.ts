import { describe, expect, it } from "vitest";
import { handleExportPaths, type ExportEnv } from "./http_export";
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

describe("ingestion-premium export auth", () => {
  it("rejects /v1/export/d1 without a token", async () => {
    const env: ExportEnv = { DB: stubD1(), DATA_EXPORT_TOKEN: EXPORT_TOKEN };
    const res = await handleExportPaths(
      new Request("https://ingestion-premium.test/v1/export/d1"),
      env,
    );
    expect(res).not.toBeNull();
    expect(res!.status).toBe(401);
    const body = await res!.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    expect(body).not.toContain(EXPORT_TOKEN);
  });

  it("rejects /v1/export/changes with a wrong token", async () => {
    const env: ExportEnv = { DB: stubD1(), DATA_EXPORT_TOKEN: EXPORT_TOKEN };
    const res = await handleExportPaths(
      new Request("https://ingestion-premium.test/v1/export/changes", {
        headers: { "X-Ingestion-Token": "wrong-token" },
      }),
      env,
    );
    expect(res).not.toBeNull();
    expect(res!.status).toBe(401);
    const body = await res!.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    expect(body).not.toContain(EXPORT_TOKEN);
  });
});

describe("ingestion-premium health", () => {
  it("serves /health without leaking secrets", async () => {
    const env = testEnv();
    const res = await worker.fetch(
      new Request("https://ingestion-premium.test/health"),
      env,
    );
    expect(res.status).toBe(200);
    const body = await res.text();
    expect(body).not.toContain(EXPORT_TOKEN);
    expect(body).not.toContain(API_KEY);
    expect(body).not.toContain(env.INGESTION_RUN_TOKEN);
    const json = JSON.parse(body) as {
      ok: boolean;
      has_jquants_key: boolean;
      datasets: number;
    };
    expect(json.has_jquants_key).toBe(true);
    expect(typeof json.datasets).toBe("number");
    expect(json.datasets).toBeGreaterThan(0);
    expect(json.ok).toBe(false);
  });
});
