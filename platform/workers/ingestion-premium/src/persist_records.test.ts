import { describe, expect, it } from "vitest";
import { datasetById } from "./catalog";
import { upsertRecords, upsertWatermark, type PersistEnv } from "./persist_records";

const SPEC = datasetById("equities_bars_daily");
const WHEN = new Date("2025-04-01T00:00:00.000Z");

function throwingEnv(): PersistEnv {
  return {
    DB: {
      prepare() {
        throw new Error("DB.prepare must not run for empty rows");
      },
    } as unknown as D1Database,
    STRUCTURED_BUCKET: {
      async put() {
        throw new Error("R2.put must not run for empty rows");
      },
    } as unknown as R2Bucket,
  };
}

function recordingD1(): {
  db: D1Database;
  sql: string[];
  binds: unknown[][];
} {
  const sql: string[] = [];
  const binds: unknown[][] = [];
  const db = {
    prepare(query: string) {
      sql.push(query);
      const stmt = {
        bind(...args: unknown[]) {
          binds.push(args);
          return stmt;
        },
        run: async () => ({ success: true, meta: { changes: 0 } }),
      };
      return stmt;
    },
  } as unknown as D1Database;
  return { db, sql, binds };
}

describe("upsertRecords empty rows", () => {
  it("returns inserted 0 revisions 0 and does not call DB.prepare or R2.put", async () => {
    expect(SPEC).toBeDefined();
    const result = await upsertRecords(throwingEnv(), SPEC!, [], WHEN);
    expect(result).toEqual({ inserted: 0, revisions: 0 });
  });
});

describe("upsertWatermark SQL", () => {
  it("pins ingestion_watermarks ON CONFLICT and bind order without live D1", async () => {
    const { db, sql, binds } = recordingD1();
    const dataset = "equities_bars_daily";
    const lastEventDate = "2025-04-01";
    const lastIngestedAt = "2025-04-01T09:00:00+09:00";
    await upsertWatermark(
      {
        DB: db,
        STRUCTURED_BUCKET: {
          async put() {
            throw new Error("R2.put must not run for watermark");
          },
        } as unknown as R2Bucket,
      },
      dataset,
      lastEventDate,
      lastIngestedAt,
    );
    expect(sql).toHaveLength(1);
    expect(sql[0]).toContain("ingestion_watermarks");
    expect(sql[0]).toMatch(/ON CONFLICT/);
    expect(binds).toEqual([[dataset, lastEventDate, lastIngestedAt, dataset]]);
  });
});
