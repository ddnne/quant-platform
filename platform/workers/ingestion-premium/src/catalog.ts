/**
 * Phase 3.5 — J-Quants Premium **core** closed-loop dataset set.
 *
 * Single source of truth for the CF schedule. MUST mirror the Python
 * `PREMIUM_CORE_DATASETS` in `ingestion/jquants/catalog.py`. A Python test
 * (`tests/test_phase35_premium_set.py`) asserts the two lists agree — so
 * adding a Premium core dataset in Python without adding it here (or vice
 * versa) fails CI.
 *
 * Add-ons (`equities_bars_minute`, `equities_trades`, `td_*`) are
 * deliberately excluded — they are out of scope for the required schedule.
 */

export interface DatasetSpec {
  id: string;
  path: string;            // /v2/... REST path
  bulk: "api" | "bulk";
  // Default date param strategy for the scheduled run. "range" -> fetch a
  // recent from/to window (incremental); "today" -> fetch the single date
  // "today" (UTC days); "none" -> no date param (full snapshot).
  dateMode: "range" | "today" | "none";
  // Whether the dataset accepts a `code` filter (kept for future fan-out).
  codeParam: boolean;
}

export const PREMIUM_CORE_DATASETS: DatasetSpec[] = [
  { id: "equities_master",                  path: "/v2/equities/master",                  bulk: "api",  dateMode: "today", codeParam: true  },
  { id: "equities_bars_daily",              path: "/v2/equities/bars/daily",              bulk: "bulk", dateMode: "range", codeParam: true  },
  { id: "equities_bars_daily_am",           path: "/v2/equities/bars/daily/am",           bulk: "api",  dateMode: "today", codeParam: true  },
  { id: "fins_summary",                     path: "/v2/fins/summary",                     bulk: "api",  dateMode: "today", codeParam: true  },
  { id: "fins_details",                     path: "/v2/fins/details",                     bulk: "api",  dateMode: "today", codeParam: true  },
  { id: "fins_dividend",                    path: "/v2/fins/dividend",                    bulk: "api",  dateMode: "range", codeParam: true  },
  { id: "fins_earnings_date",               path: "/v2/fins/earnings-date",               bulk: "api",  dateMode: "none",  codeParam: true  },
  { id: "equities_earnings_calendar",       path: "/v2/equities/earnings-calendar",       bulk: "api",  dateMode: "range", codeParam: false },
  { id: "markets_calendar",                 path: "/v2/markets/calendar",                 bulk: "api",  dateMode: "range", codeParam: false },
  { id: "equities_investor_types",          path: "/v2/equities/investor-types",          bulk: "api",  dateMode: "range", codeParam: true  },
  { id: "indices_bars_daily_topix",         path: "/v2/indices/bars/daily/topix",         bulk: "api",  dateMode: "range", codeParam: false },
  { id: "indices_bars_daily",               path: "/v2/indices/bars/daily",               bulk: "api",  dateMode: "range", codeParam: true  },
  { id: "derivatives_bars_daily_options_225",path: "/v2/derivatives/bars/daily/options/225",bulk: "api", dateMode: "range", codeParam: false },
  { id: "derivatives_bars_daily_futures",   path: "/v2/derivatives/bars/daily/futures",   bulk: "api",  dateMode: "range", codeParam: true  },
  { id: "derivatives_bars_daily_options",   path: "/v2/derivatives/bars/daily/options",   bulk: "api",  dateMode: "range", codeParam: true  },
  { id: "markets_margin_interest",          path: "/v2/markets/margin-interest",          bulk: "api",  dateMode: "range", codeParam: true  },
  { id: "markets_margin_alert",             path: "/v2/markets/margin-alert",             bulk: "api",  dateMode: "range", codeParam: true  },
  { id: "markets_short_ratio",              path: "/v2/markets/short-ratio",              bulk: "api",  dateMode: "range", codeParam: true  },
  { id: "markets_short_sale_report",        path: "/v2/markets/short-sale-report",        bulk: "api",  dateMode: "range", codeParam: true  },
  { id: "markets_breakdown",                path: "/v2/markets/breakdown",                bulk: "api",  dateMode: "range", codeParam: true  },
  // EDINET-derived (Premium surface, NOT the standalone EDINET DB addon).
  { id: "edinet_major_shareholders",        path: "/v2/edinet/major-shareholders",        bulk: "api",  dateMode: "today", codeParam: true  },
  { id: "edinet_cross_shareholdings",       path: "/v2/edinet/cross-shareholdings",       bulk: "api",  dateMode: "today", codeParam: true  },
  { id: "edinet_large_volume_shareholders", path: "/v2/edinet/large-volume-shareholders", bulk: "api",  dateMode: "today", codeParam: true  },
];

export function isPremiumCore(id: string): boolean {
  return PREMIUM_CORE_DATASETS.some((d) => d.id === id);
}

export function datasetById(id: string): DatasetSpec | undefined {
  return PREMIUM_CORE_DATASETS.find((d) => d.id === id);
}
