# W107 / w0820d — OTC planned historical backfill batch11 (2026-08-20)

**Wave:** `w0820d` / **W107** / Track A  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy:** planned official PARTIAL backfill (NOT tip-only densify invent)  
**Forbidden held:** invent COMPLETE · empty COMPLETE · fake densify · Mass ON · Dataset COMPLETE force · pin retune · GO/Mass/READY/live  
**Prior:** [`w0820c_w106_otc_backfill_batch10_20260820.md`](w0820c_w106_otc_backfill_batch10_20260820.md)  
**Artifacts:** [`.glm-logs/w0820d_w107_otc11_adaptive/`](../../.glm-logs/w0820d_w107_otc11_adaptive/)  
**Implementer:** Grok (this wave).

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **5452** |
| OTC COMPLETE AFTER (local) | **5552** (**+100**) |
| OTC PARTIAL BEFORE → AFTER | **3332 → 3232** (−100) |
| Batch11 split | **2004 = 89** + **2003 = 11** (official newer-first) |
| Batch11 scope | finish remaining official 2004 before `2004-05-17`, then start 2003 |
| COMPLETE span AFTER | **2003-12-15 … 2026-08-20** (was `2004-05-17…2026-08-20`) |
| Dataset-level status | **PARTIAL** held (5552/8784) — never force COMPLETE |
| Platform COMPLETE segs | **8841 → 8941** (+100) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Tip `S260821+` | **404** unpublished — tip-wait (**no invent**) |
| Mass | **NO-GO** |
| 3 default pins | **unchanged** (`pins_untouched=true`) |

**Return: 5452 → 5552 (+100).** Remaining official 2004: **0**. Remaining official 2003: **234**. Tip unpublished, not sealed.

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE (W106) | POST local |
|--------|----------:|-----------:|
| Dataset COMPLETE | 22 | **22** |
| Dataset PARTIAL | 4 | **4** |
| OTC COMPLETE | **5452** | **5552** |
| OTC PARTIAL | 3332 | **3232** |
| Platform COMPLETE segs | 8841 | **8941** |
| empty COMPLETE | 0 | **0** |
| all_checks_pass | true | **true** |
| Mass | NO-GO | **NO-GO** |

Log: `post_complete22_health_local.json`.

---

## 2. Batch11 composition

| bucket | n | span | result |
|--------|--:|------|--------|
| 2004 archive leftover | **89** | `2004-05-14…2004-01-05` | sealed COMPLETE |
| 2003 archive start | **11** | `2003-12-30…2003-12-15` | sealed COMPLETE |
| Tip `S260821`…`S260826` | — | unpublished | **404** tip-wait |
| Weekend / holiday 404 | — | not on archive index | stay PARTIAL (**no invent**) |

**CF worker:** `https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev`  
**Flow:** `/discover?year=2004` then `/discover?year=2003` → official `month_csv` ∩ live PARTIAL newer-first → `/fetch` → seal  
**Gate (FULL_OK_HISTORICAL):** HTTP **200** ∧ size **> 100_000** ∧ non-HTML ∧ parse **nz > 0** ∧ raw≈struct.  
**Wave id on receipts:** `w0820d_w107_otc_batch11` · policy `W107_planned_official_historical_partial_backfill`.

Artifacts: `otc_discover_2003.json` · `otc_discover_2004.json` · `otc_batch11_items.json` · `otc_batch11_full_ok.json` · `otc_batch11_download_progress.jsonl` · `otc_seal_result.json` · `otc_seal.json` · `tip_probe_S260821plus.json`

### Discover ∩ PARTIAL

- Remaining official 2004 days with `day < 2004-05-17`: **89** (pool exhausted this wave).  
- Official 2003 archive pool: **245**. Batch11 take **11**. Remaining official 2003 after this wave: **234**.  
- Official 2004 archive **done**. Official 2005 archive already exhausted (W105).

CSV sizes **769,257–809,831** bytes. **html=0 · small=0 · empty COMPLETE=0**. Download **100/100 OK**. Seal **100/100 SEALED**.

---

## 3. Seal / ledger

1. CF `/discover` → official archive reference codes  
2. CF `/fetch` → local raw under `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/` (**100/100 OK**)  
3. Parse + normalize → facts upsert (triggers off during bulk)  
4. Signed SUCCESS receipt + `record_collection_receipt` (**100/100 SEALED**)  
5. Tip `S260821+` probe — all **404**; **not sealed**  
6. `refresh_coverage_ledger` → segment COMPLETE (**5452→5552**)  
7. Dataset **PARTIAL** held (5552/8784)

Empty COMPLETE **0**. No invent / no fake densify. PARTIAL −100 while COMPLETE +100.

COMPLETE by year now includes **2003 = 11** · **2004 = 246**.

---

## 4. Tip probe `S260821+`

| code | result |
|------|--------|
| `S260821`…`S260826` | **404** all paths |
| `full_ok_n` | **0** |

`S260821+` tip-wait only. **No invent.** Artifact: `tip_probe_S260821plus.json`.

---

## 5. Dataset status

OTC dataset remains **PARTIAL** (5552/8784) until true archive reconciliation criteria are met. **Mass NO-GO.** Dataset COMPLETE **22** held. 3-default pins **untouched**. GO/READY/live **not declared**.

Next: continue 2003 official archive newer-first (remaining ~234 official 2003 days); 2004 official archive **done**; tip-wait `S260821+`.

---

## 6. Return

```json
{
  "otc_complete_pre": 5452,
  "otc_complete_post": 5552,
  "otc_partial_pre": 3332,
  "otc_partial_post": 3232,
  "delta": 100,
  "batch11_sealed_complete": 100,
  "n_2004": 89,
  "n_2003": 11,
  "tip_sealed_complete": 0,
  "span_post": ["2003-12-15", "2026-08-20"],
  "platform_complete_post": 8941,
  "dataset_status": "PARTIAL",
  "empty_otc_complete": 0,
  "tip_probe_full_ok_n_unpublished": 0,
  "mass": "NO-GO",
  "pins_untouched": true,
  "remaining_official_2004": 0,
  "remaining_official_2003": 234,
  "implementer": "Grok"
}
```

**COMPLETE: 5452 → 5552 (+100).** 2004 leftover **89** + 2003 start **11**. Dataset remains **PARTIAL**. Remaining official 2004: **0**. Remaining official 2003: **234**.
