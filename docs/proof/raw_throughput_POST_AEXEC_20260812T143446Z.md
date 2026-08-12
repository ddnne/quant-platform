# Raw throughput report (POST_AEXEC)

- generated_at: `2026-08-12T14:34:32.705361+00:00`
- db: `/Users/taku/GitHub/quant-platform/data/structured/ingestion.sqlite`
- note: Local/research mirror metrics. Not CF control-plane SoT unless this file was synced from D1. Do not treat as sole evidence of COMPLETE.

## raw_retention_manifests

| metric | value |
|--------|------:|
| total | 0 |
| COMPLETE | 0 |
| FAILED | 0 |
| sum_row_count | 0 |
| sum_raw_bytes | 0 |

## coverage

| metric | value |
|--------|------:|
| complete_segments | 482 |
| partial_segments | 12459 |
| complete_datasets | 2 |
| stale_datasets | 1 |
| complete_dataset_ids | jsda_tokyo_repo_rates, markets_calendar |
| stale_dataset_ids | markets_margin_interest |

## projection

- status: **FRESH**
- generation: `projgen-eb0412ea86f34c6ab51b5f312d3ebcbc`

## Track A focus

| dataset | status | complete/total segs | records | event_time span |
|---------|--------|--------------------:|--------:|-----------------|
| equities_bars_daily | PARTIAL | 12/272 | 803862 | 2024-01-04T15:00:00+09:00 → 2026-08-10T15:30:00+09:00 |
| indices_bars_daily_topix | PARTIAL | 32/224 | 635 | 2024-01-04T15:00:00+09:00 → 2026-08-10T15:30:00+09:00 |
| markets_breakdown | PARTIAL | 32/164 | 2669153 | 2024-01-04T00:00:00+09:00 → 2026-08-10T00:00:00+09:00 |
| fins_summary | PARTIAL | 5/224 | 6121 | 2024-01-04T09:00:00+09:00 → 2026-08-10T09:00:00+09:00 |
| equities_master | PARTIAL | 94/314 | 7679458 | 2015-01-05T00:00:00+09:00 → 2026-08-12T00:00:00+09:00 |
| markets_margin_interest | STALE | 14/164 | 251470 | 2024-01-12T00:00:00+09:00 → 2025-02-28T00:00:00+09:00 |

---
Evidence closure: COMPLETE only with raw+structured. This report never forges COMPLETE/READY/Mass.
