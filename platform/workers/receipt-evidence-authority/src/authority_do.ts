import { DurableObject } from "cloudflare:workers";
import {
  arrayBufferToBase64,
  canonicalDigest,
  canonicalJson,
  exactKeys,
  isPlainObject,
  isSha256,
  randomHex,
  sha256Digest,
  utf8Base64,
} from "./canonical";
import {
  unwrapEd25519PrivateKey,
  wrapEd25519PrivateKey,
  type WrappedPrivateKey,
} from "./key_crypto";
import type {
  ReceiptAuthorityEnv,
  ReceiptIssueResultV1,
  ReceiptPublicKeyRegistrationV1,
  SignedReceiptClaimsV2,
  SignedReceiptEnvelopeV2,
  UnsignedReceiptClaimsV2,
} from "./types";

const PARSER_NORMALIZER_VERSION = "coverage-receipt/v4-ed25519-closure";

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

export type OperationSnapshot = {
  operation_id: string;
  request_digest: string;
  acquisition_nonce: string;
  state: OperationState;
  claims: UnsignedReceiptClaimsV2 | null;
  envelope: SignedReceiptEnvelopeV2 | null;
  envelope_digest: string | null;
  receipt_digest: string | null;
  result: ReceiptIssueResultV1 | null;
};

export type IssuedRecord = {
  claims: UnsignedReceiptClaimsV2;
  envelope: SignedReceiptEnvelopeV2;
  envelope_digest: string;
};

type KeyMaterial = {
  keyId: string;
  generation: number;
  privateKey: CryptoKey;
  publicKeyBase64: string;
  generatedAt: string;
};

const UNSIGNED_CLAIM_KEYS = [
  "coverage_policy_version",
  "source",
  "dataset",
  "segment_id",
  "segment_start",
  "segment_end",
  "expected_scope",
  "expected_items",
  "observed_items",
  "raw_page_count",
  "raw_count",
  "structured_count",
  "status",
  "error",
  "pagination_exhausted",
  "discovery_exhausted",
  "source_request_digest",
  "raw_manifest_digest",
  "raw_digest",
  "structured_digest",
  "structured_generation",
  "scope_digest",
  "observation_digest",
  "run_id",
  "checked_at",
  "extra_digests",
] as const;

const REQUIRED_ACQUISITION_DIGESTS = [
  "acquisition_collection_manifest_file_digest",
  "acquisition_collection_digest",
  "acquisition_terminal_chain_digest",
] as const;

function requireUnsignedClaims(value: unknown): UnsignedReceiptClaimsV2 {
  if (!isPlainObject(value) || !exactKeys(value, UNSIGNED_CLAIM_KEYS)) {
    throw new TypeError("receipt authority claims are not closed");
  }
  const extraDigests = isPlainObject(value.extra_digests)
    ? value.extra_digests
    : null;
  const integerFields = [
    "observed_items",
    "raw_page_count",
    "raw_count",
    "structured_count",
    "structured_generation",
    "run_id",
  ] as const;
  if (
    value.coverage_policy_version !== "collection-coverage/v3" ||
    value.source !== "jquants" ||
    typeof value.dataset !== "string" || value.dataset.length === 0 ||
    typeof value.segment_id !== "string" || !/^\d{4}-\d{2}$/.test(value.segment_id) ||
    typeof value.segment_start !== "string" ||
    typeof value.segment_end !== "string" ||
    !isPlainObject(value.expected_scope) ||
    !(value.expected_items === null ||
      (Number.isSafeInteger(value.expected_items) && Number(value.expected_items) >= 0)) ||
    integerFields.some((field) =>
      !Number.isSafeInteger(value[field]) || Number(value[field]) < 0
    ) ||
    value.status !== "SUCCESS" || value.error !== null ||
    value.pagination_exhausted !== true || value.discovery_exhausted !== true ||
    !isSha256(value.source_request_digest) ||
    !isSha256(value.raw_manifest_digest) || !isSha256(value.raw_digest) ||
    !isSha256(value.structured_digest) || !isSha256(value.scope_digest) ||
    !isSha256(value.observation_digest) ||
    typeof value.checked_at !== "string" || !Number.isFinite(Date.parse(value.checked_at)) ||
    extraDigests === null ||
    !exactKeys(extraDigests, REQUIRED_ACQUISITION_DIGESTS) ||
    REQUIRED_ACQUISITION_DIGESTS.some((field) => !isSha256(extraDigests[field]))
  ) {
    throw new TypeError("receipt authority claims failed invariant validation");
  }
  return value as UnsignedReceiptClaimsV2;
}

function parseStored<T>(value: string | null, field: string): T | null {
  if (value === null) return null;
  try {
    return JSON.parse(value) as T;
  } catch {
    throw new Error(`receipt authority ${field} storage is corrupt`);
  }
}

function rowToSnapshot(row: OperationRow): OperationSnapshot {
  return {
    operation_id: row.operation_id,
    request_digest: row.request_digest,
    acquisition_nonce: row.acquisition_nonce,
    state: row.state,
    claims: parseStored<UnsignedReceiptClaimsV2>(row.claims_json, "claims"),
    envelope: parseStored<SignedReceiptEnvelopeV2>(row.envelope_json, "envelope"),
    envelope_digest: row.envelope_digest,
    receipt_digest: row.receipt_digest,
    result: parseStored<ReceiptIssueResultV1>(row.result_json, "result"),
  };
}

export class ReceiptEvidenceAuthority extends DurableObject<ReceiptAuthorityEnv> {
  private keyPromise: Promise<KeyMaterial> | null = null;

  constructor(ctx: DurableObjectState, env: ReceiptAuthorityEnv) {
    super(ctx, env);
    ctx.blockConcurrencyWhile(async () => {
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

  private operation(operationId: string): OperationRow | null {
    return this.ctx.storage.sql.exec<OperationRow>(
      "SELECT * FROM authority_operations WHERE operation_id=?",
      operationId,
    ).toArray()[0] ?? null;
  }

  private requireOperation(
    operationId: string,
    requestDigest: string,
  ): OperationRow {
    if (!isSha256(operationId) || operationId !== requestDigest) {
      throw new TypeError("operation identity must equal the request digest");
    }
    const row = this.operation(operationId);
    if (row === null || row.request_digest !== requestDigest) {
      throw new Error("receipt authority operation is absent or substituted");
    }
    return row;
  }

  private async ensureEvent(input: {
    operationId: string;
    eventType: string;
    payloadDigest: string;
    observedAt: string;
  }): Promise<void> {
    const existing = this.ctx.storage.sql.exec<{ event_digest: string }>(
      `SELECT event_digest FROM authority_events
       WHERE operation_id=? AND event_type=? AND payload_digest=?`,
      input.operationId,
      input.eventType,
      input.payloadDigest,
    ).toArray()[0];
    if (existing !== undefined) return;

    for (let attempt = 0; attempt < 8; attempt += 1) {
      const head = this.ctx.storage.sql.exec<{
        sequence: number;
        event_digest: string;
      }>(
        "SELECT sequence,event_digest FROM authority_events ORDER BY sequence DESC LIMIT 1",
      ).toArray()[0];
      const sequence = (head?.sequence ?? 0) + 1;
      const prior = head?.event_digest ?? null;
      const eventDigest = await canonicalDigest({
        schema_version: "receipt-authority-event/v1",
        sequence,
        operation_id: input.operationId,
        event_type: input.eventType,
        payload_digest: input.payloadDigest,
        prior_event_digest: prior,
        observed_at: input.observedAt,
      });
      const inserted = this.ctx.storage.transactionSync(() => {
        const current = this.ctx.storage.sql.exec<{
          sequence: number;
          event_digest: string;
        }>(
          "SELECT sequence,event_digest FROM authority_events ORDER BY sequence DESC LIMIT 1",
        ).toArray()[0];
        if ((current?.sequence ?? 0) !== (head?.sequence ?? 0) ||
          (current?.event_digest ?? null) !== prior) return false;
        this.ctx.storage.sql.exec(
          `INSERT OR IGNORE INTO authority_events
           (sequence,operation_id,event_type,payload_digest,prior_event_digest,
            event_digest,observed_at) VALUES (?,?,?,?,?,?,?)`,
          sequence,
          input.operationId,
          input.eventType,
          input.payloadDigest,
          prior,
          eventDigest,
          input.observedAt,
        );
        return true;
      });
      if (inserted) return;
      const replay = this.ctx.storage.sql.exec<{ event_digest: string }>(
        `SELECT event_digest FROM authority_events
         WHERE operation_id=? AND event_type=? AND payload_digest=?`,
        input.operationId,
        input.eventType,
        input.payloadDigest,
      ).toArray()[0];
      if (replay !== undefined) return;
    }
    throw new Error("receipt authority event append contention");
  }

  async begin_operation(
    operationId: string,
    requestDigest: string,
  ): Promise<OperationSnapshot> {
    if (!isSha256(operationId) || operationId !== requestDigest) {
      throw new TypeError("operation identity must equal the request digest");
    }
    const now = new Date().toISOString();
    const existing = this.operation(operationId);
    if (existing !== null) {
      if (existing.request_digest !== requestDigest) {
        throw new Error("receipt authority operation replay was substituted");
      }
      return rowToSnapshot(existing);
    }
    const nonce = randomHex(32);
    this.ctx.storage.transactionSync(() => {
      const replay = this.operation(operationId);
      if (replay !== null) {
        if (replay.request_digest !== requestDigest) {
          throw new Error("receipt authority operation replay was substituted");
        }
        return;
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
    });
    const row = this.requireOperation(operationId, requestDigest);
    await this.ensureEvent({
      operationId,
      eventType: "COLLECTION_STARTED",
      payloadDigest: requestDigest,
      observedAt: row.created_at,
    });
    return rowToSnapshot(row);
  }

  async recover_operation(
    operationId: string,
    requestDigest: string,
  ): Promise<OperationSnapshot> {
    return rowToSnapshot(this.requireOperation(operationId, requestDigest));
  }

  private async loadOrCreateKey(): Promise<KeyMaterial> {
    const generation = this.keyGeneration();
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
      const privateKey = await unwrapEd25519PrivateKey({
        wrapped: {
          wrap_algorithm: "AES-GCM",
          wrap_iv_base64: metadata.wrap_iv_base64,
          wrapped_private_key_base64: metadata.wrapped_private_key_base64,
        },
        wrappingSecret: this.env.RECEIPT_KEY_WRAP_KEY,
        aad: this.keyWrapAad(
          metadata.key_generation,
          metadata.key_id,
          metadata.public_key_base64,
        ),
      });
      this.requireOperationalPrivateKey(privateKey);
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
      aad: this.keyWrapAad(generation, keyId, publicKeyBase64),
    });
    const privateKey = await unwrapEd25519PrivateKey({
      wrapped,
      wrappingSecret: this.env.RECEIPT_KEY_WRAP_KEY,
      aad: this.keyWrapAad(generation, keyId, publicKeyBase64),
    });
    this.requireOperationalPrivateKey(privateKey);
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

  private keyGeneration(): number {
    if (!/^[1-9][0-9]{0,8}$/.test(this.env.RECEIPT_KEY_GENERATION)) {
      throw new Error("receipt key generation is absent or invalid");
    }
    return Number(this.env.RECEIPT_KEY_GENERATION);
  }

  private keyWrapAad(
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

  private requireOperationalPrivateKey(key: CryptoKey): void {
    if (
      key.type !== "private" || key.extractable !== false ||
      key.algorithm.name !== "Ed25519" ||
      key.usages.length !== 1 || key.usages[0] !== "sign"
    ) throw new Error("receipt authority private key invariant failed");
  }

  private ensureKey(): Promise<KeyMaterial> {
    this.keyPromise ??= this.loadOrCreateKey();
    return this.keyPromise;
  }

  private async requireSigningKey(): Promise<KeyMaterial> {
    const key = await this.ensureKey();
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
    const key = await this.ensureKey();
    const body = {
      schema_version: "receipt-public-key-registration/v1" as const,
      purpose: "receipt_verification" as const,
      environment: this.env.ENVIRONMENT,
      authority_status: "PENDING" as const,
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

  async append_issued(
    operationId: string,
    requestDigest: string,
    rawClaims: UnsignedReceiptClaimsV2,
  ): Promise<IssuedRecord> {
    const claims = requireUnsignedClaims(rawClaims);
    const row = this.requireOperation(operationId, requestDigest);
    const claimsJson = canonicalJson(claims);
    const claimsDigest = await sha256Digest(claimsJson);
    if (row.claims_digest !== null && row.claims_digest !== claimsDigest) {
      throw new Error("receipt authority claims replay was substituted");
    }
    if (row.envelope_json !== null) {
      const envelope = parseStored<SignedReceiptEnvelopeV2>(
        row.envelope_json,
        "envelope",
      );
      const storedClaims = parseStored<UnsignedReceiptClaimsV2>(
        row.claims_json,
        "claims",
      );
      if (envelope === null || storedClaims === null || row.envelope_digest === null) {
        throw new Error("receipt authority issued state is incomplete");
      }
      return { claims: storedClaims, envelope, envelope_digest: row.envelope_digest };
    }

    const key = await this.requireSigningKey();
    const issuedAt = row.issued_at ?? new Date().toISOString();
    this.ctx.storage.transactionSync(() => {
      const current = this.requireOperation(operationId, requestDigest);
      if (current.claims_digest !== null && current.claims_digest !== claimsDigest) {
        throw new Error("receipt authority claims replay was substituted");
      }
      if (current.claims_digest === null) {
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
      }
    });
    const reserved = this.requireOperation(operationId, requestDigest);
    if (
      reserved.claims_digest !== claimsDigest || reserved.claims_json !== claimsJson ||
      reserved.issued_at === null
    ) {
      throw new Error("receipt authority issue reservation failed");
    }

    const signedClaims: SignedReceiptClaimsV2 = {
      ...claims,
      version: "signed-receipt-claims/v2",
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
    const envelope: SignedReceiptEnvelopeV2 = {
      eligibility: "TRUSTED_COLLECTION",
      issuer_class: "SignedReceiptAuthority",
      issuer_key_id: key.keyId,
      issuer_id: key.keyId,
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
    this.ctx.storage.transactionSync(() => {
      const current = this.requireOperation(operationId, requestDigest);
      if (current.envelope_digest !== null) {
        if (
          current.envelope_digest !== envelopeDigest ||
          current.envelope_json !== envelopeJson
        ) {
          throw new Error("receipt authority signature replay was substituted");
        }
        return;
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
    await this.ensureEvent({
      operationId,
      eventType: "RECEIPT_ISSUED_PENDING_FINALIZE",
      payloadDigest: envelopeDigest,
      observedAt: reserved.issued_at,
    });
    return { claims, envelope, envelope_digest: envelopeDigest };
  }

  async finalize_committed(
    operationId: string,
    requestDigest: string,
    receiptDigest: string,
    result: ReceiptIssueResultV1,
  ): Promise<ReceiptIssueResultV1> {
    if (!isSha256(receiptDigest)) throw new TypeError("receipt digest required");
    const resultJson = canonicalJson(result);
    const now = new Date().toISOString();
    this.ctx.storage.transactionSync(() => {
      const current = this.requireOperation(operationId, requestDigest);
      if (current.state === "FINALIZED") {
        if (
          current.receipt_digest !== receiptDigest ||
          current.result_json !== resultJson
        ) {
          throw new Error("receipt authority finalized replay was substituted");
        }
        return;
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
        now,
        operationId,
      );
    });
    await this.ensureEvent({
      operationId,
      eventType: "RECEIPT_FINALIZED",
      payloadDigest: receiptDigest,
      observedAt: now,
    });
    return result;
  }
}
