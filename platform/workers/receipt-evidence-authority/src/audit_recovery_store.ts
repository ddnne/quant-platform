import {
  base64ToBytes,
  bytesToBase64,
  canonicalDigest,
  canonicalJson,
  isSha256,
  sha256Digest,
} from "./canonical";
import {
  auditInitialEventDocument,
  auditFirstRecoveryResult,
  auditInitialResult,
  auditInitialStateDocument,
  auditRecoveryEventPayload,
  auditRecoveryEventTail,
  auditRecoveryOperationId,
  auditReplayEventPayload,
  auditReplayEventTail,
  requireAuditRecoveryAttestationStructure,
  requireAuditRecoveryRequest,
} from "./audit_recovery_contract";
import type {
  ReceiptAuditRecoveryAttestationClaimsV1,
  ReceiptAuditRecoveryAttestationV1,
  ReceiptAuditFirstRecoveryResultV1,
  ReceiptAuditRecoveryBeginResultV1,
  ReceiptAuditRecoveryCanaryResultV1,
  ReceiptAuditRecoveryCanaryBeginRequestV1,
  ReceiptAuditRecoveryCanaryRecoverRequestV1,
  ReceiptAuditRecoveryInitialResultV1,
  ReceiptAuditRecoveryPendingReplayResultV1,
  ReceiptAuditRecoveryResultV1,
} from "./types";

type AuditOperationRow = {
  operation_id: string;
  request_digest: string;
  caller_source_sha: string;
  caller_worker_version_id: string;
  caller_worker_version_tag: string;
  request_nonce: string;
  state:
    | "RECOVERY_REQUIRED"
    | "RECOVERED_PENDING_REPLAY"
    | "AUDIT_FINALIZED";
  initial_state_digest: string;
  initial_result_digest: string;
  initial_result_json: string;
  initial_event_digest: string;
  recovery_event_digest: string | null;
  recovery_event_tail_digest: string | null;
  recovered_at: string | null;
  first_recovery_result_digest: string | null;
  first_recovery_result_json: string | null;
  replay_event_digest: string | null;
  replay_event_tail_digest: string | null;
  replay_confirmed_at: string | null;
  signed_attestation_digest: string | null;
  signed_attestation_json: string | null;
  created_at: string;
  updated_at: string;
};

type AuditEventRow = {
  operation_id: string;
  event_ordinal: number;
  event_type:
    | "INITIAL_COMMITTED"
    | "RECOVERY_COMPLETED"
    | "REPLAY_CONFIRMED";
  payload_digest: string;
  prior_event_digest: string | null;
  event_digest: string;
  observed_at: string;
};

export type AuditRecoverySigner = {
  authorityInstanceDigest: string;
  sourceSha: string;
  workerVersionId: string;
  workerVersionTag: string;
  keyId: string;
  privateKey: CryptoKey;
  publicKeyBase64: string;
};

function canonicalTimestamp(value: string): boolean {
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString() === value;
}

function parseInitialResult(value: string): ReceiptAuditRecoveryInitialResultV1 {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("Receipt audit recovery initial result is corrupt");
  }
  if (
    typeof parsed !== "object" || parsed === null || Array.isArray(parsed) ||
    canonicalJson(parsed) !== value
  ) throw new Error("Receipt audit recovery initial result is corrupt");
  return parsed as ReceiptAuditRecoveryInitialResultV1;
}

function parseFirstRecoveryResult(value: string): ReceiptAuditFirstRecoveryResultV1 {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("Receipt audit first recovery result is corrupt");
  }
  if (
    typeof parsed !== "object" || parsed === null || Array.isArray(parsed) ||
    canonicalJson(parsed) !== value
  ) throw new Error("Receipt audit first recovery result is corrupt");
  return parsed as ReceiptAuditFirstRecoveryResultV1;
}

function operation(
  storage: DurableObjectStorage,
  operationId: string,
): AuditOperationRow | null {
  return storage.sql.exec<AuditOperationRow>(
    `SELECT operation_id,request_digest,caller_source_sha,
            caller_worker_version_id,caller_worker_version_tag,request_nonce,
            state,initial_state_digest,initial_result_digest,initial_result_json,
            initial_event_digest,recovery_event_digest,
            recovery_event_tail_digest,recovered_at,
            first_recovery_result_digest,first_recovery_result_json,
            replay_event_digest,replay_event_tail_digest,replay_confirmed_at,
            signed_attestation_digest,signed_attestation_json,created_at,updated_at
       FROM authority_audit_recovery_operations WHERE operation_id=?`,
    operationId,
  ).toArray()[0] ?? null;
}

function events(
  storage: DurableObjectStorage,
  operationId: string,
): AuditEventRow[] {
  return storage.sql.exec<AuditEventRow>(
    `SELECT operation_id,event_ordinal,event_type,payload_digest,
            prior_event_digest,event_digest,observed_at
       FROM authority_audit_recovery_events
      WHERE operation_id=? ORDER BY event_ordinal`,
    operationId,
  ).toArray();
}

function requireIdentity(
  row: AuditOperationRow,
  request:
    | ReceiptAuditRecoveryCanaryBeginRequestV1
    | ReceiptAuditRecoveryCanaryRecoverRequestV1,
  operationId: string,
): void {
  if (
    row.operation_id !== operationId || row.request_digest !== operationId ||
    row.caller_source_sha !== request.caller_source_sha ||
    row.caller_worker_version_id !== request.caller_worker_version_id ||
    row.caller_worker_version_tag !== request.caller_worker_version_tag ||
    row.request_nonce !== request.request_nonce ||
    !canonicalTimestamp(row.created_at) || !canonicalTimestamp(row.updated_at)
  ) throw new Error("Receipt audit recovery operation was substituted");
}

async function requireInitialState(
  storage: DurableObjectStorage,
  row: AuditOperationRow,
  request:
    | ReceiptAuditRecoveryCanaryBeginRequestV1
    | ReceiptAuditRecoveryCanaryRecoverRequestV1,
): Promise<ReceiptAuditRecoveryInitialResultV1> {
  requireIdentity(row, request, row.operation_id);
  const expectedStateDigest = await canonicalDigest(auditInitialStateDocument(
    row.operation_id,
    row.created_at,
  ));
  const expectedResult = auditInitialResult(
    row.operation_id,
    row.request_nonce,
    expectedStateDigest,
    row.created_at,
  );
  const expectedResultJson = canonicalJson(expectedResult);
  const expectedResultDigest = await canonicalDigest(expectedResult);
  const expectedInitialEventDigest = await canonicalDigest(
    auditInitialEventDocument(
      row.operation_id,
      expectedStateDigest,
      row.created_at,
    ),
  );
  const storedResult = parseInitialResult(row.initial_result_json);
  const auditEvents = events(storage, row.operation_id);
  const initialEvent = auditEvents[0];
  if (
    row.initial_state_digest !== expectedStateDigest ||
    row.initial_result_digest !== expectedResultDigest ||
    row.initial_result_json !== expectedResultJson ||
    canonicalJson(storedResult) !== expectedResultJson ||
    row.initial_event_digest !== expectedInitialEventDigest ||
    initialEvent === undefined || initialEvent.event_ordinal !== 1 ||
    initialEvent.event_type !== "INITIAL_COMMITTED" ||
    initialEvent.payload_digest !== expectedStateDigest ||
    initialEvent.prior_event_digest !== null ||
    initialEvent.event_digest !== expectedInitialEventDigest ||
    initialEvent.observed_at !== row.created_at
  ) throw new Error("Receipt audit recovery initial state is corrupt");
  return expectedResult;
}

async function verifyAttestationSignature(
  attestation: ReceiptAuditRecoveryAttestationV1,
  signedClaimsBytes: Uint8Array,
  signer: AuditRecoverySigner,
): Promise<void> {
  if (attestation.issuer_key_id !== signer.keyId) {
    throw new Error("Receipt audit recovery signing key drifted");
  }
  const raw = base64ToBytes(signer.publicKeyBase64);
  if (raw.length !== 32) {
    throw new Error("Receipt audit recovery public key is invalid");
  }
  const publicKey = await crypto.subtle.importKey(
    "raw",
    raw,
    { name: "Ed25519" },
    false,
    ["verify"],
  );
  const signature = base64ToBytes(
    attestation.signature.slice("ed25519:".length),
  );
  if (!await crypto.subtle.verify(
    "Ed25519",
    publicKey,
    signature,
    signedClaimsBytes,
  )) throw new Error("Receipt audit recovery signature is invalid");
}

type FirstRecoveryProof = {
  result: ReceiptAuditFirstRecoveryResultV1;
  resultDigest: string;
  recoveryEventDigest: string;
  recoveryEventTailDigest: string;
};

async function requireFirstRecovery(
  storage: DurableObjectStorage,
  row: AuditOperationRow,
  request: ReceiptAuditRecoveryCanaryRecoverRequestV1,
): Promise<FirstRecoveryProof> {
  await requireInitialState(storage, row, request);
  if (
    row.state === "RECOVERY_REQUIRED" ||
    row.recovery_event_digest === null ||
    row.recovery_event_tail_digest === null || row.recovered_at === null ||
    row.first_recovery_result_digest === null ||
    row.first_recovery_result_json === null ||
    !canonicalTimestamp(row.recovered_at)
  ) throw new Error("Receipt audit first recovery is incomplete");
  const recoveryEventDigest = await canonicalDigest(auditRecoveryEventPayload(
    row.operation_id,
    row.request_nonce,
    row.initial_state_digest,
    row.initial_result_digest,
    row.recovered_at,
  ));
  const recoveryEventTailDigest = await canonicalDigest(auditRecoveryEventTail(
    row.operation_id,
    recoveryEventDigest,
    row.initial_event_digest,
    row.recovered_at,
  ));
  const result = auditFirstRecoveryResult(
    row.operation_id,
    row.request_nonce,
    row.initial_state_digest,
    row.initial_result_digest,
    recoveryEventDigest,
    recoveryEventTailDigest,
    row.recovered_at,
  );
  const resultJson = canonicalJson(result);
  const resultDigest = await canonicalDigest(result);
  const stored = parseFirstRecoveryResult(row.first_recovery_result_json);
  const auditEvents = events(storage, row.operation_id);
  const recoveryEvent = auditEvents[1];
  if (
    auditEvents.length < 2 || recoveryEvent === undefined ||
    recoveryEvent.event_ordinal !== 2 ||
    recoveryEvent.event_type !== "RECOVERY_COMPLETED" ||
    recoveryEvent.payload_digest !== recoveryEventDigest ||
    recoveryEvent.prior_event_digest !== row.initial_event_digest ||
    recoveryEvent.event_digest !== recoveryEventTailDigest ||
    recoveryEvent.observed_at !== row.recovered_at ||
    row.recovery_event_digest !== recoveryEventDigest ||
    row.recovery_event_tail_digest !== recoveryEventTailDigest ||
    row.first_recovery_result_digest !== resultDigest ||
    row.first_recovery_result_json !== resultJson ||
    canonicalJson(stored) !== resultJson
  ) throw new Error("Receipt audit first recovery chain is corrupt");
  return { result, resultDigest, recoveryEventDigest, recoveryEventTailDigest };
}

async function requireFinalized(
  storage: DurableObjectStorage,
  row: AuditOperationRow,
  request: ReceiptAuditRecoveryCanaryRecoverRequestV1,
  signer: AuditRecoverySigner,
): Promise<ReceiptAuditRecoveryResultV1> {
  const initial = await requireInitialState(storage, row, request);
  const first = await requireFirstRecovery(storage, row, request);
  if (
    row.state !== "AUDIT_FINALIZED" || row.replay_event_digest === null ||
    row.replay_event_tail_digest === null || row.replay_confirmed_at === null ||
    row.signed_attestation_digest === null ||
    row.signed_attestation_json === null ||
    !canonicalTimestamp(row.replay_confirmed_at)
  ) throw new Error("Receipt audit recovery final state is incomplete");
  const replayEventDigest = await canonicalDigest(auditReplayEventPayload(
    row.operation_id,
    row.request_nonce,
    first.resultDigest,
    first.recoveryEventDigest,
    first.recoveryEventTailDigest,
    row.replay_confirmed_at,
  ));
  const replayEventTailDigest = await canonicalDigest(auditReplayEventTail(
    row.operation_id,
    replayEventDigest,
    first.recoveryEventTailDigest,
    row.replay_confirmed_at,
  ));
  const auditEvents = events(storage, row.operation_id);
  const replayEvent = auditEvents[2];
  if (
    auditEvents.length !== 3 || replayEvent === undefined ||
    replayEvent.event_ordinal !== 3 ||
    replayEvent.event_type !== "REPLAY_CONFIRMED" ||
    replayEvent.payload_digest !== replayEventDigest ||
    replayEvent.prior_event_digest !== first.recoveryEventTailDigest ||
    replayEvent.event_digest !== replayEventTailDigest ||
    replayEvent.observed_at !== row.replay_confirmed_at ||
    row.replay_event_digest !== replayEventDigest ||
    row.replay_event_tail_digest !== replayEventTailDigest
  ) throw new Error("Receipt audit replay event chain is corrupt");

  let rawAttestation: unknown;
  try {
    rawAttestation = JSON.parse(row.signed_attestation_json);
  } catch {
    throw new Error("Receipt audit recovery attestation storage is corrupt");
  }
  const verified = await requireAuditRecoveryAttestationStructure(rawAttestation);
  if (
    canonicalJson(verified.attestation) !== row.signed_attestation_json ||
    await canonicalDigest(verified.attestation) !== row.signed_attestation_digest ||
    verified.claims.operation_id !== row.operation_id ||
    verified.claims.request_nonce !== row.request_nonce ||
    verified.claims.initial_state_digest !== row.initial_state_digest ||
    verified.claims.initial_result_digest !== row.initial_result_digest ||
    verified.claims.initial_created_at !== initial.created_at ||
    verified.claims.recovery_event_digest !== first.recoveryEventDigest ||
    verified.claims.recovery_event_tail_digest !==
      first.recoveryEventTailDigest ||
    verified.claims.recovered_at !== row.recovered_at ||
    verified.claims.first_recovery_result_digest !== first.resultDigest ||
    verified.claims.replay_event_digest !== replayEventDigest ||
    verified.claims.replay_event_tail_digest !== replayEventTailDigest ||
    verified.claims.replay_confirmed_at !== row.replay_confirmed_at ||
    verified.claims.authority_instance_digest !== signer.authorityInstanceDigest ||
    verified.claims.authority_source_sha !== signer.sourceSha ||
    verified.claims.authority_worker_version_id !== signer.workerVersionId ||
    verified.claims.authority_worker_version_tag !== signer.workerVersionTag ||
    verified.claims.caller_source_sha !== row.caller_source_sha ||
    verified.claims.caller_worker_version_id !== row.caller_worker_version_id ||
    verified.claims.caller_worker_version_tag !== row.caller_worker_version_tag
  ) throw new Error("Receipt audit recovery attestation was substituted");
  await verifyAttestationSignature(
    verified.attestation,
    verified.signedClaimsBytes,
    signer,
  );
  return {
    schema_version: "receipt-audit-recovery-result/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
    operation_id: row.operation_id,
    final_state: "AUDIT_FINALIZED",
    signed_attestation_digest: row.signed_attestation_digest,
    signed_attestation: verified.attestation,
    rpc_replayed: true,
  };
}

export function initializeAuditRecoveryStore(
  storage: DurableObjectStorage,
): void {
  storage.sql.exec(`
    CREATE TABLE IF NOT EXISTS authority_audit_recovery_operations (
      operation_id TEXT PRIMARY KEY,
      request_digest TEXT NOT NULL UNIQUE,
      caller_source_sha TEXT NOT NULL,
      caller_worker_version_id TEXT NOT NULL,
      caller_worker_version_tag TEXT NOT NULL,
      request_nonce TEXT NOT NULL,
      state TEXT NOT NULL CHECK (
        state IN (
          'RECOVERY_REQUIRED','RECOVERED_PENDING_REPLAY','AUDIT_FINALIZED'
        )
      ),
      initial_state_digest TEXT NOT NULL,
      initial_result_digest TEXT NOT NULL,
      initial_result_json TEXT NOT NULL,
      initial_event_digest TEXT NOT NULL,
      recovery_event_digest TEXT,
      recovery_event_tail_digest TEXT,
      recovered_at TEXT,
      first_recovery_result_digest TEXT,
      first_recovery_result_json TEXT,
      replay_event_digest TEXT,
      replay_event_tail_digest TEXT,
      replay_confirmed_at TEXT,
      signed_attestation_digest TEXT,
      signed_attestation_json TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      CHECK (
        (state = 'RECOVERY_REQUIRED'
         AND recovery_event_digest IS NULL
         AND recovery_event_tail_digest IS NULL
         AND recovered_at IS NULL
         AND first_recovery_result_digest IS NULL
         AND first_recovery_result_json IS NULL
         AND replay_event_digest IS NULL
         AND replay_event_tail_digest IS NULL
         AND replay_confirmed_at IS NULL
         AND signed_attestation_digest IS NULL
         AND signed_attestation_json IS NULL)
        OR
        (state = 'RECOVERED_PENDING_REPLAY'
         AND recovery_event_digest IS NOT NULL
         AND recovery_event_tail_digest IS NOT NULL
         AND recovered_at IS NOT NULL
         AND first_recovery_result_digest IS NOT NULL
         AND first_recovery_result_json IS NOT NULL
         AND replay_event_digest IS NULL
         AND replay_event_tail_digest IS NULL
         AND replay_confirmed_at IS NULL
         AND signed_attestation_digest IS NULL
         AND signed_attestation_json IS NULL)
        OR
        (state = 'AUDIT_FINALIZED'
         AND recovery_event_digest IS NOT NULL
         AND recovery_event_tail_digest IS NOT NULL
         AND recovered_at IS NOT NULL
         AND first_recovery_result_digest IS NOT NULL
         AND first_recovery_result_json IS NOT NULL
         AND replay_event_digest IS NOT NULL
         AND replay_event_tail_digest IS NOT NULL
         AND replay_confirmed_at IS NOT NULL
         AND signed_attestation_digest IS NOT NULL
         AND signed_attestation_json IS NOT NULL)
      )
    );
    CREATE TABLE IF NOT EXISTS authority_audit_recovery_events (
      operation_id TEXT NOT NULL,
      event_ordinal INTEGER NOT NULL CHECK (event_ordinal IN (1,2,3)),
      event_type TEXT NOT NULL CHECK (
        event_type IN ('INITIAL_COMMITTED','RECOVERY_COMPLETED','REPLAY_CONFIRMED')
      ),
      payload_digest TEXT NOT NULL,
      prior_event_digest TEXT,
      event_digest TEXT NOT NULL UNIQUE,
      observed_at TEXT NOT NULL,
      PRIMARY KEY(operation_id,event_ordinal),
      FOREIGN KEY(operation_id)
        REFERENCES authority_audit_recovery_operations(operation_id)
    );
    CREATE TRIGGER IF NOT EXISTS authority_audit_recovery_events_no_update
    BEFORE UPDATE ON authority_audit_recovery_events
    BEGIN
      SELECT RAISE(ABORT, 'audit recovery events are append-only');
    END;
    CREATE TRIGGER IF NOT EXISTS authority_audit_recovery_events_no_delete
    BEFORE DELETE ON authority_audit_recovery_events
    BEGIN
      SELECT RAISE(ABORT, 'audit recovery events are append-only');
    END;
    CREATE TRIGGER IF NOT EXISTS authority_audit_recovery_operations_no_delete
    BEFORE DELETE ON authority_audit_recovery_operations
    BEGIN
      SELECT RAISE(ABORT, 'audit recovery operations are append-only');
    END;
    CREATE TRIGGER IF NOT EXISTS authority_audit_recovery_identity_immutable
    BEFORE UPDATE ON authority_audit_recovery_operations
    WHEN OLD.operation_id IS NOT NEW.operation_id
      OR OLD.request_digest IS NOT NEW.request_digest
      OR OLD.caller_source_sha IS NOT NEW.caller_source_sha
      OR OLD.caller_worker_version_id IS NOT NEW.caller_worker_version_id
      OR OLD.caller_worker_version_tag IS NOT NEW.caller_worker_version_tag
      OR OLD.request_nonce IS NOT NEW.request_nonce
      OR OLD.initial_state_digest IS NOT NEW.initial_state_digest
      OR OLD.initial_result_digest IS NOT NEW.initial_result_digest
      OR OLD.initial_result_json IS NOT NEW.initial_result_json
      OR OLD.initial_event_digest IS NOT NEW.initial_event_digest
      OR OLD.created_at IS NOT NEW.created_at
      OR NEW.updated_at < OLD.updated_at
    BEGIN
      SELECT RAISE(ABORT, 'audit recovery operation identity is immutable');
    END;
    CREATE TRIGGER IF NOT EXISTS authority_audit_recovery_monotonic
    BEFORE UPDATE ON authority_audit_recovery_operations
    WHEN NOT (
      (
        OLD.state = 'RECOVERY_REQUIRED'
        AND NEW.state = 'RECOVERED_PENDING_REPLAY'
        AND OLD.recovery_event_digest IS NULL
        AND OLD.recovery_event_tail_digest IS NULL
        AND OLD.recovered_at IS NULL
        AND OLD.first_recovery_result_digest IS NULL
        AND OLD.first_recovery_result_json IS NULL
        AND OLD.replay_event_digest IS NULL
        AND OLD.replay_event_tail_digest IS NULL
        AND OLD.replay_confirmed_at IS NULL
        AND OLD.signed_attestation_digest IS NULL
        AND OLD.signed_attestation_json IS NULL
        AND NEW.recovery_event_digest IS NOT NULL
        AND NEW.recovery_event_tail_digest IS NOT NULL
        AND NEW.recovered_at IS NOT NULL
        AND NEW.first_recovery_result_digest IS NOT NULL
        AND NEW.first_recovery_result_json IS NOT NULL
        AND NEW.replay_event_digest IS NULL
        AND NEW.replay_event_tail_digest IS NULL
        AND NEW.replay_confirmed_at IS NULL
        AND NEW.signed_attestation_digest IS NULL
        AND NEW.signed_attestation_json IS NULL
      )
      OR
      (
        OLD.state = 'RECOVERED_PENDING_REPLAY'
        AND NEW.state = 'AUDIT_FINALIZED'
        AND NEW.recovery_event_digest IS OLD.recovery_event_digest
        AND NEW.recovery_event_tail_digest IS OLD.recovery_event_tail_digest
        AND NEW.recovered_at IS OLD.recovered_at
        AND NEW.first_recovery_result_digest IS OLD.first_recovery_result_digest
        AND NEW.first_recovery_result_json IS OLD.first_recovery_result_json
        AND OLD.replay_event_digest IS NULL
        AND OLD.replay_event_tail_digest IS NULL
        AND OLD.replay_confirmed_at IS NULL
        AND OLD.signed_attestation_digest IS NULL
        AND OLD.signed_attestation_json IS NULL
        AND NEW.replay_event_digest IS NOT NULL
        AND NEW.replay_event_tail_digest IS NOT NULL
        AND NEW.replay_confirmed_at IS NOT NULL
        AND NEW.signed_attestation_digest IS NOT NULL
        AND NEW.signed_attestation_json IS NOT NULL
      )
    )
    BEGIN
      SELECT RAISE(ABORT, 'audit recovery transition is not monotonic');
    END;
  `);
}

export async function beginAuditRecoveryCanary(
  storage: DurableObjectStorage,
  rawRequest: unknown,
): Promise<ReceiptAuditRecoveryBeginResultV1> {
  const request = requireAuditRecoveryRequest<
    ReceiptAuditRecoveryCanaryBeginRequestV1
  >(rawRequest, "begin_audit_recovery_canary");
  const operationId = await auditRecoveryOperationId(request);
  const existing = operation(storage, operationId);
  if (existing !== null) {
    const initialResult = await requireInitialState(storage, existing, request);
    return {
      schema_version: "receipt-audit-recovery-begin-result/v1",
      purpose: "receipt_authority_recovery_canary",
      eligibility: "AUDIT_ONLY",
      operation_id: operationId,
      initial_result_digest: existing.initial_result_digest,
      initial_result: initialResult,
      rpc_replayed: true,
    };
  }

  const createdAt = new Date().toISOString();
  const initialStateDigest = await canonicalDigest(auditInitialStateDocument(
    operationId,
    createdAt,
  ));
  const initialResult = auditInitialResult(
    operationId,
    request.request_nonce,
    initialStateDigest,
    createdAt,
  );
  const initialResultDigest = await canonicalDigest(initialResult);
  const initialResultJson = canonicalJson(initialResult);
  const initialEventDigest = await canonicalDigest(auditInitialEventDocument(
    operationId,
    initialStateDigest,
    createdAt,
  ));
  const inserted = storage.transactionSync(() => {
    if (operation(storage, operationId) !== null) {
      return false;
    }
    storage.sql.exec(
      `INSERT INTO authority_audit_recovery_operations
       (operation_id,request_digest,caller_source_sha,caller_worker_version_id,
        caller_worker_version_tag,request_nonce,state,initial_state_digest,
        initial_result_digest,initial_result_json,initial_event_digest,
        created_at,updated_at)
       VALUES (?,?,?,?,?,?,'RECOVERY_REQUIRED',?,?,?,?,?,?)`,
      operationId,
      operationId,
      request.caller_source_sha,
      request.caller_worker_version_id,
      request.caller_worker_version_tag,
      request.request_nonce,
      initialStateDigest,
      initialResultDigest,
      initialResultJson,
      initialEventDigest,
      createdAt,
      createdAt,
    );
    storage.sql.exec(
      `INSERT INTO authority_audit_recovery_events
       (operation_id,event_ordinal,event_type,payload_digest,
        prior_event_digest,event_digest,observed_at)
       VALUES (?,1,'INITIAL_COMMITTED',?,NULL,?,?)`,
      operationId,
      initialStateDigest,
      initialEventDigest,
      createdAt,
    );
    return true;
  });
  const committed = operation(storage, operationId);
  if (committed === null) throw new Error("Receipt audit recovery begin failed");
  const committedResult = await requireInitialState(storage, committed, request);
  return {
    schema_version: "receipt-audit-recovery-begin-result/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
    operation_id: operationId,
    initial_result_digest: committed.initial_result_digest,
    initial_result: committedResult,
    rpc_replayed: !inserted,
  };
}

export async function recoverAuditRecoveryCanary(
  storage: DurableObjectStorage,
  rawRequest: unknown,
  signer: AuditRecoverySigner,
): Promise<ReceiptAuditRecoveryCanaryResultV1> {
  const request = requireAuditRecoveryRequest<
    ReceiptAuditRecoveryCanaryRecoverRequestV1
  >(rawRequest, "recover_audit_recovery_canary");
  const operationId = await auditRecoveryOperationId(request);
  const existing = operation(storage, operationId);
  if (existing === null) {
    throw new Error("Receipt audit recovery operation was not begun");
  }
  await requireInitialState(storage, existing, request);
  if (existing.state === "AUDIT_FINALIZED") {
    return requireFinalized(storage, existing, request, signer);
  }

  if (existing.state === "RECOVERY_REQUIRED") {
    const recoveredAt = new Date().toISOString();
    const recoveryEventDigest = await canonicalDigest(auditRecoveryEventPayload(
      operationId,
      request.request_nonce,
      existing.initial_state_digest,
      existing.initial_result_digest,
      recoveredAt,
    ));
    const recoveryEventTailDigest = await canonicalDigest(auditRecoveryEventTail(
      operationId,
      recoveryEventDigest,
      existing.initial_event_digest,
      recoveredAt,
    ));
    const firstRecoveryResult = auditFirstRecoveryResult(
      operationId,
      request.request_nonce,
      existing.initial_state_digest,
      existing.initial_result_digest,
      recoveryEventDigest,
      recoveryEventTailDigest,
      recoveredAt,
    );
    const firstRecoveryResultDigest = await canonicalDigest(firstRecoveryResult);
    const firstRecoveryResultJson = canonicalJson(firstRecoveryResult);
    const committed = storage.transactionSync(() => {
      const current = operation(storage, operationId);
      if (current === null) {
        throw new Error("Receipt audit recovery operation disappeared");
      }
      if (current.state !== "RECOVERY_REQUIRED") return false;
      requireIdentity(current, request, operationId);
      if (
        current.initial_state_digest !== existing.initial_state_digest ||
        current.initial_result_digest !== existing.initial_result_digest ||
        current.initial_event_digest !== existing.initial_event_digest
      ) throw new Error("Receipt audit recovery initial state drifted");
      storage.sql.exec(
        `UPDATE authority_audit_recovery_operations
            SET state='RECOVERED_PENDING_REPLAY',recovery_event_digest=?,
                recovery_event_tail_digest=?,recovered_at=?,
                first_recovery_result_digest=?,first_recovery_result_json=?,
                updated_at=?
          WHERE operation_id=? AND state='RECOVERY_REQUIRED'`,
        recoveryEventDigest,
        recoveryEventTailDigest,
        recoveredAt,
        firstRecoveryResultDigest,
        firstRecoveryResultJson,
        recoveredAt,
        operationId,
      );
      storage.sql.exec(
        `INSERT INTO authority_audit_recovery_events
         (operation_id,event_ordinal,event_type,payload_digest,
          prior_event_digest,event_digest,observed_at)
         VALUES (?,2,'RECOVERY_COMPLETED',?,?,?,?)`,
        operationId,
        recoveryEventDigest,
        existing.initial_event_digest,
        recoveryEventTailDigest,
        recoveredAt,
      );
      return true;
    });
    const afterFirst = operation(storage, operationId);
    if (afterFirst === null) {
      throw new Error("Receipt audit first recovery failed");
    }
    if (committed) {
      const first = await requireFirstRecovery(storage, afterFirst, request);
      const pending: ReceiptAuditRecoveryPendingReplayResultV1 = {
        schema_version: "receipt-audit-recovery-pending-replay-result/v1",
        purpose: "receipt_authority_recovery_canary",
        eligibility: "AUDIT_ONLY",
        operation_id: operationId,
        state: "RECOVERED_PENDING_REPLAY",
        first_recovery_result_digest: first.resultDigest,
        first_recovery_result: first.result,
        rpc_replayed: false,
      };
      return pending;
    }
    if (afterFirst.state === "AUDIT_FINALIZED") {
      return requireFinalized(storage, afterFirst, request, signer);
    }
  }

  const pendingReplay = operation(storage, operationId);
  if (pendingReplay === null) {
    throw new Error("Receipt audit replay operation disappeared");
  }
  if (pendingReplay.state === "AUDIT_FINALIZED") {
    return requireFinalized(storage, pendingReplay, request, signer);
  }
  if (pendingReplay.state !== "RECOVERED_PENDING_REPLAY") {
    throw new Error("Receipt audit recovery did not reach replay state");
  }
  const first = await requireFirstRecovery(storage, pendingReplay, request);
  const replayConfirmedAt = new Date().toISOString();
  const replayEventDigest = await canonicalDigest(auditReplayEventPayload(
    operationId,
    request.request_nonce,
    first.resultDigest,
    first.recoveryEventDigest,
    first.recoveryEventTailDigest,
    replayConfirmedAt,
  ));
  const replayEventTailDigest = await canonicalDigest(auditReplayEventTail(
    operationId,
    replayEventDigest,
    first.recoveryEventTailDigest,
    replayConfirmedAt,
  ));
  const claims: ReceiptAuditRecoveryAttestationClaimsV1 = {
    schema_version: "receipt-audit-recovery-attestation-claims/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
    environment: "staging",
    authority_instance_digest: signer.authorityInstanceDigest,
    authority_source_sha: signer.sourceSha,
    authority_worker_version_id: signer.workerVersionId,
    authority_worker_version_tag: signer.workerVersionTag,
    caller_source_sha: pendingReplay.caller_source_sha,
    caller_worker_version_id: pendingReplay.caller_worker_version_id,
    caller_worker_version_tag: pendingReplay.caller_worker_version_tag,
    operation_id: operationId,
    request_nonce: pendingReplay.request_nonce,
    initial_state: "RECOVERY_REQUIRED",
    initial_state_digest: pendingReplay.initial_state_digest,
    initial_result_digest: pendingReplay.initial_result_digest,
    initial_created_at: pendingReplay.created_at,
    recovery_event: "RECOVERY_COMPLETED",
    recovery_event_digest: first.recoveryEventDigest,
    recovery_event_tail_digest: first.recoveryEventTailDigest,
    recovered_at: first.result.recovered_at,
    first_recovery_state: "RECOVERED_PENDING_REPLAY",
    first_recovery_result_digest: first.resultDigest,
    replay_event: "REPLAY_CONFIRMED",
    replay_event_digest: replayEventDigest,
    replay_event_tail_digest: replayEventTailDigest,
    replay_confirmed_at: replayConfirmedAt,
    replayed: true,
    final_state: "AUDIT_FINALIZED",
    issuer_key_id: signer.keyId,
    issued_at: replayConfirmedAt,
  };
  const signedClaimsJson = canonicalJson(claims);
  const signedClaimsBytes = new TextEncoder().encode(signedClaimsJson);
  const signatureBytes = new Uint8Array(await crypto.subtle.sign(
    "Ed25519",
    signer.privateKey,
    signedClaimsBytes,
  ));
  const attestation: ReceiptAuditRecoveryAttestationV1 = {
    schema_version: "receipt-audit-recovery-attestation/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
    environment: "staging",
    issuer_class: "ReceiptEvidenceAuthorityAuditSigner",
    issuer_key_id: signer.keyId,
    authority_instance_digest: signer.authorityInstanceDigest,
    signed_claims_base64: bytesToBase64(signedClaimsBytes),
    signed_claims_digest: await sha256Digest(signedClaimsBytes),
    signature: `ed25519:${bytesToBase64(signatureBytes)}`,
    issued_at: replayConfirmedAt,
  };
  const verified = await requireAuditRecoveryAttestationStructure(attestation);
  await verifyAttestationSignature(
    verified.attestation,
    verified.signedClaimsBytes,
    signer,
  );
  const attestationJson = canonicalJson(attestation);
  const attestationDigest = await canonicalDigest(attestation);
  storage.transactionSync(() => {
    const current = operation(storage, operationId);
    if (current === null) {
      throw new Error("Receipt audit replay operation disappeared");
    }
    if (current.state === "AUDIT_FINALIZED") return false;
    if (current.state !== "RECOVERED_PENDING_REPLAY") {
      throw new Error("Receipt audit replay state drifted");
    }
    requireIdentity(current, request, operationId);
    if (
      current.first_recovery_result_digest !== first.resultDigest ||
      current.recovery_event_digest !== first.recoveryEventDigest ||
      current.recovery_event_tail_digest !== first.recoveryEventTailDigest
    ) throw new Error("Receipt audit first recovery drifted before replay");
    storage.sql.exec(
      `UPDATE authority_audit_recovery_operations
          SET state='AUDIT_FINALIZED',replay_event_digest=?,
              replay_event_tail_digest=?,replay_confirmed_at=?,
              signed_attestation_digest=?,signed_attestation_json=?,updated_at=?
        WHERE operation_id=? AND state='RECOVERED_PENDING_REPLAY'`,
      replayEventDigest,
      replayEventTailDigest,
      replayConfirmedAt,
      attestationDigest,
      attestationJson,
      replayConfirmedAt,
      operationId,
    );
    storage.sql.exec(
      `INSERT INTO authority_audit_recovery_events
       (operation_id,event_ordinal,event_type,payload_digest,
        prior_event_digest,event_digest,observed_at)
       VALUES (?,3,'REPLAY_CONFIRMED',?,?,?,?)`,
      operationId,
      replayEventDigest,
      first.recoveryEventTailDigest,
      replayEventTailDigest,
      replayConfirmedAt,
    );
    return true;
  });
  const finalized = operation(storage, operationId);
  if (finalized === null) {
    throw new Error("Receipt audit replay finalization failed");
  }
  return requireFinalized(storage, finalized, request, signer);
}
