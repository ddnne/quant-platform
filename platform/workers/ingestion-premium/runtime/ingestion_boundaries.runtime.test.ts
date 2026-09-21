import { env } from "cloudflare:workers";
import { applyD1Migrations, createExecutionContext, reset } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, inject, vi } from "vitest";
import worker, { type Env } from "../src/index";
import { NATURAL_KEY_MIGRATION_ID, rebuildNaturalKeysV2 } from "../src/natural_key_migration";
import {
  runValuationBackfillTick,
  VALUATION_BACKFILL_KEY,
  type ValuationIngest,
} from "../src/valuation_backfill";
import {
  EXACT_FIVE_ACQUISITION_KEY,
  observeExactFiveReceipt,
  runExactFiveAcquisitionTick,
  type ExactFiveIngest,
} from "../src/exact_five_acquisition_tick";
import { PENDING_REGISTRATION_KEY } from "../src/pending_registration_tick";
import {
  COMPILED_CLOSURE_DIGEST,
  COMPILED_PROFILE_DIGEST,
  COMPILED_PROFILE_ID,
} from "../src/receipt_product_input";
import {
  base64ToBytes,
  canonicalDigest,
  canonicalJson,
  sha256Digest,
} from "../../receipt-evidence-authority/src/canonical";
import { sha256HexFromString } from "../src/sha256";
import {
  closedReceiptVerifyRegistry,
  PINNED_RECEIPT_REGISTRY_SCOPE,
} from "../src/ops_projection_policy";

const migrations = inject<Array<{ name: string; queries: string[] }>>("premiumD1Migrations");

// Test-only cast: generated harness env omits unused receipt-audit RPC secret refinements on Env.
function runtimeEnv(overrides: Partial<Env> = {}): Env {
  return {
    ...env,
    JQUANTS_API_KEY: "test-jq-key",
    INGESTION_RUN_TOKEN: "test-ingestion-run-token",
    RECEIPT_AUTHORITY_OPERATION_MODE: "PENDING",
    RECEIPT_AUTHORITY_ENVIRONMENT: "staging",
    ...overrides,
  } as Env;
}

function fetchUrl(input: unknown): URL {
  return new URL(input instanceof Request ? input.url : String(input));
}

function stubVendor(path: string, query: Record<string, string>, data: unknown[]) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = fetchUrl(input);
    const queryOk = Object.entries(query).every(([key, value]) => url.searchParams.get(key) === value);
    if (url.origin !== "https://api.jquants.com" || url.pathname !== path || !queryOk) {
      throw new Error(`unexpected fetch ${url.href}`);
    }
    return Promise.resolve(new Response(JSON.stringify({ data }), { status: 200 }));
  });
}

function scheduledAt(at = "2026-09-12T00:00:00.000Z"): ScheduledController {
  return {
    scheduledTime: Date.parse(at),
    cron: "* * * * *",
    noRetry() {},
  };
}

function canaryDoc(overrides: Record<string, unknown> = {}) {
  return {
    schema: "equities-valuation-backfill/v1",
    dataset: "equities_valuation",
    job_id: "canary:2026-09-11:2026-09-11",
    kind: "canary",
    start: "2026-09-11",
    end: "2026-09-11",
    next: "2026-09-11",
    attempts: 0,
    lease: null,
    last: null,
    ...overrides,
  };
}

const CALLER_SHA = "1".repeat(40);

function exactFiveDoc(overrides: Record<string, unknown> = {}) {
  return {
    schema: "exact-five-compiled-acquisition/v1",
    profile_id: COMPILED_PROFILE_ID,
    profile_digest: COMPILED_PROFILE_DIGEST,
    dependency_closure_digest: COMPILED_CLOSURE_DIGEST,
    jobs: [{ dataset: "markets_calendar", segment_id: "2023-01" }],
    cursor: 0,
    attempts: 0,
    lease: null,
    last: null,
    ...overrides,
  };
}

function requestedRegistrationDoc(overrides: Record<string, unknown> = {}) {
  return {
    schema: "receipt-pending-registration/v1",
    environment: "staging",
    state: "requested",
    attempts: 0,
    lease: null,
    last: null,
    ...overrides,
  };
}

async function publicRegistration(): Promise<Record<string, unknown>> {
  const publicKeyBase64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
  const keyDigest = await sha256Digest(base64ToBytes(publicKeyBase64));
  const keyId = `receipt-staging-${keyDigest.slice(7, 23)}`;
  const operationBody = {
    schema_version: "receipt-registration-operation/v1",
    authority: "receipt-evidence-authority",
    action: "public_key_registration",
    environment: "staging",
    authority_resource_digest: `sha256:${"a".repeat(64)}`,
    deployment_source_sha: CALLER_SHA,
    authority_worker_version_id: "10000000-0000-4000-8000-000000000002",
    authority_worker_version_tag: `rp-s-r-${CALLER_SHA}`,
    key_id: keyId,
    key_generation: 1,
    generated_at: "2026-08-27T08:00:00.000Z",
  } as const;
  const body = {
    schema_version: "receipt-public-key-registration/v1" as const,
    purpose: "receipt_verification" as const,
    environment: "staging" as const,
    authority_instance_digest: `sha256:${"a".repeat(64)}`,
    authority_resource_digest: `sha256:${"a".repeat(64)}`,
    authority_status: "PENDING" as const,
    action: "public_key_registration" as const,
    deployment_source_sha: CALLER_SHA,
    authority_worker_version_id: "10000000-0000-4000-8000-000000000002",
    authority_worker_version_tag: `rp-s-r-${CALLER_SHA}`,
    operation_binding_digest: await canonicalDigest(operationBody),
    key_id: keyId,
    key_generation: 1,
    algorithm: "Ed25519" as const,
    public_key_base64: publicKeyBase64,
    private_key_extractable: false as const,
    status: "pending" as const,
    generated_at: "2026-08-27T08:00:00.000Z",
  };
  return { ...body, registration_digest: await canonicalDigest(body) };
}

function registrationEnv(overrides: Partial<Env> = {}): Env {
  return runtimeEnv({
    CF_VERSION_METADATA: {
      id: "10000000-0000-4000-8000-000000000003",
      tag: `rp-s-c-${CALLER_SHA}`,
      timestamp: "2026-08-27T08:00:00.000Z",
    },
    RECEIPT_EVIDENCE_AUTHORITY: {
      public_key_registration: vi.fn(publicRegistration),
      issue_for_segment: vi.fn(),
      recover_issue: vi.fn(),
      begin_audit_recovery_canary: vi.fn(),
      recover_audit_recovery_canary: vi.fn(),
    },
    ...overrides,
  });
}

function cronIngest(testEnv: Env): ValuationIngest {
  return async (opts, signal) => {
    const res = await worker.fetch(
      new Request(
        `https://ingestion-premium.test/v1/run?dataset=${opts.dataset}&from=${opts.from}&to=${opts.to}`,
        {
          method: "POST",
          headers: { "X-Ingestion-Token": String(testEnv.INGESTION_RUN_TOKEN) },
          signal,
        },
      ),
      testEnv,
    );
    const body = (await res.json()) as {
      summary: { status: "pass" | "fail" | "partial"; datasetCount: number; rowsInserted: number };
    };
    return body.summary;
  };
}

async function postRun(testEnv: Env, dataset: string, from: string, to: string): Promise<Response> {
  return worker.fetch(
    new Request(`https://ingestion-premium.test/v1/run?dataset=${dataset}&from=${from}&to=${to}`, {
      method: "POST",
      headers: { "X-Ingestion-Token": String(testEnv.INGESTION_RUN_TOKEN) },
    }),
    testEnv,
  );
}

describe("ingestion-premium workerd ingestion boundaries", () => {
  beforeEach(async () => {
    await applyD1Migrations(env.DB, migrations);
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await reset();
  });

  it.each([
    { title: "PENDING control row", missing: false, message: "migration is PENDING" },
    { title: "missing control row", missing: true, message: "schema is not installed" },
  ])("rejects $title before vendor fetch without D1/R2 writes", async ({ missing, message }) => {
    if (missing) {
      await env.DB.prepare("DELETE FROM natural_key_migrations WHERE migration_id = ?")
        .bind(NATURAL_KEY_MIGRATION_ID)
        .run();
    }
    const testEnv = runtimeEnv();
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      throw new Error(`unexpected fetch ${fetchUrl(input).href}`);
    });
    await expect(postRun(testEnv, "equities_bars_daily", "2024-06-03", "2024-06-03")).rejects.toThrow(
      message,
    );
    expect(spy).not.toHaveBeenCalled();
    expect((await env.DB.prepare("SELECT id, status FROM ingestion_run_log").all()).results).toEqual([]);
    expect((await env.DB.prepare("SELECT dataset, natural_key FROM jquants_records").all()).results).toEqual(
      [],
    );
    expect((await env.DB.prepare("SELECT expected_items, status FROM collection_receipts").all()).results).toEqual(
      [],
    );
    expect((await env.RAW_BUCKET.list()).objects).toHaveLength(0);
    expect((await env.STRUCTURED_BUCKET.list()).objects).toHaveLength(0);
  });

  it("persists canonical daily identity and session_close available_at after rebuild", async () => {
    expect((await rebuildNaturalKeysV2(env.DB)).state).toBe("READY");
    const testEnv = runtimeEnv({ ALLOW_D1_STRUCTURED_DATASETS: "equities_bars_daily" });
    const vendorRow = {
      Code: "8697",
      Date: "2024-06-03",
      Close: 100,
      available_at: "1900-01-01T00:00:00Z",
    };
    stubVendor("/v2/equities/bars/daily", { date: "2024-06-03" }, [vendorRow]);
    const res = await postRun(testEnv, "equities_bars_daily", "2024-06-03", "2024-06-03");
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean; summary: { passed: number; rowsInserted: number } };
    expect(body.ok).toBe(true);
    expect(body.summary.passed).toBe(1);
    expect(body.summary.rowsInserted).toBe(1);
    const stored = await env.DB.prepare(
      "SELECT natural_key, available_at, raw_payload FROM jquants_records WHERE dataset = ?",
    )
      .bind("equities_bars_daily")
      .first<{ natural_key: string; available_at: string; raw_payload: string }>();
    expect(stored?.natural_key).toBe('{"Code":"8697","Date":"2024-06-03"}');
    expect(stored?.available_at).toBe("2024-06-03T15:00:00+09:00");
    expect(JSON.parse(stored!.raw_payload).available_at).toBe("1900-01-01T00:00:00Z");
  });

  it("runs one canonical-month calendar range as UNKNOWN coverage and unsigned zero-row SUCCESS", async () => {
    expect((await rebuildNaturalKeysV2(env.DB)).state).toBe("READY");
    const testEnv = runtimeEnv();
    const spy = stubVendor("/v2/markets/calendar", { from: "2024-06-01", to: "2024-06-30" }, []);
    const res = await postRun(testEnv, "markets_calendar", "2024-06-01", "2024-06-30");
    expect(res.status).toBe(200);
    expect(((await res.json()) as { ok: boolean }).ok).toBe(true);
    expect(spy).toHaveBeenCalledTimes(1);
    const vendor = fetchUrl(spy.mock.calls[0]![0]);
    expect(vendor.origin).toBe("https://api.jquants.com");
    expect(vendor.pathname).toBe("/v2/markets/calendar");
    expect(vendor.searchParams.get("from")).toBe("2024-06-01");
    expect(vendor.searchParams.get("to")).toBe("2024-06-30");
    const segments = await env.DB.prepare(
      "SELECT status, expected_items, detail_json, receipt_run_id FROM coverage_segments",
    ).all<{
      status: string;
      expected_items: number;
      detail_json: string;
      receipt_run_id: number | null;
    }>();
    expect(segments.results).toHaveLength(1);
    const segment = segments.results[0]!;
    expect(segment?.status).toBe("UNKNOWN");
    expect(segment?.expected_items).toBe(1);
    expect(segment?.receipt_run_id).toBeNull();
    const detail = JSON.parse(segment!.detail_json) as {
      expected_item_unit: string;
      query_units: number | null;
    };
    expect(detail.expected_item_unit).toBe("source_query");
    expect(detail.query_units).toBe(1);
    const receipts = await env.DB.prepare(
      "SELECT status, expected_items, raw_row_count, structured_row_count, digests_json FROM collection_receipts",
    ).all<{
      status: string;
      expected_items: number | null;
      raw_row_count: number;
      structured_row_count: number;
      digests_json: string;
    }>();
    expect(receipts.results).toHaveLength(1);
    const receipt = receipts.results[0]!;
    expect(receipt?.status).toBe("SUCCESS");
    expect(receipt?.expected_items).toBe(1);
    expect(receipt?.raw_row_count).toBe(0);
    expect(receipt?.structured_row_count).toBe(0);
    expect(JSON.parse(receipt!.digests_json)).toMatchObject({
      eligibility: "RECOVERED_RAW_ONLY",
      issuer_class: "UnsignedIngestionAudit",
    });
  });

  it.each([
    {
      dataset: "fins_summary",
      from: "2024-07-15",
      to: "2024-07-15",
      path: "/v2/fins/summary",
      query: { date: "2024-07-15" },
      expectedItems: null as number | null,
      frequency: "event_driven" as const,
      unit: "source_event" as const,
    },
    {
      dataset: "markets_calendar",
      from: "2024-06-03",
      to: "2024-06-03",
      path: "/v2/markets/calendar",
      query: { from: "2024-06-03", to: "2024-06-03" },
      expectedItems: 1 as number | null,
      frequency: undefined,
      unit: undefined,
    },
  ])("omits coverage_segments for noncanonical $dataset ($from)", async (tc) => {
    expect((await rebuildNaturalKeysV2(env.DB)).state).toBe("READY");
    const testEnv = runtimeEnv();
    stubVendor(tc.path, tc.query, []);
    const res = await postRun(testEnv, tc.dataset, tc.from, tc.to);
    expect(res.status).toBe(200);
    expect(((await res.json()) as { ok: boolean }).ok).toBe(true);
    expect((await env.DB.prepare("SELECT dataset FROM coverage_segments").all()).results).toEqual([]);
    const receipts = await env.DB.prepare(
      "SELECT expected_items, expected_scope FROM collection_receipts",
    ).all<{ expected_items: number | null; expected_scope: string }>();
    expect(receipts.results).toHaveLength(1);
    const receipt = receipts.results[0]!;
    expect(receipt?.expected_items).toBe(tc.expectedItems);
    if (tc.frequency && tc.unit) {
      const scope = JSON.parse(receipt!.expected_scope) as {
        expected_frequency: string;
        expected_item_unit: string;
      };
      expect(scope.expected_frequency).toBe(tc.frequency);
      expect(scope.expected_item_unit).toBe(tc.unit);
    }
  });

  it("absent or invalid valuation job does not fall through to Premium cron", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      throw new Error(`unexpected fetch ${fetchUrl(input).href}`);
    });
    const testEnv = runtimeEnv();
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(spy).not.toHaveBeenCalled();
    expect((await env.DB.prepare("SELECT id FROM ingestion_run_log").all()).results).toEqual([]);
    await env.STRUCTURED_BUCKET.put(
      VALUATION_BACKFILL_KEY,
      JSON.stringify(canaryDoc({
        job_id: "canary:2026-09-31:2026-09-31",
        start: "2026-09-31",
        end: "2026-09-31",
        next: "2026-09-31",
      })),
    );
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(spy).not.toHaveBeenCalled();
    expect((await env.DB.prepare("SELECT id FROM ingestion_run_log").all()).results).toEqual([]);
    expect((await env.RAW_BUCKET.list()).objects).toHaveLength(0);
  });

  it("rejects one-day, invalid-month, wrong-profile exact-five jobs and READY-declared registration", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      throw new Error(`unexpected fetch ${fetchUrl(input).href}`);
    });
    const testEnv = registrationEnv({
      READY_DECLARED: "true" as unknown as "false",
    });
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        jobs: [{ dataset: "markets_calendar", from: "2023-01-04", to: "2023-01-04" }],
      })),
    );
    await env.STRUCTURED_BUCKET.put(
      PENDING_REGISTRATION_KEY,
      JSON.stringify(requestedRegistrationDoc()),
    );
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(spy).not.toHaveBeenCalled();
    expect(testEnv.RECEIPT_EVIDENCE_AUTHORITY.public_key_registration)
      .not.toHaveBeenCalled();
    expect((await env.DB.prepare("SELECT id FROM ingestion_run_log").all()).results).toEqual([]);

    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        jobs: [{ dataset: "markets_calendar", segment_id: "2022-13" }],
      })),
    );
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(spy).not.toHaveBeenCalled();

    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        profile_digest: `sha256:${"0".repeat(64)}`,
        jobs: [{ dataset: "markets_calendar", segment_id: "2023-01" }],
      })),
    );
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(spy).not.toHaveBeenCalled();
    expect((await env.DB.prepare("SELECT id FROM ingestion_run_log").all()).results).toEqual([]);
  });

  it("staging ACTIVE scheduled invokes AUDIT_ONLY canary and not receipt issue", async () => {
    const begin = vi.fn(async () => {
      throw new Error("audit begin invoked");
    });
    const issue = vi.fn();
    const recover = vi.fn();
    const testEnv = runtimeEnv({
      RECEIPT_AUTHORITY_OPERATION_MODE: "ACTIVE",
      CF_VERSION_METADATA: {
        id: "10000000-0000-4000-8000-000000000003",
        tag: `ra-s-c-${CALLER_SHA}`,
        timestamp: "2026-08-28T00:00:00.000Z",
      },
      RECEIPT_EVIDENCE_AUTHORITY: {
        public_key_registration: vi.fn(),
        issue_for_segment: issue,
        recover_issue: recover,
        begin_audit_recovery_canary: begin,
        recover_audit_recovery_canary: vi.fn(),
      },
    });
    await expect(
      worker.scheduled(scheduledAt(), testEnv, createExecutionContext()),
    ).rejects.toThrow("audit begin invoked");
    expect(begin).toHaveBeenCalledOnce();
    expect(issue).not.toHaveBeenCalled();
    expect(recover).not.toHaveBeenCalled();
  });

  it("scheduled requested registration persists the full public envelope once", async () => {
    const testEnv = registrationEnv();
    await env.STRUCTURED_BUCKET.put(
      PENDING_REGISTRATION_KEY,
      JSON.stringify(requestedRegistrationDoc()),
    );
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(testEnv.RECEIPT_EVIDENCE_AUTHORITY.public_key_registration)
      .toHaveBeenCalledOnce();
    const stored = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(PENDING_REGISTRATION_KEY))!.text(),
    ) as {
      state: string;
      last: {
        schema_version: string;
        registration: Record<string, unknown> & { registration_digest: string };
      };
    };
    expect(stored.state).toBe("completed");
    expect(stored.last.schema_version).toBe("receipt-operator-registration/v1");
    expect(stored.last.registration).toMatchObject({
      algorithm: "Ed25519",
      environment: "staging",
      authority_status: "PENDING",
      key_generation: 1,
      private_key_extractable: false,
    });
    expect(stored.last.registration.authority_instance_digest).toMatch(/^sha256:[0-9a-f]{64}$/);
    const { registration_digest: supplied, ...body } = stored.last.registration;
    expect(await canonicalDigest(body)).toBe(supplied);
    expect(JSON.stringify(stored.last)).not.toMatch(/private_key_pkcs8|wrapped_key/);
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(testEnv.RECEIPT_EVIDENCE_AUTHORITY.public_key_registration)
      .toHaveBeenCalledOnce();
  });

  it("scheduled exact-five runs one compiled month then is idle, and skips while valuation is leased", async () => {
    expect((await rebuildNaturalKeysV2(env.DB)).state).toBe("READY");
    const testEnv = runtimeEnv();
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        jobs: [
          { dataset: "markets_calendar", segment_id: "2022-12" },
          { dataset: "markets_calendar", segment_id: "2023-01" },
        ],
      })),
    );
    // Scheduling/lease behavior does not require 31 rate-limited daily fetches.
    const spy = stubVendor("/v2/markets/calendar", { from: "2022-12-01", to: "2022-12-31" }, []);
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(spy.mock.calls.length).toBeGreaterThan(0);
    const vendor = fetchUrl(spy.mock.calls[0]![0]);
    expect(vendor.searchParams.get("from")).toBe("2022-12-01");
    const coverage = await env.DB.prepare(
      "SELECT dataset, segment_id, status FROM coverage_segments",
    ).all<{ dataset: string; segment_id: string; status: string }>();
    expect(coverage.results).toEqual([
      { dataset: "markets_calendar", segment_id: "2022-12", status: "UNKNOWN" },
    ]);
    const vendorCalls = spy.mock.calls.length;
    let control = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number; last: { from: string; to: string; status: string } };
    for (let i = 0; i < 12 && control.last?.status !== "pass"; i++) {
      await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
      control = JSON.parse(
        await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
      );
    }
    expect(spy.mock.calls.length).toBe(vendorCalls);
    expect(control.cursor).toBe(1);
    expect(control.last).toMatchObject({
      from: "2022-12-01",
      to: "2022-12-31",
      status: "pass",
    });

    const calls = spy.mock.calls.length;
    spy.mockImplementation((input) => {
      throw new Error(`unexpected fetch ${fetchUrl(input).href}`);
    });
    await env.STRUCTURED_BUCKET.put(VALUATION_BACKFILL_KEY, JSON.stringify(canaryDoc({
      lease: { owner: "cron-a", until: new Date(Date.now() + 60_000).toISOString() },
    })));
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(spy.mock.calls.length).toBe(calls);
    expect(JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ).cursor).toBe(1);
  });

  it("records a late ingest pass after fetch abort instead of timeout-zero", async () => {
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc()),
    );
    let aborted = false;
    const ingest: ExactFiveIngest = (_opts, signal) =>
      new Promise((resolve) => {
        const finish = () => {
          aborted = signal.aborted;
          resolve({ status: "pass", datasetCount: 1, rowsInserted: 7 });
        };
        if (signal.aborted) {
          queueMicrotask(finish);
          return;
        }
        signal.addEventListener("abort", () => queueMicrotask(finish), { once: true });
      });
    const result = await runExactFiveAcquisitionTick(
      env.STRUCTURED_BUCKET,
      ingest,
      {
        clock: () => new Date("2026-09-12T00:00:00.000Z"),
        fetchTimeoutMs: 5,
      },
    );
    expect(aborted).toBe(true);
    expect(result).toMatchObject({ status: "pass", fetched: true, reason: "ok" });
    const control = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number; attempts: number; last: { rowsInserted: number; status: string } };
    expect(control.cursor).toBe(1);
    expect(control.attempts).toBe(0);
    expect(control.last).toMatchObject({ rowsInserted: 7, status: "pass" });
  });

  it("fences an expired running claim and commits the original late pass on CAS retry", async () => {
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc()),
    );
    let nowMs = Date.parse("2026-09-12T00:00:00.000Z");
    const clock = () => new Date(nowMs);
    let release!: (summary: {
      status: "pass" | "fail" | "partial";
      datasetCount: number;
      rowsInserted: number;
    }) => void;
    let invocations = 0;
    const hanging: ExactFiveIngest = () => {
      invocations += 1;
      return new Promise((resolve) => {
        release = resolve;
      });
    };
    const first = runExactFiveAcquisitionTick(
      env.STRUCTURED_BUCKET,
      hanging,
      { clock, fetchTimeoutMs: 60_000 },
    );
    for (let i = 0; i < 50; i++) {
      const raw = await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY);
      const parsed = JSON.parse(await raw!.text()) as { last: { status: string } | null };
      if (parsed.last?.status === "running") break;
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    expect(
      await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, hanging, { clock, fetchTimeoutMs: 60_000 }),
    ).toMatchObject({ status: "idle", fetched: false, reason: "leased" });
    expect(invocations).toBe(1);

    nowMs += 300_000;
    expect(
      await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, hanging, { clock, fetchTimeoutMs: 60_000 }),
    ).toMatchObject({ status: "idle", fetched: false, reason: "unresolved" });
    expect(invocations).toBe(1);
    const fenced = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number; last: { status: string } };
    expect(fenced.cursor).toBe(0);
    expect(fenced.last.status).toBe("unresolved");

    release({ status: "pass", datasetCount: 1, rowsInserted: 3 });
    expect(await first).toMatchObject({ status: "pass", fetched: true, reason: "ok" });
    const control = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number; attempts: number; lease: null; last: { rowsInserted: number; status: string } };
    expect(control.cursor).toBe(1);
    expect(control.attempts).toBe(0);
    expect(control.lease).toBeNull();
    expect(control.last).toMatchObject({ rowsInserted: 3, status: "pass" });
    expect(invocations).toBe(1);
  });

  it("completed exact-five persistence advances a later expired claim without a second fetch", async () => {
    expect((await rebuildNaturalKeysV2(env.DB)).state).toBe("READY");
    const testEnv = runtimeEnv();
    await env.STRUCTURED_BUCKET.put(EXACT_FIVE_ACQUISITION_KEY, JSON.stringify(exactFiveDoc()));
    const spy = stubVendor("/v2/markets/calendar", { from: "2023-01-01", to: "2023-01-31" }, []);
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(spy).toHaveBeenCalledTimes(1);
    const run = await env.DB.prepare(
      `SELECT id, status, detail FROM ingestion_run_log
        WHERE source = 'jquants' AND runtime = 'cloudflare'`,
    ).first<{ id: number; status: string; detail: string }>();
    expect(run?.status).toBe("pass");
    const detail = JSON.parse(run!.detail) as {
      status: string;
      opts: { dataset: string; from: string; to: string; operation: string };
    };
    expect(detail.status).toBe("pass");
    expect(detail.opts).toMatchObject({
      dataset: "markets_calendar",
      from: "2023-01-01",
      to: "2023-01-31",
    });
    expect(detail.opts.operation.length).toBeGreaterThan(0);
    expect(await env.DB.prepare(
      "SELECT run_id, status FROM collection_receipts",
    ).first()).toMatchObject({ run_id: run!.id, status: "SUCCESS" });

    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        attempts: 1,
        lease: { owner: detail.opts.operation, until: "2026-09-11T23:58:30.000Z" },
        last: {
          dataset: "markets_calendar",
          segment_id: "2023-01",
          from: "2023-01-01",
          to: "2023-01-31",
          rowsInserted: 0,
          status: "running",
        },
      })),
    );
    spy.mockImplementation((input) => {
      throw new Error(`unexpected fetch ${fetchUrl(input).href}`);
    });
    await worker.scheduled(scheduledAt("2026-09-12T00:02:00.000Z"), testEnv, createExecutionContext());
    expect(spy).toHaveBeenCalledTimes(1);
    const recovered = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number; last: { status: string } };
    expect(recovered.cursor).toBe(1);
    expect(recovered.last.status).toBe("pass");
  });

  it("ACTIVE unsigned SUCCESS does not skip a compiled calendar month", async () => {
    expect((await rebuildNaturalKeysV2(env.DB)).state).toBe("READY");
    await env.STRUCTURED_BUCKET.put(EXACT_FIVE_ACQUISITION_KEY, JSON.stringify(exactFiveDoc()));
    await env.DB.prepare(
      `INSERT INTO collection_receipts (
         source, dataset, segment_id, segment_start, segment_end,
         expected_scope, expected_items, observed_items, raw_page_count,
         raw_row_count, structured_row_count, pagination_exhausted,
         digests_json, run_id, status, error, checked_at
       ) VALUES (
         'jquants', 'markets_calendar', '2023-01', '2023-01-01', '2023-01-31',
         ?, 1, 0, 1, 0, 0, 1, ?, 1, 'SUCCESS', NULL, '2023-01-31T00:00:00Z'
       )`,
    ).bind(JSON.stringify({
      coverage_mode: "calendar",
      expected_frequency: "calendar_day",
      expected_item_unit: "source_query",
      segment_end: "2023-01-31",
      segment_start: "2023-01-01",
      universe_rule: "jpx_calendar_days",
      segment_granularity: "calendar_month",
    }), JSON.stringify({
      eligibility: "RECOVERED_RAW_ONLY",
      issuer_class: "UnsignedIngestionAudit",
    })).run();
    let ingested = 0;
    const result = await runExactFiveAcquisitionTick(
      env.STRUCTURED_BUCKET,
      async () => {
        ingested += 1;
        throw new Error("must ingest unsigned SUCCESS");
      },
      {
        clock: () => new Date("2026-09-12T00:00:00.000Z"),
        observe: (job, window, operation) =>
          observeExactFiveReceipt(env.DB, job, window, operation, {
            operationMode: "ACTIVE",
            environment: "staging",
          }),
      },
    );
    expect(ingested).toBe(1);
    expect(result).toMatchObject({ status: "fail", fetched: true, reason: "ingestion_failed" });
    const stored = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number };
    expect(stored.cursor).toBe(0);
  });

  it("ACTIVE trusted signed collection receipt may skip the exact window", async () => {
    const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
    const publicKeyRaw = new Uint8Array(await crypto.subtle.exportKey("raw", pair.publicKey));
    let binary = "";
    for (const byte of publicKeyRaw) binary += String.fromCharCode(byte);
    const publicKeyBase64 = btoa(binary);
    const pin = PINNED_RECEIPT_REGISTRY_SCOPE.staging;
    const body = {
      schema_version: 3,
      purpose: "receipt_verification",
      generation: 2,
      authority_status: "ACTIVE" as const,
      environment: "staging",
      authority_instance_digest: pin.authority_instance_digest,
      prior_registry_digest: "sha256:" + "10".repeat(32),
      keys: [{
        key_id: "receipt-test-v1",
        algorithm: "Ed25519",
        public_key_base64: publicKeyBase64,
        status: "active",
      }],
    };
    const registry = await closedReceiptVerifyRegistry(
      { ...body, registry_digest: await canonicalDigest(body) },
      "staging",
    );
    if (!registry) throw new Error("test receipt registry is not closed");
    const expectedScope = {
      coverage_mode: "calendar",
      expected_frequency: "calendar_day",
      expected_item_unit: "source_query",
      segment_end: "2023-01-31",
      segment_start: "2023-01-01",
      universe_rule: "jpx_calendar_days",
      segment_granularity: "calendar_month",
    };
    const digest = "sha256:" + "ab".repeat(32);
    const extras = {
      acquisition_collection_manifest_file_digest: digest,
      acquisition_collection_digest: digest,
      acquisition_terminal_chain_digest: digest,
      product_artifact_digest: digest,
      product_manifest_digest: digest,
    };
    const claimsBase = {
      environment: "staging",
      authority_instance_digest: pin.authority_instance_digest,
      coverage_policy_version: "collection-coverage/v3",
      source: "jquants",
      contract_id: "jquants_premium_core",
      dataset: "markets_calendar",
      segment_id: "2023-01",
      segment_start: "2023-01-01",
      segment_end: "2023-01-31",
      receipt_issue_digest: digest,
      artifact_key: "artifact.jsonl",
      artifact_byte_count: 1,
      manifest_key: "manifest.json",
      manifest_byte_count: 1,
      raw_manifest_key: "raw.json",
      raw_manifest_byte_count: 1,
      raw_byte_count: 1,
      natural_key_digest: digest,
      expected_items: 1,
      observed_items: 1,
      raw_page_count: 1,
      raw_count: 1,
      structured_count: 1,
      status: "SUCCESS",
      error: null,
      pagination_exhausted: true,
      discovery_exhausted: true,
      source_request_digest: digest,
      raw_manifest_digest: digest,
      raw_digest: digest,
      structured_digest: digest,
      structured_generation: 1,
      run_id: 1,
      checked_at: "2023-01-31T00:00:00Z",
      extra_digests: extras,
      expected_scope: expectedScope,
    };
    const scope = {
      environment: claimsBase.environment,
      authority_instance_digest: claimsBase.authority_instance_digest,
      coverage_policy_version: claimsBase.coverage_policy_version,
      source: claimsBase.source,
      contract_id: claimsBase.contract_id,
      dataset: claimsBase.dataset,
      segment_id: claimsBase.segment_id,
      segment_start: claimsBase.segment_start,
      segment_end: claimsBase.segment_end,
      expected_scope: expectedScope,
      expected_items: claimsBase.expected_items,
    };
    const observation = {
      ...scope,
      observed_items: claimsBase.observed_items,
      raw_page_count: claimsBase.raw_page_count,
      raw_count: claimsBase.raw_count,
      structured_count: claimsBase.structured_count,
      status: claimsBase.status,
      error: claimsBase.error,
      pagination_exhausted: claimsBase.pagination_exhausted,
      discovery_exhausted: claimsBase.discovery_exhausted,
      receipt_issue_digest: claimsBase.receipt_issue_digest,
      artifact_key: claimsBase.artifact_key,
      artifact_byte_count: claimsBase.artifact_byte_count,
      manifest_key: claimsBase.manifest_key,
      manifest_byte_count: claimsBase.manifest_byte_count,
      raw_manifest_key: claimsBase.raw_manifest_key,
      raw_manifest_byte_count: claimsBase.raw_manifest_byte_count,
      raw_byte_count: claimsBase.raw_byte_count,
      natural_key_digest: claimsBase.natural_key_digest,
      source_request_digest: claimsBase.source_request_digest,
      raw_manifest_digest: claimsBase.raw_manifest_digest,
      raw_digest: claimsBase.raw_digest,
      structured_digest: claimsBase.structured_digest,
      structured_generation: claimsBase.structured_generation,
      scope_digest: await canonicalDigest(scope),
      run_id: claimsBase.run_id,
      checked_at: claimsBase.checked_at,
      extra_digests: extras,
    };
    const claims = {
      ...observation,
      observation_digest: await canonicalDigest(observation),
      version: "signed-receipt-claims/v3",
      parser_normalizer_version: "coverage-receipt/v4-ed25519-closure",
      issuer_id: "receipt-test-v1",
      issued_at: "2026-08-01T00:00:00Z",
    };
    const bodyBytes = new TextEncoder().encode(canonicalJson(claims));
    const signature = new Uint8Array(
      await crypto.subtle.sign("Ed25519", pair.privateKey, bodyBytes),
    );
    let sigBinary = "";
    for (const byte of signature) sigBinary += String.fromCharCode(byte);
    let bodyBinary = "";
    for (const byte of bodyBytes) bodyBinary += String.fromCharCode(byte);
    const envelope = {
      eligibility: "TRUSTED_COLLECTION",
      issuer_class: "SignedReceiptAuthority",
      issuer_key_id: "receipt-test-v1",
      issuer_id: "receipt-test-v1",
      environment: "staging",
      authority_instance_digest: pin.authority_instance_digest,
      parser_normalizer_version: "coverage-receipt/v4-ed25519-closure",
      signed_body_b64: btoa(bodyBinary),
      signature: `ed25519:${btoa(sigBinary)}`,
      body_digest: await sha256Digest(bodyBytes).then((d) => d.startsWith("sha256:") ? d : `sha256:${d}`),
      issued_at: claims.issued_at,
      checked_at: claims.checked_at,
      source_request_digest: digest,
      raw_manifest_digest: digest,
      raw: digest,
      structured_generation: 1,
      structured_digest: digest,
      scope_digest: claims.scope_digest,
      observation_digest: claims.observation_digest,
      extra_digests: extras,
      ...extras,
    };
    await env.STRUCTURED_BUCKET.put(EXACT_FIVE_ACQUISITION_KEY, JSON.stringify(exactFiveDoc()));
    await env.DB.prepare(
      `INSERT INTO collection_receipts (
         source, dataset, segment_id, segment_start, segment_end,
         expected_scope, expected_items, observed_items, raw_page_count,
         raw_row_count, structured_row_count, pagination_exhausted,
         digests_json, run_id, status, error, checked_at
       ) VALUES (
         'jquants', 'markets_calendar', '2023-01', '2023-01-01', '2023-01-31',
         ?, 1, 1, 1, 1, 1, 1, ?, 1, 'SUCCESS', NULL, '2023-01-31T00:00:00Z'
       )`,
    ).bind(JSON.stringify(expectedScope), JSON.stringify(envelope)).run();
    let ingested = 0;
    const result = await runExactFiveAcquisitionTick(
      env.STRUCTURED_BUCKET,
      async () => {
        ingested += 1;
        throw new Error("must not ingest");
      },
      {
        clock: () => new Date("2026-09-12T00:00:00.000Z"),
        observe: (job, window, operation) =>
          observeExactFiveReceipt(env.DB, job, window, operation, {
            operationMode: "ACTIVE",
            environment: "staging",
            registry,
          }),
      },
    );
    expect(result).toMatchObject({ status: "pass", fetched: false, reason: "ok" });
    expect(ingested).toBe(0);
    const stored = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number };
    expect(stored.cursor).toBe(1);
  });

  it("ACTIVE authority SUCCESS for the initiating operation advances without a second ingest", async () => {
    const owner = "dead-isolate";
    const nonce = await sha256HexFromString(owner);
    const operationId = `sha256:${"ab".repeat(32)}`;
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        attempts: 1,
        lease: { owner, until: "2026-09-11T23:58:30.000Z" },
        last: {
          dataset: "markets_calendar",
          segment_id: "2023-01",
          from: "2023-01-01",
          to: "2023-01-31",
          rowsInserted: 0,
          status: "running",
        },
      })),
    );
    await env.DB.prepare(
      `INSERT INTO ingestion_run_log (id, ran_at, source, runtime, status, detail)
       VALUES (11, '2023-01-31T00:00:00Z', 'jquants', 'cloudflare', 'running', ?)`,
    ).bind(JSON.stringify({
      triggeredBy: "cron",
      opts: {
        dataset: "markets_calendar",
        from: "2023-01-01",
        to: "2023-01-31",
        operation: owner,
      },
    })).run();
    await env.DB.prepare(
      `INSERT INTO ingestion_validation (
         run_id, dataset, started_at, finished_at, status, rows_seen, rows_inserted,
         rows_revisions, available_at_min, available_at_max, detail
       ) VALUES (
         11, 'markets_calendar', '2023-01-31T00:00:00Z', '2023-01-31T00:00:01Z',
         'fail', 0, 0, 0, NULL, NULL, 'issue rpc lost'
       )`,
    ).run();
    await env.DB.prepare(
      `INSERT INTO receipt_authority_requests(
         operation_id,request_nonce,environment,source,contract_id,dataset,segment_id,state,
         receipt_digest,created_at,updated_at
       ) VALUES (
         ?, ?, 'staging', 'jquants', 'jquants_premium_core', 'markets_calendar', '2023-01',
         'PREPARED', NULL, '2023-01-31T00:00:00Z', '2023-01-31T00:00:00Z'
       )`,
    ).bind(operationId, nonce).run();
    let invocations = 0;
    const ingest: ExactFiveIngest = async () => {
      invocations += 1;
      return { status: "pass", datasetCount: 1, rowsInserted: 99 };
    };
    const held = await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, ingest, {
      clock: () => new Date("2026-09-12T00:00:00.000Z"),
      observe: (job, window, operation) =>
        observeExactFiveReceipt(env.DB, job, window, operation),
    });
    expect(held).toMatchObject({ status: "idle", fetched: false, reason: "unresolved" });
    expect(invocations).toBe(0);
    const heldControl = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number; lease: { owner: string }; last: { status: string } };
    expect(heldControl.cursor).toBe(0);
    expect(heldControl.lease.owner).toBe(owner);
    expect(heldControl.last.status).toBe("unresolved");
    expect(await env.DB.prepare(
      "SELECT request_nonce, state FROM receipt_authority_requests",
    ).first()).toMatchObject({ request_nonce: nonce, state: "PREPARED" });

    await env.DB.prepare(
      `INSERT INTO ingestion_run_log
         (id, ran_at, source, runtime, status, detail, authority_operation_id)
       VALUES (
         99, '2023-01-31T00:00:00Z', 'jquants', 'receipt-evidence-authority',
         'SUCCESS', '{}', ?
       )`,
    ).bind(operationId).run();
    await env.DB.prepare(
      `INSERT INTO receipt_authority_operations(
         operation_id,request_digest,run_id,environment,source,contract_id,dataset,segment_id,
         segment_start,segment_end,state,checked_at,updated_at,raw_manifest_key,
         raw_manifest_digest,raw_page_count,raw_row_count,raw_bytes
       ) VALUES (
         ?, 'sha256:${"cd".repeat(32)}', 99, 'staging', 'jquants', 'jquants_premium_core',
         'markets_calendar', '2023-01', '2023-01-01', '2023-01-31', 'COLLECTING',
         '2023-01-31T00:00:00Z', '2023-01-31T00:00:00Z',
         'raw/markets_calendar/99/manifest.json', 'sha256:${"11".repeat(32)}', 1, 4, 8
       )`,
    ).bind(operationId).run();
    await env.DB.prepare(
      `UPDATE receipt_authority_operations
          SET state='STRUCTURED_COMMITTED',
              structured_manifest_key='structured/markets_calendar/99.json',
              structured_digest='sha256:${"22".repeat(32)}'
        WHERE operation_id=?`,
    ).bind(operationId).run();
    await env.DB.prepare(
      `INSERT INTO collection_receipts (
         source, dataset, segment_id, segment_start, segment_end,
         expected_scope, expected_items, observed_items, raw_page_count,
         raw_row_count, structured_row_count, pagination_exhausted,
         digests_json, run_id, status, error, checked_at
       ) VALUES (
         'jquants', 'markets_calendar', '2023-01', '2023-01-01', '2023-01-31',
         '{}', 1, 1, 1, 4, 4, 1, '{}', 99, 'SUCCESS', NULL, '2023-01-31T00:00:00Z'
       )`,
    ).run();
    await env.DB.prepare(
      `UPDATE receipt_authority_operations
          SET state='RECEIPT_COMMITTED', receipt_digest='sha256:${"33".repeat(32)}'
        WHERE operation_id=?`,
    ).bind(operationId).run();
    await env.DB.prepare(
      `UPDATE receipt_authority_requests
          SET state='FINALIZED',
              receipt_digest='sha256:${"33".repeat(32)}',
              updated_at='2023-01-31T00:00:02Z'
        WHERE operation_id=? AND request_nonce=? AND state='PREPARED'`,
    ).bind(operationId, nonce).run();
    const finished = await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, ingest, {
      clock: () => new Date("2026-09-12T00:02:00.000Z"),
      observe: (job, window, operation) =>
        observeExactFiveReceipt(env.DB, job, window, operation),
    });
    expect(finished).toMatchObject({ status: "pass", fetched: false, reason: "ok" });
    expect(invocations).toBe(0);
    const stored = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number; last: { rowsInserted: number; status: string } };
    expect(stored.cursor).toBe(1);
    expect(stored.last).toMatchObject({ rowsInserted: 4, status: "pass" });
  });

  it("fail validation after coverage is terminal for the pending operation", async () => {
    const owner = "dead-isolate";
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        attempts: 1,
        lease: { owner, until: "2026-09-11T23:58:30.000Z" },
        last: {
          dataset: "markets_calendar",
          segment_id: "2023-01",
          from: "2023-01-01",
          to: "2023-01-31",
          rowsInserted: 0,
          status: "running",
        },
      })),
    );
    await env.DB.prepare(
      `INSERT INTO coverage_segments (
         source, dataset, segment_id, policy_version, segment_start, segment_end,
         expected_scope, expected_items, status, receipt_run_id, evaluated_at, detail_json
       ) VALUES (
         'jquants', 'markets_calendar', '2023-01', 'collection-coverage/v3',
         '2023-01-01', '2023-01-31', '{}', 1, 'UNKNOWN', NULL,
         '2023-01-31T00:00:00Z', '{}'
       )`,
    ).run();
    await env.DB.prepare(
      `INSERT INTO ingestion_run_log (id, ran_at, source, runtime, status, detail)
       VALUES (11, '2023-01-31T00:00:00Z', 'jquants', 'cloudflare', 'running', ?)`,
    ).bind(JSON.stringify({
      triggeredBy: "cron",
      opts: {
        dataset: "markets_calendar",
        from: "2023-01-01",
        to: "2023-01-31",
        operation: owner,
      },
    })).run();
    await env.DB.prepare(
      `INSERT INTO ingestion_validation (
         run_id, dataset, started_at, finished_at, status, rows_seen, rows_inserted,
         rows_revisions, available_at_min, available_at_max, detail
       ) VALUES (
         11, 'markets_calendar', '2023-01-31T00:00:00Z', '2023-01-31T00:00:01Z',
         'fail', 0, 0, 0, NULL, NULL, 'r2 put failed'
       )`,
    ).run();
    let invocations = 0;
    const ingest: ExactFiveIngest = async () => {
      invocations += 1;
      return { status: "pass", datasetCount: 1, rowsInserted: 99 };
    };
    const result = await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, ingest, {
      clock: () => new Date("2026-09-12T00:00:00.000Z"),
      observe: (job, window, operation) =>
        observeExactFiveReceipt(env.DB, job, window, operation),
    });
    expect(result).toMatchObject({
      status: "fail",
      fetched: false,
      reason: "ingestion_failed",
    });
    expect(invocations).toBe(0);
    const stored = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number; last: { status: string } };
    expect(stored.cursor).toBe(0);
    expect(stored.last.status).toBe("ingestion_failed");
  });

  it("holds a second fence while a resumed callback is still pending", async () => {
    const owner = "c766f36f-6289-4793-837e-b951e35fa84b";
    let nowMs = Date.parse("2026-09-16T18:40:00.000Z");
    const clock = () => new Date(nowMs);
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        attempts: 1,
        lease: { owner, until: "2026-09-16T18:13:51.098Z" },
        last: {
          dataset: "markets_calendar",
          segment_id: "2023-01",
          from: "2023-01-01",
          to: "2023-01-31",
          rowsInserted: 0,
          status: "unresolved",
        },
      })),
    );
    await env.DB.prepare(
      `INSERT INTO ingestion_run_log (id, ran_at, source, runtime, status, detail)
       VALUES (6737, '2026-09-16T18:05:51.000Z', 'jquants', 'cloudflare', 'running', ?)`,
    ).bind(JSON.stringify({
      triggeredBy: "cron",
      opts: {
        dataset: "markets_calendar",
        from: "2023-01-01",
        to: "2023-01-31",
        operation: owner,
      },
    })).run();
    await env.DB.prepare(
      `INSERT INTO raw_retention_manifests
         (dataset, run_id, manifest_key, page_count, row_count, raw_bytes,
          data_digest, completeness, created_at)
       VALUES (
         'markets_calendar', 6737, 'raw/markets_calendar/6737/manifest.json',
         1, 1, 8, 'sha256:test', 'ACQUIRED', '2026-09-16T18:05:51.000Z'
       )`,
    ).run();
    let invocations = 0;
    let release!: (summary: {
      status: "pass" | "fail" | "partial";
      datasetCount: number;
      rowsInserted: number;
    }) => void;
    const hanging: ExactFiveIngest = () => {
      invocations += 1;
      return new Promise((resolve) => {
        release = resolve;
      });
    };
    const first = runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, hanging, {
      clock,
      observe: (job, window, operation) =>
        observeExactFiveReceipt(env.DB, job, window, operation, { clock }),
    });
    for (let i = 0; i < 50; i++) {
      const parsed = JSON.parse(
        await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
      ) as { last: { status: string } | null; lease: { started?: string } | null };
      if (parsed.last?.status === "running" && parsed.lease?.started) break;
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    expect(invocations).toBe(1);
    nowMs += 240_000;
    expect(
      await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, hanging, {
        clock,
        observe: (job, window, operation) =>
          observeExactFiveReceipt(env.DB, job, window, operation, { clock }),
      }),
    ).toMatchObject({ status: "idle", fetched: false, reason: "unresolved" });
    expect(invocations).toBe(1);
    nowMs += 240_000;
    expect(
      await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, hanging, {
        clock,
        observe: (job, window, operation) =>
          observeExactFiveReceipt(env.DB, job, window, operation, { clock }),
      }),
    ).toMatchObject({ status: "idle", fetched: false, reason: "unresolved" });
    expect(invocations).toBe(1);
    const stored = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { attempts: number; last: { status: string }; lease: { owner: string; started?: string } };
    expect(stored.attempts).toBe(1);
    expect(stored.last.status).toBe("unresolved");
    expect(stored.lease.owner).toBe(owner);
    expect(stored.lease.started).toBe("2026-09-16T18:40:00.000Z");
    release({ status: "pass", datasetCount: 1, rowsInserted: 1 });
    expect(await first).toMatchObject({ status: "pass", fetched: true, reason: "ok" });
  });

  it("fences a legacy two-field lease still inside the Cron wall", async () => {
    const owner = "legacy-lease-owner";
    let nowMs = Date.parse("2026-09-12T00:05:00.000Z");
    const clock = () => new Date(nowMs);
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        attempts: 1,
        lease: { owner, until: "2026-09-12T00:04:00.000Z" },
        last: {
          dataset: "markets_calendar",
          segment_id: "2023-01",
          from: "2023-01-01",
          to: "2023-01-31",
          rowsInserted: 0,
          status: "running",
        },
      })),
    );
    let invocations = 0;
    const ingest: ExactFiveIngest = async () => {
      invocations += 1;
      return { status: "pass", datasetCount: 1, rowsInserted: 1 };
    };
    expect(
      await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, ingest, { clock }),
    ).toMatchObject({ status: "idle", fetched: false, reason: "unresolved" });
    expect(invocations).toBe(0);
    const fenced = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { attempts: number; last: { status: string }; lease: { started?: string; owner: string } };
    expect(fenced.attempts).toBe(1);
    expect(fenced.last.status).toBe("unresolved");
    expect(fenced.lease.owner).toBe(owner);
    expect(fenced.lease.started).toBe("2026-09-12T00:00:00.000Z");
    nowMs += 240_000;
    expect(
      await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, ingest, { clock }),
    ).toMatchObject({ status: "idle", fetched: false, reason: "unresolved" });
    expect(invocations).toBe(0);
    const held = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { lease: { started?: string } };
    expect(held.lease.started).toBe("2026-09-12T00:00:00.000Z");
  });

  it("resumes only complete ACQUIRED raw and never calls the vendor", async () => {
    const missingOwner = "missing-raw-owner";
    const clock = () => new Date("2026-09-16T18:40:00.000Z");
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      throw new Error(`unexpected fetch ${fetchUrl(input).href}`);
    });
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        attempts: 1,
        lease: { owner: missingOwner, until: "2026-09-16T18:13:51.098Z" },
        last: {
          dataset: "markets_calendar",
          segment_id: "2023-01",
          from: "2023-01-01",
          to: "2023-01-31",
          rowsInserted: 0,
          status: "unresolved",
        },
      })),
    );
    await env.DB.prepare(
      `INSERT INTO ingestion_run_log (id, ran_at, source, runtime, status, detail)
       VALUES (41, '2026-09-16T18:05:51.000Z', 'jquants', 'cloudflare', 'running', ?)`,
    ).bind(JSON.stringify({
      triggeredBy: "cron",
      opts: {
        dataset: "markets_calendar",
        from: "2023-01-01",
        to: "2023-01-31",
        operation: missingOwner,
      },
    })).run();
    const seen: { operation?: string; resumeAcquired?: boolean }[] = [];
    const ingest: ExactFiveIngest = async (opts) => {
      seen.push({ operation: opts.operation, resumeAcquired: opts.resumeAcquired });
      return { status: "fail", datasetCount: 1, rowsInserted: 0 };
    };
    const missing = await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, ingest, {
      clock,
      observe: (job, window, operation) =>
        observeExactFiveReceipt(env.DB, job, window, operation, { clock }),
    });
    expect(missing).toMatchObject({ status: "fail", fetched: true });
    expect(seen).toHaveLength(1);
    expect(seen[0]?.resumeAcquired).toBe(false);
    expect(seen[0]?.operation).not.toBe(missingOwner);
    expect(spy).not.toHaveBeenCalled();
    const afterMissing = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { attempts: number };
    expect(afterMissing.attempts).toBe(2);

    const owner = "acquired-resume-owner";
    seen.length = 0;
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        attempts: 1,
        lease: { owner, until: "2026-09-16T18:13:51.098Z" },
        last: {
          dataset: "markets_calendar",
          segment_id: "2023-01",
          from: "2023-01-01",
          to: "2023-01-31",
          rowsInserted: 0,
          status: "unresolved",
        },
      })),
    );
    await env.DB.prepare(
      `INSERT INTO ingestion_run_log (id, ran_at, source, runtime, status, detail)
       VALUES (42, '2026-09-16T18:05:51.000Z', 'jquants', 'cloudflare', 'running', ?)`,
    ).bind(JSON.stringify({
      triggeredBy: "cron",
      opts: {
        dataset: "markets_calendar",
        from: "2023-01-01",
        to: "2023-01-31",
        operation: owner,
      },
    })).run();
    await env.DB.prepare(
      `INSERT INTO raw_retention_manifests
         (dataset, run_id, manifest_key, page_count, row_count, raw_bytes,
          data_digest, completeness, created_at)
       VALUES (
         'markets_calendar', 42, 'raw/markets_calendar/42/manifest.json',
         1, 1, 8, 'sha256:test', 'ACQUIRED', '2026-09-16T18:05:51.000Z'
       )`,
    ).run();
    const complete = await runExactFiveAcquisitionTick(env.STRUCTURED_BUCKET, ingest, {
      clock,
      observe: (job, window, operation) =>
        observeExactFiveReceipt(env.DB, job, window, operation, { clock }),
    });
    expect(complete).toMatchObject({ status: "fail", fetched: true });
    expect(seen).toEqual([{ operation: owner, resumeAcquired: true }]);
    expect(spy).not.toHaveBeenCalled();
    const afterComplete = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { attempts: number };
    expect(afterComplete.attempts).toBe(1);
  });

  it("replays a structured page by stable key after a progress crash", async () => {
    expect((await rebuildNaturalKeysV2(env.DB)).state).toBe("READY");
    const owner = "slice-crash-owner";
    const capturedAt = "2026-09-16T18:05:51.000Z";
    const pages = [1, 2, 3, 4, 5].map((page) => {
      const body = JSON.stringify({ data: [{ Date: `2023-01-0${page}` }] });
      return {
        page,
        body,
        key: `raw/markets_calendar/55/page-${String(page).padStart(6, "0")}.json`,
      };
    });
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        attempts: 1,
        lease: { owner, until: "2026-09-16T18:13:51.098Z" },
        last: {
          dataset: "markets_calendar",
          segment_id: "2023-01",
          from: "2023-01-01",
          to: "2023-01-31",
          rowsInserted: 0,
          status: "unresolved",
        },
      })),
    );
    await env.DB.prepare(
      `INSERT INTO ingestion_run_log (id, ran_at, source, runtime, status, detail)
       VALUES (55, ?, 'jquants', 'cloudflare', 'running', ?)`,
    ).bind(capturedAt, JSON.stringify({
      triggeredBy: "cron",
      opts: {
        dataset: "markets_calendar",
        from: "2023-01-01",
        to: "2023-01-31",
        operation: owner,
      },
    })).run();
    for (const page of pages) {
      await env.RAW_BUCKET.put(page.key, page.body);
    }
    const manifest = {
      format: "jquants-raw-manifest/v1",
      dataset: "markets_calendar",
      run_id: 55,
      fetched_at: capturedAt,
      raw_acquisition: "ACQUIRED",
      complete: true,
      page_count: 5,
      row_count: 5,
      data_digest: "sha256:test",
      pages: pages.map((page) => ({
        key: page.key,
        page: page.page,
        rows: 1,
        bytes: page.body.length,
        digest: `sha256:p${page.page}`,
        http_status: 200,
      })),
    };
    await env.RAW_BUCKET.put(
      "raw/markets_calendar/55/manifest.json",
      JSON.stringify(manifest),
    );
    await env.DB.prepare(
      `INSERT INTO raw_retention_manifests
         (dataset, run_id, manifest_key, page_count, row_count, raw_bytes,
          data_digest, completeness, created_at)
       VALUES (
         'markets_calendar', 55, 'raw/markets_calendar/55/manifest.json',
         5, 5, 5, 'sha256:test', 'ACQUIRED', ?
       )`,
    ).bind(capturedAt).run();
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      throw new Error(`unexpected fetch ${fetchUrl(input).href}`);
    });
    const testEnv = runtimeEnv();
    await worker.scheduled(scheduledAt("2026-09-16T18:40:00.000Z"), testEnv, createExecutionContext());
    expect(spy).not.toHaveBeenCalled();
    const jsonlAfterSlice = (await env.STRUCTURED_BUCKET.list({
      prefix: "structured/jsonl/markets_calendar/",
    })).objects.map((object) => object.key).sort();
    expect(jsonlAfterSlice).toEqual([
      "structured/jsonl/markets_calendar/dt=2023-01-01/run55-p1.jsonl",
      "structured/jsonl/markets_calendar/dt=2023-01-02/run55-p2.jsonl",
      "structured/jsonl/markets_calendar/dt=2023-01-03/run55-p3.jsonl",
      "structured/jsonl/markets_calendar/dt=2023-01-04/run55-p4.jsonl",
    ]);
    const firstBody = await (await env.STRUCTURED_BUCKET.get(jsonlAfterSlice[0]!))!.text();
    await env.RAW_BUCKET.delete("raw/markets_calendar/55/structured-progress.json");
    for (let i = 0; i < 8; i++) {
      const stored = JSON.parse(
        await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
      ) as { cursor: number; last: { status: string } };
      if (stored.cursor === 1 && stored.last.status === "pass") break;
      await worker.scheduled(scheduledAt("2026-09-16T18:41:00.000Z"), testEnv, createExecutionContext());
    }
    expect(spy).not.toHaveBeenCalled();
    const replayBody = await (await env.STRUCTURED_BUCKET.get(jsonlAfterSlice[0]!))!.text();
    expect(replayBody).toBe(firstBody);
    const jsonlFinal = (await env.STRUCTURED_BUCKET.list({
      prefix: "structured/jsonl/markets_calendar/",
    })).objects.map((object) => object.key).sort();
    expect(jsonlFinal).toEqual([
      "structured/jsonl/markets_calendar/dt=2023-01-01/run55-p1.jsonl",
      "structured/jsonl/markets_calendar/dt=2023-01-02/run55-p2.jsonl",
      "structured/jsonl/markets_calendar/dt=2023-01-03/run55-p3.jsonl",
      "structured/jsonl/markets_calendar/dt=2023-01-04/run55-p4.jsonl",
      "structured/jsonl/markets_calendar/dt=2023-01-05/run55-p5.jsonl",
    ]);
    const control = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as { cursor: number; attempts: number; last: { status: string; rowsInserted: number } };
    expect(control.cursor).toBe(1);
    expect(control.attempts).toBe(0);
    expect(control.last).toMatchObject({ status: "pass", rowsInserted: 5 });
    expect(await env.DB.prepare(
      "SELECT run_id, status, structured_row_count FROM collection_receipts WHERE run_id = 55",
    ).first()).toMatchObject({
      run_id: 55,
      status: "SUCCESS",
      structured_row_count: 5,
    });
  });

  it("holds missing ACQUIRED persist failure across future ticks without recapture", async () => {
    expect((await rebuildNaturalKeysV2(env.DB)).state).toBe("READY");
    const owner = "missing-page-owner";
    await env.STRUCTURED_BUCKET.put(
      EXACT_FIVE_ACQUISITION_KEY,
      JSON.stringify(exactFiveDoc({
        attempts: 1,
        lease: { owner, until: "2026-09-16T18:13:51.098Z" },
        last: {
          dataset: "markets_calendar",
          segment_id: "2023-01",
          from: "2023-01-01",
          to: "2023-01-31",
          rowsInserted: 0,
          status: "unresolved",
        },
      })),
    );
    await env.DB.prepare(
      `INSERT INTO ingestion_run_log (id, ran_at, source, runtime, status, detail)
       VALUES (56, '2026-09-16T18:05:51.000Z', 'jquants', 'cloudflare', 'running', ?)`,
    ).bind(JSON.stringify({
      triggeredBy: "cron",
      opts: {
        dataset: "markets_calendar",
        from: "2023-01-01",
        to: "2023-01-31",
        operation: owner,
      },
    })).run();
    const manifest = {
      format: "jquants-raw-manifest/v1",
      dataset: "markets_calendar",
      run_id: 56,
      fetched_at: "2026-09-16T18:05:51.000Z",
      raw_acquisition: "ACQUIRED",
      complete: true,
      page_count: 1,
      row_count: 1,
      data_digest: "sha256:test",
      pages: [{
        key: "raw/markets_calendar/56/page-000001.json",
        page: 1,
        rows: 1,
        bytes: 8,
        digest: "sha256:p1",
        http_status: 200,
      }],
    };
    await env.RAW_BUCKET.put(
      "raw/markets_calendar/56/manifest.json",
      JSON.stringify(manifest),
    );
    await env.DB.prepare(
      `INSERT INTO raw_retention_manifests
         (dataset, run_id, manifest_key, page_count, row_count, raw_bytes,
          data_digest, completeness, created_at)
       VALUES (
         'markets_calendar', 56, 'raw/markets_calendar/56/manifest.json',
         1, 1, 8, 'sha256:test', 'ACQUIRED', '2026-09-16T18:05:51.000Z'
       )`,
    ).run();
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      throw new Error(`unexpected fetch ${fetchUrl(input).href}`);
    });
    const testEnv = runtimeEnv();
    await worker.scheduled(scheduledAt("2026-09-16T18:40:00.000Z"), testEnv, createExecutionContext());
    expect(spy).not.toHaveBeenCalled();
    const failed = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as {
      cursor: number;
      attempts: number;
      last: { status: string };
      lease: { owner: string } | null;
    };
    expect(failed.cursor).toBe(0);
    expect(failed.attempts).toBe(1);
    expect(failed.last.status).toBe("ingestion_failed");
    expect(failed.lease).toMatchObject({ owner });
    expect(await env.DB.prepare(
      "SELECT status FROM ingestion_run_log WHERE id = 56",
    ).first()).toMatchObject({ status: "fail" });
    expect(await env.DB.prepare(
      "SELECT status FROM ingestion_validation WHERE run_id = 56",
    ).first()).toMatchObject({ status: "fail" });
    expect(await env.DB.prepare(
      `SELECT completeness FROM raw_retention_manifests
        WHERE dataset = 'markets_calendar' AND run_id = 56`,
    ).first()).toMatchObject({ completeness: "ACQUIRED" });
    for (const at of [
      "2026-09-16T18:41:00.000Z",
      "2026-09-16T18:42:00.000Z",
      "2026-09-16T18:56:00.000Z",
    ]) {
      await worker.scheduled(scheduledAt(at), testEnv, createExecutionContext());
      expect(spy).not.toHaveBeenCalled();
      const held = JSON.parse(
        await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
      ) as {
        attempts: number;
        last: { status: string };
        lease: { owner: string } | null;
      };
      expect(held.attempts).toBe(1);
      expect(held.last.status).toBe("ingestion_failed");
      expect(held.lease).toMatchObject({ owner });
    }

    await env.STRUCTURED_BUCKET.put(EXACT_FIVE_ACQUISITION_KEY, JSON.stringify(exactFiveDoc()));
    const innerRaw = env.RAW_BUCKET;
    const freshEnv = runtimeEnv({
      RAW_BUCKET: {
        get: (key: string) => {
          if (/\/page-\d+\.json$/.test(String(key))) return Promise.resolve(null);
          return innerRaw.get(key);
        },
        put: (key: string, value: unknown, options?: unknown) =>
          innerRaw.put(
            key,
            value as string,
            options as { customMetadata?: Record<string, string> },
          ),
      } as R2Bucket,
    });
    const vendor = stubVendor(
      "/v2/markets/calendar",
      { from: "2023-01-01", to: "2023-01-31" },
      [{ Date: "2023-01-04" }],
    );
    await worker.scheduled(scheduledAt("2026-09-16T19:00:00.000Z"), freshEnv, createExecutionContext());
    expect(vendor.mock.calls.length).toBe(1);
    const freshFailed = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
    ) as {
      attempts: number;
      last: { status: string };
      lease: { owner: string } | null;
    };
    expect(freshFailed.attempts).toBe(1);
    expect(freshFailed.last.status).toBe("ingestion_failed");
    expect(freshFailed.lease?.owner).toEqual(expect.any(String));
    const freshOwner = freshFailed.lease!.owner;
    expect(freshOwner).not.toBe(owner);
    for (const at of ["2026-09-16T19:01:00.000Z", "2026-09-16T19:16:00.000Z"]) {
      await worker.scheduled(scheduledAt(at), freshEnv, createExecutionContext());
      expect(vendor.mock.calls.length).toBe(1);
      const held = JSON.parse(
        await (await env.STRUCTURED_BUCKET.get(EXACT_FIVE_ACQUISITION_KEY))!.text(),
      ) as {
        attempts: number;
        last: { status: string };
        lease: { owner: string } | null;
      };
      expect(held.attempts).toBe(1);
      expect(held.last.status).toBe("ingestion_failed");
      expect(held.lease).toMatchObject({ owner: freshOwner });
    }
  });

  it("R2 CAS concurrent claim, thrown error, exhaustion, and resume", async () => {
    expect((await rebuildNaturalKeysV2(env.DB)).state).toBe("READY");
    const testEnv = runtimeEnv();
    await env.STRUCTURED_BUCKET.put(VALUATION_BACKFILL_KEY, JSON.stringify(canaryDoc()));
    let invocations = 0;
    let started!: () => void;
    const startedP = new Promise<void>((resolve) => {
      started = resolve;
    });
    let crash!: () => void;
    const hanging: ValuationIngest = () => {
      invocations += 1;
      started();
      return new Promise((_, reject) => {
        crash = () => reject(new Error("forced crash https://api.jquants.com/secret"));
      });
    };
    const leftP = runValuationBackfillTick(env.STRUCTURED_BUCKET, hanging);
    const rightP = runValuationBackfillTick(env.STRUCTURED_BUCKET, hanging);
    await startedP;
    const loser = await Promise.race([
      leftP.then((result) => ({ side: "left" as const, result })),
      rightP.then((result) => ({ side: "right" as const, result })),
    ]);
    expect(invocations).toBe(1);
    expect(["lost", "idle"]).toContain(loser.result.status);
    crash();
    expect(await (loser.side === "left" ? rightP : leftP)).toMatchObject({
      status: "fail",
      fetched: true,
      reason: "ingestion_failed",
    });
    const afterThrow = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(VALUATION_BACKFILL_KEY))!.text(),
    ) as { next: string; attempts: number; last: { status: string } | null };
    expect(afterThrow.next).toBe("2026-09-11");
    expect(afterThrow.attempts).toBe(1);
    expect(afterThrow.last?.status).toBe("ingestion_failed");

    let forced = 0;
    const boom: ValuationIngest = async () => {
      forced += 1;
      throw new Error("forced crash");
    };
    expect(
      await runValuationBackfillTick(env.STRUCTURED_BUCKET, boom),
    ).toMatchObject({ status: "fail", reason: "ingestion_failed" });
    expect(
      await runValuationBackfillTick(env.STRUCTURED_BUCKET, boom),
    ).toMatchObject({ status: "fail", reason: "ingestion_failed" });
    expect(forced).toBe(2);
    expect(
      await runValuationBackfillTick(env.STRUCTURED_BUCKET, boom),
    ).toMatchObject({ status: "stop", fetched: false, reason: "exhausted" });
    expect(forced).toBe(2);

    await env.STRUCTURED_BUCKET.put(
      VALUATION_BACKFILL_KEY,
      JSON.stringify({
        schema: "equities-valuation-backfill/v1",
        dataset: "equities_valuation",
        job_id: "history:2026-09-07:2026-09-13",
        kind: "history",
        start: "2026-09-07",
        end: "2026-09-13",
        next: "2026-09-07",
        attempts: 0,
        lease: null,
        last: null,
      }),
    );
    let allowEmpty = false;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = fetchUrl(input);
      const date = url.searchParams.get("date");
      if (
        url.origin !== "https://api.jquants.com" ||
        url.pathname !== "/v2/equities/valuation" ||
        !date ||
        date < "2026-09-07" ||
        date > "2026-09-13"
      ) {
        throw new Error(`unexpected fetch ${url.href}`);
      }
      if (!allowEmpty) {
        return Promise.resolve(
          new Response(JSON.stringify({ message: "unavailable" }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response(JSON.stringify({ data: [] }), { status: 200 }));
    });
    expect(
      await runValuationBackfillTick(env.STRUCTURED_BUCKET, cronIngest(testEnv)),
    ).toMatchObject({ status: "fail", reason: "ingestion_failed" });
    const blocked = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(VALUATION_BACKFILL_KEY))!.text(),
    ) as { next: string };
    expect(blocked.next).toBe("2026-09-07");
    // Seeded expired lease resume only. A live overlapping owner is already
    // rejected by R2 CAS on stale etag; this does not re-prove stale final.
    await env.STRUCTURED_BUCKET.put(
      VALUATION_BACKFILL_KEY,
      JSON.stringify({
        schema: "equities-valuation-backfill/v1",
        dataset: "equities_valuation",
        job_id: "history:2026-09-07:2026-09-13",
        kind: "history",
        start: "2026-09-07",
        end: "2026-09-13",
        next: "2026-09-07",
        attempts: 1,
        lease: {
          owner: "stale",
          until: new Date(Date.now() - 1000).toISOString(),
        },
        last: null,
      }),
    );
    allowEmpty = true;
    expect(
      await runValuationBackfillTick(env.STRUCTURED_BUCKET, cronIngest(testEnv)),
    ).toMatchObject({ status: "pass", days: 5, reason: "ok" });
    const progressed = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(VALUATION_BACKFILL_KEY))!.text(),
    ) as { next: string; attempts: number; last: { day: string; rowsInserted: number } | null };
    expect(progressed.next).toBe("2026-09-12");
    expect(progressed.attempts).toBe(0);
    expect(progressed.last?.day).toBe("2026-09-11");
    expect(progressed.last?.rowsInserted).toBe(0);
    expect(
      await runValuationBackfillTick(env.STRUCTURED_BUCKET, cronIngest(testEnv)),
    ).toMatchObject({ status: "pass", days: 2, reason: "ok" });
    const bounded = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(VALUATION_BACKFILL_KEY))!.text(),
    ) as { next: string; last: { day: string } | null };
    expect(bounded.next).toBe("2026-09-14");
    expect(bounded.last?.day).toBe("2026-09-13");
  });

  it("scheduled canary persists D1/R2 unsigned PENDING receipt and stops fetching", async () => {
    expect((await rebuildNaturalKeysV2(env.DB)).state).toBe("READY");
    const testEnv = runtimeEnv();
    await env.STRUCTURED_BUCKET.put(VALUATION_BACKFILL_KEY, JSON.stringify(canaryDoc()));
    const spy = stubVendor("/v2/equities/valuation", { date: "2026-09-11" }, [{
      Code: "86970",
      Date: "2026-09-11",
      EPS: -12.5,
      BPS: -1.0,
      ROE: -0.05,
      PER: null,
      PBR: null,
      MktCap: 1000,
    }]);
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(spy.mock.calls.length).toBeGreaterThan(0);
    const control = JSON.parse(
      await (await env.STRUCTURED_BUCKET.get(VALUATION_BACKFILL_KEY))!.text(),
    ) as { next: string; last: { rowsInserted: number; status: string } | null };
    expect(control.next).toBe("2026-09-12");
    expect(control.last?.status).toBe("pass");
    expect(control.last?.rowsInserted).toBeGreaterThan(0);
    expect((await env.RAW_BUCKET.list({ prefix: "raw/equities_valuation/" })).objects.length)
      .toBeGreaterThan(0);
    const structured = (
      await env.STRUCTURED_BUCKET.list({ prefix: "structured/jsonl/equities_valuation/" })
    ).objects;
    expect(structured.length).toBeGreaterThan(0);
    const line = JSON.parse(
      (await (await env.STRUCTURED_BUCKET.get(structured[0]!.key))!.text()).trim().split("\n")[0]!,
    ) as { payload: unknown; raw_payload: unknown; natural_key: string };
    const raw = typeof line.raw_payload === "string"
      ? JSON.parse(line.raw_payload) as Record<string, unknown>
      : line.raw_payload as Record<string, unknown>;
    const payload = typeof line.payload === "string"
      ? JSON.parse(line.payload) as Record<string, unknown>
      : line.payload as Record<string, unknown>;
    expect(raw.EPS).toBe(-12.5);
    expect(raw.ROE).toBe(-0.05);
    expect(raw.MktCap).toBe(1000);
    expect(payload.EPS).toBe(-12.5);
    expect(payload.ROE).toBe(-0.05);
    expect(payload.MktCap).toBe(1000);
    const receipts = await env.DB.prepare(
      "SELECT status, digests_json FROM collection_receipts WHERE dataset = ?",
    ).bind("equities_valuation").all<{ status: string; digests_json: string }>();
    expect(receipts.results).toHaveLength(1);
    expect(receipts.results[0]?.status).toBe("SUCCESS");
    expect(JSON.parse(receipts.results[0]!.digests_json)).toMatchObject({
      eligibility: "RECOVERED_RAW_ONLY",
      issuer_class: "UnsignedIngestionAudit",
    });
    const coverage = await env.DB.prepare(
      "SELECT status FROM coverage_segments WHERE dataset = ?",
    ).bind("equities_valuation").all<{ status: string }>();
    expect(coverage.results.every((row) => row.status !== "COMPLETE")).toBe(true);
    const calls = spy.mock.calls.length;
    spy.mockImplementation((input) => {
      throw new Error(`unexpected fetch ${fetchUrl(input).href}`);
    });
    await worker.scheduled(scheduledAt(), testEnv, createExecutionContext());
    expect(spy.mock.calls.length).toBe(calls);
  });
});
