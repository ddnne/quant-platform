import { env, exports as workerExports } from "cloudflare:workers";
import {
  applyD1Migrations,
  evictDurableObject,
  reset,
  runInDurableObject,
} from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, inject, it } from "vitest";
import {
  fetchGovernedPage,
  type AcquisitionEnv,
} from "../../ingestion-secrets/src/jquants_acquisition";
import type {
  AcquisitionResponseMetadataV2,
} from "../../ingestion-secrets/src/jquants_acquisition_types";
import { canonicalDigest, canonicalJson, sha256Digest } from "../src/canonical";
import { ReceiptEvidenceAuthority } from "../src/authority_do";
import { authorityInstanceDigest } from "../src/authority_instance";
import {
  capturedOfficialCalendarDescriptor,
  loadCaptureState,
  type Capture,
  type CaptureRecoveryContext,
} from "../src/raw_capture";
import {
  canonicalProductBody,
  compareUtf8Text,
} from "../src/product_materialization";
import {
  unwrapEd25519PrivateKey,
  wrapEd25519PrivateKey,
} from "../src/key_crypto";
import type {
  ReceiptAuditRecoveryCanaryBeginRequestV1,
  ReceiptAuthorityEnv,
  ReceiptEvidenceAuthorityRpc,
  ReceiptIssueRequestV1,
} from "../src/types";

const runtimeEnv = env as ReceiptAuthorityEnv;
const migrations = inject<Array<{ name: string; queries: string[] }>>(
  "receiptD1Migrations",
);
const originalFetch = globalThis.fetch;

const request: ReceiptIssueRequestV1 = {
  schema_version: "receipt-evidence-issue-request/v1",
  operation: "issue_for_segment",
  environment: "production",
  dataset_id: "indices_bars_daily_topix",
  segment_id: "2024-02",
  request_nonce: "a".repeat(64),
};

const acquisitionEnv: AcquisitionEnv = {
  ENVIRONMENT: "production",
  JQUANTS_API_KEY: "jq-runtime-api-key-not-for-live",
  JQUANTS_RPC_CURSOR_HMAC_KEY:
    "jq-runtime-cursor-hmac-key-not-for-live-00000000000000000000000000000000",
  PROXY_RATE_LIMITER: {
    limit: async () => ({ success: true }),
  },
};

function withAcquisition(
  transform?: (response: Response) => Promise<Response>,
): ReceiptAuthorityEnv {
  const binding = {
    fetch_governed_page: async (input: Parameters<typeof fetchGovernedPage>[0]) => {
      const response = await fetchGovernedPage(input, acquisitionEnv);
      return transform === undefined ? response : transform(response);
    },
  };
  return {
    ...runtimeEnv,
    JQUANTS_ACQUISITION: binding as unknown as ReceiptAuthorityEnv["JQUANTS_ACQUISITION"],
  };
}

function installSinglePageUpstream(
  body = '{"data":[{"Date":"2024-02-01","Open":1,"Close":2}],"pagination_key":null}',
): void {
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    expect(new Headers(init?.headers).get("x-api-key")).toBe(
      "jq-runtime-api-key-not-for-live",
    );
    return new Response(body, {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
}

function installTopixContinuationUpstream(): void {
  let calls = 0;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(new Headers(init?.headers).get("x-api-key")).toBe(
      "jq-runtime-api-key-not-for-live",
    );
    const url = new URL(input instanceof Request ? input.url : input.toString());
    calls += 1;
    if (calls === 1) {
      expect(url.searchParams.get("pagination_key")).toBeNull();
      return new Response(
        '{"data":[{"Date":"2024-02-01","Open":1,"Close":2}],"pagination_key":"topix-page-2"}',
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    expect(calls).toBe(2);
    expect(url.searchParams.get("pagination_key")).toBe("topix-page-2");
    return new Response(
      '{"data":[{"Date":"2024-02-02","Open":2,"Close":3}],"pagination_key":null}',
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
}

function officialCalendarBody(
  segmentStart: string,
  segmentEnd: string,
  businessDates: readonly string[],
): string {
  const business = new Set(businessDates);
  const rows: Array<{ Date: string; HolDiv: string }> = [];
  let current = new Date(`${segmentStart}T00:00:00Z`);
  const terminal = new Date(`${segmentEnd}T00:00:00Z`);
  while (current <= terminal) {
    const date = current.toISOString().slice(0, 10);
    rows.push({ Date: date, HolDiv: business.has(date) ? "1" : "0" });
    current = new Date(current.getTime() + 86_400_000);
  }
  return JSON.stringify({ data: rows });
}

function installMasterCalendarUpstream(
  businessDates: readonly string[] = ["2024-02-01", "2024-02-02"],
): () => number {
  let calls = 0;
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(new Headers(init?.headers).get("x-api-key")).toBe(
      "jq-runtime-api-key-not-for-live",
    );
    const url = new URL(input instanceof Request ? input.url : input.toString());
    calls += 1;
    if (url.pathname === "/v2/markets/calendar") {
      expect(url.searchParams.get("from")).toBe("2024-02-01");
      expect(url.searchParams.get("to")).toBe("2024-02-29");
      return new Response(
        officialCalendarBody("2024-02-01", "2024-02-29", businessDates),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    }
    expect(url.pathname).toBe("/v2/equities/master");
    const date = url.searchParams.get("date");
    expect(businessDates).toContain(date);
    return new Response(
      JSON.stringify({
        data: [{ Code: date === "2024-02-01" ? "1301" : "1302", Date: date }],
        pagination_key: null,
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;
  return () => calls;
}

function decodeBase64UrlForTest(value: string): string {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") +
    "=".repeat((4 - value.length % 4) % 4);
  return new TextDecoder().decode(
    Uint8Array.from(atob(padded), (character) => character.charCodeAt(0)),
  );
}

function encodeBase64UrlForTest(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function rewriteContinuationPayload(
  response: Response,
  mutate: (payload: Record<string, unknown>) => void | Promise<void>,
): Promise<Response> {
  const body = await response.arrayBuffer();
  const headers = new Headers(response.headers);
  const token = headers.get("x-quant-acquisition-continuation");
  if (token === null || token === "NONE") throw new Error("test continuation absent");
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "jqa2") {
    throw new Error("test continuation malformed");
  }
  const payload = JSON.parse(decodeBase64UrlForTest(parts[1]!)) as Record<string, unknown>;
  await mutate(payload);
  headers.set(
    "x-quant-acquisition-continuation",
    `jqa2.${encodeBase64UrlForTest(canonicalJson(payload))}.${parts[2]}`,
  );
  const metadata = acquisitionMetadata(headers);
  headers.set(
    "x-quant-acquisition-metadata-digest",
    await canonicalDigest(metadata),
  );
  return new Response(body, { status: response.status, headers });
}

async function replaceCalendarCursorClaims(
  payload: Record<string, unknown>,
  businessDates: readonly string[],
  segmentStart = "2024-02-01",
  segmentEnd = "2024-02-29",
): Promise<void> {
  const orderedQuery = [["from", segmentStart], ["to", segmentEnd]];
  const calendarQueryDigest = await canonicalDigest({
    schema_version: "jquants-acquisition-query/v2",
    path: "/v2/markets/calendar",
    ordered_query: orderedQuery,
  });
  const businessDatesDigest = await canonicalDigest({
    schema_version: "jquants-official-business-dates/v1",
    segment_start: segmentStart,
    segment_end: segmentEnd,
    dates: businessDates,
  });
  const rawBodyDigest = payload.official_calendar_raw_body_digest;
  payload.official_calendar_query_digest = calendarQueryDigest;
  payload.official_business_dates_digest = businessDatesDigest;
  payload.official_business_dates = businessDates;
  payload.official_calendar_binding_digest = await canonicalDigest({
    schema_version: "jquants-official-business-calendar-binding/v1",
    path: "/v2/markets/calendar",
    ordered_query: orderedQuery,
    raw_body_digest: rawBodyDigest,
    calendar_query_digest: calendarQueryDigest,
    business_dates_digest: businessDatesDigest,
    business_dates: businessDates,
  });
}

function nullHeader(value: string): string | null {
  return value === "NONE" ? null : value;
}

function integerHeader(value: string): number | null {
  return value === "NONE" ? null : Number(value);
}

function acquisitionMetadata(headers: Headers): AcquisitionResponseMetadataV2 {
  const get = (name: string): string => {
    const value = headers.get(name);
    if (value === null) throw new Error(`test acquisition header absent: ${name}`);
    return value;
  };
  return {
    schema_version: "jquants-acquisition-rpc-response-metadata/v2",
    evidence_state: get("x-quant-acquisition-evidence-state") as AcquisitionResponseMetadataV2["evidence_state"],
    environment: nullHeader(get("x-quant-acquisition-environment")) as AcquisitionResponseMetadataV2["environment"],
    dataset_id: nullHeader(get("x-quant-acquisition-dataset")),
    segment_id: nullHeader(get("x-quant-acquisition-segment")),
    segment_start: nullHeader(get("x-quant-acquisition-segment-start")),
    segment_end: nullHeader(get("x-quant-acquisition-segment-end")),
    request_digest: nullHeader(get("x-quant-acquisition-request-digest")),
    request_identity_digest: nullHeader(get("x-quant-acquisition-request-identity-digest")),
    previous_request_digest: nullHeader(get("x-quant-acquisition-previous-request-digest")),
    acquisition_id: nullHeader(get("x-quant-acquisition-acquisition-id")),
    acquisition_issued_at: nullHeader(get("x-quant-acquisition-acquisition-issued-at")),
    acquisition_expires_at: nullHeader(get("x-quant-acquisition-acquisition-expires-at")),
    target_registry_digest: nullHeader(get("x-quant-acquisition-registry-digest")),
    source_capability_digest: nullHeader(get("x-quant-acquisition-source-capability-digest")),
    dataset_contract_digest: nullHeader(get("x-quant-acquisition-dataset-contract-digest")),
    coverage_policy_digest: nullHeader(get("x-quant-acquisition-coverage-policy-digest")),
    query_contract_digest: nullHeader(get("x-quant-acquisition-query-contract-digest")),
    cursor_key_id: nullHeader(get("x-quant-acquisition-cursor-key-id")),
    slice_date: nullHeader(get("x-quant-acquisition-slice-date")),
    query_digest: nullHeader(get("x-quant-acquisition-query-digest")),
    page_ordinal: integerHeader(get("x-quant-acquisition-page-ordinal")),
    slice_ordinal: integerHeader(get("x-quant-acquisition-slice-ordinal")),
    provider_page_ordinal: integerHeader(get("x-quant-acquisition-provider-page-ordinal")),
    provider_pagination_state: get("x-quant-acquisition-provider-pagination-state") as AcquisitionResponseMetadataV2["provider_pagination_state"],
    upstream_http_status: integerHeader(get("x-quant-acquisition-upstream-status")),
    body_digest: get("x-quant-acquisition-body-digest"),
    body_kind: get("x-quant-acquisition-body-kind") as AcquisitionResponseMetadataV2["body_kind"],
    pagination_state: get("x-quant-acquisition-pagination-state") as AcquisitionResponseMetadataV2["pagination_state"],
    continuation_token: nullHeader(get("x-quant-acquisition-continuation")),
    content_type: get("content-type") as AcquisitionResponseMetadataV2["content_type"],
    redirect_count: Number(get("x-quant-acquisition-redirect-count")),
    previous_chain_digest: nullHeader(get("x-quant-acquisition-previous-chain-digest")),
    chain_digest: nullHeader(get("x-quant-acquisition-chain-digest")),
  };
}

async function forgeSegmentExhaustion(response: Response): Promise<Response> {
  const body = await response.arrayBuffer();
  const headers = new Headers(response.headers);
  headers.set("x-quant-acquisition-pagination-state", "EXHAUSTED");
  headers.set("x-quant-acquisition-continuation", "NONE");
  const metadata = acquisitionMetadata(headers);
  metadata.chain_digest = await canonicalDigest({
    schema_version: "jquants-acquisition-chain-link/v2",
    acquisition_id: metadata.acquisition_id,
    cursor_key_id: metadata.cursor_key_id,
    acquisition_issued_at: metadata.acquisition_issued_at,
    acquisition_expires_at: metadata.acquisition_expires_at,
    request_digest: metadata.request_digest,
    request_identity_digest: metadata.request_identity_digest,
    previous_request_digest: metadata.previous_request_digest,
    previous_chain_digest: metadata.previous_chain_digest,
    page_ordinal: metadata.page_ordinal,
    slice_date: metadata.slice_date,
    slice_ordinal: metadata.slice_ordinal,
    provider_page_ordinal: metadata.provider_page_ordinal,
    query_digest: metadata.query_digest,
    body_digest: metadata.body_digest,
    upstream_http_status: metadata.upstream_http_status,
    evidence_state: metadata.evidence_state,
    provider_pagination_state: metadata.provider_pagination_state,
    pagination_state: metadata.pagination_state,
  });
  headers.set("x-quant-acquisition-chain-digest", metadata.chain_digest);
  headers.set(
    "x-quant-acquisition-metadata-digest",
    await canonicalDigest(metadata),
  );
  return new Response(body, { status: response.status, headers });
}

function decodeBase64(value: string): Uint8Array {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

async function activateRegisteredTestKey(): Promise<{
  stub: ReturnType<typeof runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName>;
  registration: Awaited<ReturnType<ReceiptEvidenceAuthority["public_key_registration"]>>;
}> {
  const stub = runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
    "receipt:production",
  );
  const registration = await runInDurableObject(stub, async (instance) => {
    const internal = instance as unknown as { env: ReceiptAuthorityEnv };
    internal.env.AUTHORITY_MODE = "PENDING";
    internal.env.ACTIVATED_KEY_ID = undefined;
    const pendingRegistration = await instance.public_key_registration();
    internal.env.AUTHORITY_MODE = "ACTIVE";
    internal.env.ACTIVATED_KEY_ID = pendingRegistration.key_id;
    return pendingRegistration;
  });
  return { stub, registration };
}

function installAuthorityAcquisition(
  transform?: (response: Response) => Promise<Response>,
): void {
  (runtimeEnv as unknown as Record<string, unknown>).JQUANTS_ACQUISITION =
    withAcquisition(transform).JQUANTS_ACQUISITION;
}

type TestCaptureStateV2 = {
  schema_version: "receipt-authority-capture-state/v2";
  validator: {
    schema_version: "receipt-authority-capture-validator/v1";
    capture_deployment_version: string;
    digest: string;
  };
  authority_binding: Record<string, unknown>;
  capture: Capture;
};

type InterruptedCapture = {
  stub: ReturnType<typeof runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName>;
  context: CaptureRecoveryContext;
  state: TestCaptureStateV2;
};

async function interruptAfterDurableCapture(
  issueRequest: ReceiptIssueRequestV1,
): Promise<InterruptedCapture> {
  const { stub } = await activateRegisteredTestKey();
  await runtimeEnv.DB.prepare(
    `CREATE TRIGGER inject_capture_reproof_failure
     BEFORE UPDATE OF state ON receipt_authority_operations
     WHEN OLD.state='COLLECTING' AND NEW.state='STRUCTURED_COMMITTED'
     BEGIN
       SELECT RAISE(ABORT, 'injected capture reproof failure');
     END`,
  ).run();
  await expect(runInDurableObject(stub, (instance) =>
    instance.issue_for_segment(issueRequest)
  )).rejects.toThrow("injected capture reproof failure");
  await runtimeEnv.DB.prepare(
    "DROP TRIGGER inject_capture_reproof_failure",
  ).run();
  const operationId = await canonicalDigest(issueRequest);
  const durable = await runInDurableObject(stub, async (_instance, state) =>
    state.storage.sql.exec<{
      request_digest: string;
      attempt_id: string;
      acquisition_nonce: string;
      created_at: string;
      capture_key: string;
      capture_digest: string;
    }>(
      `SELECT o.request_digest,a.attempt_id,a.acquisition_nonce,a.created_at,
              a.capture_key,a.capture_digest
         FROM authority_operations o
         JOIN authority_capture_attempts a ON a.operation_id=o.operation_id
        WHERE o.operation_id=? AND a.state='CAPTURED'`,
      operationId,
    ).one()
  );
  const object = await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.get(
    durable.capture_key,
  );
  if (object === null) throw new Error("test capture state missing");
  const state = JSON.parse(await object.text()) as TestCaptureStateV2;
  return {
    stub,
    context: {
      key: durable.capture_key,
      expectedDigest: durable.capture_digest,
      operationId,
      requestDigest: durable.request_digest,
      captureAttemptId: durable.attempt_id,
      acquisitionNonce: durable.acquisition_nonce,
      collectionStartedAt: durable.created_at,
      request: issueRequest,
    },
    state,
  };
}

async function replaceCaptureState(
  key: string,
  value: unknown,
): Promise<string> {
  const body = canonicalJson(value);
  await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.delete(key);
  await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.put(key, body);
  return sha256Digest(body);
}

function legacyFlatCaptureLoaderWouldAccept(value: unknown): boolean {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const candidate = value as Partial<Capture>;
  return typeof candidate.rawManifestKey === "string" &&
    typeof candidate.rawManifestDigest === "string" &&
    typeof candidate.rawDigest === "string" &&
    typeof candidate.manifestFileDigest === "string" &&
    typeof candidate.collectionDigest === "string" &&
    typeof candidate.terminalChainDigest === "string" &&
    typeof candidate.acquisitionExpiresAt === "string" &&
    Array.isArray(candidate.pages) && candidate.pages.length > 0 &&
    typeof candidate.initialRequest === "object" &&
    candidate.initialRequest !== null;
}

beforeEach(async () => {
  await reset();
  (runtimeEnv as unknown as { ENVIRONMENT: string }).ENVIRONMENT = "production";
  (runtimeEnv as unknown as { CF_VERSION_METADATA: WorkerVersionMetadata })
    .CF_VERSION_METADATA = {
      id: "10000000-0000-4000-8000-000000000002",
      tag: `rp-p-r-${"1".repeat(40)}`,
      timestamp: "2026-08-27T08:00:00.000Z",
    };
  (runtimeEnv as unknown as { AUTHORITY_MODE: string }).AUTHORITY_MODE = "ACTIVE";
  (runtimeEnv as unknown as { ACTIVATED_KEY_ID?: string }).ACTIVATED_KEY_ID =
    undefined;
  await applyD1Migrations(runtimeEnv.DB, migrations);
  installSinglePageUpstream();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("Receipt Evidence Authority in workerd", () => {
  it("exposes only five public Durable Object RPC methods", async () => {
    expect(
      Reflect.ownKeys(ReceiptEvidenceAuthority.prototype)
        .map(String)
        .filter((name) => name !== "constructor")
        .sort(),
    ).toEqual([
      "begin_audit_recovery_canary",
      "issue_for_segment",
      "public_key_registration",
      "recover_audit_recovery_canary",
      "recover_issue",
    ]);

    const stub = runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
      "receipt:private-rpc-negative",
    );
    const snapshot = async () => ({
      durable: await runInDurableObject(stub, async (_instance, state) => ({
        operations: state.storage.sql.exec<{ count: number }>(
          "SELECT COUNT(*) AS count FROM authority_operations",
        ).one().count,
        attempts: state.storage.sql.exec<{ count: number }>(
          "SELECT COUNT(*) AS count FROM authority_capture_attempts",
        ).one().count,
        events: state.storage.sql.exec<{ count: number }>(
          "SELECT COUNT(*) AS count FROM authority_events",
        ).one().count,
        keys: state.storage.sql.exec<{ count: number }>(
          "SELECT COUNT(*) AS count FROM authority_key_metadata",
        ).one().count,
        auditOperations: state.storage.sql.exec<{ count: number }>(
          "SELECT COUNT(*) AS count FROM authority_audit_recovery_operations",
        ).one().count,
        auditEvents: state.storage.sql.exec<{ count: number }>(
          "SELECT COUNT(*) AS count FROM authority_audit_recovery_events",
        ).one().count,
      })),
      d1: await runtimeEnv.DB.prepare(
        `SELECT
          (SELECT COUNT(*) FROM collection_receipts) AS receipts,
          (SELECT COUNT(*) FROM receipt_authority_operations) AS operations,
          (SELECT COUNT(*) FROM receipt_authority_structured_rows) AS rows,
          (SELECT COUNT(*) FROM receipt_product_materializations) AS products`,
      ).first(),
      r2: (await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.list()).objects
        .map((object) => object.key)
        .sort(),
    });
    const before = await snapshot();
    const formerPrivateMethods = [
      "operation",
      "requireOperation",
      "latestCaptureAttempt",
      "captureAttempt",
      "requireLatestCaptureAttempt",
      "operationSnapshot",
      "event",
      "requireExistingEvents",
      "requireEvent",
      "transactEvents",
      "requireValidEventChain",
      "captureAttempts",
      "requireAuditedOperation",
      "loadOrCreateKey",
      "keyGeneration",
      "keyWrapAad",
      "requireOperationalPrivateKey",
      "ensureKey",
      "requireSigningKey",
    ] as const;
    expect(await runInDurableObject(stub, (instance) => {
      const untypedInstance = instance as unknown as Record<string, unknown>;
      return formerPrivateMethods.map((method) => ({
        method,
        type: typeof untypedInstance[method],
      }));
    })).toEqual(formerPrivateMethods.map((method) => ({
      method,
      type: "undefined",
    })));

    // `ensureKey` was the highest-impact confirmed exploit: it created key
    // metadata without going through public registration. Keep one real stub
    // denial to exercise workerd's RPC dispatcher; exact prototype equality
    // above covers the complete former-private inventory without 19 noisy
    // remote errors.
    const untypedStub = stub as unknown as {
      ensureKey(): Promise<unknown>;
    };
    let rejected = false;
    try {
      await untypedStub.ensureKey();
    } catch (error) {
      rejected = true;
      expect(error).toBeInstanceOf(TypeError);
      expect(String(error)).toContain('does not implement "ensureKey"');
    }
    expect(rejected).toBe(true);
    expect(await snapshot()).toEqual(before);
  });

  it.each([
    {
      eventType: "COLLECTION_STARTED",
      expectedState: null,
      expectedClaims: null,
      expectedEnvelope: null,
      expectedReceipt: null,
      expectedEvents: 0,
    },
    {
      eventType: "CAPTURE_COMMITTED",
      expectedState: "COLLECTING",
      expectedClaims: null,
      expectedEnvelope: null,
      expectedReceipt: null,
      expectedEvents: 1,
    },
    {
      eventType: "CLAIMS_RESERVED",
      expectedState: "COLLECTING",
      expectedClaims: null,
      expectedEnvelope: null,
      expectedReceipt: null,
      expectedEvents: 2,
    },
    {
      eventType: "RECEIPT_ISSUED_PENDING_FINALIZE",
      expectedState: "COLLECTING",
      expectedClaims: "present",
      expectedEnvelope: null,
      expectedReceipt: null,
      expectedEvents: 3,
    },
    {
      eventType: "RECEIPT_FINALIZED",
      expectedState: "ISSUED_PENDING_FINALIZE",
      expectedClaims: "present",
      expectedEnvelope: "present",
      expectedReceipt: null,
      expectedEvents: 4,
    },
  ])("rolls back the state paired with $eventType when event append fails", async ({
    eventType,
    expectedState,
    expectedClaims,
    expectedEnvelope,
    expectedReceipt,
    expectedEvents,
  }) => {
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    await runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec(
        `CREATE TRIGGER reject_test_event
         BEFORE INSERT ON authority_events
         WHEN NEW.event_type = '${eventType}'
         BEGIN
           SELECT RAISE(ABORT, 'injected event failure');
         END`,
      );
    });
    const faultRequest = {
      ...request,
      request_nonce: eventType.charCodeAt(0).toString(16).padStart(64, "0"),
    };
    await expect(runInDurableObject(
      stub,
      (instance) => instance.issue_for_segment(faultRequest),
    )).rejects.toThrow("injected event failure");
    const operationId = await canonicalDigest(faultRequest);
    const observed = await runInDurableObject(
      stub,
      async (_instance, state) => {
        const operation = state.storage.sql.exec<{
          state: string;
          claims_digest: string | null;
          envelope_digest: string | null;
          receipt_digest: string | null;
        }>(
          `SELECT state,claims_digest,envelope_digest,receipt_digest
             FROM authority_operations WHERE operation_id=?`,
          operationId,
        ).toArray()[0] ?? null;
        const attempt = state.storage.sql.exec<{
          state: string;
          capture_digest: string | null;
        }>(
          `SELECT state,capture_digest FROM authority_capture_attempts
            WHERE operation_id=? ORDER BY attempt_ordinal DESC LIMIT 1`,
          operationId,
        ).toArray()[0] ?? null;
        const count = state.storage.sql.exec<{ count: number }>(
          "SELECT COUNT(*) AS count FROM authority_events",
        ).one().count;
        return { operation, attempt, count };
      },
    );
    expect(observed.operation?.state ?? null).toBe(expectedState);
    expect(observed.operation?.claims_digest ? "present" : null).toBe(
      expectedClaims,
    );
    expect(observed.operation?.envelope_digest ? "present" : null).toBe(
      expectedEnvelope,
    );
    expect(observed.operation?.receipt_digest ? "present" : null).toBe(
      expectedReceipt,
    );
    expect(observed.count).toBe(expectedEvents);
    if (eventType === "CAPTURE_COMMITTED") {
      expect(observed.attempt).toEqual({ state: "OPEN", capture_digest: null });
    }
  });

  it("rolls back abandonment when the paired replacement-start event fails", async () => {
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    const faultRequest = {
      ...request,
      request_nonce: "b".repeat(64),
    };
    await runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec(
        `CREATE TRIGGER reject_test_event
         BEFORE INSERT ON authority_events
         WHEN NEW.event_type = 'CAPTURE_COMMITTED'
         BEGIN
           SELECT RAISE(ABORT, 'injected capture event failure');
         END`,
      );
    });
    await expect(runInDurableObject(
      stub,
      (instance) => instance.issue_for_segment(faultRequest),
    )).rejects.toThrow("injected capture event failure");
    await runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec("DROP TRIGGER reject_test_event");
      state.storage.sql.exec(
        `CREATE TRIGGER reject_test_event
         BEFORE INSERT ON authority_events
         WHEN NEW.event_type = 'CAPTURE_ATTEMPT_STARTED'
         BEGIN
           SELECT RAISE(ABORT, 'injected replacement event failure');
         END`,
      );
    });
    await expect(runInDurableObject(
      stub,
      (instance) => instance.recover_issue({
        ...faultRequest,
        operation: "recover_issue",
      }),
    )).rejects.toThrow("injected replacement event failure");
    const operationId = await canonicalDigest(faultRequest);
    const observed = await runInDurableObject(
      stub,
      async (_instance, state) => ({
        attempts: state.storage.sql.exec<{
          attempt_ordinal: number;
          state: string;
        }>(
          `SELECT attempt_ordinal,state FROM authority_capture_attempts
            WHERE operation_id=? ORDER BY attempt_ordinal`,
          operationId,
        ).toArray(),
        events: state.storage.sql.exec<{ event_type: string }>(
          "SELECT event_type FROM authority_events ORDER BY sequence",
        ).toArray(),
      }),
    );
    expect(observed.attempts).toEqual([{
      attempt_ordinal: 1,
      state: "OPEN",
    }]);
    expect(observed.events).toEqual([{ event_type: "COLLECTION_STARTED" }]);
  });

  it("renders the cross-language product JSONL vector in UTF-8 key order", async () => {
    const rows = ["z-key", "a-key"].map((naturalKey) => ({
      source: "jquants" as const,
      dataset: "indices_bars_daily_topix",
      natural_key: naturalKey,
      event_time: "2024-02-01T00:00:00Z",
      available_at: "2024-02-01T00:00:00Z",
      ingested_at: "2024-02-02T00:00:00Z",
      payload: `{"key":"${naturalKey}"}`,
      raw_payload: `{"key":"${naturalKey}"}`,
      row_digest: "sha256:" + "0".repeat(64),
    }));
    const body = canonicalProductBody(rows);
    expect(body.indexOf("a-key")).toBeLessThan(body.indexOf("z-key"));
    expect(await sha256Digest(new TextEncoder().encode(body))).toBe(
      "sha256:fc5f92e255656fa9c17298cc492b6f72ee1c647fa47a749174ea66c290f9dc8e",
    );
  });
  it("uses SQLite BINARY-compatible UTF-8 order for non-ASCII natural keys", () => {
    const keys = ["あ", "z", "é", "A", "😀"];
    const actual = [...keys].sort(compareUtf8Text);
    const encoder = new TextEncoder();
    const expected = [...keys].sort((left, right) => {
      const leftBytes = encoder.encode(left);
      const rightBytes = encoder.encode(right);
      const length = Math.min(leftBytes.length, rightBytes.length);
      for (let index = 0; index < length; index += 1) {
        if (leftBytes[index] !== rightBytes[index]) {
          return leftBytes[index]! - rightBytes[index]!;
        }
      }
      return leftBytes.length - rightBytes.length;
    });
    expect(actual).toEqual(expected);
    expect(actual).toEqual(["A", "z", "é", "あ", "😀"]);
  });
  it("has no public HTTP surface and permits provisioning only while PENDING", async () => {
    const rpc = workerExports.default as unknown as ReceiptEvidenceAuthorityRpc & Fetcher;
    const response = await rpc.fetch(new Request("https://authority.invalid/health"));
    expect(response.status).toBe(404);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.text()).toBe("");

    const stub = runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
      "receipt:production",
    );
    const registration = await runInDurableObject(stub, async (instance) => {
      const internal = instance as unknown as { env: ReceiptAuthorityEnv };
      internal.env.AUTHORITY_MODE = "PENDING";
      internal.env.ACTIVATED_KEY_ID = undefined;
      return instance.public_key_registration();
    });
    expect(registration).toMatchObject({
      schema_version: "receipt-public-key-registration/v1",
      purpose: "receipt_verification",
      environment: "production",
      authority_instance_digest: await authorityInstanceDigest("production"),
      authority_status: "PENDING",
      algorithm: "Ed25519",
      private_key_extractable: false,
      status: "pending",
    });
    expect(registration.registration_digest).toBe(
      await canonicalDigest({
        schema_version: registration.schema_version,
        purpose: registration.purpose,
        environment: registration.environment,
        authority_instance_digest: registration.authority_instance_digest,
        authority_resource_digest: registration.authority_resource_digest,
        authority_status: registration.authority_status,
        action: registration.action,
        deployment_source_sha: registration.deployment_source_sha,
        authority_worker_version_id: registration.authority_worker_version_id,
        authority_worker_version_tag: registration.authority_worker_version_tag,
        operation_binding_digest: registration.operation_binding_digest,
        key_id: registration.key_id,
        key_generation: registration.key_generation,
        algorithm: registration.algorithm,
        public_key_base64: registration.public_key_base64,
        private_key_extractable: registration.private_key_extractable,
        status: registration.status,
        generated_at: registration.generated_at,
      }),
    );
    expect(registration.key_id).toBe(
      `receipt-production-${
        (await sha256Digest(decodeBase64(registration.public_key_base64)))
          .slice(7, 23)
      }`,
    );
    await runInDurableObject(stub, async (instance) => {
      const internal = instance as unknown as { env: ReceiptAuthorityEnv };
      internal.env.AUTHORITY_MODE = "ACTIVE";
      internal.env.ACTIVATED_KEY_ID = registration.key_id;
      await expect(instance.public_key_registration()).rejects.toThrow(
        "requires unactivated PENDING mode",
      );
    });
  });

  it("uses a dedicated signed AUDIT_ONLY state machine for staging recovery", async () => {
    const sourceSha = "2".repeat(40);
    const callerVersionId = "20000000-0000-4000-8000-000000000002";
    const authorityVersionId = "30000000-0000-4000-8000-000000000003";
    const stub = runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
      "receipt:staging",
    );
    const registration = await runInDurableObject(stub, async (instance) => {
      const internal = instance as unknown as { env: ReceiptAuthorityEnv };
      internal.env.ENVIRONMENT = "staging";
      internal.env.AUTHORITY_MODE = "PENDING";
      internal.env.ACTIVATED_KEY_ID = undefined;
      internal.env.CF_VERSION_METADATA = {
        id: authorityVersionId,
        tag: `rp-s-r-${sourceSha}`,
        timestamp: "2026-08-28T00:00:00.000Z",
      };
      const pending = await instance.public_key_registration();
      internal.env.AUTHORITY_MODE = "ACTIVE";
      internal.env.ACTIVATED_KEY_ID = pending.key_id;
      internal.env.CF_VERSION_METADATA = {
        id: authorityVersionId,
        tag: `ra-s-r-${sourceSha}`,
        timestamp: "2026-08-28T00:01:00.000Z",
      };
      return pending;
    });
    const beginRequest: ReceiptAuditRecoveryCanaryBeginRequestV1 = {
      schema_version: "receipt-audit-recovery-canary-request/v1",
      purpose: "receipt_authority_recovery_canary",
      eligibility: "AUDIT_ONLY",
      operation: "begin_audit_recovery_canary",
      environment: "staging",
      caller_source_sha: sourceSha,
      caller_worker_version_id: callerVersionId,
      caller_worker_version_tag: `ra-s-c-${sourceSha}`,
      request_nonce: "c".repeat(64),
    };
    const productBefore = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS count FROM collection_receipts",
    ).first<{ count: number }>();
    const bucketBefore = await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.list();

    const begun = await runInDurableObject(
      stub,
      (instance) => instance.begin_audit_recovery_canary(beginRequest),
    );
    expect(begun).toMatchObject({
      eligibility: "AUDIT_ONLY",
      rpc_replayed: false,
      initial_result: { state: "RECOVERY_REQUIRED" },
    });
    const repeatedBegin = await runInDurableObject(
      stub,
      (instance) => instance.begin_audit_recovery_canary(beginRequest),
    );
    expect(repeatedBegin).toEqual({ ...begun, rpc_replayed: true });

    const recoverRequest = {
      ...beginRequest,
      operation: "recover_audit_recovery_canary" as const,
    };
    const firstRecovery = await runInDurableObject(
      stub,
      (instance) => instance.recover_audit_recovery_canary(recoverRequest),
    );
    expect(firstRecovery).toMatchObject({
      schema_version: "receipt-audit-recovery-pending-replay-result/v1",
      eligibility: "AUDIT_ONLY",
      state: "RECOVERED_PENDING_REPLAY",
      rpc_replayed: false,
    });
    if (
      firstRecovery.schema_version !==
        "receipt-audit-recovery-pending-replay-result/v1"
    ) throw new Error("test expected first recovery to remain unsigned");
    expect(firstRecovery).not.toHaveProperty("signed_attestation");
    expect(await runInDurableObject(stub, async (_instance, state) => ({
      state: state.storage.sql.exec<{ state: string }>(
        `SELECT state FROM authority_audit_recovery_operations
          WHERE operation_id=?`,
        begun.operation_id,
      ).one().state,
      events: state.storage.sql.exec<{ count: number }>(
        `SELECT COUNT(*) AS count FROM authority_audit_recovery_events
          WHERE operation_id=?`,
        begun.operation_id,
      ).one().count,
      signed: state.storage.sql.exec<{ signed: string | null }>(
        `SELECT signed_attestation_json AS signed
           FROM authority_audit_recovery_operations WHERE operation_id=?`,
        begun.operation_id,
      ).one().signed,
    }))).toEqual({
      state: "RECOVERED_PENDING_REPLAY",
      events: 2,
      signed: null,
    });

    const recovered = await runInDurableObject(
      stub,
      (instance) => instance.recover_audit_recovery_canary(recoverRequest),
    );
    expect(recovered).toMatchObject({
      eligibility: "AUDIT_ONLY",
      final_state: "AUDIT_FINALIZED",
      rpc_replayed: true,
      signed_attestation: {
        eligibility: "AUDIT_ONLY",
        issuer_class: "ReceiptEvidenceAuthorityAuditSigner",
      },
    });
    if (recovered.schema_version !== "receipt-audit-recovery-result/v1") {
      throw new Error("test expected replay-confirmed attestation");
    }
    const replay = await runInDurableObject(
      stub,
      (instance) => instance.recover_audit_recovery_canary(recoverRequest),
    );
    expect(replay).toEqual(recovered);

    const publicKey = await crypto.subtle.importKey(
      "raw",
      decodeBase64(registration.public_key_base64),
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    const signedClaimsBytes = decodeBase64(
      recovered.signed_attestation.signed_claims_base64,
    );
    expect(await crypto.subtle.verify(
      "Ed25519",
      publicKey,
      decodeBase64(
        recovered.signed_attestation.signature.replace(/^ed25519:/, ""),
      ),
      signedClaimsBytes,
    )).toBe(true);
    const claims = JSON.parse(
      new TextDecoder().decode(signedClaimsBytes),
    ) as Record<string, unknown>;
    expect(claims).toMatchObject({
      eligibility: "AUDIT_ONLY",
      environment: "staging",
      authority_source_sha: sourceSha,
      authority_worker_version_id: authorityVersionId,
      authority_worker_version_tag: `ra-s-r-${sourceSha}`,
      caller_source_sha: sourceSha,
      caller_worker_version_id: callerVersionId,
      caller_worker_version_tag: `ra-s-c-${sourceSha}`,
      operation_id: begun.operation_id,
      request_nonce: beginRequest.request_nonce,
      initial_state: "RECOVERY_REQUIRED",
      initial_result_digest: begun.initial_result_digest,
      recovery_event: "RECOVERY_COMPLETED",
      first_recovery_state: "RECOVERED_PENDING_REPLAY",
      first_recovery_result_digest: firstRecovery.first_recovery_result_digest,
      replay_event: "REPLAY_CONFIRMED",
      replayed: true,
      final_state: "AUDIT_FINALIZED",
    });

    const auditRows = await runInDurableObject(stub, async (_instance, state) => ({
      operations: state.storage.sql.exec<{ count: number }>(
        "SELECT COUNT(*) AS count FROM authority_audit_recovery_operations",
      ).one().count,
      events: state.storage.sql.exec<{ count: number }>(
        "SELECT COUNT(*) AS count FROM authority_audit_recovery_events",
      ).one().count,
      productOperations: state.storage.sql.exec<{ count: number }>(
        "SELECT COUNT(*) AS count FROM authority_operations",
      ).one().count,
    }));
    expect(auditRows).toEqual({ operations: 1, events: 3, productOperations: 0 });
    expect(await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS count FROM collection_receipts",
    ).first<{ count: number }>()).toEqual(productBefore);
    expect((await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.list()).objects).toEqual(
      bucketBefore.objects,
    );

    const concurrentRequest = {
      ...beginRequest,
      request_nonce: "d".repeat(64),
    };
    const concurrent = await Promise.all([
      stub.begin_audit_recovery_canary(concurrentRequest),
      stub.begin_audit_recovery_canary(concurrentRequest),
    ]);
    expect(concurrent[0].operation_id).toBe(concurrent[1].operation_id);
    expect(concurrent[0].initial_result).toEqual(concurrent[1].initial_result);
    expect(concurrent.map((row) => row.rpc_replayed).sort()).toEqual([false, true]);
  });

  it("replays a durable receipt after eviction without a claims RPC seam", async () => {
    installAuthorityAcquisition();
    const { stub, registration } = await activateRegisteredTestKey();
    const issued = await stub.issue_for_segment(request);

    const operationId = await canonicalDigest(request);
    const pending = await runInDurableObject(stub, async (_instance, state) => {
      const operation = state.storage.sql.exec<{
        state: string;
        claims_json: string | null;
        envelope_json: string | null;
      }>(
        `SELECT state,claims_json,envelope_json FROM authority_operations
         WHERE operation_id=?`,
        operationId,
      ).one();
      const wrapped = state.storage.sql.exec<{
        wrap_algorithm: string;
        wrapped_private_key_base64: string;
      }>(
        `SELECT wrap_algorithm,wrapped_private_key_base64
           FROM authority_key_metadata WHERE key_generation=1`,
      ).one();
      expect(wrapped.wrap_algorithm).toBe("AES-GCM");
      expect(wrapped.wrapped_private_key_base64.length).toBeGreaterThan(64);
      return operation;
    });
    expect(pending.state).toBe("FINALIZED");
    expect(pending.claims_json).not.toBeNull();
    expect(pending.envelope_json).not.toBeNull();
    await runInDurableObject(stub, async (instance) => {
      const methods = Object.getOwnPropertyNames(Object.getPrototypeOf(instance));
      expect(methods).not.toContain("append_issued");
      expect(methods).not.toContain("finalize_committed");
    });
    await evictDurableObject(stub);

    const afterEvictionRegistration = await runInDurableObject(
      stub,
      async (instance) => {
        const internal = instance as unknown as { env: ReceiptAuthorityEnv };
        internal.env.AUTHORITY_MODE = "PENDING";
        internal.env.ACTIVATED_KEY_ID = undefined;
        const pendingRegistration = await instance.public_key_registration();
        internal.env.AUTHORITY_MODE = "ACTIVE";
        internal.env.ACTIVATED_KEY_ID = pendingRegistration.key_id;
        return pendingRegistration;
      },
    );
    expect(afterEvictionRegistration.key_id).toBe(registration.key_id);
    expect(afterEvictionRegistration.public_key_base64).toBe(
      registration.public_key_base64,
    );

    const recovered = await stub.recover_issue({
      ...request,
      operation: "recover_issue",
    });
    expect(recovered).toMatchObject({
      operation_id: operationId,
      state: "FINALIZED",
      replayed: true,
    });
    expect(recovered.receipt_digest).toBe(issued.receipt_digest);
    expect(recovered.receipt.digests).toEqual(
      JSON.parse(pending.envelope_json!),
    );

    const publicKey = await crypto.subtle.importKey(
      "raw",
      decodeBase64(registration.public_key_base64),
      { name: "Ed25519" },
      false,
      ["verify"],
    );
    const signature = decodeBase64(
      recovered.receipt.digests.signature.replace(/^ed25519:/, ""),
    );
    expect(await crypto.subtle.verify(
      "Ed25519",
      publicKey,
      signature,
      decodeBase64(recovered.receipt.digests.signed_body_b64),
    )).toBe(true);
    const signedClaims = JSON.parse(
      new TextDecoder().decode(
        decodeBase64(recovered.receipt.digests.signed_body_b64),
      ),
    ) as Record<string, unknown>;
    expect(signedClaims).toMatchObject({
      version: "signed-receipt-claims/v3",
      environment: "production",
      authority_instance_digest: await authorityInstanceDigest("production"),
    });
    expect(recovered.receipt.digests.environment).toBe("production");
    expect(recovered.receipt.digests.authority_instance_digest).toBe(
      await authorityInstanceDigest("production"),
    );

    const replay = await stub.issue_for_segment(request);
    expect(replay.replayed).toBe(true);
    expect(replay.receipt_digest).toBe(recovered.receipt_digest);
    expect(replay.receipt).toEqual(recovered.receipt);
  });

  it("rejects a finalized replay whose lifecycle-start event is absent", async () => {
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    const replayRequest = {
      ...request,
      request_nonce: "c".repeat(64),
    };
    const issued = await stub.issue_for_segment(replayRequest);
    await runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec("DROP TRIGGER authority_events_no_delete");
      state.storage.sql.exec(
        `DELETE FROM authority_events
          WHERE operation_id=? AND event_type='COLLECTION_STARTED'`,
        issued.operation_id,
      );
    });
    await expect(runInDurableObject(
      stub,
      (instance) => instance.recover_issue({
        ...replayRequest,
        operation: "recover_issue",
      }),
    )).rejects.toThrow("required event is absent");
    expect(await runInDurableObject(stub, async (_instance, state) =>
      state.storage.sql.exec<{ count: number }>(
        "SELECT COUNT(*) AS count FROM authority_events",
      ).one().count
    )).toBe(4);
  });

  it("shares canonical environment/resource authority digests with verifiers", async () => {
    expect(await authorityInstanceDigest("production")).toBe(
      "sha256:a63f439bbf478ce25795ed2c80ed6e88ddcd344a4c8538713a20410ac58b8f8c",
    );
    expect(await authorityInstanceDigest("staging")).toBe(
      "sha256:0fa133cf345bdd1f979beebb18e3873fbad88ac7631fc7d5b07ffaca34e68ac7",
    );
  });

  it("resumes the same COLLECTING operation after a pre-sign D1 failure", async () => {
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    const interruptedRequest = {
      ...request,
      request_nonce: "1".repeat(64),
    };
    const operationId = await canonicalDigest(interruptedRequest);
    await runtimeEnv.DB.prepare(
      `CREATE TRIGGER inject_receipt_pre_sign_failure
       BEFORE UPDATE OF state ON receipt_authority_operations
       WHEN OLD.state='COLLECTING' AND NEW.state='STRUCTURED_COMMITTED'
       BEGIN
         SELECT RAISE(ABORT, 'injected receipt pre-sign failure');
       END`,
    ).run();

    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment(interruptedRequest)
    )).rejects.toThrow("injected receipt pre-sign failure");
    const durableState = await runInDurableObject(stub, async (_instance, state) =>
      state.storage.sql.exec<{
        state: string;
        claims_json: string | null;
        envelope_json: string | null;
        created_at: string;
      }>(
        `SELECT state,claims_json,envelope_json,created_at
           FROM authority_operations WHERE operation_id=?`,
        operationId,
      ).one()
    );
    expect(durableState).toMatchObject({
      state: "COLLECTING",
      claims_json: null,
      envelope_json: null,
    });
    expect(await runtimeEnv.DB.prepare(
      `SELECT state FROM receipt_authority_operations WHERE operation_id=?`,
    ).bind(operationId).first()).toEqual({ state: "COLLECTING" });
    expect(await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS count FROM receipt_product_materializations
        WHERE operation_id=?`,
    ).bind(operationId).first<{ count: number }>()).toEqual({ count: 1 });

    await runtimeEnv.DB.prepare(
      "DROP TRIGGER inject_receipt_pre_sign_failure",
    ).run();
    const recovered = await stub.recover_issue({
      ...interruptedRequest,
      operation: "recover_issue",
    });
    expect(recovered).toMatchObject({
      operation_id: operationId,
      state: "FINALIZED",
      replayed: true,
    });
    expect(await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS count FROM receipt_product_materializations
        WHERE operation_id=?`,
    ).bind(operationId).first<{ count: number }>()).toEqual({ count: 1 });
    expect(await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS count FROM collection_receipts WHERE run_id=(
         SELECT run_id FROM receipt_authority_operations WHERE operation_id=?
       )`,
    ).bind(operationId).first<{ count: number }>()).toEqual({ count: 1 });
  });

  it("recovery reuses the same immutable official calendar capture", async () => {
    const acquisitionCalls = installMasterCalendarUpstream();
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    const interruptedRequest = {
      ...request,
      dataset_id: "equities_master",
      request_nonce: "a".repeat(63) + "1",
    };
    const operationId = await canonicalDigest(interruptedRequest);
    await runtimeEnv.DB.prepare(
      `CREATE TRIGGER inject_master_pre_sign_failure
       BEFORE UPDATE OF state ON receipt_authority_operations
       WHEN OLD.state='COLLECTING' AND NEW.state='STRUCTURED_COMMITTED'
       BEGIN
         SELECT RAISE(ABORT, 'injected master pre-sign failure');
       END`,
    ).run();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment(interruptedRequest)
    )).rejects.toThrow("injected master pre-sign failure");
    expect(acquisitionCalls()).toBe(3);
    const prefix =
      `raw/receipt-authority/production/equities_master/2024-02/${operationId.slice(7)}/`;
    const before = await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.list({ prefix });
    const calendarKeys = before.objects
      .map((object) => object.key)
      .filter((key) => key.endsWith("/official-calendar.json"));
    expect(calendarKeys).toHaveLength(1);
    const captureStateKey = before.objects
      .map((object) => object.key)
      .find((key) => key.endsWith("/capture-state.json"));
    expect(captureStateKey).toBeDefined();
    const captureStateObject = await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.get(
      captureStateKey!,
    );
    expect(captureStateObject).not.toBeNull();
    const captureState = JSON.parse(
      await captureStateObject!.text(),
    ) as { capture: Capture };
    const calendarDescriptor = capturedOfficialCalendarDescriptor(
      captureState.capture.officialCalendarEvidence,
    );
    expect(calendarDescriptor).toMatchObject({ raw_path: calendarKeys[0] });
    const expectedCalendarEvidenceDigest = await canonicalDigest(
      calendarDescriptor!,
    );

    await runtimeEnv.DB.prepare(
      "DROP TRIGGER inject_master_pre_sign_failure",
    ).run();
    await evictDurableObject(stub);
    globalThis.fetch = (async () => {
      throw new Error("recovery must not reacquire official calendar evidence");
    }) as typeof fetch;
    const recovered = await stub.recover_issue({
      ...interruptedRequest,
      operation: "recover_issue",
    });
    expect(recovered).toMatchObject({
      operation_id: operationId,
      state: "FINALIZED",
      replayed: true,
    });
    expect(
      recovered.receipt.digests.extra_digests.official_calendar_evidence_digest,
    ).toBe(expectedCalendarEvidenceDigest);
    const after = await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.list({ prefix });
    expect(after.objects.map((object) => object.key).sort()).toEqual(
      before.objects.map((object) => object.key).sort(),
    );
    expect(acquisitionCalls()).toBe(3);
  });

  it("fails closed after eviction when the anchored capture manifest disappeared", async () => {
    installAuthorityAcquisition();
    const interruptedRequest = {
      ...request,
      request_nonce: "c".repeat(64),
    };
    const interrupted = await interruptAfterDurableCapture(interruptedRequest);
    await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.delete(
      interrupted.state.capture.rawManifestKey,
    );
    await evictDurableObject(interrupted.stub);
    globalThis.fetch = (async () => {
      throw new Error("recovery must not reacquire after a committed capture");
    }) as typeof fetch;
    await expect(runInDurableObject(interrupted.stub, (instance) =>
      instance.recover_issue({
        ...interruptedRequest,
        operation: "recover_issue",
      })
    )).rejects.toThrow("immutable capture manifest disappeared");
    expect(await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS count FROM collection_receipts",
    ).first<{ count: number }>()).toEqual({ count: 0 });
  });

  it("rejects a changed capture manifest even when its key remains present", async () => {
    installAuthorityAcquisition();
    const interrupted = await interruptAfterDurableCapture({
      ...request,
      request_nonce: "d".repeat(64),
    });
    const manifestKey = interrupted.state.capture.rawManifestKey;
    await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.delete(manifestKey);
    await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.put(
      manifestKey,
      canonicalJson({ substituted: true }),
    );
    await expect(loadCaptureState(runtimeEnv, interrupted.context)).rejects.toThrow(
      "immutable capture manifest digest differs",
    );
  });

  it("rejects a changed raw page during durable reproof", async () => {
    installAuthorityAcquisition();
    const interrupted = await interruptAfterDurableCapture({
      ...request,
      request_nonce: "0".repeat(63) + "6",
    });
    const rawKey = interrupted.state.capture.pages[0]!.key;
    await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.delete(rawKey);
    await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.put(
      rawKey,
      '{"data":[{"Date":"2024-02-01","Open":999,"Close":2}],"pagination_key":null}',
    );
    await expect(loadCaptureState(runtimeEnv, interrupted.context)).rejects.toThrow(
      "immutable raw page changed after capture",
    );
  });

  it("rejects changed official-calendar bytes during durable reproof", async () => {
    installMasterCalendarUpstream();
    installAuthorityAcquisition();
    const interrupted = await interruptAfterDurableCapture({
      ...request,
      dataset_id: "equities_master",
      request_nonce: "0".repeat(63) + "7",
    });
    const calendar = interrupted.state.capture.officialCalendarEvidence;
    if (calendar === null) throw new Error("test official calendar missing");
    await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.delete(calendar.key);
    await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.put(calendar.key, '{"data":[]}');
    await expect(loadCaptureState(runtimeEnv, interrupted.context)).rejects.toThrow(
      "immutable official calendar changed after capture",
    );
  });

  it("uses a rollback-incompatible v2 envelope and rejects legacy flat state", async () => {
    installAuthorityAcquisition();
    const interrupted = await interruptAfterDurableCapture({
      ...request,
      request_nonce: "e".repeat(64),
    });
    expect(legacyFlatCaptureLoaderWouldAccept(interrupted.state)).toBe(false);
    expect(legacyFlatCaptureLoaderWouldAccept(interrupted.state.capture)).toBe(true);

    const flatDigest = await replaceCaptureState(
      interrupted.context.key,
      interrupted.state.capture,
    );
    await expect(loadCaptureState(runtimeEnv, {
      ...interrupted.context,
      expectedDigest: flatDigest,
    })).rejects.toThrow("durable capture state envelope is invalid");
  });

  it("rejects missing deployment metadata and a rollback validator", async () => {
    installAuthorityAcquisition();
    const interrupted = await interruptAfterDurableCapture({
      ...request,
      request_nonce: "f".repeat(64),
    });
    expect(interrupted.state.validator.capture_deployment_version).toBe(
      runtimeEnv.CF_VERSION_METADATA.id,
    );
    await expect(loadCaptureState({
      ...runtimeEnv,
      CF_VERSION_METADATA: undefined,
    } as unknown as ReceiptAuthorityEnv, interrupted.context)).rejects.toThrow(
      "deployment metadata is unavailable",
    );
    await expect(loadCaptureState({
      ...runtimeEnv,
      CF_VERSION_METADATA: {
        ...runtimeEnv.CF_VERSION_METADATA,
        id: "next-deployment-version",
      },
    } as ReceiptAuthorityEnv, interrupted.context)).resolves.toMatchObject({
      rawManifestKey: interrupted.state.capture.rawManifestKey,
      paginationExhausted: true,
      discoveryExhausted: true,
    });

    const rollback = structuredClone(interrupted.state);
    rollback.validator.digest = "sha256:" + "0".repeat(64);
    const rollbackDigest = await replaceCaptureState(
      interrupted.context.key,
      rollback,
    );
    await expect(loadCaptureState(runtimeEnv, {
      ...interrupted.context,
      expectedDigest: rollbackDigest,
    })).rejects.toThrow("durable capture validator is not current");
  });

  it("rejects capture operation and attempt substitution", async () => {
    installAuthorityAcquisition();
    const interrupted = await interruptAfterDurableCapture({
      ...request,
      request_nonce: "0".repeat(63) + "1",
    });
    await expect(loadCaptureState(runtimeEnv, {
      ...interrupted.context,
      captureAttemptId: "0".repeat(64),
    })).rejects.toThrow("durable capture state authority binding differs");
    const substitutedRequest = {
      ...interrupted.context.request,
      request_nonce: "0".repeat(63) + "2",
    };
    const substitutedOperation = await canonicalDigest(substitutedRequest);
    await expect(loadCaptureState(runtimeEnv, {
      ...interrupted.context,
      operationId: substitutedOperation,
      requestDigest: substitutedOperation,
      request: substitutedRequest,
    })).rejects.toThrow("durable capture state authority binding differs");
  });

  it("reconstructs raw pagination and rejects a forged terminal capture", async () => {
    installTopixContinuationUpstream();
    installAuthorityAcquisition();
    const interrupted = await interruptAfterDurableCapture({
      ...request,
      request_nonce: "0".repeat(63) + "3",
    });
    expect(interrupted.state.capture.pages).toHaveLength(2);
    const forgedState = structuredClone(interrupted.state);
    const first = forgedState.capture.pages[0]!;
    const rawObject = await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.get(first.key);
    if (rawObject === null) throw new Error("test raw page missing");
    const raw = new Uint8Array(await rawObject.arrayBuffer());
    const forged = await forgeSegmentExhaustion(new Response(raw, {
      status: first.responseStatus,
      headers: first.headers,
    }));
    first.headers = Object.fromEntries(forged.headers.entries());
    first.metadata = acquisitionMetadata(forged.headers);
    forgedState.capture.pages = [first];
    forgedState.capture.rawDigest = first.digest;
    forgedState.capture.terminalChainDigest = first.metadata.chain_digest!;
    forgedState.capture.acquisitionExpiresAt =
      first.metadata.acquisition_expires_at!;
    const forgedDigest = await replaceCaptureState(
      interrupted.context.key,
      forgedState,
    );
    await expect(loadCaptureState(runtimeEnv, {
      ...interrupted.context,
      expectedDigest: forgedDigest,
    })).rejects.toThrow("provider continuation cannot terminate the segment");
  });

  it.each([
    ["status", (state: TestCaptureStateV2) => {
      state.capture.pages[0]!.responseStatus = 201;
    }, "failed independent reconciliation"],
    ["headers", (state: TestCaptureStateV2) => {
      delete state.capture.pages[0]!.headers["x-quant-acquisition-chain-digest"];
    }, "response header surface drifted"],
  ])("rejects a persisted response %s substitution", async (
    _label,
    mutate,
    expected,
  ) => {
    installAuthorityAcquisition();
    const interrupted = await interruptAfterDurableCapture({
      ...request,
      request_nonce: _label === "status"
        ? "0".repeat(63) + "4"
        : "0".repeat(63) + "5",
    });
    const changed = structuredClone(interrupted.state);
    mutate(changed);
    const changedDigest = await replaceCaptureState(
      interrupted.context.key,
      changed,
    );
    await expect(loadCaptureState(runtimeEnv, {
      ...interrupted.context,
      expectedDigest: changedDigest,
    })).rejects.toThrow(expected);
  });

  it("branches a new immutable capture attempt after a partial raw failure", async () => {
    installSinglePageUpstream(
      '{"data":[{"Date":"2024-02-01","Open":1,"Close":2}],"pagination_key":"page-2"}',
    );
    let acquisitionCalls = 0;
    const interruptedAcquisition = {
      fetch_governed_page: async (
        input: Parameters<typeof fetchGovernedPage>[0],
      ) => {
        acquisitionCalls += 1;
        if (acquisitionCalls === 2) {
          throw new Error("injected acquisition interruption");
        }
        return fetchGovernedPage(input, acquisitionEnv);
      },
    };
    (runtimeEnv as unknown as Record<string, unknown>).JQUANTS_ACQUISITION =
      interruptedAcquisition;
    const { stub } = await activateRegisteredTestKey();
    const interruptedRequest = {
      ...request,
      request_nonce: "6".repeat(64),
    };
    const operationId = await canonicalDigest(interruptedRequest);
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment(interruptedRequest)
    )).rejects.toThrow("injected acquisition interruption");

    installSinglePageUpstream();
    installAuthorityAcquisition();
    const recovered = await stub.recover_issue({
      ...interruptedRequest,
      operation: "recover_issue",
    });
    expect(recovered).toMatchObject({
      operation_id: operationId,
      state: "FINALIZED",
      replayed: true,
    });
    const attempts = await runInDurableObject(stub, async (_instance, state) =>
      state.storage.sql.exec<{
        attempt_ordinal: number;
        attempt_id: string;
        state: string;
      }>(
        `SELECT attempt_ordinal,attempt_id,state
           FROM authority_capture_attempts WHERE operation_id=?
          ORDER BY attempt_ordinal`,
        operationId,
      ).toArray()
    );
    expect(attempts.map((attempt) => ({
      attempt_ordinal: attempt.attempt_ordinal,
      state: attempt.state,
    }))).toEqual([
      { attempt_ordinal: 1, state: "ABANDONED" },
      { attempt_ordinal: 2, state: "CAPTURED" },
    ]);
    expect(attempts[0]!.attempt_id).not.toBe(attempts[1]!.attempt_id);
    const rawObjects = await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.list({
      prefix: `raw/receipt-authority/production/${request.dataset_id}/${request.segment_id}/${operationId.slice(7)}/`,
    });
    expect(rawObjects.objects.some((object) =>
      object.key.includes(`attempt-${attempts[0]!.attempt_id}/page-000000.json`)
    )).toBe(true);
    expect(rawObjects.objects.some((object) =>
      object.key.includes(`attempt-${attempts[1]!.attempt_id}/manifest.json`)
    )).toBe(true);
  });

  it("re-proves matching existing product rows with their original ingestion time", async () => {
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    const first = await stub.issue_for_segment({
      ...request,
      request_nonce: "2".repeat(64),
    });
    const priorIngestedAt = "2024-03-01T00:00:00.000Z";
    await runtimeEnv.DB.prepare(
      `UPDATE jquants_records SET ingested_at=?
        WHERE source='jquants' AND dataset=?`,
    ).bind(priorIngestedAt, request.dataset_id).run();
    await runtimeEnv.DB.prepare(
      `UPDATE ingestion_change_log SET ingested_at=?,changed_at=?
        WHERE table_name='jquants_records' AND source='jquants' AND dataset=?`,
    ).bind(priorIngestedAt, priorIngestedAt, request.dataset_id).run();

    const reproved = await stub.issue_for_segment({
      ...request,
      request_nonce: "3".repeat(64),
    });
    expect(reproved.state).toBe("FINALIZED");
    const product = await runtimeEnv.DB.prepare(
      `SELECT artifact_body,artifact_digest,row_count
         FROM receipt_product_materializations WHERE operation_id=?`,
    ).bind(reproved.operation_id).first<{
      artifact_body: string;
      artifact_digest: string;
      row_count: number;
    }>();
    expect(product).not.toBeNull();
    expect(product!.artifact_body).toContain(
      `"ingested_at":"${priorIngestedAt}"`,
    );
    expect(product!.artifact_digest).toBe(
      reproved.receipt.digests.structured_digest,
    );
    expect(product!.row_count).toBe(1);
    expect(reproved.receipt.structured_row_count).toBe(1);
    expect(reproved.receipt.digests.structured_digest).not.toBe(
      first.receipt.digests.structured_digest,
    );
    expect(await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS count FROM jquants_records
        WHERE source='jquants' AND dataset=?`,
    ).bind(request.dataset_id).first<{ count: number }>()).toEqual({ count: 1 });
  });

  it("rejects re-proof when an existing product payload differs", async () => {
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    await stub.issue_for_segment({
      ...request,
      request_nonce: "4".repeat(64),
    });
    await runtimeEnv.DB.prepare(
      `UPDATE jquants_records SET payload='{}'
        WHERE source='jquants' AND dataset=?`,
    ).bind(request.dataset_id).run();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        request_nonce: "5".repeat(64),
      })
    )).rejects.toThrow(
      "governed jquants_records fields differ from canonical raw normalization",
    );
    expect(await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS count FROM collection_receipts
        WHERE run_id=(SELECT run_id FROM receipt_authority_operations
          WHERE operation_id=?)`,
    ).bind(await canonicalDigest({
      ...request,
      request_nonce: "5".repeat(64),
    })).first<{ count: number }>()).toEqual({ count: 0 });
  });

  it("exposes no caller-authored claims/result RPC and never signs in PENDING mode", async () => {
    const stub = runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
      "receipt:production",
    );
    for (const method of [
      "begin_operation",
      "recover_operation",
      "append_issued",
      "finalize_committed",
    ]) {
      await runInDurableObject(stub, async (instance) => {
        expect(Object.getOwnPropertyNames(Object.getPrototypeOf(instance)))
          .not.toContain(method);
      });
    }
    let acquisitionCalls = 0;
    (runtimeEnv as unknown as Record<string, unknown>).JQUANTS_ACQUISITION = {
      fetch_governed_page: async () => {
        acquisitionCalls += 1;
        throw new Error("PENDING authority reached acquisition");
      },
    };
    await runInDurableObject(stub, async (instance) => {
      (instance as unknown as { env: ReceiptAuthorityEnv }).env.AUTHORITY_MODE =
        "PENDING";
    });
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        request_nonce: "b".repeat(64),
      })
    )).rejects.toThrow("PENDING activation");
    const receiptCount = await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS count FROM collection_receipts",
    ).first<{ count: number }>();
    expect(receiptCount?.count).toBe(0);
    expect(acquisitionCalls).toBe(0);
    expect((await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.list()).objects).toEqual([]);
    await runInDurableObject(stub, async (_instance, state) => {
      expect(state.storage.sql.exec<{ count: number }>(
        "SELECT COUNT(*) AS count FROM authority_operations",
      ).one().count).toBe(0);
      expect(state.storage.sql.exec<{ count: number }>(
        "SELECT COUNT(*) AS count FROM authority_events",
      ).one().count).toBe(0);
    });
    expect(await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS count FROM receipt_authority_requests",
    ).first<{ count: number }>()).toEqual({ count: 0 });

    await runInDurableObject(stub, async (instance) => {
      (instance as unknown as { env: ReceiptAuthorityEnv }).env.AUTHORITY_MODE =
        "ACTIVE_TEST" as never;
    });
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        request_nonce: "d".repeat(64),
      })
    )).rejects.toThrow("PENDING activation");

    await expect(runInDurableObject(stub, (instance) =>
      instance.recover_issue({
        ...request,
        operation: "recover_issue",
        request_nonce: "a".repeat(64),
      })
    )).rejects.toThrow("PENDING activation");
  });

  it("rejects a forged terminal header while immutable raw has a provider cursor", async () => {
    installSinglePageUpstream('{"data":[],"pagination_key":"page-2"}');
    installAuthorityAcquisition(forgeSegmentExhaustion);
    const { stub } = await activateRegisteredTestKey();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        request_nonce: "e".repeat(64),
      })
    )).rejects.toThrow("provider continuation cannot terminate the segment");
  });

  it("rejects a forged terminal header before the final deterministic slice", async () => {
    installSinglePageUpstream('{"data":[],"pagination_key":null}');
    installAuthorityAcquisition(forgeSegmentExhaustion);
    const { stub } = await activateRegisteredTestKey();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        dataset_id: "fins_summary",
        request_nonce: "f".repeat(64),
      })
    )).rejects.toThrow("sliced acquisition terminated before the final date");
  });

  it("accepts a normal TOPIX continuation only with null calendar fields", async () => {
    installTopixContinuationUpstream();
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    const issued = await runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        request_nonce: "1".repeat(64),
      })
    );
    expect(issued.receipt).toMatchObject({
      dataset: "indices_bars_daily_topix",
      raw_page_count: 2,
      raw_row_count: 2,
      structured_row_count: 2,
      status: "SUCCESS",
    });
  });

  it("rejects any non-null calendar field on a non-calendar continuation", async () => {
    installTopixContinuationUpstream();
    installAuthorityAcquisition((response) =>
      rewriteContinuationPayload(response, (payload) => {
        payload.official_calendar_raw_body_digest = "sha256:" + "0".repeat(64);
      })
    );
    const { stub } = await activateRegisteredTestKey();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        request_nonce: "5".repeat(64),
      })
    )).rejects.toThrow("unauthorized official calendar");
  });

  it("independently rederives the official-calendar master chain", async () => {
    installMasterCalendarUpstream();
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    const issued = await runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        dataset_id: "equities_master",
        request_nonce: "2".repeat(64),
      })
    );
    expect(issued.receipt).toMatchObject({
      dataset: "equities_master",
      raw_page_count: 2,
      raw_row_count: 2,
      structured_row_count: 2,
      status: "SUCCESS",
    });
    expect(issued.receipt.digests.extra_digests).toMatchObject({
      official_calendar_raw_body_digest: expect.stringMatching(/^sha256:/),
      official_calendar_query_digest: expect.stringMatching(/^sha256:/),
      official_business_dates_digest: expect.stringMatching(/^sha256:/),
      official_calendar_binding_digest: expect.stringMatching(/^sha256:/),
      official_calendar_evidence_digest: expect.stringMatching(/^sha256:/),
    });
  });

  it("accepts a one-business-date terminal master without a continuation", async () => {
    installMasterCalendarUpstream(["2024-02-01"]);
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    const issued = await runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        dataset_id: "equities_master",
        request_nonce: "6".repeat(64),
      })
    );
    expect(issued.receipt).toMatchObject({
      dataset: "equities_master",
      raw_page_count: 1,
      raw_row_count: 1,
      structured_row_count: 1,
      status: "SUCCESS",
    });
  });

  it("rejects a tampered master official-calendar cursor", async () => {
    installMasterCalendarUpstream();
    installAuthorityAcquisition((response) =>
      rewriteContinuationPayload(response, (payload) => {
        payload.official_business_dates = ["2024-02-01", "2024-02-05"];
      })
    );
    const { stub } = await activateRegisteredTestKey();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        dataset_id: "equities_master",
        request_nonce: "3".repeat(64),
      })
    )).rejects.toThrow("official calendar digest chain drifted");
  });

  it("rejects a self-consistent same-segment business-date omission", async () => {
    installMasterCalendarUpstream();
    installAuthorityAcquisition((response) =>
      rewriteContinuationPayload(response, (payload) =>
        replaceCalendarCursorClaims(payload, ["2024-02-01"])
      )
    );
    const { stub } = await activateRegisteredTestKey();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        dataset_id: "equities_master",
        request_nonce: "7".repeat(64),
      })
    )).rejects.toThrow("differs from immutable raw evidence");
  });

  it("rejects official calendar raw body/digest mismatch", async () => {
    installMasterCalendarUpstream();
    installAuthorityAcquisition(async (response) => {
      const body = await response.arrayBuffer();
      const headers = new Headers(response.headers);
      headers.set(
        "x-quant-acquisition-official-calendar-raw-digest",
        "sha256:" + "0".repeat(64),
      );
      return new Response(body, { status: response.status, headers });
    });
    const { stub } = await activateRegisteredTestKey();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        dataset_id: "equities_master",
        request_nonce: "8".repeat(64),
      })
    )).rejects.toThrow("raw evidence body/digest mismatch");
  });

  it("rejects a self-consistent official calendar transplanted across segments", async () => {
    installMasterCalendarUpstream();
    installAuthorityAcquisition((response) =>
      rewriteContinuationPayload(response, async (payload) => {
        const businessDates = ["2024-03-01", "2024-03-04"];
        await replaceCalendarCursorClaims(
          payload, businessDates, "2024-03-01", "2024-03-31",
        );
      })
    );
    const { stub } = await activateRegisteredTestKey();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        dataset_id: "equities_master",
        request_nonce: "4".repeat(64),
      })
    )).rejects.toThrow("official calendar crosses its segment");
  });

  it("rejects an exact-key poisoned preinsert instead of self-digesting it", async () => {
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    await runtimeEnv.DB.prepare(
      `CREATE TRIGGER poison_receipt_structured_row
       AFTER INSERT ON receipt_authority_operations
       BEGIN
         INSERT INTO receipt_authority_structured_rows
         (operation_id,natural_key,source,dataset,event_time,available_at,
          ingested_at,payload,raw_payload,row_digest)
         VALUES (
           NEW.operation_id,'{"Date":"2024-02-01"}','jquants',NEW.dataset,
           '2024-02-01T15:00:00+09:00','2024-02-01T15:00:00+09:00',
           NEW.checked_at,'{}',
           '{"Date":"2024-02-01","Open":1,"Close":2}',
           'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
         );
       END`,
    ).run();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        request_nonce: "7".repeat(64),
      })
    )).rejects.toThrow(
      "persisted structured fields differ from canonical raw normalization",
    );
    expect(await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS count FROM collection_receipts",
    ).first<{ count: number }>()).toEqual({ count: 0 });
  });

  it("rejects a poisoned research product preinsert before signing", async () => {
    installAuthorityAcquisition();
    const { stub } = await activateRegisteredTestKey();
    await runtimeEnv.DB.prepare(
      `CREATE TRIGGER poison_governed_product
       AFTER INSERT ON receipt_authority_operations
       BEGIN
         INSERT INTO jquants_records
         (source,dataset,natural_key,event_time,available_at,ingested_at,payload,raw_payload)
         VALUES ('jquants',NEW.dataset,'{"Date":"2024-02-01"}',
                 '2024-02-01T00:00:00Z','2024-02-01T00:00:00Z',NEW.checked_at,
                 '{}','{"Date":"2024-02-01","Open":1,"Close":2}');
       END`,
    ).run();
    await expect(runInDurableObject(stub, (instance) =>
      instance.issue_for_segment({
        ...request,
        request_nonce: "8".repeat(64),
      })
    )).rejects.toThrow(
      "governed jquants_records fields differ from canonical raw normalization",
    );
    expect(await runtimeEnv.DB.prepare(
      "SELECT COUNT(*) AS count FROM collection_receipts",
    ).first<{ count: number }>()).toEqual({ count: 0 });
  });

  it("makes reconciled rows, committed receipts, and authority history append-only", async () => {
    const { stub } = await activateRegisteredTestKey();
    installAuthorityAcquisition();
    await runtimeEnv.DB.prepare(
      `INSERT INTO ingestion_run_log(ran_at,source,runtime,status,detail)
       VALUES ('2024-01-01T00:00:00Z','jquants','prior-test','SUCCESS','{}')`,
    ).run();
    const result = await stub.issue_for_segment({
      ...request,
      request_nonce: "9".repeat(64),
    });
    const operation = await runtimeEnv.DB.prepare(
      `SELECT run_id FROM receipt_authority_operations WHERE operation_id=?`,
    ).bind(result.operation_id).first<{ run_id: number }>();
    expect(operation).not.toBeNull();
    expect(operation!.run_id).toBeGreaterThan(1);
    expect(await runtimeEnv.DB.prepare(
      `SELECT source,runtime,status,authority_operation_id
         FROM ingestion_run_log WHERE id=?`,
    ).bind(operation!.run_id).first()).toMatchObject({
      source: "jquants",
      runtime: "receipt-evidence-authority",
      status: "SUCCESS",
      authority_operation_id: result.operation_id,
    });
    expect(await runtimeEnv.DB.prepare(
      `SELECT dataset,run_id,page_count,row_count,completeness
         FROM raw_retention_manifests WHERE run_id=?`,
    ).bind(operation!.run_id).first()).toMatchObject({
      dataset: "indices_bars_daily_topix",
      run_id: operation!.run_id,
      page_count: 1,
      row_count: 1,
      completeness: "ACQUIRED",
    });
    const product = await runtimeEnv.DB.prepare(
      `SELECT artifact_key,artifact_digest,row_count,manifest_key
         FROM receipt_product_materializations WHERE run_id=?`,
    ).bind(operation!.run_id).first<{
      artifact_key: string;
      artifact_digest: string;
      row_count: number;
      manifest_key: string;
    }>();
    expect(product).not.toBeNull();
    expect(product!.artifact_digest).toBe(
      result.receipt.digests.structured_digest,
    );
    expect(product!.row_count).toBe(result.receipt.structured_row_count);
    expect(product!.artifact_key).toMatch(
      /^product\/receipt-authority\/production\//,
    );
    expect(product!.manifest_key).toMatch(
      /^product\/receipt-authority\/production\//,
    );
    const artifact = await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.get(
      product!.artifact_key,
    );
    expect(artifact).not.toBeNull();
    expect(await sha256Digest(new Uint8Array(await artifact!.arrayBuffer())))
      .toBe(product!.artifact_digest);
    expect(await runtimeEnv.AUTHORITY_EVIDENCE_BUCKET.get(
      product!.manifest_key,
    )).not.toBeNull();
    expect(await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS count FROM jquants_records
        WHERE source='jquants' AND dataset='indices_bars_daily_topix'`,
    ).first<{ count: number }>()).toEqual({ count: 1 });
    expect(await runtimeEnv.DB.prepare(
      `SELECT COUNT(*) AS count FROM ingestion_change_log
        WHERE table_name='jquants_records'
          AND dataset='indices_bars_daily_topix'`,
    ).first<{ count: number }>()).toEqual({ count: 1 });

    const history = await runInDurableObject(
      stub,
      async (_instance, state) => state.storage.sql.exec<{
        sequence: number;
        operation_id: string;
        event_type: string;
        payload_digest: string;
        prior_event_digest: string | null;
        event_digest: string;
        observed_at: string;
      }>(
        `SELECT sequence,operation_id,event_type,payload_digest,
                prior_event_digest,event_digest,observed_at
           FROM authority_events ORDER BY sequence`,
      ).toArray(),
    );
    expect(history.map((event) => event.event_type)).toEqual([
      "COLLECTION_STARTED",
      "CAPTURE_COMMITTED",
      "CLAIMS_RESERVED",
      "RECEIPT_ISSUED_PENDING_FINALIZE",
      "RECEIPT_FINALIZED",
    ]);
    let priorEventDigest: string | null = null;
    for (let index = 0; index < history.length; index += 1) {
      const event = history[index];
      expect(event.sequence).toBe(index + 1);
      expect(event.prior_event_digest).toBe(priorEventDigest);
      expect(event.event_digest).toBe(await canonicalDigest({
        schema_version: "receipt-authority-event/v1",
        sequence: event.sequence,
        operation_id: event.operation_id,
        event_type: event.event_type,
        payload_digest: event.payload_digest,
        prior_event_digest: event.prior_event_digest,
        observed_at: event.observed_at,
      }));
      priorEventDigest = event.event_digest;
    }

    await expect(runtimeEnv.DB.prepare(
      `UPDATE receipt_authority_structured_rows SET payload='{}'
        WHERE operation_id=?`,
    ).bind(result.operation_id).run()).rejects.toThrow("append-only");
    await expect(runtimeEnv.DB.prepare(
      `DELETE FROM receipt_authority_structured_rows WHERE operation_id=?`,
    ).bind(result.operation_id).run()).rejects.toThrow("append-only");
    await expect(runtimeEnv.DB.prepare(
      `UPDATE receipt_authority_operations SET dataset='substituted'
        WHERE operation_id=?`,
    ).bind(result.operation_id).run()).rejects.toThrow("immutable");
    await expect(runtimeEnv.DB.prepare(
      `DELETE FROM receipt_authority_operations WHERE operation_id=?`,
    ).bind(result.operation_id).run()).rejects.toThrow("append-only");
    await expect(runtimeEnv.DB.prepare(
      `UPDATE collection_receipts SET checked_at='2000-01-01T00:00:00.000Z'
        WHERE run_id=?`,
    ).bind(operation!.run_id).run()).rejects.toThrow("append-only");
    await expect(runtimeEnv.DB.prepare(
      `DELETE FROM collection_receipts WHERE run_id=?`,
    ).bind(operation!.run_id).run()).rejects.toThrow("append-only");

    await expect(runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec(
        "UPDATE authority_events SET event_type='SUBSTITUTED' WHERE sequence=1",
      );
    })).rejects.toThrow("append-only");
    await expect(runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec(
        "DELETE FROM authority_operations WHERE operation_id=?",
        result.operation_id,
      );
    })).rejects.toThrow("append-only");
    await expect(runInDurableObject(stub, async (_instance, state) => {
      state.storage.sql.exec(
        "UPDATE authority_key_metadata SET key_id='substituted' WHERE key_generation=1",
      );
    })).rejects.toThrow("append-only");
  });

  it("authenticates the wrap key, AAD, ciphertext, and key generation", async () => {
    const pair = await crypto.subtle.generateKey(
      { name: "Ed25519" },
      true,
      ["sign", "verify"],
    );
    const secret = "1".repeat(64);
    const aad = '{"authority":"receipt","environment":"production","generation":1}';
    const wrapped = await wrapEd25519PrivateKey({
      privateKey: pair.privateKey,
      wrappingSecret: secret,
      aad,
    });
    const operational = await unwrapEd25519PrivateKey({
      wrapped,
      wrappingSecret: secret,
      aad,
    });
    expect(operational.extractable).toBe(false);
    await expect(crypto.subtle.exportKey("pkcs8", operational)).rejects.toThrow();
    await expect(unwrapEd25519PrivateKey({
      wrapped,
      wrappingSecret: "2".repeat(64),
      aad,
    })).rejects.toThrow("authenticated unwrap");
    await expect(unwrapEd25519PrivateKey({
      wrapped,
      wrappingSecret: secret,
      aad: `${aad}-substituted`,
    })).rejects.toThrow("authenticated unwrap");
    const changed = `${wrapped.wrapped_private_key_base64[0] === "A" ? "B" : "A"}${wrapped.wrapped_private_key_base64.slice(1)}`;
    await expect(unwrapEd25519PrivateKey({
      wrapped: { ...wrapped, wrapped_private_key_base64: changed },
      wrappingSecret: secret,
      aad,
    })).rejects.toThrow("authenticated unwrap");

    const stub = runtimeEnv.RECEIPT_EVIDENCE_AUTHORITY_DO.getByName(
      "receipt:production",
    );
    const first = await runInDurableObject(stub, async (instance) => {
      const internal = instance as unknown as { env: ReceiptAuthorityEnv };
      internal.env.AUTHORITY_MODE = "PENDING";
      internal.env.ACTIVATED_KEY_ID = undefined;
      return instance.public_key_registration();
    });
    (runtimeEnv as unknown as {
      AUTHORITY_MODE: string;
      ACTIVATED_KEY_ID?: string;
      RECEIPT_KEY_GENERATION: string;
    }).AUTHORITY_MODE = "PENDING";
    runtimeEnv.ACTIVATED_KEY_ID = undefined;
    (runtimeEnv as unknown as { RECEIPT_KEY_GENERATION: string })
      .RECEIPT_KEY_GENERATION = "2";
    await evictDurableObject(stub);
    const rotated = await runInDurableObject(
      stub,
      (instance) => instance.public_key_registration(),
    );
    expect(rotated.key_generation).toBe(2);
    expect(rotated.key_id).not.toBe(first.key_id);
    await evictDurableObject(stub);
    const repeated = await runInDurableObject(
      stub,
      (instance) => instance.public_key_registration(),
    );
    expect(repeated).toEqual(rotated);
    const keyRows = await runInDurableObject(stub, async (_instance, state) =>
      state.storage.sql.exec<{ key_generation: number }>(
        "SELECT key_generation FROM authority_key_metadata ORDER BY key_generation",
      ).toArray()
    );
    expect(keyRows.map((row) => row.key_generation)).toEqual([1, 2]);
  });
});
