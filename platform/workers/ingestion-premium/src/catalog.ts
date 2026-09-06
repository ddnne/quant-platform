/** Shared J-Quants Premium-core dataset contract.
 *
 * Python loads this same JSON file from `data_contracts.loader`; no dataset
 * path, natural key, or PIT timestamp policy is duplicated in Worker source.
 */

import contractDocument from "../../../../packages/data_plane/data_contracts/jquants_premium_core.json";
import coverageDocument from "../../../../packages/data_plane/data_contracts/collection_coverage.json";
import jsdaDocument from "../../../../packages/data_plane/data_contracts/jsda_governed.json";

export type DateMode = "range" | "today" | "none";
export type AvailabilityPolicy =
  | "session_close"
  | "explicit_timestamp_field"
  | "explicit_disclosure_date"
  | "known_publication_lag"
  | "calendar_prepublished"
  | "ingest_time_conservative";
export type EventTimePolicy =
  | "session_close"
  | "explicit_timestamp_field"
  | "observation_date";

interface ContractJson {
  dataset_id: string;
  path: string;
  group: string;
  date_mode: DateMode;
  natural_key_fields: string[];
  event_time_policy: EventTimePolicy;
  event_time_fields: string[];
  available_at_policy: AvailabilityPolicy;
  availability_field: string | null;
  known_publication_lag: string | null;
  fallback_policy: "ingest_time_conservative";
  observation_grain: string;
  bulk: "api" | "bulk";
  params: string[];
  code_param: boolean;
  day_param?: string;
  session?: string;
  field_aliases?: Record<string, string[]>;
  assumption: string;
}

export interface DatasetSpec extends ContractJson {
  id: string;
  dateMode: DateMode;
  dayParam?: string;
  codeParam: boolean;
  bulkPath?: string;
  coverage: CollectionCoveragePolicy;
}

export interface CollectionCoveragePolicy {
  policy_version: "collection-coverage/v2" | "collection-coverage/v3";
  collection_scope: string;
  history_target_start: string;
  history_target_end_rule: string;
  coverage_mode: string;
  expected_frequency: string;
  universe_rule: string;
  raw_retention_required: boolean;
  structured_reconciliation_required: boolean;
  segment_granularity: string;
  governance_tier: "governed" | "experimental";
}

const rawContracts = contractDocument.datasets as ContractJson[];

if (contractDocument.schema_version !== 2 || rawContracts.length !== 23) {
  throw new Error("invalid J-Quants Premium-core contract document");
}

const coverageDefaults = coverageDocument.defaults as Omit<
  CollectionCoveragePolicy,
  "policy_version"
>;
const coverageRows = coverageDocument.datasets as Record<
  string, Partial<CollectionCoveragePolicy>
>;
if (
  coverageDocument.schema_version !== 2 ||
  coverageDocument.policy_version !== "collection-coverage/v2"
) {
  throw new Error("invalid collection Coverage V2 contract document");
}
// Coverage catalog may include JSDA + all governed sets (26); Premium core is 23.
// Require every Premium dataset has a coverage row rather than equal counts.
for (const contract of rawContracts) {
  if (!coverageRows[contract.dataset_id]) {
    throw new Error(
      `missing Coverage V2 row for Premium dataset ${contract.dataset_id}`,
    );
  }
  const policyVersion =
    coverageRows[contract.dataset_id]?.policy_version ??
    coverageDocument.policy_version;
  if (
    policyVersion !== "collection-coverage/v2" &&
    policyVersion !== "collection-coverage/v3"
  ) {
    throw new Error(
      `unsupported Coverage policy for Premium dataset ${contract.dataset_id}`,
    );
  }
}

export const PREMIUM_CORE_DATASETS: DatasetSpec[] = rawContracts.map((contract) => ({
  ...contract,
  id: contract.dataset_id,
  dateMode: contract.date_mode,
  dayParam: contract.day_param,
  codeParam: contract.code_param,
  coverage: {
    ...coverageDefaults,
    ...coverageRows[contract.dataset_id],
    policy_version:
      coverageRows[contract.dataset_id]?.policy_version ??
      coverageDocument.policy_version as CollectionCoveragePolicy["policy_version"],
  },
}));

const BY_ID: ReadonlyMap<string, DatasetSpec> = new Map(
  PREMIUM_CORE_DATASETS.map((contract) => [contract.id, contract]),
);

export function isPremiumCore(id: string): boolean {
  return BY_ID.has(id);
}

const JSDA_FIELD_ALIASES: Record<string, Record<string, string[]>> = {
  jsda_otc_bond_reference_prices: {
    publication_label_date: ["年月日", "日付", "取引日", "営業日"],
    security_code: ["銘柄コード", "code", "コード"],
    bond_name: ["銘柄名", "name", "発行体"],
  },
};

function jsdaDatasetSpec(datasetId: string): DatasetSpec | undefined {
  const rows = jsdaDocument.datasets as Array<{
    dataset_id: string;
    index_url: string;
    source_product: string;
    natural_key_fields: string[];
    effective_time_policy: string;
  }>;
  const row = rows.find((entry) => entry.dataset_id === datasetId);
  const coveragePartial = coverageRows[datasetId];
  const policyVersion =
    coveragePartial?.policy_version ?? coverageDocument.policy_version;
  if (
    row === undefined ||
    coveragePartial === undefined ||
    policyVersion !== "collection-coverage/v3"
  ) {
    return undefined;
  }
  const coverage: CollectionCoveragePolicy = {
    ...coverageDefaults,
    ...coveragePartial,
    policy_version: "collection-coverage/v3",
  };
  return {
    id: datasetId,
    dataset_id: datasetId,
    path: row.index_url,
    group: "jsda",
    date_mode: "none",
    natural_key_fields: row.natural_key_fields,
    event_time_policy: "observation_date",
    event_time_fields: row.natural_key_fields.includes("publication_label_date")
      ? ["publication_label_date"]
      : ["as_of_date"],
    available_at_policy: "ingest_time_conservative",
    availability_field: null,
    known_publication_lag: null,
    fallback_policy: "ingest_time_conservative",
    observation_grain: coverage.segment_granularity,
    bulk: "bulk",
    params: [],
    code_param: false,
    field_aliases: JSDA_FIELD_ALIASES[datasetId],
    assumption: row.source_product,
    dateMode: "none",
    codeParam: false,
    coverage,
  };
}

export function datasetById(id: string): DatasetSpec | undefined {
  return BY_ID.get(id) ?? jsdaDatasetSpec(id);
}

export function governedDatasetSpec(id: string): DatasetSpec | undefined {
  return datasetById(id);
}

export type CatalogProjectionRow = {
  dataset_id: string;
  display_name: string;
  source: "jquants" | "jsda";
  coverage: CollectionCoveragePolicy;
};

export function catalogProjectionRows(): CatalogProjectionRow[] {
  const rows: CatalogProjectionRow[] = PREMIUM_CORE_DATASETS.map((spec) => ({
    dataset_id: spec.id,
    display_name: spec.id,
    source: "jquants" as const,
    coverage: spec.coverage,
  }));
  const seen = new Set(rows.map((row) => row.dataset_id));
  for (const [datasetId, partial] of Object.entries(coverageRows)) {
    if (seen.has(datasetId)) continue;
    const policyVersion =
      partial.policy_version ?? coverageDocument.policy_version;
    if (
      policyVersion !== "collection-coverage/v2" &&
      policyVersion !== "collection-coverage/v3"
    ) {
      continue;
    }
    rows.push({
      dataset_id: datasetId,
      display_name: datasetId,
      source: datasetId.startsWith("jsda_") ? "jsda" : "jquants",
      coverage: {
        ...coverageDefaults,
        ...partial,
        policy_version: policyVersion,
      },
    });
  }
  return rows.sort((left, right) =>
    left.dataset_id < right.dataset_id ? -1 : left.dataset_id > right.dataset_id ? 1 : 0,
  );
}

export type SegmentGrain =
  | "calendar_month"
  | "same_trading_day_am_snapshot"
  | "collection_cutoff_snapshot"
  | "official_archive_index_day"
  | "official_archive_year"
  | "source_time_series_file";

export type GovernedReceiptIdentity = {
  source: "jquants" | "jsda";
  contract_id: string;
  dataset_id: string;
  segment_grain: SegmentGrain;
  coverage: CollectionCoveragePolicy;
};

const GRAIN_BY_SEGMENT: Record<string, SegmentGrain> = {
  calendar_month: "calendar_month",
  same_trading_day_am_snapshot: "same_trading_day_am_snapshot",
  collection_cutoff_snapshot: "collection_cutoff_snapshot",
  official_archive_index_day: "official_archive_index_day",
  official_archive_year: "official_archive_year",
  source_time_series_file: "source_time_series_file",
};

export function governedReceiptIdentity(
  datasetId: string,
): GovernedReceiptIdentity | undefined {
  const spec = datasetById(datasetId);
  const catalog = catalogProjectionRows().find((row) => row.dataset_id === datasetId);
  const coverage = spec?.coverage ?? catalog?.coverage;
  if (coverage === undefined || coverage.policy_version !== "collection-coverage/v3") {
    return undefined;
  }
  const source = catalog?.source ?? (datasetId.startsWith("jsda_") ? "jsda" as const : "jquants" as const);
  const grain = GRAIN_BY_SEGMENT[coverage.segment_granularity] ?? (
    source === "jquants" ? "calendar_month" as const : undefined
  );
  if (grain === undefined) return undefined;
  return {
    source,
    contract_id: coverage.collection_scope,
    dataset_id: datasetId,
    segment_grain: grain,
    coverage,
  };
}
