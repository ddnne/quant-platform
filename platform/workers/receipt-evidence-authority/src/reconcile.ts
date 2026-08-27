import {
  canonicalDigest,
  canonicalJson,
} from "../../ingestion-secrets/src/jquants_acquisition_registry";
import { datasetById } from "../../ingestion-premium/src/catalog";
import { exactKeys, isPlainObject } from "./canonical";
import {
  commitReceipt,
  measuredClaims,
  receiptFromIssued,
} from "./receipt_evidence";
import { captureCollection } from "./raw_capture";
import {
  initializeD1Operation,
  reconcileStructured,
} from "./structured_reconciliation";
import type {
  ReceiptAuthorityEnv,
  ReceiptAuthorityIssuedRecord,
  ReceiptAuthorityOperationSnapshot,
  ReceiptIssueRequestV1,
  ReceiptIssueResultV1,
  ReceiptRecoveryRequestV1,
  ReceiptRequestV1,
  UnsignedReceiptClaimsV2,
} from "./types";

const REQUEST_KEYS = [
  "schema_version",
  "operation",
  "environment",
  "dataset_id",
  "segment_id",
  "request_nonce",
] as const;
const MAX_CONTEXT_AGE_MS = 15 * 60 * 1000;

export type InternalReceiptAuthority = {
  begin(
    operationId: string,
    requestDigest: string,
  ): Promise<ReceiptAuthorityOperationSnapshot>;
  recover(
    operationId: string,
    requestDigest: string,
  ): Promise<ReceiptAuthorityOperationSnapshot>;
  appendDerived(
    operationId: string,
    requestDigest: string,
    claims: UnsignedReceiptClaimsV2,
  ): Promise<ReceiptAuthorityIssuedRecord>;
  finalizeCommitted(
    operationId: string,
    requestDigest: string,
    receiptDigest: string,
    result: ReceiptIssueResultV1,
  ): Promise<ReceiptIssueResultV1>;
};

export type FaultInjection = {
  crashAfterIssueBeforeFinalize?: boolean;
};

function requireRequest(value: unknown): ReceiptRequestV1 {
  if (!isPlainObject(value) || !exactKeys(value, REQUEST_KEYS)) {
    throw new TypeError("receipt request is not closed");
  }
  if (
    value.schema_version !== "receipt-evidence-issue-request/v1" ||
    (value.operation !== "issue_for_segment" && value.operation !== "recover_issue") ||
    (value.environment !== "staging" && value.environment !== "production") ||
    typeof value.dataset_id !== "string" ||
    !/^[a-z][a-z0-9_]{2,127}$/.test(value.dataset_id) ||
    typeof value.segment_id !== "string" ||
    !/^\d{4}-\d{2}$/.test(value.segment_id) ||
    typeof value.request_nonce !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.request_nonce)
  ) {
    throw new TypeError("receipt request fields are invalid");
  }
  return value as ReceiptRequestV1;
}

function issueIdentity(request: ReceiptRequestV1): ReceiptIssueRequestV1 {
  return {
    schema_version: "receipt-evidence-issue-request/v1",
    operation: "issue_for_segment",
    environment: request.environment,
    dataset_id: request.dataset_id,
    segment_id: request.segment_id,
    request_nonce: request.request_nonce,
  };
}

async function finalizeIssued(
  env: ReceiptAuthorityEnv,
  authority: InternalReceiptAuthority,
  operationId: string,
  requestDigest: string,
  issued: ReceiptAuthorityIssuedRecord,
  replayed: boolean,
): Promise<ReceiptIssueResultV1> {
  const receipt = receiptFromIssued(issued);
  const receiptDigest = await commitReceipt(env, operationId, receipt);
  const result: ReceiptIssueResultV1 = {
    schema_version: "receipt-evidence-issue-result/v1",
    operation_id: operationId,
    state: "FINALIZED",
    replayed: false,
    receipt_digest: receiptDigest,
    receipt,
  };
  const finalized = await authority.finalizeCommitted(
    operationId,
    requestDigest,
    receiptDigest,
    result,
  );
  return replayed ? { ...finalized, replayed: true } : finalized;
}

function issuedFromSnapshot(
  snapshot: ReceiptAuthorityOperationSnapshot,
): ReceiptAuthorityIssuedRecord | null {
  if (
    snapshot.claims === null || snapshot.envelope === null ||
    snapshot.envelope_digest === null
  ) return null;
  return {
    claims: snapshot.claims,
    envelope: snapshot.envelope,
    envelope_digest: snapshot.envelope_digest,
  };
}

/**
 * Thin authority transaction façade. Acquisition proof, raw persistence,
 * structured reconciliation, and receipt assembly live in dedicated modules;
 * this function owns only the durable append/finalize/recover ordering.
 */
export async function executeReceiptRequest(
  env: ReceiptAuthorityEnv,
  rawRequest: ReceiptIssueRequestV1 | ReceiptRecoveryRequestV1,
  authority: InternalReceiptAuthority,
  faults: FaultInjection = {},
): Promise<ReceiptIssueResultV1> {
  const request = requireRequest(rawRequest);
  if (request.environment !== env.ENVIRONMENT) {
    throw new Error("receipt authority environment mismatch");
  }
  const identity = issueIdentity(request);
  const requestDigest = await canonicalDigest(identity);
  const operationId = requestDigest;
  let snapshot = await authority.begin(operationId, requestDigest);
  if (snapshot.state === "FINALIZED") {
    if (snapshot.result === null) throw new Error("finalized operation lost its result");
    return { ...snapshot.result, replayed: true };
  }
  const recoveredIssued = issuedFromSnapshot(snapshot);
  if (recoveredIssued !== null) {
    return finalizeIssued(
      env,
      authority,
      operationId,
      requestDigest,
      recoveredIssued,
      true,
    );
  }
  if (request.operation === "recover_issue") {
    throw new Error("receipt recovery has no issued envelope to recover");
  }
  if (env.AUTHORITY_MODE !== "ACTIVE") {
    throw new Error("receipt evidence authority is PENDING activation");
  }
  const capture = await captureCollection(
    env,
    identity,
    operationId,
    snapshot.acquisition_nonce,
  );
  const observedAt = new Date().toISOString();
  if (Date.parse(observedAt) >= Date.parse(capture.acquisitionExpiresAt)) {
    throw new Error("acquisition collection expired before reconciliation");
  }
  const spec = datasetById(request.dataset_id);
  if (spec === undefined || spec.coverage.policy_version !== "collection-coverage/v3") {
    throw new Error("dataset is outside the Receipt V3 authority inventory");
  }
  const operation = await initializeD1Operation(env, {
    operationId,
    requestDigest,
    request: identity,
    initial: capture.initialRequest,
    capture,
    checkedAt: observedAt,
  });
  const checkedAt = operation.checkedAt;
  const structured = await reconcileStructured(env, {
    operationId,
    capture,
    spec,
    checkedAt,
  });
  if (
    Date.now() - Date.parse(checkedAt) > MAX_CONTEXT_AGE_MS ||
    Date.now() >= Date.parse(capture.acquisitionExpiresAt)
  ) {
    throw new Error("receipt reconciliation context expired before issuance");
  }
  const claims = await measuredClaims({
    requestDigest,
    runId: operation.runId,
    spec,
    capture,
    structuredCount: structured.count,
    structuredDigest: structured.digest,
    checkedAt,
  });
  const issued = await authority.appendDerived(
    operationId,
    requestDigest,
    claims,
  );
  if (faults.crashAfterIssueBeforeFinalize) {
    throw new Error("injected crash after issue before finalize");
  }
  snapshot = await authority.recover(operationId, requestDigest);
  const durableIssued = issuedFromSnapshot(snapshot);
  if (
    durableIssued === null || durableIssued.envelope_digest !== issued.envelope_digest ||
    canonicalJson(durableIssued.envelope) !== canonicalJson(issued.envelope)
  ) throw new Error("issued envelope was not durably appended");
  return finalizeIssued(
    env,
    authority,
    operationId,
    requestDigest,
    durableIssued,
    false,
  );
}
