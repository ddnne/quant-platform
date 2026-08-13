# COMPLETE +4 proof — investor_types 2019-12 + edinet 2026-08 (Track A3)

**Date:** 2026-08-13  
**Operator path:** R2 raw mirror → `scripts/issue_receipts_parallel.py` (empty-raw ban) → fail-closed `publish_ops_projection.py --apply-remote`  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**cf_premium_backfill:** **not** launched

## Summary

| Metric | PRE | POST |
|--------|----:|-----:|
| Local segment COMPLETE | **490** | **494** |
| Remote segment COMPLETE | **490** | **494** |
| Net this batch | | **+4 sealed** |
| Remote `raw_retention_manifests` | ~3158+ | **3535** total / **3330** COMPLETE completeness |

Local raw+struct sealables were exhausted after the prior +8 batch except:

1. `equities_investor_types/2019-12` — structured present, no local usable raw  
2. three `edinet_* /2026-08` — structured present, no local usable raw  

Honest path (same as +8):

1. Remote `raw_retention_manifests` with `row_count>0`.  
2. `wrangler r2 object get quant-raw/raw/{dataset}/{run_id}/page-*.json` → local mirror under `data/raw/jquants/2026/08/13/` (usable non-empty bodies only; empty-raw ban).  
3. `issue_receipts_parallel.py --struct-hint` issue + ledger refresh.  
4. Fail-closed publish (`local COMPLETE ≥ remote`, no `--force-apply-remote`).

## Segments sealed

| dataset | segment_id | structured_row_count | receipt run_id | raw source |
|---------|------------|---------------------:|---------------:|------------|
| `equities_investor_types` | 2019-12 | 10 | **900504** | R2 run **67** (`from=2013-01-04`…`to=2026-08-10`, 3294 rows; usable history page) |
| `edinet_major_shareholders` | 2026-08 | 1 | **900508** | R2 run **889** (re-issue after day-roll) |
| `edinet_large_volume_shareholders` | 2026-08 | 34 | **900509** | R2 run **2506** (re-issue after day-roll) |
| `edinet_cross_shareholdings` | 2026-08 | 1 | **900510** | R2 run **889** (re-issue after day-roll) |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Reconciliation: script sets `raw_row_count == structured_row_count`.

### Day-roll note (edinet)

First edinet issue (run_id 900505–900507) used ledger `segment_end=2026-08-12`.  
Ledger refresh advanced UTC `target_end` → `segment_end=2026-08-13`, so exact-window match failed (`missing collection receipt`) and sticky COMPLETE does **not** promote first-time seals (only blocks demotion of prior COMPLETE).  

Re-issued with current window (900508–900510) → **COMPLETE**. Investor `2019-12` sealed on first issue (stable month window).

### Empty-raw ban

| Candidate | outcome |
|-----------|---------|
| Cron-empty `{"data":[]}` envelopes | rejected by `_is_usable_raw` (unchanged) |
| Mirrored R2 pages above | usable non-empty → accepted |

## Exhausted local struct months (pre-batch scan)

All other local `jquants_records` months were already COMPLETE. Remaining non-COMPLETE structured months were exactly the four sealed here. Further +N needs additional **real raw + structured** (not invented).

## Publish (fail-closed, no `--force-apply-remote`)

| Step | Guard | Generation |
|------|-------|------------|
| Apply | `complete_count_guard ok local=494 remote=490 force=False` | `projgen-5debb592dbc64b828b8bf3fb0879e527` |

Verified remote D1 after apply:

- segment COMPLETE **494**  
- projection **FRESH** (`generated_at=2026-08-13T11:39:06.806695+00:00`)  
- sealed segments above **COMPLETE** on remote  

Phase7 **OFF**. Mass / READY **NO-GO**.

## Explicit non-claims / DEFER

| Item | Status |
|------|--------|
| COMPLETE without raw | **Forbidden** |
| Empty `{"data":[]}` raw | **Rejected** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| `cf_premium_backfill` | **Not** started |
| Dataset-level COMPLETE beyond calendar + tokyo-repo | still **2** datasets |
| Full edinet history COMPLETE | **DEFER** (only 2026-08 sealed) |
| investor_types months without local structured | **DEFER** (need struct before seal) |
