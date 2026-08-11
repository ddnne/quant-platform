/** Shared J-Quants Premium-core dataset contract.
 *
 * Python loads this same JSON file from `data_contracts.loader`; no dataset
 * path, natural key, or PIT timestamp policy is duplicated in Worker source.
 */

import contractDocument from "../../../../data_contracts/jquants_premium_core.json";
import coverageDocument from "../../../../data_contracts/collection_coverage.json";

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
  collection_scope: string;
  history_target_start: string;
  history_target_end_rule: string;
  coverage_mode: string;
  expected_frequency: string;
  universe_rule: string;
  raw_retention_required: boolean;
  structured_reconciliation_required: boolean;
  segment_granularity: "calendar_month";
  governance_tier: "governed" | "experimental";
}

const rawContracts = contractDocument.datasets as ContractJson[];

if (contractDocument.schema_version !== 2 || rawContracts.length !== 23) {
  throw new Error("invalid J-Quants Premium-core contract document");
}

const coverageDefaults = coverageDocument.defaults as CollectionCoveragePolicy;
const coverageRows = coverageDocument.datasets as Record<
  string, Partial<CollectionCoveragePolicy>
>;
if (
  coverageDocument.schema_version !== 2 ||
  coverageDocument.policy_version !== "collection-coverage/v2" ||
  Object.keys(coverageRows).length !== rawContracts.length
) {
  throw new Error("invalid collection Coverage V2 contract document");
}

export const PREMIUM_CORE_DATASETS: DatasetSpec[] = rawContracts.map((contract) => ({
  ...contract,
  id: contract.dataset_id,
  dateMode: contract.date_mode,
  dayParam: contract.day_param,
  codeParam: contract.code_param,
  coverage: { ...coverageDefaults, ...coverageRows[contract.dataset_id] },
}));

const BY_ID: ReadonlyMap<string, DatasetSpec> = new Map(
  PREMIUM_CORE_DATASETS.map((contract) => [contract.id, contract]),
);

export function isPremiumCore(id: string): boolean {
  return BY_ID.has(id);
}

export function datasetById(id: string): DatasetSpec | undefined {
  return BY_ID.get(id);
}
