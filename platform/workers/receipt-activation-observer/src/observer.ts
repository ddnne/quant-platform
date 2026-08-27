/// <reference types="@cloudflare/workers-types" />

import {
  base64ToBytes,
  bytesToBase64,
  canonicalDigest,
  canonicalJson,
  isPlainObject,
  isSha256,
} from "../../receipt-evidence-authority/src/canonical";

const AUDIT_PATH = "/v1/receipt-authority/audit-evidence";
const MAX_RESPONSE_BYTES = 64 * 1024;
const MAX_ATTESTATION_BYTES = 48 * 1024;
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CHALLENGE = /^[0-9a-f]{64}$/;
const SOURCE_SHA = /^[0-9a-f]{40}$/;

export type PremiumAuditEvidence = {
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

export interface PremiumReceiptOperatorRpc {
  staging_recovery_audit_evidence(): Promise<PremiumAuditEvidence>;
}

export type ObserverEnv = Omit<
  Cloudflare.Env,
  "ENVIRONMENT" | "PREMIUM_RECEIPT_OPERATOR"
> & {
  ENVIRONMENT: "disabled" | "staging";
  PREMIUM_RECEIPT_OPERATOR?: PremiumReceiptOperatorRpc;
};

const PREMIUM_EVIDENCE_FIELDS = [
  "schema_version",
  "purpose",
  "eligibility",
  "environment",
  "caller_source_sha",
  "caller_worker_version_id",
  "caller_worker_version_tag",
  "d1_schema_digest",
  "reservation_id",
  "authority_operation_id",
  "request_nonce",
  "signed_attestation_digest",
  "signed_attestation_json_utf8_base64",
  "signed_attestation_json_utf8_length",
  "evidence_digest",
] as const;

function exactKeys(value: Record<string, unknown>, fields: readonly string[]): boolean {
  return Object.keys(value).sort().join("\n") === [...fields].sort().join("\n");
}

function responseHeaders(): HeadersInit {
  return {
    "Cache-Control": "no-store",
    "Content-Type": "application/json; charset=utf-8",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
  };
}

function closedError(status: number, code: string): Response {
  return new Response(canonicalJson({
    schema_version: "receipt-activation-observer-error/v1",
    purpose: "receipt_authority_recovery_canary",
    eligibility: "AUDIT_ONLY",
    error: code,
  }), { status, headers: responseHeaders() });
}

function observerProvenance(env: ObserverEnv): {
  sourceSha: string;
  versionId: string;
  versionTag: string;
} {
  const metadata = env.CF_VERSION_METADATA;
  const match = /^rao-s-o-([0-9a-f]{40})$/.exec(metadata?.tag ?? "");
  if (
    env.ENVIRONMENT !== "staging" || metadata === undefined ||
    !UUID.test(metadata.id) || match === null
  ) throw new Error("observer deployment provenance is invalid");
  return { sourceSha: match[1]!, versionId: metadata.id, versionTag: metadata.tag };
}

async function requirePremiumEvidence(value: unknown): Promise<PremiumAuditEvidence> {
  if (!isPlainObject(value) || !exactKeys(value, PREMIUM_EVIDENCE_FIELDS)) {
    throw new Error("Premium audit evidence is malformed");
  }
  const evidence = value;
  if (
    evidence.schema_version !== "receipt-operator-audit-evidence/v1" ||
    evidence.purpose !== "receipt_authority_recovery_canary" ||
    evidence.eligibility !== "AUDIT_ONLY" || evidence.environment !== "staging" ||
    typeof evidence.caller_source_sha !== "string" ||
    !SOURCE_SHA.test(evidence.caller_source_sha) ||
    typeof evidence.caller_worker_version_id !== "string" ||
    !UUID.test(evidence.caller_worker_version_id) ||
    evidence.caller_worker_version_tag !==
      `ra-s-c-${evidence.caller_source_sha}` ||
    !isSha256(evidence.d1_schema_digest) ||
    !isSha256(evidence.reservation_id) ||
    !isSha256(evidence.authority_operation_id) ||
    typeof evidence.request_nonce !== "string" ||
    !CHALLENGE.test(evidence.request_nonce) ||
    !isSha256(evidence.signed_attestation_digest) ||
    typeof evidence.signed_attestation_json_utf8_base64 !== "string" ||
    typeof evidence.signed_attestation_json_utf8_length !== "number" ||
    !Number.isSafeInteger(evidence.signed_attestation_json_utf8_length) ||
    evidence.signed_attestation_json_utf8_length <= 0 ||
    evidence.signed_attestation_json_utf8_length > MAX_ATTESTATION_BYTES ||
    !isSha256(evidence.evidence_digest)
  ) throw new Error("Premium audit evidence is malformed");

  let exactBytes: Uint8Array;
  let parsed: unknown;
  try {
    exactBytes = base64ToBytes(evidence.signed_attestation_json_utf8_base64);
    if (
      exactBytes.length !== evidence.signed_attestation_json_utf8_length ||
      bytesToBase64(exactBytes) !== evidence.signed_attestation_json_utf8_base64
    ) throw new Error("non-canonical base64");
    const exactText = new TextDecoder("utf-8", {
      fatal: true,
      ignoreBOM: false,
    }).decode(exactBytes);
    parsed = JSON.parse(exactText);
    if (!isPlainObject(parsed) || canonicalJson(parsed) !== exactText) {
      throw new Error("non-canonical attestation JSON");
    }
  } catch {
    throw new Error("Premium audit evidence exact bytes are invalid");
  }
  if (await canonicalDigest(parsed) !== evidence.signed_attestation_digest) {
    throw new Error("Premium audit evidence attestation digest drifted");
  }
  const { evidence_digest: suppliedDigest, ...body } = evidence;
  if (suppliedDigest !== await canonicalDigest(body)) {
    throw new Error("Premium audit evidence digest drifted");
  }
  return evidence as PremiumAuditEvidence;
}

export async function handleReceiptActivationObserverRequest(
  request: Request,
  env: ObserverEnv,
  ctx: ExecutionContext,
): Promise<Response> {
  if (ctx.access === undefined || typeof ctx.access.aud !== "string" ||
      ctx.access.aud.length === 0) {
    return closedError(403, "ACCESS_REQUIRED");
  }
  if (request.method !== "GET") return closedError(405, "GET_REQUIRED");
  const url = new URL(request.url);
  const challenges = url.searchParams.getAll("challenge");
  if (
    url.pathname !== AUDIT_PATH || [...url.searchParams.keys()].length !== 1 ||
    challenges.length !== 1 || !CHALLENGE.test(challenges[0]!) ||
    request.body !== null || request.headers.has("content-length") ||
    request.headers.has("transfer-encoding")
  ) return closedError(400, "CLOSED_REQUEST_REQUIRED");

  let provenance: ReturnType<typeof observerProvenance>;
  try {
    provenance = observerProvenance(env);
  } catch {
    return closedError(503, "OBSERVER_NOT_ACTIVE");
  }
  if (env.PREMIUM_RECEIPT_OPERATOR === undefined) {
    return closedError(503, "PREMIUM_OPERATOR_UNAVAILABLE");
  }

  try {
    const premiumEvidence = await requirePremiumEvidence(
      await env.PREMIUM_RECEIPT_OPERATOR.staging_recovery_audit_evidence(),
    );
    const body = {
      schema_version: "receipt-activation-observer-response/v1" as const,
      purpose: "receipt_authority_recovery_canary" as const,
      eligibility: "AUDIT_ONLY" as const,
      environment: "staging" as const,
      challenge: challenges[0]!,
      observer_source_sha: provenance.sourceSha,
      observer_worker_version_id: provenance.versionId,
      observer_worker_version_tag: provenance.versionTag,
      access_authenticated: true as const,
      access_aud: ctx.access.aud,
      premium_evidence: premiumEvidence,
      premium_evidence_digest: premiumEvidence.evidence_digest,
    };
    const document = { ...body, response_digest: await canonicalDigest(body) };
    const encoded = canonicalJson(document);
    if (new TextEncoder().encode(encoded).length > MAX_RESPONSE_BYTES) {
      return closedError(502, "PREMIUM_EVIDENCE_OVERSIZE");
    }
    return new Response(encoded, { status: 200, headers: responseHeaders() });
  } catch {
    return closedError(502, "PREMIUM_EVIDENCE_INVALID");
  }
}
