/**
 * Read-only receipt-product input descriptor. DB metadata only; never
 * publishes, never reads R2, never selects artifact_body / fact rows.
 */
import controlledPilot from "../../../../specs/ready/controlled_pilot_v1.generated.json";
import {
  canonicalDigest,
  canonicalJson,
  exactKeys,
  isPlainObject,
  isSha256,
} from "../../receipt-evidence-authority/src/canonical";
import { catalogProjectionRows } from "./catalog";
import {
  COVERAGE_POLICY_VERSION,
  pinnedReceiptRegistryForEnvironment,
  requireCanonicalUtc,
  trustedComplete,
  type ReceiptVerifyRegistry,
} from "./ops_projection_policy";

export const RECEIPT_PRODUCT_INPUT_REQUEST =
  "receipt-product-input-request/v1" as const;
export const RECEIPT_PRODUCT_INPUT_SET =
  "receipt-product-input-set/v1" as const;

const MAX_BODY_BYTES = 64 * 1024;
export const RECEIPT_PRODUCT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024;
const MAX_RESPONSE_BYTES = RECEIPT_PRODUCT_MAX_RESPONSE_BYTES;
const MAX_SEGMENTS = 128;
const MAX_QUERIES = 24;
const REQUIRED_TABLES = [
  "coverage_segments",
  "collection_receipts",
  "receipt_product_materializations",
  "receipt_authority_operations",
  "receipt_authority_requests",
  "receipt_authority_structured_rows",
] as const;

const PROFILE_ID = controlledPilot.profile_id;
const PROFILE_DIGEST = controlledPilot.profile_digest;
const CLOSURE_DIGEST = controlledPilot.dependency_closure_digest;
const PROFILE_DATASETS = new Set(
  Array.isArray(controlledPilot.dataset_ids)
    ? controlledPilot.dataset_ids.filter((id): id is string =>
      typeof id === "string" && id.length > 0
    )
    : [],
);

if (
  typeof PROFILE_ID !== "string" ||
  PROFILE_ID.length === 0 ||
  !isSha256(PROFILE_DIGEST) ||
  !isSha256(CLOSURE_DIGEST) ||
  PROFILE_DATASETS.size === 0 ||
  controlledPilot.coverage_policy_version !== COVERAGE_POLICY_VERSION
) {
  throw new Error("controlled pilot profile pins are invalid");
}

const REQUEST_KEYS = [
  "schema_version",
  "profile_id",
  "profile_digest",
  "dependency_closure_digest",
  "segments",
] as const;
const REQUEST_KEYS_WITH_DIGEST = [
  ...REQUEST_KEYS,
  "expected_current_digest",
] as const;
const SEGMENT_KEYS = ["dataset", "segment_id"] as const;

export type ReceiptProductInputEnv = {
  DB: D1Database;
  OPS_PROJECTION_ENVIRONMENT?: string;
};

export type HoldReason =
  | "MISSING_TABLE"
  | "MISSING_ROW"
  | "COVERAGE_INCOMPLETE"
  | "PENDING_REGISTRY"
  | "UNTRUSTED_CHAIN"
  | "UNFINALIZED_REQUEST"
  | "REFERENCE_CHANGED"
  | "READ_BUDGET"
  | "READ_FAILURE";

export type HoldSelector = { dataset: string; segment_id: string };

type ClosedRequest = {
  segments: Array<{ dataset: string; segment_id: string }>;
  expected_current_digest?: string;
};

type CoverageRef = {
  source: string;
  dataset: string;
  segment_id: string;
  policy_version: string;
  segment_start: string;
  segment_end: string;
  expected_scope: unknown;
  expected_items: number | null;
  status: string;
  receipt_run_id: number;
  evaluated_at: string;
};

type CatalogRow = ReturnType<typeof catalogProjectionRows>[number];
type SourceDb = D1Database | D1DatabaseSession;

class HoldError extends Error {
  readonly reason: HoldReason;
  readonly selector: HoldSelector | null;
  constructor(reason: HoldReason, selector: HoldSelector | null = null) {
    super(reason);
    this.name = "HoldError";
    this.reason = reason;
    this.selector = selector;
  }
}

function parseJsonObject(raw: unknown): unknown {
  if (raw && typeof raw === "object") return raw;
  if (typeof raw !== "string") return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

function requireInt(value: unknown): number | null {
  if (typeof value === "bigint") {
    const asNumber = Number(value);
    return Number.isSafeInteger(asNumber) ? asNumber : null;
  }
  if (typeof value === "number" && Number.isSafeInteger(value)) return value;
  if (typeof value === "string" && /^-?\d+$/.test(value)) {
    const asNumber = Number(value);
    return Number.isSafeInteger(asNumber) ? asNumber : null;
  }
  return null;
}

function environmentOf(
  env: ReceiptProductInputEnv,
): "staging" | "production" | null {
  return env.OPS_PROJECTION_ENVIRONMENT === "staging" ||
      env.OPS_PROJECTION_ENVIRONMENT === "production"
    ? env.OPS_PROJECTION_ENVIRONMENT
    : null;
}

function sourceSession(db: D1Database): SourceDb {
  if (typeof db.withSession === "function") {
    return db.withSession("first-primary");
  }
  return db;
}

function sessionBookmark(db: SourceDb): string | null {
  if ("getBookmark" in db && typeof db.getBookmark === "function") {
    return db.getBookmark();
  }
  return null;
}

type QueryBudget = { queries: number };

async function sourceAll<T>(
  db: SourceDb,
  budget: QueryBudget,
  sql: string,
  binds: unknown[] = [],
): Promise<T[]> {
  budget.queries += 1;
  if (budget.queries > MAX_QUERIES) throw new HoldError("READ_BUDGET");
  const result = await db.prepare(sql).bind(...binds).all<T>();
  if (!result || !Array.isArray(result.results) || result.success !== true) {
    throw new HoldError("READ_FAILURE");
  }
  return result.results;
}

async function sourceFirst<T>(
  db: SourceDb,
  budget: QueryBudget,
  sql: string,
  binds: unknown[] = [],
): Promise<T | null> {
  budget.queries += 1;
  if (budget.queries > MAX_QUERIES) throw new HoldError("READ_BUDGET");
  return (await db.prepare(sql).bind(...binds).first<T>()) ?? null;
}

function coverageIdentity(row: CoverageRef): string {
  return canonicalJson({
    source: row.source,
    dataset: row.dataset,
    segment_id: row.segment_id,
    policy_version: row.policy_version,
    segment_start: row.segment_start,
    segment_end: row.segment_end,
    expected_scope: row.expected_scope,
    expected_items: row.expected_items,
    status: row.status,
    receipt_run_id: row.receipt_run_id,
    evaluated_at: row.evaluated_at,
  });
}

function selectorOf(dataset: unknown, segmentId: unknown): HoldSelector | null {
  return typeof dataset === "string" && typeof segmentId === "string"
    ? { dataset, segment_id: segmentId }
    : null;
}

function missingSelector(
  wanted: Array<{ dataset: string; segment_id: string }>,
  present: ReadonlyArray<{ dataset?: unknown; segment_id?: unknown }>,
): HoldSelector {
  const seen = new Set(
    present.map((row) => `${row.dataset}\0${row.segment_id}`),
  );
  const row = wanted.find((item) => !seen.has(`${item.dataset}\0${item.segment_id}`))
    ?? wanted[0]!;
  return { dataset: row.dataset, segment_id: row.segment_id };
}

function asCoverageRef(
  row: Record<string, unknown>,
  catalogById: Map<string, CatalogRow>,
): CoverageRef | null {
  const source = typeof row.source === "string" ? row.source : "";
  const dataset = typeof row.dataset === "string" ? row.dataset : "";
  const segment = typeof row.segment_id === "string" ? row.segment_id : "";
  const policy = typeof row.policy_version === "string" ? row.policy_version : "";
  const start = typeof row.segment_start === "string" ? row.segment_start : "";
  const end = typeof row.segment_end === "string" ? row.segment_end : "";
  const evaluated = typeof row.evaluated_at === "string" ? row.evaluated_at : "";
  const status = typeof row.status === "string" ? row.status : "";
  const runId = requireInt(row.receipt_run_id);
  const catalog = catalogById.get(dataset);
  const expectedItems = row.expected_items == null
    ? null
    : requireInt(row.expected_items);
  const expectedScope = parseJsonObject(row.expected_scope);
  if (
    !source || !dataset || !segment || !start || !end || !evaluated ||
    policy !== COVERAGE_POLICY_VERSION ||
    catalog == null ||
    catalog.source !== source ||
    catalog.coverage.policy_version !== COVERAGE_POLICY_VERSION ||
    !PROFILE_DATASETS.has(dataset) ||
    runId === null || runId < 0 ||
    (row.expected_items != null && expectedItems === null) ||
    expectedScope === null
  ) {
    return null;
  }
  return {
    source,
    dataset,
    segment_id: segment,
    policy_version: policy,
    segment_start: start,
    segment_end: end,
    expected_scope: expectedScope,
    expected_items: expectedItems,
    status,
    receipt_run_id: runId,
    evaluated_at: evaluated,
  };
}

export function parseReceiptProductInputRequest(
  value: unknown,
): { ok: true; request: ClosedRequest } | { ok: false; error: string } {
  if (!isPlainObject(value)) return { ok: false, error: "invalid request" };
  const hasExpected = Object.prototype.hasOwnProperty.call(
    value,
    "expected_current_digest",
  );
  if (
    !exactKeys(
      value,
      hasExpected ? REQUEST_KEYS_WITH_DIGEST : REQUEST_KEYS,
    )
  ) {
    return { ok: false, error: "unknown field" };
  }
  if (
    value.schema_version !== RECEIPT_PRODUCT_INPUT_REQUEST ||
    value.profile_id !== PROFILE_ID ||
    value.profile_digest !== PROFILE_DIGEST ||
    value.dependency_closure_digest !== CLOSURE_DIGEST
  ) {
    return { ok: false, error: "profile pin mismatch" };
  }
  if (hasExpected && !isSha256(value.expected_current_digest)) {
    return { ok: false, error: "invalid digest" };
  }
  if (!Array.isArray(value.segments)) {
    return { ok: false, error: "invalid request" };
  }
  if (value.segments.length < 1 || value.segments.length > MAX_SEGMENTS) {
    return { ok: false, error: "segments out of range" };
  }
  const seen = new Set<string>();
  const segments: Array<{ dataset: string; segment_id: string }> = [];
  for (const item of value.segments) {
    if (!isPlainObject(item) || !exactKeys(item, SEGMENT_KEYS)) {
      return { ok: false, error: "unknown field" };
    }
    const dataset = item.dataset;
    const segmentId = item.segment_id;
    if (typeof dataset !== "string" || typeof segmentId !== "string") {
      return { ok: false, error: "invalid request" };
    }
    if (!PROFILE_DATASETS.has(dataset) || segmentId.length === 0) {
      return { ok: false, error: "dataset not in profile" };
    }
    const key = `${dataset}\0${segmentId}`;
    if (seen.has(key)) return { ok: false, error: "duplicate selector" };
    seen.add(key);
    segments.push({ dataset, segment_id: segmentId });
  }
  return {
    ok: true,
    request: {
      segments,
      expected_current_digest: hasExpected
        ? String(value.expected_current_digest)
        : undefined,
    },
  };
}

export type BoundedBody =
  | { ok: true; bytes: Uint8Array }
  | { ok: false; error: "body too large" | "body read failed" };

export async function readBoundedBody(
  request: Request,
  maxBytes = MAX_BODY_BYTES,
): Promise<BoundedBody> {
  const declared = Number(request.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > maxBytes) {
    return { ok: false, error: "body too large" };
  }
  const reader = request.body?.getReader();
  if (!reader) return { ok: true, bytes: new Uint8Array() };
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        try {
          await reader.cancel();
        } catch {
          /* already closed */
        }
        return { ok: false, error: "body too large" };
      }
      chunks.push(value);
    }
  } catch {
    try {
      await reader.cancel();
    } catch {
      /* already closed */
    }
    return { ok: false, error: "body read failed" };
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, bytes };
}

function nowUtc(): string {
  const canonical = requireCanonicalUtc(
    new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
  );
  if (canonical === null) throw new HoldError("READ_FAILURE");
  return canonical;
}

function rowKey(
  source: unknown,
  dataset: unknown,
  segment: unknown,
  runId: unknown,
): string {
  return `${source}\0${dataset}\0${segment}\0${runId}`;
}

function requireMetaBudget(
  bytes: number,
  selector: HoldSelector | null = null,
): void {
  if (bytes > MAX_RESPONSE_BYTES) throw new HoldError("READ_BUDGET", selector);
}

async function loadCoverage(
  db: SourceDb,
  budget: QueryBudget,
  selectors: Array<{ dataset: string; segment_id: string }>,
  catalogById: Map<string, CatalogRow>,
): Promise<CoverageRef[]> {
  const rows = await sourceAll<Record<string, unknown>>(
    db,
    budget,
    `WITH wanted AS (
        SELECT json_extract(value, '$.dataset') AS dataset,
               json_extract(value, '$.segment_id') AS segment_id
          FROM json_each(?)
      ),
      selected AS (
        SELECT coverage.source, coverage.dataset, coverage.segment_id,
               coverage.policy_version, coverage.segment_start, coverage.segment_end,
               coverage.expected_scope, coverage.expected_items, coverage.status,
               coverage.receipt_run_id, coverage.evaluated_at,
               length(CAST(COALESCE(coverage.expected_scope, '') AS BLOB)) AS scope_bytes
          FROM coverage_segments AS coverage
          JOIN wanted
            ON coverage.dataset = wanted.dataset
           AND coverage.segment_id = wanted.segment_id
         WHERE coverage.policy_version = ?
      ),
      budgeted AS (
        SELECT *, SUM(scope_bytes) OVER () AS total_scope_bytes
          FROM selected
      )
      SELECT source, dataset, segment_id, policy_version, segment_start, segment_end,
             expected_items, status, receipt_run_id, evaluated_at, scope_bytes,
             total_scope_bytes,
             CASE WHEN total_scope_bytes > ? THEN NULL ELSE expected_scope END AS expected_scope
        FROM budgeted
       ORDER BY dataset, segment_id`,
    [JSON.stringify(selectors), COVERAGE_POLICY_VERSION, MAX_RESPONSE_BYTES],
  );
  if (rows.length !== selectors.length) {
    throw new HoldError("MISSING_ROW", missingSelector(selectors, rows));
  }
  const total = requireInt(rows[0]?.total_scope_bytes) ?? Number.POSITIVE_INFINITY;
  if (total > MAX_RESPONSE_BYTES) {
    const over = rows.find((row) =>
      (requireInt(row.scope_bytes) ?? Number.POSITIVE_INFINITY) > 0
    );
    throw new HoldError(
      "READ_BUDGET",
      selectorOf(over?.dataset, over?.segment_id),
    );
  }
  const wanted = new Set(selectors.map((item) => `${item.dataset}\0${item.segment_id}`));
  const refs: CoverageRef[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    const selector = selectorOf(row.dataset, row.segment_id);
    if (row.status !== "COMPLETE") {
      throw new HoldError("COVERAGE_INCOMPLETE", selector);
    }
    const ref = asCoverageRef(row, catalogById);
    if (!ref) throw new HoldError("UNTRUSTED_CHAIN", selector);
    const key = `${ref.dataset}\0${ref.segment_id}`;
    if (!wanted.has(key) || seen.has(key)) {
      throw new HoldError("UNTRUSTED_CHAIN", selector);
    }
    seen.add(key);
    refs.push(ref);
  }
  return refs;
}

function frozenWanted(refs: CoverageRef[]): string {
  return JSON.stringify(refs.map((row) => ({
    source: row.source,
    dataset: row.dataset,
    segment_id: row.segment_id,
    receipt_run_id: row.receipt_run_id,
  })));
}

async function describeFromDb(
  env: ReceiptProductInputEnv,
  request: ClosedRequest,
  environment: "staging" | "production",
  registry: ReceiptVerifyRegistry,
): Promise<{ body: Record<string, unknown>; digest: string }> {
  const catalogById = new Map(
    catalogProjectionRows().map((row) => [row.dataset_id, row]),
  );
  const db = sourceSession(env.DB);
  const budget: QueryBudget = { queries: 0 };
  const present = new Set(
    (await sourceAll<{ name: string }>(
      db,
      budget,
      `SELECT name FROM sqlite_master
        WHERE type='table' AND name IN (SELECT value FROM json_each(?))`,
      [JSON.stringify([...REQUIRED_TABLES, "ingestion_change_log"])],
    )).map((row) => row.name),
  );
  for (const name of REQUIRED_TABLES) {
    if (!present.has(name)) throw new HoldError("MISSING_TABLE");
  }

  const changeBefore = present.has("ingestion_change_log")
    ? requireInt(
      (await sourceFirst<{ change_seq: number | null }>(
        db,
        budget,
        "SELECT MAX(change_seq) AS change_seq FROM ingestion_change_log",
      ))?.change_seq,
    )
    : null;

  const frozen = await loadCoverage(db, budget, request.segments, catalogById);
  const wanted = frozenWanted(frozen);

  const receiptMeta = await sourceAll<Record<string, unknown>>(
    db,
    budget,
    `SELECT receipt.source, receipt.dataset, receipt.segment_id, receipt.run_id,
            length(CAST(COALESCE(receipt.digests_json, '') AS BLOB)) AS digest_bytes,
            length(CAST(COALESCE(receipt.expected_scope, '') AS BLOB)) AS scope_bytes
       FROM collection_receipts AS receipt
       JOIN json_each(?) AS wanted
         ON receipt.source = json_extract(wanted.value, '$.source')
        AND receipt.dataset = json_extract(wanted.value, '$.dataset')
        AND receipt.segment_id = json_extract(wanted.value, '$.segment_id')
        AND receipt.run_id = json_extract(wanted.value, '$.receipt_run_id')
      WHERE receipt.status = 'SUCCESS'`,
    [wanted],
  );
  if (receiptMeta.length !== frozen.length) {
    throw new HoldError("MISSING_ROW", missingSelector(frozen, receiptMeta));
  }
  let receiptBytes = 0;
  for (const row of receiptMeta) {
    const selector = selectorOf(row.dataset, row.segment_id);
    const size = (requireInt(row.digest_bytes) ?? Number.POSITIVE_INFINITY)
      + (requireInt(row.scope_bytes) ?? 0);
    receiptBytes += size;
    requireMetaBudget(size, selector);
  }
  requireMetaBudget(receiptBytes, selectorOf(receiptMeta[0]?.dataset, receiptMeta[0]?.segment_id));

  const receipts = await sourceAll<Record<string, unknown>>(
    db,
    budget,
    `SELECT receipt.source, receipt.dataset, receipt.segment_id, receipt.segment_start,
            receipt.segment_end, receipt.expected_scope, receipt.expected_items,
            receipt.observed_items, receipt.raw_page_count, receipt.raw_row_count,
            receipt.structured_row_count, receipt.pagination_exhausted,
            receipt.digests_json, receipt.run_id, receipt.status, receipt.error,
            receipt.checked_at
       FROM collection_receipts AS receipt
       JOIN json_each(?) AS wanted
         ON receipt.source = json_extract(wanted.value, '$.source')
        AND receipt.dataset = json_extract(wanted.value, '$.dataset')
        AND receipt.segment_id = json_extract(wanted.value, '$.segment_id')
        AND receipt.run_id = json_extract(wanted.value, '$.receipt_run_id')
      WHERE receipt.status = 'SUCCESS'`,
    [wanted],
  );
  if (receipts.length !== frozen.length) {
    throw new HoldError("MISSING_ROW", missingSelector(frozen, receipts));
  }

  const products = await sourceAll<Record<string, unknown>>(
    db,
    budget,
    `SELECT product.operation_id, product.run_id, product.source, product.dataset,
            product.segment_id, product.artifact_key, product.artifact_digest,
            product.row_count, product.byte_count, product.manifest_key,
            product.manifest_digest, product.raw_manifest_key,
            product.raw_manifest_digest, product.raw_page_count, product.raw_row_count,
            product.raw_bytes, product.committed_at
       FROM receipt_product_materializations AS product
       JOIN json_each(?) AS wanted
         ON product.source = json_extract(wanted.value, '$.source')
        AND product.dataset = json_extract(wanted.value, '$.dataset')
        AND product.segment_id = json_extract(wanted.value, '$.segment_id')
        AND product.run_id = json_extract(wanted.value, '$.receipt_run_id')`,
    [wanted],
  );
  if (products.length !== frozen.length) {
    throw new HoldError("MISSING_ROW", missingSelector(frozen, products));
  }

  const operations = await sourceAll<Record<string, unknown>>(
    db,
    budget,
    `SELECT operation.operation_id, operation.run_id, operation.environment,
            operation.source, operation.contract_id, operation.dataset,
            operation.segment_id, operation.segment_start, operation.segment_end,
            operation.state, operation.receipt_digest, operation.request_digest,
            operation.structured_manifest_key, operation.structured_digest,
            operation.raw_manifest_key, operation.raw_manifest_digest,
            operation.raw_page_count, operation.raw_row_count, operation.raw_bytes
       FROM receipt_authority_operations AS operation
       JOIN json_each(?) AS wanted
         ON operation.source = json_extract(wanted.value, '$.source')
        AND operation.dataset = json_extract(wanted.value, '$.dataset')
        AND operation.segment_id = json_extract(wanted.value, '$.segment_id')
        AND operation.run_id = json_extract(wanted.value, '$.receipt_run_id')
      WHERE operation.environment=?
        AND operation.state='RECEIPT_COMMITTED'`,
    [wanted, environment],
  );
  if (operations.length !== frozen.length) {
    throw new HoldError("MISSING_ROW", missingSelector(frozen, operations));
  }

  const requests = await sourceAll<Record<string, unknown>>(
    db,
    budget,
    `SELECT request.operation_id, request.environment, request.source,
            request.contract_id, request.dataset, request.segment_id,
            request.state, request.receipt_digest
       FROM receipt_authority_requests AS request
       JOIN receipt_authority_operations AS operation
         ON operation.operation_id = request.operation_id
       JOIN json_each(?) AS wanted
         ON operation.source = json_extract(wanted.value, '$.source')
        AND operation.dataset = json_extract(wanted.value, '$.dataset')
        AND operation.segment_id = json_extract(wanted.value, '$.segment_id')
        AND operation.run_id = json_extract(wanted.value, '$.receipt_run_id')
      WHERE request.environment=?`,
    [wanted, environment],
  );
  if (requests.length !== frozen.length) {
    throw new HoldError("MISSING_ROW", missingSelector(frozen, requests));
  }
  const unfinalized = requests.find((row) => row.state !== "FINALIZED");
  if (unfinalized) {
    throw new HoldError(
      "UNFINALIZED_REQUEST",
      selectorOf(unfinalized.dataset, unfinalized.segment_id),
    );
  }

  const naturalRows = await sourceAll<{ operation_id: string; n: number }>(
    db,
    budget,
    `SELECT structured.operation_id, COUNT(*) AS n
       FROM receipt_authority_structured_rows AS structured
       JOIN json_each(?) AS wanted
         ON structured.operation_id = wanted.value
      GROUP BY structured.operation_id`,
    [JSON.stringify(operations.map((row) => String(row.operation_id)))],
  );
  if (naturalRows.length !== frozen.length) {
    const have = new Set(naturalRows.map((row) => String(row.operation_id)));
    const missing = operations.find((row) => !have.has(String(row.operation_id)));
    throw new HoldError(
      "MISSING_ROW",
      selectorOf(missing?.dataset, missing?.segment_id),
    );
  }
  const naturalByOp = new Map<string, number>();
  for (const row of naturalRows) {
    const count = requireInt(row.n);
    if (count === null) throw new HoldError("UNTRUSTED_CHAIN");
    naturalByOp.set(String(row.operation_id), count);
  }

  const segments: Record<string, unknown>[] = [];
  for (const ref of frozen) {
    const selector = { dataset: ref.dataset, segment_id: ref.segment_id };
    const key = rowKey(ref.source, ref.dataset, ref.segment_id, ref.receipt_run_id);
    const receipt = receipts.filter((item) =>
      rowKey(item.source, item.dataset, item.segment_id, item.run_id) === key
    );
    const product = products.filter((item) =>
      rowKey(item.source, item.dataset, item.segment_id, item.run_id) === key
    );
    const operation = operations.filter((item) =>
      rowKey(item.source, item.dataset, item.segment_id, item.run_id) === key
    );
    if (receipt.length !== 1 || product.length !== 1 || operation.length !== 1) {
      throw new HoldError("UNTRUSTED_CHAIN", selector);
    }
    const requestRows = requests.filter(
      (item) => item.operation_id === operation[0]!.operation_id,
    );
    if (requestRows.length !== 1) throw new HoldError("UNTRUSTED_CHAIN", selector);
    const coverageRow = {
      status: ref.status,
      source: ref.source,
      dataset: ref.dataset,
      segment_id: ref.segment_id,
      segment_start: ref.segment_start,
      segment_end: ref.segment_end,
      expected_scope: ref.expected_scope,
      expected_items: ref.expected_items,
      policy_version: ref.policy_version,
      receipt_run_id: ref.receipt_run_id,
    };
    if (
      await trustedComplete(
        coverageRow,
        receipt,
        product,
        operation,
        requestRows,
        naturalByOp,
        environment,
        registry,
      ) !== true
    ) {
      throw new HoldError("UNTRUSTED_CHAIN", selector);
    }
    const envelope = parseJsonObject(receipt[0]!.digests_json);
    if (!isPlainObject(envelope)) throw new HoldError("UNTRUSTED_CHAIN", selector);
    segments.push({
      source: ref.source,
      dataset: ref.dataset,
      segment_id: ref.segment_id,
      segment_start: ref.segment_start,
      segment_end: ref.segment_end,
      expected_scope: ref.expected_scope,
      expected_items: ref.expected_items,
      receipt_run_id: ref.receipt_run_id,
      operation_id: String(operation[0]!.operation_id),
      receipt_digest: String(operation[0]!.receipt_digest),
      signed_receipt: envelope,
      product: {
        schema: "jquants_records/v1",
        plane: "structured",
        artifact_key: String(product[0]!.artifact_key),
        artifact_digest: String(product[0]!.artifact_digest),
        byte_count: requireInt(product[0]!.byte_count),
        row_count: requireInt(product[0]!.row_count),
        manifest_plane: "authority_evidence",
        manifest_key: String(product[0]!.manifest_key),
        manifest_digest: String(product[0]!.manifest_digest),
        raw_manifest_key: String(product[0]!.raw_manifest_key),
        raw_manifest_digest: String(product[0]!.raw_manifest_digest),
        raw_page_count: requireInt(product[0]!.raw_page_count),
        raw_row_count: requireInt(product[0]!.raw_row_count),
        raw_bytes: requireInt(product[0]!.raw_bytes),
        committed_at: String(product[0]!.committed_at),
      },
    });
  }

  const reread = await loadCoverage(db, budget, request.segments, catalogById);
  if (reread.length !== frozen.length) {
    throw new HoldError("REFERENCE_CHANGED", missingSelector(frozen, reread));
  }
  const changed = reread.find((row, index) =>
    coverageIdentity(row) !== coverageIdentity(frozen[index]!)
  );
  if (changed) {
    throw new HoldError("REFERENCE_CHANGED", {
      dataset: changed.dataset,
      segment_id: changed.segment_id,
    });
  }

  const changeAfter = present.has("ingestion_change_log")
    ? requireInt(
      (await sourceFirst<{ change_seq: number | null }>(
        db,
        budget,
        "SELECT MAX(change_seq) AS change_seq FROM ingestion_change_log",
      ))?.change_seq,
    )
    : null;

  const identity = {
    schema_version: RECEIPT_PRODUCT_INPUT_SET,
    status: "DESCRIBED",
    scope_semantics: "requested_segments_only",
    profile_completeness: "NOT_CHECKED",
    physical_availability: "NOT_CHECKED",
    readiness: "NOT_EVALUATED",
    environment,
    profile_id: PROFILE_ID,
    profile_digest: PROFILE_DIGEST,
    dependency_closure_digest: CLOSURE_DIGEST,
    coverage_policy_version: COVERAGE_POLICY_VERSION,
    receipt_registry_digest: registry.registry_digest,
    segments,
  };
  const digest = await canonicalDigest(identity);
  const body = {
    ...identity,
    input_set_digest: digest,
    read_observation: {
      checked_at: nowUtc(),
      source_change_seq_before: changeBefore,
      source_change_seq_after: changeAfter,
      session_bookmark: sessionBookmark(db),
    },
  };
  const encoded = new TextEncoder().encode(JSON.stringify(body));
  if (encoded.byteLength > MAX_RESPONSE_BYTES) throw new HoldError("READ_BUDGET");
  return { body, digest };
}

export function holdBody(
  env: ReceiptProductInputEnv,
  reason: HoldReason,
  registryDigest: string | null = null,
  selector: HoldSelector | null = null,
): Record<string, unknown> {
  return {
    schema_version: RECEIPT_PRODUCT_INPUT_SET,
    status: "HOLD",
    hold_reason: reason,
    hold_selector: selector,
    scope_semantics: "requested_segments_only",
    profile_completeness: "NOT_CHECKED",
    physical_availability: "NOT_CHECKED",
    readiness: "NOT_EVALUATED",
    environment: environmentOf(env),
    profile_id: PROFILE_ID,
    profile_digest: PROFILE_DIGEST,
    dependency_closure_digest: CLOSURE_DIGEST,
    coverage_policy_version: COVERAGE_POLICY_VERSION,
    receipt_registry_digest: registryDigest,
  };
}

export async function describeReceiptProductInput(
  env: ReceiptProductInputEnv,
  request: ClosedRequest,
): Promise<
  | { httpStatus: 200; body: Record<string, unknown> }
  | { httpStatus: 409; body: Record<string, unknown> }
> {
  const environment = environmentOf(env);
  if (!environment) {
    return { httpStatus: 409, body: holdBody(env, "READ_FAILURE") };
  }
  const registry = await pinnedReceiptRegistryForEnvironment(environment);
  const registryDigest = registry?.registry_digest ?? null;
  if (!registry || registry.authority_status !== "ACTIVE") {
    return {
      httpStatus: 409,
      body: holdBody(env, "PENDING_REGISTRY", registryDigest),
    };
  }
  try {
    const described = await describeFromDb(env, request, environment, registry);
    if (
      request.expected_current_digest &&
      request.expected_current_digest !== described.digest
    ) {
      return {
        httpStatus: 409,
        body: {
          error: "INPUT_SET_CHANGED",
          current_digest: described.digest,
        },
      };
    }
    return { httpStatus: 200, body: described.body };
  } catch (error) {
    const reason = error instanceof HoldError ? error.reason : "READ_FAILURE";
    const selector = error instanceof HoldError ? error.selector : null;
    return {
      httpStatus: 409,
      body: holdBody(env, reason, registryDigest, selector),
    };
  }
}
