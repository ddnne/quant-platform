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
  bulkPath?: string;       // confirmed /v2/bulk/... path when bulk-preferred
  // Default date param strategy for the scheduled run. "range" -> fetch a
  // recent from/to window (incremental); "today" -> single-day market-wide
  // (or day fan-out for backfill); "none" -> no date param.
  //
  // IMPORTANT: many J-Quants V2 endpoints require `date` OR `code` and reject
  // bare `from`/`to` without a code. For market-wide scheduled pulls use
  // dateMode "today" (sends `date=YYYY-MM-DD`). Only endpoints that accept
  // from/to without code should use "range".
  dateMode: "range" | "today" | "none";
  // Query key for the single-day param (default "date"). Some series use
  // disc_date / scheduled_date instead.
  dayParam?: string;
  // Whether the dataset accepts a `code` filter (kept for future fan-out).
  codeParam: boolean;
}

export const PREMIUM_CORE_DATASETS: DatasetSpec[] = [
  // date OR code required — market-wide cron uses date=
  { id: "equities_master",                  path: "/v2/equities/master",                    bulk: "api", dateMode: "today", codeParam: true  },
  // bulk path /v2/bulk/... is not available on this plan (403). Use REST + date=.
  { id: "equities_bars_daily",              path: "/v2/equities/bars/daily",                bulk: "api", dateMode: "today", codeParam: true  },
  { id: "equities_bars_daily_am",           path: "/v2/equities/bars/daily/am",             bulk: "api", dateMode: "today", codeParam: true  },
  { id: "fins_summary",                     path: "/v2/fins/summary",                       bulk: "api", dateMode: "today", codeParam: true  },
  { id: "fins_details",                     path: "/v2/fins/details",                       bulk: "api", dateMode: "today", codeParam: true  },
  // dividend rejects bare from/to — requires date or code
  { id: "fins_dividend",                    path: "/v2/fins/dividend",                      bulk: "api", dateMode: "today", codeParam: true  },
  // exactly one of code | date | scheduled_date
  { id: "fins_earnings_date",               path: "/v2/fins/earnings-date",                 bulk: "api", dateMode: "today", dayParam: "date", codeParam: true  },
  // from/to OK without code
  { id: "equities_earnings_calendar",       path: "/v2/equities/earnings-calendar",         bulk: "api", dateMode: "range", codeParam: false },
  { id: "markets_calendar",                 path: "/v2/markets/calendar",                   bulk: "api", dateMode: "range", codeParam: false },
  // investor-types: from/to often works; keep range for multi-day window
  { id: "equities_investor_types",          path: "/v2/equities/investor-types",            bulk: "api", dateMode: "range", codeParam: true  },
  { id: "indices_bars_daily_topix",         path: "/v2/indices/bars/daily/topix",           bulk: "api", dateMode: "range", codeParam: false },
  // indices daily: code OR date (not bare from/to)
  { id: "indices_bars_daily",               path: "/v2/indices/bars/daily",                 bulk: "api", dateMode: "today", codeParam: true  },
  // derivatives: date required for market-wide
  { id: "derivatives_bars_daily_options_225", path: "/v2/derivatives/bars/daily/options/225", bulk: "api", dateMode: "today", codeParam: false },
  { id: "derivatives_bars_daily_futures",   path: "/v2/derivatives/bars/daily/futures",     bulk: "api", dateMode: "today", codeParam: true  },
  { id: "derivatives_bars_daily_options",   path: "/v2/derivatives/bars/daily/options",     bulk: "api", dateMode: "today", codeParam: true  },
  { id: "markets_margin_interest",          path: "/v2/markets/margin-interest",            bulk: "api", dateMode: "today", codeParam: true  },
  // margin-alert: code required with from/to — use date= for market day
  { id: "markets_margin_alert",             path: "/v2/markets/margin-alert",               bulk: "api", dateMode: "today", codeParam: true  },
  // short-ratio: date or s33
  { id: "markets_short_ratio",              path: "/v2/markets/short-ratio",                bulk: "api", dateMode: "today", codeParam: true  },
  // short-sale-report: code | disc_date | calc_date
  { id: "markets_short_sale_report",        path: "/v2/markets/short-sale-report",          bulk: "api", dateMode: "today", dayParam: "disc_date", codeParam: true  },
  { id: "markets_breakdown",                path: "/v2/markets/breakdown",                  bulk: "api", dateMode: "today", codeParam: true  },
  // EDINET-derived (Premium surface, NOT the standalone EDINET DB addon).
  { id: "edinet_major_shareholders",        path: "/v2/edinet/major-shareholders",          bulk: "api", dateMode: "today", codeParam: true  },
  { id: "edinet_cross_shareholdings",       path: "/v2/edinet/cross-shareholdings",         bulk: "api", dateMode: "today", codeParam: true  },
  { id: "edinet_large_volume_shareholders", path: "/v2/edinet/large-volume-shareholders",   bulk: "api", dateMode: "today", codeParam: true  },
];

export function isPremiumCore(id: string): boolean {
  return PREMIUM_CORE_DATASETS.some((d) => d.id === id);
}

export function datasetById(id: string): DatasetSpec | undefined {
  return PREMIUM_CORE_DATASETS.find((d) => d.id === id);
}
