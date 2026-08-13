# COMPLETE +3 proof — margin 2026-06/08 + short_sale 2026-06 (Track A3)

**Date:** 2026-08-13  
**Operator path:** R2 raw week pages → local `jquants_records` normalize/upsert → `scripts/issue_receipts_parallel.py` (empty-raw ban) → fail-closed `publish_ops_projection.py --apply-remote`  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**cf_premium_backfill:** **not** launched (bars mid-hole execute already live; dual-run ban)

## Summary

| Metric | PRE | POST |
|--------|----:|-----:|
| Local segment COMPLETE | **503** | **506** |
| Remote segment COMPLETE | **503** | **506** |
| Net this batch | | **+3 sealed** |

Local struct+raw sealables were **exhausted** at 503 after margin/ssr 2026-07. Honest path for +3:

1. Remote R2 week manifests (`row_count>0`, empty pages skipped).  
2. Download nonempty `page-*.json` for June margin runs **164–167** and June SSR runs **208/211/213/215**.  
3. `normalize_generic` → local `SqliteStore.upsert('jquants_records')` for **2026-06** only (margin) + SSR June.  
4. Mirror one usable non-empty page under `data/raw/jquants/2026/08/13/`.  
5. `issue_receipts_parallel.py --struct-hint` → **+3** (also picked up margin **2026-08** with pre-mirrored run **2519** p7 usable raw + 4259 struct rows for `2026-08-07`).  
6. Fail-closed publish (`local COMPLETE ≥ remote`, no `--force-apply-remote`).

## Segments sealed (run_id 900523–900525)

| dataset | segment_id | structured_row_count | receipt run_id | raw source |
|---------|------------|---------------------:|---------------:|------------|
| `markets_short_sale_report` | 2026-06 | 16260 | **900523** | R2 week run **208** page-000001 (`from=2026-06-03`…`to=2026-06-09`; + weeks 211/213/215 for struct) |
| `markets_margin_interest` | 2026-08 | 4259 | **900524** | R2 week run **2519** page-000007 (`Date=2026-08-07`; pages 1/3 empty → skipped) |
| `markets_margin_interest` | 2026-06 | 17051 | **900525** | R2 week runs **164–167** page-000003 each (June 3–30 weeks; empty p1/p2 rejected) |

Struct rebuild evidence:

| dataset / month | source pages | local rows POST | notes |
|-----------------|--------------|----------------:|-------|
| margin 2026-06 | runs 164–167 nonempty p3 | **17051** | date range `2026-06-05`…`2026-06-26` |
| margin 2026-08 | run 2519 nonempty p7 | **4259** | single observed day `2026-08-07` (partial month evidence; still real raw) |
| short_sale 2026-06 | runs 208/211/213/215 nonempty pages | **16260** | natural_key collapse from ~20822 raw rows |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Reconciliation: script sets `raw_row_count == structured_row_count`.

### Empty-raw ban

| Candidate | outcome |
|-----------|---------|
| Margin week pages 000001/000002 (`{"data":[]}` / 12B) | rejected / not used as seal raw |
| Margin run 2519 pages 1/3 empty | skipped |
| Nonempty multi-row pages above | usable → accepted |

## Publish (fail-closed, no `--force-apply-remote`)

| Step | Guard | Generation |
|------|-------|------------|
| Apply | `complete_count_guard ok local=506 remote=503 force=False` | `projgen-a2391c9fb2334eb6b4573c4f3598dc82` (`generated_at=2026-08-13T13:35:37.726377+00:00`, age_seconds=0) |

Verified remote D1 after apply:

- segment COMPLETE **506**  
- sealed three segments **COMPLETE**  
- projection **FRESH**  

Phase7 **OFF**. Mass / READY **NO-GO**.

## Explicit non-claims / DEFER

| Item | Status |
|------|--------|
| COMPLETE without raw | **Forbidden** |
| Empty `{"data":[]}` raw | **Rejected** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| `cf_premium_backfill` | **Not** started this session |
| Dataset-level COMPLETE for margin / short_sale | still **PARTIAL** |
| margin 2026-08 full-month depth | **partial evidence only** (one day / 4259 rows) — further raw weeks welcome |
| margin 2025-03…2026-05 / short_sale other months | **DEFER** (need more real raw+struct) |
