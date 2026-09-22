import {
  canonicalDigest,
  canonicalJson,
} from "../../ingestion-secrets/src/jquants_acquisition_registry";
import { requireProductObject } from "./product_materialization";
import { base64ToBytes, isPlainObject, sha256Digest } from "./canonical";

import type { DatasetSpec } from "../../ingestion-premium/src/catalog";
import {
  capturedOfficialCalendarDescriptor,
  type Capture,
} from "./raw_capture";
import { authorityInstanceScope } from "./authority_instance";
import type {
  CollectionReceiptV3,
  JsonValue,
  ReceiptAuthorityEnv,
  ReceiptAuthorityIssuedRecord,
  GovernedSource,
  SegmentGrain,
  UnsignedReceiptClaimsV3,
} from "./types";

export function canonicalReceiptExpectedScope(spec: DatasetSpec, initial: {
  segment_start: string;
  segment_end: string;
  segment_grain: SegmentGrain;
}): {
  scope: Record<string, JsonValue>;
  expectedItems: number | null;
} {
  const eventDriven = spec.coverage.expected_frequency === "event_driven";
  const jsda = spec.id.startsWith("jsda_");
  return {
    scope: {
      coverage_mode: spec.coverage.coverage_mode,
      expected_frequency: spec.coverage.expected_frequency,
      expected_item_unit: jsda
        ? "official_archive_file"
        : eventDriven ? "source_event" : "source_query",
      segment_end: initial.segment_end,
      segment_start: initial.segment_start,
      universe_rule: spec.coverage.universe_rule,
      segment_granularity: initial.segment_grain,
    },
    expectedItems: eventDriven && !jsda ? null : 1,
  };
}

const COVERAGE_POLICY_VERSION = "collection-coverage/v3";
const EXPECTED_EMPTY_WITH_EVIDENCE = "EXPECTED_EMPTY_WITH_EVIDENCE";

function extraDigest(
  digests: CollectionReceiptV3["digests"],
  name: string,
): string | undefined {
  const extra = digests.extra_digests;
  if (!extra || typeof extra !== "object") return undefined;
  const value = extra[name];
  return typeof value === "string" ? value : undefined;
}

/** COMPLETE only for a jquants V3 signed SUCCESS that already proved exhaustion
 * and raw/structured reconciliation. Does not invent a planned coverage row. */
export function receiptEligibleForCoverageComplete(
  receipt: CollectionReceiptV3,
): boolean {
  if (receipt.source !== "jquants") return false;
  if (receipt.status !== "SUCCESS" || receipt.error !== null) return false;
  if (receipt.pagination_exhausted !== true) return false;
  if (
    receipt.digests.eligibility !== "TRUSTED_COLLECTION" ||
    receipt.digests.issuer_class !== "SignedReceiptAuthority"
  ) {
    return false;
  }
  if (!Number.isInteger(receipt.raw_page_count) || receipt.raw_page_count < 1) {
    return false;
  }
  if (receipt.raw_row_count !== receipt.structured_row_count) return false;
  if (
    receipt.expected_items !== null &&
    receipt.observed_items !== receipt.expected_items
  ) {
    return false;
  }
  const emptyEvidence = extraDigest(receipt.digests, EXPECTED_EMPTY_WITH_EVIDENCE);
  const emptyOk = typeof emptyEvidence === "string" &&
    /^sha256:[0-9a-f]{64}$/.test(emptyEvidence);
  if (receipt.raw_row_count < 1 && !emptyOk) return false;
  return true;
}

export async function measuredClaims(input: {
  env: ReceiptAuthorityEnv;
  requestDigest: string;
  runId: number;
  spec: DatasetSpec;
  segmentGrain: SegmentGrain;
  capture: Capture;
  structuredCount: number;
  structuredDigest: string;
  productManifestDigest: string;
  artifactKey: string;
  artifactByteCount: number;
  manifestKey: string;
  manifestByteCount: number;
  naturalKeyDigest: string;
  contractId: string;
  checkedAt: string;
}): Promise<UnsignedReceiptClaimsV3> {
  if (!input.capture.paginationExhausted || !input.capture.discoveryExhausted) {
    throw new Error("receipt capture did not independently prove exhaustion");
  }
  const authorityScope = await authorityInstanceScope(input.env);
  const { scope, expectedItems } = canonicalReceiptExpectedScope(input.spec, {
    segment_start: input.capture.initialRequest.segment_start,
    segment_end: input.capture.initialRequest.segment_end,
    segment_grain: input.segmentGrain,
  });
  const rawCount = input.capture.pages.reduce((total, page) => total + page.rowCount, 0);
  if (rawCount !== input.structuredCount) {
    throw new Error("raw and structured counts do not reconcile");
  }
  if (input.spec.coverage.policy_version !== "collection-coverage/v3") {
    throw new Error("receipt authority accepts only Coverage V3");
  }
  const scopeBody = {
    environment: authorityScope.environment,
    authority_instance_digest: authorityScope.authorityInstanceDigest,
    coverage_policy_version: "collection-coverage/v3" as const,
    source: (input.spec.id.startsWith("jsda_") ? "jsda" : "jquants") as GovernedSource,
    contract_id: input.contractId,
    dataset: input.spec.id,
    segment_id: input.capture.initialRequest.segment_id,
    segment_start: input.capture.initialRequest.segment_start,
    segment_end: input.capture.initialRequest.segment_end,
    expected_scope: scope,
    expected_items: expectedItems,
  };
  const scopeDigest = await canonicalDigest(scopeBody);
  const unit = String(scope.expected_item_unit);
  const officialCalendarEvidence = capturedOfficialCalendarDescriptor(
    input.capture.officialCalendarEvidence,
  );
  const officialCalendarDigests: Record<string, string> =
    input.capture.officialCalendarEvidence === null
    ? {}
    : {
      official_calendar_evidence_digest: await canonicalDigest(
        officialCalendarEvidence!,
      ),
      official_calendar_raw_body_digest:
        input.capture.officialCalendarEvidence.digest,
      official_calendar_query_digest:
        input.capture.officialCalendarEvidence.calendarQueryDigest,
      official_business_dates_digest:
        input.capture.officialCalendarEvidence.businessDatesDigest,
      official_calendar_binding_digest:
        input.capture.officialCalendarEvidence.bindingDigest,
    };
  const observation = {
    ...scopeBody,
    observed_items: unit === "source_query" ? 1 : rawCount,
    raw_page_count: input.capture.pages.length,
    raw_count: rawCount,
    structured_count: input.structuredCount,
    status: "SUCCESS" as const,
    error: null,
    pagination_exhausted: input.capture.paginationExhausted,
    discovery_exhausted: input.capture.discoveryExhausted,
    receipt_issue_digest: input.requestDigest,
    artifact_key: input.artifactKey,
    artifact_byte_count: input.artifactByteCount,
    manifest_key: input.manifestKey,
    manifest_byte_count: input.manifestByteCount,
    raw_manifest_key: input.capture.rawManifestKey,
    raw_manifest_byte_count: input.capture.rawManifestByteCount,
    raw_byte_count: input.capture.pages.reduce((total, page) => total + page.size, 0),
    natural_key_digest: input.naturalKeyDigest,
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
      product_artifact_digest: input.structuredDigest,
      product_manifest_digest: input.productManifestDigest,
      ...officialCalendarDigests,
    },
  };
  return {
    ...observation,
    observation_digest: await canonicalDigest(observation),
  };
}

export function receiptFromIssued(
  issued: ReceiptAuthorityIssuedRecord,
): CollectionReceiptV3 {
  const claims = issued.claims;
  return {
    source: claims.source,
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
  receipt: CollectionReceiptV3,
): Promise<string> {
  const receiptDigest = await canonicalDigest(receipt);
  const operation = await env.DB.prepare(
    `SELECT run_id,dataset,segment_id,state,raw_manifest_key,
            raw_manifest_digest,raw_page_count,raw_row_count,raw_bytes,
            structured_manifest_key,structured_digest,structured_storage
       FROM receipt_authority_operations WHERE operation_id=?`,
  ).bind(operationId).first<{
    run_id: number;
    dataset: string;
    segment_id: string;
    state: string;
    raw_manifest_key: string;
    raw_manifest_digest: string;
    raw_page_count: number;
    raw_row_count: number;
    raw_bytes: number;
    structured_manifest_key: string;
    structured_digest: string;
    structured_storage: "legacy_d1" | "r2_scratch_v1";
  }>();
  if (
    operation === null ||
    (operation.state !== "STRUCTURED_COMMITTED" &&
      operation.state !== "RECEIPT_COMMITTED") ||
    operation.run_id !== receipt.run_id || operation.dataset !== receipt.dataset ||
    operation.segment_id !== receipt.segment_id ||
    operation.raw_page_count !== receipt.raw_page_count ||
    operation.raw_row_count !== receipt.raw_row_count ||
    operation.raw_manifest_digest !== receipt.digests.raw_manifest_digest ||
    operation.structured_digest !== receipt.digests.structured_digest ||
    !operation.structured_manifest_key ||
    !operation.raw_manifest_key || operation.raw_bytes <= 0
  ) throw new Error("receipt commit is not bound to the measured run/raw evidence");
  const product = await env.DB.prepare(
    `SELECT operation_id,run_id,source,dataset,segment_id,artifact_key,
            artifact_digest,artifact_body,row_count,byte_count,manifest_key,manifest_digest,
            raw_manifest_key,raw_manifest_digest,raw_page_count,raw_row_count,
            raw_bytes,committed_at
       FROM receipt_product_materializations WHERE operation_id=?`,
  ).bind(operationId).first<Record<string, unknown>>();
  if (
    product === null || product.operation_id !== operationId ||
    product.run_id !== receipt.run_id || product.source !== receipt.source ||
    product.dataset !== receipt.dataset || product.segment_id !== receipt.segment_id ||
    product.artifact_digest !== receipt.digests.structured_digest ||
    typeof product.artifact_body !== "string" ||
    product.row_count !== receipt.structured_row_count ||
    product.manifest_key !== operation.structured_manifest_key ||
    product.raw_manifest_key !== operation.raw_manifest_key ||
    product.raw_manifest_digest !== operation.raw_manifest_digest ||
    product.raw_page_count !== receipt.raw_page_count ||
    product.raw_row_count !== receipt.raw_row_count ||
    product.raw_bytes !== operation.raw_bytes ||
    product.committed_at !== receipt.checked_at ||
    typeof product.artifact_key !== "string" || !product.artifact_key ||
    typeof product.manifest_digest !== "string" || !product.manifest_digest ||
    typeof product.byte_count !== "number" || product.byte_count <= 0
  ) throw new Error("signed digest is not bound to the product materialization");
  if (operation.structured_storage === "r2_scratch_v1") {
    const measurement = await env.DB.prepare(
      `SELECT artifact_digest,row_count,natural_key_digest,measured_at
       FROM receipt_r2_reconciliations WHERE operation_id=?`,
    ).bind(operationId).first<Record<string, unknown>>();
    const body = base64ToBytes(receipt.digests.signed_body_b64);
    const claims: unknown = JSON.parse(new TextDecoder().decode(body));
    if (!isPlainObject(claims) ||
        await sha256Digest(body) !== receipt.digests.body_digest ||
        measurement === null ||
        measurement.artifact_digest !== product.artifact_digest ||
        measurement.row_count !== product.row_count ||
        measurement.measured_at !== product.committed_at ||
        measurement.natural_key_digest !== claims.natural_key_digest ||
        claims.structured_digest !== product.artifact_digest ||
        claims.structured_count !== product.row_count ||
        claims.checked_at !== product.committed_at) {
      throw new Error("receipt commit lacks matching R2 reconciliation evidence");
    }
  } else if (operation.structured_storage !== "legacy_d1") {
    throw new Error("unknown receipt structured storage mode");
  }
  if (product.artifact_body.length === 0 || operation.structured_storage === "r2_scratch_v1") {
    await requireProductObject(env.STRUCTURED_BUCKET, product.artifact_key,
      product.byte_count, String(product.artifact_digest));
  }
  const successDetail = canonicalJson({
    schema_version: "receipt-authority-ingestion-result/v1",
    operation_id: operationId,
    receipt_digest: receiptDigest,
    structured_digest: receipt.digests.structured_digest,
    product_artifact_key: product.artifact_key,
    raw_manifest_digest: operation.raw_manifest_digest,
  });
  const coverageDetail = canonicalJson({
    reason: "receipt reconciled",
    event_zero: receipt.observed_items === 0,
  });
  const promoteCoverage = receiptEligibleForCoverageComplete(receipt);
  await env.DB.batch([
    // Acquisition no longer depends on a duplicate Premium write. Publish
    // operation-measured watermarks atomically with the receipt, including
    // recovery; older backfills/replays must not move them backwards.
    env.DB.prepare(
      `INSERT INTO ingestion_watermarks
         (dataset,last_event_date,last_ingested_at,last_export_cursor)
       ${operation.structured_storage === "r2_scratch_v1"
         ? `SELECT ?,substr(last_event_time,1,10),?,NULL
              FROM receipt_r2_reconciliations WHERE operation_id=?`
         : `SELECT ?,substr(MAX(event_time),1,10),?,
                   (SELECT MAX(change_seq) FROM ingestion_change_log WHERE dataset=?)
              FROM receipt_authority_structured_rows WHERE operation_id=?
            HAVING COUNT(*) > 0`}
       ON CONFLICT(dataset) DO UPDATE SET
         last_event_date=CASE
           WHEN ingestion_watermarks.last_event_date IS NULL
             OR excluded.last_event_date > ingestion_watermarks.last_event_date
           THEN excluded.last_event_date ELSE ingestion_watermarks.last_event_date END,
         last_ingested_at=CASE
           WHEN ingestion_watermarks.last_ingested_at IS NULL
             OR julianday(excluded.last_ingested_at) > julianday(ingestion_watermarks.last_ingested_at)
           THEN excluded.last_ingested_at ELSE ingestion_watermarks.last_ingested_at END,
         last_export_cursor=${operation.structured_storage === "r2_scratch_v1"
           ? "NULL"
           : "COALESCE(excluded.last_export_cursor,ingestion_watermarks.last_export_cursor)"}`,
    ).bind(...(operation.structured_storage === "r2_scratch_v1"
      ? [receipt.dataset, receipt.checked_at, operationId]
      : [receipt.dataset, receipt.checked_at, receipt.dataset, operationId])),
    env.DB.prepare(
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
    ),
    env.DB.prepare(
      `INSERT OR IGNORE INTO raw_retention_manifests
       (dataset,run_id,manifest_key,page_count,row_count,raw_bytes,data_digest,
        completeness,created_at)
       VALUES (?,?,?,?,?,?,?,'ACQUIRED',?)`,
    ).bind(
      receipt.dataset,
      receipt.run_id,
      operation.raw_manifest_key,
      operation.raw_page_count,
      operation.raw_row_count,
      operation.raw_bytes,
      operation.raw_manifest_digest,
      receipt.checked_at,
    ),
    env.DB.prepare(
      `UPDATE receipt_authority_operations
       SET state='RECEIPT_COMMITTED',receipt_digest=?,updated_at=?
       WHERE operation_id=? AND state IN ('STRUCTURED_COMMITTED','RECEIPT_COMMITTED')`,
    ).bind(receiptDigest, receipt.checked_at, operationId),
    env.DB.prepare(
      `UPDATE ingestion_run_log SET status='SUCCESS',detail=?
       WHERE id=? AND authority_operation_id=? AND status IN ('RUNNING','SUCCESS')`,
    ).bind(successDetail, receipt.run_id, operationId),
    ...(promoteCoverage
      ? [env.DB.prepare(
        `UPDATE coverage_segments
            SET status='COMPLETE',
                receipt_run_id=?,
                evaluated_at=?,
                detail_json=?
          WHERE source=?
            AND dataset=?
            AND segment_id=?
            AND policy_version=?
            AND segment_start=?
            AND segment_end=?
            AND expected_scope=?
            AND (
              (expected_items IS NULL AND ? IS NULL)
              OR expected_items = ?
            )
            AND status IN ('UNKNOWN','PARTIAL','STALE','COMPLETE')
            AND (receipt_run_id IS NULL OR receipt_run_id=?)`,
      ).bind(
        receipt.run_id,
        receipt.checked_at,
        coverageDetail,
        receipt.source,
        receipt.dataset,
        receipt.segment_id,
        COVERAGE_POLICY_VERSION,
        receipt.segment_start,
        receipt.segment_end,
        canonicalJson(receipt.expected_scope),
        receipt.expected_items,
        receipt.expected_items,
        receipt.run_id,
      )]
      : []),
  ]);
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
  const restored: CollectionReceiptV3 = {
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
    digests: JSON.parse(String(row.digests_json)) as CollectionReceiptV3["digests"],
    run_id: Number(row.run_id),
    status: String(row.status) as "SUCCESS",
    error: row.error === null ? null : String(row.error) as never,
    checked_at: String(row.checked_at),
  };
  if (canonicalJson(restored) !== canonicalJson(receipt)) {
    throw new Error("persisted receipt differs from signed authority result");
  }
  const raw = await env.DB.prepare(
    `SELECT dataset,run_id,manifest_key,page_count,row_count,raw_bytes,
            data_digest,completeness,created_at
       FROM raw_retention_manifests WHERE dataset=? AND run_id=?`,
  ).bind(receipt.dataset, receipt.run_id).first<Record<string, unknown>>();
  if (
    raw === null || raw.dataset !== receipt.dataset || raw.run_id !== receipt.run_id ||
    raw.manifest_key !== operation.raw_manifest_key ||
    raw.page_count !== operation.raw_page_count ||
    raw.row_count !== operation.raw_row_count || raw.raw_bytes !== operation.raw_bytes ||
    raw.data_digest !== operation.raw_manifest_digest ||
    raw.completeness !== "ACQUIRED" || raw.created_at !== receipt.checked_at
  ) throw new Error("persisted raw retention evidence differs from signed receipt");
  const committed = await env.DB.prepare(
    `SELECT operation.state,operation.receipt_digest,run.status,run.detail
       FROM receipt_authority_operations AS operation
       JOIN ingestion_run_log AS run ON run.id=operation.run_id
      WHERE operation.operation_id=? AND run.authority_operation_id=?`,
  ).bind(operationId, operationId).first<Record<string, unknown>>();
  if (
    committed === null || committed.state !== "RECEIPT_COMMITTED" ||
    committed.receipt_digest !== receiptDigest || committed.status !== "SUCCESS" ||
    committed.detail !== successDetail
  ) throw new Error("receipt run finalization did not commit exactly");
  return receiptDigest;
}
