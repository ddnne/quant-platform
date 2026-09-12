import { env } from "cloudflare:workers";
import { applyD1Migrations, reset } from "cloudflare:test";
import { afterEach, describe, expect, inject, it, vi } from "vitest";
import controlledPilot from "../../../../specs/ready/controlled_pilot_v1.generated.json";
import {
  canonicalDigest,
  canonicalJson,
} from "../../receipt-evidence-authority/src/canonical";
import { canonicalProductBody } from "../../receipt-evidence-authority/src/product_materialization";
import {
  handleExportPaths,
  type ExportEnv,
} from "../src/http_export";
import {
  readReceiptProductBytes,
  RECEIPT_PRODUCT_BYTE_REQUEST,
} from "../src/receipt_product_bytes";
import {
  RECEIPT_PRODUCT_HOST,
  receiptProductSourceOutbound,
} from "../../research-mass-eval/src/receipt_product_source";
import {
  PINNED_RECEIPT_REGISTRY_SCOPE,
  closedReceiptVerifyRegistry,
  type ReceiptVerifyRegistry,
} from "../src/ops_projection_policy";

const registries = vi.hoisted(() => ({
  production: {} as Record<string, unknown>,
  staging: {} as Record<string, unknown>,
  originals: {
    production: {} as Record<string, unknown>,
    staging: {} as Record<string, unknown>,
  },
}));

async function mockRegistry(
  environment: "production" | "staging",
  importOriginal: () => Promise<unknown>,
): Promise<{ default: Record<string, unknown> }> {
  const imported = await importOriginal() as { default?: Record<string, unknown> };
  const document = { ...(imported.default ?? imported as Record<string, unknown>) };
  registries.originals[environment] = { ...document };
  Object.assign(registries[environment], document);
  return { default: registries[environment] };
}

vi.mock(
  "../../../../packages/data_plane/data_contracts/receipt_verify_public_keys.production.json",
  async (importOriginal) => mockRegistry("production", importOriginal),
);
vi.mock(
  "../../../../packages/data_plane/data_contracts/receipt_verify_public_keys.staging.json",
  async (importOriginal) => mockRegistry("staging", importOriginal),
);

function installRegistry(
  environment: "production" | "staging",
  document: object,
): void {
  const target = registries[environment];
  for (const key of Object.keys(target)) delete target[key];
  Object.assign(target, structuredClone(document));
}

function restoreRegistries(): void {
  for (const environment of ["production", "staging"] as const) {
    const target = registries[environment];
    for (const key of Object.keys(target)) delete target[key];
    Object.assign(target, structuredClone(registries.originals[environment]));
  }
}

const EXPORT_TOKEN = "premium-test-export-token-do-not-leak";
const runtimeEnv = env as {
  DB: D1Database;
  OPS_PROJECTION_ENVIRONMENT: string;
  RAW_BUCKET: R2Bucket;
  STRUCTURED_BUCKET: R2Bucket;
};
const migrations = inject<Array<{ name: string; queries: string[] }>>(
  "premiumD1Migrations",
);

function b64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

async function sha256Prefixed(bytes: Uint8Array): Promise<string> {
  const raw = await crypto.subtle.digest("SHA-256", bytes);
  return "sha256:" + Array.from(new Uint8Array(raw), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

async function closedActiveStagingRegistry(
  publicKeyRaw: Uint8Array,
): Promise<ReceiptVerifyRegistry> {
  const pin = PINNED_RECEIPT_REGISTRY_SCOPE.staging;
  const body = {
    schema_version: 3,
    purpose: "receipt_verification",
    generation: pin.generation,
    authority_status: "ACTIVE" as const,
    environment: "staging",
    authority_instance_digest: pin.authority_instance_digest,
    prior_registry_digest: "sha256:" + "10".repeat(32),
    keys: [{
      key_id: "receipt-test-v1",
      algorithm: "Ed25519",
      public_key_base64: b64(publicKeyRaw),
      status: "active",
    }],
  };
  const closed = await closedReceiptVerifyRegistry(
    { ...body, registry_digest: await canonicalDigest(body) },
    "staging",
  );
  if (!closed) throw new Error("test receipt registry is not closed");
  return closed;
}

function barsScope(start = "2026-08-01", end = "2026-08-31") {
  return {
    coverage_mode: "trading_calendar",
    expected_frequency: "trading_day",
    expected_item_unit: "source_query",
    segment_end: end,
    segment_start: start,
    universe_rule: "all_listed_equities_at_event_date",
    segment_granularity: "calendar_month",
  };
}

function calendarScope(start = "2026-08-01", end = "2026-08-31") {
  return {
    coverage_mode: "calendar",
    expected_frequency: "calendar_day",
    expected_item_unit: "source_query",
    segment_end: end,
    segment_start: start,
    universe_rule: "jpx_calendar_days",
    segment_granularity: "calendar_month",
  };
}

async function seedGovernedObjects() {
  const artifact = new TextEncoder().encode(canonicalProductBody([
    {
      source: "jquants",
      dataset: "equities_bars_daily",
      natural_key: "k1",
      event_time: "2026-08-01T00:00:00Z",
      available_at: "2026-08-01T00:00:00Z",
      ingested_at: "2026-08-01T00:00:00Z",
      payload: "{}",
      raw_payload: "{}",
      row_digest: "sha256:" + "11".repeat(32),
    },
    {
      source: "jquants",
      dataset: "equities_bars_daily",
      natural_key: "k2",
      event_time: "2026-08-02T00:00:00Z",
      available_at: "2026-08-02T00:00:00Z",
      ingested_at: "2026-08-01T00:00:00Z",
      payload: "{}",
      raw_payload: "{}",
      row_digest: "sha256:" + "22".repeat(32),
    },
  ]));
  const manifest = new TextEncoder().encode(JSON.stringify({
    format: "product-manifest/v1",
    artifact_body: new TextDecoder().decode(artifact),
  }));
  const rawManifest = new TextEncoder().encode('{"format":"jquants-raw-manifest/v1"}');
  return {
    structured: await sha256Prefixed(artifact),
    artifact,
    manifestDigest: await sha256Prefixed(manifest),
    rawDigest: "sha256:" + "aa".repeat(32),
    rawFileDigest: await sha256Prefixed(rawManifest),
    artifactBytes: artifact.byteLength,
    manifestBytes: manifest.byteLength,
    rawBytes: rawManifest.byteLength,
  };
}

async function canonicalV3Claims(
  objects: Awaited<ReturnType<typeof seedGovernedObjects>>,
  overrides: Record<string, unknown> = {},
): Promise<Record<string, unknown>> {
  const base = {
    environment: "staging",
    authority_instance_digest: PINNED_RECEIPT_REGISTRY_SCOPE.staging.authority_instance_digest,
    coverage_policy_version: "collection-coverage/v3",
    source: "jquants",
    contract_id: "jquants_premium_core",
    dataset: "equities_bars_daily",
    segment_id: "2026-08",
    segment_start: "2026-08-01",
    segment_end: "2026-08-31",
    receipt_issue_digest: "sha256:" + "cc".repeat(32),
    artifact_key: "artifact.jsonl",
    artifact_byte_count: objects.artifactBytes,
    manifest_key: "manifest.json",
    manifest_byte_count: objects.manifestBytes,
    raw_manifest_key: "raw.json",
    raw_manifest_byte_count: objects.rawBytes,
    raw_byte_count: 2,
    natural_key_digest: "sha256:" + "11".repeat(32),
    expected_items: 1,
    observed_items: 1,
    raw_page_count: 1,
    raw_count: 2,
    structured_count: 2,
    status: "SUCCESS",
    error: null,
    pagination_exhausted: true,
    discovery_exhausted: true,
    source_request_digest: "sha256:" + "ff".repeat(32),
    raw_manifest_digest: objects.rawDigest,
    raw_digest: "sha256:" + "bb".repeat(32),
    structured_digest: objects.structured,
    structured_generation: 1,
    run_id: 1,
    checked_at: "2026-08-01T00:00:00Z",
    extra_digests: {
      acquisition_collection_manifest_file_digest: objects.rawFileDigest,
      acquisition_collection_digest: "sha256:" + "12".repeat(32),
      acquisition_terminal_chain_digest: "sha256:" + "13".repeat(32),
      product_artifact_digest: objects.structured,
      product_manifest_digest: objects.manifestDigest,
    },
    ...overrides,
  };
  const expectedScope = overrides.expected_scope ?? barsScope(
    String(base.segment_start),
    String(base.segment_end),
  );
  const scope = {
    environment: base.environment,
    authority_instance_digest: base.authority_instance_digest,
    coverage_policy_version: base.coverage_policy_version,
    source: base.source,
    contract_id: base.contract_id,
    dataset: base.dataset,
    segment_id: base.segment_id,
    segment_start: base.segment_start,
    segment_end: base.segment_end,
    expected_scope: expectedScope,
    expected_items: base.expected_items,
  };
  const scopeDigest = await canonicalDigest(scope);
  const observation = {
    ...scope,
    observed_items: base.observed_items,
    raw_page_count: base.raw_page_count,
    raw_count: base.raw_count,
    structured_count: base.structured_count,
    status: base.status,
    error: base.error,
    pagination_exhausted: base.pagination_exhausted,
    discovery_exhausted: base.discovery_exhausted,
    receipt_issue_digest: base.receipt_issue_digest,
    artifact_key: base.artifact_key,
    artifact_byte_count: base.artifact_byte_count,
    manifest_key: base.manifest_key,
    manifest_byte_count: base.manifest_byte_count,
    raw_manifest_key: base.raw_manifest_key,
    raw_manifest_byte_count: base.raw_manifest_byte_count,
    raw_byte_count: base.raw_byte_count,
    natural_key_digest: base.natural_key_digest,
    source_request_digest: base.source_request_digest,
    raw_manifest_digest: base.raw_manifest_digest,
    raw_digest: base.raw_digest,
    structured_digest: base.structured_digest,
    structured_generation: base.structured_generation,
    scope_digest: scopeDigest,
    run_id: base.run_id,
    checked_at: base.checked_at,
    extra_digests: base.extra_digests,
  };
  return {
    ...observation,
    observation_digest: await canonicalDigest(observation),
    version: "signed-receipt-claims/v3",
    parser_normalizer_version: "coverage-receipt/v4-ed25519-closure",
    issuer_id: "receipt-test-v1",
    issued_at: "2026-08-01T00:00:00Z",
  };
}

async function signV3Claims(
  pair: CryptoKeyPair,
  claims: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const body = canonicalJson(claims);
  const bodyBytes = new TextEncoder().encode(body);
  const signature = new Uint8Array(
    await crypto.subtle.sign("Ed25519", pair.privateKey, bodyBytes),
  );
  const extras = claims.extra_digests as Record<string, string>;
  return {
    eligibility: "TRUSTED_COLLECTION",
    issuer_class: "SignedReceiptAuthority",
    issuer_key_id: claims.issuer_id,
    issuer_id: claims.issuer_id,
    environment: claims.environment,
    authority_instance_digest: claims.authority_instance_digest,
    parser_normalizer_version: claims.parser_normalizer_version,
    signed_body_b64: b64(bodyBytes),
    signature: `ed25519:${b64(signature)}`,
    body_digest: await sha256Prefixed(bodyBytes),
    issued_at: claims.issued_at,
    checked_at: claims.checked_at,
    source_request_digest: claims.source_request_digest,
    raw_manifest_digest: claims.raw_manifest_digest,
    raw: claims.raw_digest,
    structured_generation: claims.structured_generation,
    structured_digest: claims.structured_digest,
    scope_digest: claims.scope_digest,
    observation_digest: claims.observation_digest,
    extra_digests: extras,
    ...extras,
  };
}

function interceptCoverage(
  db: D1Database,
  mutate: () => Promise<void>,
): D1Database {
  let coverageQueries = 0;
  const wrapSession = (target: D1Database | D1DatabaseSession): D1DatabaseSession => {
    const session = {
      prepare(sql: string) {
        const stmt = target.prepare(sql);
        return {
          bind(...args: unknown[]) {
            const bound = stmt.bind(...args);
            const before = async () => {
              if (sql.includes("FROM coverage_segments")) {
                coverageQueries += 1;
                if (coverageQueries === 2) await mutate();
              }
            };
            return {
              bind: (...more: unknown[]) => bound.bind(...more),
              all: async () => {
                await before();
                return bound.all();
              },
              first: async () => {
                await before();
                return bound.first();
              },
              run: () => bound.run(),
            };
          },
        };
      },
      batch: (statements: D1PreparedStatement[]) => target.batch(statements),
      getBookmark: () =>
        "getBookmark" in target && typeof target.getBookmark === "function"
          ? target.getBookmark()
          : null,
    };
    return session as unknown as D1DatabaseSession;
  };
  return {
    prepare: (sql: string) => wrapSession(db).prepare(sql),
    batch: (statements: D1PreparedStatement[]) => db.batch(statements),
    exec: (query: string) => db.exec(query),
    withSession: () => wrapSession(
      typeof db.withSession === "function" ? db.withSession("first-primary") : db,
    ),
  } as unknown as D1Database;
}

type SeedSpec = {
  dataset: string;
  segmentId: string;
  runId: number;
  operationId: string;
  nonce: string;
  requestDigest: string;
  expectedScope: Record<string, unknown>;
  artifactKey: string;
  manifestKey: string;
  rawKey: string;
  envelope: Record<string, unknown>;
  objects: Awaited<ReturnType<typeof seedGovernedObjects>>;
  requestState?: "FINALIZED" | "PREPARED";
  artifactDigest?: string;
};

async function seedComplete(db: D1Database, spec: SeedSpec): Promise<void> {
  const expectedScopeJson = JSON.stringify(spec.expectedScope);
  const receiptDigest = await canonicalDigest({
    source: "jquants",
    dataset: spec.dataset,
    segment_id: spec.segmentId,
    segment_start: "2026-08-01",
    segment_end: "2026-08-31",
    expected_scope: spec.expectedScope,
    expected_items: 1,
    observed_items: 1,
    raw_page_count: 1,
    raw_row_count: 2,
    structured_row_count: 2,
    pagination_exhausted: true,
    digests: spec.envelope,
    run_id: spec.runId,
    status: "SUCCESS",
    error: null,
    checked_at: "2026-08-01T00:00:00Z",
  });
  const artifactDigest = spec.artifactDigest ?? spec.objects.structured;
  await db.prepare(
    `INSERT INTO ingestion_run_log(id,ran_at,source,runtime,status,detail)
     VALUES (?,'2026-08-01T00:00:00Z','jquants','cloud','ok',NULL)`,
  ).bind(spec.runId).run();
  await db.prepare(
    `INSERT INTO coverage_segments(
       source,dataset,segment_id,policy_version,segment_start,segment_end,expected_scope,
       expected_items,status,receipt_run_id,evaluated_at,detail_json
     ) VALUES (
       'jquants',?,?,'collection-coverage/v3','2026-08-01','2026-08-31',?,1,'COMPLETE',?,
       '2026-08-01T00:00:00Z','{}'
     )`,
  ).bind(spec.dataset, spec.segmentId, expectedScopeJson, spec.runId).run();
  await db.prepare(
    `INSERT INTO receipt_authority_operations(
       operation_id,request_digest,run_id,environment,source,contract_id,dataset,segment_id,
       segment_start,segment_end,state,checked_at,updated_at,raw_manifest_key,
       raw_manifest_digest,raw_page_count,raw_row_count,raw_bytes
     ) VALUES (
       ?,?,?,'staging','jquants','jquants_premium_core',?,?,
       '2026-08-01','2026-08-31','COLLECTING','2026-08-01T00:00:00Z','2026-08-01T00:00:00Z',
       ?,?,1,2,2
     )`,
  ).bind(
    spec.operationId,
    spec.requestDigest,
    spec.runId,
    spec.dataset,
    spec.segmentId,
    spec.rawKey,
    spec.objects.rawDigest,
  ).run();
  await db.prepare(
    `INSERT INTO receipt_authority_structured_rows(
       operation_id,natural_key,source,dataset,event_time,available_at,ingested_at,payload,raw_payload,row_digest
     ) VALUES
       (?,'k1','jquants',?,'2026-08-01','2026-08-01','2026-08-01T00:00:00Z','{}','{}',?),
       (?,'k2','jquants',?,'2026-08-02','2026-08-02','2026-08-01T00:00:00Z','{}','{}',?)`,
  ).bind(
    spec.operationId,
    spec.dataset,
    "sha256:" + "11".repeat(32),
    spec.operationId,
    spec.dataset,
    "sha256:" + "22".repeat(32),
  ).run();
  await db.prepare(
    `INSERT INTO receipt_product_materializations(
       operation_id,run_id,source,dataset,segment_id,artifact_key,artifact_digest,artifact_body,
       row_count,byte_count,manifest_key,manifest_digest,raw_manifest_key,raw_manifest_digest,
       raw_page_count,raw_row_count,raw_bytes,committed_at
     ) VALUES (
       ?,?,'jquants',?,?,?,?,'',
       2,?, ?,?,?,?,
       1,2,2,'2026-08-01T00:00:00Z'
     )`,
  ).bind(
    spec.operationId,
    spec.runId,
    spec.dataset,
    spec.segmentId,
    spec.artifactKey,
    artifactDigest,
    spec.objects.artifactBytes,
    spec.manifestKey,
    spec.objects.manifestDigest,
    spec.rawKey,
    spec.objects.rawDigest,
  ).run();
  await db.prepare(
    `UPDATE receipt_authority_operations
        SET state='STRUCTURED_COMMITTED',
            structured_manifest_key=?,
            structured_digest=?
      WHERE operation_id=?`,
  ).bind(spec.manifestKey, spec.objects.structured, spec.operationId).run();
  await db.prepare(
    `INSERT INTO collection_receipts(
       source,dataset,segment_id,segment_start,segment_end,expected_scope,expected_items,
       observed_items,raw_page_count,raw_row_count,structured_row_count,pagination_exhausted,
       digests_json,run_id,status,error,checked_at
     ) VALUES (
       'jquants',?,?,'2026-08-01','2026-08-31',?,1,
       1,1,2,2,1,?,?,'SUCCESS',NULL,'2026-08-01T00:00:00Z'
     )`,
  ).bind(
    spec.dataset,
    spec.segmentId,
    expectedScopeJson,
    JSON.stringify(spec.envelope),
    spec.runId,
  ).run();
  await db.prepare(
    `UPDATE receipt_authority_operations
        SET state='RECEIPT_COMMITTED', receipt_digest=?
      WHERE operation_id=?`,
  ).bind(receiptDigest, spec.operationId).run();
  if (spec.requestState === "PREPARED") {
    await db.prepare(
      `INSERT INTO receipt_authority_requests(
         operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,state,
         receipt_digest,created_at,updated_at
       ) VALUES (
         ?,?,'staging','jquants','jquants_premium_core',?,?,'PREPARED',
         NULL,'2026-08-01T00:00:00Z','2026-08-01T00:00:00Z'
       )`,
    ).bind(spec.operationId, spec.nonce, spec.dataset, spec.segmentId).run();
    return;
  }
  await db.prepare(
    `INSERT INTO receipt_authority_requests(
       operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,state,
       receipt_digest,created_at,updated_at
     ) VALUES (
       ?,?,'staging','jquants','jquants_premium_core',?,?,'FINALIZED',
       ?,'2026-08-01T00:00:00Z','2026-08-01T00:00:00Z'
     )`,
  ).bind(spec.operationId, spec.nonce, spec.dataset, spec.segmentId, receiptDigest).run();
}

async function seedBase(db: D1Database): Promise<void> {
  await db.prepare(
    `INSERT INTO ingestion_change_log(
       table_name,source,dataset,natural_key,event_time,available_at,ingested_at,payload,changed_at
     ) VALUES ('jquants_daily_bars','jquants','equities_bars','1301','2026-08-01','2026-08-01','2026-08-01','{}','2026-08-01T00:00:00Z')`,
  ).run();
  await db.prepare("UPDATE ingestion_change_log SET change_seq=?").bind(12).run();
}

function inputRequest(
  segments: Array<{ dataset: string; segment_id: string }>,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    schema_version: "receipt-product-input-request/v1",
    profile_id: controlledPilot.profile_id,
    profile_digest: controlledPilot.profile_digest,
    dependency_closure_digest: controlledPilot.dependency_closure_digest,
    segments,
    ...extra,
  };
}

function exportEnv(db: D1Database = runtimeEnv.DB): ExportEnv {
  return {
    DB: db,
    DATA_EXPORT_TOKEN: EXPORT_TOKEN,
    OPS_PROJECTION_ENVIRONMENT: runtimeEnv.OPS_PROJECTION_ENVIRONMENT,
  };
}

function postReceiptProducts(
  env: ExportEnv,
  body: unknown,
  headers: HeadersInit = { "X-Ingestion-Token": EXPORT_TOKEN },
): Promise<Response | null> {
  return handleExportPaths(
    new Request("https://ingestion-premium.test/v1/export/receipt-products", {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: typeof body === "string" || body instanceof Uint8Array
        ? body
        : JSON.stringify(body),
    }),
    env,
  );
}

async function seedPair(options?: {
  calRequest?: "FINALIZED" | "PREPARED";
  barsArtifactDigest?: string;
}) {
  await applyD1Migrations(runtimeEnv.DB, migrations);
  await seedBase(runtimeEnv.DB);
  const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
  const registry = await closedActiveStagingRegistry(raw);
  const objects = await seedGovernedObjects();
  const barsClaims = await canonicalV3Claims(objects, {
    artifact_key: "bars-artifact.jsonl",
    manifest_key: "bars-manifest.json",
    raw_manifest_key: "bars-raw.json",
    receipt_issue_digest: "sha256:" + "cc".repeat(32),
    run_id: 1,
    structured_generation: 1,
    natural_key_digest: await canonicalDigest({
      operation_id: "op-bars",
      natural_keys: ["k1", "k2"],
    }),
  });
  const calClaims = await canonicalV3Claims(objects, {
    dataset: "markets_calendar",
    expected_scope: calendarScope(),
    artifact_key: "cal-artifact.jsonl",
    manifest_key: "cal-manifest.json",
    raw_manifest_key: "cal-raw.json",
    receipt_issue_digest: "sha256:" + "cd".repeat(32),
    run_id: 2,
    structured_generation: 2,
    natural_key_digest: await canonicalDigest({
      operation_id: "op-cal",
      natural_keys: ["k1", "k2"],
    }),
  });
  await seedComplete(runtimeEnv.DB, {
    dataset: "equities_bars_daily",
    segmentId: "2026-08",
    runId: 1,
    operationId: "op-bars",
    nonce: "ab".repeat(32),
    requestDigest: "sha256:" + "cc".repeat(32),
    expectedScope: barsScope(),
    artifactKey: "bars-artifact.jsonl",
    manifestKey: "bars-manifest.json",
    rawKey: "bars-raw.json",
    envelope: await signV3Claims(pair, barsClaims),
    objects,
    artifactDigest: options?.barsArtifactDigest,
  });
  await seedComplete(runtimeEnv.DB, {
    dataset: "markets_calendar",
    segmentId: "2026-08",
    runId: 2,
    operationId: "op-cal",
    nonce: "ac".repeat(32),
    requestDigest: "sha256:" + "cd".repeat(32),
    expectedScope: calendarScope(),
    artifactKey: "cal-artifact.jsonl",
    manifestKey: "cal-manifest.json",
    rawKey: "cal-raw.json",
    envelope: await signV3Claims(pair, calClaims),
    objects,
    requestState: options?.calRequest,
  });
  return { registry, objects };
}

afterEach(async () => {
  restoreRegistries();
  await reset();
});

describe("POST /v1/export/receipt-products workerd D1", () => {
  it("describes multi-segment evidence in sorted order with stable digest and plane metadata", async () => {
    const { registry } = await seedPair();
    installRegistry("staging", registry);
    const env = exportEnv();
    const reverse = await postReceiptProducts(env, inputRequest([
      { dataset: "markets_calendar", segment_id: "2026-08" },
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
    ]));
    const forward = await postReceiptProducts(env, inputRequest([
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
      { dataset: "markets_calendar", segment_id: "2026-08" },
    ]));
    expect(reverse?.status).toBe(200);
    expect(forward?.status).toBe(200);
    const left = await reverse!.json() as Record<string, unknown>;
    const right = await forward!.json() as Record<string, unknown>;
    expect(left.status).toBe("DESCRIBED");
    expect(left.schema_version).toBe("receipt-product-input-set/v1");
    expect(left.scope_semantics).toBe("requested_segments_only");
    expect(left.profile_completeness).toBe("NOT_CHECKED");
    expect(left.physical_availability).toBe("NOT_CHECKED");
    expect(left.readiness).toBe("NOT_EVALUATED");
    expect(left.environment).toBe("staging");
    expect(left.coverage_policy_version).toBe("collection-coverage/v3");
    expect(left.receipt_registry_digest).toBe(registry.registry_digest);
    const segments = left.segments as Array<Record<string, unknown>>;
    expect(segments.map((row) => `${row.dataset}:${row.segment_id}`)).toEqual([
      "equities_bars_daily:2026-08",
      "markets_calendar:2026-08",
    ]);
    expect(segments[0]!.product).toMatchObject({
      schema: "jquants_records/v1",
      plane: "structured",
      artifact_key: "bars-artifact.jsonl",
      manifest_plane: "authority_evidence",
      raw_page_count: 1,
      raw_bytes: 2,
    });
    expect(segments[0]!.product).not.toHaveProperty("artifact_body");
    expect(left.input_set_digest).toBe(right.input_set_digest);
    expect(left.segments).toEqual(right.segments);
    const observation = left.read_observation as Record<string, unknown>;
    expect(observation.source_change_seq_before).toBe(12);
    expect(observation.source_change_seq_after).toBe(12);
    const identity = { ...left };
    delete identity.input_set_digest;
    delete identity.read_observation;
    expect(left.input_set_digest).toBe(await canonicalDigest(identity));
  });

  it("holds on current incomplete coverage and never falls back to an older successful receipt", async () => {
    const { registry } = await seedPair();
    await runtimeEnv.DB.prepare(
      `INSERT INTO ingestion_run_log(id,ran_at,source,runtime,status,detail)
       VALUES (9,'2026-08-02T00:00:00Z','jquants','cloud','ok',NULL)`,
    ).run();
    await runtimeEnv.DB.prepare(
      `UPDATE coverage_segments
          SET receipt_run_id=9, evaluated_at='2026-08-02T00:00:00Z'
        WHERE dataset='equities_bars_daily'`,
    ).run();
    await runtimeEnv.DB.prepare(
      `INSERT INTO collection_receipts(
         source,dataset,segment_id,segment_start,segment_end,expected_scope,expected_items,
         observed_items,raw_page_count,raw_row_count,structured_row_count,pagination_exhausted,
         digests_json,run_id,status,error,checked_at
       ) VALUES (
         'jquants','equities_bars_daily','2026-08','2026-08-01','2026-08-31','{}',1,
         1,1,2,2,1,'{}',9,'FAILED','pending','2026-08-02T00:00:00Z'
       )`,
    ).run();
    installRegistry("staging", registry);
    const res = await postReceiptProducts(exportEnv(), inputRequest([
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
    ]));
    expect(res?.status).toBe(409);
    const body = await res!.json() as Record<string, unknown>;
    expect(body.status).toBe("HOLD");
    expect(body.hold_reason).toBe("MISSING_ROW");
    expect(body.hold_selector).toEqual({
      dataset: "equities_bars_daily",
      segment_id: "2026-08",
    });
    expect(body).not.toHaveProperty("input_set_digest");
    expect(body).not.toHaveProperty("segments");
  });

  it("rejects receipt/product/operation/request mismatches as HOLD", async () => {
    const { registry } = await seedPair({
      barsArtifactDigest: "sha256:" + "99".repeat(32),
    });
    installRegistry("staging", registry);
    const mismatch = await postReceiptProducts(exportEnv(), inputRequest([
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
    ]));
    expect(mismatch?.status).toBe(409);
    expect(await mismatch!.json()).toMatchObject({
      status: "HOLD",
      hold_reason: "UNTRUSTED_CHAIN",
      hold_selector: { dataset: "equities_bars_daily", segment_id: "2026-08" },
    });

    await reset();
    const prepared = await seedPair({ calRequest: "PREPARED" });
    installRegistry("staging", prepared.registry);
    const unfinalized = await postReceiptProducts(exportEnv(), inputRequest([
      { dataset: "markets_calendar", segment_id: "2026-08" },
    ]));
    expect(unfinalized?.status).toBe(409);
    expect(await unfinalized!.json()).toMatchObject({
      status: "HOLD",
      hold_reason: "UNFINALIZED_REQUEST",
      hold_selector: { dataset: "markets_calendar", segment_id: "2026-08" },
    });
  });

  it("HOLDs when coverage identity changes with an unchanged change-feed, and conflicts expected digest", async () => {
    const { registry } = await seedPair();
    installRegistry("staging", registry);
    const intercepted = interceptCoverage(runtimeEnv.DB, async () => {
      await runtimeEnv.DB.prepare(
        `UPDATE coverage_segments
            SET evaluated_at='2026-08-01T00:00:01Z'
          WHERE dataset='equities_bars_daily'`,
      ).run();
    });
    const hold = await postReceiptProducts(exportEnv(intercepted), inputRequest([
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
      { dataset: "markets_calendar", segment_id: "2026-08" },
    ]));
    expect(hold?.status).toBe(409);
    expect(await hold!.json()).toMatchObject({
      status: "HOLD",
      hold_reason: "REFERENCE_CHANGED",
      hold_selector: { dataset: "equities_bars_daily", segment_id: "2026-08" },
    });
    const seq = await runtimeEnv.DB.prepare(
      "SELECT MAX(change_seq) AS n FROM ingestion_change_log",
    ).first<{ n: number }>();
    expect(seq?.n).toBe(12);

    const described = await postReceiptProducts(exportEnv(), inputRequest([
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
      { dataset: "markets_calendar", segment_id: "2026-08" },
    ]));
    const describedBody = await described!.json() as { input_set_digest: string };
    const conflict = await postReceiptProducts(exportEnv(), inputRequest(
      [{ dataset: "equities_bars_daily", segment_id: "2026-08" }],
      { expected_current_digest: describedBody.input_set_digest },
    ));
    expect(conflict?.status).toBe(409);
    const changed = await conflict!.json() as Record<string, unknown>;
    expect(changed.error).toBe("INPUT_SET_CHANGED");
    expect(changed.current_digest).not.toBe(describedBody.input_set_digest);
    expect(changed).not.toHaveProperty("segments");
  });

  it("never returns a partial DESCRIBED set when a selector or metadata bound fails", async () => {
    const { registry } = await seedPair();
    installRegistry("staging", registry);
    const missing = await postReceiptProducts(exportEnv(), inputRequest([
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
      { dataset: "fins_summary", segment_id: "2026-08" },
    ]));
    expect(missing?.status).toBe(409);
    expect(await missing!.json()).toMatchObject({
      status: "HOLD",
      hold_reason: "MISSING_ROW",
      hold_selector: { dataset: "fins_summary", segment_id: "2026-08" },
    });
    const missingBody = await (await postReceiptProducts(exportEnv(), inputRequest([
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
      { dataset: "fins_summary", segment_id: "2026-08" },
    ])))!.json() as Record<string, unknown>;
    expect(missingBody).not.toHaveProperty("input_set_digest");
    expect(missingBody).not.toHaveProperty("segments");

    for (const dataset of [
      "equities_master",
      "fins_summary",
      "indices_bars_daily_topix",
    ]) {
      await runtimeEnv.DB.exec(
        "INSERT INTO coverage_segments(source,dataset,segment_id,policy_version,segment_start,segment_end,expected_scope,expected_items,status,receipt_run_id,evaluated_at,detail_json) VALUES "
          + `('jquants','${dataset}','2026-08','collection-coverage/v3','2026-08-01','2026-08-31',replace(hex(zeroblob(800000)),'00',char(233)),1,'COMPLETE',1,'2026-08-01T00:00:00Z','{}')`,
      );
    }
    const oversized = await postReceiptProducts(exportEnv(), inputRequest([
      { dataset: "equities_master", segment_id: "2026-08" },
      { dataset: "fins_summary", segment_id: "2026-08" },
      { dataset: "indices_bars_daily_topix", segment_id: "2026-08" },
    ]));
    expect(oversized?.status).toBe(409);
    expect(await oversized!.json()).toMatchObject({
      status: "HOLD",
      hold_reason: "READ_BUDGET",
      hold_selector: { dataset: "equities_master", segment_id: "2026-08" },
    });
  });

  it("rejects auth, query-token-only, unknown fields, duplicate selectors, profile pins, and body limits", async () => {
    const env = exportEnv();
    const unauth = await postReceiptProducts(env, inputRequest([
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
    ]), {});
    expect(unauth?.status).toBe(401);
    expect(await unauth!.json()).toEqual({ error: "unauthorized" });

    const queryToken = await handleExportPaths(
      new Request(
        `https://ingestion-premium.test/v1/export/receipt-products?token=${EXPORT_TOKEN}`,
        {
          method: "POST",
          body: JSON.stringify(inputRequest([
            { dataset: "equities_bars_daily", segment_id: "2026-08" },
          ])),
        },
      ),
      env,
    );
    expect(queryToken?.status).toBe(401);

    const get = await handleExportPaths(
      new Request("https://ingestion-premium.test/v1/export/receipt-products", {
        method: "GET",
        headers: { "X-Ingestion-Token": EXPORT_TOKEN },
      }),
      env,
    );
    expect(get?.status).toBe(405);

    const unknown = await postReceiptProducts(env, {
      ...inputRequest([{ dataset: "equities_bars_daily", segment_id: "2026-08" }]),
      environment: "production",
    });
    expect(unknown?.status).toBe(400);
    expect(await unknown!.json()).toEqual({ error: "unknown field" });

    const duplicate = await postReceiptProducts(env, inputRequest([
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
    ]));
    expect(duplicate?.status).toBe(400);
    expect(await duplicate!.json()).toEqual({ error: "duplicate selector" });

    const pins = await postReceiptProducts(env, {
      ...inputRequest([{ dataset: "equities_bars_daily", segment_id: "2026-08" }]),
      profile_digest: "sha256:" + "00".repeat(32),
    });
    expect(pins?.status).toBe(400);
    expect(await pins!.json()).toEqual({ error: "profile pin mismatch" });

    const outside = await postReceiptProducts(env, inputRequest([
      { dataset: "equities_bars_daily_am", segment_id: "2026-08" },
    ]));
    expect(outside?.status).toBe(400);
    expect(await outside!.json()).toEqual({ error: "dataset not in profile" });

    const oversized = await postReceiptProducts(env, new Uint8Array(64 * 1024 + 1));
    expect(oversized?.status).toBe(400);
    expect(await oversized!.json()).toEqual({ error: "body too large" });

    const pending = await postReceiptProducts(env, inputRequest([
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
    ]));
    expect(pending?.status).toBe(409);
    expect(await pending!.json()).toMatchObject({
      status: "HOLD",
      hold_reason: "PENDING_REGISTRY",
    });
  });
});

function masterScope(start = "2026-08-01", end = "2026-08-31") {
  return {
    coverage_mode: "scd2_event_sourcing",
    expected_frequency: "trading_day",
    expected_item_unit: "source_query",
    segment_end: end,
    segment_start: start,
    universe_rule: "all_listed_equities_at_event_date",
    segment_granularity: "calendar_month",
  };
}

function byteRequest(
  dataset: string,
  segmentId: string,
  operationId: string,
  receiptDigest: string,
  resource: "product_artifact" | "raw_collection_manifest" | "official_calendar_raw",
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    schema_version: RECEIPT_PRODUCT_BYTE_REQUEST,
    profile_id: controlledPilot.profile_id,
    profile_digest: controlledPilot.profile_digest,
    dependency_closure_digest: controlledPilot.dependency_closure_digest,
    dataset,
    segment_id: segmentId,
    operation_id: operationId,
    receipt_digest: receiptDigest,
    resource,
    ...extra,
  };
}

describe("original receipt product bytes workerd R2", () => {
  it("streams signed product bytes and refuses a wrong receipt identity or missing object", async () => {
    const { registry, objects } = await seedPair();
    installRegistry("staging", registry);
    await runtimeEnv.STRUCTURED_BUCKET.put("bars-artifact.jsonl", objects.artifact);
    const described = await postReceiptProducts(exportEnv(), inputRequest([
      { dataset: "markets_calendar", segment_id: "2026-08" },
      { dataset: "equities_bars_daily", segment_id: "2026-08" },
    ]));
    expect(described?.status).toBe(200);
    const body = await described!.json() as {
      input_set_digest: string;
      segments: Array<{
        dataset: string;
        segment_id: string;
        operation_id: string;
        receipt_digest: string;
      }>;
    };
    const segment = body.segments.find((row) =>
      row.dataset === "equities_bars_daily" && row.segment_id === "2026-08"
    );
    expect(segment).toBeDefined();
    const payload = byteRequest(
      "equities_bars_daily",
      "2026-08",
      segment.operation_id,
      segment.receipt_digest,
      "product_artifact",
    );
    const encoded = JSON.stringify(payload);
    const streamed = await receiptProductSourceOutbound(
      new Request(`http://${RECEIPT_PRODUCT_HOST}/v1/read-receipt-product-bytes`, {
        method: "POST",
        headers: { "content-length": String(encoded.length) },
        body: encoded,
      }),
      {
        INGESTION_PREMIUM: {
          read_receipt_product_bytes: (request) =>
            readReceiptProductBytes(runtimeEnv, request),
        },
      },
    );
    expect(streamed.status).toBe(200);
    expect(new Uint8Array(await streamed.arrayBuffer())).toEqual(objects.artifact);

    const changed = await readReceiptProductBytes(runtimeEnv, byteRequest(
      "equities_bars_daily",
      "2026-08",
      segment.operation_id,
      "sha256:" + "00".repeat(32),
      "product_artifact",
    ));
    expect(changed.status).toBe(409);
    expect(await changed.json()).toMatchObject({
      status: "HOLD",
      hold_reason: "UNTRUSTED_CHAIN",
    });

    await runtimeEnv.STRUCTURED_BUCKET.delete("bars-artifact.jsonl");
    const missing = await readReceiptProductBytes(runtimeEnv, byteRequest(
      "equities_bars_daily",
      "2026-08",
      segment.operation_id,
      segment.receipt_digest,
      "product_artifact",
    ));
    expect(missing.status).toBe(409);
    expect(await missing.json()).toMatchObject({
      status: "HOLD",
      hold_reason: "READ_FAILURE",
    });

    const nonMaster = await readReceiptProductBytes(runtimeEnv, byteRequest(
      "equities_bars_daily",
      "2026-08",
      segment.operation_id,
      segment.receipt_digest,
      "official_calendar_raw",
    ));
    expect(nonMaster.status).toBe(400);
    expect(await nonMaster.json()).toEqual({
      error: "official calendar is master-only",
    });
  });

  it("returns original calendar bytes and refuses key-reordered re-encoding", async () => {
    await applyD1Migrations(runtimeEnv.DB, migrations);
    await seedBase(runtimeEnv.DB);
    const pair = await crypto.subtle.generateKey(
      { name: "Ed25519" },
      true,
      ["sign", "verify"],
    );
    const raw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
    const registry = await closedActiveStagingRegistry(raw);
    installRegistry("staging", registry);
    const objects = await seedGovernedObjects();
    const original = new TextEncoder().encode(
      '{"data":[{"Date":"2026-08-01","HolDiv":"1"}]}',
    );
    const reordered = new TextEncoder().encode(
      '{"data":[{"HolDiv":"1","Date":"2026-08-01"}]}',
    );
    expect(original.byteLength).toBe(reordered.byteLength);
    const prefix =
      "raw/receipt-authority/staging/equities_master/2026-08/op/attempt-1/";
    const rawKey = `${prefix}manifest.json`;
    const calendarKey = `${prefix}official-calendar.json`;
    const evidence = {
      raw_path: calendarKey,
      source_path: "/v2/markets/calendar",
      raw_size: original.byteLength,
      raw_digest: await sha256Prefixed(original),
      calendar_query_digest: "sha256:" + "c1".repeat(32),
      business_dates_digest: "sha256:" + "c2".repeat(32),
      binding_digest: "sha256:" + "c3".repeat(32),
      business_dates: ["2026-08-01"],
    };
    const page = {
      raw_path: `${prefix}page-000000.json`,
      raw_size: 2,
      raw_digest: "sha256:" + "bb".repeat(32),
      response_status: 200,
      headers: { "content-type": "application/json" },
      metadata: { pagination_state: "EXHAUSTED" },
    };
    const captureBody = {
      schema_version: "jquants-acquisition-collection/v2",
      capture_mode: "LIVE_SERVICE_BINDING_RESPONSE",
      initial_request: { dataset_id: "equities_master" },
      official_calendar_evidence: evidence,
      pages: [page],
    };
    const collectionDigest = await canonicalDigest(captureBody);
    const collectionJson = canonicalJson({
      ...captureBody,
      collection_digest: collectionDigest,
    });
    const collectionBytes = new TextEncoder().encode(collectionJson);
    const rawManifestDigest = await canonicalDigest({
      pages: [{ index: 0, digest: page.raw_digest, size: page.raw_size }],
      official_calendar_evidence: evidence,
    });
    const claims = await canonicalV3Claims({
      ...objects,
      rawDigest: rawManifestDigest,
      rawFileDigest: await sha256Prefixed(collectionBytes),
      rawBytes: collectionBytes.byteLength,
    }, {
      dataset: "equities_master",
      expected_scope: masterScope(),
      artifact_key: "master-artifact.jsonl",
      manifest_key: "master-manifest.json",
      raw_manifest_key: rawKey,
      receipt_issue_digest: "sha256:" + "ce".repeat(32),
      run_id: 3,
      structured_generation: 3,
      extra_digests: {
        acquisition_collection_manifest_file_digest:
          await sha256Prefixed(collectionBytes),
        acquisition_collection_digest: collectionDigest,
        acquisition_terminal_chain_digest: "sha256:" + "13".repeat(32),
        product_artifact_digest: objects.structured,
        product_manifest_digest: objects.manifestDigest,
        official_calendar_evidence_digest: await canonicalDigest(evidence),
        official_calendar_raw_body_digest: evidence.raw_digest,
        official_calendar_query_digest: evidence.calendar_query_digest,
        official_business_dates_digest: evidence.business_dates_digest,
        official_calendar_binding_digest: evidence.binding_digest,
      },
    });
    await seedComplete(runtimeEnv.DB, {
      dataset: "equities_master",
      segmentId: "2026-08",
      runId: 3,
      operationId: "op-master",
      nonce: "ad".repeat(32),
      requestDigest: "sha256:" + "ce".repeat(32),
      expectedScope: masterScope(),
      artifactKey: "master-artifact.jsonl",
      manifestKey: "master-manifest.json",
      rawKey,
      envelope: await signV3Claims(pair, claims),
      objects: {
        ...objects,
        rawDigest: rawManifestDigest,
        rawFileDigest: await sha256Prefixed(collectionBytes),
        rawBytes: collectionBytes.byteLength,
      },
    });
    await runtimeEnv.RAW_BUCKET.put(rawKey, collectionBytes);
    await runtimeEnv.RAW_BUCKET.put(calendarKey, original);
    const described = await postReceiptProducts(exportEnv(), inputRequest([
      { dataset: "equities_master", segment_id: "2026-08" },
    ]));
    const describedBody = await described!.json() as {
      input_set_digest: string;
      segments: Array<{ operation_id: string; receipt_digest: string }>;
    };
    const segment = describedBody.segments[0]!;
    const originalRead = await readReceiptProductBytes(runtimeEnv, byteRequest(
      "equities_master",
      "2026-08",
      segment.operation_id,
      segment.receipt_digest,
      "official_calendar_raw",
    ));
    expect(originalRead.status).toBe(200);
    expect(new Uint8Array(await originalRead.arrayBuffer())).toEqual(original);

    await runtimeEnv.RAW_BUCKET.put(calendarKey, reordered);
    const refused = await readReceiptProductBytes(runtimeEnv, byteRequest(
      "equities_master",
      "2026-08",
      segment.operation_id,
      segment.receipt_digest,
      "official_calendar_raw",
    ));
    expect(refused.status).toBe(409);
    expect(await refused.json()).toMatchObject({
      status: "HOLD",
      hold_reason: "UNTRUSTED_CHAIN",
    });
  });
});
