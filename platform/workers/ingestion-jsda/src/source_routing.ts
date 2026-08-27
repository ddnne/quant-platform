import type { DatasetId } from "./queue_contract";

/** Official JSDA file-routing contract. Classification is table-driven. */
export const FILE_ROUTING_VERSION = "jsda-official-file-routing/v2" as const;

export type FreshnessClass = "archive" | "rolling";

export type LocatorPolicy =
  | "rolling_current_file"
  | "annual_file_current_year_rolling"
  | "dated_publication_archive";

interface DatasetFileRouting {
  readonly locator_policy: LocatorPolicy;
  readonly year_token?: RegExp;
  readonly publication_date_tokens?: readonly RegExp[];
}

/**
 * Source-object freshness is a dataset locator policy, not a filename comment.
 * Rolling locators are re-observed per governed run; dated archives are not.
 */
export const JSDA_FILE_ROUTING: Readonly<Record<DatasetId, DatasetFileRouting>> = {
  jsda_tokyo_repo_rates: {
    locator_policy: "rolling_current_file",
  },
  jsda_corporate_bond_transactions: {
    locator_policy: "annual_file_current_year_rolling",
    year_token: /^torihiki(20\d{2})\.[a-z0-9]+$/i,
  },
  jsda_otc_bond_reference_prices: {
    locator_policy: "dated_publication_archive",
    publication_date_tokens: [
      /(?:^|[^0-9])(20\d{6})(?:[^0-9]|$)/,
      /^[sS]\d{6}\./,
    ],
  },
};

function basenameOf(raw: string): string {
  return new URL(raw).pathname.split("/").filter(Boolean).pop() || "";
}

function governedYear(requestedAt: string): number | null {
  if (!/^\d{4}-/.test(requestedAt)) return null;
  const year = Number(requestedAt.slice(0, 4));
  return Number.isInteger(year) ? year : null;
}

export function classifyFetchFreshness(
  dataset: DatasetId,
  targetUrl: string,
  requestedAt: string,
): FreshnessClass {
  const routing = JSDA_FILE_ROUTING[dataset];
  const name = basenameOf(targetUrl);
  if (routing.locator_policy === "rolling_current_file") {
    return "rolling";
  }
  if (routing.locator_policy === "annual_file_current_year_rolling") {
    const match = routing.year_token?.exec(name);
    const fileYear = match ? Number(match[1]) : null;
    const runYear = governedYear(requestedAt);
    if (fileYear !== null && runYear !== null && fileYear === runYear) {
      return "rolling";
    }
    return "archive";
  }
  const dated = (routing.publication_date_tokens ?? []).some((token) =>
    token.test(name),
  );
  return dated ? "archive" : "rolling";
}

export function observationEpoch(
  freshness: FreshnessClass,
  runKey: string,
): string {
  return freshness === "rolling" ? runKey : "archive";
}
