# W101 / w0819d — OTC planned historical backfill batch5 (2026-08-19)

**Wave:** `w0819d` / **W101** / Track A  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy:** planned official PARTIAL backfill (NOT tip-only densify invent)  
**Forbidden held:** invent COMPLETE · empty COMPLETE · fake densify · Mass ON · Dataset COMPLETE force · pin retune · GO/Mass/READY/live  
**Plan:** [`.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md`](../../.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md) (Batch5)  
**Prior:** [`w0819c_w100_otc_backfill_batch4_20260819.md`](w0819c_w100_otc_backfill_batch4_20260819.md)  
**Artifacts:** [`.glm-logs/w0819d_w101_otc5_dd_close/`](../../.glm-logs/w0819d_w101_otc5_dd_close/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **4852** |
| OTC COMPLETE AFTER (local + D1) | **4952** (**+100**) |
| OTC PARTIAL BEFORE → AFTER | **3932 → 3832** (−100) |
| Batch5 scope | pre-2008 archive newer-first before span start `2006-10-19` |
| COMPLETE span AFTER | **2006-05-29 … 2026-08-20** (was `2006-10-19…2026-08-20`) |
| Dataset-level status | **PARTIAL** held (4952/8784) — never force COMPLETE |
| Platform COMPLETE segs | **8241 → 8341** (+100) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Tip `S260821+` | **404** unpublished — tip-wait (**no invent**) |
| Mass | **NO-GO** |
| 3 default pins | **unchanged** (`pins_untouched=true`) |

**Return: 4852 → 4952 (+100).** Within Batch5 band (~50–100 official days). Tip unpublished, not sealed.

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE local | POST local | POST remote |
|--------|----------:|-----------:|------------:|
| Dataset COMPLETE | 22 | 22 | 22 |
| Dataset PARTIAL | 4 | 4 | 4 |
| OTC COMPLETE | **4852** | **4952** | **4952** |
| OTC PARTIAL | 3932 | **3832** | **3832** |
| Platform COMPLETE segs | 8241 | **8341** | **8341** |
| empty COMPLETE | 0 | 0 | 0 |
| all_checks_pass | true | true | true |
| Mass | NO-GO | NO-GO | NO-GO |

Logs: `pre_complete22_health_local.json` · `post_complete22_health_local.json` · `post_complete22_health_remote.json`

---

## 2. Batch5 composition

| bucket | n | span | result |
|--------|--:|------|--------|
| Remaining 2006 archive newer-first | **100** | `2006-10-18…2006-05-29` | sealed COMPLETE |
| Tip `S260821`…`S260826` | — | unpublished | **404** tip-wait |
| Weekend / holiday 404 | — | not on archive index | stay PARTIAL (**no invent**) |

**CF worker:** `https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev`  
**Flow:** `/discover?year=2006` → official `month_csv` ∩ live PARTIAL ∧ `day < 2006-10-19` newer-first → `/fetch` → seal  
**Gate (FULL_OK_HISTORICAL):** HTTP **200** ∧ size **> 100_000** ∧ non-HTML ∧ parse **nz > 0** ∧ raw≈struct.  
**Wave id on receipts:** `w0819d_w101_otc_batch5` · policy `W101_planned_official_historical_partial_backfill`.

Artifacts: `otc_discover_2006.json` · `otc_batch5_items.json` · `otc_batch5_full_ok.json` · `otc_batch5_download_progress.jsonl` · `otc_seal_result.json` · `otc_batch5_summary.json` · `tip_probe_S260821plus.json`

### Discover ∩ PARTIAL

- Archive `archive2006.html` via CF `/discover`: **n_reference=250** (`month_csv` 248).  
- Still PARTIAL official 2006 days with `day < 2006-10-19`: **198** (pool).  
- Batch5 take: **100** 2006 newer-first.

### Batch5 days (100)

`2006-10-18`, `2006-10-17`, `2006-10-16`, `2006-10-13`, `2006-10-12`, `2006-10-11`, `2006-10-10`, `2006-10-06`, `2006-10-05`, `2006-10-04`, `2006-10-03`, `2006-10-02`, `2006-09-29`, `2006-09-28`, `2006-09-27`, `2006-09-26`, `2006-09-25`, `2006-09-22`, `2006-09-21`, `2006-09-20`, `2006-09-19`, `2006-09-15`, `2006-09-14`, `2006-09-13`, `2006-09-12`, `2006-09-11`, `2006-09-08`, `2006-09-07`, `2006-09-06`, `2006-09-05`, `2006-09-04`, `2006-09-01`, `2006-08-31`, `2006-08-30`, `2006-08-29`, `2006-08-28`, `2006-08-25`, `2006-08-24`, `2006-08-23`, `2006-08-22`, `2006-08-21`, `2006-08-18`, `2006-08-17`, `2006-08-16`, `2006-08-15`, `2006-08-14`, `2006-08-11`, `2006-08-10`, `2006-08-09`, `2006-08-08`, `2006-08-07`, `2006-08-04`, `2006-08-03`, `2006-08-02`, `2006-08-01`, `2006-07-31`, `2006-07-28`, `2006-07-27`, `2006-07-26`, `2006-07-25`, `2006-07-24`, `2006-07-21`, `2006-07-20`, `2006-07-19`, `2006-07-18`, `2006-07-14`, `2006-07-13`, `2006-07-12`, `2006-07-11`, `2006-07-10`, `2006-07-07`, `2006-07-06`, `2006-07-05`, `2006-07-04`, `2006-07-03`, `2006-06-30`, `2006-06-29`, `2006-06-28`, `2006-06-27`, `2006-06-26`, `2006-06-23`, `2006-06-22`, `2006-06-21`, `2006-06-20`, `2006-06-19`, `2006-06-16`, `2006-06-15`, `2006-06-14`, `2006-06-13`, `2006-06-12`, `2006-06-09`, `2006-06-08`, `2006-06-07`, `2006-06-06`, `2006-06-05`, `2006-06-02`, `2006-06-01`, `2006-05-31`, `2006-05-30`, `2006-05-29`

CSV sizes **896,259–940,435** bytes (HTML ~46KB excluded). **html=0 · small=0 · empty COMPLETE=0**.

---

## 3. Seal / ledger

1. CF `/discover?year=2006` → official archive reference codes  
2. CF `/fetch` → local raw under `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/` (**100/100 OK**)  
3. Parse + normalize → facts upsert (triggers off during bulk)  
4. Signed SUCCESS receipt + `record_collection_receipt` (**100/100 SEALED**, run_id **908672…908771**)  
5. Tip `S260821+` probe — all **404**; **not sealed**  
6. `refresh_coverage_ledger` → segment COMPLETE (**4852→4952**)  
7. `sync_dataset_coverage_from_segments` → dataset **PARTIAL** held (4952/8784)  
8. `publish_ops_projection --apply-remote` · `ops_reeval_freshness` → FRESH · Mass **NO-GO**

Empty COMPLETE **0**. No invent / no fake densify. PARTIAL −100 while COMPLETE +100. No new inventory tip day.

---

## 4. Tip probe `S260821+`

| code | result |
|------|--------|
| `S260821` | **404** all paths |
| `S260822` | **404** all paths |
| `S260823` | **404** all paths |
| `S260824` | **404** all paths |
| `S260825` | **404** all paths |
| `S260826` | **404** all paths |
| `full_ok_n` | **0** |

`S260821+` tip-wait only. **No invent.** Artifact: `tip_probe_S260821plus.json`.

---

## 5. Dataset status

OTC dataset remains **PARTIAL** until true archive reconciliation criteria are met. **Mass NO-GO.** Dataset COMPLETE **22** held. 3-default pins **untouched**. GO/READY/live **not declared**.

Next: continue pre-2008 archive newer-first (remaining ~98 official 2006 days before `2006-05-29`, then 2005→…); tip-wait `S260821+`.

---

## 6. Return

```json
{
  "otc_complete_pre": 4852,
  "otc_complete_post": 4952,
  "otc_partial_pre": 3932,
  "otc_partial_post": 3832,
  "delta": 100,
  "batch5_sealed_complete": 100,
  "tip_sealed_complete": 0,
  "span_post": ["2006-05-29", "2026-08-20"],
  "platform_complete_post": 8341,
  "dataset_status": "PARTIAL",
  "empty_otc_complete": 0,
  "tip_probe_full_ok_n_unpublished": 0,
  "mass": "NO-GO",
  "pins_untouched": true,
  "implementer": "GLM5.3",
  "orchestrator_implemented": false
}
```

**COMPLETE: 4852 → 4952 (+100).** Dataset remains **PARTIAL**.
