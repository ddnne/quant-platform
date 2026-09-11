/**
 * Node public-routing probe for /v1/export/* via worker.fetch.
 * Not a workerd/D1 runtime proof.
 *
 * Matcher coverage is GET /v1/export/d1 (absent, wrong, unbound, run-token).
 * Query-only and wrong-method run on all three routes because dispatch can
 * omit a handler; those are route-wiring checks, not extra comparator cells.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import worker, { type Env } from "./index";

const EXPORT_TOKEN = "premium-test-export-token-do-not-leak";
const RUN_TOKEN = "premium-test-run-token-do-not-leak";

type ProbeCounts = {
  dbPrepare: number;
  dbAccess: number;
  dbOther: number;
  envUnexpected: string[];
  fetch: number;
};

function exportRequest(path: string, init: RequestInit = {}): Request {
  return new Request(`https://ingestion-premium.test${path}`, init);
}

function beginProbe(
  dataExportToken: string | undefined,
): { env: Env; counts: ProbeCounts } {
  const counts: ProbeCounts = {
    dbPrepare: 0,
    dbAccess: 0,
    dbOther: 0,
    envUnexpected: [],
    fetch: 0,
  };

  const db = new Proxy({} as D1Database, {
    get(_target, prop) {
      if (prop === "prepare") {
        return (_sql: string) => {
          counts.dbPrepare += 1;
          throw new Error("prepare-after-auth");
        };
      }
      counts.dbOther += 1;
      throw new Error(`unexpected D1 access: ${String(prop)}`);
    },
  });

  // Single test-only Env boundary. Credential fields plus DB; other gets
  // are recorded and refused.
  const env = new Proxy({} as Env, {
    get(_target, prop) {
      if (prop === "DATA_EXPORT_TOKEN") return dataExportToken;
      if (prop === "INGESTION_RUN_TOKEN") return RUN_TOKEN;
      if (prop === "DB") {
        counts.dbAccess += 1;
        return db;
      }
      const name = String(prop);
      counts.envUnexpected.push(name);
      throw new Error(`unexpected env binding: ${name}`);
    },
  });

  return { env, counts };
}

async function assertRejected(
  res: Response,
  status: number,
  error: string,
  counts: ProbeCounts,
): Promise<void> {
  expect(res.status).toBe(status);
  expect(await res.json()).toEqual({ error });
  expect(counts.dbPrepare).toBe(0);
  expect(counts.dbAccess).toBe(0);
  expect(counts.dbOther).toBe(0);
  expect(counts.envUnexpected).toEqual([]);
  expect(counts.fetch).toBe(0);
}

describe("export public routing via worker.fetch", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      throw new Error("unexpected outbound fetch");
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function installFetchCounter(counts: ProbeCounts): void {
    vi.mocked(globalThis.fetch).mockImplementation(async () => {
      counts.fetch += 1;
      throw new Error("unexpected outbound fetch");
    });
  }

  it("GET /v1/export/d1 without X-Ingestion-Token is 401", async () => {
    const { env, counts } = beginProbe(EXPORT_TOKEN);
    installFetchCounter(counts);
    const res = await worker.fetch(exportRequest("/v1/export/d1"), env);
    await assertRejected(res, 401, "unauthorized", counts);
  });

  it("GET /v1/export/d1 with the wrong header is 401", async () => {
    const { env, counts } = beginProbe(EXPORT_TOKEN);
    installFetchCounter(counts);
    const res = await worker.fetch(
      exportRequest("/v1/export/d1", {
        headers: { "X-Ingestion-Token": "wrong-token" },
      }),
      env,
    );
    await assertRejected(res, 401, "unauthorized", counts);
  });

  it("GET /v1/export/d1 with unbound DATA_EXPORT_TOKEN is 401", async () => {
    const { env, counts } = beginProbe(undefined);
    installFetchCounter(counts);
    const res = await worker.fetch(
      exportRequest("/v1/export/d1", {
        headers: { "X-Ingestion-Token": EXPORT_TOKEN },
      }),
      env,
    );
    await assertRejected(res, 401, "unauthorized", counts);
  });

  it("GET /v1/export/d1 with INGESTION_RUN_TOKEN as the header is 401", async () => {
    const { env, counts } = beginProbe(EXPORT_TOKEN);
    installFetchCounter(counts);
    const res = await worker.fetch(
      exportRequest("/v1/export/d1", {
        headers: { "X-Ingestion-Token": RUN_TOKEN },
      }),
      env,
    );
    await assertRejected(res, 401, "unauthorized", counts);
  });

  it("query token is ignored on all three export routes", async () => {
    for (const [method, path] of [
      ["GET", "/v1/export/d1"],
      ["GET", "/v1/export/changes"],
      ["POST", "/v1/export/receipt-products"],
    ] as const) {
      const { env, counts } = beginProbe(EXPORT_TOKEN);
      installFetchCounter(counts);
      const res = await worker.fetch(
        exportRequest(`${path}?token=${EXPORT_TOKEN}`, { method }),
        env,
      );
      await assertRejected(res, 401, "unauthorized", counts);
    }
  });

  it("wrong method is 405 on all three export routes", async () => {
    for (const [method, path, error] of [
      ["POST", "/v1/export/d1", "GET required"],
      ["POST", "/v1/export/changes", "GET required"],
      ["GET", "/v1/export/receipt-products", "POST required"],
    ] as const) {
      const { env, counts } = beginProbe(EXPORT_TOKEN);
      installFetchCounter(counts);
      const res = await worker.fetch(
        exportRequest(path, {
          method,
          headers: { "X-Ingestion-Token": EXPORT_TOKEN },
        }),
        env,
      );
      await assertRejected(res, 405, error, counts);
    }
  });

  it("authorized table=not_a_table is 400 and does not touch DB", async () => {
    const { env, counts } = beginProbe(EXPORT_TOKEN);
    installFetchCounter(counts);
    const res = await worker.fetch(
      exportRequest("/v1/export/d1?table=not_a_table", {
        headers: { "X-Ingestion-Token": EXPORT_TOKEN },
      }),
      env,
    );
    await assertRejected(res, 400, "table not exportable", counts);
  });

  it("authorized limit=0 or 1001 is 400 and does not touch DB", async () => {
    for (const limit of [0, 1001]) {
      const { env, counts } = beginProbe(EXPORT_TOKEN);
      installFetchCounter(counts);
      const res = await worker.fetch(
        exportRequest(`/v1/export/d1?limit=${limit}`, {
          headers: { "X-Ingestion-Token": EXPORT_TOKEN },
        }),
        env,
      );
      await assertRejected(
        res,
        400,
        "limit must be an integer between 1 and 1000",
        counts,
      );
    }
  });

  it("authorized after_seq=-1 is 400 and does not touch DB", async () => {
    const { env, counts } = beginProbe(EXPORT_TOKEN);
    installFetchCounter(counts);
    const res = await worker.fetch(
      exportRequest("/v1/export/changes?after_seq=-1", {
        headers: { "X-Ingestion-Token": EXPORT_TOKEN },
      }),
      env,
    );
    await assertRejected(
      res,
      400,
      "after_seq must be a non-negative safe integer",
      counts,
    );
  });

  it("authorized GET /v1/export/d1 attempts DB prepare", async () => {
    const { env, counts } = beginProbe(EXPORT_TOKEN);
    installFetchCounter(counts);
    await expect(
      worker.fetch(
        exportRequest("/v1/export/d1", {
          headers: { "X-Ingestion-Token": EXPORT_TOKEN },
        }),
        env,
      ),
    ).rejects.toThrow("prepare-after-auth");
    expect(counts.dbPrepare).toBeGreaterThan(0);
    expect(counts.dbAccess).toBeGreaterThan(0);
    expect(counts.fetch).toBe(0);
    expect(counts.envUnexpected).toEqual([]);
  });

  it("authorized GET /v1/export/changes attempts DB prepare", async () => {
    const { env, counts } = beginProbe(EXPORT_TOKEN);
    installFetchCounter(counts);
    await expect(
      worker.fetch(
        exportRequest("/v1/export/changes", {
          headers: { "X-Ingestion-Token": EXPORT_TOKEN },
        }),
        env,
      ),
    ).rejects.toThrow("prepare-after-auth");
    expect(counts.dbPrepare).toBeGreaterThan(0);
    expect(counts.dbAccess).toBeGreaterThan(0);
    expect(counts.fetch).toBe(0);
    expect(counts.envUnexpected).toEqual([]);
  });

  it("authorized POST /v1/export/receipt-products with malformed JSON is 400", async () => {
    const { env, counts } = beginProbe(EXPORT_TOKEN);
    installFetchCounter(counts);
    const res = await worker.fetch(
      exportRequest("/v1/export/receipt-products", {
        method: "POST",
        headers: { "X-Ingestion-Token": EXPORT_TOKEN },
        body: "{",
      }),
      env,
    );
    await assertRejected(res, 400, "invalid json", counts);
  });

  it("unknown export path is 404 via worker.fetch", async () => {
    const { env, counts } = beginProbe(EXPORT_TOKEN);
    installFetchCounter(counts);
    const res = await worker.fetch(
      exportRequest("/v1/export/unknown", {
        headers: { "X-Ingestion-Token": EXPORT_TOKEN },
      }),
      env,
    );
    await assertRejected(res, 404, "not found", counts);
  });
});
