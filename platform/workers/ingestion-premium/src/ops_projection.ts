/** Metadata-only Ops Projection publisher. Never reads market/fact tables. */

import { catalogProjectionRows, datasetById } from "./catalog";
import {
  COVERAGE_POLICY_VERSION,
  aggregateDatasetStatus,
  projectedSegmentStatus,
  type ReceiptVerifyRegistry,
} from "./ops_projection_policy";
import { produceImmutableB0B4 } from "./snapshot_quality_evidence";
import { sha256HexFromBytes, sha256HexFromString } from "./sha256";
import pinnedReceiptRegistry from "../../../../packages/data_plane/data_contracts/receipt_verify_public_keys.json";

export const OPS_SYNC_FEED = "jquants_records";

export const PROJECTED_CONTENT_TABLES = [
  "collection_sla_status",
  "coverage_segments",
  "dataset_coverage",
  "endpoint_inventory",
  "ingestion_run_log",
  "ingestion_validation",
  "ingestion_watermarks",
  "ops_alerts",
  "ops_b0_status",
  "ops_projection_metadata",
  "ops_ready_snapshots",
  "ops_ready_state",
  "ops_snapshot_quality",
  "ops_storage_plane_status",
  "ops_sync_feed",
  "raw_retention_manifests",
  "receipt_product_materializations",
] as const;

const SOURCE_WHITELIST = [
  "ingestion_change_log",
  "ingestion_run_log",
  "ingestion_validation",
  "ingestion_watermarks",
  "coverage_segments",
  "collection_receipts",
  "raw_retention_manifests",
  "receipt_product_materializations",
  "receipt_authority_operations",
  "receipt_authority_requests",
  "receipt_authority_structured_rows",
  "jsda_v3_cutover_control",
  "jsda_acquisition_jobs",
  "jsda_acquisition_jobs_v2",
  "jsda_acquisition_jobs_v3",
  "snapshot_quality_results",
  "snapshot_quality_evidence",
] as const;

const FORBIDDEN_SQL =
  /\b(jquants_records|jquants_daily_bars|jquants_listed_info|jquants_market_calendar|jsda_otc_bond|jsda_corporate_bond|jsda_repo_rates|fins_summary|fins_details|options)\b/i;

const ROW_CAP = 10_000;
const RUN_CAP = 100;
const ENVELOPE_SCHEMA = "ops-projection-envelope/v1";
const SIGNED_DOCUMENT_SCHEMA = "ops-projection-signed-envelope/v1";
const SOURCE_DB = {
  production: {
    provider: "cloudflare",
    kind: "d1",
    name: "quant-ingest",
    database_id: "be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
    authority_id: "cloudflare-d1:be6fdcf8-40be-41fc-9535-7facd1fc2ffc",
  },
  staging: {
    provider: "cloudflare",
    kind: "d1",
    name: "quant-ingest-staging",
    database_id: "d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb",
    authority_id: "cloudflare-d1:d448d1c6-27c8-4aeb-8702-3e7a8b6bf2bb",
  },
} as const;

export class OpsProjectionPublishError extends Error {
  readonly fields: Record<string, unknown>;
  constructor(message: string, fields: Record<string, unknown> = {}) {
    super(message);
    this.name = "OpsProjectionPublishError";
    this.fields = fields;
  }
}

export type OpsProjectionEnv = {
  DB: D1Database;
  OPS_PROJECTION_DB: D1Database;
  STRUCTURED_BUCKET?: R2Bucket;
  RAW_BUCKET?: R2Bucket;
  AUTHORITY_EVIDENCE_BUCKET?: R2Bucket;
  OPS_PROJECTION_SIGNING_PKCS8_B64: string;
  OPS_PROJECTION_VERIFY_SPKI_B64: string;
  OPS_PROJECTION_SIGNING_KEY_ID: string;
  OPS_PROJECTION_ENVIRONMENT: "staging" | "production";
  CF_VERSION_METADATA?: { id: string; tag?: string };
  RECEIPT_VERIFY_REGISTRY?: ReceiptVerifyRegistry;
  OPS_PROJECTION_REGISTRY_DIGEST?: string;
};

export type PublishResult =
  | { status: "published"; generation_id: string; source_evidence_digest: string }
  | { status: "noop"; generation_id: string; source_evidence_digest: string };

type SourceDb = D1Database | D1DatabaseSession;

function assertSafeSql(sql: string): void {
  if (FORBIDDEN_SQL.test(sql)) {
    throw new OpsProjectionPublishError("refuses market/fact table reads");
  }
}

function requireInt(value: unknown, label: string): number {
  if (typeof value === "bigint") {
    const asNumber = Number(value);
    if (!Number.isSafeInteger(asNumber)) {
      throw new OpsProjectionPublishError(`${label} must be an integer`);
    }
    return asNumber;
  }
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new OpsProjectionPublishError(`${label} must be an integer`);
  }
  return value;
}

export function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

export async function digest(value: unknown): Promise<string> {
  return `sha256:${await sha256HexFromString(JSON.stringify(canonicalize(value)))}`;
}

function bytesToB64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function b64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  return Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
}

function placeholderKey(value: string): boolean {
  const compact = value.replace(/=+$/g, "");
  return compact.length > 0 && /^A+$/.test(compact);
}

function sourceSession(db: D1Database): SourceDb {
  if (typeof db.withSession === "function") {
    return db.withSession("first-primary");
  }
  return db;
}

async function sourceAll<T>(
  db: SourceDb,
  sql: string,
  binds: unknown[] = [],
): Promise<T[]> {
  assertSafeSql(sql);
  const result = await db.prepare(sql).bind(...binds).all<T>();
  return result.results ?? [];
}

async function sourceFirst<T>(
  db: SourceDb,
  sql: string,
  binds: unknown[] = [],
): Promise<T | null> {
  assertSafeSql(sql);
  return (await db.prepare(sql).bind(...binds).first<T>()) ?? null;
}

async function tableExists(db: SourceDb, name: string): Promise<boolean> {
  const rows = await sourceAll<{ name: string }>(
    db,
    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
    [name],
  );
  return rows.length === 1;
}

async function tableColumns(db: SourceDb, name: string): Promise<Set<string>> {
  const rows = await sourceAll<{ name: string }>(
    db,
    `PRAGMA table_info(${name})`,
  );
  return new Set(rows.map((row) => String(row.name)));
}

function loadReceiptRegistry(env: OpsProjectionEnv): ReceiptVerifyRegistry | null {
  const registry = (env.RECEIPT_VERIFY_REGISTRY ?? pinnedReceiptRegistry) as ReceiptVerifyRegistry;
  if (!registry || registry.authority_status !== "ACTIVE") return null;
  return registry;
}

async function requireCap(db: SourceDb, table: string): Promise<void> {
  const rows = await sourceAll<{ n: number }>(
    db,
    `SELECT COUNT(*) AS n FROM (SELECT 1 FROM ${table} LIMIT ?)`,
    [ROW_CAP + 1],
  );
  if (requireInt(rows[0]?.n ?? 0, `${table} count`) > ROW_CAP) {
    throw new OpsProjectionPublishError(`${table} exceeds metadata cap`);
  }
}

function latestByKey<T extends Record<string, unknown>>(
  rows: T[],
  keyOf: (row: T) => string,
): T[] {
  const seen = new Set<string>();
  const latest: T[] = [];
  for (const row of rows) {
    const key = keyOf(row);
    if (seen.has(key)) continue;
    seen.add(key);
    latest.push(row);
  }
  return latest;
}

const GIT_SHA = /^[0-9a-f]{40}$/;
const CF_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const EXPORT_KIND = "ops-projection-export/v1";

function deployProvenance(env: OpsProjectionEnv): {
  producerCommitSha: string;
  workerVersionId: string;
} {
  const metadata = env.CF_VERSION_METADATA;
  const versionId = typeof metadata?.id === "string" ? metadata.id.trim() : "";
  const tag = typeof metadata?.tag === "string" ? metadata.tag.trim() : "";
  if (!tag || !versionId) {
    throw new OpsProjectionPublishError("deployment provenance is missing");
  }
  if (!GIT_SHA.test(tag)) {
    throw new OpsProjectionPublishError("Worker tag is not a clean merged Git SHA");
  }
  if (!CF_UUID.test(versionId)) {
    throw new OpsProjectionPublishError("Cloudflare version UUID is invalid");
  }
  if (tag === versionId) {
    throw new OpsProjectionPublishError("Cloudflare version UUID is not a Git SHA");
  }
  return { producerCommitSha: tag, workerVersionId: versionId };
}

function parseB4(resultsJson: unknown): { status: "PASS" | "FAIL"; results: unknown[] } {
  let document: unknown = [];
  if (typeof resultsJson === "string") {
    try {
      document = JSON.parse(resultsJson);
    } catch {
      throw new OpsProjectionPublishError("B4 evidence is malformed");
    }
  } else if (Array.isArray(resultsJson)) {
    document = resultsJson;
  }
  if (!Array.isArray(document)) {
    throw new OpsProjectionPublishError("B4 evidence is malformed");
  }
  const results = document.filter(
    (row) => row && typeof row === "object" && !Array.isArray(row) &&
      String((row as { check_id?: unknown }).check_id) === "B4",
  );
  if (results.length === 0) {
    throw new OpsProjectionPublishError("B4 evidence is missing");
  }
  const status = results.every(
    (row) => String((row as { status?: unknown }).status).toLowerCase() === "pass",
  )
    ? "PASS"
    : "FAIL";
  return { status, results };
}

function unknownB0B4(): {
  status: "UNKNOWN";
  policy_version: string;
  evaluated_at: string;
  summary_json: string;
  results_json: string;
  source_build_id: string;
  b4_status: "UNKNOWN";
  b4_results: unknown[];
} {
  return {
    status: "UNKNOWN",
    policy_version: "",
    evaluated_at: "",
    summary_json: "{}",
    results_json: "[]",
    source_build_id: "",
    b4_status: "UNKNOWN",
    b4_results: [],
  };
}

async function readAuthoritativeB0B4(
  source: SourceDb,
  present: Set<string>,
): Promise<{
  status: "PASS" | "FAIL" | "UNKNOWN";
  policy_version: string;
  evaluated_at: string;
  summary_json: string;
  results_json: string;
  source_build_id: string;
  b4_status: "PASS" | "FAIL" | "UNKNOWN";
  b4_results: unknown[];
}> {
  // Mutable snapshot_quality_results is audit-only. PASS requires an immutable
  // signed evidence table produced by the governed verification path.
  if (!present.has("snapshot_quality_evidence")) {
    return unknownB0B4();
  }
  const row = await sourceFirst<Record<string, unknown>>(
    source,
    `SELECT evidence_digest, canonical_evidence_digest, status, b4_status, policy_version, evaluated_at,
            summary_json, results_json, source_build_id, generation_id,
            source_cursor, export_cursor, applied_cursor, signature
       FROM snapshot_quality_evidence
      ORDER BY evaluated_at DESC, evidence_digest DESC
      LIMIT 1`,
  );
  if (!row) return unknownB0B4();
  if (String(row.status) !== "PASS" || String(row.b4_status) !== "PASS") {
    return {
      ...unknownB0B4(),
      status: String(row.status) === "FAIL" ? "FAIL" : "UNKNOWN",
      b4_status: String(row.b4_status) === "FAIL" ? "FAIL" : "UNKNOWN",
    };
  }
  if (typeof row.signature !== "string" || !row.signature.startsWith("ed25519:")) {
    return unknownB0B4();
  }
  const digest = String(row.evidence_digest ?? "");
  const canonical = String(row.canonical_evidence_digest ?? "");
  if (digest !== canonical || !/^sha256:[0-9a-f]{64}$/.test(digest)) {
    return unknownB0B4();
  }
  if (!row.generation_id || row.source_cursor == null || row.export_cursor == null) {
    return unknownB0B4();
  }
  return {
    status: "PASS",
    policy_version: String(row.policy_version ?? ""),
    evaluated_at: String(row.evaluated_at ?? ""),
    summary_json: String(row.summary_json ?? "{}"),
    results_json: typeof row.results_json === "string"
      ? row.results_json
      : JSON.stringify(row.results_json ?? []),
    source_build_id: String(row.source_build_id ?? ""),
    b4_status: "PASS",
    b4_results: parseB4(row.results_json).results,
  };
}

function exportCursorOf(value: unknown): number | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const cursor = (value as { source_cursor?: unknown }).source_cursor;
  if (typeof cursor !== "number" || !Number.isInteger(cursor) || cursor < 0) return null;
  return cursor;
}

function closedExport(value: unknown): {
  kind: string;
  environment: string;
  generation_id: string;
  source_cursor: number | null;
  producer_commit_sha: string;
  worker_version_id: string;
  coverage_policy_version: string;
  contract_tables: readonly string[];
  b0_status: string;
  b4_status: string;
  b0_source_build_id: string;
  b0_evaluated_at: string;
  b0_results_json: string;
  b4_results: unknown[];
  dataset_coverage: Record<string, Record<string, unknown>>;
  tables: Record<string, Record<string, unknown>[]>;
} {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new OpsProjectionPublishError("export object schema is not closed");
  }
  const document = value as Record<string, unknown>;
  if (
    document.kind !== EXPORT_KIND ||
    typeof document.environment !== "string" ||
    typeof document.generation_id !== "string" ||
    document.generation_id.length === 0 ||
    typeof document.producer_commit_sha !== "string" ||
    !GIT_SHA.test(document.producer_commit_sha) ||
    typeof document.worker_version_id !== "string" ||
    !CF_UUID.test(document.worker_version_id) ||
    typeof document.coverage_policy_version !== "string" ||
    typeof document.b0_status !== "string" ||
    typeof document.b4_status !== "string" ||
    typeof document.b0_source_build_id !== "string" ||
    typeof document.b0_evaluated_at !== "string" ||
    typeof document.b0_results_json !== "string" ||
    !Array.isArray(document.b4_results) ||
    !document.dataset_coverage ||
    typeof document.dataset_coverage !== "object" ||
    Array.isArray(document.dataset_coverage) ||
    !Array.isArray(document.contract_tables) ||
    !document.tables ||
    typeof document.tables !== "object" ||
    Array.isArray(document.tables)
  ) {
    throw new OpsProjectionPublishError("export object schema is not closed");
  }
  const tables = document.tables as Record<string, unknown>;
  for (const table of PROJECTED_CONTENT_TABLES) {
    if (!Array.isArray(tables[table])) {
      throw new OpsProjectionPublishError("export object schema is not closed");
    }
  }
  if (Object.keys(tables).length !== PROJECTED_CONTENT_TABLES.length) {
    throw new OpsProjectionPublishError("export object schema is not closed");
  }
  const cursor = document.source_cursor;
  if (cursor !== null && (typeof cursor !== "number" || !Number.isInteger(cursor) || cursor < 0)) {
    throw new OpsProjectionPublishError("export object schema is not closed");
  }
  return {
    kind: EXPORT_KIND,
    environment: document.environment,
    generation_id: document.generation_id,
    source_cursor: cursor === null ? null : cursor,
    producer_commit_sha: document.producer_commit_sha,
    worker_version_id: document.worker_version_id,
    coverage_policy_version: document.coverage_policy_version,
    contract_tables: document.contract_tables as string[],
    b0_status: document.b0_status,
    b4_status: document.b4_status,
    b0_source_build_id: document.b0_source_build_id,
    b0_evaluated_at: document.b0_evaluated_at,
    b0_results_json: document.b0_results_json,
    b4_results: document.b4_results as unknown[],
    dataset_coverage: document.dataset_coverage as Record<string, Record<string, unknown>>,
    tables: tables as Record<string, Record<string, unknown>[]>,
  };
}

function bytesEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.byteLength !== right.byteLength) return false;
  for (let index = 0; index < left.byteLength; index += 1) {
    if (left[index] !== right[index]) return false;
  }
  return true;
}

async function digestBytes(bytes: Uint8Array): Promise<string> {
  return `sha256:${await sha256HexFromBytes(bytes)}`;
}

async function putExportCreateOnly(
  env: OpsProjectionEnv,
  generationId: string,
  payload: unknown,
): Promise<{
  key: string;
  digest: string;
  byteSize: number;
  cursor: number | null;
  parsed: ReturnType<typeof closedExport>;
}> {
  const bucket = env.STRUCTURED_BUCKET;
  if (!bucket) {
    throw new OpsProjectionPublishError("R2 export bucket is required");
  }
  const key = `ops-projection/${env.OPS_PROJECTION_ENVIRONMENT}/${generationId}/export.json`;
  const body = JSON.stringify(canonicalize(payload));
  const bytes = new TextEncoder().encode(body);
  const expectedDigest = await digestBytes(bytes);
  const expectedBytes = bytes.byteLength;
  const created = await bucket.put(key, bytes, {
    onlyIf: { etagDoesNotMatch: "*" },
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    customMetadata: {
      content_digest: expectedDigest,
      byte_size: String(expectedBytes),
    },
  });
  const readback = await bucket.get(key);
  if (!readback) {
    throw new OpsProjectionPublishError("export object readback is missing");
  }
  const observed = new Uint8Array(await readback.arrayBuffer());
  if (created == null) {
    if (bytesEqual(observed, bytes)) {
      // identical create-only reuse of the same exact bytes
    } else if (observed.byteLength === bytes.byteLength) {
      throw new OpsProjectionPublishError(
        "export object exists with equal-length different bytes",
      );
    } else {
      throw new OpsProjectionPublishError("export object exists with a different digest");
    }
  } else if (!bytesEqual(observed, bytes)) {
    throw new OpsProjectionPublishError("export object readback is not byte-identical");
  }
  const observedDigest = await digestBytes(observed);
  if (observedDigest !== expectedDigest || observed.byteLength !== expectedBytes) {
    throw new OpsProjectionPublishError("export object raw-byte digest drifted");
  }
  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(new TextDecoder("utf-8").decode(observed));
  } catch {
    throw new OpsProjectionPublishError("export object is not JSON");
  }
  const parsed = closedExport(parsedJson);
  if (parsed.generation_id !== generationId || parsed.environment !== env.OPS_PROJECTION_ENVIRONMENT) {
    throw new OpsProjectionPublishError("export object identity drifted");
  }
  return {
    key,
    digest: observedDigest,
    byteSize: observed.byteLength,
    cursor: exportCursorOf(parsed),
    parsed,
  };
}

function stamp(
  rows: Record<string, unknown>[],
  generationId: string,
): Record<string, unknown>[] {
  return rows.map((row) => ({ ...row, projection_generation_id: generationId }));
}

function compareBytes(left: Uint8Array, right: Uint8Array): number {
  const length = Math.min(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    if (left[index] !== right[index]) return left[index] - right[index];
  }
  return left.length - right.length;
}

function sortRows(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  const encoder = new TextEncoder();
  return rows
    .map((row) => ({ bytes: encoder.encode(JSON.stringify(canonicalize(row))), row }))
    .sort((left, right) => compareBytes(left.bytes, right.bytes))
    .map(({ row }) => row);
}

function alignRows(
  rows: Record<string, unknown>[],
  keys: string[],
): Record<string, unknown>[] {
  return sortRows(
    rows.map((row) => {
      const aligned: Record<string, unknown> = {};
      for (const key of keys) aligned[key] = row[key] ?? null;
      return aligned;
    }),
  );
}

export async function manifestFromRows(
  tableRows: Record<string, Record<string, unknown>[]>,
): Promise<Record<string, { row_count: number; content_digest: string }>> {
  const manifest: Record<string, { row_count: number; content_digest: string }> = {};
  for (const table of PROJECTED_CONTENT_TABLES) {
    const rows = sortRows(tableRows[table] ?? []);
    manifest[table] = {
      row_count: rows.length,
      content_digest: await digest({ rows }),
    };
  }
  return manifest;
}

async function signAndVerify(
  env: OpsProjectionEnv,
  envelope: Record<string, unknown>,
): Promise<{ signature: string; signedJson: string }> {
  if (
    !env.OPS_PROJECTION_VERIFY_SPKI_B64 ||
    placeholderKey(env.OPS_PROJECTION_VERIFY_SPKI_B64)
  ) {
    throw new OpsProjectionPublishError("Ops Projection verify SPKI is unprovisioned");
  }
  const body = {
    schema_version: SIGNED_DOCUMENT_SCHEMA,
    algorithm: "Ed25519",
    issuer_key_id: env.OPS_PROJECTION_SIGNING_KEY_ID,
    envelope,
  };
  const canonical = JSON.stringify(canonicalize(body));
  const signingKey = await crypto.subtle.importKey(
    "pkcs8",
    b64ToBytes(env.OPS_PROJECTION_SIGNING_PKCS8_B64),
    { name: "Ed25519" },
    false,
    ["sign"],
  );
  const signatureBytes = new Uint8Array(
    await crypto.subtle.sign(
      { name: "Ed25519" },
      signingKey,
      new TextEncoder().encode(canonical),
    ),
  );
  const verifyKey = await crypto.subtle.importKey(
    "spki",
    b64ToBytes(env.OPS_PROJECTION_VERIFY_SPKI_B64),
    { name: "Ed25519" },
    false,
    ["verify"],
  );
  const ok = await crypto.subtle.verify(
    { name: "Ed25519" },
    verifyKey,
    signatureBytes,
    new TextEncoder().encode(canonical),
  );
  if (!ok) {
    throw new OpsProjectionPublishError("signed envelope failed SPKI self-verify");
  }
  const signature = `ed25519:${bytesToB64(signatureBytes)}`;
  return { signature, signedJson: JSON.stringify({ ...body, signature }) };
}

export async function publishOpsProjection(
  env: OpsProjectionEnv,
): Promise<PublishResult> {
  const environment = env.OPS_PROJECTION_ENVIRONMENT;
  if (environment !== "staging" && environment !== "production") {
    throw new OpsProjectionPublishError("OPS_PROJECTION_ENVIRONMENT is invalid");
  }
  if (!env.OPS_PROJECTION_SIGNING_KEY_ID || placeholderKey(env.OPS_PROJECTION_SIGNING_PKCS8_B64)) {
    throw new OpsProjectionPublishError("Ops Projection signing key is unprovisioned");
  }
  if (!env.OPS_PROJECTION_VERIFY_SPKI_B64 || placeholderKey(env.OPS_PROJECTION_VERIFY_SPKI_B64)) {
    throw new OpsProjectionPublishError("Ops Projection verify SPKI is unprovisioned");
  }
  const sourceIdentity = SOURCE_DB[environment];
  const { producerCommitSha: producerSha, workerVersionId: versionId } =
    deployProvenance(env);
  const receiptRegistry = loadReceiptRegistry(env);
  const source = sourceSession(env.DB);

  const present = new Set<string>();
  for (const name of SOURCE_WHITELIST) {
    if (await tableExists(source, name)) present.add(name);
  }

  let sourceCursor: number | null = null;
  if (present.has("ingestion_change_log")) {
    const row = await sourceFirst<{ change_seq: number | null }>(
      source,
      "SELECT MAX(change_seq) AS change_seq FROM ingestion_change_log",
    );
    sourceCursor = row?.change_seq == null ? null : requireInt(row.change_seq, "change_seq");
  }

  if (present.has("ingestion_run_log")) await requireCap(source, "ingestion_run_log");
  const runs = present.has("ingestion_run_log")
    ? await sourceAll<Record<string, unknown>>(
        source,
        "SELECT id, ran_at, source, runtime, status, detail FROM ingestion_run_log ORDER BY id DESC LIMIT ?",
        [RUN_CAP],
      )
    : [];

  const runIds = runs.map((row) => requireInt(row.id, "run id"));
  const validation = present.has("ingestion_validation") && runIds.length
    ? await sourceAll<Record<string, unknown>>(
        source,
        `SELECT run_id, dataset, status, rows_seen, rows_inserted, rows_revisions, detail
           FROM ingestion_validation
          WHERE run_id IN (${runIds.map(() => "?").join(",")})
          ORDER BY run_id DESC, dataset
          LIMIT ?`,
        [...runIds, ROW_CAP + 1],
      )
    : [];
  if (validation.length > ROW_CAP) {
    throw new OpsProjectionPublishError("ingestion_validation exceeds metadata cap");
  }

  const watermarks = present.has("ingestion_watermarks")
    ? await sourceAll<Record<string, unknown>>(
        source,
        "SELECT dataset, last_event_date, last_ingested_at, last_export_cursor FROM ingestion_watermarks ORDER BY dataset LIMIT ?",
        [ROW_CAP + 1],
      )
    : [];
  if (watermarks.length > ROW_CAP) {
    throw new OpsProjectionPublishError("ingestion_watermarks exceeds metadata cap");
  }

  if (present.has("coverage_segments")) await requireCap(source, "coverage_segments");
  const coverageRaw = present.has("coverage_segments")
    ? await sourceAll<Record<string, unknown>>(
        source,
        `SELECT source, dataset, segment_id, policy_version, segment_start, segment_end,
                expected_scope, expected_items, status, receipt_run_id, evaluated_at, detail_json
           FROM coverage_segments
          ORDER BY source, dataset, segment_id, policy_version, evaluated_at DESC, segment_id
          LIMIT ?`,
        [ROW_CAP + 1],
      )
    : [];
  if (coverageRaw.length > ROW_CAP) {
    throw new OpsProjectionPublishError("coverage_segments exceeds metadata cap");
  }
  const coverage = latestByKey(
    coverageRaw,
    (row) => `${row.source}\0${row.dataset}\0${row.segment_id}\0${row.policy_version}`,
  );

  if (present.has("collection_receipts")) await requireCap(source, "collection_receipts");
  const receiptsRaw = present.has("collection_receipts")
    ? await sourceAll<Record<string, unknown>>(
        source,
        `SELECT source, dataset, segment_id, segment_start, segment_end, expected_scope,
                expected_items, observed_items, raw_page_count, raw_row_count,
                structured_row_count, pagination_exhausted, digests_json, run_id,
                status, error, checked_at
           FROM collection_receipts
          ORDER BY source, dataset, segment_id, checked_at DESC, run_id DESC
          LIMIT ?`,
        [ROW_CAP + 1],
      )
    : [];
  if (receiptsRaw.length > ROW_CAP) {
    throw new OpsProjectionPublishError("collection_receipts exceeds metadata cap");
  }
  const receipts = receiptsRaw;

  if (present.has("raw_retention_manifests")) await requireCap(source, "raw_retention_manifests");
  const rawRows = present.has("raw_retention_manifests")
    ? await sourceAll<Record<string, unknown>>(
        source,
        `SELECT dataset, run_id, manifest_key, page_count, row_count,
                raw_bytes, data_digest, completeness, created_at
           FROM raw_retention_manifests
          ORDER BY dataset, created_at DESC, run_id DESC
          LIMIT ?`,
        [ROW_CAP + 1],
      )
    : [];
  if (rawRows.length > ROW_CAP) {
    throw new OpsProjectionPublishError("raw_retention_manifests exceeds metadata cap");
  }
  const rawLatest = latestByKey(rawRows, (row) => String(row.dataset)).map((row) => ({
    source: "UNKNOWN",
    dataset: row.dataset,
    segment_id: "dataset",
    run_id: row.run_id,
    manifest_key: row.manifest_key,
    page_count: row.page_count,
    row_count: row.row_count,
    raw_bytes: row.raw_bytes,
    data_digest: row.data_digest,
    completeness: row.completeness,
    created_at: row.created_at,
    reason: null,
  }));

  if (present.has("receipt_product_materializations")) {
    await requireCap(source, "receipt_product_materializations");
  }
  const productsRaw = present.has("receipt_product_materializations")
    ? await sourceAll<Record<string, unknown>>(
        source,
        `SELECT operation_id, run_id, source, dataset, segment_id, artifact_key, artifact_digest,
                row_count, byte_count, manifest_key, manifest_digest, raw_manifest_key,
                raw_manifest_digest, raw_page_count, raw_row_count, raw_bytes, committed_at
           FROM receipt_product_materializations
          ORDER BY dataset, segment_id, committed_at DESC, operation_id
          LIMIT ?`,
        [ROW_CAP + 1],
      )
    : [];
  if (productsRaw.length > ROW_CAP) {
    throw new OpsProjectionPublishError("receipt_product_materializations exceeds metadata cap");
  }
  const products = latestByKey(
    productsRaw,
    (row) => `${row.source}\0${row.run_id}\0${row.dataset}\0${row.segment_id}`,
  ).filter(
    (row) =>
      (String(row.source) === "jquants" || String(row.source) === "jsda") &&
      Number(row.row_count) > 0 &&
      Number(row.byte_count) > 0 &&
      Number(row.raw_page_count) > 0 &&
      Number(row.raw_row_count) > 0 &&
      Number(row.raw_bytes) > 0 &&
      String(row.operation_id || "") &&
      String(row.artifact_key || "") &&
      String(row.artifact_digest || "") &&
      String(row.manifest_key || "") &&
      String(row.manifest_digest || "") &&
      String(row.raw_manifest_key || "") &&
      String(row.raw_manifest_digest || "") &&
      String(row.committed_at || "") &&
      !/UNKNOWN/i.test(String(row.artifact_digest || "")) &&
      !/UNKNOWN/i.test(String(row.manifest_digest || "")) &&
      !/UNKNOWN/i.test(String(row.raw_manifest_digest || "")),
  );

  if (present.has("receipt_authority_operations")) {
    await requireCap(source, "receipt_authority_operations");
  }
  const operations = present.has("receipt_authority_operations")
    ? await sourceAll<Record<string, unknown>>(
        source,
        `SELECT operation_id, run_id, environment, source, contract_id, dataset, segment_id,
                segment_start, segment_end, state, receipt_digest, request_digest,
                structured_manifest_key, structured_digest, raw_manifest_key,
                raw_manifest_digest, raw_page_count, raw_row_count, raw_bytes
           FROM receipt_authority_operations
          ORDER BY dataset, segment_id, updated_at DESC, operation_id
          LIMIT ?`,
        [ROW_CAP + 1],
      )
    : [];
  if (operations.length > ROW_CAP) {
    throw new OpsProjectionPublishError("receipt_authority_operations exceeds metadata cap");
  }

  if (present.has("receipt_authority_requests")) {
    await requireCap(source, "receipt_authority_requests");
  }
  const requests = present.has("receipt_authority_requests")
    ? await sourceAll<Record<string, unknown>>(
        source,
        `SELECT operation_id, environment, source, contract_id, dataset, segment_id,
                state, receipt_digest
           FROM receipt_authority_requests
          ORDER BY dataset, segment_id, updated_at DESC, operation_id
          LIMIT ?`,
        [ROW_CAP + 1],
      )
    : [];
  if (requests.length > ROW_CAP) {
    throw new OpsProjectionPublishError("receipt_authority_requests exceeds metadata cap");
  }

  const naturalByOp = new Map<string, number>();
  if (present.has("receipt_authority_structured_rows")) {
    await requireCap(source, "receipt_authority_structured_rows");
    for (const operation of operations) {
      const operationId = String(operation.operation_id ?? "");
      if (!operationId) continue;
      const row = await sourceFirst<{ n: number }>(
        source,
        "SELECT COUNT(*) AS n FROM receipt_authority_structured_rows WHERE operation_id=?",
        [operationId],
      );
      naturalByOp.set(operationId, requireInt(row?.n ?? 0, "natural key count"));
    }
  }

  async function jobCount(table: string, where: string): Promise<number | null> {
    if (!present.has(table)) return null;
    await requireCap(source, table);
    const row = await sourceFirst<{ n: number }>(
      source,
      `SELECT COUNT(*) AS n FROM ${table} ${where}`,
    );
    return requireInt(row?.n ?? 0, `${table} count`);
  }

  const jsda = {
    phase: present.has("jsda_v3_cutover_control")
      ? ((await sourceFirst<{ phase: string }>(
          source,
          "SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1",
        ))?.phase ?? "UNKNOWN")
      : "NOT_PROJECTED",
    nonterminal_v1: await jobCount(
      "jsda_acquisition_jobs",
      "WHERE state IN ('pending','running','retry')",
    ),
    nonterminal_v2: await jobCount(
      "jsda_acquisition_jobs_v2",
      "WHERE state IN ('pending','queued','running','failed_transient')",
    ),
    nonterminal_v3: await jobCount(
      "jsda_acquisition_jobs_v3",
      "WHERE state IN ('pending','queued','running','waiting_children','failed_transient')",
    ),
    future_leases: present.has("jsda_acquisition_jobs_v3")
      ? requireInt(
          (await sourceFirst<{ n: number }>(
            source,
            "SELECT COUNT(*) AS n FROM jsda_acquisition_jobs_v3 WHERE lease_until IS NOT NULL AND lease_until > datetime('now')",
          ))?.n ?? 0,
          "lease count",
        )
      : null,
  };
  let changeLogRowCount: number | null = null;
  if (present.has("ingestion_change_log")) {
    const counted = await sourceFirst<{ n: number }>(
      source,
      "SELECT COUNT(*) AS n FROM ingestion_change_log",
    );
    changeLogRowCount = requireInt(counted?.n ?? 0, "change log row count");
  }

  const b0b4 = await readAuthoritativeB0B4(source, present);
  const sourceEvidence = {
    environment,
    source: sourceIdentity,
    source_cursor: sourceCursor,
    runs,
    validation,
    watermarks,
    coverage,
    receipts,
    raw: rawLatest,
    products,
    operations,
    requests,
    jsda,
    b0: {
      status: b0b4.status,
      policy_version: b0b4.policy_version,
      evaluated_at: b0b4.evaluated_at,
      source_build_id: b0b4.source_build_id,
      results_digest: await digest(b0b4.results_json),
    },
    b4: { status: b0b4.b4_status, results: b0b4.b4_results },
  };
  const sourceEvidenceDigest = await digest(sourceEvidence);
  const sourceDbDigest = sourceEvidenceDigest;

  const active = await env.OPS_PROJECTION_DB.prepare(
    `SELECT a.generation_id, g.content_digest, g.source_db_digest, g.detail_json,
            g.generated_at, g.status, g.producer_commit_sha
       FROM ops_projection_active a
       JOIN ops_projection_generation g ON g.generation_id=a.generation_id
      WHERE a.singleton=1`,
  ).first<{
    generation_id: string;
    content_digest: string;
    source_db_digest: string;
    detail_json: string;
    generated_at: string;
    status: string;
    producer_commit_sha: string;
  }>();
  let activeEvidence = "";
  let activeVersion = "";
  try {
    const parsed = JSON.parse(active?.detail_json || "{}") as Record<string, unknown>;
    activeEvidence = String(parsed.source_evidence_digest || "");
    activeVersion = String(parsed.worker_version_id || "");
  } catch {
    activeEvidence = "";
    activeVersion = "";
  }
  if (
    active?.status === "SEALED" &&
    activeEvidence === sourceEvidenceDigest &&
    active.producer_commit_sha === producerSha &&
    activeVersion === versionId &&
    GIT_SHA.test(producerSha) &&
    CF_UUID.test(versionId)
  ) {
    return {
      status: "noop",
      generation_id: active.generation_id,
      source_evidence_digest: sourceEvidenceDigest,
    };
  }
  let activeCursor: number | null = null;
  try {
    const parsed = JSON.parse(active?.detail_json || "{}");
    activeCursor = typeof parsed.source_cursor === "number" ? parsed.source_cursor : null;
  } catch {
    activeCursor = null;
  }
  if (
    typeof activeCursor === "number" &&
    typeof sourceCursor === "number" &&
    sourceCursor < activeCursor
  ) {
    throw new OpsProjectionPublishError("source cursor would regress", {
      source_cursor: sourceCursor,
      active_cursor: activeCursor,
    });
  }

  const generationId = (await digest({
    kind: "ops-projection-generation/v1",
    environment,
    source_evidence_digest: sourceEvidenceDigest,
    producer_commit_sha: producerSha,
    worker_version_id: versionId,
  })).slice("sha256:".length);
  const produced = await produceImmutableB0B4(env, source, generationId);
  if (produced.status === "PASS" && produced.b4_status === "PASS") {
    Object.assign(b0b4, {
      status: produced.status,
      policy_version: produced.policy_version,
      evaluated_at: produced.evaluated_at,
      summary_json: produced.summary_json,
      results_json: produced.results_json,
      source_build_id: produced.source_build_id,
      b4_status: produced.b4_status,
      b4_results: (() => { try { return parseB4(produced.results_json).results; } catch { return []; } })(),
    });
  } else if (produced.status === "UNKNOWN" || produced.b4_status === "UNKNOWN") {
    Object.assign(b0b4, {
      status: produced.status === "FAIL" ? "FAIL" : "UNKNOWN",
      b4_status: produced.b4_status === "FAIL" ? "FAIL" : "UNKNOWN",
      policy_version: produced.policy_version,
      evaluated_at: produced.evaluated_at,
      summary_json: produced.summary_json,
      results_json: produced.results_json,
      source_build_id: produced.source_build_id,
      b4_results: (() => { try { return parseB4(produced.results_json).results; } catch { return []; } })(),
    });
  } else {
    Object.assign(b0b4, {
      status: produced.status,
      b4_status: produced.b4_status,
      policy_version: produced.policy_version,
      evaluated_at: produced.evaluated_at,
      summary_json: produced.summary_json,
      results_json: produced.results_json,
      source_build_id: produced.source_build_id,
      b4_results: (() => { try { return parseB4(produced.results_json).results; } catch { return []; } })(),
    });
  }

  const existing = await env.OPS_PROJECTION_DB.prepare(
    "SELECT status, generated_at FROM ops_projection_generation WHERE generation_id=?",
  )
    .bind(generationId)
    .first<{ status: string; generated_at: string }>();

  let generatedAt = new Date().toISOString().replace(/\.\d+Z$/, "Z");
  if (existing?.status === "SEALED" && active?.generation_id === generationId) {
    return {
      status: "noop",
      generation_id: generationId,
      source_evidence_digest: sourceEvidenceDigest,
    };
  }
  if (existing?.status === "OPEN" && existing.generated_at) {
    generatedAt = existing.generated_at;
  }

  const catalogRowsForPolicy = catalogProjectionRows();
  const coverageByDataset: Record<string, Record<string, unknown>> = {};
  const coverageGrouped = new Map<string, Record<string, unknown>[]>();
  for (const row of coverage) {
    const dataset = String(row.dataset ?? "");
    if (!dataset) continue;
    const group = coverageGrouped.get(dataset) ?? [];
    group.push(row);
    coverageGrouped.set(dataset, group);
  }
  for (const [dataset, rows] of coverageGrouped) {
    const spec = datasetById(dataset);
    const catalog = catalogRowsForPolicy.find((item) => item.dataset_id === dataset);
    const policy = spec?.coverage ?? catalog?.coverage;
    const currentPolicy = policy?.policy_version;
    const currentSource = catalog?.source;
    const eligible = rows.filter((row) =>
      currentPolicy === COVERAGE_POLICY_VERSION &&
      String(row.policy_version) === currentPolicy &&
      (currentSource == null || String(row.source) === currentSource),
    );
    const statuses = await Promise.all(
      eligible.map((row) =>
        projectedSegmentStatus(
          row, receipts, products, operations, requests, naturalByOp, environment,
          receiptRegistry,
          {
            structured: env.STRUCTURED_BUCKET,
            authority: env.AUTHORITY_EVIDENCE_BUCKET,
            raw: env.RAW_BUCKET,
          },
        ),
      ),
    );
    coverageByDataset[dataset] = {
      policy_id: dataset,
      policy_version: currentPolicy ?? "UNKNOWN",
      policy_digest: policy
        ? await digest(policy)
        : await digest({ dataset, policy: "UNKNOWN" }),
      status: aggregateDatasetStatus(statuses),
    };
  }
  const catalogRows = catalogProjectionRows();
  for (const row of catalogRows) {
    if (coverageByDataset[row.dataset_id]) continue;
    coverageByDataset[row.dataset_id] = {
      policy_id: row.dataset_id,
      policy_version: row.coverage.policy_version,
      policy_digest: await digest(row.coverage),
      status: "UNKNOWN",
    };
  }

  const jsdaProjected = jsda.phase !== "NOT_PROJECTED";
  const alerts: Record<string, unknown>[] = [];
  if (!jsdaProjected) {
    alerts.push({
      alert_key: "jsda_state",
      severity: "info",
      status: "open",
      reason: "JSDA cutover/job tables are NOT_PROJECTED",
      observed_at: generatedAt,
      detail_json: JSON.stringify({ plane: "ops_current", jsda }),
    });
  }
  if (!present.has("receipt_product_materializations") || products.length === 0) {
    alerts.push({
      alert_key: "receipt_products",
      severity: "info",
      status: "open",
      reason: present.has("receipt_product_materializations")
        ? "receipt_product_materializations present but not a verified projectable chain"
        : "receipt_product_materializations are NOT_PROJECTED",
      observed_at: generatedAt,
      detail_json: "{}",
    });
  }

  const logical: Record<string, Record<string, unknown>[]> = {
    collection_sla_status: catalogRows.map((row) => ({
      dataset_id: row.dataset_id,
      expected_after: null,
      usable_by: null,
      freshness_policy: row.coverage.expected_frequency,
      timezone: "Asia/Tokyo",
      current_state: "UNKNOWN",
      state_reason: "trusted SLA evidence is absent from metadata-only source reads",
      state_since: null,
      last_event_date:
        watermarks.find((mark) => String(mark.dataset) === row.dataset_id)?.last_event_date ??
        null,
      last_checked_at: generatedAt,
    })),
    coverage_segments: await Promise.all(coverage.map(async (row) => ({
      source: row.source,
      dataset: row.dataset,
      segment_id: row.segment_id,
      policy_version: row.policy_version,
      segment_start: row.segment_start,
      segment_end: row.segment_end,
      expected_scope: row.expected_scope,
      expected_items: row.expected_items ?? null,
      status: await projectedSegmentStatus(
        row, receipts, products, operations, requests, naturalByOp, environment,
        receiptRegistry,
        {
          structured: env.STRUCTURED_BUCKET,
          authority: env.AUTHORITY_EVIDENCE_BUCKET,
          raw: env.RAW_BUCKET,
        },
      ),
      receipt_run_id: row.receipt_run_id ?? null,
      evaluated_at: row.evaluated_at,
      detail_json: row.detail_json,
    }))),
    dataset_coverage: Object.entries(coverageByDataset).map(([dataset, row]) => {
      const spec = datasetById(dataset);
      const catalog = catalogRows.find((item) => item.dataset_id === dataset);
      const coverage = spec?.coverage ?? catalog?.coverage;
      return {
        dataset,
        status: row.status,
        policy_version: row.policy_version,
        collection_scope: coverage?.collection_scope ?? "UNKNOWN",
        history_target_start: coverage?.history_target_start ?? "UNKNOWN",
        history_target_end_rule: coverage?.history_target_end_rule ?? "UNKNOWN",
        coverage_mode: coverage?.coverage_mode ?? "UNKNOWN",
        expected_frequency: coverage?.expected_frequency ?? "UNKNOWN",
        universe_rule: coverage?.universe_rule ?? "UNKNOWN",
        raw_retention_required: coverage?.raw_retention_required ? 1 : 0,
        structured_reconciliation_required: coverage?.structured_reconciliation_required
          ? 1
          : 0,
        governance_tier: coverage?.governance_tier ?? "governed",
        observed_start: null,
        observed_end: null,
        row_count: 0,
        source_run_id: null,
        evaluated_at: generatedAt,
        detail_json: "{}",
      };
    }),
    endpoint_inventory: catalogRows.map((row) => ({
      dataset_id: row.dataset_id,
      display_name: row.display_name,
      source: row.source,
      governance_tier: row.coverage.governance_tier,
      inventory_status: "catalog",
      upstream_locator: null,
      collection_window: row.coverage.collection_scope,
      expected_frequency: row.coverage.expected_frequency,
      coverage_segment_granularity: row.coverage.segment_granularity,
      research_eligible: 0,
      enabled: 1,
      sla: JSON.stringify({
        expected_frequency: row.coverage.expected_frequency,
        collection_scope: row.coverage.collection_scope,
        policy_version: row.coverage.policy_version,
      }),
      historical_start: row.coverage.history_target_start,
      available_at_json: "{}",
    })),
    ingestion_run_log: runs.map((row) => ({
      id: row.id,
      ran_at: row.ran_at,
      source: row.source,
      runtime: row.runtime,
      status: row.status,
      detail: row.detail ?? null,
      authority_operation_id: row.authority_operation_id ?? null,
    })),
    ingestion_validation: validation.map((row) => ({
      run_id: row.run_id,
      dataset: row.dataset,
      status: row.status,
      rows_seen: row.rows_seen ?? null,
      rows_inserted: row.rows_inserted ?? null,
      rows_revisions: row.rows_revisions ?? null,
      detail: row.detail ?? null,
    })),
    ingestion_watermarks: (() => {
      const projected = watermarks.map((row) => ({ ...row }));
      const seen = new Set(projected.map((row) => String(row.dataset ?? "")));
      for (const row of catalogRows) {
        if (row.source !== "jsda" || seen.has(row.dataset_id)) continue;
        projected.push({
          dataset: row.dataset_id,
          last_event_date: null,
          last_ingested_at: null,
          last_export_cursor: null,
        });
      }
      return projected;
    })(),
    ops_alerts: alerts,
    ops_b0_status: [
      {
        singleton: 1,
        status: b0b4.status,
        policy_version: b0b4.policy_version,
        evaluated_at: b0b4.evaluated_at,
        summary_json: b0b4.summary_json,
        results_json: b0b4.results_json,
        source_build_id: b0b4.source_build_id,
      },
    ],
    ops_projection_metadata: [
      {
        generated_at: generatedAt,
        source_generation: sourceCursor,
        source_cursor: sourceCursor,
        export_cursor: env.STRUCTURED_BUCKET && sourceCursor !== null ? sourceCursor : null,
        applied_cursor: env.STRUCTURED_BUCKET && sourceCursor !== null ? sourceCursor : null,
        age_seconds: 0,
        status: env.STRUCTURED_BUCKET && sourceCursor !== null ? "FRESH" : "UNKNOWN",
        projection_version: "ops-projection/v1",
        refresh_attempt_at: generatedAt,
        refresh_success_at: env.STRUCTURED_BUCKET && sourceCursor !== null ? generatedAt : null,
        refresh_error: null,
        detail_json: JSON.stringify({
          worker_version_id: versionId,
          producer_commit_sha: producerSha,
          jsda,
          refresh_status: env.STRUCTURED_BUCKET && sourceCursor !== null ? "success" : "attempted",
        }),
      },
    ],
    ops_ready_snapshots: [],
    ops_ready_state: [
      {
        status: "NOT_READY",
        snapshot_id: null,
        reason: "trusted READY evidence is absent from metadata-only source reads",
        evaluated_at: generatedAt,
      },
    ],
    ops_snapshot_quality: [],
    ops_storage_plane_status: [
      {
        materialized_at: generatedAt,
        payload_json: JSON.stringify({
          schema: "ops_storage_plane_status/v1",
          generation: generationId,
          counts: {
            status: "NOT_PROJECTED",
            reason: "metadata-only producer does not scan ingestion facts",
          },
          hot_window: {
            status: "NOT_PROJECTED",
            reason: "metadata-only producer does not scan ingestion facts",
          },
          plane: "ops_current",
          jsda,
          reason: present.has("ingestion_change_log") ? null : "source change log is NOT_PROJECTED",
          source_db_digest: sourceDbDigest,
        }),
      },
    ],
    ops_sync_feed: [
      {
        feed: OPS_SYNC_FEED,
        latest_source_change_seq: sourceCursor,
        change_log_row_count: changeLogRowCount,
        exported_cursor: env.STRUCTURED_BUCKET && sourceCursor !== null ? sourceCursor : null,
        applied_cursor: env.STRUCTURED_BUCKET && sourceCursor !== null ? sourceCursor : null,
        updated_at: generatedAt,
      },
    ],
    raw_retention_manifests: rawLatest,
    receipt_product_materializations: products.map((row) => ({
      operation_id: row.operation_id,
      run_id: row.run_id,
      source: row.source,
      dataset: row.dataset,
      segment_id: row.segment_id,
      artifact_key: row.artifact_key,
      artifact_digest: row.artifact_digest,
      artifact_body: "",
      row_count: row.row_count,
      byte_count: row.byte_count,
      manifest_key: row.manifest_key,
      manifest_digest: row.manifest_digest,
      raw_manifest_key: row.raw_manifest_key,
      raw_manifest_digest: row.raw_manifest_digest,
      raw_page_count: row.raw_page_count,
      raw_row_count: row.raw_row_count,
      raw_bytes: row.raw_bytes,
      committed_at: row.committed_at,
    })),
  };

  const tableRows: Record<string, Record<string, unknown>[]> = {};
  for (const table of PROJECTED_CONTENT_TABLES) {
    tableRows[table] = stamp(logical[table] ?? [], generationId);
  }
  const allIdentitiesV3 = coverage.every(
    (row) => String(row.policy_version) === COVERAGE_POLICY_VERSION,
  );
  const envelopePolicy = allIdentitiesV3
    ? COVERAGE_POLICY_VERSION
    : "collection-coverage/mixed";
  async function rereadSourceCursor(): Promise<number | null> {
    if (!present.has("ingestion_change_log")) return null;
    const row = await sourceFirst<{ change_seq: number | null }>(
      source,
      "SELECT MAX(change_seq) AS change_seq FROM ingestion_change_log",
    );
    return row?.change_seq == null ? null : requireInt(row.change_seq, "change_seq");
  }
  const sealedCursor = await rereadSourceCursor();
  if (sealedCursor !== sourceCursor) {
    throw new OpsProjectionPublishError("source cursor changed during projection; aborting without publish", {
      source_cursor: sourceCursor,
      reread_cursor: sealedCursor,
    });
  }
  const exportBundle = {
    kind: EXPORT_KIND,
    environment,
    generation_id: generationId,
    source_cursor: sourceCursor,
    producer_commit_sha: producerSha,
    worker_version_id: versionId,
    coverage_policy_version: envelopePolicy,
    contract_tables: [...PROJECTED_CONTENT_TABLES],
    b0_status: b0b4.status,
    b4_status: b0b4.b4_status,
    b0_source_build_id: b0b4.source_build_id,
    b0_evaluated_at: b0b4.evaluated_at,
    b0_results_json: b0b4.results_json,
    b4_results: b0b4.b4_results,
    dataset_coverage: coverageByDataset,
    tables: tableRows,
  };
  const exported = await putExportCreateOnly(env, generationId, exportBundle);
  const appliedRows = exported.parsed.tables;
  const verifiedCoverage = exported.parsed.dataset_coverage;
  const exportCursor = exported.cursor;
  const verifiedSourceCursor = exported.parsed.source_cursor;
  const manifest = await manifestFromRows(appliedRows);
  const contentDigest = await digest({ tables: manifest });
  const contractDigest = await digest({ tables: PROJECTED_CONTENT_TABLES });
  const pinnedRegistryDigest = environment === "staging"
    ? "sha256:093fb04a3530cb094b4c4eaf2bbd92f9813706c12a885aa70931fbc4d605b7b9"
    : "sha256:5bebf8906b263fd9a2edf295a4e1e64e0a5a7e52bb3160123c455ebc3d39dadb";
  const registryDigest = env.OPS_PROJECTION_REGISTRY_DIGEST &&
    /^sha256:[0-9a-f]{64}$/.test(env.OPS_PROJECTION_REGISTRY_DIGEST)
    ? env.OPS_PROJECTION_REGISTRY_DIGEST
    : pinnedRegistryDigest;
  const meta = appliedRows.ops_projection_metadata[0] ?? {};
  const appliedCursor =
    typeof meta.applied_cursor === "number" ? meta.applied_cursor : null;
  const projectionStatus = typeof meta.status === "string" ? meta.status : "UNKNOWN";
  const envelope: Record<string, unknown> = {
    schema_version: ENVELOPE_SCHEMA,
    environment,
    resource_identity: {
      environment,
      source_d1: sourceIdentity,
      source_audit_digest: sourceDbDigest,
      source_export_digest: exported.digest,
      source_change_seq: verifiedSourceCursor,
    },
    generation_id: exported.parsed.generation_id,
    content_digest: contentDigest,
    source_db_digest: sourceDbDigest,
    generated_at: generatedAt,
    producer_commit_sha: exported.parsed.producer_commit_sha,
    worker_version_id: exported.parsed.worker_version_id,
    contract_digest: contractDigest,
    registry_digest: registryDigest,
    coverage_policy_version: exported.parsed.coverage_policy_version,
    coverage_policy_digest: await digest({
      version: exported.parsed.coverage_policy_version,
    }),
    projection_status: projectionStatus,
    source_generation: verifiedSourceCursor,
    source_snapshot_generation: verifiedSourceCursor,
    source_cursor: verifiedSourceCursor,
    export_cursor: exportCursor,
    applied_cursor: appliedCursor,
    coverage_status_digest: await digest(verifiedCoverage),
    dataset_coverage: verifiedCoverage,
    b0_status: exported.parsed.b0_status,
    b0_evidence_digest: await digest({
      status: exported.parsed.b0_status,
      source_build_id: exported.parsed.b0_source_build_id,
      evaluated_at: exported.parsed.b0_evaluated_at,
      results: exported.parsed.b0_results_json,
      generation_id: exported.parsed.generation_id,
      source_cursor: verifiedSourceCursor,
      export_cursor: exportCursor,
      applied_cursor: appliedCursor,
    }),
    b4_status: exported.parsed.b4_status,
    b4_evidence_digest: await digest({
      status: exported.parsed.b4_status,
      results: exported.parsed.b4_results,
      generation_id: exported.parsed.generation_id,
      source_cursor: verifiedSourceCursor,
      export_cursor: exportCursor,
      applied_cursor: appliedCursor,
    }),
    evidence_digests: {
      source_evidence_digest: sourceEvidenceDigest,
      registry_identity_digest: await digest({
        document_digest: registryDigest,
        body_digest: pinnedRegistryDigest,
        raw_sha: environment === "staging"
          ? "sha256:ae06407af2401545e59fb507aa9f9765b9840b4d7cfeb6d8fc528dc43416f2b0"
          : "sha256:b8dbdbc826c7d6af6546fd3ba7b681a5c03a688cb0899ac449d1adbfaf96387a",
        raw_size: environment === "staging" ? 655 : 1078,
        generation: environment === "staging" ? 2 : 3,
        authority_status: receiptRegistry?.authority_status ?? "PENDING",
      }),
      receipt_registry_identity_digest: await digest({
        digest: receiptRegistry?.registry_digest ?? null,
        raw_sha: "sha256:dc6095db1d09bf775f972cb428944a1ba5bc47fefa0af19e77c3f3a157ae47f5",
        raw_size: 1370,
        generation: receiptRegistry?.generation ?? 2,
        authority_status: receiptRegistry?.authority_status ?? "PENDING",
      }),
    },
    content_manifest: manifest,
    row_counts: Object.fromEntries(
      PROJECTED_CONTENT_TABLES.map((table) => [table, manifest[table].row_count]),
    ),
  };
  const beforeSealCursor = await rereadSourceCursor();
  if (beforeSealCursor !== sourceCursor || beforeSealCursor !== verifiedSourceCursor) {
    throw new OpsProjectionPublishError("source cursor changed before seal; aborting without publish", {
      source_cursor: sourceCursor,
      reread_cursor: beforeSealCursor,
    });
  }
  if (produced.evidence_digest) {
    if (produced.generation_id !== generationId) {
      throw new OpsProjectionPublishError("B0/B4 generation/cursors drifted before seal");
    }
    if (
      produced.source_cursor != null &&
      sourceCursor != null &&
      Number(produced.source_cursor) !== Number(sourceCursor)
    ) {
      throw new OpsProjectionPublishError("B0/B4 generation/cursors drifted before seal");
    }
  }
  const signed = await signAndVerify(env, envelope);
  const detail = JSON.stringify({
    source_evidence_digest: sourceEvidenceDigest,
    source_cursor: sourceCursor,
    export_cursor: exportCursor,
    applied_cursor: appliedCursor,
    worker_version_id: versionId,
    producer_commit_sha: producerSha,
  });

  const countGuardSql = PROJECTED_CONTENT_TABLES.map(
    (table) => `(SELECT COUNT(*) FROM ${table} WHERE projection_generation_id=?)=?`,
  ).join(" AND ");
  const countGuardBinds: Array<string | number> = [];
  for (const table of PROJECTED_CONTENT_TABLES) {
    countGuardBinds.push(generationId, manifest[table].row_count);
  }

  if (existing?.status === "OPEN") {
    const deletes = PROJECTED_CONTENT_TABLES.map((table) =>
      env.OPS_PROJECTION_DB.prepare(
        `DELETE FROM ${table} WHERE projection_generation_id=?`,
      ).bind(generationId),
    );
    deletes.push(
      env.OPS_PROJECTION_DB.prepare(
        `UPDATE ops_projection_generation
            SET signed_envelope_json=?, issuer_key_id=?, signature=?, detail_json=?
          WHERE generation_id=? AND status='OPEN' AND content_digest=?`,
      ).bind(
        signed.signedJson,
        env.OPS_PROJECTION_SIGNING_KEY_ID,
        signed.signature,
        detail,
        generationId,
        contentDigest,
      ),
    );
    await env.OPS_PROJECTION_DB.batch(deletes);
  } else {
    await env.OPS_PROJECTION_DB.prepare(
      `INSERT INTO ops_projection_generation (
          generation_id, status, source_db_digest, content_digest, generated_at,
          producer_commit_sha, contract_digest, registry_digest,
          coverage_policy_version, sealed_at, signed_envelope_json,
          issuer_key_id, signature, detail_json
       ) VALUES (?, 'OPEN', ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)`,
    )
      .bind(
        generationId,
        sourceDbDigest,
        contentDigest,
        generatedAt,
        producerSha,
        contractDigest,
        registryDigest,
        COVERAGE_POLICY_VERSION,
        signed.signedJson,
        env.OPS_PROJECTION_SIGNING_KEY_ID,
        signed.signature,
        detail,
      )
      .run();
  }

  try {
    const inserts: D1PreparedStatement[] = [];
    for (const table of PROJECTED_CONTENT_TABLES) {
      for (const row of appliedRows[table] ?? []) {
        const keys = Object.keys(row);
        inserts.push(
          env.OPS_PROJECTION_DB.prepare(
            `INSERT INTO ${table} (${keys.join(",")}) VALUES (${keys.map(() => "?").join(",")})`,
          ).bind(...keys.map((key) => row[key] as string | number | null)),
        );
      }
    }
    for (let index = 0; index < inserts.length; index += 20) {
      await env.OPS_PROJECTION_DB.batch(inserts.slice(index, index + 20));
    }

    const reread: Record<string, Record<string, unknown>[]> = {};
    for (const table of PROJECTED_CONTENT_TABLES) {
      const observed = await env.OPS_PROJECTION_DB.prepare(
        `SELECT * FROM ${table} WHERE projection_generation_id=?`,
      )
        .bind(generationId)
        .all<Record<string, unknown>>();
      const expected = appliedRows[table] ?? [];
      const keys = expected[0]
        ? Object.keys(expected[0])
        : ["projection_generation_id"];
      reread[table] = alignRows(observed.results ?? [], keys);
    }
    const observedManifest = await manifestFromRows(reread);
    const observedDigest = await digest({ tables: observedManifest });
    if (observedDigest !== contentDigest) {
      throw new OpsProjectionPublishError("reread content digest does not match signed manifest", {
        generation_id: generationId,
      });
    }
    const exportTableDigest = await digest({
      tables: await manifestFromRows(exported.parsed.tables),
    });
    if (exportTableDigest !== observedDigest) {
      throw new OpsProjectionPublishError("target D1 does not match verified export bytes", {
        generation_id: generationId,
      });
    }
    const metaRow = reread.ops_projection_metadata[0];
    const readSource =
      typeof metaRow?.source_cursor === "number" ? metaRow.source_cursor : null;
    const readExport =
      typeof metaRow?.export_cursor === "number" ? metaRow.export_cursor : null;
    const readApplied =
      typeof metaRow?.applied_cursor === "number" ? metaRow.applied_cursor : null;
    const readStatus = String(metaRow?.status ?? "UNKNOWN");
    if (
      readStatus !== "FRESH" ||
      readSource === null ||
      readExport !== readSource ||
      readApplied !== readSource
    ) {
      return {
        status: "published",
        generation_id: generationId,
        source_evidence_digest: sourceEvidenceDigest,
      };
    }
    const appliedManifest = observedManifest;
    const appliedDigest = observedDigest;

    const finalBatch = await env.OPS_PROJECTION_DB.batch([
      env.OPS_PROJECTION_DB.prepare(
        `UPDATE ops_projection_generation
            SET status='SEALED', sealed_at=?
          WHERE generation_id=? AND status='OPEN' AND content_digest=?
            AND signed_envelope_json IS NOT NULL
            AND issuer_key_id IS NOT NULL
            AND signature IS NOT NULL
            AND ${countGuardSql}`,
      ).bind(generatedAt, generationId, appliedDigest, ...countGuardBinds),
      env.OPS_PROJECTION_DB.prepare(
        `INSERT INTO ops_projection_active (singleton, generation_id, activated_at)
         SELECT 1, ?, ?
           FROM ops_projection_generation
          WHERE generation_id=? AND status='SEALED' AND content_digest=?
            AND ${countGuardSql}
         ON CONFLICT(singleton) DO UPDATE SET
           generation_id=excluded.generation_id,
           activated_at=excluded.activated_at`,
      ).bind(generationId, generatedAt, generationId, appliedDigest, ...countGuardBinds),
    ]);
    if ((finalBatch[0]?.meta?.changes ?? 0) !== 1) {
      throw new OpsProjectionPublishError("OPEN to SEALED did not change exactly one row", {
        generation_id: generationId,
      });
    }
    if ((finalBatch[1]?.meta?.changes ?? 0) !== 1) {
      throw new OpsProjectionPublishError("active pointer did not move", {
        generation_id: generationId,
      });
    }
    const postflight = await env.OPS_PROJECTION_DB.prepare(
      `SELECT g.generation_id, g.status, g.content_digest
         FROM ops_projection_active a
         JOIN ops_projection_generation g ON g.generation_id=a.generation_id
        WHERE a.singleton=1`,
    ).first<{ generation_id: string; status: string; content_digest: string }>();
    if (
      postflight?.generation_id !== generationId ||
      postflight.status !== "SEALED" ||
      postflight.content_digest !== appliedDigest
    ) {
      throw new OpsProjectionPublishError("postflight active generation mismatch", {
        generation_id: generationId,
      });
    }
  } catch (error) {
    const reason = error instanceof OpsProjectionPublishError
      ? error.message
      : "publication failed; prior active generation unchanged";
    throw new OpsProjectionPublishError(reason, {
      generation_id: generationId,
      source_cursor: sourceCursor,
      worker_version_id: versionId,
    });
  }
  return {
    status: "published",
    generation_id: generationId,
    source_evidence_digest: sourceEvidenceDigest,
  };
}

export async function publishOpsProjectionBestEffort(
  env: OpsProjectionEnv,
): Promise<PublishResult> {
  try {
    return await publishOpsProjection(env);
  } catch (error) {
    const fields = error instanceof OpsProjectionPublishError ? error.fields : {};
    const reason = error instanceof Error ? error.message : "unknown";
    const safe = /pkcs8|secret|token|password|spki/i.test(reason)
      ? "ops projection publish failed"
      : reason;
    console.error(JSON.stringify({
      event: "ops_projection_publish_failed",
      generation_id: fields.generation_id ?? null,
      source_cursor: fields.source_cursor ?? null,
      worker_version_id: fields.worker_version_id ?? null,
      reason: safe,
    }));
    throw error;
  }
}
