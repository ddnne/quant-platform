/**
 * Collection receipt and required-segment evidence writes.
 * Segment insert stays UNKNOWN; COMPLETE is not minted here.
 */

import type { DatasetSpec } from "./catalog";
import { toJstIso } from "./identity";

export interface CollectionReceiptEnv {
  DB: D1Database;
}

export interface CollectionSegment {
  id: string;
  start: string;
  end: string;
  expectedScope: Record<string, string>;
  expectedItems: number | null;
  canonicalMonth: boolean;
}

export async function writeRequiredCoverageSegment(
  env: CollectionReceiptEnv,
  spec: DatasetSpec,
  segment: CollectionSegment,
): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO coverage_segments
       (source, dataset, segment_id, policy_version, segment_start,
        segment_end, expected_scope, expected_items, status, receipt_run_id,
        evaluated_at, detail_json)
     VALUES ('jquants', ?, ?, ?, ?, ?, ?, ?, 'UNKNOWN', NULL, ?, ?)
     ON CONFLICT(source, dataset, segment_id, policy_version) DO UPDATE SET
       segment_start=excluded.segment_start,
       segment_end=excluded.segment_end,
       expected_scope=excluded.expected_scope,
       expected_items=excluded.expected_items,
       status='UNKNOWN',
       receipt_run_id=NULL,
       evaluated_at=excluded.evaluated_at,
       detail_json=excluded.detail_json`,
  ).bind(
    spec.id, segment.id, spec.coverage.policy_version,
    segment.start, segment.end, JSON.stringify(segment.expectedScope),
    segment.expectedItems, toJstIso(new Date()),
    JSON.stringify({
      reason: "request queries planned",
      expected_item_unit: spec.coverage.expected_frequency === "event_driven"
        ? "source_event"
        : "source_query",
      query_units: segment.expectedItems,
    }),
  ).run();
}

export async function writeCollectionReceipt(
  env: CollectionReceiptEnv,
  spec: DatasetSpec,
  runId: number,
  segment: CollectionSegment,
  evidence: {
    observedItems: number;
    rawPageCount: number;
    rawRowCount: number;
    structuredRowCount: number;
    paginationExhausted: boolean;
    rawDigest: string;
    manifestKey: string;
    status: "SUCCESS" | "FAILED";
    error: string | null;
  },
): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO collection_receipts
       (source, dataset, segment_id, segment_start, segment_end,
        expected_scope, expected_items, observed_items, raw_page_count,
        raw_row_count, structured_row_count, pagination_exhausted,
        digests_json, run_id, status, error, checked_at)
     VALUES ('jquants', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(source, dataset, segment_id, run_id) DO UPDATE SET
       segment_start=excluded.segment_start,
       segment_end=excluded.segment_end,
       expected_scope=excluded.expected_scope,
       expected_items=excluded.expected_items,
       observed_items=excluded.observed_items,
       raw_page_count=excluded.raw_page_count,
       raw_row_count=excluded.raw_row_count,
       structured_row_count=excluded.structured_row_count,
       pagination_exhausted=excluded.pagination_exhausted,
       digests_json=excluded.digests_json,
       status=excluded.status,
       error=excluded.error,
       checked_at=excluded.checked_at`,
  ).bind(
    spec.id, segment.id, segment.start, segment.end,
    JSON.stringify(segment.expectedScope), segment.expectedItems,
    evidence.observedItems,
    evidence.rawPageCount, evidence.rawRowCount, evidence.structuredRowCount,
    evidence.paginationExhausted ? 1 : 0,
    JSON.stringify({ raw: evidence.rawDigest, manifest: evidence.manifestKey }),
    runId, evidence.status, evidence.error, toJstIso(new Date()),
  ).run();
}
