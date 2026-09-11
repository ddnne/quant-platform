import { env } from "cloudflare:workers";
import { applyD1Migrations, reset } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, inject, it } from "vitest";
import { datasetById } from "../src/catalog";
import {
  writeCollectionReceipt,
  writeRequiredCoverageSegment,
  type CollectionSegment,
} from "../src/collection_receipts";

const premiumD1Migrations =
  inject<Array<{ name: string; queries: string[] }>>("premiumD1Migrations");

function spec(id: Parameters<typeof datasetById>[0]) {
  const dataset = datasetById(id);
  if (!dataset) throw new Error(`catalog missing ${id}`);
  return dataset;
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

async function coverageRow(dataset: string) {
  return env.DB.prepare(
    `SELECT source, dataset, segment_id, policy_version, segment_start,
            segment_end, expected_scope, expected_items, status,
            receipt_run_id, evaluated_at, detail_json
       FROM coverage_segments
      WHERE dataset = ? AND segment_id = ?`,
  )
    .bind(dataset, "2024-06")
    .first<Record<string, unknown>>();
}

async function receiptRow(runId: number) {
  return env.DB.prepare(
    `SELECT source, dataset, segment_id, expected_items, observed_items,
            raw_page_count, raw_row_count, structured_row_count,
            pagination_exhausted, digests_json, run_id, status, error
       FROM collection_receipts
      WHERE dataset = ? AND segment_id = ? AND run_id = ?`,
  )
    .bind("markets_calendar", "2024-06", runId)
    .first<Record<string, unknown>>();
}

beforeEach(async () => {
  await applyD1Migrations(env.DB, premiumD1Migrations);
});

afterEach(async () => {
  await reset();
});

describe("writeRequiredCoverageSegment", () => {
  it.each([
    ["markets_calendar", "collection-coverage/v3", 4, "source_query"],
    ["fins_summary", "collection-coverage/v3", null, "source_event"],
    ["equities_investor_types", "collection-coverage/v2", 1, "source_query"],
  ] as const)(
    "records %s UNKNOWN %s %s units=%s and no receipt",
    async (id, policy, expectedItems, unit) => {
      const segment = june({ expectedItems });
      await writeRequiredCoverageSegment({ DB: env.DB }, spec(id), segment);
      const row = await coverageRow(id);
      expect(row).toMatchObject({
        source: "jquants",
        dataset: id,
        segment_id: "2024-06",
        segment_start: "2024-06-01",
        segment_end: "2024-06-30",
        policy_version: policy,
        expected_items: expectedItems,
        status: "UNKNOWN",
        receipt_run_id: null,
      });
      expect(JSON.parse(String(row?.detail_json))).toMatchObject({
        reason: "request queries planned",
        expected_item_unit: unit,
        query_units: expectedItems,
      });
      expect(
        await env.DB.prepare("SELECT run_id FROM collection_receipts").first(),
      ).toBeNull();
    },
  );

  it("replans COMPLETE+77 to UNKNOWN/null and updates expected amount/scope", async () => {
    const dataset = spec("markets_calendar");
    const replanned = june({ expectedItems: 4 });
    await env.DB.prepare(
      `INSERT INTO coverage_segments
         (source, dataset, segment_id, policy_version, segment_start,
          segment_end, expected_scope, expected_items, status, receipt_run_id,
          evaluated_at, detail_json)
       VALUES ('jquants', ?, ?, ?, '2024-06-01', '2024-06-30', ?, 1, 'COMPLETE', 77,
               '2024-05-01T00:00:00+09:00', '{"reason":"prior"}')`,
    )
      .bind(
        dataset.id,
        replanned.id,
        dataset.coverage.policy_version,
        JSON.stringify({ universe_rule: "prior_universe" }),
      )
      .run();
    await writeRequiredCoverageSegment({ DB: env.DB }, dataset, replanned);
    expect(await coverageRow("markets_calendar")).toMatchObject({
      expected_scope: JSON.stringify(replanned.expectedScope),
      expected_items: 4,
      status: "UNKNOWN",
      receipt_run_id: null,
    });
    expect(
      await env.DB.prepare("SELECT COUNT(*) AS n FROM coverage_segments").first<{
        n: number;
      }>(),
    ).toMatchObject({ n: 1 });
  });
});

describe("writeCollectionReceipt", () => {
  it.each([
    {
      runId: 42,
      evidence: {
        observedItems: 3, rawPageCount: 2, rawRowCount: 5, structuredRowCount: 8,
        paginationExhausted: true, rawDigest: "digest-success",
        manifestKey: "raw/markets_calendar/2024-06/success.json",
        status: "SUCCESS" as const, error: null,
      },
    },
    {
      runId: 43,
      evidence: {
        observedItems: 4, rawPageCount: 1, rawRowCount: 6, structuredRowCount: 7,
        paginationExhausted: false, rawDigest: "digest-failed",
        manifestKey: "raw/markets_calendar/2024-06/failed.json",
        status: "FAILED" as const, error: "vendor 400",
      },
    },
  ])(
    "records $evidence.status unsigned RECOVERED_RAW_ONLY without changing coverage",
    async ({ runId, evidence }) => {
      const dataset = spec("markets_calendar");
      const segment = june({ expectedItems: 1 });
      await writeRequiredCoverageSegment({ DB: env.DB }, dataset, segment);
      const before = await coverageRow("markets_calendar");
      expect(before).toMatchObject({ status: "UNKNOWN", receipt_run_id: null });
      await writeCollectionReceipt(
        { DB: env.DB },
        dataset,
        runId,
        segment,
        evidence,
      );
      expect(await coverageRow("markets_calendar")).toEqual(before);
      const receipt = await receiptRow(runId);
      expect(receipt).toMatchObject({
        source: "jquants",
        dataset: "markets_calendar",
        segment_id: "2024-06",
        expected_items: 1,
        observed_items: evidence.observedItems,
        raw_page_count: evidence.rawPageCount,
        raw_row_count: evidence.rawRowCount,
        structured_row_count: evidence.structuredRowCount,
        pagination_exhausted: evidence.paginationExhausted ? 1 : 0,
        run_id: runId,
        status: evidence.status,
        error: evidence.error,
      });
      expect(JSON.parse(String(receipt?.digests_json))).toMatchObject({
        eligibility: "RECOVERED_RAW_ONLY",
        issuer_class: "UnsignedIngestionAudit",
        raw: evidence.rawDigest,
        manifest: evidence.manifestKey,
      });
    },
  );
});
