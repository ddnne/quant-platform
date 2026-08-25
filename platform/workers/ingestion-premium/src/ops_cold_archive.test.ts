import { describe, expect, it } from "vitest";
import { handleArchiveCold, type ArchiveEnv } from "./ops_cold_archive";

const RUN_TOKEN = "premium-test-run-token-do-not-leak";
const ARCHIVE_PATH = "https://ingestion-premium.test/v1/ops/archive-cold";

function touchingEnv(
  overrides: Partial<ArchiveEnv> = {},
): {
  env: ArchiveEnv;
  sql: string[];
  r2Puts: string[];
} {
  const sql: string[] = [];
  const r2Puts: string[] = [];
  const env: ArchiveEnv = {
    DB: {
      prepare(query: string) {
        sql.push(query);
        const stmt = {
          bind(..._args: unknown[]) {
            return stmt;
          },
          all: async () => ({ results: [], success: true, meta: {} }),
          run: async () => ({ success: true, meta: { changes: 0 } }),
        };
        return stmt;
      },
    } as unknown as D1Database,
    STRUCTURED_BUCKET: {
      async put(key: string) {
        r2Puts.push(key);
        return { key, etag: "test-etag" };
      },
    } as unknown as R2Bucket,
    INGESTION_RUN_TOKEN: RUN_TOKEN,
    ...overrides,
  };
  return { env, sql, r2Puts };
}

function archiveRequest(
  params: Record<string, string> = {},
  headers: HeadersInit = {},
): Request {
  const url = new URL(ARCHIVE_PATH);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  return new Request(url, { method: "POST", headers });
}

function assertNoCoverageInvention(body: string): void {
  expect(body).not.toContain(RUN_TOKEN);
  expect(body).not.toMatch(/INGESTION_RUN_TOKEN/i);
  expect(body).not.toContain("COMPLETE");
  expect(body).not.toContain("READY");
  expect(body).not.toMatch(/Coverage/i);
}

function assertNoArchiveSideEffects(sql: string[], r2Puts: string[]): void {
  expect(sql).toEqual([]);
  expect(r2Puts).toEqual([]);
  expect(sql.some((query) => /\bDELETE\b/i.test(query))).toBe(false);
  expect(
    sql.some(
      (query) =>
        query.includes("coverage_segments") ||
        query.includes("collection_receipts") ||
        query.includes("raw_retention_manifests"),
    ),
  ).toBe(false);
}

describe("handleArchiveCold fail-closed", () => {
  it("missing or wrong INGESTION_RUN_TOKEN is 401 with no D1 DELETE and no R2 put", async () => {
    const missing = touchingEnv();
    const missingRes = await handleArchiveCold(
      archiveRequest({ dataset: "markets_calendar", before: "2024-01-01" }),
      missing.env,
    );
    expect(missingRes.status).toBe(401);
    const missingBody = await missingRes.text();
    expect(JSON.parse(missingBody)).toEqual({ error: "unauthorized" });
    assertNoCoverageInvention(missingBody);
    assertNoArchiveSideEffects(missing.sql, missing.r2Puts);

    const wrong = touchingEnv();
    const wrongRes = await handleArchiveCold(
      archiveRequest(
        { dataset: "markets_calendar", before: "2024-01-01" },
        { "X-Ingestion-Token": "wrong-token" },
      ),
      wrong.env,
    );
    expect(wrongRes.status).toBe(401);
    const wrongBody = await wrongRes.text();
    expect(JSON.parse(wrongBody)).toEqual({ error: "unauthorized" });
    assertNoCoverageInvention(wrongBody);
    assertNoArchiveSideEffects(wrong.sql, wrong.r2Puts);
  });

  it("unbound INGESTION_RUN_TOKEN is 401 even when a header is sent", async () => {
    const { env, sql, r2Puts } = touchingEnv({ INGESTION_RUN_TOKEN: undefined });
    const res = await handleArchiveCold(
      archiveRequest(
        { dataset: "markets_calendar", before: "2024-01-01" },
        { "X-Ingestion-Token": RUN_TOKEN },
      ),
      env,
    );
    expect(res.status).toBe(401);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "unauthorized" });
    assertNoCoverageInvention(body);
    assertNoArchiveSideEffects(sql, r2Puts);
  });

  it("missing dataset is 400 with no D1 DELETE and no R2 put", async () => {
    const { env, sql, r2Puts } = touchingEnv();
    const res = await handleArchiveCold(
      archiveRequest(
        { before: "2024-01-01" },
        { "X-Ingestion-Token": RUN_TOKEN },
      ),
      env,
    );
    expect(res.status).toBe(400);
    const body = await res.text();
    expect(JSON.parse(body)).toEqual({ error: "dataset is required" });
    assertNoCoverageInvention(body);
    assertNoArchiveSideEffects(sql, r2Puts);
  });

  it("bad before (not YYYY-MM-DD) is 400 with no D1 DELETE and no R2 put", async () => {
    const bads = ["2024/01/01", "20240101", "2024-1-1", "yesterday"];
    for (const before of bads) {
      const { env, sql, r2Puts } = touchingEnv();
      const res = await handleArchiveCold(
        archiveRequest(
          { dataset: "markets_calendar", before },
          { "X-Ingestion-Token": RUN_TOKEN },
        ),
        env,
      );
      expect(res.status).toBe(400);
      const body = await res.text();
      expect(JSON.parse(body)).toEqual({ error: "before must be YYYY-MM-DD" });
      assertNoCoverageInvention(body);
      assertNoArchiveSideEffects(sql, r2Puts);
    }
  });
});
