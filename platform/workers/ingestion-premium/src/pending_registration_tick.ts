/**
 * Staging R2 control for one PENDING public-key registration.
 * Absent/idle/completed is a no-op. Does not mint READY or issue receipts.
 * Persists the validated public operator envelope; never wrapped/private key.
 */

import type { ReceiptPublicKeyRegistrationV1 } from "../../receipt-evidence-authority/src/types";
import {
  canonicalDigest,
  exactKeys,
  isPlainObject,
  isSha256,
} from "../../receipt-evidence-authority/src/canonical";
import {
  casPutJson,
  CONTROL_LEASE_MS,
  CONTROL_MAX_BYTES,
  parseControlLease,
  type ControlLease,
} from "./control_cas";

export const PENDING_REGISTRATION_KEY =
  "control/receipt_pending_registration.json";

const SCHEMA = "receipt-pending-registration/v1";
const MAX_ATTEMPTS = 3;

const CONTROL_KEYS = [
  "schema",
  "environment",
  "state",
  "attempts",
  "lease",
  "last",
] as const;

const OPERATOR_KEYS = [
  "schema_version",
  "authority",
  "action",
  "environment",
  "caller_worker_version_id",
  "caller_worker_version_tag",
  "registration",
] as const;

const REGISTRATION_FIELDS = [
  "schema_version",
  "purpose",
  "environment",
  "authority_instance_digest",
  "authority_resource_digest",
  "authority_status",
  "action",
  "deployment_source_sha",
  "authority_worker_version_id",
  "authority_worker_version_tag",
  "operation_binding_digest",
  "key_id",
  "key_generation",
  "algorithm",
  "public_key_base64",
  "private_key_extractable",
  "status",
  "generated_at",
  "registration_digest",
] as const;

type RegistrationState = "idle" | "requested" | "completed";

export type PendingRegistrationOutput = {
  schema_version: "receipt-operator-registration/v1";
  authority: "receipt-evidence-authority";
  action: "public_key_registration";
  environment: "staging" | "production";
  caller_worker_version_id: string;
  caller_worker_version_tag: string;
  registration: ReceiptPublicKeyRegistrationV1;
};

type RegistrationLast = PendingRegistrationOutput | {
  status: "fail";
  detail: string;
} | null;

type RegistrationControl = {
  schema: typeof SCHEMA;
  environment: "staging";
  state: RegistrationState;
  attempts: number;
  lease: ControlLease;
  last: RegistrationLast;
};

export type PendingRegistrationResult = {
  status: "idle" | "stop" | "lost" | "pass" | "fail";
  called: boolean;
  reason: string;
};

export type PendingRegistrationPolicy = {
  environment: "staging" | "production";
  operationMode: "PENDING" | "ACTIVE";
  readyDeclared: string | undefined;
};

function parseFailLast(value: Record<string, unknown>): RegistrationLast | undefined {
  const keys = Object.keys(value);
  if (keys.length !== 2 || typeof value.detail !== "string" || value.detail.length === 0) {
    return undefined;
  }
  return { status: "fail", detail: value.detail };
}

function parseOperatorEnvelope(
  value: Record<string, unknown>,
): PendingRegistrationOutput | undefined {
  if (!exactKeys(value, OPERATOR_KEYS)) return undefined;
  if (
    value.schema_version !== "receipt-operator-registration/v1" ||
    value.authority !== "receipt-evidence-authority" ||
    value.action !== "public_key_registration" ||
    (value.environment !== "staging" && value.environment !== "production") ||
    typeof value.caller_worker_version_id !== "string" ||
    typeof value.caller_worker_version_tag !== "string"
  ) {
    return undefined;
  }
  const registration = value.registration;
  if (!isPlainObject(registration) || !exactKeys(registration, REGISTRATION_FIELDS)) {
    return undefined;
  }
  if (
    registration.schema_version !== "receipt-public-key-registration/v1" ||
    registration.purpose !== "receipt_verification" ||
    registration.authority_status !== "PENDING" ||
    registration.algorithm !== "Ed25519" ||
    registration.private_key_extractable !== false ||
    registration.status !== "pending" ||
    typeof registration.key_id !== "string" ||
    typeof registration.public_key_base64 !== "string" ||
    typeof registration.key_generation !== "number" ||
    !Number.isSafeInteger(registration.key_generation) ||
    !isSha256(registration.registration_digest) ||
    !isSha256(registration.authority_instance_digest) ||
    !isSha256(registration.authority_resource_digest) ||
    !isSha256(registration.operation_binding_digest)
  ) {
    return undefined;
  }
  return value as unknown as PendingRegistrationOutput;
}

function parseLast(value: unknown): RegistrationLast | undefined {
  if (value === null) return null;
  if (!isPlainObject(value)) return undefined;
  if (value.status === "fail") return parseFailLast(value);
  return parseOperatorEnvelope(value);
}

function parseControl(raw: string): RegistrationControl | null {
  if (new TextEncoder().encode(raw).byteLength > CONTROL_MAX_BYTES) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isPlainObject(parsed)) return null;
  const keys = Object.keys(parsed);
  if (keys.length !== CONTROL_KEYS.length) return null;
  for (const key of CONTROL_KEYS) {
    if (!keys.includes(key)) return null;
  }
  if (parsed.schema !== SCHEMA || parsed.environment !== "staging") return null;
  if (
    parsed.state !== "idle" &&
    parsed.state !== "requested" &&
    parsed.state !== "completed"
  ) {
    return null;
  }
  if (
    typeof parsed.attempts !== "number" ||
    !Number.isSafeInteger(parsed.attempts) ||
    parsed.attempts < 0
  ) {
    return null;
  }
  const lease = parseControlLease(parsed.lease);
  const last = parseLast(parsed.last);
  if (lease === undefined || last === undefined) return null;
  return {
    schema: SCHEMA,
    environment: "staging",
    state: parsed.state,
    attempts: parsed.attempts,
    lease,
    last,
  };
}

async function publicEnvelopeDigestMatches(
  output: PendingRegistrationOutput,
): Promise<boolean> {
  const { registration_digest: supplied, ...body } = output.registration;
  return supplied === await canonicalDigest(body);
}

function casPut(
  bucket: R2Bucket,
  control: RegistrationControl,
  etag: string,
): Promise<R2Object | null> {
  return casPutJson(bucket, PENDING_REGISTRATION_KEY, control, etag);
}

export async function runPendingRegistrationTick(
  bucket: R2Bucket,
  register: () => Promise<PendingRegistrationOutput>,
  policy: PendingRegistrationPolicy,
  clock: () => Date = () => new Date(),
): Promise<PendingRegistrationResult> {
  const object = await bucket.get(PENDING_REGISTRATION_KEY);
  if (!object) return { status: "idle", called: false, reason: "absent" };
  if (object.size > CONTROL_MAX_BYTES) {
    return { status: "stop", called: false, reason: "invalid" };
  }
  const control = parseControl(await object.text());
  if (!control || !object.etag) {
    return { status: "stop", called: false, reason: "invalid" };
  }
  if (control.state === "idle" || control.state === "completed") {
    return {
      status: "idle",
      called: false,
      reason: control.state === "completed" ? "completed" : "idle",
    };
  }
  if (
    policy.environment !== "staging" ||
    policy.operationMode !== "PENDING" ||
    policy.readyDeclared === "true"
  ) {
    return { status: "stop", called: false, reason: "policy" };
  }
  if (control.last && !("status" in control.last)) {
    if (!await publicEnvelopeDigestMatches(control.last)) {
      return { status: "stop", called: false, reason: "invalid" };
    }
    control.state = "completed";
    control.lease = null;
    const written = await casPut(bucket, control, object.etag);
    if (written === null) return { status: "lost", called: false, reason: "cas" };
    return { status: "idle", called: false, reason: "idempotent" };
  }
  if (control.attempts >= MAX_ATTEMPTS) {
    return { status: "stop", called: false, reason: "exhausted" };
  }
  const now = clock();
  if (control.lease && control.lease.until > now.toISOString()) {
    return { status: "idle", called: false, reason: "leased" };
  }

  const owner = crypto.randomUUID();
  const until = new Date(now.getTime() + CONTROL_LEASE_MS).toISOString();
  control.attempts += 1;
  control.lease = { owner, until };
  const claimed = await casPut(bucket, control, object.etag);
  if (claimed === null || !claimed.etag) {
    return { status: "lost", called: false, reason: "cas" };
  }

  try {
    const output = await register();
    const envelope = parseOperatorEnvelope(output as unknown as Record<string, unknown>);
    if (!envelope || !await publicEnvelopeDigestMatches(envelope)) {
      throw new Error("registration_failed");
    }
    const reportNow = clock();
    const leaseUntil = control.lease?.until;
    if (!leaseUntil || leaseUntil <= reportNow.toISOString()) {
      return { status: "lost", called: true, reason: "expired" };
    }
    control.state = "completed";
    control.attempts = 0;
    control.lease = null;
    control.last = envelope;
    const written = await casPut(bucket, control, claimed.etag);
    if (written === null) return { status: "lost", called: true, reason: "cas" };
    return { status: "pass", called: true, reason: "ok" };
  } catch {
    const reportNow = clock();
    const leaseUntil = control.lease?.until;
    if (!leaseUntil || leaseUntil <= reportNow.toISOString()) {
      return { status: "lost", called: true, reason: "expired" };
    }
    control.lease = null;
    control.last = { status: "fail", detail: "registration_failed" };
    const written = await casPut(bucket, control, claimed.etag);
    if (written === null) return { status: "lost", called: true, reason: "cas" };
    return { status: "fail", called: true, reason: "registration_failed" };
  }
}
