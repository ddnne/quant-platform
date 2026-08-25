/** Discovery caps are rate/safety limits, never proof of archive exhaustion. */

export type DiscoveryRunStatus = "pass" | "fail" | "partial";

export interface DiscoveryCapInput {
  yearPagesFound: number;
  maxYearPages: number;
  dataFilesDiscovered: number;
  dataFilesStored: number;
  maxDataFiles: number;
  fetchErrors: number;
}

export interface DiscoveryCapSemantics {
  year_page_cap_hit: boolean;
  data_file_cap_hit: boolean;
  pagination_exhausted: boolean;
  status: DiscoveryRunStatus;
}

/** 0 = unlimited. Unset MAX_YEAR_PAGES defaults to 1. */
export function parseYearPageCap(raw: string | undefined): number {
  return Math.max(0, Math.min(100, Number(raw ?? "1") || 0));
}

/** 0 = unlimited. Unset MAX_DATA_FILES stays unlimited. */
export function parseDataFileCap(raw: string | undefined): number {
  return Math.max(0, Math.min(10_000, Number(raw ?? "0") || 0));
}

/** Cap-truncated discovery is never coverage-eligible. */
export function discoveryCapSemantics(
  input: DiscoveryCapInput,
): DiscoveryCapSemantics {
  const year_page_cap_hit =
    input.maxYearPages > 0 && input.yearPagesFound > input.maxYearPages;
  const data_file_cap_hit =
    input.maxDataFiles > 0 && input.dataFilesDiscovered > input.maxDataFiles;
  const capHit = year_page_cap_hit || data_file_cap_hit;
  const fullFetch =
    input.dataFilesStored === input.dataFilesDiscovered &&
    input.fetchErrors === 0 &&
    input.dataFilesStored > 0;
  const pagination_exhausted = fullFetch && !capHit;

  let status: DiscoveryRunStatus = "partial";
  if (input.dataFilesDiscovered === 0 && input.yearPagesFound === 0) {
    status = "partial";
  } else if (pagination_exhausted) {
    status = "pass";
  } else if (input.dataFilesStored === 0 && !capHit) {
    status = "fail";
  }
  return {
    year_page_cap_hit,
    data_file_cap_hit,
    pagination_exhausted,
    status,
  };
}

/** Coverage-eligible only when pagination truly exhausted. */
export function discoveryIsCoverageEligible(
  sem: Pick<DiscoveryCapSemantics, "pagination_exhausted" | "status">,
): boolean {
  return sem.status === "pass" && sem.pagination_exhausted === true;
}
