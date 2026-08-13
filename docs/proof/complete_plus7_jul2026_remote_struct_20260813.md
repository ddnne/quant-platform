# COMPLETE +7 proof — 2026-07 remote struct + R2 raw seal (Track A3)

**Date:** 2026-08-13  
**Operator path:** remote D1 `jquants_records` (2026-07) → local upsert → R2 raw mirror (`page-NNNNNN`) → `scripts/issue_receipts_parallel.py` (empty-raw ban) → fail-closed `publish_ops_projection.py --apply-remote`  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**cf_premium_backfill:** **not** launched (coordinate with acquisition owner; ban this session)

## Summary

| Metric | PRE | POST |
|--------|----:|-----:|
| Local segment COMPLETE | **494** | **501** |
| Remote segment COMPLETE | **494** | **501** |
| Net this batch | | **+7 sealed** |
| Remote `raw_retention_manifests` | 3535 | **4099** total / **3712** COMPLETE completeness (acquisition continuing elsewhere) |

Local struct months were **exhausted** at 494. Honest path for +7:

1. Remote D1 held **2026-07** structured rows not present in local research mirror.  
2. Export via `wrangler d1 execute quant-ingest --remote` → upsert local `jquants_records`.  
3. R2 `quant-raw/raw/{dataset}/{run_id}/page-000001.json` → local mirror under `data/raw/jquants/2026/08/13/{dataset}_date=2026-07-01_from_r2_run….json` (usable non-empty only; empty-raw ban). Investor used existing history page run **67** (`from=2013-01-04`…`to=2026-08-10`).  
4. `issue_receipts_parallel.py --struct-hint` issue + ledger refresh → **+7**.  
5. Fail-closed publish (`local COMPLETE ≥ remote`, no `--force-apply-remote`).

## Segments sealed (run_id 900511–900517)

| dataset | segment_id | structured_row_count | receipt run_id | raw source |
|---------|------------|---------------------:|---------------:|------------|
| `indices_bars_daily` | 2026-07 | 3344 | **900511** | R2 run **148** |
| `fins_earnings_date` | 2026-07 | 746 | **900512** | R2 run **141** |
| `fins_dividend` | 2026-07 | 1213 | **900513** | R2 run **122** |
| `equities_investor_types` | 2026-07 | 16 | **900514** | R2 run **67** (existing history mirror) |
| `edinet_major_shareholders` | 2026-07 | 55 | **900515** | R2 run **288** |
| `edinet_large_volume_shareholders` | 2026-07 | 1113 | **900516** | R2 run **357** |
| `edinet_cross_shareholdings` | 2026-07 | 49 | **900517** | R2 run **316** |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Reconciliation: script sets `raw_row_count == structured_row_count`.

### Empty-raw ban

| Candidate | outcome |
|-----------|---------|
| Wrong key `page-0.json` / empty download | rejected (0 bytes deleted) |
| Correct `page-000001.json` multi-row bodies | usable → accepted |
| Cron `{"data":[]}` envelopes | rejected by `_is_usable_raw` (unchanged) |

## Publish (fail-closed, no `--force-apply-remote`)

| Step | Guard | Generation |
|------|-------|------------|
| Apply | `complete_count_guard ok local=501 remote=494 force=False` | `projgen-63c1a8f5df4a4b34844e4e15cedcf575` |

Verified remote D1 after apply:

- segment COMPLETE **501**  
- sealed seven `*/2026-07` segments **COMPLETE**  
- projection **FRESH** (`generated_at=2026-08-13T12:15:46.731549+00:00`, age_seconds=0)  

Phase7 **OFF**. Mass / READY **NO-GO**.

## Explicit non-claims / DEFER

| Item | Status |
|------|--------|
| COMPLETE without raw | **Forbidden** |
| Empty `{"data":[]}` raw | **Rejected** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| `cf_premium_backfill` | **Not** started |
| Dataset-level COMPLETE beyond calendar + tokyo-repo | still **2** datasets |
| `markets_short_sale_report` / `markets_margin_interest` 2026-07 | **DEFER** (large remote struct; not sealed this batch) |
| fins_earnings_date future months (2026-09+) | **DEFER** (no coverage segments + need raw/struct path) |
