import { describe, expect, it } from "vitest";
import { datasetById } from "./catalog";
import {
  writeRequiredCoverageSegment,
  type CollectionSegment,
} from "./collection_receipts";

function capturingD1(): {
  db: D1Database;
  binds: { sql: string; args: unknown[] }[];
} {
  const binds: { sql: string; args: unknown[] }[] = [];
  const db = {
    prepare(sql: string) {
      const stmt = {
        bind(...args: unknown[]) {
          binds.push({ sql, args });
          return stmt;
        },
        run: async () => ({ success: true, meta: {} }),
      };
      return stmt;
    },
  } as unknown as D1Database;
  return { db, binds };
}

function june(overrides: Partial<CollectionSegment> = {}): CollectionSegment {
  return {
    id: "2024-06",
    start: "2024-06-01",
    end: "2024-06-30",
    expectedScope: {
      coverage_mode: "calendar",
      expected_frequency: "calendar_day",
      expected_item_unit: "source_query",
      segment_end: "2024-06-30",
      segment_start: "2024-06-01",
      universe_rule: "jpx_calendar_days",
    },
    expectedItems: 1,
    canonicalMonth: true,
    ...overrides,
  };
}

describe("writeRequiredCoverageSegment", () => {
  it("inserts coverage_segments as UNKNOWN with planned query units", async () => {
    const spec = datasetById("markets_calendar");
    expect(spec).toBeDefined();
    expect(spec!.coverage.expected_frequency).toBe("calendar_day");
    const { db, binds } = capturingD1();
    await writeRequiredCoverageSegment(
      { DB: db },
      spec!,
      june({ expectedItems: 4 }),
    );
    expect(binds).toHaveLength(1);
    const row = binds[0]!;
    expect(row.sql).toContain("INSERT INTO coverage_segments");
    expect(row.sql).toContain("'UNKNOWN'");
    expect(row.sql).toContain("status='UNKNOWN'");
    expect(row.sql).not.toContain("COMPLETE");
    expect(row.args[0]).toBe("markets_calendar");
    expect(row.args[1]).toBe("2024-06");
    expect(row.args[2]).toBe("collection-coverage/v2");
    expect(row.args[3]).toBe("2024-06-01");
    expect(row.args[4]).toBe("2024-06-30");
    expect(row.args[6]).toBe(4);
    const detail = JSON.parse(String(row.args[8])) as {
      reason: string;
      expected_item_unit: string;
      query_units: number | null;
    };
    expect(detail).toEqual({
      reason: "request queries planned",
      expected_item_unit: "source_query",
      query_units: 4,
    });
    expect(JSON.stringify(row)).not.toContain("COMPLETE");
  });

  it("records event_driven required segments with null query units", async () => {
    const spec = datasetById("fins_summary");
    expect(spec).toBeDefined();
    expect(spec!.coverage.expected_frequency).toBe("event_driven");
    const { db, binds } = capturingD1();
    await writeRequiredCoverageSegment(
      { DB: db },
      spec!,
      june({ expectedItems: null }),
    );
    expect(binds).toHaveLength(1);
    const row = binds[0]!;
    expect(row.sql).toContain("INSERT INTO coverage_segments");
    expect(row.sql).toContain("'UNKNOWN'");
    expect(row.sql).not.toContain("COMPLETE");
    expect(row.args[0]).toBe("fins_summary");
    expect(row.args[6]).toBeNull();
    const detail = JSON.parse(String(row.args[8])) as {
      expected_item_unit: string;
      query_units: number | null;
    };
    expect(detail.expected_item_unit).toBe("source_event");
    expect(detail.query_units).toBeNull();
  });
});
