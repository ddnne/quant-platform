# W103 / w0819f — OTC planned historical backfill batch7 (2026-08-19)

**Wave:** `w0819f` / **W103** / Track A  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy:** planned official PARTIAL backfill (NOT tip-only densify invent)  
**Forbidden held:** invent COMPLETE · empty COMPLETE · fake densify · Mass ON · Dataset COMPLETE force · pin retune · GO/Mass/READY/live  
**Prior:** [`w0819e_w102_otc_backfill_batch6_20260819.md`](w0819e_w102_otc_backfill_batch6_20260819.md)  
**Artifacts:** [`.glm-logs/w0819f_w103_otc7_repo_gate/`](../../.glm-logs/w0819f_w103_otc7_repo_gate/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **5052** |
| OTC COMPLETE AFTER (local + D1) | **5152** (**+100**) |
| OTC PARTIAL BEFORE → AFTER | **3732 → 3632** (−100) |
| Batch7 scope | 2005 archive newer-first before span start `2005-12-29` |
| COMPLETE span AFTER | **2005-08-03 … 2026-08-20** (was `2005-12-29…2026-08-20`) |
| Dataset-level status | **PARTIAL** held (5152/8784) — never force COMPLETE |
| Platform COMPLETE segs | **8441 → 8541** (+100) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Tip `S260821+` | **404** unpublished — tip-wait (**no invent**) |
| Mass | **NO-GO** |
| 3 default pins | **unchanged** (`pins_untouched=true`) |

**Return: 5052 → 5152 (+100).** Within Batch7 band (~50–100 official days). Tip unpublished, not sealed.

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE local | POST local | POST remote |
|--------|----------:|-----------:|------------:|
| Dataset COMPLETE | 22 | 22 | 22 |
| Dataset PARTIAL | 4 | 4 | 4 |
| OTC COMPLETE | **5052** | **5152** | **5152** |
| OTC PARTIAL | 3732 | **3632** | **3632** |
| Platform COMPLETE segs | 8441 | **8541** | **8541** |
| empty COMPLETE | 0 | 0 | 0 |
| all_checks_pass | true | true | true |
| Mass | NO-GO | NO-GO | NO-GO |

Logs: `pre_complete22_health_local.json` · `post_complete22_health_local.json` · `post_complete22_health_remote.json`

---

## 2. Batch7 composition

| bucket | n | span | result |
|--------|--:|------|--------|
| 2005 archive newer-first | **100** | `2005-12-28…2005-08-03` | sealed COMPLETE |
| Tip `S260821`…`S260826` | — | unpublished | **404** tip-wait |
| Weekend / holiday 404 | — | not on archive index | stay PARTIAL (**no invent**) |

**CF worker:** `https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev`  
**Flow:** `/discover?year=2005` → official `month_csv` ∩ live PARTIAL ∧ `day < 2005-12-29` newer-first → `/fetch` → seal  
**Gate (FULL_OK_HISTORICAL):** HTTP **200** ∧ size **> 100_000** ∧ non-HTML ∧ parse **nz > 0** ∧ raw≈struct.  
**Wave id on receipts:** `w0819f_w103_otc_batch7` · policy `W103_planned_official_historical_partial_backfill`.

Artifacts: `otc_discover_2005.json` · `otc_batch7_items.json` · `otc_batch7_full_ok.json` · `otc_batch7_download_progress.jsonl` · `otc_seal_result.json` · `otc_batch7_summary.json` · `tip_probe_S260821plus.json`

### Discover ∩ PARTIAL

- Archive `archive2005.html` via CF `/discover`: **n_reference=247** (`month_csv` 245).  
- Still PARTIAL official 2005 days with `day < 2005-12-29`: **243** (pool).  
- Batch7 take: **100** newer-first (newest remaining 2005).  
- Remaining official 2005 after this wave: **143**.

### Batch7 days (100)

`2005-12-28` … `2005-08-03` (newer-first; see `otc_batch7_plan.json` `days`).

CSV sizes **848,735–897,265** bytes (HTML ~46KB excluded). **html=0 · small=0 · empty COMPLETE=0**.

---

## 3. Seal / ledger

1. CF `/discover?year=2005` → official archive reference codes  
2. CF `/fetch` → local raw under `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/` (**100/100 OK**)  
3. Parse + normalize → facts upsert (triggers off during bulk)  
4. Signed SUCCESS receipt + `record_collection_receipt` (**100/100 SEALED**, run_id **908872…908971**)  
5. Tip `S260821+` probe — all **404**; **not sealed**  
6. `refresh_coverage_ledger` → segment COMPLETE (**5052→5152**)  
7. `sync_dataset_coverage_from_segments` → dataset **PARTIAL** held (5152/8784)  
8. `publish_ops_projection --apply-remote` · `ops_reeval_freshness` → FRESH · Mass **NO-GO**

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

OTC dataset remains **PARTIAL** (5152/8784) until true archive reconciliation criteria are met. **Mass NO-GO.** Dataset COMPLETE **22** held. 3-default pins **untouched**. GO/READY/live **not declared**.

Next: continue pre-2008 archive newer-first (remaining ~143 official 2005 days before `2005-08-03`, then 2004→…); tip-wait `S260821+`.

---

## 6. Return

```json
{
  "otc_complete_pre": 5052,
  "otc_complete_post": 5152,
  "otc_partial_pre": 3732,
  "otc_partial_post": 3632,
  "delta": 100,
  "batch7_sealed_complete": 100,
  "tip_sealed_complete": 0,
  "span_post": ["2005-08-03", "2026-08-20"],
  "platform_complete_post": 8541,
  "dataset_status": "PARTIAL",
  "empty_otc_complete": 0,
  "tip_probe_full_ok_n_unpublished": 0,
  "mass": "NO-GO",
  "pins_untouched": true,
  "implementer": "GLM5.3",
  "orchestrator_implemented": false
}
```

**COMPLETE: 5052 → 5152 (+100).** Dataset remains **PARTIAL**.

GLM5.3 only. Grok did not implement.
