# W98 / w0819a — OTC planned historical backfill batch2 (2026-08-19)

**Wave:** `w0819a` / **W98** / Track A  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy:** planned official PARTIAL backfill (NOT tip-only densify invent)  
**Forbidden held:** invent COMPLETE · empty COMPLETE · fake densify · Mass ON · Dataset COMPLETE force  
**Plan:** [`.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md`](../../.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md) (Batch2)  
**Artifacts:** [`.glm-logs/w0819a_w98_otc_master_xs/`](../../.glm-logs/w0819a_w98_otc_master_xs/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **4551** |
| OTC COMPLETE AFTER (local + D1) | **4651** (**+100**) |
| OTC PARTIAL BEFORE → AFTER | **4232 → 4132** (−100) |
| Batch2 scope | early-2008 rem5 (`2008-01-10…01-04`) + pre-2008 archive newer-first |
| COMPLETE span AFTER | **2007-08-13 … 2026-08-19** (was `2008-01-11…`) |
| Dataset-level status | **PARTIAL** held (4651/8783) — never force COMPLETE |
| Platform COMPLETE segs | **7940 → 8040** (+100) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Tip `S260820+` | **404** unpublished — tip-wait (**no invent**) |
| Mass | **NO-GO** |

**Return: 4551 → 4651 (+100).** Within Batch2 band (~50–100 official days).

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE local | POST local | POST remote |
|--------|----------:|-----------:|------------:|
| Dataset COMPLETE | 22 | 22 | 22 |
| Dataset PARTIAL | 4 | 4 | 4 |
| OTC COMPLETE | **4551** | **4651** | **4651** |
| OTC PARTIAL | 4232 | **4132** | **4132** |
| Platform COMPLETE segs | 7940 | **8040** | **8040** |
| empty COMPLETE | 0 | 0 | 0 |
| all_checks_pass | true | true | true |
| Mass | NO-GO | NO-GO | NO-GO |

Logs: `pre_complete22_health_*.json` · `post_complete22_health_*_final.json`

---

## 2. Batch2 composition

| bucket | n | span | result |
|--------|--:|------|--------|
| Early-2008 remainder (W97 leftover) | **5** | `2008-01-10…2008-01-04` | sealed COMPLETE |
| Pre-2008 archive newer-first | **~95** | `2007-12-28…2007-08-13` | sealed COMPLETE |
| Tip `S260820+` | — | unpublished | **404** tip-wait |
| Weekend / holiday 404 | — | — | stay PARTIAL (**no invent**) |

**CF worker:** `https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev`  
**Gate (FULL_OK_HISTORICAL):** HTTP **200** ∧ size **> 100_000** ∧ non-HTML ∧ parse **nz > 0** ∧ raw≈struct.  
**Wave id on receipts:** `w0819a_w98_otc_batch2` · policy `W98_planned_official_historical_partial_backfill`.

Artifacts: `otc_batch2_items.json` · `otc_batch2_full_ok.json` · `otc_batch2_download_progress.jsonl` · `otc_seal_result.json` · `otc_batch2_summary.json`

---

## 3. Seal / ledger

1. CF `/fetch` → local raw under `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/`  
2. Parse + normalize → facts upsert (triggers off during bulk)  
3. Signed SUCCESS receipt + `record_collection_receipt`  
4. `refresh_coverage_ledger` → segment COMPLETE  
5. `sync_dataset_coverage_from_segments` → dataset **PARTIAL** held  
6. `publish_ops_projection --apply-remote` · `ops_reeval_freshness` → FRESH

Empty COMPLETE **0**. No invent / no fake densify.

---

## 4. Dataset status

OTC dataset remains **PARTIAL** until true archive reconciliation criteria are met. **Mass NO-GO.**

Next: continue pre-2008 archive newer-first; tip-wait `S260820+`.
