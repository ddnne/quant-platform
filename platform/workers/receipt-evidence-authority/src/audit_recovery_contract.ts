import {
  base64ToBytes,
  bytesToBase64,
  canonicalDigest,
  canonicalJson,
  exactKeys,
  isPlainObject,
  isSha256,
  sha256Digest,
} from "./canonical";
import type {
  ReceiptAuditRecoveryAttestationClaimsV1,
  ReceiptAuditRecoveryAttestationV1,
  ReceiptAuditRecoveryCanaryBeginRequestV1,
  ReceiptAuditRecoveryCanaryRecoverRequestV1,
  ReceiptAuditFirstRecoveryResultV1,
  ReceiptAuditRecoveryInitialResultV1,
} from "./types";

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SOURCE_SHA = /^[0-9a-f]{40}$/;
const NONCE = /^[0-9a-f]{64}$/;

const REQUEST_FIELDS = [
  "schema_version",
  "purpose",
  "eligibility",
  "operation",
  "environment",
  "caller_source_sha",
  "caller_worker_version_id",
  "caller_worker_version_tag",
  "request_nonce",
] as const;

const CLAIM_FIELDS = [
  "schema_version",
  "purpose",
  "eligibility",
  "environment",
  "authority_instance_digest",
  "authority_source_sha",
  "authority_worker_version_id",
  "authority_worker_version_tag",
  "caller_source_sha",
  "caller_worker_version_id",
  "caller_worker_version_tag",
  "operation_id",
  "request_nonce",
  "initial_state",
  "initial_state_digest",
  "initial_result_digest",
  "initial_created_at",
  "recovery_event",
  "recovery_event_digest",
  "recovery_event_tail_digest",
  "recovered_at",
  "first_recovery_state",
  "first_recovery_result_digest",
  "replay_event",
  "replay_event_digest",
  "replay_event_tail_digest",
  "replay_confirmed_at",
  "replayed",
  "final_state",
  "issuer_key_id",
  "issued_at",
] as const;

const ATTESTATION_FIELDS = [
  "schema_version",
  "purpose",
  "eligibility",
  "environment",
  "issuer_class",
  "issuer_key_id",
  "authority_instance_digest",
  "signed_claims_base64",
  "signed_claims_digest",
  "signature",
  "issued_at",
] as const;

type AuditRequest =
  | ReceiptAuditRecoveryCanaryBeginRequestV1
  | ReceiptAuditRecoveryCanaryRecoverRequestV1;

export type VerifiedAuditRecoveryAttestationStructure = {
  attestation: ReceiptAuditRecoveryAttestationV1;
  claims: ReceiptAuditRecoveryAttestationClaimsV1;
  signedClaimsBytes: Uint8Array;
};

function canonicalTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString() === value;
}

function canonicalBase64(value: unknown, expectedLength?: number): Uint8Array | null {
  if (typeof value !== "string") return null;
  try {
    const decoded = base64ToBytes(value);
    if (
      bytesToBase64(decoded) !== value ||
      (expectedLength !== undefined && decoded.length !== expectedLength)
    ) return null;
    return decoded;
  } catch {
    return null;
  }
}

export function requireAuditRecoveryRequest<T extends AuditRequest>(
  value: unknown,
  expectedOperation: T["operation"],
): T {
  if (!isPlainObject(value) || !exactKeys(value, REQUEST_FIELDS)) {
    throw new TypeError("Receipt audit recovery request is not closed");
  }
  if (
    value.schema_version !== "receipt-audit-recovery-canary-request/v1" ||
    value.purpose !== "receipt_authority_recovery_canary" ||
    value.eligibility !== "AUDIT_ONLY" ||
    value.operation !== expectedOperation ||
    value.environment !== "staging" ||
    typeof value.caller_source_sha !== "string" ||
    !SOURCE_SHA.test(value.caller_source_sha) ||
    typeof value.caller_worker_version_id !== "string" ||
    !UUID.test(value.caller_worker_version_id) ||
    value.caller_worker_version_tag !== `ra-s-c-${value.caller_source_sha}` ||
    typeof value.request_nonce !== "string" ||
    !NONCE.test(value.request_nonce)
  ) throw new TypeError("Receipt audit recovery request is invalid");
  return value as T;
}

export function auditRecoveryIdentity(request: AuditRequest) {
  return {
    schema_version: "receipt-audit-recovery-canary-identity/v1" as const,
    purpose: "receipt_authority_recovery_canary" as const,
    eligibility: "AUDIT_ONLY" as const,
    environment: "staging" as const,
    caller_source_sha: request.caller_source_sha,
    caller_worker_version_id: request.caller_worker_version_id,
    caller_worker_version_tag: request.caller_worker_version_tag,
    request_nonce: request.request_nonce,
  };
}

export function auditRecoveryOperationId(request: AuditRequest): Promise<string> {
  return canonicalDigest(auditRecoveryIdentity(request));
}

export function auditInitialStateDocument(
  operationId: string,
  createdAt: string,
) {
  return {
    schema_version: "receipt-audit-recovery-initial-state/v1" as const,
    purpose: "receipt_authority_recovery_canary" as const,
    eligibility: "AUDIT_ONLY" as const,
    environment: "staging" as const,
    operation_id: operationId,
    request_digest: operationId,
    state: "RECOVERY_REQUIRED" as const,
    created_at: createdAt,
  };
}

export function auditInitialResult(
  operationId: string,
  requestNonce: string,
  initialStateDigest: string,
  createdAt: string,
): ReceiptAuditRecoveryInitialResultV1 {
  return {
    schema_version: "receipt-audit-recovery-initial-result/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
    environment: "staging",
    operation_id: operationId,
    request_nonce: requestNonce,
    state: "RECOVERY_REQUIRED",
    initial_state_digest: initialStateDigest,
    created_at: createdAt,
  };
}

export function auditInitialEventDocument(
  operationId: string,
  initialStateDigest: string,
  createdAt: string,
) {
  return {
    schema_version: "receipt-audit-recovery-event-link/v1" as const,
    purpose: "receipt_authority_recovery_canary" as const,
    eligibility: "AUDIT_ONLY" as const,
    environment: "staging" as const,
    operation_id: operationId,
    event: "INITIAL_COMMITTED" as const,
    payload_digest: initialStateDigest,
    prior_event_digest: null,
    observed_at: createdAt,
  };
}

export function auditRecoveryEventPayload(
  operationId: string,
  requestNonce: string,
  initialStateDigest: string,
  initialResultDigest: string,
  recoveredAt: string,
) {
  return {
    schema_version: "receipt-audit-recovery-event/v1" as const,
    purpose: "receipt_authority_recovery_canary" as const,
    eligibility: "AUDIT_ONLY" as const,
    environment: "staging" as const,
    operation_id: operationId,
    request_nonce: requestNonce,
    event: "RECOVERY_COMPLETED" as const,
    from_state: "RECOVERY_REQUIRED" as const,
    to_state: "RECOVERED_PENDING_REPLAY" as const,
    initial_state_digest: initialStateDigest,
    initial_result_digest: initialResultDigest,
    recovered_at: recoveredAt,
  };
}

export function auditRecoveryEventTail(
  operationId: string,
  recoveryEventDigest: string,
  priorEventDigest: string,
  recoveredAt: string,
) {
  return {
    schema_version: "receipt-audit-recovery-event-link/v1" as const,
    purpose: "receipt_authority_recovery_canary" as const,
    eligibility: "AUDIT_ONLY" as const,
    environment: "staging" as const,
    operation_id: operationId,
    event: "RECOVERY_COMPLETED" as const,
    payload_digest: recoveryEventDigest,
    prior_event_digest: priorEventDigest,
    observed_at: recoveredAt,
  };
}

export function auditFirstRecoveryResult(
  operationId: string,
  requestNonce: string,
  initialStateDigest: string,
  initialResultDigest: string,
  recoveryEventDigest: string,
  recoveryEventTailDigest: string,
  recoveredAt: string,
): ReceiptAuditFirstRecoveryResultV1 {
  return {
    schema_version: "receipt-audit-first-recovery-result/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
    environment: "staging",
    operation_id: operationId,
    request_nonce: requestNonce,
    initial_state_digest: initialStateDigest,
    initial_result_digest: initialResultDigest,
    recovery_event_digest: recoveryEventDigest,
    recovery_event_tail_digest: recoveryEventTailDigest,
    recovered_at: recoveredAt,
    state: "RECOVERED_PENDING_REPLAY",
  };
}

export function auditReplayEventPayload(
  operationId: string,
  requestNonce: string,
  firstRecoveryResultDigest: string,
  recoveryEventDigest: string,
  recoveryEventTailDigest: string,
  replayConfirmedAt: string,
) {
  return {
    schema_version: "receipt-audit-replay-event/v1" as const,
    purpose: "receipt_authority_recovery_canary" as const,
    eligibility: "AUDIT_ONLY" as const,
    environment: "staging" as const,
    operation_id: operationId,
    request_nonce: requestNonce,
    event: "REPLAY_CONFIRMED" as const,
    from_state: "RECOVERED_PENDING_REPLAY" as const,
    to_state: "AUDIT_FINALIZED" as const,
    first_recovery_result_digest: firstRecoveryResultDigest,
    recovery_event_digest: recoveryEventDigest,
    recovery_event_tail_digest: recoveryEventTailDigest,
    replay_confirmed_at: replayConfirmedAt,
  };
}

export function auditReplayEventTail(
  operationId: string,
  replayEventDigest: string,
  recoveryEventTailDigest: string,
  replayConfirmedAt: string,
) {
  return {
    schema_version: "receipt-audit-recovery-event-link/v1" as const,
    purpose: "receipt_authority_recovery_canary" as const,
    eligibility: "AUDIT_ONLY" as const,
    environment: "staging" as const,
    operation_id: operationId,
    event: "REPLAY_CONFIRMED" as const,
    payload_digest: replayEventDigest,
    prior_event_digest: recoveryEventTailDigest,
    observed_at: replayConfirmedAt,
  };
}

export async function requireAuditRecoveryAttestationStructure(
  value: unknown,
): Promise<VerifiedAuditRecoveryAttestationStructure> {
  if (!isPlainObject(value) || !exactKeys(value, ATTESTATION_FIELDS)) {
    throw new Error("Receipt audit recovery attestation is not closed");
  }
  const signedBytes = canonicalBase64(value.signed_claims_base64);
  const signature = typeof value.signature === "string" &&
      value.signature.startsWith("ed25519:")
    ? canonicalBase64(value.signature.slice("ed25519:".length), 64)
    : null;
  if (
    value.schema_version !== "receipt-audit-recovery-attestation/v1" ||
    value.purpose !== "receipt_authority_recovery_canary" ||
    value.eligibility !== "AUDIT_ONLY" ||
    value.environment !== "staging" ||
    value.issuer_class !== "ReceiptEvidenceAuthorityAuditSigner" ||
    typeof value.issuer_key_id !== "string" ||
    !/^receipt-staging-[0-9a-f]{16}$/.test(value.issuer_key_id) ||
    !isSha256(value.authority_instance_digest) ||
    signedBytes === null || signature === null ||
    !isSha256(value.signed_claims_digest) ||
    !canonicalTimestamp(value.issued_at)
  ) throw new Error("Receipt audit recovery attestation is invalid");

  let parsed: unknown;
  try {
    const raw = new TextDecoder().decode(signedBytes);
    parsed = JSON.parse(raw);
    if (canonicalJson(parsed) !== raw) {
      throw new Error("signed claims are not canonical");
    }
  } catch {
    throw new Error("Receipt audit recovery signed claims are invalid");
  }
  if (!isPlainObject(parsed) || !exactKeys(parsed, CLAIM_FIELDS)) {
    throw new Error("Receipt audit recovery signed claims are not closed");
  }
  if (
    parsed.schema_version !== "receipt-audit-recovery-attestation-claims/v1" ||
    parsed.purpose !== "receipt_authority_recovery_canary" ||
    parsed.eligibility !== "AUDIT_ONLY" ||
    parsed.environment !== "staging" ||
    !isSha256(parsed.authority_instance_digest) ||
    typeof parsed.authority_source_sha !== "string" ||
    !SOURCE_SHA.test(parsed.authority_source_sha) ||
    typeof parsed.authority_worker_version_id !== "string" ||
    !UUID.test(parsed.authority_worker_version_id) ||
    parsed.authority_worker_version_tag !==
      `ra-s-r-${parsed.authority_source_sha}` ||
    typeof parsed.caller_source_sha !== "string" ||
    !SOURCE_SHA.test(parsed.caller_source_sha) ||
    typeof parsed.caller_worker_version_id !== "string" ||
    !UUID.test(parsed.caller_worker_version_id) ||
    parsed.caller_worker_version_tag !== `ra-s-c-${parsed.caller_source_sha}` ||
    !isSha256(parsed.operation_id) ||
    typeof parsed.request_nonce !== "string" || !NONCE.test(parsed.request_nonce) ||
    parsed.initial_state !== "RECOVERY_REQUIRED" ||
    !isSha256(parsed.initial_state_digest) ||
    !isSha256(parsed.initial_result_digest) ||
    !canonicalTimestamp(parsed.initial_created_at) ||
    parsed.recovery_event !== "RECOVERY_COMPLETED" ||
    !isSha256(parsed.recovery_event_digest) ||
    !isSha256(parsed.recovery_event_tail_digest) ||
    !canonicalTimestamp(parsed.recovered_at) ||
    parsed.first_recovery_state !== "RECOVERED_PENDING_REPLAY" ||
    !isSha256(parsed.first_recovery_result_digest) ||
    parsed.replay_event !== "REPLAY_CONFIRMED" ||
    !isSha256(parsed.replay_event_digest) ||
    !isSha256(parsed.replay_event_tail_digest) ||
    !canonicalTimestamp(parsed.replay_confirmed_at) ||
    parsed.replayed !== true || parsed.final_state !== "AUDIT_FINALIZED" ||
    parsed.issuer_key_id !== value.issuer_key_id ||
    parsed.authority_instance_digest !== value.authority_instance_digest ||
    parsed.issued_at !== value.issued_at ||
    parsed.issued_at !== parsed.replay_confirmed_at ||
    Date.parse(parsed.recovered_at) < Date.parse(parsed.initial_created_at) ||
    Date.parse(parsed.replay_confirmed_at) < Date.parse(parsed.recovered_at) ||
    await sha256Digest(signedBytes) !== value.signed_claims_digest
  ) throw new Error("Receipt audit recovery signed claims are invalid");

  const claims = parsed as ReceiptAuditRecoveryAttestationClaimsV1;
  const beginRequest: ReceiptAuditRecoveryCanaryBeginRequestV1 = {
    schema_version: "receipt-audit-recovery-canary-request/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
    operation: "begin_audit_recovery_canary",
    environment: "staging",
    caller_source_sha: claims.caller_source_sha,
    caller_worker_version_id: claims.caller_worker_version_id,
    caller_worker_version_tag: claims.caller_worker_version_tag,
    request_nonce: claims.request_nonce,
  };
  const operationId = await auditRecoveryOperationId(beginRequest);
  const initialStateDigest = await canonicalDigest(auditInitialStateDocument(
    operationId,
    claims.initial_created_at,
  ));
  const initialResultDigest = await canonicalDigest(auditInitialResult(
    operationId,
    claims.request_nonce,
    initialStateDigest,
    claims.initial_created_at,
  ));
  const initialEventDigest = await canonicalDigest(auditInitialEventDocument(
    operationId,
    initialStateDigest,
    claims.initial_created_at,
  ));
  const recoveryEventDigest = await canonicalDigest(auditRecoveryEventPayload(
    operationId,
    claims.request_nonce,
    initialStateDigest,
    initialResultDigest,
    claims.recovered_at,
  ));
  const recoveryTailDigest = await canonicalDigest(auditRecoveryEventTail(
    operationId,
    recoveryEventDigest,
    initialEventDigest,
    claims.recovered_at,
  ));
  const firstRecoveryResultDigest = await canonicalDigest(
    auditFirstRecoveryResult(
      operationId,
      claims.request_nonce,
      initialStateDigest,
      initialResultDigest,
      recoveryEventDigest,
      recoveryTailDigest,
      claims.recovered_at,
    ),
  );
  const replayEventDigest = await canonicalDigest(auditReplayEventPayload(
    operationId,
    claims.request_nonce,
    firstRecoveryResultDigest,
    recoveryEventDigest,
    recoveryTailDigest,
    claims.replay_confirmed_at,
  ));
  const replayEventTailDigest = await canonicalDigest(auditReplayEventTail(
    operationId,
    replayEventDigest,
    recoveryTailDigest,
    claims.replay_confirmed_at,
  ));
  if (
    claims.operation_id !== operationId ||
    claims.initial_state_digest !== initialStateDigest ||
    claims.initial_result_digest !== initialResultDigest ||
    claims.recovery_event_digest !== recoveryEventDigest ||
    claims.recovery_event_tail_digest !== recoveryTailDigest ||
    claims.first_recovery_result_digest !== firstRecoveryResultDigest ||
    claims.replay_event_digest !== replayEventDigest ||
    claims.replay_event_tail_digest !== replayEventTailDigest
  ) throw new Error("Receipt audit recovery digest chain is invalid");

  return {
    attestation: value as ReceiptAuditRecoveryAttestationV1,
    claims,
    signedClaimsBytes: signedBytes,
  };
}

export const AUDIT_RECOVERY_REQUEST_FIELDS = REQUEST_FIELDS;
