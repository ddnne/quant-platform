import {
  CONTROLLED_COVERAGE_POLICY_ROWS,
  OPS_PROJECTION_D1_IDENTITIES,
  OPS_PROJECTION_PRODUCTION_RAW,
  OPS_PROJECTION_PRODUCTION_RAW_DIGEST,
  OPS_PROJECTION_REGISTRY_PINS,
  OPS_PROJECTION_STAGING_RAW,
  OPS_PROJECTION_STAGING_RAW_DIGEST,
} from "./controlled_pilot_registry_raw.generated";
import {
  EXACT_FOUR_COVERAGE_POLICY_DIGEST,
  EXACT_FOUR_COVERAGE_POLICY_VERSION,
  EXACT_FOUR_DATASET_IDS,
} from "./controlled_pilot_contract";
import {
  canonicalJson,
  decodeStrictJson,
  isRecord,
  parseCanonicalUtc,
  sha256Digest,
} from "./controlled_pilot_json";

const SHA256_RE = /^sha256:[0-9a-f]{64}$/;
const SIGNED_DOCUMENT_SCHEMA = "ops-projection-signed-envelope/v1";
const ENVELOPE_SCHEMA = "ops-projection-envelope/v1";
const MAX_FUTURE_SKEW_MS = 5 * 60_000;
const MAX_PROJECTION_AGE_MS = 24 * 60 * 60_000;

const DOCUMENT_FIELDS = new Set([
  "schema_version",
  "algorithm",
  "issuer_key_id",
  "envelope",
  "signature",
]);

const ENVELOPE_FIELDS = new Set([
  "schema_version",
  "environment",
  "resource_identity",
  "generation_id",
  "content_digest",
  "source_db_digest",
  "generated_at",
  "producer_commit_sha",
  "contract_digest",
  "registry_digest",
  "coverage_policy_version",
  "coverage_policy_digest",
  "projection_status",
  "source_generation",
  "source_snapshot_generation",
  "source_cursor",
  "export_cursor",
  "applied_cursor",
  "coverage_status_digest",
  "dataset_coverage",
  "b0_status",
  "b0_evidence_digest",
  "b4_status",
  "b4_evidence_digest",
  "evidence_digests",
  "content_manifest",
  "row_counts",
]);

const DATASET_COVERAGE_FIELDS = new Set([
  "status",
  "coverage_mode",
  "policy_id",
  "policy_version",
  "policy_digest",
  "collection_scope",
  "observed_start",
  "observed_end",
]);

const PROJECTED_CONTENT_TABLES = [
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

const SCOPE_FIELDS = new Set([
  "format",
  "status",
  "profile_digest",
  "plan_set_digest",
  "dependency_closure_digest",
  "universe_rule_digest",
  "resolved_universe_digest",
  "universe_daily_summary",
  "period_start",
  "period_end",
  "lookback_trading_days",
  "entries",
  "product_materialization_digest",
  "proof_digest",
]);

const SCOPE_ENTRY_FIELDS = new Set([
  "dataset_id",
  "natural_key_count",
  "natural_key_digest",
  "receipt_digests",
  "receipt_set_digest",
  "product_artifact_digests",
  "product_artifact_set_digest",
]);

export type ProjectionEnvironment = "production" | "staging";

export type ControlledSessionScopeEntry = {
  dataset_id: "equities_bars_daily" | "equities_bars_daily_am";
  natural_key_count: number;
  natural_key_digest: string;
  product_artifact_digests: string[];
  product_artifact_set_digest: string;
};

export type ControlledSessionScope = {
  format: "controlled-session-scope/v1";
  dependency_scope_proof_digest: string;
  observed_through: string;
  entries: [ControlledSessionScopeEntry, ControlledSessionScopeEntry];
};

export type VerifiedOpsProjectionReady = {
  document_digest: string;
  issuer_key_id: string;
  envelope: Record<string, unknown>;
  session_scope: ControlledSessionScope;
};

export type ProjectionVerifyResult =
  | { ok: true; value: VerifiedOpsProjectionReady }
  | { ok: false; status: "PENDING" | "REJECTED"; error: string };

type ActiveProjectionKey = { key_id: string; public_key: Uint8Array };

function closedShape(value: Record<string, unknown>, fields: ReadonlySet<string>): boolean {
  const keys = Object.keys(value);
  return keys.length === fields.size && keys.every((key) => fields.has(key));
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && SHA256_RE.test(value);
}

function decodeBase64(value: unknown): Uint8Array | null {
  if (typeof value !== "string") return null;
  try {
    const binary = atob(value);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    return bytes;
  } catch {
    return null;
  }
}

function jsonEqual(left: unknown, right: unknown): boolean {
  return canonicalJson(left) === canonicalJson(right);
}

async function loadPinnedProjectionKey(
  environment: ProjectionEnvironment,
): Promise<{ status: "ACTIVE"; key: ActiveProjectionKey } | { status: "PENDING" }> {
  const raw = environment === "production"
    ? OPS_PROJECTION_PRODUCTION_RAW
    : OPS_PROJECTION_STAGING_RAW;
  const expectedRawDigest = environment === "production"
    ? OPS_PROJECTION_PRODUCTION_RAW_DIGEST
    : OPS_PROJECTION_STAGING_RAW_DIGEST;
  const pins = OPS_PROJECTION_REGISTRY_PINS[environment];
  if ((await sha256Digest(raw)) !== expectedRawDigest) {
    throw new Error("pinned Ops Projection registry raw bytes drifted");
  }
  const parsed = decodeStrictJson(raw);
  if (!isRecord(parsed) || !closedShape(parsed, new Set([
    "schema_version",
    "purpose",
    "generation",
    "authority_status",
    "prior_registry_digest",
    "keys",
    "registry_digest",
  ]))) {
    throw new Error("pinned Ops Projection registry is malformed");
  }
  if (
    parsed.schema_version !== 2 ||
    parsed.purpose !== "ops_projection_verification" ||
    parsed.generation !== pins.generation ||
    parsed.prior_registry_digest !== pins.prior_registry_digest ||
    parsed.registry_digest !== pins.body_digest ||
    (parsed.authority_status !== "ACTIVE" && parsed.authority_status !== "PENDING") ||
    !Array.isArray(parsed.keys) ||
    parsed.keys.length > 16 ||
    (await sha256Digest(canonicalJson(parsed))) !== pins.document_digest
  ) {
    throw new Error("pinned Ops Projection registry identity is invalid");
  }
  const body = { ...parsed };
  delete body.registry_digest;
  if ((await sha256Digest(canonicalJson(body))) !== pins.body_digest) {
    throw new Error("pinned Ops Projection registry body digest is invalid");
  }
  const seen = new Set<string>();
  const active: ActiveProjectionKey[] = [];
  for (const rawRow of parsed.keys) {
    if (!isRecord(rawRow) || !closedShape(rawRow, new Set([
      "key_id",
      "algorithm",
      "public_key_base64",
      "status",
    ]))) {
      throw new Error("pinned Ops Projection registry key is malformed");
    }
    const keyId = typeof rawRow.key_id === "string" ? rawRow.key_id.trim() : "";
    const publicKey = decodeBase64(rawRow.public_key_base64);
    if (
      !keyId || seen.has(keyId) || rawRow.algorithm !== "Ed25519" ||
      (rawRow.status !== "active" && rawRow.status !== "pending" && rawRow.status !== "revoked") ||
      !publicKey || publicKey.byteLength !== 32
    ) {
      throw new Error("pinned Ops Projection registry key is invalid");
    }
    seen.add(keyId);
    if (rawRow.status === "active") active.push({ key_id: keyId, public_key: publicKey });
  }
  const expectedActive = parsed.authority_status === "ACTIVE" ? 1 : 0;
  if (active.length !== expectedActive) {
    throw new Error("pinned Ops Projection registry ACTIVE state is inconsistent");
  }
  if (parsed.authority_status === "PENDING") return { status: "PENDING" };
  return { status: "ACTIVE", key: active[0]! };
}

function validateResourceIdentity(
  value: unknown,
  environment: ProjectionEnvironment,
): boolean {
  if (!isRecord(value) || !closedShape(value, new Set([
    "environment",
    "source_d1",
    "source_audit_digest",
    "source_export_digest",
    "source_change_seq",
  ]))) return false;
  const expectedD1 = OPS_PROJECTION_D1_IDENTITIES[environment];
  return value.environment === environment &&
    jsonEqual(value.source_d1, expectedD1) &&
    isSha256(value.source_audit_digest) &&
    isSha256(value.source_export_digest) &&
    Number.isSafeInteger(value.source_change_seq) &&
    Number(value.source_change_seq) >= 0;
}

async function validateContentManifest(envelope: Record<string, unknown>): Promise<string | null> {
  if (!isRecord(envelope.content_manifest) || !isRecord(envelope.row_counts)) {
    return "Ops Projection content manifest is missing";
  }
  const manifest = envelope.content_manifest;
  const rowCounts = envelope.row_counts;
  const expected = [...PROJECTED_CONTENT_TABLES].sort();
  if (!jsonEqual(Object.keys(manifest).sort(), expected) ||
      !jsonEqual(Object.keys(rowCounts).sort(), expected)) {
    return "Ops Projection content manifest membership drift";
  }
  const normalized: Record<string, { row_count: number; content_digest: string }> = {};
  for (const table of PROJECTED_CONTENT_TABLES) {
    const raw = manifest[table];
    if (!isRecord(raw) || !closedShape(raw, new Set(["content_digest", "row_count"]))) {
      return `Ops Projection content manifest row invalid for ${table}`;
    }
    if (!Number.isSafeInteger(raw.row_count) || Number(raw.row_count) < 0 ||
        !isSha256(raw.content_digest) || rowCounts[table] !== raw.row_count) {
      return `Ops Projection content manifest row invalid for ${table}`;
    }
    normalized[table] = {
      row_count: Number(raw.row_count),
      content_digest: String(raw.content_digest),
    };
  }
  const digest = await sha256Digest(canonicalJson({ tables: normalized }));
  return digest === envelope.content_digest
    ? null
    : "Ops Projection content digest does not bind its manifest";
}

export async function validateOpsProjectionEnvelopeClaims(
  envelope: Record<string, unknown>,
  environment: ProjectionEnvironment,
  nowMs: number,
): Promise<string | null> {
  if (!closedShape(envelope, ENVELOPE_FIELDS) || envelope.schema_version !== ENVELOPE_SCHEMA) {
    return "Ops Projection envelope fields are not closed";
  }
  if (envelope.environment !== environment ||
      !validateResourceIdentity(envelope.resource_identity, environment)) {
    return "Ops Projection environment/resource identity mismatch";
  }
  for (const field of [
    "generation_id", "generated_at", "producer_commit_sha", "coverage_policy_version",
  ]) {
    if (typeof envelope[field] !== "string" || !String(envelope[field]).trim()) {
      return `Ops Projection ${field} is invalid`;
    }
  }
  for (const field of [
    "content_digest", "source_db_digest", "contract_digest", "registry_digest",
    "coverage_policy_digest", "coverage_status_digest", "b0_evidence_digest",
    "b4_evidence_digest",
  ]) {
    if (!isSha256(envelope[field])) return `Ops Projection ${field} is invalid`;
  }
  if (envelope.projection_status !== "FRESH") return "Ops Projection is not FRESH";
  if (envelope.b0_status !== "PASS" || envelope.b4_status !== "PASS") {
    return "Ops Projection B0/B4 is not PASS";
  }
  const generatedAt = parseCanonicalUtc(envelope.generated_at);
  if (!Number.isFinite(generatedAt) || generatedAt > nowMs + MAX_FUTURE_SKEW_MS ||
      nowMs - generatedAt > MAX_PROJECTION_AGE_MS) {
    return "Ops Projection generated_at is stale or time-incoherent";
  }
  const cursors = [
    envelope.source_generation,
    envelope.source_cursor,
    envelope.export_cursor,
    envelope.applied_cursor,
  ];
  if (cursors.some((value) => !Number.isSafeInteger(value) || Number(value) <= 0) ||
      new Set(cursors.map(Number)).size !== 1) {
    return "Ops Projection source/export/applied cursor chain is not current";
  }
  const resourceIdentity = envelope.resource_identity;
  if (!isRecord(resourceIdentity) ||
      Number(resourceIdentity.source_change_seq) !== Number(envelope.source_generation)) {
    return "Ops Projection resource cursor does not match the signed cursor chain";
  }
  const snapshotGeneration = envelope.source_snapshot_generation;
  if (!((typeof snapshotGeneration === "string" && snapshotGeneration.length > 0) ||
        (Number.isSafeInteger(snapshotGeneration) && Number(snapshotGeneration) >= 0))) {
    return "Ops Projection source snapshot generation is invalid";
  }
  if (envelope.coverage_policy_version !== EXACT_FOUR_COVERAGE_POLICY_VERSION) {
    return "Ops Projection is not Coverage V3";
  }
  if (!isRecord(envelope.dataset_coverage)) {
    return "Ops Projection dataset Coverage is missing";
  }
  for (const [datasetId, rawRow] of Object.entries(envelope.dataset_coverage)) {
    if (!isRecord(rawRow) || !closedShape(rawRow, DATASET_COVERAGE_FIELDS) ||
        rawRow.policy_id !== datasetId || typeof rawRow.policy_version !== "string" ||
        !isSha256(rawRow.policy_digest) || typeof rawRow.status !== "string" ||
        typeof rawRow.coverage_mode !== "string" || typeof rawRow.collection_scope !== "string" ||
        (rawRow.observed_start !== null && typeof rawRow.observed_start !== "string") ||
        (rawRow.observed_end !== null && typeof rawRow.observed_end !== "string")) {
      return `Ops Projection dataset Coverage row is invalid for ${datasetId}`;
    }
  }
  for (const datasetId of EXACT_FOUR_DATASET_IDS) {
    const row = envelope.dataset_coverage[datasetId];
    const expected = CONTROLLED_COVERAGE_POLICY_ROWS[
      datasetId as keyof typeof CONTROLLED_COVERAGE_POLICY_ROWS
    ];
    if (!isRecord(row) || row.status !== "COMPLETE" || row.policy_id !== expected.policy_id ||
        row.policy_version !== expected.policy_version || row.policy_digest !== expected.policy_digest) {
      return `Ops Projection controlled Coverage is not exact COMPLETE for ${datasetId}`;
    }
  }
  if (!isRecord(envelope.evidence_digests) ||
      Object.entries(envelope.evidence_digests).some(
        ([key, value]) => !key || !isSha256(value),
      )) {
    return "Ops Projection evidence digests are invalid";
  }
  return validateContentManifest(envelope);
}

function validateScopeEntry(value: unknown): value is Record<string, unknown> {
  if (!isRecord(value) || !closedShape(value, SCOPE_ENTRY_FIELDS) ||
      typeof value.dataset_id !== "string" ||
      !Number.isSafeInteger(value.natural_key_count) || Number(value.natural_key_count) < 1 ||
      !isSha256(value.natural_key_digest) || !Array.isArray(value.receipt_digests) ||
      value.receipt_digests.length < 1 || value.receipt_digests.some((item) => !isSha256(item)) ||
      !isSha256(value.receipt_set_digest) || !Array.isArray(value.product_artifact_digests) ||
      value.product_artifact_digests.length < 1 ||
      value.product_artifact_digests.some((item) => !isSha256(item)) ||
      !isSha256(value.product_artifact_set_digest)) return false;
  return true;
}

async function verifyDependencyScope(
  scope: unknown,
  manifest: Record<string, unknown>,
  projectionEnvelope: Record<string, unknown>,
): Promise<ControlledSessionScope | null> {
  if (!isRecord(scope) || !closedShape(scope, SCOPE_FIELDS) ||
      scope.format !== "pit-dependency-scope-proof/v1" || scope.status !== "PASS" ||
      scope.profile_digest !== manifest.profile_digest ||
      scope.plan_set_digest !== manifest.plan_set_digest ||
      scope.dependency_closure_digest !== manifest.dependency_closure_digest ||
      scope.universe_rule_digest !== manifest.universe_rule_digest ||
      scope.resolved_universe_digest !== manifest.resolved_universe_digest ||
      !isSha256(scope.product_materialization_digest) || !isSha256(scope.proof_digest) ||
      !Array.isArray(scope.universe_daily_summary) || !Array.isArray(scope.entries) ||
      !Number.isSafeInteger(scope.lookback_trading_days) || Number(scope.lookback_trading_days) < 0 ||
      typeof scope.period_start !== "string" || typeof scope.period_end !== "string") {
    return null;
  }
  const body = { ...scope };
  delete body.proof_digest;
  if ((await sha256Digest(canonicalJson(body))) !== scope.proof_digest) return null;
  const projectionEvidence = projectionEnvelope.evidence_digests;
  if (!isRecord(projectionEvidence) ||
      projectionEvidence.dependency_scope !== scope.proof_digest ||
      projectionEvidence.product_materializations !== scope.product_materialization_digest) {
    return null;
  }
  if (!isRecord(manifest.pit_contract_digests) ||
      manifest.pit_contract_digests.dependency_scope !== scope.proof_digest) return null;
  const entries = scope.entries.filter(validateScopeEntry);
  if (entries.length !== scope.entries.length || entries.length !== EXACT_FOUR_DATASET_IDS.length ||
      !jsonEqual(entries.map((entry) => entry.dataset_id).sort(), [...EXACT_FOUR_DATASET_IDS].sort())) {
    return null;
  }
  for (const entry of entries) {
    const receipts = [...(entry.receipt_digests as string[])].sort();
    const products = [...(entry.product_artifact_digests as string[])].sort();
    if (!jsonEqual(receipts, entry.receipt_digests) || !jsonEqual(products, entry.product_artifact_digests) ||
        (await sha256Digest(canonicalJson(receipts))) !== entry.receipt_set_digest ||
        (await sha256Digest(canonicalJson(products))) !== entry.product_artifact_set_digest) return null;
  }
  const selected = ["equities_bars_daily", "equities_bars_daily_am"].map((datasetId) => {
    const entry = entries.find((item) => item.dataset_id === datasetId)!;
    return {
      dataset_id: datasetId,
      natural_key_count: Number(entry.natural_key_count),
      natural_key_digest: String(entry.natural_key_digest),
      product_artifact_digests: [...(entry.product_artifact_digests as string[])],
      product_artifact_set_digest: String(entry.product_artifact_set_digest),
    } as ControlledSessionScopeEntry;
  }) as [ControlledSessionScopeEntry, ControlledSessionScopeEntry];
  const observedThrough = manifest.observed_through;
  const observedMs = typeof observedThrough === "string" ? Date.parse(observedThrough) : Number.NaN;
  if (!Number.isFinite(observedMs)) return null;
  return {
    format: "controlled-session-scope/v1",
    dependency_scope_proof_digest: String(scope.proof_digest),
    observed_through: String(observedThrough),
    entries: selected,
  };
}

function verifyManifestEvidence(
  manifest: Record<string, unknown>,
  envelope: Record<string, unknown>,
): string | null {
  const evidence = envelope.evidence_digests;
  if (!isRecord(evidence)) return "Ops Projection evidence digests are missing";
  const expected: Array<[string, unknown]> = [
    ["coverage_proof_digest", envelope.coverage_status_digest],
    ["raw_proof_digest", evidence.raw_retention],
    ["receipt_proof_digest", evidence.product_materializations],
    ["validation_proof_digest", evidence.validation],
    ["b0_proof_digest", envelope.b0_evidence_digest],
    ["b4_proof_digest", envelope.b4_evidence_digest],
  ];
  for (const [field, value] of expected) {
    if (!isSha256(value) || manifest[field] !== value) {
      return `ReadyManifest ${field} does not match signed Ops Projection`;
    }
  }
  const cursor = String(envelope.source_generation);
  for (const field of ["source_generation", "applied_sync_generation", "export_cursor", "applied_cursor"]) {
    if (manifest[field] !== cursor) return `ReadyManifest ${field} does not match signed Ops Projection`;
  }
  if (manifest.coverage_policy_version !== EXACT_FOUR_COVERAGE_POLICY_VERSION ||
      manifest.coverage_policy_digest !== EXACT_FOUR_COVERAGE_POLICY_DIGEST) {
    return "ReadyManifest controlled Coverage policy binding is invalid";
  }
  const published = parseCanonicalUtc(manifest.published_at);
  const projectionGenerated = parseCanonicalUtc(envelope.generated_at);
  if (!Number.isFinite(published) || published < projectionGenerated) {
    return "ReadyManifest publication precedes signed Ops Projection";
  }
  return null;
}

export async function verifyOpsProjectionReady(
  signedDocument: unknown,
  dependencyScope: unknown,
  readyManifest: Record<string, unknown>,
  environment: ProjectionEnvironment,
  nowMs = Date.now(),
): Promise<ProjectionVerifyResult> {
  let pinned: Awaited<ReturnType<typeof loadPinnedProjectionKey>>;
  try {
    pinned = await loadPinnedProjectionKey(environment);
  } catch (error) {
    return {
      ok: false,
      status: "PENDING",
      error: error instanceof Error ? error.message : "Ops Projection registry unavailable",
    };
  }
  if (pinned.status === "PENDING") {
    return { ok: false, status: "PENDING", error: "Ops Projection registry is PENDING" };
  }
  if (!isRecord(signedDocument) || !closedShape(signedDocument, DOCUMENT_FIELDS) ||
      signedDocument.schema_version !== SIGNED_DOCUMENT_SCHEMA ||
      signedDocument.algorithm !== "Ed25519" ||
      signedDocument.issuer_key_id !== pinned.key.key_id ||
      !isRecord(signedDocument.envelope)) {
    return { ok: false, status: "REJECTED", error: "signed Ops Projection shape is invalid" };
  }
  const envelope = signedDocument.envelope;
  const envelopeError = await validateOpsProjectionEnvelopeClaims(
    envelope,
    environment,
    nowMs,
  );
  if (envelopeError) return { ok: false, status: "REJECTED", error: envelopeError };
  const signature = typeof signedDocument.signature === "string" &&
    signedDocument.signature.startsWith("ed25519:")
    ? decodeBase64(signedDocument.signature.slice("ed25519:".length))
    : null;
  if (!signature || signature.byteLength !== 64) {
    return { ok: false, status: "REJECTED", error: "Ops Projection signature is malformed" };
  }
  const body = {
    schema_version: SIGNED_DOCUMENT_SCHEMA,
    algorithm: "Ed25519",
    issuer_key_id: pinned.key.key_id,
    envelope,
  };
  try {
    const key = await crypto.subtle.importKey(
      "raw", pinned.key.public_key, { name: "Ed25519" }, false, ["verify"],
    );
    const valid = await crypto.subtle.verify(
      { name: "Ed25519" }, key, signature,
      new TextEncoder().encode(canonicalJson(body)),
    );
    if (!valid) return { ok: false, status: "REJECTED", error: "Ops Projection signature is invalid" };
  } catch {
    return { ok: false, status: "REJECTED", error: "Ops Projection signature verification failed" };
  }
  const manifestError = verifyManifestEvidence(readyManifest, envelope);
  if (manifestError) return { ok: false, status: "REJECTED", error: manifestError };
  const sessionScope = await verifyDependencyScope(
    dependencyScope,
    readyManifest,
    envelope,
  );
  if (!sessionScope) {
    return { ok: false, status: "REJECTED", error: "signed PIT dependency scope is invalid" };
  }
  const documentDigest = await sha256Digest(canonicalJson(signedDocument));
  return {
    ok: true,
    value: {
      document_digest: documentDigest,
      issuer_key_id: pinned.key.key_id,
      envelope: structuredClone(envelope),
      session_scope: sessionScope,
    },
  };
}
