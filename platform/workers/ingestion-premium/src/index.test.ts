import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { handleExportPaths, type ExportEnv } from "./http_export";
import worker, { type Env } from "./index";

const here = dirname(fileURLToPath(import.meta.url));

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

  it("rejects /v1/export/d1 with unbound DATA_EXPORT_TOKEN even when a header is sent", async () => {
    const env: ExportEnv = { DB: stubD1(), DATA_EXPORT_TOKEN: undefined };
    const res = await handleExportPaths(
      new Request("https://ingestion-premium.test/v1/export/d1", {
        headers: { "X-Ingestion-Token": EXPORT_TOKEN },
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

const READY_MIGRATION = {
  migration_id: "jquants-premium-natural-keys-v2",
  state: "READY",
  contract_schema_version: 2,
  rows_primary: 0,
  rows_revisions: 0,
  rows_changes: 0,
  audit_mismatches: 0,
  detail: null,
};

function ingestD1(): { db: D1Database; binds: { sql: string; args: unknown[] }[] } {
  const binds: { sql: string; args: unknown[] }[] = [];
  const db = {
    prepare(sql: string) {
      const stmt = {
        bind(...args: unknown[]) {
          binds.push({ sql, args });
          return stmt;
        },
        first: async () => READY_MIGRATION,
        all: async () => ({ results: [], success: true, meta: {} }),
        run: async () => ({ success: true, meta: { last_row_id: 42, changes: 0 } }),
      };
      return stmt;
    },
    batch: async () => [],
  } as unknown as D1Database;
  return { db, binds };
}

function capturingBucket(): {
  bucket: R2Bucket;
  puts: { key: string; body: string; metadata?: Record<string, string> }[];
} {
  const puts: { key: string; body: string; metadata?: Record<string, string> }[] = [];
  const bucket = {
    async put(key: string, value: unknown, options?: { customMetadata?: Record<string, string> }) {
      const body = typeof value === "string" ? value : "";
      puts.push({ key, body, metadata: options?.customMetadata });
      return { key, etag: "test-etag" };
    },
  } as unknown as R2Bucket;
  return { bucket, puts };
}

describe("ingestion-premium raw acquisition status", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function runEnv() {
    const d1 = ingestD1();
    const raw = capturingBucket();
    const structured = capturingBucket();
    return {
      env: testEnv({
        DB: d1.db,
        RAW_BUCKET: raw.bucket,
        STRUCTURED_BUCKET: structured.bucket,
      }),
      d1,
      raw,
    };
  }

  function retentionBind(d1: { binds: { sql: string; args: unknown[] }[] }) {
    return d1.binds.find((row) => row.sql.includes("INSERT INTO raw_retention_manifests"));
  }

  it("writes raw_acquisition ACQUIRED on a successful fetch and never COMPLETE", async () => {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ data: [] }), { status: 200 })) as typeof fetch;
    const { env, d1, raw } = runEnv();
    const res = await worker.fetch(
      new Request(
        "https://ingestion-premium.test/v1/run?dataset=markets_calendar&from=2024-06-03&to=2024-06-03",
        {
          method: "POST",
          headers: { "X-Ingestion-Token": env.INGESTION_RUN_TOKEN! },
        },
      ),
      env,
    );
    expect(res.status).toBe(200);
    const manifests = raw.puts.filter((put) => put.key.endsWith("/manifest.json"));
    expect(manifests).toHaveLength(1);
    const body = JSON.parse(manifests[0]!.body) as Record<string, unknown>;
    expect(body.raw_acquisition).toBe("ACQUIRED");
    expect(body.complete).toBe(true);
    expect(body).not.toHaveProperty("completeness");
    expect(JSON.stringify(body)).not.toContain("COMPLETE");
    expect(manifests[0]!.metadata?.raw_acquisition).toBe("ACQUIRED");
    const retention = retentionBind(d1);
    expect(retention?.args[7]).toBe("ACQUIRED");
    expect(retention?.args).not.toContain("COMPLETE");
  });

  it("writes raw_acquisition FAILED when the vendor fetch fails and never COMPLETE", async () => {
    globalThis.fetch = (async () =>
      new Response("vendor error", { status: 400 })) as typeof fetch;
    const { env, d1, raw } = runEnv();
    const res = await worker.fetch(
      new Request(
        "https://ingestion-premium.test/v1/run?dataset=markets_calendar&from=2024-06-03&to=2024-06-03",
        {
          method: "POST",
          headers: { "X-Ingestion-Token": env.INGESTION_RUN_TOKEN! },
        },
      ),
      env,
    );
    expect(res.status).toBe(200);
    const manifests = raw.puts.filter((put) => put.key.endsWith("/manifest.json"));
    expect(manifests).toHaveLength(1);
    const body = JSON.parse(manifests[0]!.body) as Record<string, unknown>;
    expect(body.raw_acquisition).toBe("FAILED");
    expect(body.complete).toBe(false);
    expect(body).not.toHaveProperty("completeness");
    expect(JSON.stringify(body)).not.toContain("COMPLETE");
    expect(manifests[0]!.metadata?.raw_acquisition).toBe("FAILED");
    const retention = retentionBind(d1);
    expect(retention?.args[7]).toBe("FAILED");
    expect(retention?.args).not.toContain("COMPLETE");
  });

  it("retains every vendor page as page-NNNNNN.json plus rawPrefix/manifest.json", async () => {
    let calls = 0;
    globalThis.fetch = (async () => {
      calls += 1;
      if (calls === 1) {
        return new Response(
          JSON.stringify({ data: [], pagination_key: "page-2" }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ data: [] }), { status: 200 });
    }) as typeof fetch;
    const { env, raw } = runEnv();
    const res = await worker.fetch(
      new Request(
        "https://ingestion-premium.test/v1/run?dataset=markets_calendar&from=2024-06-03&to=2024-06-03",
        {
          method: "POST",
          headers: { "X-Ingestion-Token": env.INGESTION_RUN_TOKEN! },
        },
      ),
      env,
    );
    expect(res.status).toBe(200);
    const pagePuts = raw.puts.filter((put) => /\/page-\d{6}\.json$/.test(put.key));
    expect(pagePuts.map((put) => put.key.slice(put.key.lastIndexOf("/") + 1))).toEqual([
      "page-000001.json",
      "page-000002.json",
    ]);
    const prefix = pagePuts[0]!.key.slice(0, pagePuts[0]!.key.lastIndexOf("/"));
    expect(raw.puts.some((put) => put.key === `${prefix}/manifest.json`)).toBe(true);
    for (const put of raw.puts) {
      expect(put.body).not.toContain("data_truncated");
    }
  });
});

describe("ingestion-premium raw-page retain source pin", () => {
  it("keeps every raw page, a rawPrefix manifest, and ingest/export tokens only", () => {
    const src = readFileSync(join(here, "index.ts"), "utf8");
    expect(src).toContain('page-${String(page.number).padStart(6, "0")}.json');
    expect(src).toContain("`${rawPrefix}/manifest.json`");
    expect(src).not.toContain("data_truncated");
    expect(src).toContain("INGESTION_RUN_TOKEN");
    expect(src).toContain("DATA_EXPORT_TOKEN");
    expect(src).not.toContain("INGESTION_PROXY_TOKEN");
  });
});

describe("ingestion-premium coverage-segment plan", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function runEnv() {
    const d1 = ingestD1();
    const raw = capturingBucket();
    const structured = capturingBucket();
    return {
      env: testEnv({
        DB: d1.db,
        RAW_BUCKET: raw.bucket,
        STRUCTURED_BUCKET: structured.bucket,
      }),
      d1,
    };
  }

  async function runDataset(dataset: string, from: string, to: string) {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ data: [] }), { status: 200 })) as typeof fetch;
    const { env, d1 } = runEnv();
    const res = await worker.fetch(
      new Request(
        `https://ingestion-premium.test/v1/run?dataset=${dataset}&from=${from}&to=${to}`,
        {
          method: "POST",
          headers: { "X-Ingestion-Token": env.INGESTION_RUN_TOKEN! },
        },
      ),
      env,
    );
    expect(res.status).toBe(200);
    return d1;
  }

  function coverageInserts(d1: { binds: { sql: string; args: unknown[] }[] }) {
    return d1.binds.filter((row) => row.sql.includes("INSERT INTO coverage_segments"));
  }

  function receiptInserts(d1: { binds: { sql: string; args: unknown[] }[] }) {
    return d1.binds.filter((row) => row.sql.includes("INSERT INTO collection_receipts"));
  }

  it("keeps event vs query-unit planning in the ingest façade", () => {
    const src = readFileSync(join(here, "index.ts"), "utf8");
    expect(src).toContain('expected_frequency === "event_driven"');
    expect(src).toContain(": queries.length");
    expect(src).toContain("if (segment.canonicalMonth)");
    expect(src).toContain("await writeRequiredCoverageSegment");
  });

  it("plans non-event expected_items as queries.length and writes canonical months", async () => {
    const d1 = await runDataset("markets_calendar", "2024-06-01", "2024-06-30");
    const segments = coverageInserts(d1);
    expect(segments).toHaveLength(1);
    expect(segments[0]!.sql).toContain("INSERT INTO coverage_segments");
    expect(segments[0]!.sql).toContain("'UNKNOWN'");
    expect(segments[0]!.sql).not.toContain("COMPLETE");
    expect(segments[0]!.args[6]).toBe(1);
    const detail = JSON.parse(String(segments[0]!.args[8])) as {
      expected_item_unit: string;
      query_units: number | null;
    };
    expect(detail.expected_item_unit).toBe("source_query");
    expect(detail.query_units).toBe(1);
    const receipts = receiptInserts(d1);
    expect(receipts).toHaveLength(1);
    expect(receipts[0]!.args[5]).toBe(1);
    expect(JSON.stringify(segments)).not.toContain("COMPLETE");
  });

  it("plans event_driven expected_items as null before collection", async () => {
    const d1 = await runDataset("fins_summary", "2024-07-15", "2024-07-15");
    expect(coverageInserts(d1)).toHaveLength(0);
    const receipts = receiptInserts(d1);
    expect(receipts).toHaveLength(1);
    expect(receipts[0]!.args[5]).toBeNull();
    const scope = JSON.parse(String(receipts[0]!.args[4])) as {
      expected_item_unit: string;
      expected_frequency: string;
    };
    expect(scope.expected_frequency).toBe("event_driven");
    expect(scope.expected_item_unit).toBe("source_event");
  });

  it("does not write required coverage_segments for a non-canonical window", async () => {
    const d1 = await runDataset("markets_calendar", "2024-06-03", "2024-06-03");
    expect(coverageInserts(d1)).toHaveLength(0);
    const receipts = receiptInserts(d1);
    expect(receipts).toHaveLength(1);
    expect(receipts[0]!.args[5]).toBe(1);
  });
});
