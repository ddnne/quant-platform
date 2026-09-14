/** AUTO-GENERATED from one retained canonical + Coverage snapshot.
 * DO NOT HAND-EDIT. Regenerate: python scripts/generate_governed_js.py
 * membership_digest=sha256:7a22fd8412c8e26a39a636ec8a1f04d906aaf9513641a591be37fb790467b583
 * receipt_source_digest=sha256:e3d24a2facfcdfef0887789bc1e1ce5de10f42da54e03ee2a692cbeccc3795c4
 */
export const GOVERNED_DATASETS = Object.freeze([
  "derivatives_bars_daily_futures",
  "derivatives_bars_daily_options",
  "derivatives_bars_daily_options_225",
  "edinet_cross_shareholdings",
  "edinet_large_volume_shareholders",
  "edinet_major_shareholders",
  "equities_bars_daily",
  "equities_bars_daily_am",
  "equities_earnings_calendar",
  "equities_investor_types",
  "equities_master",
  "equities_valuation",
  "fins_details",
  "fins_dividend",
  "fins_earnings_date",
  "fins_summary",
  "indices_bars_daily",
  "indices_bars_daily_topix",
  "jsda_corporate_bond_transactions",
  "jsda_otc_bond_reference_prices",
  "jsda_tokyo_repo_rates",
  "markets_breakdown",
  "markets_calendar",
  "markets_margin_alert",
  "markets_margin_interest",
  "markets_short_ratio",
  "markets_short_sale_report"
]);

export const GOVERNED_MEMBERSHIP_DIGEST = "sha256:7a22fd8412c8e26a39a636ec8a1f04d906aaf9513641a591be37fb790467b583";

export const GOVERNED_DATASET_SET = new Set(GOVERNED_DATASETS);

/** @type {Readonly<Record<string, "jquants" | "jsda">>} */
export const CANONICAL_RECEIPT_SOURCE_BY_DATASET = Object.freeze({
  "derivatives_bars_daily_futures": "jquants",
  "derivatives_bars_daily_options": "jquants",
  "derivatives_bars_daily_options_225": "jquants",
  "edinet_cross_shareholdings": "jquants",
  "edinet_large_volume_shareholders": "jquants",
  "edinet_major_shareholders": "jquants",
  "equities_bars_daily": "jquants",
  "equities_bars_daily_am": "jquants",
  "equities_bars_minute": "jquants",
  "equities_earnings_calendar": "jquants",
  "equities_investor_types": "jquants",
  "equities_master": "jquants",
  "equities_trades": "jquants",
  "equities_valuation": "jquants",
  "fins_details": "jquants",
  "fins_dividend": "jquants",
  "fins_earnings_date": "jquants",
  "fins_summary": "jquants",
  "indices_bars_daily": "jquants",
  "indices_bars_daily_topix": "jquants",
  "jsda_corporate_bond_transactions": "jsda",
  "jsda_otc_bond_reference_prices": "jsda",
  "jsda_tokyo_repo_rates": "jsda",
  "markets_breakdown": "jquants",
  "markets_calendar": "jquants",
  "markets_margin_alert": "jquants",
  "markets_margin_interest": "jquants",
  "markets_short_ratio": "jquants",
  "markets_short_sale_report": "jquants",
  "td_bulk": "jquants",
  "td_files": "jquants",
  "td_list": "jquants"
});

export const CANONICAL_RECEIPT_SOURCE_DIGEST = "sha256:e3d24a2facfcdfef0887789bc1e1ce5de10f42da54e03ee2a692cbeccc3795c4";

export const CANONICAL_JSDA_DATASET_SET = new Set(
  Object.entries(CANONICAL_RECEIPT_SOURCE_BY_DATASET)
    .filter(([, source]) => source === "jsda")
    .map(([dataset]) => dataset),
);
