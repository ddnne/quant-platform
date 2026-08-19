# W105 / w0820b — OTC planned historical backfill batch9 (2026-08-20)

**Wave:** `w0820b` / **W105** / Track A  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy:** planned official PARTIAL backfill (NOT tip-only densify invent)  
**Forbidden held:** invent COMPLETE · empty COMPLETE · fake densify · Mass ON · Dataset COMPLETE force · pin retune · GO/Mass/READY/live  
**Prior:** [`w0820a_w104_otc_backfill_batch8_20260820.md`](w0820a_w104_otc_backfill_batch8_20260820.md)  
**Artifacts:** [`.glm-logs/w0820b_w105_otc9_family_hyps/`](../../.glm-logs/w0820b_w105_otc9_family_hyps/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **5252** |
| OTC COMPLETE AFTER (local + D1) | **5352** (**+100**) |
| OTC PARTIAL BEFORE → AFTER | **3532 → 3432** (−100) |
| Batch9 split | **2005 = 43** (finish remaining official) · **2004 = 57** |
| Batch9 scope | 2005 archive newer-first before span start `2005-03-08`, then 2004 official newer-first |
| COMPLETE span AFTER | **2004-10-07 … 2026-08-20** (was `2005-03-08…2026-08-20`) |
| Dataset-level status | **PARTIAL** held (5352/8784) — never force COMPLETE |
| Platform COMPLETE segs | **8641 → 8741** (+100) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Tip `S260821+` | **404** unpublished — tip-wait (**no invent**) |
| Mass | **NO-GO** |
| 3 default pins | **unchanged** (`pins_untouched=true`) |

**Return: 5252 → 5352 (+100).** Within Batch9 band (~50–100 official days). 2005 official archive exhausted. Tip unpublished, not sealed.

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE local | POST local | POST remote |
|--------|----------:|-----------:|------------:|
| Dataset COMPLETE | 22 | 22 | 22 |
| Dataset PARTIAL | 4 | 4 | 4 |
| OTC COMPLETE | **5252** | **5352** | **5352** |
| OTC PARTIAL | 3532 | **3432** | **3432** |
| Platform COMPLETE segs | 8641 | **8741** | **8741** |
| empty COMPLETE | 0 | 0 | 0 |
| all_checks_pass | true | true | true |
| Mass | NO-GO | NO-GO | NO-GO |

Logs: `pre_complete22_health_local.json` · `post_complete22_health_local.json` · `post_complete22_health_remote.json`

---

## 2. Batch9 composition

| bucket | n | span | result |
|--------|--:|------|--------|
| 2005 archive remaining newer-first | **43** | `2005-03-07…2005-01-04` | sealed COMPLETE |
| 2004 archive newer-first | **57** | `2004-12-30…2004-10-07` | sealed COMPLETE |
| Tip `S260821`…`S260826` | — | unpublished | **404** tip-wait |
| Weekend / holiday 404 | — | not on archive index | stay PARTIAL (**no invent**) |

**CF worker:** `https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev`  
**Flow:** `/discover?year=2005` then `/discover?year=2004` → official `month_csv` ∩ live PARTIAL ∧ `day < 2005-03-08` (2005) then 2004 newer-first → `/fetch` → seal  
**Gate (FULL_OK_HISTORICAL):** HTTP **200** ∧ size **> 100_000** ∧ non-HTML ∧ parse **nz > 0** ∧ raw≈struct.  
**Wave id on receipts:** `w0820b_w105_otc_batch9` · policy `W105_planned_official_historical_partial_backfill`.

Artifacts: `otc_discover_2005.json` · `otc_discover_2004.json` · `otc_batch9_items.json` · `otc_batch9_full_ok.json` · `otc_batch9_download_progress.jsonl` · `otc_seal_result.json` · `otc_batch9_summary.json` · `tip_probe_S260821plus.json`

### Discover ∩ PARTIAL

- Archive `archive2005.html` via CF `/discover`: **n_reference=247** (`month_csv` 245).  
- Still PARTIAL official 2005 days with `day < 2005-03-08`: **43** (pool = remaining official 2005).  
- Batch9 take 2005: **43** (all remaining official 2005).  
- Remaining official 2005 after this wave: **0**.
- Archive `archive2004.html` via CF `/discover`: **n_reference=248** (`month_csv` 246).  
- PARTIAL official 2004 days: **246** (pool).  
- Batch9 take 2004: **57** newer-first (newest remaining 2004).  
- Remaining official 2004 after this wave: **189**.

### Batch9 days (100 = 43 + 57)

- 2005 (43): `2005-03-07` … `2005-01-04` (newer-first; see `otc_batch9_plan.json` `days_2005`).
- 2004 (57): `2004-12-30` … `2004-10-07` (newer-first; see `otc_batch9_plan.json` `days_2004`).

CSV sizes **807,478–850,637** bytes (HTML ~46KB excluded). **html=0 · small=0 · empty COMPLETE=0**.

---

## 3. Seal / ledger

1. CF `/discover?year=2005` then `/discover?year=2004` → official archive reference codes  
2. CF `/fetch` → local raw under `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/` (**100/100 OK**)  
3. Parse + normalize → facts upsert (triggers off during bulk)  
4. Signed SUCCESS receipt + `record_collection_receipt` (**100/100 SEALED**, run_id **909072…909171**)  
5. Tip `S260821+` probe — all **404**; **not sealed**  
6. `refresh_coverage_ledger` → segment COMPLETE (**5252→5352**)  
7. `sync_dataset_coverage_from_segments` → dataset **PARTIAL** held (5352/8784)  
8. `publish_ops_projection --apply-remote` · `ops_reeval_freshness` → FRESH (`projgen-6be6453281b44928b2738c96f5de2011`) · Mass **NO-GO**

Empty COMPLETE **0**. No invent / no fake densify. PARTIAL −100 while COMPLETE +100. No new inventory tip day.

---

## 4. Tip probe `S260821+`

| code | result |
|------|--------|
| `S260821`…`S260826` | **404** all paths |
| `full_ok_n` | **0** |

`S260821+` tip-wait only. **No invent.** Artifact: `tip_probe_S260821plus.json`.

---

## 5. Dataset status

OTC dataset remains **PARTIAL** (5352/8784) until true archive reconciliation criteria are met. **Mass NO-GO.** Dataset COMPLETE **22** held. 3-default pins **untouched**. GO/READY/live **not declared**.

Next: continue 2004 official archive newer-first (remaining ~189 official 2004 days before `2004-10-07`); 2005 official archive **done**; tip-wait `S260821+`.

---

## 6. Return

```json
{
  "otc_complete_pre": 5252,
  "otc_complete_post": 5352,
  "otc_partial_pre": 3532,
  "otc_partial_post": 3432,
  "delta": 100,
  "batch9_sealed_complete": 100,
  "n_2005": 43,
  "n_2004": 57,
  "tip_sealed_complete": 0,
  "span_post": ["2004-10-07", "2026-08-20"],
  "platform_complete_post": 8741,
  "dataset_status": "PARTIAL",
  "empty_otc_complete": 0,
  "tip_probe_full_ok_n_unpublished": 0,
  "mass": "NO-GO",
  "pins_untouched": true,
  "implementer": "GLM5.3",
  "orchestrator_implemented": false
}
```

**COMPLETE: 5252 → 5352 (+100).** Split **2005=43 / 2004=57**. Dataset remains **PARTIAL**.

GLM5.3 only. Grok did not implement.
