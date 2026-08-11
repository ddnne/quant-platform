/** Compatibility wrapper around contract-driven Worker identity semantics. */

import { datasetById, type AvailabilityPolicy } from "./catalog";
import { pickAvailableAt as pickFromContract, sessionCloseJst } from "./identity";

export { sessionCloseJst };
export type { AvailabilityPolicy };

export function policyForDataset(datasetId: string): AvailabilityPolicy {
  return datasetById(datasetId)?.available_at_policy ?? "ingest_time_conservative";
}

export function pickAvailableAt(
  row: Record<string, unknown>,
  datasetId: string,
  ingestedAt: string,
): string {
  const spec = datasetById(datasetId);
  if (!spec) return ingestedAt;
  return pickFromContract(row, spec, ingestedAt);
}
