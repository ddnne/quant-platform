import type {
  ReceiptAuditRecoveryAttestationV1,
  ReceiptAuditRecoveryBeginResultV1,
  ReceiptAuditRecoveryPendingReplayResultV1,
  ReceiptEvidenceAuthorityRpc,
} from "../../receipt-evidence-authority/src/types";
import {
  bytesToBase64,
  canonicalDigest,
  canonicalJson,
  isPlainObject,
  isSha256,
} from "../../receipt-evidence-authority/src/canonical";
import {
  auditInitialResult,
  auditInitialStateDocument,
  auditRecoveryOperationId,
  requireAuditRecoveryAttestationStructure,
} from "../../receipt-evidence-authority/src/audit_recovery_contract";

export type ReceiptAuthorityAuditCanaryEnv = {
  DB: D1Database;
  RECEIPT_EVIDENCE_AUTHORITY: Pick<
    ReceiptEvidenceAuthorityRpc,
    "begin_audit_recovery_canary" | "recover_audit_recovery_canary"
  >;
  CF_VERSION_METADATA?: WorkerVersionMetadata;
  RECEIPT_AUTHORITY_OPERATION_MODE?: "PENDING" | "ACTIVE";
};

function randomNonce(): string {
  return [...crypto.getRandomValues(new Uint8Array(32))]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function activeStagingProvenance(
  env: ReceiptAuthorityAuditCanaryEnv,
): { sourceSha: string; versionId: string; versionTag: string } {
  const metadata = env.CF_VERSION_METADATA;
  const match = /^ra-s-c-([0-9a-f]{40})$/.exec(metadata?.tag ?? "");
  if (
    env.RECEIPT_AUTHORITY_OPERATION_MODE !== "ACTIVE" ||
    metadata === undefined ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
      .test(metadata.id) ||
    match === null
  ) {
    throw new Error("staging Receipt recovery smoke deployment is not ACTIVE");
  }
  return {
    sourceSha: match[1]!,
    versionId: metadata.id,
    versionTag: metadata.tag,
  };
}

type AuditReservation = {
  reservation_id: string;
  source_sha: string;
  caller_worker_version_id: string;
  authority_operation_id: string;
  request_nonce: string;
  state: "PREPARED" | "ATTESTED";
  signed_attestation_digest: string | null;
  signed_attestation_json: string | null;
};

type RecoveryAuditSchemaRow = {
  type: "table" | "trigger";
  name: string;
  tbl_name: string;
  sql: string;
};

export type ReceiptOperatorAuditEvidenceV1 = {
  schema_version: "receipt-operator-audit-evidence/v1";
  purpose: "receipt_authority_recovery_canary";
  eligibility: "AUDIT_ONLY";
  environment: "staging";
  caller_source_sha: string;
  caller_worker_version_id: string;
  caller_worker_version_tag: string;
  d1_schema_digest: string;
  reservation_id: string;
  authority_operation_id: string;
  request_nonce: string;
  signed_attestation_digest: string;
  signed_attestation_json_utf8_base64: string;
  signed_attestation_json_utf8_length: number;
  evidence_digest: string;
};

const RECOVERY_AUDIT_SCHEMA_DIGEST =
  "sha256:fba0bdada764ff2dc67caa5c11b3a31b2c3c28d673a25712a853e0b0566b5259";
const RECOVERY_AUDIT_SCHEMA_NAMES = [
  "receipt_authority_recovery_audit_attestations",
  "receipt_authority_recovery_audit_monotonic",
  "receipt_authority_recovery_audit_no_delete",
] as const;

async function recoveryAuditSchemaDigest(db: D1Database): Promise<string> {
  const result = await db.prepare(
    `SELECT type,name,tbl_name,sql FROM sqlite_schema
      WHERE name IN (?,?,?) ORDER BY type,name`,
  ).bind(...RECOVERY_AUDIT_SCHEMA_NAMES).all<RecoveryAuditSchemaRow>();
  if (result.results.length !== RECOVERY_AUDIT_SCHEMA_NAMES.length) {
    throw new Error("staging Receipt audit schema inventory drifted");
  }
  const rows: RecoveryAuditSchemaRow[] = [];
  for (const row of result.results) {
    if (
      !isPlainObject(row) ||
      Object.keys(row).sort().join("\n") !==
        ["type", "name", "tbl_name", "sql"].sort().join("\n") ||
      (row.type !== "table" && row.type !== "trigger") ||
      !RECOVERY_AUDIT_SCHEMA_NAMES.includes(
        row.name as typeof RECOVERY_AUDIT_SCHEMA_NAMES[number],
      ) ||
      row.tbl_name !== "receipt_authority_recovery_audit_attestations" ||
      typeof row.sql !== "string" || row.sql.length === 0
    ) throw new Error("staging Receipt audit schema inventory drifted");
    rows.push(row as RecoveryAuditSchemaRow);
  }
  const digest = await canonicalDigest({
    schema_version: "receipt-recovery-audit-sqlite-schema/v1",
    objects: rows,
  });
  if (digest !== RECOVERY_AUDIT_SCHEMA_DIGEST) {
    throw new Error("staging Receipt audit schema digest drifted");
  }
  return digest;
}

async function verifyStoredAuditAttestation(
  reservation: AuditReservation,
  provenance: ReturnType<typeof activeStagingProvenance>,
) {
  const expectedReservationId = await canonicalDigest({
    schema_version: "staging-receipt-audit-reservation/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
    source_sha: provenance.sourceSha,
    caller_worker_version_id: provenance.versionId,
  });
  if (
    reservation.reservation_id !== expectedReservationId ||
    reservation.source_sha !== provenance.sourceSha ||
    reservation.caller_worker_version_id !== provenance.versionId ||
    !isSha256(reservation.authority_operation_id) ||
    !/^[0-9a-f]{64}$/.test(reservation.request_nonce) ||
    reservation.state !== "ATTESTED" ||
    !isSha256(reservation.signed_attestation_digest) ||
    reservation.signed_attestation_json === null
  ) throw new Error("staging Receipt audit attestation is incomplete");
  let raw: unknown;
  try {
    raw = JSON.parse(reservation.signed_attestation_json);
  } catch {
    throw new Error("staging Receipt audit attestation is malformed");
  }
  const verified = await requireAuditRecoveryAttestationStructure(raw);
  if (
    canonicalJson(verified.attestation) !== reservation.signed_attestation_json ||
    await canonicalDigest(verified.attestation) !==
      reservation.signed_attestation_digest ||
    verified.claims.operation_id !== reservation.authority_operation_id ||
    verified.claims.request_nonce !== reservation.request_nonce ||
    verified.claims.caller_source_sha !== provenance.sourceSha ||
    verified.claims.caller_worker_version_id !== provenance.versionId ||
    verified.claims.caller_worker_version_tag !== provenance.versionTag ||
    verified.claims.authority_source_sha !== provenance.sourceSha ||
    verified.claims.authority_worker_version_tag !==
      `ra-s-r-${provenance.sourceSha}`
  ) throw new Error("staging Receipt audit attestation was substituted");
  return { ...verified, exactJson: reservation.signed_attestation_json };
}

async function requireStoredAuditAttestation(
  reservation: AuditReservation,
  provenance: ReturnType<typeof activeStagingProvenance>,
): Promise<ReceiptAuditRecoveryAttestationV1> {
  return (await verifyStoredAuditAttestation(reservation, provenance)).attestation;
}

function requireAuditResultEnvelope(value: unknown): asserts value is {
  schema_version: "receipt-audit-recovery-result/v1";
  purpose: "receipt_authority_recovery_canary";
  eligibility: "AUDIT_ONLY";
  operation_id: string;
  final_state: "AUDIT_FINALIZED";
  signed_attestation_digest: string;
  signed_attestation: ReceiptAuditRecoveryAttestationV1;
  rpc_replayed: true;
} {
  if (!isPlainObject(value)) {
    throw new Error("Receipt audit recovery result is malformed");
  }
  const fields = [
    "schema_version", "purpose", "eligibility", "operation_id",
    "final_state", "signed_attestation_digest", "signed_attestation",
    "rpc_replayed",
  ];
  if (
    Object.keys(value).sort().join("\n") !== fields.sort().join("\n") ||
    value.schema_version !== "receipt-audit-recovery-result/v1" ||
    value.purpose !== "receipt_authority_recovery_canary" ||
    value.eligibility !== "AUDIT_ONLY" ||
    !isSha256(value.operation_id) || value.final_state !== "AUDIT_FINALIZED" ||
    !isSha256(value.signed_attestation_digest) ||
    value.rpc_replayed !== true ||
    !isPlainObject(value.signed_attestation)
  ) throw new Error("Receipt audit recovery result is malformed");
}

function requireAuditPendingReplayEnvelope(
  value: unknown,
): asserts value is ReceiptAuditRecoveryPendingReplayResultV1 {
  if (!isPlainObject(value) || !isPlainObject(value.first_recovery_result)) {
    throw new Error("Receipt audit first recovery result is malformed");
  }
  const fields = [
    "schema_version", "purpose", "eligibility", "operation_id", "state",
    "first_recovery_result_digest", "first_recovery_result", "rpc_replayed",
  ];
  const resultFields = [
    "schema_version", "purpose", "eligibility", "environment", "operation_id",
    "request_nonce", "initial_state_digest", "initial_result_digest",
    "recovery_event_digest", "recovery_event_tail_digest", "recovered_at",
    "state",
  ];
  const recoveredAt = typeof value.first_recovery_result.recovered_at === "string"
    ? new Date(value.first_recovery_result.recovered_at)
    : null;
  if (
    Object.keys(value).sort().join("\n") !== fields.sort().join("\n") ||
    Object.keys(value.first_recovery_result).sort().join("\n") !==
      resultFields.sort().join("\n") ||
    value.schema_version !==
      "receipt-audit-recovery-pending-replay-result/v1" ||
    value.purpose !== "receipt_authority_recovery_canary" ||
    value.eligibility !== "AUDIT_ONLY" || !isSha256(value.operation_id) ||
    value.state !== "RECOVERED_PENDING_REPLAY" ||
    !isSha256(value.first_recovery_result_digest) ||
    value.rpc_replayed !== false ||
    value.first_recovery_result.schema_version !==
      "receipt-audit-first-recovery-result/v1" ||
    value.first_recovery_result.purpose !==
      "receipt_authority_recovery_canary" ||
    value.first_recovery_result.eligibility !== "AUDIT_ONLY" ||
    value.first_recovery_result.environment !== "staging" ||
    value.first_recovery_result.operation_id !== value.operation_id ||
    typeof value.first_recovery_result.request_nonce !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.first_recovery_result.request_nonce) ||
    !isSha256(value.first_recovery_result.initial_state_digest) ||
    !isSha256(value.first_recovery_result.initial_result_digest) ||
    !isSha256(value.first_recovery_result.recovery_event_digest) ||
    !isSha256(value.first_recovery_result.recovery_event_tail_digest) ||
    value.first_recovery_result.state !== "RECOVERED_PENDING_REPLAY" ||
    recoveredAt === null || Number.isNaN(recoveredAt.getTime()) ||
    recoveredAt.toISOString() !== value.first_recovery_result.recovered_at
  ) throw new Error("Receipt audit first recovery result is malformed");
}

function requireAuditBeginResultEnvelope(
  value: unknown,
): asserts value is ReceiptAuditRecoveryBeginResultV1 {
  if (!isPlainObject(value) || !isPlainObject(value.initial_result)) {
    throw new Error("Receipt audit recovery begin result is malformed");
  }
  const fields = [
    "schema_version", "purpose", "eligibility", "operation_id",
    "initial_result_digest", "initial_result", "rpc_replayed",
  ];
  const initialFields = [
    "schema_version", "purpose", "eligibility", "environment", "operation_id",
    "request_nonce", "state", "initial_state_digest", "created_at",
  ];
  const createdAt = typeof value.initial_result.created_at === "string"
    ? new Date(value.initial_result.created_at)
    : null;
  if (
    Object.keys(value).sort().join("\n") !== fields.sort().join("\n") ||
    Object.keys(value.initial_result).sort().join("\n") !==
      initialFields.sort().join("\n") ||
    value.schema_version !== "receipt-audit-recovery-begin-result/v1" ||
    value.purpose !== "receipt_authority_recovery_canary" ||
    value.eligibility !== "AUDIT_ONLY" || !isSha256(value.operation_id) ||
    !isSha256(value.initial_result_digest) ||
    typeof value.rpc_replayed !== "boolean" ||
    value.initial_result.schema_version !==
      "receipt-audit-recovery-initial-result/v1" ||
    value.initial_result.purpose !== "receipt_authority_recovery_canary" ||
    value.initial_result.eligibility !== "AUDIT_ONLY" ||
    value.initial_result.environment !== "staging" ||
    value.initial_result.operation_id !== value.operation_id ||
    typeof value.initial_result.request_nonce !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.initial_result.request_nonce) ||
    value.initial_result.state !== "RECOVERY_REQUIRED" ||
    !isSha256(value.initial_result.initial_state_digest) ||
    createdAt === null || Number.isNaN(createdAt.getTime()) ||
    createdAt.toISOString() !== value.initial_result.created_at
  ) throw new Error("Receipt audit recovery begin result is malformed");
}

/**
 * ACTIVE-staging audit canary. It exercises only the authority's dedicated
 * audit state machine. It cannot create a TRUSTED_COLLECTION Receipt, mutate
 * Coverage, or persist product raw/structured data.
 */
export async function runStagingReceiptAuditRecoveryCanary(
  env: ReceiptAuthorityAuditCanaryEnv,
): Promise<ReceiptAuditRecoveryAttestationV1> {
  const provenance = activeStagingProvenance(env);
  const proposedNonce = randomNonce();
  const proposedRequest = {
    schema_version: "receipt-audit-recovery-canary-request/v1" as const,
    purpose: "receipt_authority_recovery_canary" as const,
    eligibility: "AUDIT_ONLY" as const,
    operation: "begin_audit_recovery_canary" as const,
    environment: "staging" as const,
    caller_source_sha: provenance.sourceSha,
    caller_worker_version_id: provenance.versionId,
    caller_worker_version_tag: provenance.versionTag,
    request_nonce: proposedNonce,
  };
  const proposedOperationId = await auditRecoveryOperationId(proposedRequest);
  const reservationId = await canonicalDigest({
    schema_version: "staging-receipt-audit-reservation/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
    source_sha: provenance.sourceSha,
    caller_worker_version_id: provenance.versionId,
  });
  const preparedAt = new Date().toISOString();
  await env.DB.prepare(
    `INSERT OR IGNORE INTO receipt_authority_recovery_audit_attestations
       (reservation_id,source_sha,caller_worker_version_id,
        authority_operation_id,request_nonce,state,signed_attestation_digest,
        signed_attestation_json,created_at,updated_at)
     VALUES (?,?,?,?,?,'PREPARED',NULL,NULL,?,?)`,
  ).bind(
    reservationId,
    provenance.sourceSha,
    provenance.versionId,
    proposedOperationId,
    proposedNonce,
    preparedAt,
    preparedAt,
  ).run();
  const reservation = await env.DB.prepare(
    `SELECT reservation_id,source_sha,caller_worker_version_id,
            authority_operation_id,request_nonce,state,
            signed_attestation_digest,signed_attestation_json
       FROM receipt_authority_recovery_audit_attestations
      WHERE source_sha=? AND caller_worker_version_id=?`,
  ).bind(provenance.sourceSha, provenance.versionId).first<AuditReservation>();
  if (
    reservation === null || reservation.reservation_id !== reservationId ||
    reservation.source_sha !== provenance.sourceSha ||
    reservation.caller_worker_version_id !== provenance.versionId ||
    !/^[0-9a-f]{64}$/.test(reservation.request_nonce)
  ) throw new Error("staging Receipt audit reservation drifted");

  const beginRequest = {
    ...proposedRequest,
    request_nonce: reservation.request_nonce,
  };
  const expectedOperationId = await auditRecoveryOperationId(beginRequest);
  if (reservation.authority_operation_id !== expectedOperationId) {
    // This check deliberately precedes every positive authority RPC.
    throw new Error("staging Receipt audit operation identity drifted");
  }
  if (reservation.state === "ATTESTED") {
    return requireStoredAuditAttestation(reservation, provenance);
  }
  if (
    reservation.state !== "PREPARED" ||
    reservation.signed_attestation_digest !== null ||
    reservation.signed_attestation_json !== null
  ) throw new Error("staging Receipt audit reservation is invalid");

  const rawBegun: unknown = await env.RECEIPT_EVIDENCE_AUTHORITY
    .begin_audit_recovery_canary(beginRequest);
  requireAuditBeginResultEnvelope(rawBegun);
  const begun = rawBegun;
  const expectedInitialStateDigest = await canonicalDigest(
    auditInitialStateDocument(
      expectedOperationId,
      begun.initial_result.created_at,
    ),
  );
  const expectedInitialResult = auditInitialResult(
    expectedOperationId,
    reservation.request_nonce,
    expectedInitialStateDigest,
    begun.initial_result.created_at,
  );
  if (
    begun.schema_version !== "receipt-audit-recovery-begin-result/v1" ||
    begun.purpose !== "receipt_authority_recovery_canary" ||
    begun.eligibility !== "AUDIT_ONLY" ||
    begun.operation_id !== expectedOperationId ||
    typeof begun.rpc_replayed !== "boolean" ||
    canonicalJson(begun.initial_result) !== canonicalJson(expectedInitialResult) ||
    begun.initial_result_digest !== await canonicalDigest(expectedInitialResult)
  ) throw new Error("Receipt audit recovery begin result was substituted");

  const recoverRequest = {
    ...beginRequest,
    operation: "recover_audit_recovery_canary" as const,
  };
  const firstRecoveryResponse: unknown = await env.RECEIPT_EVIDENCE_AUTHORITY
    .recover_audit_recovery_canary(recoverRequest);
  let firstRecovery: ReceiptAuditRecoveryPendingReplayResultV1 | null = null;
  let replay: unknown;
  if (
    isPlainObject(firstRecoveryResponse) &&
    firstRecoveryResponse.schema_version ===
      "receipt-audit-recovery-pending-replay-result/v1"
  ) {
    requireAuditPendingReplayEnvelope(firstRecoveryResponse);
    firstRecovery = firstRecoveryResponse;
    if (
      firstRecovery.operation_id !== expectedOperationId ||
      firstRecovery.first_recovery_result.request_nonce !==
        reservation.request_nonce ||
      firstRecovery.first_recovery_result.initial_state_digest !==
        expectedInitialStateDigest ||
      firstRecovery.first_recovery_result.initial_result_digest !==
        begun.initial_result_digest ||
      firstRecovery.first_recovery_result_digest !==
        await canonicalDigest(firstRecovery.first_recovery_result)
    ) throw new Error("Receipt audit first recovery scope drifted");
    replay = await env.RECEIPT_EVIDENCE_AUTHORITY
      .recover_audit_recovery_canary(recoverRequest);
  } else {
    // A prior call may have committed either transition before its response was
    // lost. A finalized result is the authority-signed observation of the
    // second identical recover; do not require an unsigned result to recur.
    replay = firstRecoveryResponse;
  }
  requireAuditResultEnvelope(replay);
  if (
    replay.operation_id !== expectedOperationId || replay.rpc_replayed !== true ||
    replay.signed_attestation_digest !==
      await canonicalDigest(replay.signed_attestation)
  ) throw new Error("Receipt audit recovery did not prove replay");
  const verified = await requireAuditRecoveryAttestationStructure(
    replay.signed_attestation,
  );
  if (
    verified.claims.operation_id !== expectedOperationId ||
    verified.claims.request_nonce !== reservation.request_nonce ||
    verified.claims.initial_state_digest !== expectedInitialStateDigest ||
    verified.claims.initial_result_digest !== begun.initial_result_digest ||
    verified.claims.initial_created_at !== begun.initial_result.created_at ||
    (firstRecovery !== null &&
      (verified.claims.first_recovery_result_digest !==
          firstRecovery.first_recovery_result_digest ||
        verified.claims.recovered_at !==
          firstRecovery.first_recovery_result.recovered_at)) ||
    verified.claims.caller_source_sha !== provenance.sourceSha ||
    verified.claims.caller_worker_version_id !== provenance.versionId ||
    verified.claims.caller_worker_version_tag !== provenance.versionTag ||
    verified.claims.authority_source_sha !== provenance.sourceSha ||
    verified.claims.authority_worker_version_tag !==
      `ra-s-r-${provenance.sourceSha}`
  ) throw new Error("Receipt audit recovery attestation scope drifted");

  const attestationJson = canonicalJson(verified.attestation);
  await env.DB.prepare(
    `UPDATE receipt_authority_recovery_audit_attestations
        SET state='ATTESTED',signed_attestation_digest=?,
            signed_attestation_json=?,updated_at=?
      WHERE reservation_id=? AND state='PREPARED'
        AND signed_attestation_digest IS NULL
        AND signed_attestation_json IS NULL`,
  ).bind(
    replay.signed_attestation_digest,
    attestationJson,
    verified.claims.replay_confirmed_at,
    reservationId,
  ).run();
  const finalized = await env.DB.prepare(
    `SELECT reservation_id,source_sha,caller_worker_version_id,
            authority_operation_id,request_nonce,state,
            signed_attestation_digest,signed_attestation_json
       FROM receipt_authority_recovery_audit_attestations
      WHERE reservation_id=?`,
  ).bind(reservationId).first<AuditReservation>();
  if (finalized === null) {
    throw new Error("staging Receipt audit attestation finalization failed");
  }
  return requireStoredAuditAttestation(finalized, provenance);
}

/** Read-only operator observation; it cannot invoke an authority operation. */
export async function readStagingReceiptAuditRecoveryAttestation(
  env: ReceiptAuthorityAuditCanaryEnv,
): Promise<ReceiptAuditRecoveryAttestationV1> {
  const provenance = activeStagingProvenance(env);
  const row = await env.DB.prepare(
    `SELECT reservation_id,source_sha,caller_worker_version_id,
            authority_operation_id,request_nonce,state,
            signed_attestation_digest,signed_attestation_json
       FROM receipt_authority_recovery_audit_attestations
      WHERE source_sha=? AND caller_worker_version_id=?`,
  ).bind(provenance.sourceSha, provenance.versionId).first<AuditReservation>();
  if (row === null) throw new Error("staging Receipt audit attestation is absent");
  return requireStoredAuditAttestation(row, provenance);
}

/**
 * Read-only activation evidence for the isolated staging observer. The two D1
 * statements are SELECT-only, and the exact stored TEXT bytes are returned
 * without reserialization.
 */
export async function readStagingReceiptAuditRecoveryEvidence(
  env: ReceiptAuthorityAuditCanaryEnv,
): Promise<ReceiptOperatorAuditEvidenceV1> {
  const provenance = activeStagingProvenance(env);
  const schemaDigest = await recoveryAuditSchemaDigest(env.DB);
  const row = await env.DB.prepare(
    `SELECT reservation_id,source_sha,caller_worker_version_id,
            authority_operation_id,request_nonce,state,
            signed_attestation_digest,signed_attestation_json
       FROM receipt_authority_recovery_audit_attestations
      WHERE source_sha=? AND caller_worker_version_id=?`,
  ).bind(provenance.sourceSha, provenance.versionId).first<AuditReservation>();
  if (row === null) throw new Error("staging Receipt audit attestation is absent");
  const verified = await verifyStoredAuditAttestation(row, provenance);
  const exactBytes = new TextEncoder().encode(verified.exactJson);
  const body = {
    schema_version: "receipt-operator-audit-evidence/v1" as const,
    purpose: "receipt_authority_recovery_canary" as const,
    eligibility: "AUDIT_ONLY" as const,
    environment: "staging" as const,
    caller_source_sha: provenance.sourceSha,
    caller_worker_version_id: provenance.versionId,
    caller_worker_version_tag: provenance.versionTag,
    d1_schema_digest: schemaDigest,
    reservation_id: row.reservation_id,
    authority_operation_id: row.authority_operation_id,
    request_nonce: row.request_nonce,
    signed_attestation_digest: row.signed_attestation_digest!,
    signed_attestation_json_utf8_base64: bytesToBase64(exactBytes),
    signed_attestation_json_utf8_length: exactBytes.length,
  };
  return { ...body, evidence_digest: await canonicalDigest(body) };
}
