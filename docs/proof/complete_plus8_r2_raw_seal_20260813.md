# COMPLETE +8 proof — R2 raw mirror + parallel signed receipts (Track A3)

**Date:** 2026-08-13 (JST) / 2026-08-12 (UTC session)  
**Operator path:** `scripts/issue_receipts_parallel.py` (ThreadPool prepare + serial sign/write)  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**cf_premium_backfill:** **not** launched (other agent owns bars mid-hole execute)

## Summary

| Metric | PRE | POST |
|--------|----:|-----:|
| Local segment COMPLETE | **482** | **490** |
| Remote segment COMPLETE | **482** | **490** |
| Net this batch | | **+8 sealed** |

Local raw+struct sealables were **exhausted** at 482. Remaining non-COMPLETE months
with structured rows lacked local `data/raw/jquants/**` files. Honest path:

1. Read remote `raw_retention_manifests` for candidate datasets (row_count>0).
2. `wrangler r2 object get quant-raw/raw/{dataset}/{run_id}/page-*.json` → local
   mirror under `data/raw/jquants/2026/08/13/{dataset}_date=2026-08-01_from_r2_run….json`
   (usable non-empty bodies only).
3. `issue_receipts_parallel.py --struct-hint` → 8 ready, 1 skip (`no_raw`).
4. Fail-closed `publish_ops_projection.py --apply-remote` (local ≥ remote).

## Segments sealed (run_id 900496–900503)

| dataset | segment_id | structured_row_count | run_id | raw source |
|---------|------------|---------------------:|-------:|------------|
| `markets_short_sale_report` | 2026-08 | 634 | 900496 | R2 run 1574 |
| `fins_earnings_date` | 2026-08 | 18 | 900497 | R2 run 1574 |
| `fins_dividend` | 2026-08 | 135 | 900498 | R2 run 1574 |
| `fins_details` | 2026-08 | 266 | 900499 | R2 run 1574 |
| `equities_investor_types` | 2026-08 | 4 | 900500 | R2 run 889 (non-empty; latest 1574 was `{"data":[]}`) |
| `derivatives_bars_daily_options_225` | 2026-08 | 10534 | 900501 | R2 run 1574 |
| `derivatives_bars_daily_options` | 2026-08 | 42460 | 900502 | R2 run 1574 |
| `derivatives_bars_daily_futures` | 2026-08 | 126 | 900503 | R2 run 1574 |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Reconciliation: `raw_row_count == structured_row_count` (script policy).

### Skipped (empty-raw ban)

| dataset / segment | reason |
|-------------------|--------|
| `equities_investor_types/2019-12` | no local usable raw |
| `equities_investor_types` latest cron raw | `{"data":[]}` rejected by empty-raw ban |

## Code landed with this seal

| Change | Why |
|--------|-----|
| empty-raw ban: reject `{"data":[]}` envelopes | Cron empty pages must not seal |
| sticky COMPLETE segment_id fallback | Day-roll replan broke exact window match → demoted honest seals |
| retain COMPLETE inventory past UTC `target_end` | JST archive day can lead UTC calendar (OTC `2026-08-13`) |
| recompute dataset aggregate after sticky | `markets_calendar` stayed PARTIAL at dataset level with 224/224 segs COMPLETE |

## Publish (fail-closed, no `--force-apply-remote`)

| Step | Guard | Generation |
|------|-------|------------|
| Final | `local=490 remote=490 force=False` | `projgen-b19da58cd0974e4fb84802ba69ad7a0d` |

Verified: **local COMPLETE = remote COMPLETE = 490**.  
Projection status **FRESH**. Phase7 **OFF**.

### Post-publish dataset notes

| dataset | status | notes |
|---------|--------|-------|
| `markets_calendar` | **COMPLETE** | sticky + aggregate fix |
| `jsda_tokyo_repo_rates` | **COMPLETE** | unchanged |
| `markets_margin_interest` | **PARTIAL** | `observed_end=2026-08-12` via `ops_reeval_observed_window` (not COMPLETE) |
| sealed series above | still **PARTIAL** at dataset level | single month sealed |

## Explicit non-claims / DEFER

| Item | Status |
|------|--------|
| COMPLETE without raw | **Forbidden** |
| Empty `{"data":[]}` raw | **Rejected** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| `cf_premium_backfill` | **Not** started (bars mid-hole owned elsewhere) |
| Full history COMPLETE for new series | **DEFER** |
| Dataset-level COMPLETE beyond calendar + tokyo-repo | unchanged (still 2) |

## Operator command (repro dry-run)

```bash
.venv/bin/python scripts/issue_receipts_parallel.py \
  --datasets fins_details,fins_dividend,fins_earnings_date,markets_short_sale_report,equities_investor_types,derivatives_bars_daily_futures,derivatives_bars_daily_options,derivatives_bars_daily_options_225 \
  --struct-hint --limit 5 --workers 6 --dry-run --json-summary
```
