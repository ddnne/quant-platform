import { describe, expect, it } from "vitest";
import { datasetById } from "./catalog";
import { MASTER_EVENT_TYPES } from "./master_scd2/types";
import {
  upsertRecords,
  upsertWatermark,
  type PersistEnv,
} from "./persist_records";

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

const MASTER_SPEC = datasetById("equities_master");
const CURRENT_KEY = "structured/scd2/equities_master/CURRENT.json";
const LATER = new Date("2025-04-02T00:00:00.000Z");

function memoryBucket(): {
  bucket: R2Bucket;
  puts: { key: string; body: string }[];
} {
  const puts: { key: string; body: string }[] = [];
  const objects = new Map<string, string>();
  const etags = new Map<string, string>();
  const bucket = {
    async get(key: string) {
      const body = objects.get(key);
      if (body === undefined) return null;
      return {
        json: async () => JSON.parse(body),
        text: async () => body,
        etag: etags.get(key),
      };
    },
    async put(
      key: string,
      value: unknown,
      options?: {
        onlyIf?: { etagMatches?: string; etagDoesNotMatch?: string };
      },
    ) {
      const body = typeof value === "string" ? value : "";
      const exists = objects.has(key);
      const existingEtag = etags.get(key);
      if (options?.onlyIf?.etagDoesNotMatch === "*" && exists) {
        return null;
      }
      if (
        options?.onlyIf?.etagMatches &&
        (!exists || existingEtag !== options.onlyIf.etagMatches)
      ) {
        return null;
      }
      const etag = `mem-${puts.length + 1}`;
      objects.set(key, body);
      etags.set(key, etag);
      puts.push({ key, body });
      return { key, etag };
    },
  } as unknown as R2Bucket;
  return { bucket, puts };
}

function listedRow(
  code: string,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    Code: code,
    Date: "2025-04-01",
    CompanyName: `Name ${code}`,
    Sector33Code: "7200",
    Sector33CodeName: "Other Financing Business",
    Sector17Code: "15",
    Sector17CodeName: "Financials (Ex Banks)",
    ScaleCategory: "TOPIX Large70",
    MarketCode: "0111",
    MarketCodeName: "Prime",
    ListingDate: "2013-01-01",
    ...overrides,
  };
}

function persistEnv(bucket: R2Bucket): PersistEnv {
  return {
    DB: recordingD1().db,
    STRUCTURED_BUCKET: bucket,
  };
}

function parseCurrent(puts: { key: string; body: string }[], from = 0) {
  const found = puts
    .slice(from)
    .filter((put) => put.key === CURRENT_KEY)
    .at(-1);
  expect(found).toBeDefined();
  return JSON.parse(found!.body) as {
    count: number;
    by_code: Record<string, unknown>;
  };
}

function eventRows(puts: { key: string; body: string }[], from = 0) {
  return puts
    .slice(from)
    .filter((put) => put.key.includes("/events/"))
    .flatMap((put) =>
      put.body
        .split("\n")
        .filter((line) => line.length > 0)
        .map((line) => JSON.parse(line) as Record<string, unknown>),
    );
}

function evidenceBodies(puts: { key: string; body: string }[], from = 0) {
  return puts
    .slice(from)
    .filter((put) => put.key.includes("/evidence/"))
    .map((put) => JSON.parse(put.body) as Record<string, unknown>);
}

describe("upsertRecords equities_master universe evidence", () => {
  it("empty rows with trusted evidence still skip R2 and do not claim delist", async () => {
    expect(MASTER_SPEC).toBeDefined();
    const result = await upsertRecords(
      throwingEnv(),
      MASTER_SPEC!,
      [],
      WHEN,
      { paginationExhausted: true, fullUniverse: true },
    );
    expect(result).toEqual({ inserted: 0, revisions: 0 });
  });

  it("missing evidence preserves prior codes and emits no DELISTED", async () => {
    expect(MASTER_SPEC).toBeDefined();
    const { bucket, puts } = memoryBucket();
    const env = persistEnv(bucket);
    await upsertRecords(
      env,
      MASTER_SPEC!,
      [listedRow("8697"), listedRow("7203"), listedRow("6758")],
      WHEN,
    );
    const afterFirst = puts.length;

    const result = await upsertRecords(
      env,
      MASTER_SPEC!,
      [listedRow("8697"), listedRow("7203")],
      LATER,
    );

    const snap = parseCurrent(puts, afterFirst);
    expect(snap.count).toBe(3);
    expect(Object.keys(snap.by_code).sort()).toEqual(["6758", "7203", "8697"]);
    expect(
      eventRows(puts, afterFirst).filter(
        (row) => row.event_type === MASTER_EVENT_TYPES.DELISTED,
      ),
    ).toHaveLength(0);
    const evidence = evidenceBodies(puts, afterFirst);
    expect(evidence.length).toBeGreaterThan(0);
    expect(evidence.at(-1)).toMatchObject({
      pagination_exhausted: false,
      full_universe: false,
    });
    expect(result.inserted).toBe(0);
    expect(JSON.stringify(puts.slice(afterFirst))).not.toContain("COMPLETE");
  });

  it("paginationExhausted without fullUniverse does not delist", async () => {
    expect(MASTER_SPEC).toBeDefined();
    const { bucket, puts } = memoryBucket();
    const env = persistEnv(bucket);
    await upsertRecords(
      env,
      MASTER_SPEC!,
      [listedRow("8697"), listedRow("7203"), listedRow("6758")],
      WHEN,
    );
    const afterFirst = puts.length;

    await upsertRecords(
      env,
      MASTER_SPEC!,
      [listedRow("8697"), listedRow("7203")],
      LATER,
      { paginationExhausted: true, fullUniverse: false },
    );

    const snap = parseCurrent(puts, afterFirst);
    expect(snap.count).toBe(3);
    expect(Object.keys(snap.by_code).sort()).toEqual(["6758", "7203", "8697"]);
    expect(
      eventRows(puts, afterFirst).filter(
        (row) => row.event_type === MASTER_EVENT_TYPES.DELISTED,
      ),
    ).toHaveLength(0);
    expect(evidenceBodies(puts, afterFirst).at(-1)).toMatchObject({
      pagination_exhausted: true,
      full_universe: false,
    });
  });

  it("DELISTED only when paginationExhausted and fullUniverse are both true", async () => {
    expect(MASTER_SPEC).toBeDefined();
    const { bucket, puts } = memoryBucket();
    const env = persistEnv(bucket);
    await upsertRecords(
      env,
      MASTER_SPEC!,
      [listedRow("8697"), listedRow("7203"), listedRow("6758")],
      WHEN,
    );
    const afterFirst = puts.length;

    const result = await upsertRecords(
      env,
      MASTER_SPEC!,
      [listedRow("8697"), listedRow("7203")],
      LATER,
      { paginationExhausted: true, fullUniverse: true },
    );

    const snap = parseCurrent(puts, afterFirst);
    expect(snap.count).toBe(2);
    expect(snap.by_code["6758"]).toBeUndefined();
    expect(Object.keys(snap.by_code).sort()).toEqual(["7203", "8697"]);
    const delisted = eventRows(puts, afterFirst).filter(
      (row) => row.event_type === MASTER_EVENT_TYPES.DELISTED,
    );
    expect(delisted).toHaveLength(1);
    expect(delisted[0]).toMatchObject({
      event_type: MASTER_EVENT_TYPES.DELISTED,
      local_code: "6758",
      new_hash: null,
      attrs: null,
    });
    expect(result.inserted).toBe(1);
    expect(evidenceBodies(puts, afterFirst).at(-1)).toMatchObject({
      pagination_exhausted: true,
      full_universe: true,
    });
    expect(JSON.stringify(puts.slice(afterFirst))).not.toContain("COMPLETE");
  });
});
