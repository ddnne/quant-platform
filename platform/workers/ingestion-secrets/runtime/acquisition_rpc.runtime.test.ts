import { exports } from "cloudflare:workers";
import { afterEach, describe, expect, it, vi } from "vitest";
import canonicalVectorsDocument from "../../../../specs/authorities/jquants_acquisition_canonical_vectors.json";
import bindingManifest from "../../../../specs/cloudflare/active_worker_bindings.json";
import generatedRegistry from "../src/generated/jquants_acquisition_registry";
import { IngestionSecretsService } from "../src/index";
import {
  ACQUISITION_RESPONSE_HEADER_NAMES,
  fetchGovernedPage,
  type AcquisitionEnv,
} from "../src/jquants_acquisition";
import {
  canonicalJson,
  canonicalDigest,
  resolveGovernedRequest,
  sha256Digest,
} from "../src/jquants_acquisition_registry";
import type {
  AcquisitionResponseMetadataV2,
  JquantsAcquisitionRequestV2,
  JquantsAcquisitionRpc,
} from "../src/jquants_acquisition_types";
import {
  deriveOfficialBusinessCalendar,
  officialMasterQueryDigest,
} from "../src/jquants_official_business_calendar";

const API_KEY = "jq-runtime-api-key-not-for-live";
const PROXY_TOKEN = "jq-runtime-proxy-token-not-for-live";
const HMAC_KEY = "jq-runtime-cursor-hmac-key-not-for-live-00000000000000000000000000000000";
const rpc = exports.default as unknown as JquantsAcquisitionRpc & Fetcher;
const originalFetch = globalThis.fetch;

type RegistryRow = {
  canonical_dataset: Record<string, unknown>;
  premium_contract: Record<string, unknown>;
  coverage_policy: Record<string, unknown>;
  query_resolution: Record<string, unknown>;
  source_capability: Record<string, unknown>;
};

type AcquisitionQueryValue = {
  schema_version: string;
  path: string;
  ordered_query: readonly (readonly [string, string])[];
};

type CanonicalVector = {
  id: string;
  family: "acquisition-query" | "ecmascript-json-number";
  value: unknown;
  canonical_json: string;
  sha256_digest: string;
};

function canonicalVector(id: string): CanonicalVector {
  expect(canonicalVectorsDocument).toMatchObject({
    schema_version: "jquants-acquisition-canonical-vectors/v1",
    canonicalization: "RFC8259_UTF8_SORTED_KEYS_NO_WHITESPACE",
    number_rendering: "ECMASCRIPT_JSON_STRINGIFY",
  });
  const vectors = canonicalVectorsDocument.vectors as unknown as readonly CanonicalVector[];
  const matches = vectors.filter((item) => item.id === id);
  expect(matches).toHaveLength(1);
  return matches[0]!;
}

/** Node JSON.stringify number rendering with sorted object keys. Test oracle only. */
function ecmaCanonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => ecmaCanonicalJson(item === undefined ? null : item)).join(",")}]`;
  }
  if (typeof value === "object") {
    const object = value as Record<string, unknown>;
    return `{${Object.keys(object).filter((key) => object[key] !== undefined).sort().map(
      (key) => `${JSON.stringify(key)}:${ecmaCanonicalJson(object[key])}`,
    ).join(",")}}`;
  }
  throw new TypeError(`not an interoperable JSON value: ${typeof value}`);
}

function registryRow(datasetId: string): RegistryRow {
  const rows = generatedRegistry.datasets as unknown as readonly RegistryRow[];
  const row = rows.find((item) => item.canonical_dataset.dataset_id === datasetId);
  if (row === undefined) throw new Error(`missing registry row: ${datasetId}`);
  return row;
}

async function requestFor(
  datasetId: string,
  segmentId = "2024-02",
): Promise<JquantsAcquisitionRequestV2> {
  const row = registryRow(datasetId);
  const officialStart = String(row.source_capability.earliest_official_availability);
  const segmentStart = officialStart.startsWith(segmentId) ? officialStart : `${segmentId}-01`;
  const [year, month] = segmentId.split("-").map(Number);
  const segmentEnd = new Date(Date.UTC(year!, month!, 0)).toISOString().slice(0, 10);
  return {
    schema_version: "jquants-acquisition-rpc-request/v2",
    environment: "production",
    operation: "fetch_governed_page",
    dataset_id: datasetId,
    segment_id: segmentId,
    segment_start: segmentStart,
    segment_end: segmentEnd,
    acquisition_nonce: "a".repeat(64),
    source_capability_digest: await canonicalDigest(row.source_capability),
    dataset_contract_digest: await canonicalDigest({
      canonical_dataset: row.canonical_dataset,
      premium_contract: row.premium_contract,
    }),
    coverage_policy_digest: await canonicalDigest(row.coverage_policy),
    query_contract_digest: await canonicalDigest(row.query_resolution),
    target_registry_digest: generatedRegistry.registry_digest,
    continuation_token: null,
  };
}

function installFetch(
  implementation: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
) {
  const mock = vi.fn(implementation);
  globalThis.fetch = mock as typeof fetch;
  return mock;
}

function bytes(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function base64Url(value: Uint8Array): string {
  let binary = "";
  for (const item of value) binary += String.fromCharCode(item);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function upstream(
  body: Uint8Array | string,
  status = 200,
  contentType = "application/json; charset=utf-8",
  extraHeaders: HeadersInit = {},
): Response {
  const raw = typeof body === "string" ? bytes(body) : body;
  return new Response(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength), {
    status,
    headers: { "content-type": contentType, ...extraHeaders },
  });
}

function officialCalendarBody(
  start: string,
  end: string,
  businessDates: ReadonlySet<string>,
  halfDays: ReadonlySet<string> = new Set(),
): Uint8Array {
  const rows: Array<{ Date: string; HolDiv: string }> = [];
  let cursor = new Date(`${start}T00:00:00Z`);
  const terminal = new Date(`${end}T00:00:00Z`);
  while (cursor <= terminal) {
    const rendered = cursor.toISOString().slice(0, 10);
    rows.push({
      Date: rendered,
      HolDiv: halfDays.has(rendered) ? "2" : businessDates.has(rendered) ? "1" : "0",
    });
    cursor = new Date(cursor.getTime() + 86_400_000);
  }
  return bytes(JSON.stringify({ data: rows }));
}

function nullable(value: string | null): string | null {
  return value === "NONE" ? null : value;
}

function integer(value: string | null): number | null {
  return value === "NONE" || value === null ? null : Number(value);
}

function productionEnv(
  limiter: { limit: () => Promise<{ success: boolean }> } = {
    limit: async () => ({ success: true }),
  },
): AcquisitionEnv {
  return {
    ENVIRONMENT: "production",
    JQUANTS_API_KEY: API_KEY,
    JQUANTS_RPC_CURSOR_HMAC_KEY: HMAC_KEY,
    PROXY_RATE_LIMITER: limiter as unknown as RateLimit,
  };
}

function captureAcquisitionAudit() {
  const spy = vi.spyOn(console, "info").mockImplementation(() => undefined);
  return {
    events(): Record<string, unknown>[] {
      return spy.mock.calls.flatMap((call) => {
        const raw = call[0];
        if (typeof raw !== "string") return [];
        try {
          const parsed = JSON.parse(raw) as Record<string, unknown>;
          return parsed.event === "jquants_acquisition_rpc" ? [parsed] : [];
        } catch {
          return [];
        }
      });
    },
  };
}

async function metadata(response: Response): Promise<AcquisitionResponseMetadataV2> {
  const h = response.headers;
  expect(h.get("x-quant-acquisition-schema")).toBe("jquants-acquisition-rpc-response/v2");
  const value: AcquisitionResponseMetadataV2 = {
    schema_version: "jquants-acquisition-rpc-response-metadata/v2",
    evidence_state: h.get("x-quant-acquisition-evidence-state") as AcquisitionResponseMetadataV2["evidence_state"],
    environment: nullable(h.get("x-quant-acquisition-environment")) as AcquisitionResponseMetadataV2["environment"],
    dataset_id: nullable(h.get("x-quant-acquisition-dataset")),
    segment_id: nullable(h.get("x-quant-acquisition-segment")),
    segment_start: nullable(h.get("x-quant-acquisition-segment-start")),
    segment_end: nullable(h.get("x-quant-acquisition-segment-end")),
    request_digest: nullable(h.get("x-quant-acquisition-request-digest")),
    request_identity_digest: nullable(h.get("x-quant-acquisition-request-identity-digest")),
    previous_request_digest: nullable(h.get("x-quant-acquisition-previous-request-digest")),
    acquisition_id: nullable(h.get("x-quant-acquisition-acquisition-id")),
    acquisition_issued_at: nullable(h.get("x-quant-acquisition-acquisition-issued-at")),
    acquisition_expires_at: nullable(h.get("x-quant-acquisition-acquisition-expires-at")),
    target_registry_digest: nullable(h.get("x-quant-acquisition-registry-digest")),
    source_capability_digest: nullable(h.get("x-quant-acquisition-source-capability-digest")),
    dataset_contract_digest: nullable(h.get("x-quant-acquisition-dataset-contract-digest")),
    coverage_policy_digest: nullable(h.get("x-quant-acquisition-coverage-policy-digest")),
    query_contract_digest: nullable(h.get("x-quant-acquisition-query-contract-digest")),
    cursor_key_id: nullable(h.get("x-quant-acquisition-cursor-key-id")),
    slice_date: nullable(h.get("x-quant-acquisition-slice-date")),
    query_digest: nullable(h.get("x-quant-acquisition-query-digest")),
    page_ordinal: integer(h.get("x-quant-acquisition-page-ordinal")),
    slice_ordinal: integer(h.get("x-quant-acquisition-slice-ordinal")),
    provider_page_ordinal: integer(h.get("x-quant-acquisition-provider-page-ordinal")),
    provider_pagination_state: h.get("x-quant-acquisition-provider-pagination-state") as AcquisitionResponseMetadataV2["provider_pagination_state"],
    upstream_http_status: integer(h.get("x-quant-acquisition-upstream-status")),
    body_digest: h.get("x-quant-acquisition-body-digest")!,
    body_kind: h.get("x-quant-acquisition-body-kind") as AcquisitionResponseMetadataV2["body_kind"],
    pagination_state: h.get("x-quant-acquisition-pagination-state") as AcquisitionResponseMetadataV2["pagination_state"],
    continuation_token: nullable(h.get("x-quant-acquisition-continuation")),
    content_type: h.get("content-type") as AcquisitionResponseMetadataV2["content_type"],
    redirect_count: Number(h.get("x-quant-acquisition-redirect-count")),
    previous_chain_digest: nullable(h.get("x-quant-acquisition-previous-chain-digest")),
    chain_digest: nullable(h.get("x-quant-acquisition-chain-digest")),
  };
  expect(h.get("x-quant-acquisition-metadata-digest")).toBe(await canonicalDigest(value));
  return value;
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("governed J-Quants WorkerEntrypoint RPC", () => {
  it("matches the exact manifest RPC inventory and reserved fetch special", () => {
    const rows = bindingManifest.workers["ingestion-secrets"].staging
      .worker_entrypoints;
    expect(rows).toHaveLength(1);
    const inventory = rows[0]!;
    expect(inventory).toMatchObject({
      name: "IngestionSecretsService",
      fetch_reserved_special: true,
      rpc_methods: ["fetch_governed_page"],
    });
    const methods = Reflect.ownKeys(IngestionSecretsService.prototype)
      .map(String)
      .filter((name) => name !== "constructor");
    expect(methods.includes("fetch")).toBe(true);
    expect(methods.filter((name) => name !== "fetch").sort()).toEqual(
      [...inventory.rpc_methods].sort(),
    );
  });

  it("matches the shared ASCII and Unicode canonical JSON vectors", async () => {
    const expectedIds = [
      "ascii-pagination-key",
      "unicode-bmp-pagination-key",
      "unicode-astral-pagination-key",
    ];
    for (const id of expectedIds) {
      const vector = canonicalVector(id);
      expect(vector.family).toBe("acquisition-query");
      expect(canonicalJson(vector.value)).toBe(vector.canonical_json);
      expect(await canonicalDigest(vector.value)).toBe(vector.sha256_digest);
    }
  });

  it("matches the shared ECMAScript JSON number vectors", async () => {
    const expectedIds = [
      "js-number-ordinary-fractions",
      "js-number-zero",
      "js-number-exponent-thresholds",
      "js-number-binary64-integers",
      "js-number-array-object",
    ];
    for (const id of expectedIds) {
      const vector = canonicalVector(id);
      expect(vector.family).toBe("ecmascript-json-number");
      expect(ecmaCanonicalJson(vector.value)).toBe(vector.canonical_json);
      expect(await sha256Digest(vector.canonical_json)).toBe(vector.sha256_digest);
    }
  });

  it.each([
    "unicode-bmp-pagination-key",
    "unicode-astral-pagination-key",
  ])("keeps %s pagination RAW_PAGE and replays its UTF-8 cursor", async (vectorId) => {
    const vector = canonicalVector(vectorId);
    const cursor = (vector.value as AcquisitionQueryValue).ordered_query.at(-1)![1];
    const firstBody = bytes(JSON.stringify({ data: [], pagination_key: cursor }));
    const secondBody = bytes('{"data":[],"pagination_key":null}');
    const fetchMock = installFetch(async () =>
      fetchMock.mock.calls.length === 1 ? upstream(firstBody) : upstream(secondBody)
    );
    const firstRequest = await requestFor("indices_bars_daily_topix");
    const first = await rpc.fetch_governed_page(firstRequest);
    expect(new Uint8Array(await first.arrayBuffer())).toEqual(firstBody);
    const firstMeta = await metadata(first);
    expect(firstMeta).toMatchObject({
      evidence_state: "RAW_PAGE",
      provider_pagination_state: "CONTINUATION",
      pagination_state: "CONTINUATION",
    });

    const second = await rpc.fetch_governed_page({
      ...firstRequest,
      continuation_token: firstMeta.continuation_token,
    });
    expect(new Uint8Array(await second.arrayBuffer())).toEqual(secondBody);
    const secondMeta = await metadata(second);
    expect(secondMeta).toMatchObject({
      evidence_state: "RAW_PAGE",
      provider_pagination_state: "EXHAUSTED",
      pagination_state: "EXHAUSTED",
      query_digest: vector.sha256_digest,
    });
    expect(String(fetchMock.mock.calls[1]![0])).toBe(
      "https://api.jquants.com/v2/indices/bars/daily/topix" +
      `?from=2024-02-01&to=2024-02-29&pagination_key=${encodeURIComponent(cursor)}`,
    );
  });

  it("returns exact bytes and a chained provider continuation then exhaustion", async () => {
    const firstBody = bytes('{"data":[{"Name":"日本"}],"pagination_key":"page-2"}\n');
    const secondBody = bytes('{"data":[],"pagination_key":null}\n');
    const fetchMock = installFetch(async (_input, init) => {
      expect(new Headers(init?.headers).get("x-api-key")).toBe(API_KEY);
      return fetchMock.mock.calls.length === 1 ? upstream(firstBody) : upstream(secondBody);
    });
    const firstRequest = await requestFor("indices_bars_daily_topix");
    const first = await rpc.fetch_governed_page(firstRequest);
    expect(new Uint8Array(await first.arrayBuffer())).toEqual(firstBody);
    const firstMeta = await metadata(first);
    expect(firstMeta).toMatchObject({
      evidence_state: "RAW_PAGE",
      provider_pagination_state: "CONTINUATION",
      pagination_state: "CONTINUATION",
      page_ordinal: 0,
      provider_page_ordinal: 0,
      slice_date: null,
      upstream_http_status: 200,
      body_digest: await sha256Digest(firstBody),
    });
    expect(firstMeta.continuation_token).toMatch(/^jqa2\./);

    const secondRequest = { ...firstRequest, continuation_token: firstMeta.continuation_token };
    const second = await rpc.fetch_governed_page(secondRequest);
    expect(new Uint8Array(await second.arrayBuffer())).toEqual(secondBody);
    const secondMeta = await metadata(second);
    expect(secondMeta).toMatchObject({
      evidence_state: "RAW_PAGE",
      provider_pagination_state: "EXHAUSTED",
      pagination_state: "EXHAUSTED",
      page_ordinal: 1,
      provider_page_ordinal: 1,
      previous_request_digest: firstMeta.request_digest,
      previous_chain_digest: firstMeta.chain_digest,
      acquisition_id: firstMeta.acquisition_id,
      continuation_token: null,
    });
    expect(String(fetchMock.mock.calls[0]![0])).toBe(
      "https://api.jquants.com/v2/indices/bars/daily/topix?from=2024-02-01&to=2024-02-29",
    );
    expect(String(fetchMock.mock.calls[1]![0])).toContain("pagination_key=page-2");

    const duplicate = await rpc.fetch_governed_page(secondRequest);
    const duplicateBody = new Uint8Array(await duplicate.arrayBuffer());
    const duplicateMeta = await metadata(duplicate);
    expect(duplicateBody).toEqual(secondBody);
    expect(duplicateMeta).toEqual(secondMeta);
  });

  it("advances a closed disclosure month by date and never replays informational cursor", async () => {
    const urls: string[] = [];
    installFetch(async (input) => {
      urls.push(String(input));
      return upstream('{"data":[],"cursor":"differential-only"}');
    });
    const firstRequest = await requestFor("fins_summary");
    const first = await rpc.fetch_governed_page(firstRequest);
    const firstMeta = await metadata(first);
    expect(firstMeta).toMatchObject({
      slice_date: "2024-02-01",
      slice_ordinal: 0,
      provider_pagination_state: "EXHAUSTED",
      pagination_state: "CONTINUATION",
    });
    const second = await rpc.fetch_governed_page({
      ...firstRequest,
      continuation_token: firstMeta.continuation_token,
    });
    const secondMeta = await metadata(second);
    expect(secondMeta).toMatchObject({
      slice_date: "2024-02-02",
      slice_ordinal: 1,
      provider_page_ordinal: 0,
    });
    expect(urls).toEqual([
      "https://api.jquants.com/v2/fins/summary?date=2024-02-01",
      "https://api.jquants.com/v2/fins/summary?date=2024-02-02",
    ]);
  });

  it("derives equities_master slices only from the exact official calendar", async () => {
    const businessDates = new Set([
      "2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06", "2024-06-07",
      "2024-06-10", "2024-06-11", "2024-06-12", "2024-06-13", "2024-06-14",
      "2024-06-17", "2024-06-18", "2024-06-19", "2024-06-21",
      "2024-06-24", "2024-06-25", "2024-06-26", "2024-06-27", "2024-06-28",
    ]);
    const calendarRaw = officialCalendarBody(
      "2024-06-01", "2024-06-30", businessDates, new Set(["2024-06-28"]),
    );
    const urls: string[] = [];
    const fetchMock = installFetch(async (input, init) => {
      urls.push(String(input));
      expect(new Headers(init?.headers).get("x-api-key")).toBe(API_KEY);
      return fetchMock.mock.calls.length === 1
        ? upstream(calendarRaw)
        : upstream('{"data":[]}');
    });
    const initial = await requestFor("equities_master", "2024-06");
    let request = initial;
    const observed: AcquisitionResponseMetadataV2[] = [];
    while (true) {
      const response = await rpc.fetch_governed_page(request);
      expect(response.status).toBe(200);
      const item = await metadata(response);
      observed.push(item);
      if (item.continuation_token === null) break;
      request = { ...initial, continuation_token: item.continuation_token };
    }

    expect(urls[0]).toBe(
      "https://api.jquants.com/v2/markets/calendar?from=2024-06-01&to=2024-06-30",
    );
    expect(urls.slice(1)).toEqual(
      [...businessDates].map((day) =>
        `https://api.jquants.com/v2/equities/master?date=${day}`),
    );
    expect(observed.map((item) => item.slice_date)).toEqual([...businessDates]);
    expect(observed.map((item) => item.slice_ordinal)).toEqual(
      [...businessDates].map((_, index) => index),
    );
    expect(observed.some((item) => item.slice_date === "2024-06-20")).toBe(false);
    expect(observed.at(-1)).toMatchObject({
      slice_date: "2024-06-28",
      pagination_state: "EXHAUSTED",
      continuation_token: null,
    });
    const calendar = await deriveOfficialBusinessCalendar(
      calendarRaw, "2024-06-01", "2024-06-30",
    );
    expect(observed[0]!.query_digest).toBe(await officialMasterQueryDigest({
      path: "/v2/equities/master",
      sliceDate: "2024-06-03",
      providerCursor: null,
      calendar,
    }));
  });

  it("clamps the first partial master month before calendar acquisition", async () => {
    const calendarRaw = officialCalendarBody(
      "2008-05-07", "2008-05-31", new Set(["2008-05-07", "2008-05-30"]),
    );
    const urls: string[] = [];
    const fetchMock = installFetch(async (input) => {
      urls.push(String(input));
      return fetchMock.mock.calls.length === 1
        ? upstream(calendarRaw)
        : upstream('{"data":[]}');
    });
    const initial = await requestFor("equities_master", "2008-05");
    const first = await rpc.fetch_governed_page(initial);
    const firstMeta = await metadata(first);
    expect(urls).toEqual([
      "https://api.jquants.com/v2/markets/calendar?from=2008-05-07&to=2008-05-31",
      "https://api.jquants.com/v2/equities/master?date=2008-05-07",
    ]);
    expect(firstMeta).toMatchObject({
      segment_start: "2008-05-07",
      slice_date: "2008-05-07",
      pagination_state: "CONTINUATION",
    });
  });

  it("keeps provider pagination on one official master slice before advancing", async () => {
    const calendarRaw = officialCalendarBody(
      "2024-02-01", "2024-02-29", new Set(["2024-02-01", "2024-02-02"]),
    );
    const urls: string[] = [];
    const fetchMock = installFetch(async (input) => {
      urls.push(String(input));
      if (fetchMock.mock.calls.length === 1) return upstream(calendarRaw);
      if (fetchMock.mock.calls.length === 2) {
        return upstream('{"data":[],"pagination_key":"master-next"}');
      }
      return upstream('{"data":[]}');
    });
    const initial = await requestFor("equities_master", "2024-02");
    const first = await rpc.fetch_governed_page(initial);
    const firstMeta = await metadata(first);
    const second = await rpc.fetch_governed_page({
      ...initial, continuation_token: firstMeta.continuation_token,
    });
    const secondMeta = await metadata(second);
    const third = await rpc.fetch_governed_page({
      ...initial, continuation_token: secondMeta.continuation_token,
    });
    const thirdMeta = await metadata(third);
    expect(urls).toEqual([
      "https://api.jquants.com/v2/markets/calendar?from=2024-02-01&to=2024-02-29",
      "https://api.jquants.com/v2/equities/master?date=2024-02-01",
      "https://api.jquants.com/v2/equities/master?date=2024-02-01&pagination_key=master-next",
      "https://api.jquants.com/v2/equities/master?date=2024-02-02",
    ]);
    expect([firstMeta, secondMeta, thirdMeta].map((item) => [
      item.slice_date, item.slice_ordinal, item.provider_page_ordinal,
      item.pagination_state,
    ])).toEqual([
      ["2024-02-01", 0, 0, "CONTINUATION"],
      ["2024-02-01", 0, 1, "CONTINUATION"],
      ["2024-02-02", 1, 0, "EXHAUSTED"],
    ]);
  });

  it("HMAC-authenticates the exact official business-date list", async () => {
    const calendarRaw = officialCalendarBody(
      "2024-02-01", "2024-02-29", new Set(["2024-02-01", "2024-02-02"]),
    );
    const fetchMock = installFetch(async () =>
      fetchMock.mock.calls.length === 1 ? upstream(calendarRaw) : upstream('{"data":[]}')
    );
    const initial = await requestFor("equities_master", "2024-02");
    const first = await rpc.fetch_governed_page(initial);
    const token = (await metadata(first)).continuation_token!;
    const parts = token.split(".");
    const padded = parts[1]!.replace(/-/g, "+").replace(/_/g, "/") +
      "=".repeat((4 - parts[1]!.length % 4) % 4);
    const payload = JSON.parse(atob(padded)) as Record<string, unknown>;
    payload.official_business_dates = ["2024-02-01", "2024-02-05"];
    parts[1] = base64Url(bytes(JSON.stringify(payload)));
    const rejected = await rpc.fetch_governed_page({
      ...initial, continuation_token: parts.join("."),
    });
    expect(rejected.status).toBe(400);
    expect(await rejected.json()).toEqual({ error: "request_rejected" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    {
      name: "missing day",
      body: bytes('{"data":[{"Date":"2024-02-01","HolDiv":"1"}]}'),
    },
    {
      name: "caller-style legacy field",
      body: bytes('{"data":[{"Date":"2024-02-01","HolidayDivision":"1"}]}'),
    },
    {
      name: "duplicate escaped row key",
      body: bytes('{"data":[{"Date":"2024-02-01","\\u0044ate":"2024-02-01","HolDiv":"1"}]}'),
    },
  ])("rejects incomplete or tampered official calendar: $name", async ({ body }) => {
    const fetchMock = installFetch(async () => upstream(body));
    const response = await rpc.fetch_governed_page(
      await requestFor("equities_master", "2024-02"),
    );
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: "official_calendar_failed" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]![0])).toContain("/v2/markets/calendar?");
  });

  it("keeps uncertain pagination and non-canonical HTTP envelopes RAW_ONLY", async () => {
    const cases = [
      { raw: new Uint8Array([0xff, 0x00, 0xfe]), status: 200, type: "application/octet-stream" },
      { raw: bytes('{"data":[],"pagination_token":"unknown"}'), status: 200, type: "application/json" },
      { raw: bytes('{"data":[],"cursor":"delta","pagination_key":"next"}'), status: 200, type: "application/json" },
      { raw: bytes('{"data":[]}'), status: 206, type: "application/json" },
      { raw: bytes('{"data":[]}'), status: 200, type: "application/json-malformed" },
      { raw: bytes('{"data":[],"pagination_key":"next","pagination_\\u006bey":null}'), status: 200, type: "application/json" },
      { raw: bytes('{"data":[{"Code":1,"\\u0043ode":2}]}'), status: 200, type: "application/json" },
      { raw: bytes('{"data":[],"pagination_key":"\\ud800"}'), status: 200, type: "application/json" },
      { raw: bytes('{"data":[],"next_page":"schema-drift"}'), status: 200, type: "application/json" },
      { raw: bytes(JSON.stringify({ data: [], pagination_key: "界".repeat(1000) })), status: 200, type: "application/json" },
    ];
    const request = await requestFor("fins_summary");
    for (const item of cases) {
      installFetch(async () => upstream(item.raw, item.status, item.type));
      const response = await rpc.fetch_governed_page(request);
      const responseBody = new Uint8Array(await response.clone().arrayBuffer());
      const meta = await metadata(response);
      expect(responseBody).toEqual(item.raw);
      expect(meta.evidence_state).toBe("RAW_ONLY");
      expect(meta.pagination_state).toBe("UNKNOWN");
      expect(meta.continuation_token).toBeNull();
      expect(meta.upstream_http_status).toBe(item.status);
      globalThis.fetch = originalFetch;
    }
  });

  it("shape-scans a near-limit raw page without materializing provider rows", async () => {
    const maximum = Number(generatedRegistry.maximum_page_bytes);
    const prefix = '{"data":["';
    const suffix = '"]}';
    const raw = bytes(`${prefix}${"x".repeat(maximum - prefix.length - suffix.length - 1024)}${suffix}`);
    installFetch(async () => upstream(raw));
    const response = await rpc.fetch_governed_page(
      await requestFor("indices_bars_daily_topix"),
    );
    const meta = await metadata(response);
    expect(meta).toMatchObject({
      evidence_state: "RAW_PAGE",
      pagination_state: "EXHAUSTED",
      body_digest: await sha256Digest(raw),
    });
    const returned = new Uint8Array(await response.arrayBuffer());
    expect(returned.byteLength).toBe(raw.byteLength);
    expect(await sha256Digest(returned)).toBe(await sha256Digest(raw));
  });

  it("rejects caller-controlled URL/query/header/token/method and identity tampering before fetch", async () => {
    const fetchMock = installFetch(async () => upstream('{"data":[]}'));
    const valid = await requestFor("indices_bars_daily_topix");
    const fakeDigest = `sha256:${"0".repeat(64)}`;
    const invalid: unknown[] = [
      { ...valid, url: "https://evil.example/" },
      { ...valid, query: { code: "86970" } },
      { ...valid, headers: { "x-api-key": "caller" } },
      { ...valid, token: "shared-token" },
      { ...valid, method: "POST" },
      { ...valid, environment: "staging" },
      { ...valid, dataset_id: "equities_master" },
      { ...valid, source_capability_digest: fakeDigest },
      { ...valid, coverage_policy_digest: fakeDigest },
      { ...valid, query_contract_digest: fakeDigest },
      { ...valid, target_registry_digest: fakeDigest },
      { ...valid, segment_end: "2024-02-28" },
      { ...valid, segment_id: "2026-08", segment_start: "2026-08-01", segment_end: "2026-08-31" },
      { ...valid, acquisition_nonce: "predictable" },
      { ...valid, continuation_token: "jqa2.invalid.invalid" },
    ];
    const untyped = rpc as unknown as { fetch_governed_page(request: unknown): Promise<Response> };
    for (const request of invalid) {
      const response = await untyped.fetch_governed_page(request);
      expect(response.status).toBe(400);
      expect(await response.json()).toEqual({ error: "request_rejected" });
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects redirects and provider failures without exposing target-only secrets", async () => {
    const request = await requestFor("indices_bars_daily_topix");
    installFetch(async () => upstream("redirect", 302, "text/plain", { location: "http://evil.example/" }));
    const redirect = await rpc.fetch_governed_page(request);
    expect(redirect.status).toBe(502);
    expect(await redirect.json()).toEqual({ error: "upstream_unavailable" });

    installFetch(async () => {
      throw new Error(`provider exploded ${API_KEY} ${HMAC_KEY} ${PROXY_TOKEN}`);
    });
    const failed = await rpc.fetch_governed_page(request);
    const rendered = `${await failed.text()} ${JSON.stringify([...failed.headers])}`;
    expect(failed.status).toBe(502);
    expect(rendered).not.toContain(API_KEY);
    expect(rendered).not.toContain(HMAC_KEY);
    expect(rendered).not.toContain(PROXY_TOKEN);
  });

  it("returns a closed FAILED envelope when cancelling a provider error body rejects", async () => {
    const upstreamSecret = `upstream-only ${API_KEY} ${HMAC_KEY} ${PROXY_TOKEN}`;
    let cancelCalls = 0;
    installFetch(async () => new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes(upstreamSecret));
      },
      cancel() {
        cancelCalls += 1;
        return Promise.reject(new Error(`cancel rejected ${upstreamSecret}`));
      },
    }), {
      status: 429,
      headers: {
        "content-type": "text/plain",
        "set-cookie": upstreamSecret,
        "retry-after": "1",
      },
    }));

    const response = await rpc.fetch_governed_page(
      await requestFor("indices_bars_daily_topix"),
    );
    const responseBody = await response.clone().text();
    const meta = await metadata(response);
    expect(cancelCalls).toBe(1);
    expect(response.status).toBe(429);
    expect(JSON.parse(responseBody)).toEqual({ error: "upstream_failed" });
    expect(response.headers.get("Retry-After")).toBe("60");
    expect(meta).toMatchObject({
      evidence_state: "FAILED",
      body_kind: "TARGET_ERROR_JSON",
      provider_pagination_state: "NOT_APPLICABLE",
      pagination_state: "NOT_APPLICABLE",
      upstream_http_status: 429,
      continuation_token: null,
      chain_digest: null,
    });
    const rendered = `${responseBody} ${JSON.stringify([...response.headers])}`;
    expect(rendered).not.toContain(upstreamSecret);
    expect(rendered).not.toContain(API_KEY);
    expect(rendered).not.toContain(HMAC_KEY);
    expect(rendered).not.toContain(PROXY_TOKEN);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("does not tunnel RPC through public HTTP", async () => {
    const fetchMock = installFetch(async () => upstream('{"data":[]}'));
    const request = await requestFor("indices_bars_daily_topix");
    const response = await rpc.fetch(
      new Request("https://ingestion-secrets.test/fetch_governed_page", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-ingestion-token": PROXY_TOKEN,
        },
        body: JSON.stringify(request),
      }),
    );
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "not found" });
    expect(fetchMock).not.toHaveBeenCalled();
    const health = await rpc.fetch(new Request("https://ingestion-secrets.test/health"));
    expect(await health.json()).toEqual({ ok: true, worker: "ingestion-secrets" });
  });

  it("enforces the first-day 01:00 JST closed-month cutoff", async () => {
    const request = await requestFor("fins_summary", "2026-02");
    await expect(resolveGovernedRequest(
      request,
      "production",
      new Date("2026-02-28T15:59:00.000Z"),
    )).rejects.toThrow("J-Quants acquisition request rejected");
    await expect(resolveGovernedRequest(
      request,
      "production",
      new Date("2026-02-28T16:00:00.000Z"),
    )).resolves.toMatchObject({ segmentStart: "2026-02-01", segmentEnd: "2026-02-28" });
  });

  it("keeps staging RPC unavailable without production secret bindings", async () => {
    const request = { ...(await requestFor("indices_bars_daily_topix")), environment: "staging" };
    const fetchMock = installFetch(async () => upstream('{"data":[]}'));
    const response = await fetchGovernedPage(
      request,
      { ENVIRONMENT: "staging" } as unknown as AcquisitionEnv,
      new Date("2026-08-26T00:00:00.000Z"),
    );
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: "rpc_unavailable" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a non-canonical base64url continuation spelling", async () => {
    installFetch(async () => upstream('{"data":[],"pagination_key":"next"}'));
    const request = await requestFor("indices_bars_daily_topix");
    const first = await rpc.fetch_governed_page(request);
    const token = (await metadata(first)).continuation_token!;
    const parts = token.split(".");
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    const last = parts[2]!.at(-1)!;
    const index = alphabet.indexOf(last);
    const replacement = alphabet[(index & 0b110000) | ((index + 1) & 0b001111)]!;
    parts[2] = `${parts[2]!.slice(0, -1)}${replacement}`;
    const fetchMock = installFetch(async () => upstream('{"data":[]}'));
    const response = await rpc.fetch_governed_page({
      ...request,
      continuation_token: parts.join("."),
    });
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("mints distinct target sessions and rejects continuation splicing across request identities", async () => {
    const fetchMock = installFetch(async () => upstream('{"data":[],"pagination_key":"next"}'));
    const request = await requestFor("indices_bars_daily_topix");
    const first = await rpc.fetch_governed_page(request);
    const second = await rpc.fetch_governed_page(request);
    const firstMeta = await metadata(first);
    const secondMeta = await metadata(second);
    expect(firstMeta.acquisition_id).not.toBe(secondMeta.acquisition_id);
    expect(firstMeta.chain_digest).not.toBe(secondMeta.chain_digest);

    const spliced = await rpc.fetch_governed_page({
      ...request,
      acquisition_nonce: "b".repeat(64),
      continuation_token: firstMeta.continuation_token,
    });
    expect(spliced.status).toBe(400);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("fails RAW_ONLY when a provider repeats the same pagination cursor", async () => {
    installFetch(async () => upstream('{"data":[],"pagination_key":"same"}'));
    const request = await requestFor("indices_bars_daily_topix");
    const first = await rpc.fetch_governed_page(request);
    const firstMeta = await metadata(first);
    const repeated = await rpc.fetch_governed_page({
      ...request,
      continuation_token: firstMeta.continuation_token,
    });
    const repeatedMeta = await metadata(repeated);
    expect(repeatedMeta).toMatchObject({
      evidence_state: "RAW_ONLY",
      provider_pagination_state: "UNKNOWN",
      pagination_state: "UNKNOWN",
      continuation_token: null,
    });
  });

  it("sets only the reviewed target-owned response header surface", async () => {
    installFetch(async () => upstream('{"data":[]}'));
    const response = await rpc.fetch_governed_page(
      await requestFor("indices_bars_daily_topix"),
    );
    expect([...response.headers.keys()].sort()).toEqual(
      [...ACQUISITION_RESPONSE_HEADER_NAMES].sort(),
    );
    expect(response.headers.get("server")).toBeNull();
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("sets Retry-After 60 for the internal governed rate limiter 429", async () => {
    const fetchMock = installFetch(async () => upstream('{"data":[]}'));
    const request = await requestFor("indices_bars_daily_topix");
    const limited = await fetchGovernedPage(request, {
      ENVIRONMENT: "production",
      JQUANTS_API_KEY: API_KEY,
      JQUANTS_RPC_CURSOR_HMAC_KEY: HMAC_KEY,
      PROXY_RATE_LIMITER: {
        limit: async () => ({ success: false }),
      } as unknown as RateLimit,
    } as AcquisitionEnv, new Date("2026-08-26T00:00:00.000Z"));
    const limitedBody = await limited.clone().json();
    const limitedMeta = await metadata(limited);
    expect(limited.status).toBe(429);
    expect(limitedBody).toEqual({ error: "rate_limited" });
    expect(limited.headers.get("Retry-After")).toBe("60");
    expect(limitedMeta).toMatchObject({
      evidence_state: "FAILED",
      body_kind: "TARGET_ERROR_JSON",
      dataset_id: "indices_bars_daily_topix",
      upstream_http_status: null,
      continuation_token: null,
    });
    expect(fetchMock).not.toHaveBeenCalled();

    const rejected = await rpc.fetch_governed_page({
      ...request,
      acquisition_nonce: "too-short",
    });
    expect(rejected.status).toBe(400);
    expect(await rejected.json()).toEqual({ error: "request_rejected" });
    expect(rejected.headers.get("Retry-After")).toBeNull();
  });

  it.each([
    { label: "missing", extraHeaders: {} },
    { label: "zero", extraHeaders: { "retry-after": "0" } },
    { label: "one", extraHeaders: { "retry-after": "1" } },
    { label: "huge", extraHeaders: { "retry-after": "999999" } },
    { label: "http-date", extraHeaders: { "retry-after": "Wed, 21 Oct 2015 07:28:00 GMT" } },
  ])("returns target-owned Retry-After 60 for provider 429 with $label Retry-After", async ({ extraHeaders }) => {
    const audit = captureAcquisitionAudit();
    installFetch(async () => upstream(
      "provider-only-body",
      429,
      "text/plain",
      { "set-cookie": "evil=1", ...extraHeaders },
    ));
    const response = await fetchGovernedPage(
      await requestFor("indices_bars_daily_topix"),
      productionEnv(),
      new Date("2026-08-26T00:00:00.000Z"),
    );
    const events = audit.events();
    expect(response.status).toBe(429);
    expect(await response.json()).toEqual({ error: "upstream_failed" });
    expect(response.headers.get("Retry-After")).toBe("60");
    expect(response.headers.get("set-cookie")).toBeNull();
    expect((await metadata(response)).upstream_http_status).toBe(429);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      event: "jquants_acquisition_rpc",
      result: "FAILED",
      status: 429,
      upstream_status: 429,
    });
    expect(JSON.stringify(events[0])).not.toContain("provider-only-body");
    expect(JSON.stringify(events[0])).not.toContain("999999");
    expect(JSON.stringify(events[0])).not.toContain("Wed, 21 Oct 2015");
  });

  it("maps provider 503 to 502 without Retry-After and logs upstream_status 503", async () => {
    const audit = captureAcquisitionAudit();
    installFetch(async () => upstream(
      "provider-only-body",
      503,
      "text/plain",
      { "retry-after": "1", "set-cookie": "evil=1" },
    ));
    const response = await fetchGovernedPage(
      await requestFor("indices_bars_daily_topix"),
      productionEnv(),
      new Date("2026-08-26T00:00:00.000Z"),
    );
    const events = audit.events();
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: "upstream_failed" });
    expect(response.headers.get("Retry-After")).toBeNull();
    expect(response.headers.get("set-cookie")).toBeNull();
    expect((await metadata(response)).upstream_http_status).toBe(503);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      event: "jquants_acquisition_rpc",
      result: "FAILED",
      status: 502,
      upstream_status: 503,
    });
    expect(Object.keys(events[0]!).sort()).toEqual([
      "acquisition_id",
      "dataset",
      "environment",
      "event",
      "operation",
      "redirect_count",
      "result",
      "segment_id",
      "status",
      "upstream_status",
      "worker",
    ]);
    expect(JSON.stringify(events[0])).not.toContain("provider-only-body");
    expect(JSON.stringify(events[0])).not.toContain(API_KEY);
  });

  it("does not claim an upstream_status for the internal governed rate limiter 429", async () => {
    const audit = captureAcquisitionAudit();
    const fetchMock = installFetch(async () => upstream('{"data":[]}'));
    const response = await fetchGovernedPage(
      await requestFor("indices_bars_daily_topix"),
      productionEnv({ limit: async () => ({ success: false }) }),
      new Date("2026-08-26T00:00:00.000Z"),
    );
    const events = audit.events();
    expect(response.status).toBe(429);
    expect(await response.json()).toEqual({ error: "rate_limited" });
    expect(response.headers.get("Retry-After")).toBe("60");
    expect((await metadata(response)).upstream_http_status).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      event: "jquants_acquisition_rpc",
      result: "FAILED",
      status: 429,
      upstream_status: null,
    });
    expect(Object.prototype.hasOwnProperty.call(events[0], "upstream_status")).toBe(true);
  });
});
