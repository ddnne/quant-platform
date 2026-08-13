# COMPLETE +2 proof — margin + short_sale 2026-07 (Track A3)

**Date:** 2026-08-13  
**Operator path:** R2 raw pages → local `jquants_records` normalize/upsert → `scripts/issue_receipts_parallel.py` (empty-raw ban) → fail-closed `publish_ops_projection.py --apply-remote`  
**Mass / READY / Phase7:** still **NO-GO / OFF**  
**cf_premium_backfill:** **not** launched (bars mid-hole + fins paced runner already live; dual-run ban)

## Summary

| Metric | PRE | POST |
|--------|----:|-----:|
| Local segment COMPLETE | **501** | **503** |
| Remote segment COMPLETE | **501** | **503** |
| Net this batch | | **+2 sealed** |
| margin detail_json C8 | **pass** lag 1d≤7 | **pass** lag 1d≤7 (`source=receipt_observed_end`) |

Local struct months were **exhausted** at 501 after prior +7. Honest path for +2 (previously DEFER in +7 proof):

1. R2 `quant-raw/raw/{dataset}/{run_id}/page-*.json` with `row_count>0` (empty pages rejected).  
2. Normalize usable pages into local research mirror `jquants_records` for **2026-07** only.  
3. Mirror one usable non-empty page under `data/raw/jquants/2026/08/13/{dataset}_date=2026-07-01_from_r2_run….json`.  
4. `issue_receipts_parallel.py --struct-hint` issue + ledger refresh → **+2**.  
5. Fail-closed publish (`local COMPLETE ≥ remote`, no `--force-apply-remote`).

## Segments sealed (run_id 900518–900519)

| dataset | segment_id | structured_row_count | receipt run_id | raw source |
|---------|------------|---------------------:|---------------:|------------|
| `markets_short_sale_report` | 2026-07 | 17804 | **900518** | R2 week run **217** page-000001 (`from=2026-07-01`…`to=2026-07-07`; usable non-empty) |
| `markets_margin_interest` | 2026-07 | 21277 | **900519** | R2 month run **2513** page-000003 (`from=2026-07-01`…`to=2026-07-31`; pages 1–2 empty → skipped) |

Struct rebuild evidence:

| dataset | source pages | local July rows POST |
|---------|--------------|---------------------:|
| `markets_margin_interest` | run 2513 nonempty pages 3/10/17/24/31 | **21277** (matches remote D1 hot) |
| `markets_short_sale_report` | week runs 217/220/222/224/227 nonempty pages; July filter | **17804** (remote D1 hot 17806; 2 key-collision collapse) |

Eligibility: `TRUSTED_COLLECTION` / `SignedReceiptAuthority` / `dev-receipt-v1`.  
Reconciliation: script sets `raw_row_count == structured_row_count`.

### Empty-raw ban

| Candidate | outcome |
|-----------|---------|
| Margin run 2513 page-000001/000002 (`{"data":[]}` / 12B) | not used as seal raw |
| Short-sale cron day envelopes | not used |
| Nonempty multi-row pages above | usable → accepted |

## C8 (margin detail_json) — wrangler confirmed

| Field | Value |
|-------|-------|
| dataset status | **PARTIAL** (15 COMPLETE / 149 PARTIAL segs; not dataset COMPLETE) |
| `observed_end` | **`2026-08-12`** |
| detail C8 | **pass** `1 day(s)`, `latest_event_time=2026-08-12`, `max_days=7`, `source=receipt_observed_end` |
| Aug execute | **skipped** (C8 already pass; bars `cf_premium` live → dual-run ban) |

## Publish (fail-closed, no `--force-apply-remote`)

| Step | Guard | Generation |
|------|-------|------------|
| Apply | `complete_count_guard ok local=503 remote=501 force=False` | remote `projgen-d754e700cb7748b986c256ff4ce7c19f` (`generated_at=2026-08-13T13:19:26.473192+00:00`, age_seconds=0) |

Verified remote D1 after apply:

- segment COMPLETE **503**  
- sealed `markets_margin_interest/2026-07` + `markets_short_sale_report/2026-07` **COMPLETE**  
- projection **FRESH**  
- margin detail_json C8 still **pass**

Phase7 **OFF**. Mass / READY **NO-GO**.

## Explicit non-claims / DEFER

| Item | Status |
|------|--------|
| COMPLETE without raw | **Forbidden** |
| Empty `{"data":[]}` raw | **Rejected** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| `cf_premium_backfill` | **Not** started this session |
| Dataset-level COMPLETE for margin / short_sale | still **PARTIAL** |
| margin months 2025-03…2026-06 / short_sale other months | **DEFER** (need more real raw+struct) |
| short_sale local July row count 17804 vs remote 17806 | accepted (natural_key collapse); not fabricated |
