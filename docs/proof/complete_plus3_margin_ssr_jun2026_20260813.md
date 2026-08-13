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

1. Remote R2 week manifests (`row_count>0`; empty pages rejected by empty-raw ban).  
2. Download nonempty `page-*.json` for June margin runs **164–167** (p3) and June SSR runs **206/208/211/213/215** (nonempty pages).  
3. `normalize_generic` → local `SqliteStore.upsert('jquants_records')` filtered to **2026-06** / **2026-08**.  
4. Mirror one usable non-empty page under `data/raw/jquants/2026/08/13/`.  
5. `issue_receipts_parallel.py --struct-hint` issue + ledger refresh → **+3**.  
6. Fail-closed publish (`local COMPLETE ≥ remote`, no `--force-apply-remote`).

## Segments sealed (primary run_id 900520–900522)

| dataset | segment_id | structured_row_count | receipt run_id | raw source |
|---------|------------|---------------------:|---------------:|------------|
| `markets_short_sale_report` | 2026-06 | 16260 | **900520** (re-issue **900523**) | R2 week run **208** page-000001 (`from=2026-06-03`…`to=2026-06-09`; weeks 206/211/213/215 also normalized for struct) |
| `markets_margin_interest` | 2026-08 | 4259 | **900521** (re-issue **900524**) | R2 run **2519** page-000007 (`from=2026-08-01`…`to=2026-08-12`; empty pages skipped) |
| `markets_margin_interest` | 2026-06 | 17051 | **900522** (re-issue **900525**) | R2 week runs **164–167** page-000003 each (June 3–30 weeks; p1/p2 empty → rejected) |

Struct rebuild evidence:

| dataset / month | source pages | local rows POST | notes |
|-----------------|--------------|----------------:|-------|
| margin 2026-06 | runs 164–167 nonempty p3 | **17051** | 4 distinct observed days (weekly series) |
| margin 2026-08 | run 2519 nonempty p7 | **4259** | single observed day in-window (partial month; real raw) |
| short_sale 2026-06 | runs 206/208/211/213/215 nonempty pages | **16260** | natural_key collapse from ~21100 raw rows |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Reconciliation: script sets `raw_row_count == structured_row_count`.

### Empty-raw ban

| Candidate | outcome |
|-----------|---------|
| Margin week pages 000001/000002 (`{"data":[]}` / 12B) | rejected / not used as seal raw |
| Cron empty envelopes | rejected by `_is_usable_raw` |
| Nonempty multi-row pages above | usable → accepted |

## Publish (fail-closed, no `--force-apply-remote`)

| Step | Guard | Generation |
|------|-------|------------|
| First apply | `complete_count_guard ok local=506 remote=503 force=False` | `projgen-a2391c9fb2334eb6b4573c4f3598dc82` (`generated_at=2026-08-13T13:35:37.726377+00:00`) |
| Re-publish (same 506) | `complete_count_guard ok local=506 remote=506 force=False` | `projgen-2bb40f808a8a4b278d7bc571114ddd89` (`generated_at=2026-08-13T13:36:35.511110+00:00`, age_seconds=0) |

Verified remote D1 after apply:

- segment COMPLETE **506**  
- sealed `markets_margin_interest/2026-06`, `markets_margin_interest/2026-08`, `markets_short_sale_report/2026-06` **COMPLETE**  
- projection **FRESH**  
- margin dataset still **PARTIAL**; detail_json C8 remains **pass** (lag ≤7 via receipt SoT)

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
