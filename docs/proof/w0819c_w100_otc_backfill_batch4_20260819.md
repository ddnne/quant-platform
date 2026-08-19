# W100 / w0819c — OTC planned historical backfill batch4 (2026-08-19)

**Wave:** `w0819c` / **W100** / Track A  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy:** planned official PARTIAL backfill (NOT tip-only densify invent)  
**Forbidden held:** invent COMPLETE · empty COMPLETE · fake densify · Mass ON · Dataset COMPLETE force  
**Plan:** [`.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md`](../../.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md) (Batch4)  
**Artifacts:** [`.glm-logs/w0819c_w100_daily_path_dd_otc4/`](../../.glm-logs/w0819c_w100_daily_path_dd_otc4/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **4751** |
| OTC COMPLETE AFTER (local + D1) | **4852** (**+101**) |
| OTC PARTIAL BEFORE → AFTER | **4032 → 3932** (−100) |
| Batch4 scope | pre-2008 archive newer-first before span start `2007-03-19` |
| COMPLETE span AFTER | **2006-10-19 … 2026-08-20** (was `2007-03-19…2026-08-19`) |
| Dataset-level status | **PARTIAL** held (4852/8784) — never force COMPLETE |
| Platform COMPLETE segs | **8140 → 8241** (+101) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Tip `S260820` | **FULL_OK** sealed (size 2,155,282) |
| Tip `S260821+` | **404** unpublished — tip-wait (**no invent**) |
| Mass | **NO-GO** |
| 3 default pins | **unchanged** (`pins_untouched=true`) |

**Return: 4751 → 4852 (+101).** Within Batch4 band (~50–100 official days) plus one published tip day.

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE local | POST local | POST remote |
|--------|----------:|-----------:|------------:|
| Dataset COMPLETE | 22 | 22 | 22 |
| Dataset PARTIAL | 4 | 4 | 4 |
| OTC COMPLETE | **4751** | **4852** | **4852** |
| OTC PARTIAL | 4032 | **3932** | **3932** |
| Platform COMPLETE segs | 8140 | **8241** | **8241** |
| empty COMPLETE | 0 | 0 | 0 |
| all_checks_pass | true | true | true |
| Mass | NO-GO | NO-GO | NO-GO |

Logs: `pre_complete22_health_local.json` · `post_complete22_health_local.json` · `post_complete22_health_remote.json`

---

## 2. Batch4 composition

| bucket | n | span | result |
|--------|--:|------|--------|
| Remaining 2007 archive newer-first | **50** | `2007-03-16…2007-01-04` | sealed COMPLETE |
| 2006 archive newer-first | **50** | `2006-12-29…2006-10-19` | sealed COMPLETE |
| Tip `S260820` | **1** | `2026-08-20` | sealed COMPLETE (FULL_OK_MODERN) |
| Tip `S260821`…`S260825` | — | unpublished | **404** tip-wait |
| Weekend / holiday 404 | — | e.g. `2007-03-17`/`2007-03-18` | stay PARTIAL (**no invent**) |

**CF worker:** `https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev`  
**Flow:** `/discover?year=2007|2006` → official `month_csv` ∩ live PARTIAL → `/fetch` → seal  
**Gate (FULL_OK_HISTORICAL):** HTTP **200** ∧ size **> 100_000** ∧ non-HTML ∧ parse **nz > 0** ∧ raw≈struct.  
**Gate (FULL_OK_MODERN tip):** HTTP **200** ∧ size **> 1_500_000** ∧ parse nz.  
**Wave id on receipts:** `w0819c_w100_otc_batch4` / `w0819c_w100_otc_tip` · policy `W100_planned_official_historical_partial_backfill`.

Artifacts: `otc_discover_2007.json` · `otc_discover_2006.json` · `otc_batch4_items.json` · `otc_batch4_full_ok.json` · `otc_batch4_download_progress.jsonl` · `otc_seal_result.json` · `otc_batch4_summary.json` · `tip_probe_S260820plus.json`

### Discover ∩ PARTIAL

- Archive `archive2007.html` via CF `/discover`: **n_reference=247** (`month_csv` 245).  
- Archive `archive2006.html` via CF `/discover`: **n_reference=250** (`month_csv` 248).  
- Still PARTIAL official 2007 days with `day < 2007-03-19`: **50** (pool; all taken).  
- Still PARTIAL official 2006 days: **248** (pool).  
- Batch4 take: **50** remaining 2007 + **50** 2006 newer-first = **100**.

### Batch4 days (100)

2007 (50): `2007-03-16`, `2007-03-15`, `2007-03-14`, `2007-03-13`, `2007-03-12`, `2007-03-09`, `2007-03-08`, `2007-03-07`, `2007-03-06`, `2007-03-05`, `2007-03-02`, `2007-03-01`, `2007-02-28`, `2007-02-27`, `2007-02-26`, `2007-02-23`, `2007-02-22`, `2007-02-21`, `2007-02-20`, `2007-02-19`, `2007-02-16`, `2007-02-15`, `2007-02-14`, `2007-02-13`, `2007-02-09`, `2007-02-08`, `2007-02-07`, `2007-02-06`, `2007-02-05`, `2007-02-02`, `2007-02-01`, `2007-01-31`, `2007-01-30`, `2007-01-29`, `2007-01-26`, `2007-01-25`, `2007-01-24`, `2007-01-23`, `2007-01-22`, `2007-01-19`, `2007-01-18`, `2007-01-17`, `2007-01-16`, `2007-01-15`, `2007-01-12`, `2007-01-11`, `2007-01-10`, `2007-01-09`, `2007-01-05`, `2007-01-04`

2006 (50): `2006-12-29`, `2006-12-28`, `2006-12-27`, `2006-12-26`, `2006-12-25`, `2006-12-22`, `2006-12-21`, `2006-12-20`, `2006-12-19`, `2006-12-18`, `2006-12-15`, `2006-12-14`, `2006-12-13`, `2006-12-12`, `2006-12-11`, `2006-12-08`, `2006-12-07`, `2006-12-06`, `2006-12-05`, `2006-12-04`, `2006-12-01`, `2006-11-30`, `2006-11-29`, `2006-11-28`, `2006-11-27`, `2006-11-24`, `2006-11-22`, `2006-11-21`, `2006-11-20`, `2006-11-17`, `2006-11-16`, `2006-11-15`, `2006-11-14`, `2006-11-13`, `2006-11-10`, `2006-11-09`, `2006-11-08`, `2006-11-07`, `2006-11-06`, `2006-11-02`, `2006-11-01`, `2006-10-31`, `2006-10-30`, `2006-10-27`, `2006-10-26`, `2006-10-25`, `2006-10-24`, `2006-10-23`, `2006-10-20`, `2006-10-19`

CSV sizes **913,906–971,578** bytes (HTML ~46KB excluded). **html=0 · small=0 · empty COMPLETE=0**.

---

## 3. Seal / ledger

1. CF `/discover?year=2007|2006` → official archive reference codes  
2. CF `/fetch` → local raw under `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/` (**100/100 OK**)  
3. Parse + normalize → facts upsert (triggers off during bulk)  
4. Signed SUCCESS receipt + `record_collection_receipt` (**100/100 SEALED**, run_id **908571…908670**)  
5. Tip `S260820` fetch+seal (**run_id 908671**, expected_items **12411**)  
6. `refresh_coverage_ledger` → segment COMPLETE (**4751→4852**)  
7. `sync_dataset_coverage_from_segments` → dataset **PARTIAL** held (4852/8784)  
8. `publish_ops_projection --apply-remote` · `ops_reeval_freshness` → FRESH · Mass **NO-GO**

Empty COMPLETE **0**. No invent / no fake densify. New tip day adds one inventory segment (8783→8784 total) so PARTIAL −100 while COMPLETE +101.

---

## 4. Tip probe `S260820+`

| code | result |
|------|--------|
| `S260820` | **FULL_OK** flat_csv HTTP 200 size **2,155,282** — sealed |
| `S260821` | **404** all paths |
| `S260822` | **404** all paths |
| `S260823` | **404** all paths |
| `S260824` | **404** all paths |
| `S260825` | **404** all paths |
| `full_ok_n` (unpublished remainder) | **0** |

`S260821+` tip-wait only. **No invent.** Artifact: `tip_probe_S260820plus.json`.

---

## 5. Dataset status

OTC dataset remains **PARTIAL** until true archive reconciliation criteria are met. **Mass NO-GO.** Dataset COMPLETE **22** held. 3-default pins **untouched**.

Next: continue pre-2008 archive newer-first (remaining ~198 official 2006 days before `2006-10-19`, then 2005→…); tip-wait `S260821+`.

---

## 6. Return

```json
{
  "otc_complete_pre": 4751,
  "otc_complete_post": 4852,
  "otc_partial_pre": 4032,
  "otc_partial_post": 3932,
  "delta": 101,
  "batch4_sealed_complete": 100,
  "tip_sealed_complete": 1,
  "span_post": ["2006-10-19", "2026-08-20"],
  "platform_complete_post": 8241,
  "dataset_status": "PARTIAL",
  "empty_otc_complete": 0,
  "tip_probe_full_ok_n_unpublished": 0,
  "mass": "NO-GO",
  "pins_untouched": true,
  "implementer": "GLM5.3",
  "orchestrator_implemented": false
}
```

**COMPLETE: 4751 → 4852 (+101).** Dataset remains **PARTIAL**.
