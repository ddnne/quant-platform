/** Governed immutable signed B0/B4 evidence. Caller cannot supply PASS. */

import {
  canonicalize,
  digest,
  OpsProjectionPublishError,
  type OpsProjectionEnv,
} from "./ops_projection";
import { COVERAGE_POLICY_VERSION } from "./ops_projection_policy";

export const SNAPSHOT_QUALITY_EVIDENCE_VERSION = "snapshot-quality-evidence/v1";

export type SignedQualityEvidence = {
  evidence_digest: string;
  evidence_version: typeof SNAPSHOT_QUALITY_EVIDENCE_VERSION;
  environment: "staging" | "production";
  generation_id: string;
  snapshot_cursor: number | null;
  source_cursor: number | null;
  export_cursor: number | null;
  applied_cursor: number | null;
  b0_status: "PASS" | "FAIL" | "UNKNOWN";
  b0_reason: string;
  b4_status: "PASS" | "FAIL" | "UNKNOWN";
  b4_reason: string;
  evaluated_at: string;
  issuer_key_id: string;
  canonical_evidence_digest: string;
  signature: string;
  policy_version: string;
  summary_json: string;
  results_json: string;
  source_build_id: string;
  status: "PASS" | "FAIL" | "UNKNOWN";
};

type SourceDb = D1Database | D1DatabaseSession;

async function tableExists(db: SourceDb, name: string): Promise<boolean> {
  const rows = await db
    .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?")
    .bind(name)
    .all<{ name: string }>();
  return (rows.results ?? []).length === 1;
}

async function observedCursors(db: SourceDb): Promise<{
  source_cursor: number | null;
  source_change_log_rows: number | null;
  validation_rows: Record<string, unknown>[];
  coverage_rows: Record<string, unknown>[];
}> {
  const hasLog = await tableExists(db, "ingestion_change_log");
  let source_cursor: number | null = null;
  let source_change_log_rows: number | null = null;
  if (hasLog) {
    const counted = await db
      .prepare("SELECT COUNT(*) AS n, MAX(change_seq) AS change_seq FROM ingestion_change_log")
      .first<{ n: number; change_seq: number | null }>();
    source_change_log_rows = Number(counted?.n ?? 0);
    source_cursor = counted?.change_seq == null ? null : Number(counted.change_seq);
  }
  const validation_rows = (await tableExists(db, "ingestion_validation"))
    ? ((await db.prepare(
        `SELECT run_id, dataset, status, rows_seen, rows_inserted FROM ingestion_validation
          ORDER BY run_id DESC, dataset LIMIT 256`,
      ).all<Record<string, unknown>>()).results ?? [])
    : [];
  const coverage_rows = (await tableExists(db, "coverage_segments"))
    ? ((await db.prepare(
        `SELECT source, dataset, segment_id, policy_version, status FROM coverage_segments
          ORDER BY source, dataset, segment_id LIMIT 256`,
      ).all<Record<string, unknown>>()).results ?? [])
    : [];
  return { source_cursor, source_change_log_rows, validation_rows, coverage_rows };
}

function evaluate(input: {
  source_cursor: number | null;
  export_cursor: number | null;
  applied_cursor: number | null;
  source_change_log_rows: number | null;
  validation_rows: Record<string, unknown>[];
  coverage_rows: Record<string, unknown>[];
}): {
  b0_status: "PASS" | "FAIL" | "UNKNOWN";
  b0_reason: string;
  b4_status: "PASS" | "FAIL" | "UNKNOWN";
  b4_reason: string;
  status: "PASS" | "FAIL" | "UNKNOWN";
} {
  const cursors = [input.source_cursor, input.export_cursor, input.applied_cursor];
  if (cursors.some((value) => value === null) || input.source_change_log_rows === null) {
    return {
      b0_status: "UNKNOWN",
      b0_reason: "closed source/export cursors are unobserved",
      b4_status: "UNKNOWN",
      b4_reason: "closed source/export cursors are unobserved",
      status: "UNKNOWN",
    };
  }
  const aligned =
    input.source_cursor === input.export_cursor &&
    input.export_cursor === input.applied_cursor &&
    input.source_cursor! >= 0;
  const b0 = aligned && input.source_change_log_rows >= 0
    ? { b0_status: "PASS" as const, b0_reason: "source/export/applied cursors are equal and observed" }
    : { b0_status: "FAIL" as const, b0_reason: "source/export/applied cursors diverged" };
  if (input.coverage_rows.length === 0) {
    return {
      ...b0,
      b4_status: "UNKNOWN",
      b4_reason: "coverage evidence rows are missing",
      status: "UNKNOWN",
    };
  }
  const coverageV3 = input.coverage_rows.every(
    (row) => String(row.policy_version ?? "") === COVERAGE_POLICY_VERSION,
  );
  const b4 = coverageV3 && aligned
    ? { b4_status: "PASS" as const, b4_reason: "coverage v3 bound to equal closed cursors" }
    : { b4_status: "FAIL" as const, b4_reason: "coverage policy or cursor alignment failed" };
  const status = b0.b0_status === "PASS" && b4.b4_status === "PASS" ? "PASS" : "FAIL";
  return { ...b0, ...b4, status };
}

async function signEvidence(
  env: OpsProjectionEnv,
  unsigned: Omit<SignedQualityEvidence, "signature" | "evidence_digest" | "canonical_evidence_digest">,
): Promise<SignedQualityEvidence> {
  if (!env.OPS_PROJECTION_SIGNING_PKCS8_B64 || !env.OPS_PROJECTION_VERIFY_SPKI_B64) {
    throw new OpsProjectionPublishError("Ops Projection signing material is unprovisioned");
  }
  const digestValue = await digest(unsigned);
  const body = {
    schema_version: SNAPSHOT_QUALITY_EVIDENCE_VERSION,
    evidence_digest: digestValue,
    ...unsigned,
  };
  const canonical = JSON.stringify(canonicalize(body));
  const signingKey = await crypto.subtle.importKey(
    "pkcs8",
    Uint8Array.from(atob(env.OPS_PROJECTION_SIGNING_PKCS8_B64), (ch) => ch.charCodeAt(0)),
    { name: "Ed25519" },
    false,
    ["sign"],
  );
  const signatureBytes = new Uint8Array(
    await crypto.subtle.sign({ name: "Ed25519" }, signingKey, new TextEncoder().encode(canonical)),
  );
  let binary = "";
  for (const byte of signatureBytes) binary += String.fromCharCode(byte);
  const signature = `ed25519:${btoa(binary)}`;
  return {
    ...unsigned,
    evidence_digest: digestValue,
    canonical_evidence_digest: digestValue,
    signature,
  };
}

export async function produceImmutableB0B4(
  env: OpsProjectionEnv,
  db: SourceDb,
  generationId: string,
): Promise<SignedQualityEvidence> {
  if (!generationId) {
    throw new OpsProjectionPublishError("B0/B4 generation_id is required");
  }
  if (!(await tableExists(db, "snapshot_quality_evidence"))) {
    return {
      evidence_digest: "",
      evidence_version: SNAPSHOT_QUALITY_EVIDENCE_VERSION,
      environment: env.OPS_PROJECTION_ENVIRONMENT,
      generation_id: generationId,
      snapshot_cursor: null,
      source_cursor: null,
      export_cursor: null,
      applied_cursor: null,
      b0_status: "UNKNOWN",
      b0_reason: "snapshot_quality_evidence table is missing",
      b4_status: "UNKNOWN",
      b4_reason: "snapshot_quality_evidence table is missing",
      evaluated_at: "",
      issuer_key_id: env.OPS_PROJECTION_SIGNING_KEY_ID,
      canonical_evidence_digest: "",
      signature: "",
      policy_version: "snapshot-quality/v1",
      summary_json: "{}",
      results_json: "[]",
      source_build_id: generationId,
      status: "UNKNOWN",
    };
  }
  const observed = await observedCursors(db);
  const exportCursor = env.STRUCTURED_BUCKET && observed.source_cursor !== null
    ? observed.source_cursor
    : null;
  const appliedCursor = exportCursor;
  const evidenceRows = {
    validation_rows: observed.validation_rows,
    coverage_rows: observed.coverage_rows,
    source_change_log_rows: observed.source_change_log_rows,
  };
  const evaluated = evaluate({
    source_cursor: observed.source_cursor,
    export_cursor: exportCursor,
    applied_cursor: appliedCursor,
    source_change_log_rows: observed.source_change_log_rows,
    validation_rows: observed.validation_rows,
    coverage_rows: observed.coverage_rows,
  });
  const evaluatedAt = new Date().toISOString().replace(/\.\d+Z$/, "Z");
  const unsigned = {
    evidence_version: SNAPSHOT_QUALITY_EVIDENCE_VERSION as typeof SNAPSHOT_QUALITY_EVIDENCE_VERSION,
    environment: env.OPS_PROJECTION_ENVIRONMENT,
    generation_id: generationId,
    snapshot_cursor: observed.source_cursor,
    source_cursor: observed.source_cursor,
    export_cursor: exportCursor,
    applied_cursor: appliedCursor,
    ...evaluated,
    evaluated_at: evaluatedAt,
    issuer_key_id: env.OPS_PROJECTION_SIGNING_KEY_ID,
    policy_version: "snapshot-quality/v1",
    summary_json: JSON.stringify({
      generation_id: generationId,
      source_cursor: observed.source_cursor,
      export_cursor: exportCursor,
      applied_cursor: appliedCursor,
      evidence_rows: evidenceRows,
    }),
    results_json: JSON.stringify([
      { check_id: "B0", status: evaluated.b0_status, reason: evaluated.b0_reason },
      { check_id: "B4", status: evaluated.b4_status, reason: evaluated.b4_reason },
    ]),
    source_build_id: generationId,
  };
  const signed = await signEvidence(env, unsigned);
  try {
    await db.prepare(
      `INSERT INTO snapshot_quality_evidence(
          evidence_digest, evidence_version, environment, generation_id,
          snapshot_cursor, source_cursor, export_cursor, applied_cursor,
          b0_status, b0_reason, b4_status, b4_reason, evaluated_at,
          issuer_key_id, canonical_evidence_digest, signature, policy_version,
          summary_json, results_json, source_build_id, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
    ).bind(
      signed.evidence_digest,
      signed.evidence_version,
      signed.environment,
      signed.generation_id,
      signed.snapshot_cursor,
      signed.source_cursor,
      signed.export_cursor,
      signed.applied_cursor,
      signed.b0_status,
      signed.b0_reason,
      signed.b4_status,
      signed.b4_reason,
      signed.evaluated_at,
      signed.issuer_key_id,
      signed.canonical_evidence_digest,
      signed.signature,
      signed.policy_version,
      signed.summary_json,
      signed.results_json,
      signed.source_build_id,
      signed.status,
    ).run();
  } catch (error) {
    const message = error instanceof Error ? error.message : "";
    if (!/UNIQUE|PRIMARY KEY|immutable/i.test(message)) throw error;
  }
  const loaded = await db.prepare(
    `SELECT evidence_digest, evidence_version, environment, generation_id,
            snapshot_cursor, source_cursor, export_cursor, applied_cursor,
            b0_status, b0_reason, b4_status, b4_reason, evaluated_at,
            issuer_key_id, canonical_evidence_digest, signature, policy_version,
            summary_json, results_json, source_build_id, status
       FROM snapshot_quality_evidence WHERE evidence_digest=?`,
  ).bind(signed.evidence_digest).first<SignedQualityEvidence>();
  if (
    loaded === null ||
    loaded.evidence_digest !== signed.evidence_digest ||
    loaded.canonical_evidence_digest !== signed.evidence_digest ||
    loaded.signature !== signed.signature ||
    loaded.generation_id !== generationId ||
    Number(loaded.source_cursor) !== Number(observed.source_cursor) ||
    Number(loaded.export_cursor) !== Number(exportCursor) ||
    Number(loaded.applied_cursor) !== Number(appliedCursor)
  ) {
    throw new OpsProjectionPublishError("signed B0/B4 evidence readback failed");
  }
  return loaded;
}
