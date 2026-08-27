import { DurableObject } from "cloudflare:workers";
import {
  arrayBufferToBase64,
  base64ToBytes,
  canonicalDigest,
  canonicalJson,
  isSha256,
  randomHex,
  sha256Digest,
  utf8Base64,
} from "./canonical";
import {
  beginAuditRecoveryCanary,
  initializeAuditRecoveryStore,
  recoverAuditRecoveryCanary,
} from "./audit_recovery_store";
import { requireDerivedClaims } from "./claims_validation";
import { authorityInstanceScope } from "./authority_instance";
import {
  unwrapEd25519PrivateKey,
  wrapEd25519PrivateKey,
  type WrappedPrivateKey,
} from "./key_crypto";
import { executeReceiptRequest } from "./reconcile";
import type {
  ReceiptAuthorityEnv,
  ReceiptAuthorityIssuedRecord,
  ReceiptAuthorityOperationSnapshot,
  ReceiptAuditRecoveryBeginResultV1,
  ReceiptAuditRecoveryCanaryBeginRequestV1,
  ReceiptAuditRecoveryCanaryResultV1,
  ReceiptAuditRecoveryCanaryRecoverRequestV1,
  ReceiptIssueRequestV1,
  ReceiptIssueResultV1,
  ReceiptPublicKeyRegistrationV1,
  ReceiptRecoveryRequestV1,
  SignedReceiptClaimsV3,
  SignedReceiptEnvelopeV3,
  UnsignedReceiptClaimsV3,
} from "./types";

const PARSER_NORMALIZER_VERSION = "coverage-receipt/v4-ed25519-closure";

function pendingDeploymentProvenance(
  env: ReceiptAuthorityEnv,
): { sourceSha: string; versionId: string; versionTag: string } {
  const metadata = env.CF_VERSION_METADATA;
  const environmentCode = env.ENVIRONMENT === "staging" ? "s" : "p";
  const match = new RegExp(`^rp-${environmentCode}-r-([0-9a-f]{40})$`).exec(
    metadata?.tag ?? "",
  );
  if (
    metadata === undefined ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
      .test(metadata.id) ||
    match === null
  ) {
    throw new Error("Receipt authority deployment provenance is invalid");
  }
  return {
    sourceSha: match[1]!,
    versionId: metadata.id,
    versionTag: metadata.tag,
  };
}

function activeStagingDeploymentProvenance(
  env: ReceiptAuthorityEnv,
): { sourceSha: string; versionId: string; versionTag: string } {
  const metadata = env.CF_VERSION_METADATA;
  const match = /^ra-s-r-([0-9a-f]{40})$/.exec(metadata?.tag ?? "");
  if (
    env.ENVIRONMENT !== "staging" || env.AUTHORITY_MODE !== "ACTIVE" ||
    metadata === undefined ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
      .test(metadata.id) ||
    match === null
  ) {
    throw new Error("Receipt audit recovery deployment provenance is invalid");
  }
  return {
    sourceSha: match[1]!,
    versionId: metadata.id,
    versionTag: metadata.tag,
  };
}

type OperationState =
  | "COLLECTING"
  | "ISSUED_PENDING_FINALIZE"
  | "FINALIZED";

type OperationRow = {
  operation_id: string;
  request_digest: string;
  acquisition_nonce: string;
  state: OperationState;
  claims_digest: string | null;
  claims_json: string | null;
  issued_at: string | null;
  envelope_digest: string | null;
  envelope_json: string | null;
  receipt_digest: string | null;
  result_json: string | null;
  created_at: string;
  updated_at: string;
};

type CaptureAttemptRow = {
  operation_id: string;
  attempt_ordinal: number;
  attempt_id: string;
  acquisition_nonce: string;
  state: "OPEN" | "CAPTURED" | "ABANDONED";
  capture_key: string | null;
  capture_digest: string | null;
  created_at: string;
  updated_at: string;
};

type AuthorityEventInput = {
  operationId: string;
  eventType: string;
  payloadDigest: string;
  observedAt: string;
};

type AuthorityEventRow = {
  sequence: number;
  operation_id: string;
  event_type: string;
  payload_digest: string;
  prior_event_digest: string | null;
  event_digest: string;
  observed_at: string;
};

type KeyMaterial = {
  keyId: string;
  generation: number;
  privateKey: CryptoKey;
  publicKeyBase64: string;
  generatedAt: string;
};

function parseStored<T>(value: string | null, field: string): T | null {
  if (value === null) return null;
  try {
    return JSON.parse(value) as T;
  } catch {
    throw new Error(`receipt authority ${field} storage is corrupt`);
  }
}

function rowToSnapshot(
  row: OperationRow,
  attempt: CaptureAttemptRow,
): ReceiptAuthorityOperationSnapshot {
  if (
    attempt.operation_id !== row.operation_id ||
    (attempt.state === "CAPTURED") !==
      (attempt.capture_key !== null && attempt.capture_digest !== null) ||
    (attempt.state !== "CAPTURED" &&
      (attempt.capture_key !== null || attempt.capture_digest !== null))
  ) throw new Error("receipt authority capture attempt storage is corrupt");
  return {
    operation_id: row.operation_id,
    request_digest: row.request_digest,
    capture_attempt_id: attempt.attempt_id,
    capture_attempt_ordinal: attempt.attempt_ordinal,
    acquisition_nonce: attempt.acquisition_nonce,
    collection_started_at: attempt.created_at,
    capture_key: attempt.capture_key,
    capture_digest: attempt.capture_digest,
    state: row.state,
    claims: parseStored<UnsignedReceiptClaimsV3>(row.claims_json, "claims"),
    envelope: parseStored<SignedReceiptEnvelopeV3>(row.envelope_json, "envelope"),
    envelope_digest: row.envelope_digest,
    receipt_digest: row.receipt_digest,
    result: parseStored<ReceiptIssueResultV1>(row.result_json, "result"),
  };
}

export class ReceiptEvidenceAuthority extends DurableObject<ReceiptAuthorityEnv> {
  #keyPromise: Promise<KeyMaterial> | null = null;

  constructor(ctx: DurableObjectState, env: ReceiptAuthorityEnv) {
    super(ctx, env);
    ctx.blockConcurrencyWhile(async () => {
      initializeAuditRecoveryStore(this.ctx.storage);
      this.ctx.storage.sql.exec(`
        CREATE TABLE IF NOT EXISTS authority_operations (
          operation_id TEXT PRIMARY KEY,
          request_digest TEXT NOT NULL UNIQUE,
          acquisition_nonce TEXT NOT NULL,
          state TEXT NOT NULL CHECK (
            state IN ('COLLECTING','ISSUED_PENDING_FINALIZE','FINALIZED')
          ),
          claims_digest TEXT,
          claims_json TEXT,
          issued_at TEXT,
          envelope_digest TEXT,
          envelope_json TEXT,
          receipt_digest TEXT,
          result_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS authority_events (
          sequence INTEGER PRIMARY KEY,
          operation_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          payload_digest TEXT NOT NULL,
          prior_event_digest TEXT,
          event_digest TEXT NOT NULL UNIQUE,
          observed_at TEXT NOT NULL,
          UNIQUE(operation_id,event_type,payload_digest),
          FOREIGN KEY(operation_id) REFERENCES authority_operations(operation_id)
        );
        CREATE TABLE IF NOT EXISTS authority_capture_attempts (
          operation_id TEXT NOT NULL,
          attempt_ordinal INTEGER NOT NULL CHECK (attempt_ordinal > 0),
          attempt_id TEXT NOT NULL UNIQUE,
          acquisition_nonce TEXT NOT NULL UNIQUE,
          state TEXT NOT NULL CHECK (state IN ('OPEN','CAPTURED','ABANDONED')),
          capture_key TEXT,
          capture_digest TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(operation_id,attempt_ordinal),
          FOREIGN KEY(operation_id) REFERENCES authority_operations(operation_id),
          CHECK (
            (state = 'CAPTURED' AND capture_key IS NOT NULL AND capture_digest IS NOT NULL)
            OR
            (state IN ('OPEN','ABANDONED') AND capture_key IS NULL AND capture_digest IS NULL)
          )
        );
        CREATE TABLE IF NOT EXISTS authority_key_metadata (
          key_generation INTEGER PRIMARY KEY CHECK (key_generation > 0),
          key_id TEXT NOT NULL UNIQUE,
          algorithm TEXT NOT NULL CHECK (algorithm = 'Ed25519'),
          public_key_base64 TEXT NOT NULL,
          wrap_algorithm TEXT NOT NULL CHECK (wrap_algorithm = 'AES-GCM'),
          wrap_iv_base64 TEXT NOT NULL,
          wrapped_private_key_base64 TEXT NOT NULL,
          generated_at TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS authority_events_no_update
        BEFORE UPDATE ON authority_events
        BEGIN
          SELECT RAISE(ABORT, 'authority events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS authority_events_no_delete
        BEFORE DELETE ON authority_events
        BEGIN
          SELECT RAISE(ABORT, 'authority events are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS authority_key_metadata_no_update
        BEFORE UPDATE ON authority_key_metadata
        BEGIN
          SELECT RAISE(ABORT, 'authority key metadata is append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS authority_key_metadata_no_delete
        BEFORE DELETE ON authority_key_metadata
        BEGIN
          SELECT RAISE(ABORT, 'authority key metadata is append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS authority_capture_attempts_no_delete
        BEFORE DELETE ON authority_capture_attempts
        BEGIN
          SELECT RAISE(ABORT, 'authority capture attempts are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS authority_capture_attempts_insert_collecting
        BEFORE INSERT ON authority_capture_attempts
        WHEN NOT EXISTS (
          SELECT 1 FROM authority_operations AS operation
           WHERE operation.operation_id = NEW.operation_id
             AND operation.state = 'COLLECTING'
        )
        OR NEW.attempt_ordinal != COALESCE((
          SELECT MAX(attempt.attempt_ordinal)
            FROM authority_capture_attempts AS attempt
           WHERE attempt.operation_id = NEW.operation_id
        ), 0) + 1
        BEGIN
          SELECT RAISE(ABORT, 'authority capture attempt allocation is invalid');
        END;
        CREATE TRIGGER IF NOT EXISTS authority_capture_attempts_monotonic
        BEFORE UPDATE ON authority_capture_attempts
        WHEN OLD.operation_id IS NOT NEW.operation_id
          OR OLD.attempt_ordinal IS NOT NEW.attempt_ordinal
          OR OLD.attempt_id IS NOT NEW.attempt_id
          OR OLD.acquisition_nonce IS NOT NEW.acquisition_nonce
          OR OLD.created_at IS NOT NEW.created_at
          OR NEW.updated_at < OLD.updated_at
          OR NOT (
            (
              OLD.state = 'OPEN'
              AND NEW.state IN ('CAPTURED','ABANDONED')
            )
            OR (
              OLD.state = 'CAPTURED'
              AND NEW.state = 'CAPTURED'
              AND NEW.capture_key IS OLD.capture_key
              AND NEW.capture_digest IS OLD.capture_digest
            )
            OR (
              OLD.state = 'ABANDONED'
              AND NEW.state = 'ABANDONED'
              AND NEW.capture_key IS NULL
              AND NEW.capture_digest IS NULL
            )
          )
        BEGIN
          SELECT RAISE(ABORT, 'authority capture attempt transition is not monotonic');
        END;
        CREATE TRIGGER IF NOT EXISTS authority_operations_no_delete
        BEFORE DELETE ON authority_operations
        BEGIN
          SELECT RAISE(ABORT, 'authority operations are append-only');
        END;
        CREATE TRIGGER IF NOT EXISTS authority_operations_identity_immutable
        BEFORE UPDATE ON authority_operations
        WHEN OLD.operation_id IS NOT NEW.operation_id
          OR OLD.request_digest IS NOT NEW.request_digest
          OR OLD.acquisition_nonce IS NOT NEW.acquisition_nonce
          OR OLD.created_at IS NOT NEW.created_at
          OR NEW.updated_at < OLD.updated_at
        BEGIN
          SELECT RAISE(ABORT, 'authority operation identity is immutable');
        END;
        CREATE TRIGGER IF NOT EXISTS authority_operations_monotonic
        BEFORE UPDATE ON authority_operations
        WHEN NOT (
          (
            OLD.state = 'COLLECTING'
            AND NEW.state = 'COLLECTING'
            AND NEW.envelope_digest IS NULL
            AND NEW.envelope_json IS NULL
            AND NEW.receipt_digest IS NULL
            AND NEW.result_json IS NULL
            AND (
              (
                OLD.claims_digest IS NULL
                AND OLD.claims_json IS NULL
                AND OLD.issued_at IS NULL
                AND NEW.claims_digest IS NOT NULL
                AND NEW.claims_json IS NOT NULL
                AND NEW.issued_at IS NOT NULL
              )
              OR (
                NEW.claims_digest IS OLD.claims_digest
                AND NEW.claims_json IS OLD.claims_json
                AND NEW.issued_at IS OLD.issued_at
              )
            )
          )
          OR (
            OLD.state = 'COLLECTING'
            AND NEW.state = 'ISSUED_PENDING_FINALIZE'
            AND OLD.claims_digest IS NOT NULL
            AND NEW.claims_digest IS OLD.claims_digest
            AND NEW.claims_json IS OLD.claims_json
            AND NEW.issued_at IS OLD.issued_at
            AND OLD.envelope_digest IS NULL
            AND OLD.envelope_json IS NULL
            AND NEW.envelope_digest IS NOT NULL
            AND NEW.envelope_json IS NOT NULL
            AND NEW.receipt_digest IS NULL
            AND NEW.result_json IS NULL
          )
          OR (
            OLD.state = 'ISSUED_PENDING_FINALIZE'
            AND NEW.state = 'ISSUED_PENDING_FINALIZE'
            AND NEW.claims_digest IS OLD.claims_digest
            AND NEW.claims_json IS OLD.claims_json
            AND NEW.issued_at IS OLD.issued_at
            AND NEW.envelope_digest IS OLD.envelope_digest
            AND NEW.envelope_json IS OLD.envelope_json
            AND NEW.receipt_digest IS OLD.receipt_digest
            AND NEW.result_json IS OLD.result_json
          )
          OR (
            OLD.state = 'ISSUED_PENDING_FINALIZE'
            AND NEW.state = 'FINALIZED'
            AND NEW.claims_digest IS OLD.claims_digest
            AND NEW.claims_json IS OLD.claims_json
            AND NEW.issued_at IS OLD.issued_at
            AND NEW.envelope_digest IS OLD.envelope_digest
            AND NEW.envelope_json IS OLD.envelope_json
            AND OLD.receipt_digest IS NULL
            AND OLD.result_json IS NULL
            AND NEW.receipt_digest IS NOT NULL
            AND NEW.result_json IS NOT NULL
          )
          OR (
            OLD.state = 'FINALIZED'
            AND NEW.state = 'FINALIZED'
            AND NEW.claims_digest IS OLD.claims_digest
            AND NEW.claims_json IS OLD.claims_json
            AND NEW.issued_at IS OLD.issued_at
            AND NEW.envelope_digest IS OLD.envelope_digest
            AND NEW.envelope_json IS OLD.envelope_json
            AND NEW.receipt_digest IS OLD.receipt_digest
            AND NEW.result_json IS OLD.result_json
          )
        )
        BEGIN
          SELECT RAISE(ABORT, 'authority operation transition is not monotonic');
        END;
      `);
    });
  }

  #operation(operationId: string): OperationRow | null {
    return this.ctx.storage.sql.exec<OperationRow>(
      "SELECT * FROM authority_operations WHERE operation_id=?",
      operationId,
    ).toArray()[0] ?? null;
  }

  #requireOperation(
    operationId: string,
    requestDigest: string,
  ): OperationRow {
    if (!isSha256(operationId) || operationId !== requestDigest) {
      throw new TypeError("operation identity must equal the request digest");
    }
    const row = this.#operation(operationId);
    if (row === null || row.request_digest !== requestDigest) {
      throw new Error("receipt authority operation is absent or substituted");
    }
    return row;
  }

  #latestCaptureAttempt(operationId: string): CaptureAttemptRow | null {
    return this.ctx.storage.sql.exec<CaptureAttemptRow>(
      `SELECT * FROM authority_capture_attempts
        WHERE operation_id=? ORDER BY attempt_ordinal DESC LIMIT 1`,
      operationId,
    ).toArray()[0] ?? null;
  }

  #captureAttempt(
    operationId: string,
    attemptId: string,
  ): CaptureAttemptRow | null {
    return this.ctx.storage.sql.exec<CaptureAttemptRow>(
      `SELECT * FROM authority_capture_attempts
        WHERE operation_id=? AND attempt_id=?`,
      operationId,
      attemptId,
    ).toArray()[0] ?? null;
  }

  #requireLatestCaptureAttempt(row: OperationRow): CaptureAttemptRow {
    const existing = this.#latestCaptureAttempt(row.operation_id);
    if (existing !== null) return existing;
    throw new Error("receipt authority capture attempt is absent");
  }

  #operationSnapshot(row: OperationRow): ReceiptAuthorityOperationSnapshot {
    return rowToSnapshot(row, this.#requireLatestCaptureAttempt(row));
  }

  #event(input: AuthorityEventInput): AuthorityEventRow | null {
    return this.ctx.storage.sql.exec<AuthorityEventRow>(
      `SELECT sequence,operation_id,event_type,payload_digest,
              prior_event_digest,event_digest,observed_at
         FROM authority_events
        WHERE operation_id=? AND event_type=? AND payload_digest=?`,
      input.operationId,
      input.eventType,
      input.payloadDigest,
    ).toArray()[0] ?? null;
  }

  async #requireExistingEvents(
    inputs: readonly AuthorityEventInput[],
  ): Promise<boolean> {
    const rows = inputs.map((input) => this.#event(input));
    const present = rows.filter((row) => row !== null).length;
    if (present === 0) return false;
    if (present !== inputs.length) {
      throw new Error("receipt authority event transition is partial");
    }
    for (let index = 0; index < inputs.length; index += 1) {
      const input = inputs[index];
      const row = rows[index]!;
      if (
        row.operation_id !== input.operationId ||
        row.event_type !== input.eventType ||
        row.payload_digest !== input.payloadDigest ||
        row.observed_at !== input.observedAt ||
        row.event_digest !== await canonicalDigest({
          schema_version: "receipt-authority-event/v1",
          sequence: row.sequence,
          operation_id: row.operation_id,
          event_type: row.event_type,
          payload_digest: row.payload_digest,
          prior_event_digest: row.prior_event_digest,
          observed_at: row.observed_at,
        })
      ) throw new Error("receipt authority event replay is corrupt");
    }
    return true;
  }

  async #requireEvent(
    input: AuthorityEventInput,
  ): Promise<AuthorityEventRow> {
    if (!await this.#requireExistingEvents([input])) {
      throw new Error("receipt authority required event is absent");
    }
    return this.#event(input)!;
  }

  async #transactEvents(
    inputs: readonly AuthorityEventInput[],
    mutation: () => void,
  ): Promise<void> {
    if (inputs.length === 0) {
      throw new TypeError("receipt authority event transaction is empty");
    }
    for (const input of inputs) {
      if (!isSha256(input.operationId) || !isSha256(input.payloadDigest)) {
        throw new TypeError("receipt authority event identity is invalid");
      }
    }
    for (let attempt = 0; attempt < 8; attempt += 1) {
      if (await this.#requireExistingEvents(inputs)) return;
      const head = this.ctx.storage.sql.exec<{
        sequence: number;
        event_digest: string;
      }>(
        "SELECT sequence,event_digest FROM authority_events ORDER BY sequence DESC LIMIT 1",
      ).toArray()[0];
      let sequence = (head?.sequence ?? 0) + 1;
      let prior = head?.event_digest ?? null;
      const rows: AuthorityEventRow[] = [];
      for (const input of inputs) {
        const row = {
          sequence,
          operation_id: input.operationId,
          event_type: input.eventType,
          payload_digest: input.payloadDigest,
          prior_event_digest: prior,
          event_digest: "",
          observed_at: input.observedAt,
        };
        row.event_digest = await canonicalDigest({
          schema_version: "receipt-authority-event/v1",
          sequence: row.sequence,
          operation_id: row.operation_id,
          event_type: row.event_type,
          payload_digest: row.payload_digest,
          prior_event_digest: row.prior_event_digest,
          observed_at: row.observed_at,
        });
        rows.push(row);
        sequence += 1;
        prior = row.event_digest;
      }
      const committed = this.ctx.storage.transactionSync(() => {
        const current = this.ctx.storage.sql.exec<{
          sequence: number;
          event_digest: string;
        }>(
          "SELECT sequence,event_digest FROM authority_events ORDER BY sequence DESC LIMIT 1",
        ).toArray()[0];
        if (
          (current?.sequence ?? 0) !== (head?.sequence ?? 0) ||
          (current?.event_digest ?? null) !== (head?.event_digest ?? null)
        ) return false;
        if (inputs.some((input) => this.#event(input) !== null)) return false;
        mutation();
        for (const row of rows) {
          this.ctx.storage.sql.exec(
            `INSERT INTO authority_events
             (sequence,operation_id,event_type,payload_digest,prior_event_digest,
              event_digest,observed_at) VALUES (?,?,?,?,?,?,?)`,
            row.sequence,
            row.operation_id,
            row.event_type,
            row.payload_digest,
            row.prior_event_digest,
            row.event_digest,
            row.observed_at,
          );
        }
        return true;
      });
      if (committed) return;
    }
    throw new Error("receipt authority event transaction contention");
  }

  async #requireValidEventChain(): Promise<void> {
    const rows = this.ctx.storage.sql.exec<AuthorityEventRow>(
      `SELECT sequence,operation_id,event_type,payload_digest,
              prior_event_digest,event_digest,observed_at
         FROM authority_events ORDER BY sequence`,
    ).toArray();
    let prior: string | null = null;
    for (let index = 0; index < rows.length; index += 1) {
      const row = rows[index];
      if (
        row.sequence !== index + 1 ||
        row.prior_event_digest !== prior ||
        !isSha256(row.operation_id) ||
        !isSha256(row.payload_digest) ||
        row.event_digest !== await canonicalDigest({
          schema_version: "receipt-authority-event/v1",
          sequence: row.sequence,
          operation_id: row.operation_id,
          event_type: row.event_type,
          payload_digest: row.payload_digest,
          prior_event_digest: row.prior_event_digest,
          observed_at: row.observed_at,
        })
      ) throw new Error("receipt authority event chain is corrupt");
      prior = row.event_digest;
    }
  }

  #captureAttempts(operationId: string): CaptureAttemptRow[] {
    return this.ctx.storage.sql.exec<CaptureAttemptRow>(
      `SELECT * FROM authority_capture_attempts
        WHERE operation_id=? ORDER BY attempt_ordinal`,
      operationId,
    ).toArray();
  }

  async #requireAuditedOperation(row: OperationRow): Promise<void> {
    const required: AuthorityEventInput[] = [{
      operationId: row.operation_id,
      eventType: "COLLECTION_STARTED",
      payloadDigest: row.request_digest,
      observedAt: row.created_at,
    }];
    const attempts = this.#captureAttempts(row.operation_id);
    if (attempts.length === 0) {
      throw new Error("receipt authority audited capture history is absent");
    }
    for (const attempt of attempts) {
      const attemptDigest = await canonicalDigest({
        attempt_id: attempt.attempt_id,
        attempt_ordinal: attempt.attempt_ordinal,
      });
      if (attempt.attempt_ordinal > 1) {
        required.push({
          operationId: row.operation_id,
          eventType: "CAPTURE_ATTEMPT_STARTED",
          payloadDigest: attemptDigest,
          observedAt: attempt.created_at,
        });
      }
      if (attempt.state === "ABANDONED") {
        required.push({
          operationId: row.operation_id,
          eventType: "CAPTURE_ATTEMPT_ABANDONED",
          payloadDigest: attemptDigest,
          observedAt: attempt.updated_at,
        });
      } else if (attempt.state === "CAPTURED") {
        if (attempt.capture_digest === null) {
          throw new Error("receipt authority audited capture digest is absent");
        }
        required.push({
          operationId: row.operation_id,
          eventType: "CAPTURE_COMMITTED",
          payloadDigest: attempt.capture_digest,
          observedAt: attempt.updated_at,
        });
      }
    }
    if (row.claims_digest !== null && attempts.at(-1)?.state !== "CAPTURED") {
      throw new Error("receipt authority claims lack a captured terminal attempt");
    }
    if (row.claims_digest !== null) {
      if (row.issued_at === null) {
        throw new Error("receipt authority audited issue time is absent");
      }
      required.push({
        operationId: row.operation_id,
        eventType: "CLAIMS_RESERVED",
        payloadDigest: row.claims_digest,
        observedAt: row.issued_at,
      });
    }
    if (row.envelope_digest !== null) {
      if (row.issued_at === null) {
        throw new Error("receipt authority audited envelope time is absent");
      }
      required.push({
        operationId: row.operation_id,
        eventType: "RECEIPT_ISSUED_PENDING_FINALIZE",
        payloadDigest: row.envelope_digest,
        observedAt: row.issued_at,
      });
    }
    if (row.receipt_digest !== null) {
      required.push({
        operationId: row.operation_id,
        eventType: "RECEIPT_FINALIZED",
        payloadDigest: row.receipt_digest,
        observedAt: row.updated_at,
      });
    }
    let priorSequence = 0;
    for (const event of required) {
      const row = await this.#requireEvent(event);
      if (row.sequence <= priorSequence) {
        throw new Error("receipt authority lifecycle event order is corrupt");
      }
      priorSequence = row.sequence;
    }
    await this.#requireValidEventChain();
  }

  async #beginOperation(
    operationId: string,
    requestDigest: string,
  ): Promise<ReceiptAuthorityOperationSnapshot> {
    if (!isSha256(operationId) || operationId !== requestDigest) {
      throw new TypeError("operation identity must equal the request digest");
    }
    const now = new Date().toISOString();
    const existing = this.#operation(operationId);
    if (existing !== null) {
      if (existing.request_digest !== requestDigest) {
        throw new Error("receipt authority operation replay was substituted");
      }
      await this.#requireEvent({
        operationId,
        eventType: "COLLECTION_STARTED",
        payloadDigest: requestDigest,
        observedAt: existing.created_at,
      });
      this.#requireLatestCaptureAttempt(existing);
      await this.#requireAuditedOperation(existing);
      return this.#operationSnapshot(existing);
    }
    const nonce = randomHex(32);
    const attemptId = randomHex(32);
    await this.#transactEvents([{
      operationId,
      eventType: "COLLECTION_STARTED",
      payloadDigest: requestDigest,
      observedAt: now,
    }], () => {
      const replay = this.#operation(operationId);
      if (replay !== null) {
        throw new Error("receipt authority operation appeared during begin");
      }
      this.ctx.storage.sql.exec(
        `INSERT INTO authority_operations
         (operation_id,request_digest,acquisition_nonce,state,created_at,updated_at)
         VALUES (?,?,?,'COLLECTING',?,?)`,
        operationId,
        requestDigest,
        nonce,
        now,
        now,
      );
      this.ctx.storage.sql.exec(
        `INSERT INTO authority_capture_attempts
         (operation_id,attempt_ordinal,attempt_id,acquisition_nonce,state,
          created_at,updated_at) VALUES (?,1,?,?,'OPEN',?,?)`,
        operationId,
        attemptId,
        nonce,
        now,
        now,
      );
    });
    const row = this.#requireOperation(operationId, requestDigest);
    await this.#requireAuditedOperation(row);
    return this.#operationSnapshot(row);
  }

  async #recoverOperation(
    operationId: string,
    requestDigest: string,
  ): Promise<ReceiptAuthorityOperationSnapshot> {
    const row = this.#requireOperation(operationId, requestDigest);
    let attempt = this.#requireLatestCaptureAttempt(row);
    if (row.state === "COLLECTING" && attempt.state === "OPEN") {
      const now = new Date().toISOString();
      const nextOrdinal = attempt.attempt_ordinal + 1;
      const nextAttemptId = randomHex(32);
      const nextNonce = randomHex(32);
      const abandonedDigest = await canonicalDigest({
        attempt_id: attempt.attempt_id,
        attempt_ordinal: attempt.attempt_ordinal,
      });
      const startedDigest = await canonicalDigest({
        attempt_id: nextAttemptId,
        attempt_ordinal: nextOrdinal,
      });
      await this.#transactEvents([{
        operationId,
        eventType: "CAPTURE_ATTEMPT_ABANDONED",
        payloadDigest: abandonedDigest,
        observedAt: now,
      }, {
        operationId,
        eventType: "CAPTURE_ATTEMPT_STARTED",
        payloadDigest: startedDigest,
        observedAt: now,
      }], () => {
        const current = this.#latestCaptureAttempt(operationId);
        if (
          current === null || current.attempt_id !== attempt.attempt_id ||
          current.state !== "OPEN"
        ) throw new Error("receipt authority capture attempt recovery drifted");
        this.ctx.storage.sql.exec(
          `UPDATE authority_capture_attempts
              SET state='ABANDONED',updated_at=?
            WHERE operation_id=? AND attempt_id=? AND state='OPEN'`,
          now,
          operationId,
          attempt.attempt_id,
        );
        this.ctx.storage.sql.exec(
          `INSERT INTO authority_capture_attempts
           (operation_id,attempt_ordinal,attempt_id,acquisition_nonce,state,
            created_at,updated_at) VALUES (?,?,?,?,'OPEN',?,?)`,
          operationId,
          nextOrdinal,
          nextAttemptId,
          nextNonce,
          now,
          now,
        );
      });
      attempt = this.#latestCaptureAttempt(operationId)!;
      if (
        attempt.attempt_id !== nextAttemptId ||
        attempt.attempt_ordinal !== nextOrdinal ||
        attempt.created_at !== now
      ) throw new Error("receipt authority capture recovery did not commit");
    }
    await this.#requireAuditedOperation(row);
    return rowToSnapshot(row, attempt);
  }

  async #appendCapture(
    operationId: string,
    requestDigest: string,
    attemptId: string,
    captureKey: string,
    captureDigest: string,
  ): Promise<ReceiptAuthorityOperationSnapshot> {
    const row = this.#requireOperation(operationId, requestDigest);
    if (row.state !== "COLLECTING") {
      throw new Error("receipt authority cannot append capture after issuance");
    }
    const expectedPrefix =
      `raw/receipt-authority/${this.env.ENVIRONMENT}/`;
    if (
      !isSha256(captureDigest) || !captureKey.startsWith(expectedPrefix) ||
      !captureKey.includes(`/${operationId.slice(7)}/attempt-${attemptId}/`) ||
      !captureKey.endsWith("/capture-state.json")
    ) throw new Error("receipt authority capture reference is invalid");
    const storedAttempt = this.#captureAttempt(operationId, attemptId);
    if (storedAttempt === null) {
      throw new Error("receipt authority capture attempt is absent");
    }
    if (storedAttempt.state === "CAPTURED") {
      if (
        storedAttempt.capture_digest !== captureDigest ||
        storedAttempt.capture_key !== captureKey
      ) throw new Error("receipt authority capture replay was substituted");
      await this.#requireEvent({
        operationId,
        eventType: "CAPTURE_COMMITTED",
        payloadDigest: captureDigest,
        observedAt: storedAttempt.updated_at,
      });
      await this.#requireAuditedOperation(row);
      return this.#operationSnapshot(row);
    }
    if (storedAttempt.state !== "OPEN") {
      throw new Error("receipt authority capture attempt was abandoned");
    }
    const observedAt = new Date().toISOString();
    await this.#transactEvents([{
      operationId,
      eventType: "CAPTURE_COMMITTED",
      payloadDigest: captureDigest,
      observedAt,
    }], () => {
      const attempt = this.#captureAttempt(operationId, attemptId);
      const latest = this.#latestCaptureAttempt(operationId);
      if (attempt === null || latest?.attempt_id !== attemptId) {
        throw new Error("receipt authority capture attempt was superseded");
      }
      if (attempt.state !== "OPEN") {
        throw new Error("receipt authority capture attempt was abandoned");
      }
      this.ctx.storage.sql.exec(
        `UPDATE authority_capture_attempts
            SET state='CAPTURED',capture_key=?,capture_digest=?,updated_at=?
          WHERE operation_id=? AND attempt_id=? AND state='OPEN'`,
        captureKey,
        captureDigest,
        observedAt,
        operationId,
        attemptId,
      );
    });
    const committed = this.#captureAttempt(operationId, attemptId);
    if (
      committed?.state !== "CAPTURED" ||
      committed.capture_key !== captureKey ||
      committed.capture_digest !== captureDigest
    ) throw new Error("receipt authority capture transaction did not commit");
    await this.#requireAuditedOperation(row);
    return this.#operationSnapshot(
      this.#requireOperation(operationId, requestDigest),
    );
  }

  async #loadOrCreateKey(): Promise<KeyMaterial> {
    const generation = this.#keyGeneration();
    const metadata = this.ctx.storage.sql.exec<{
      key_generation: number;
      key_id: string;
      public_key_base64: string;
      wrap_algorithm: string;
      wrap_iv_base64: string;
      wrapped_private_key_base64: string;
      generated_at: string;
    }>(
      `SELECT key_generation,key_id,public_key_base64,wrap_algorithm,wrap_iv_base64,
              wrapped_private_key_base64,generated_at
         FROM authority_key_metadata WHERE key_generation=?`,
      generation,
    ).toArray()[0];
    if (metadata !== undefined) {
      if (metadata.wrap_algorithm !== "AES-GCM") {
        throw new Error("receipt authority wrapped key storage is corrupt");
      }
      const publicKey = base64ToBytes(metadata.public_key_base64);
      const publicDigest = await sha256Digest(publicKey);
      const expectedKeyId =
        `receipt-${this.env.ENVIRONMENT}-${publicDigest.slice(7, 23)}`;
      if (publicKey.length !== 32 || metadata.key_id !== expectedKeyId) {
        throw new Error("receipt authority public-key identity is corrupt");
      }
      const privateKey = await unwrapEd25519PrivateKey({
        wrapped: {
          wrap_algorithm: "AES-GCM",
          wrap_iv_base64: metadata.wrap_iv_base64,
          wrapped_private_key_base64: metadata.wrapped_private_key_base64,
        },
        wrappingSecret: this.env.RECEIPT_KEY_WRAP_KEY,
        aad: this.#keyWrapAad(
          metadata.key_generation,
          metadata.key_id,
          metadata.public_key_base64,
        ),
      });
      this.#requireOperationalPrivateKey(privateKey);
      return {
        keyId: metadata.key_id,
        generation: metadata.key_generation,
        privateKey,
        publicKeyBase64: metadata.public_key_base64,
        generatedAt: metadata.generated_at,
      };
    }

    const current = this.ctx.storage.sql.exec<{ maximum: number | null }>(
      "SELECT MAX(key_generation) AS maximum FROM authority_key_metadata",
    ).one().maximum;
    if (generation !== (current ?? 0) + 1) {
      throw new Error("receipt key generation is absent or skips history");
    }
    if (
      current !== null && this.env.AUTHORITY_MODE !== "PENDING"
    ) throw new Error("receipt key rotation requires PENDING mode");

    const pair = await crypto.subtle.generateKey(
      { name: "Ed25519" },
      true,
      ["sign", "verify"],
    );
    if (!("privateKey" in pair)) {
      throw new Error("runtime did not create an Ed25519 key pair");
    }
    const publicRaw = await crypto.subtle.exportKey(
      "raw",
      pair.publicKey,
    ) as ArrayBuffer;
    const publicDigest = await sha256Digest(new Uint8Array(publicRaw));
    const keyId = `receipt-${this.env.ENVIRONMENT}-${publicDigest.slice(7, 23)}`;
    const generatedAt = new Date().toISOString();
    const publicKeyBase64 = arrayBufferToBase64(publicRaw);
    const wrapped = await wrapEd25519PrivateKey({
      privateKey: pair.privateKey,
      wrappingSecret: this.env.RECEIPT_KEY_WRAP_KEY,
      aad: this.#keyWrapAad(generation, keyId, publicKeyBase64),
    });
    const privateKey = await unwrapEd25519PrivateKey({
      wrapped,
      wrappingSecret: this.env.RECEIPT_KEY_WRAP_KEY,
      aad: this.#keyWrapAad(generation, keyId, publicKeyBase64),
    });
    this.#requireOperationalPrivateKey(privateKey);
    this.ctx.storage.transactionSync(() => {
      this.ctx.storage.sql.exec(
        `INSERT INTO authority_key_metadata
         (key_generation,key_id,algorithm,public_key_base64,wrap_algorithm,
          wrap_iv_base64,wrapped_private_key_base64,generated_at)
         VALUES (?,?,'Ed25519',?,'AES-GCM',?,?,?)`,
        generation,
        keyId,
        publicKeyBase64,
        wrapped.wrap_iv_base64,
        wrapped.wrapped_private_key_base64,
        generatedAt,
      );
    });
    return {
      keyId,
      generation,
      privateKey,
      publicKeyBase64,
      generatedAt,
    };
  }

  #keyGeneration(): number {
    if (!/^[1-9][0-9]{0,8}$/.test(this.env.RECEIPT_KEY_GENERATION)) {
      throw new Error("receipt key generation is absent or invalid");
    }
    return Number(this.env.RECEIPT_KEY_GENERATION);
  }

  #keyWrapAad(
    generation: number,
    keyId: string,
    publicKeyBase64: string,
  ): string {
    return canonicalJson({
      schema_version: "receipt-key-wrap-aad/v1",
      authority_id: "receipt-evidence-authority",
      environment: this.env.ENVIRONMENT,
      key_generation: generation,
      key_id: keyId,
      algorithm: "Ed25519",
      public_key_base64: publicKeyBase64,
    });
  }

  #requireOperationalPrivateKey(key: CryptoKey): void {
    if (
      key.type !== "private" || key.extractable !== false ||
      key.algorithm.name !== "Ed25519" ||
      key.usages.length !== 1 || key.usages[0] !== "sign"
    ) throw new Error("receipt authority private key invariant failed");
  }

  #ensureKey(): Promise<KeyMaterial> {
    this.#keyPromise ??= this.#loadOrCreateKey();
    return this.#keyPromise;
  }

  async #requireSigningKey(): Promise<KeyMaterial> {
    const key = await this.#ensureKey();
    if (
      this.env.AUTHORITY_MODE !== "ACTIVE" ||
      !this.env.ACTIVATED_KEY_ID ||
      this.env.ACTIVATED_KEY_ID !== key.keyId
    ) {
      throw new Error("receipt evidence authority is PENDING registry activation");
    }
    return key;
  }

  async public_key_registration(): Promise<ReceiptPublicKeyRegistrationV1> {
    if (
      this.env.AUTHORITY_MODE !== "PENDING" ||
      this.env.ACTIVATED_KEY_ID !== undefined
    ) {
      throw new Error(
        "receipt public-key registration requires unactivated PENDING mode",
      );
    }
    const key = await this.#ensureKey();
    const scope = await authorityInstanceScope(this.env);
    const deployment = pendingDeploymentProvenance(this.env);
    const operationBindingDigest = await canonicalDigest({
      schema_version: "receipt-registration-operation/v1",
      authority: "receipt-evidence-authority",
      action: "public_key_registration",
      environment: this.env.ENVIRONMENT,
      authority_resource_digest: scope.authorityInstanceDigest,
      deployment_source_sha: deployment.sourceSha,
      authority_worker_version_id: deployment.versionId,
      authority_worker_version_tag: deployment.versionTag,
      key_id: key.keyId,
      key_generation: key.generation,
      generated_at: key.generatedAt,
    });
    const body = {
      schema_version: "receipt-public-key-registration/v1" as const,
      purpose: "receipt_verification" as const,
      environment: this.env.ENVIRONMENT,
      authority_instance_digest: scope.authorityInstanceDigest,
      authority_resource_digest: scope.authorityInstanceDigest,
      authority_status: "PENDING" as const,
      action: "public_key_registration" as const,
      deployment_source_sha: deployment.sourceSha,
      authority_worker_version_id: deployment.versionId,
      authority_worker_version_tag: deployment.versionTag,
      operation_binding_digest: operationBindingDigest,
      key_id: key.keyId,
      key_generation: key.generation,
      algorithm: "Ed25519" as const,
      public_key_base64: key.publicKeyBase64,
      private_key_extractable: false as const,
      status: "pending" as const,
      generated_at: key.generatedAt,
    };
    return {
      ...body,
      registration_digest: await canonicalDigest(body),
    };
  }

  async #appendIssued(
    operationId: string,
    requestDigest: string,
    rawClaims: UnsignedReceiptClaimsV3,
  ): Promise<ReceiptAuthorityIssuedRecord> {
    const claims = requireDerivedClaims(rawClaims);
    const authorityScope = await authorityInstanceScope(this.env);
    if (
      claims.environment !== authorityScope.environment ||
      claims.authority_instance_digest !== authorityScope.authorityInstanceDigest
    ) {
      throw new Error("receipt claims are not bound to this authority instance");
    }
    const row = this.#requireOperation(operationId, requestDigest);
    const claimsJson = canonicalJson(claims);
    const claimsDigest = await sha256Digest(claimsJson);
    if (row.claims_digest !== null && row.claims_digest !== claimsDigest) {
      throw new Error("receipt authority claims replay was substituted");
    }
    if (row.envelope_json !== null) {
      const envelope = parseStored<SignedReceiptEnvelopeV3>(
        row.envelope_json,
        "envelope",
      );
      const storedClaims = parseStored<UnsignedReceiptClaimsV3>(
        row.claims_json,
        "claims",
      );
      if (envelope === null || storedClaims === null || row.envelope_digest === null) {
        throw new Error("receipt authority issued state is incomplete");
      }
      await this.#requireAuditedOperation(row);
      return { claims: storedClaims, envelope, envelope_digest: row.envelope_digest };
    }

    const key = await this.#requireSigningKey();
    let reserved: OperationRow;
    if (row.claims_digest === null) {
      const issuedAt = new Date().toISOString();
      await this.#transactEvents([{
        operationId,
        eventType: "CLAIMS_RESERVED",
        payloadDigest: claimsDigest,
        observedAt: issuedAt,
      }], () => {
        const current = this.#requireOperation(operationId, requestDigest);
        if (current.claims_digest !== null) {
          throw new Error("receipt authority claims reservation raced");
        }
        this.ctx.storage.sql.exec(
          `UPDATE authority_operations
           SET claims_digest=?,claims_json=?,issued_at=?,updated_at=?
           WHERE operation_id=? AND state='COLLECTING'`,
          claimsDigest,
          claimsJson,
          issuedAt,
          issuedAt,
          operationId,
        );
      });
      reserved = this.#requireOperation(operationId, requestDigest);
    } else {
      if (row.claims_json !== claimsJson || row.issued_at === null) {
        throw new Error("receipt authority claims reservation replay drifted");
      }
      await this.#requireEvent({
        operationId,
        eventType: "CLAIMS_RESERVED",
        payloadDigest: claimsDigest,
        observedAt: row.issued_at,
      });
      reserved = row;
    }
    if (
      reserved.claims_digest !== claimsDigest || reserved.claims_json !== claimsJson ||
      reserved.issued_at === null
    ) {
      throw new Error("receipt authority issue reservation failed");
    }
    await this.#requireAuditedOperation(reserved);

    const signedClaims: SignedReceiptClaimsV3 = {
      ...claims,
      version: "signed-receipt-claims/v3",
      parser_normalizer_version: PARSER_NORMALIZER_VERSION,
      issuer_id: key.keyId,
      issued_at: reserved.issued_at,
    };
    const body = canonicalJson(signedClaims);
    const signature = new Uint8Array(await crypto.subtle.sign(
      "Ed25519",
      key.privateKey,
      new TextEncoder().encode(body),
    ));
    const envelope: SignedReceiptEnvelopeV3 = {
      eligibility: "TRUSTED_COLLECTION",
      issuer_class: "SignedReceiptAuthority",
      issuer_key_id: key.keyId,
      issuer_id: key.keyId,
      environment: claims.environment,
      authority_instance_digest: claims.authority_instance_digest,
      parser_normalizer_version: PARSER_NORMALIZER_VERSION,
      signed_body_b64: utf8Base64(body),
      signature: `ed25519:${arrayBufferToBase64(signature.buffer)}`,
      body_digest: await sha256Digest(body),
      issued_at: reserved.issued_at,
      checked_at: claims.checked_at,
      source_request_digest: claims.source_request_digest,
      raw_manifest_digest: claims.raw_manifest_digest,
      raw: claims.raw_digest,
      structured_generation: claims.structured_generation,
      structured_digest: claims.structured_digest,
      scope_digest: claims.scope_digest,
      observation_digest: claims.observation_digest,
      extra_digests: claims.extra_digests,
      ...claims.extra_digests,
    };
    const envelopeJson = canonicalJson(envelope);
    const envelopeDigest = await sha256Digest(envelopeJson);
    await this.#transactEvents([{
      operationId,
      eventType: "RECEIPT_ISSUED_PENDING_FINALIZE",
      payloadDigest: envelopeDigest,
      observedAt: reserved.issued_at,
    }], () => {
      const current = this.#requireOperation(operationId, requestDigest);
      if (current.envelope_digest !== null) {
        throw new Error("receipt authority signature reservation raced");
      }
      if (
        current.state !== "COLLECTING" ||
        current.claims_digest !== claimsDigest ||
        current.issued_at !== reserved.issued_at
      ) {
        throw new Error("receipt authority issue state drifted");
      }
      this.ctx.storage.sql.exec(
        `UPDATE authority_operations
         SET state='ISSUED_PENDING_FINALIZE',envelope_digest=?,envelope_json=?,
             updated_at=? WHERE operation_id=? AND state='COLLECTING'`,
        envelopeDigest,
        envelopeJson,
        reserved.issued_at,
        operationId,
      );
    });
    const issued = this.#requireOperation(operationId, requestDigest);
    if (
      issued.envelope_digest !== envelopeDigest ||
      issued.envelope_json !== envelopeJson
    ) throw new Error("receipt authority signature replay was substituted");
    await this.#requireAuditedOperation(issued);
    return { claims, envelope, envelope_digest: envelopeDigest };
  }

  async #finalizeCommitted(
    operationId: string,
    requestDigest: string,
    receiptDigest: string,
    result: ReceiptIssueResultV1,
  ): Promise<ReceiptIssueResultV1> {
    if (!isSha256(receiptDigest)) throw new TypeError("receipt digest required");
    const resultJson = canonicalJson(result);
    const before = this.#requireOperation(operationId, requestDigest);
    if (before.state === "FINALIZED") {
      if (
        before.receipt_digest !== receiptDigest || before.result_json !== resultJson
      ) throw new Error("receipt authority finalized replay was substituted");
      await this.#requireEvent({
        operationId,
        eventType: "RECEIPT_FINALIZED",
        payloadDigest: receiptDigest,
        observedAt: before.updated_at,
      });
      await this.#requireAuditedOperation(before);
      return result;
    }
    const observedAt = new Date().toISOString();
    await this.#transactEvents([{
      operationId,
      eventType: "RECEIPT_FINALIZED",
      payloadDigest: receiptDigest,
      observedAt,
    }], () => {
      const current = this.#requireOperation(operationId, requestDigest);
      if (current.state === "FINALIZED") {
        throw new Error("receipt authority finalization raced");
      }
      if (
        current.state !== "ISSUED_PENDING_FINALIZE" ||
        current.envelope_digest === null || current.envelope_json === null
      ) {
        throw new Error("receipt authority cannot finalize before issuance");
      }
      this.ctx.storage.sql.exec(
        `UPDATE authority_operations
         SET state='FINALIZED',receipt_digest=?,result_json=?,updated_at=?
         WHERE operation_id=? AND state='ISSUED_PENDING_FINALIZE'`,
        receiptDigest,
        resultJson,
        observedAt,
        operationId,
      );
    });
    const finalized = this.#requireOperation(operationId, requestDigest);
    if (
      finalized.state !== "FINALIZED" ||
      finalized.receipt_digest !== receiptDigest ||
      finalized.result_json !== resultJson
    ) throw new Error("receipt authority finalization did not commit");
    await this.#requireAuditedOperation(finalized);
    return result;
  }

  #internalAuthority() {
    return {
      begin: (
        operationId: string,
        requestDigest: string,
      ) => this.#beginOperation(operationId, requestDigest),
      recover: (
        operationId: string,
        requestDigest: string,
      ) => this.#recoverOperation(operationId, requestDigest),
      appendCapture: (
        operationId: string,
        requestDigest: string,
        attemptId: string,
        captureKey: string,
        captureDigest: string,
      ) => this.#appendCapture(
        operationId,
        requestDigest,
        attemptId,
        captureKey,
        captureDigest,
      ),
      appendDerived: (
        operationId: string,
        requestDigest: string,
        claims: UnsignedReceiptClaimsV3,
      ) => this.#appendIssued(operationId, requestDigest, claims),
      finalizeCommitted: (
        operationId: string,
        requestDigest: string,
        receiptDigest: string,
        result: ReceiptIssueResultV1,
      ) => this.#finalizeCommitted(
        operationId,
        requestDigest,
        receiptDigest,
        result,
      ),
    };
  }

  issue_for_segment(
    request: ReceiptIssueRequestV1,
  ): Promise<ReceiptIssueResultV1> {
    return executeReceiptRequest(this.env, request, this.#internalAuthority());
  }

  recover_issue(
    request: ReceiptRecoveryRequestV1,
  ): Promise<ReceiptIssueResultV1> {
    return executeReceiptRequest(this.env, request, this.#internalAuthority());
  }

  begin_audit_recovery_canary(
    request: ReceiptAuditRecoveryCanaryBeginRequestV1,
  ): Promise<ReceiptAuditRecoveryBeginResultV1> {
    activeStagingDeploymentProvenance(this.env);
    return beginAuditRecoveryCanary(this.ctx.storage, request);
  }

  async recover_audit_recovery_canary(
    request: ReceiptAuditRecoveryCanaryRecoverRequestV1,
  ): Promise<ReceiptAuditRecoveryCanaryResultV1> {
    const deployment = activeStagingDeploymentProvenance(this.env);
    const key = await this.#requireSigningKey();
    const scope = await authorityInstanceScope(this.env);
    return recoverAuditRecoveryCanary(this.ctx.storage, request, {
      authorityInstanceDigest: scope.authorityInstanceDigest,
      sourceSha: deployment.sourceSha,
      workerVersionId: deployment.versionId,
      workerVersionTag: deployment.versionTag,
      keyId: key.keyId,
      privateKey: key.privateKey,
      publicKeyBase64: key.publicKeyBase64,
    });
  }
}
