import { env } from "cloudflare:workers";
import { applyD1Migrations, reset } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, inject, vi } from "vitest";
import worker, { type Env } from "../src/index";
import { NATURAL_KEY_MIGRATION_ID, rebuildNaturalKeysV2 } from "../src/natural_key_migration";

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
});
