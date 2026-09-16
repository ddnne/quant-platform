/**
 * Staging R2 control for one PENDING public-key registration.
 * Absent/idle/completed is a no-op. Does not mint READY or issue receipts.
 */

export const PENDING_REGISTRATION_KEY =
  "control/receipt_pending_registration.json";

const SCHEMA = "receipt-pending-registration/v1";
const CONTROL_MAX_BYTES = 8 * 1024;
const MAX_ATTEMPTS = 3;
const LEASE_MS = 90_000;

const CONTROL_KEYS = [
  "schema",
  "environment",
  "state",
  "attempts",
  "lease",
  "last",
] as const;

type RegistrationState = "idle" | "requested" | "completed";

type ControlLease = { owner: string; until: string } | null;

export type PublicRegistrationEvidence = {
  status: "pass";
  key_id: string;
  public_key_base64: string;
  registration_digest: string;
  authority_status: "PENDING";
  caller_worker_version_id: string;
  caller_worker_version_tag: string;
};

type RegistrationLast = PublicRegistrationEvidence | {
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

export type PendingRegistrationOutput = {
  registration: {
    key_id: string;
    public_key_base64: string;
    registration_digest: string;
    authority_status: "PENDING";
  };
  caller_worker_version_id: string;
  caller_worker_version_tag: string;
};

const LAST_PASS_KEYS = [
  "status",
  "key_id",
  "public_key_base64",
  "registration_digest",
  "authority_status",
  "caller_worker_version_id",
  "caller_worker_version_tag",
] as const;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseLease(value: unknown): ControlLease | undefined {
  if (value === null) return null;
  if (!isPlainObject(value) || Object.keys(value).length !== 2) return undefined;
  if (typeof value.owner !== "string" || value.owner.length === 0) return undefined;
  if (typeof value.until !== "string") return undefined;
  const until = new Date(value.until);
  if (Number.isNaN(until.getTime()) || until.toISOString() !== value.until) {
    return undefined;
  }
  return { owner: value.owner, until: value.until };
}

function parseLast(value: unknown): RegistrationLast | undefined {
  if (value === null) return null;
  if (!isPlainObject(value)) return undefined;
  const keys = Object.keys(value);
  if (value.status === "fail") {
    if (keys.length !== 2 || typeof value.detail !== "string" || value.detail.length === 0) {
      return undefined;
    }
    return { status: "fail", detail: value.detail };
  }
  if (value.status !== "pass") return undefined;
  if (keys.length !== LAST_PASS_KEYS.length) return undefined;
  const keyId = value.key_id;
  const publicKey = value.public_key_base64;
  const digest = value.registration_digest;
  const authorityStatus = value.authority_status;
  const callerId = value.caller_worker_version_id;
  const callerTag = value.caller_worker_version_tag;
  if (
    typeof keyId !== "string" ||
    typeof publicKey !== "string" ||
    typeof digest !== "string" ||
    typeof callerId !== "string" ||
    typeof callerTag !== "string"
  ) {
    return undefined;
  }
  if (authorityStatus !== "PENDING") return undefined;
  if (!/^sha256:[0-9a-f]{64}$/.test(digest)) return undefined;
  return {
    status: "pass",
    key_id: keyId,
    public_key_base64: publicKey,
    registration_digest: digest,
    authority_status: "PENDING",
    caller_worker_version_id: callerId,
    caller_worker_version_tag: callerTag,
  };
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
  const lease = parseLease(parsed.lease);
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

function serialize(control: RegistrationControl): string {
  return JSON.stringify(control);
}

async function casPut(
  bucket: R2Bucket,
  control: RegistrationControl,
  etag: string,
): Promise<R2Object | null> {
  const body = serialize(control);
  if (new TextEncoder().encode(body).byteLength > CONTROL_MAX_BYTES) return null;
  return bucket.put(PENDING_REGISTRATION_KEY, body, {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    onlyIf: { etagMatches: etag },
  });
}

function publicEvidence(
  output: PendingRegistrationOutput,
): PublicRegistrationEvidence {
  return {
    status: "pass",
    key_id: output.registration.key_id,
    public_key_base64: output.registration.public_key_base64,
    registration_digest: output.registration.registration_digest,
    authority_status: "PENDING",
    caller_worker_version_id: output.caller_worker_version_id,
    caller_worker_version_tag: output.caller_worker_version_tag,
  };
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
  if (control.last?.status === "pass") {
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
  const until = new Date(now.getTime() + LEASE_MS).toISOString();
  control.attempts += 1;
  control.lease = { owner, until };
  const claimed = await casPut(bucket, control, object.etag);
  if (claimed === null || !claimed.etag) {
    return { status: "lost", called: false, reason: "cas" };
  }

  try {
    const output = publicEvidence(await register());
    const reportNow = clock();
    const leaseUntil = control.lease?.until;
    if (!leaseUntil || leaseUntil <= reportNow.toISOString()) {
      return { status: "lost", called: true, reason: "expired" };
    }
    control.state = "completed";
    control.attempts = 0;
    control.lease = null;
    control.last = output;
    const written = await casPut(bucket, control, claimed.etag);
    if (written === null) return { status: "lost", called: true, reason: "cas" };
    return { status: "pass", called: true, reason: "ok" };
  } catch (error) {
    const reportNow = clock();
    const leaseUntil = control.lease?.until;
    if (!leaseUntil || leaseUntil <= reportNow.toISOString()) {
      return { status: "lost", called: true, reason: "expired" };
    }
    control.lease = null;
    control.last = {
      status: "fail",
      detail: error instanceof Error ? "registration_failed" : "registration_failed",
    };
    const written = await casPut(bucket, control, claimed.etag);
    if (written === null) return { status: "lost", called: true, reason: "cas" };
    return { status: "fail", called: true, reason: "registration_failed" };
  }
}
