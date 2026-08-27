import generatedRegistry from "./generated/jquants_acquisition_registry";
import type {
  AcquisitionEnvironment,
  JquantsAcquisitionRequestV2,
} from "./jquants_acquisition_types";

type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export type QueryMode =
  | "calendar_month_sliced"
  | "calendar_month_range"
  | "official_business_day_sliced";

export type GovernedRoute = {
  datasetId: string;
  path: string;
  queryMode: QueryMode;
  dayParameter: "date" | null;
  earliestOfficialAvailability: string;
  sourceCapabilityDigest: string;
  datasetContractDigest: string;
  coveragePolicyDigest: string;
  queryContractDigest: string;
  registryDigest: string;
  paginationParameters: ReadonlyMap<string, string>;
  allowedIgnoredResponseFields: ReadonlySet<string>;
  requiresOfficialCalendar: boolean;
};

export type ResolvedGovernedRequest = {
  request: JquantsAcquisitionRequestV2;
  requestDigest: string;
  requestIdentityDigest: string;
  route: GovernedRoute;
  segmentStart: string;
  segmentEnd: string;
};

export type TargetRegistryLimits = {
  officialOrigin: string;
  maximumRedirects: 0;
  maximumPageBytes: number;
  maximumSegmentPages: number;
  maximumProviderPagesPerSlice: number;
  continuationTtlSeconds: number;
};

export class AcquisitionRequestRejected extends Error {
  constructor(readonly code: string) {
    super("J-Quants acquisition request rejected");
    this.name = "AcquisitionRequestRejected";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isSafeInteger(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isObject(value) && Object.values(value).every(isJsonValue);
}

function canonicalize(value: JsonValue): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  return `{${Object.keys(value).sort().map(
    (key) => `${JSON.stringify(key)}:${canonicalize(value[key]!)}`,
  ).join(",")}}`;
}

export function canonicalJson(value: unknown): string {
  if (!isJsonValue(value)) throw new TypeError("value is not canonical JSON");
  return canonicalize(value);
}

function hex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)].map(
    (value) => value.toString(16).padStart(2, "0"),
  ).join("");
}

export async function sha256Digest(value: Uint8Array | string): Promise<string> {
  const bytes = typeof value === "string" ? new TextEncoder().encode(value) : value;
  return `sha256:${hex(await crypto.subtle.digest("SHA-256", bytes))}`;
}

export async function canonicalDigest(value: unknown): Promise<string> {
  return sha256Digest(canonicalJson(value));
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function requireObject(value: unknown, code: string): Record<string, unknown> {
  if (!isObject(value)) throw new AcquisitionRequestRejected(code);
  return value;
}

function requireString(value: unknown, code: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new AcquisitionRequestRejected(code);
  }
  return value;
}

const REQUEST_KEYS = [
  "schema_version", "environment", "operation", "dataset_id", "segment_id",
  "segment_start", "segment_end", "acquisition_nonce",
  "source_capability_digest", "dataset_contract_digest",
  "coverage_policy_digest", "query_contract_digest", "target_registry_digest",
  "continuation_token",
] as const;
const SHA256_RE = /^sha256:[0-9a-f]{64}$/;
const DATASET_RE = /^[a-z][a-z0-9_]{2,127}$/;
const NONCE_RE = /^[0-9a-f]{64}$/;

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

export function decodeRequest(value: unknown): JquantsAcquisitionRequestV2 {
  if (!isObject(value) || !exactKeys(value, REQUEST_KEYS)) {
    throw new AcquisitionRequestRejected("request_shape");
  }
  if (
    value.schema_version !== "jquants-acquisition-rpc-request/v2" ||
    (value.environment !== "staging" && value.environment !== "production") ||
    value.operation !== "fetch_governed_page" ||
    typeof value.dataset_id !== "string" || !DATASET_RE.test(value.dataset_id) ||
    typeof value.segment_id !== "string" || !/^\d{4}-\d{2}$/.test(value.segment_id) ||
    typeof value.segment_start !== "string" || !validDate(value.segment_start) ||
    typeof value.segment_end !== "string" || !validDate(value.segment_end) ||
    typeof value.acquisition_nonce !== "string" || !NONCE_RE.test(value.acquisition_nonce) ||
    typeof value.source_capability_digest !== "string" || !SHA256_RE.test(value.source_capability_digest) ||
    typeof value.dataset_contract_digest !== "string" || !SHA256_RE.test(value.dataset_contract_digest) ||
    typeof value.coverage_policy_digest !== "string" || !SHA256_RE.test(value.coverage_policy_digest) ||
    typeof value.query_contract_digest !== "string" || !SHA256_RE.test(value.query_contract_digest) ||
    typeof value.target_registry_digest !== "string" || !SHA256_RE.test(value.target_registry_digest) ||
    !(value.continuation_token === null ||
      (typeof value.continuation_token === "string" &&
        value.continuation_token.length >= 32 && value.continuation_token.length <= 8192))
  ) {
    throw new AcquisitionRequestRejected("request_fields");
  }
  return value as JquantsAcquisitionRequestV2;
}

async function registryRows(): Promise<{
  digest: string;
  rows: readonly Record<string, unknown>[];
}> {
  const document = requireObject(generatedRegistry, "registry_shape");
  const sources = requireObject(document.sources, "registry_sources");
  if (
    document.schema_version !== "jquants-acquisition-target-registry/v2" ||
    typeof document.registry_digest !== "string" || !SHA256_RE.test(document.registry_digest) ||
    document.canonicalization !== "RFC8259_UTF8_SORTED_KEYS_NO_WHITESPACE" ||
    !Array.isArray(document.datasets) || !Array.isArray(document.excluded_datasets) ||
    sources.official_client_revision !== "e38614ea3d66c4420597ff148c4848693692d6d9"
  ) {
    throw new AcquisitionRequestRejected("registry_shape");
  }
  const body: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(document)) {
    if (key !== "registry_digest") body[key] = item;
  }
  const digest = await canonicalDigest(body);
  if (digest !== document.registry_digest) {
    throw new AcquisitionRequestRejected("registry_digest");
  }
  const active = document.datasets.map((item) =>
    requireObject(requireObject(item, "registry_row").canonical_dataset, "registry_canonical").dataset_id,
  );
  const expectedActive = [
    "equities_bars_daily", "equities_master", "fins_details", "fins_dividend",
    "fins_earnings_date", "fins_summary", "indices_bars_daily_topix",
    "markets_calendar",
  ];
  const excluded = document.excluded_datasets.map((item) => {
    const row = requireObject(item, "registry_exclusion");
    if (!exactKeys(row, ["dataset_id", "reason", "status"]) ||
      row.status !== "PENDING" || typeof row.dataset_id !== "string" ||
      typeof row.reason !== "string" || row.reason.length < 32) {
      throw new AcquisitionRequestRejected("registry_exclusion");
    }
    return row.dataset_id;
  });
  const expectedExcluded = [
    "equities_bars_daily_am", "equities_earnings_calendar", "equities_master",
  ];
  if (canonicalJson(active.slice().sort()) !== canonicalJson(expectedActive) ||
    canonicalJson(excluded.slice().sort()) !== canonicalJson(expectedExcluded)) {
    throw new AcquisitionRequestRejected("registry_inventory");
  }
  return {
    digest,
    rows: document.datasets.map((item) => requireObject(item, "registry_row")),
  };
}

async function resolveRoute(datasetId: string): Promise<GovernedRoute> {
  const registry = await registryRows();
  const matches = registry.rows.filter((row) =>
    requireObject(row.canonical_dataset, "registry_canonical").dataset_id === datasetId,
  );
  if (matches.length !== 1) {
    throw new AcquisitionRequestRejected(matches.length === 0 ? "dataset_unknown" : "registry_duplicate");
  }
  const selected = matches[0]!;
  const canonical = requireObject(selected.canonical_dataset, "registry_canonical");
  const premium = requireObject(selected.premium_contract, "registry_premium");
  const coverage = requireObject(selected.coverage_policy, "registry_coverage");
  const capability = requireObject(selected.source_capability, "registry_capability");
  const query = requireObject(selected.query_resolution, "registry_query");
  const contracts = requireObject(canonical.contracts, "registry_contracts");
  if (
    canonical.dataset_id !== datasetId || canonical.enabled !== true ||
    canonical.governance_tier !== "governed" || canonical.source !== "jquants_premium_core" ||
    contracts.primary !== "jquants_premium_core" || premium.dataset_id !== datasetId ||
    capability.dataset_id !== datasetId || capability.source !== "jquants_premium_core" ||
    capability.policy_version !== "source-capability/v3" ||
    premium.path !== capability.upstream_locator ||
    coverage.dataset_id !== datasetId || coverage.policy_version !== "collection-coverage/v3" ||
    coverage.collection_scope !== "jquants_premium_core" ||
    coverage.segment_granularity !== "calendar_month" ||
    query.authority !== "target-reviewed-route/v2" ||
    query.coverage_segment_granularity !== "calendar_month"
  ) throw new AcquisitionRequestRejected("registry_contract");

  const path = requireString(premium.path, "registry_path");
  if (!/^\/v2\/[a-z0-9/-]+$/.test(path)) {
    throw new AcquisitionRequestRejected("registry_path");
  }
  const earliest = requireString(capability.earliest_official_availability, "registry_official_start");
  if (!validDate(earliest) || coverage.history_target_start !== earliest) {
    throw new AcquisitionRequestRejected("registry_official_start");
  }
  const queryMode = query.mode;
  const dayParameter = query.day_parameter;
  if (
    (queryMode !== "calendar_month_sliced" && queryMode !== "calendar_month_range" &&
      queryMode !== "official_business_day_sliced") ||
    ((queryMode === "calendar_month_sliced" ||
      queryMode === "official_business_day_sliced") && dayParameter !== "date") ||
    (queryMode === "calendar_month_range" && dayParameter !== null)
  ) throw new AcquisitionRequestRejected("registry_query");
  const calendarBinding = query.official_calendar_binding;
  const requiresOfficialCalendar = queryMode === "official_business_day_sliced";
  if (requiresOfficialCalendar) {
    const binding = requireObject(calendarBinding, "registry_official_calendar");
    if (!exactKeys(binding, [
      "authority", "path", "ordered_parameters", "response_data_field",
      "date_field", "holiday_division_field", "tse_business_day_values",
      "complete_calendar_day_sequence_required", "cross_segment_resolution",
    ]) || binding.authority !== "target-and-receipt-independent-reproof/v1" ||
      binding.path !== "/v2/markets/calendar" ||
      canonicalJson(binding.ordered_parameters) !== canonicalJson(["from", "to"]) ||
      binding.response_data_field !== "data" || binding.date_field !== "Date" ||
      binding.holiday_division_field !== "HolDiv" ||
      canonicalJson(binding.tse_business_day_values) !== canonicalJson(["1", "2"]) ||
      binding.complete_calendar_day_sequence_required !== true ||
      binding.cross_segment_resolution !== "FORBIDDEN") {
      throw new AcquisitionRequestRejected("registry_official_calendar");
    }
  } else if (calendarBinding !== undefined) {
    throw new AcquisitionRequestRejected("registry_official_calendar");
  }

  const paginationParameters = new Map<string, string>();
  if (!Array.isArray(query.pagination)) throw new AcquisitionRequestRejected("registry_pagination");
  for (const raw of query.pagination) {
    const item = requireObject(raw, "registry_pagination");
    if (!exactKeys(item, ["query_parameter", "response_field"]) ||
      item.query_parameter !== "pagination_key" || item.response_field !== "pagination_key" ||
      paginationParameters.size !== 0) {
      throw new AcquisitionRequestRejected("registry_pagination");
    }
    paginationParameters.set("pagination_key", "pagination_key");
  }
  if (!Array.isArray(query.allowed_ignored_response_fields) ||
    !query.allowed_ignored_response_fields.every((item) => item === "cursor") ||
    query.allowed_ignored_response_fields.length > 1) {
    throw new AcquisitionRequestRejected("registry_response_fields");
  }
  const ignored = new Set<string>(query.allowed_ignored_response_fields as string[]);
  if ((ignored.has("cursor")) !== ["fins_details", "fins_summary"].includes(datasetId)) {
    throw new AcquisitionRequestRejected("registry_response_fields");
  }

  const typedDayParameter: "date" | null = queryMode !== "calendar_month_range"
    ? "date"
    : null;
  return {
    datasetId, path, queryMode, dayParameter: typedDayParameter,
    earliestOfficialAvailability: earliest,
    sourceCapabilityDigest: await canonicalDigest(capability),
    datasetContractDigest: await canonicalDigest({ canonical_dataset: canonical, premium_contract: premium }),
    coveragePolicyDigest: await canonicalDigest(coverage),
    queryContractDigest: await canonicalDigest(query),
    registryDigest: registry.digest,
    paginationParameters,
    allowedIgnoredResponseFields: ignored,
    requiresOfficialCalendar,
  };
}

function monthEnd(month: string): string {
  const [yearText, monthText] = month.split("-");
  const year = Number(yearText);
  const monthNumber = Number(monthText);
  if (!Number.isSafeInteger(year) || year < 1900 || year > 9999 || monthNumber < 1 || monthNumber > 12) {
    throw new AcquisitionRequestRejected("segment_shape");
  }
  return new Date(Date.UTC(year, monthNumber, 0)).toISOString().slice(0, 10);
}

function currentJst(now: Date): { month: string; day: number; minutes: number; previousMonth: string } {
  if (Number.isNaN(now.getTime())) throw new AcquisitionRequestRejected("target_clock");
  const shifted = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const month = shifted.toISOString().slice(0, 7);
  const previousMonth = new Date(Date.UTC(
    shifted.getUTCFullYear(), shifted.getUTCMonth() - 1, 1,
  )).toISOString().slice(0, 7);
  return {
    month,
    day: shifted.getUTCDate(),
    minutes: shifted.getUTCHours() * 60 + shifted.getUTCMinutes(),
    previousMonth,
  };
}

function resolveClosedSegment(
  route: GovernedRoute,
  request: JquantsAcquisitionRequestV2,
  now: Date,
): { start: string; end: string } {
  const month = request.segment_id;
  const first = `${month}-01`;
  const end = monthEnd(month);
  const current = currentJst(now);
  if (month >= current.month || end < route.earliestOfficialAvailability ||
    (month === current.previousMonth && current.day === 1 && current.minutes < 60)) {
    throw new AcquisitionRequestRejected("segment_not_closed");
  }
  const start = first < route.earliestOfficialAvailability
    ? route.earliestOfficialAvailability
    : first;
  if (request.segment_start !== start || request.segment_end !== end) {
    throw new AcquisitionRequestRejected("segment_descriptor");
  }
  return { start, end };
}

/**
 * Build the only initial request shape accepted by the governed target.
 *
 * Receipt callers choose only a reviewed dataset and a closed calendar month.
 * Contract digests and the official partial first-month boundary are derived
 * from the target registry that is bundled into both sides of the binding.
 */
export async function buildGovernedInitialRequest(input: {
  environment: AcquisitionEnvironment;
  datasetId: string;
  segmentId: string;
  acquisitionNonce: string;
  now: Date;
}): Promise<JquantsAcquisitionRequestV2> {
  const route = await resolveRoute(input.datasetId);
  const first = `${input.segmentId}-01`;
  const candidate: JquantsAcquisitionRequestV2 = {
    schema_version: "jquants-acquisition-rpc-request/v2",
    environment: input.environment,
    operation: "fetch_governed_page",
    dataset_id: input.datasetId,
    segment_id: input.segmentId,
    segment_start: first < route.earliestOfficialAvailability
      ? route.earliestOfficialAvailability
      : first,
    segment_end: monthEnd(input.segmentId),
    acquisition_nonce: input.acquisitionNonce,
    source_capability_digest: route.sourceCapabilityDigest,
    dataset_contract_digest: route.datasetContractDigest,
    coverage_policy_digest: route.coveragePolicyDigest,
    query_contract_digest: route.queryContractDigest,
    target_registry_digest: route.registryDigest,
    continuation_token: null,
  };
  const resolved = await resolveGovernedRequest(
    candidate,
    input.environment,
    input.now,
  );
  return resolved.request;
}

export async function resolveGovernedRequest(
  raw: unknown,
  targetEnvironment: AcquisitionEnvironment,
  now: Date,
): Promise<ResolvedGovernedRequest> {
  const request = decodeRequest(raw);
  if (request.environment !== targetEnvironment) {
    throw new AcquisitionRequestRejected("environment_mismatch");
  }
  const route = await resolveRoute(request.dataset_id);
  if (
    request.source_capability_digest !== route.sourceCapabilityDigest ||
    request.dataset_contract_digest !== route.datasetContractDigest ||
    request.coverage_policy_digest !== route.coveragePolicyDigest ||
    request.query_contract_digest !== route.queryContractDigest ||
    request.target_registry_digest !== route.registryDigest
  ) throw new AcquisitionRequestRejected("contract_digest_mismatch");
  const segment = resolveClosedSegment(route, request, now);
  const identity = {
    schema_version: request.schema_version,
    environment: request.environment,
    operation: request.operation,
    dataset_id: request.dataset_id,
    segment_id: request.segment_id,
    segment_start: request.segment_start,
    segment_end: request.segment_end,
    acquisition_nonce: request.acquisition_nonce,
    source_capability_digest: request.source_capability_digest,
    dataset_contract_digest: request.dataset_contract_digest,
    coverage_policy_digest: request.coverage_policy_digest,
    query_contract_digest: request.query_contract_digest,
    target_registry_digest: request.target_registry_digest,
  };
  return {
    request,
    requestDigest: await canonicalDigest(request),
    requestIdentityDigest: await canonicalDigest(identity),
    route,
    segmentStart: segment.start,
    segmentEnd: segment.end,
  };
}

export function targetRegistryLimits(): TargetRegistryLimits {
  const document = requireObject(generatedRegistry, "registry_shape");
  if (
    document.official_origin !== "https://api.jquants.com" ||
    document.maximum_redirects !== 0 ||
    !Number.isSafeInteger(document.maximum_page_bytes) || Number(document.maximum_page_bytes) < 1 || Number(document.maximum_page_bytes) > 32 * 1024 * 1024 ||
    !Number.isSafeInteger(document.maximum_segment_pages) || Number(document.maximum_segment_pages) < 1 || Number(document.maximum_segment_pages) > 10000 ||
    !Number.isSafeInteger(document.maximum_provider_pages_per_slice) || Number(document.maximum_provider_pages_per_slice) < 1 || Number(document.maximum_provider_pages_per_slice) > 1000 ||
    !Number.isSafeInteger(document.continuation_ttl_seconds) || Number(document.continuation_ttl_seconds) < 60 || Number(document.continuation_ttl_seconds) > 86400
  ) throw new AcquisitionRequestRejected("registry_limits");
  return {
    officialOrigin: document.official_origin,
    maximumRedirects: 0,
    maximumPageBytes: Number(document.maximum_page_bytes),
    maximumSegmentPages: Number(document.maximum_segment_pages),
    maximumProviderPagesPerSlice: Number(document.maximum_provider_pages_per_slice),
    continuationTtlSeconds: Number(document.continuation_ttl_seconds),
  };
}
