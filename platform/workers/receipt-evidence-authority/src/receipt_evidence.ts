import {
  canonicalDigest,
  canonicalJson,
} from "../../ingestion-secrets/src/jquants_acquisition_registry";
import type { JquantsAcquisitionRequestV2 } from "../../ingestion-secrets/src/jquants_acquisition_types";
import type { DatasetSpec } from "../../ingestion-premium/src/catalog";
import type { IssuedRecord } from "./authority_do";
import type { Capture } from "./raw_capture";
import type {
  CollectionReceiptV2,
  JsonValue,
  ReceiptAuthorityEnv,
  UnsignedReceiptClaimsV2,
} from "./types";

function expectedScope(spec: DatasetSpec, initial: JquantsAcquisitionRequestV2): {
  scope: Record<string, JsonValue>;
  expectedItems: number | null;
} {
  const eventDriven = spec.coverage.expected_frequency === "event_driven";
  return {
    scope: {
      coverage_mode: spec.coverage.coverage_mode,
      expected_frequency: spec.coverage.expected_frequency,
      expected_item_unit: eventDriven ? "source_event" : "source_query",
      segment_end: initial.segment_end,
      segment_start: initial.segment_start,
      universe_rule: spec.coverage.universe_rule,
      segment_granularity: "calendar_month",
    },
    expectedItems: eventDriven ? null : 1,
  };
}

export async function measuredClaims(input: {
  requestDigest: string;
  runId: number;
  spec: DatasetSpec;
  capture: Capture;
  structuredCount: number;
  structuredDigest: string;
  checkedAt: string;
}): Promise<UnsignedReceiptClaimsV2> {
  const { scope, expectedItems } = expectedScope(input.spec, input.capture.initialRequest);
  const rawCount = input.capture.pages.reduce((total, page) => total + page.rowCount, 0);
  if (rawCount !== input.structuredCount) {
    throw new Error("raw and structured counts do not reconcile");
  }
  if (input.spec.coverage.policy_version !== "collection-coverage/v3") {
    throw new Error("receipt authority accepts only Coverage V3");
  }
  const scopeBody = {
    coverage_policy_version: "collection-coverage/v3" as const,
    source: "jquants" as const,
    dataset: input.spec.id,
    segment_id: input.capture.initialRequest.segment_id,
    segment_start: input.capture.initialRequest.segment_start,
    segment_end: input.capture.initialRequest.segment_end,
    expected_scope: scope,
    expected_items: expectedItems,
  };
  const scopeDigest = await canonicalDigest(scopeBody);
  const unit = String(scope.expected_item_unit);
  const observation = {
    ...scopeBody,
    observed_items: unit === "source_query" ? 1 : rawCount,
    raw_page_count: input.capture.pages.length,
    raw_count: rawCount,
    structured_count: input.structuredCount,
    status: "SUCCESS" as const,
    error: null,
    pagination_exhausted: true as const,
    discovery_exhausted: true as const,
    source_request_digest: await canonicalDigest(input.capture.initialRequest),
    raw_manifest_digest: input.capture.rawManifestDigest,
    raw_digest: input.capture.rawDigest,
    structured_digest: input.structuredDigest,
    structured_generation: input.runId,
    scope_digest: scopeDigest,
    run_id: input.runId,
    checked_at: input.checkedAt,
    extra_digests: {
      acquisition_collection_manifest_file_digest: input.capture.manifestFileDigest,
      acquisition_collection_digest: input.capture.collectionDigest,
      acquisition_terminal_chain_digest: input.capture.terminalChainDigest,
    },
  };
  return {
    ...observation,
    observation_digest: await canonicalDigest(observation),
  };
}

export function receiptFromIssued(issued: IssuedRecord): CollectionReceiptV2 {
  const claims = issued.claims;
  return {
    source: "jquants",
    dataset: claims.dataset,
    segment_id: claims.segment_id,
    segment_start: claims.segment_start,
    segment_end: claims.segment_end,
    expected_scope: claims.expected_scope,
    expected_items: claims.expected_items,
    observed_items: claims.observed_items,
    raw_page_count: claims.raw_page_count,
    raw_row_count: claims.raw_count,
    structured_row_count: claims.structured_count,
    pagination_exhausted: true,
    digests: issued.envelope,
    run_id: claims.run_id,
    status: "SUCCESS",
    error: null,
    checked_at: claims.checked_at,
  };
}

export async function commitReceipt(
  env: ReceiptAuthorityEnv,
  operationId: string,
  receipt: CollectionReceiptV2,
): Promise<string> {
  const receiptDigest = await canonicalDigest(receipt);
  await env.DB.prepare(
    `INSERT OR IGNORE INTO collection_receipts
     (source,dataset,segment_id,segment_start,segment_end,expected_scope,
      expected_items,observed_items,raw_page_count,raw_row_count,
      structured_row_count,pagination_exhausted,digests_json,run_id,status,
      error,checked_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'SUCCESS',NULL,?)`,
  ).bind(
    receipt.source,
    receipt.dataset,
    receipt.segment_id,
    receipt.segment_start,
    receipt.segment_end,
    JSON.stringify(receipt.expected_scope),
    receipt.expected_items,
    receipt.observed_items,
    receipt.raw_page_count,
    receipt.raw_row_count,
    receipt.structured_row_count,
    1,
    JSON.stringify(receipt.digests),
    receipt.run_id,
    receipt.checked_at,
  ).run();
  const row = await env.DB.prepare(
    `SELECT source,dataset,segment_id,segment_start,segment_end,expected_scope,
            expected_items,observed_items,raw_page_count,raw_row_count,
            structured_row_count,pagination_exhausted,digests_json,run_id,
            status,error,checked_at
     FROM collection_receipts
     WHERE source=? AND dataset=? AND segment_id=? AND run_id=?`,
  ).bind(
    receipt.source,
    receipt.dataset,
    receipt.segment_id,
    receipt.run_id,
  ).first<Record<string, unknown>>();
  if (row === null) throw new Error("receipt D1 insert disappeared");
  const restored: CollectionReceiptV2 = {
    source: String(row.source) as "jquants",
    dataset: String(row.dataset),
    segment_id: String(row.segment_id),
    segment_start: String(row.segment_start),
    segment_end: String(row.segment_end),
    expected_scope: JSON.parse(String(row.expected_scope)) as Record<string, JsonValue>,
    expected_items: row.expected_items === null ? null : Number(row.expected_items),
    observed_items: Number(row.observed_items),
    raw_page_count: Number(row.raw_page_count),
    raw_row_count: Number(row.raw_row_count),
    structured_row_count: Number(row.structured_row_count),
    pagination_exhausted: Boolean(row.pagination_exhausted) as true,
    digests: JSON.parse(String(row.digests_json)) as CollectionReceiptV2["digests"],
    run_id: Number(row.run_id),
    status: String(row.status) as "SUCCESS",
    error: row.error === null ? null : String(row.error) as never,
    checked_at: String(row.checked_at),
  };
  if (canonicalJson(restored) !== canonicalJson(receipt)) {
    throw new Error("persisted receipt differs from signed authority result");
  }
  await env.DB.prepare(
    `UPDATE receipt_authority_operations
     SET state='RECEIPT_COMMITTED',receipt_digest=?,updated_at=?
     WHERE operation_id=? AND state IN ('STRUCTURED_COMMITTED','RECEIPT_COMMITTED')`,
  ).bind(receiptDigest, new Date().toISOString(), operationId).run();
  return receiptDigest;
}
