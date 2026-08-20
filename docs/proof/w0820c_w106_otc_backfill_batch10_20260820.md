# W106 / w0820c — OTC planned historical backfill batch10 (2026-08-20)

**Wave:** `w0820c` / **W106** / Track A  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy:** planned official PARTIAL backfill (NOT tip-only densify invent)  
**Forbidden held:** invent COMPLETE · empty COMPLETE · fake densify · Mass ON · Dataset COMPLETE force · pin retune · GO/Mass/READY/live  
**Prior:** [`w0820b_w105_otc_backfill_batch9_20260820.md`](w0820b_w105_otc_backfill_batch9_20260820.md)  
**Artifacts:** [`.glm-logs/w0820c_w106_otc10_ls_hyps/`](../../.glm-logs/w0820c_w106_otc10_ls_hyps/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **5352** |
| OTC COMPLETE AFTER (local + D1) | **5452** (**+100**) |
| OTC PARTIAL BEFORE → AFTER | **3432 → 3332** (−100) |
| Batch10 split | **2004 = 100** (official newer-first before span start `2004-10-07`) |
| Batch10 scope | 2004 official archive newer-first, days **before** `2004-10-07` |
| COMPLETE span AFTER | **2004-05-17 … 2026-08-20** (was `2004-10-07…2026-08-20`) |
| Dataset-level status | **PARTIAL** held (5452/8784) — never force COMPLETE |
| Platform COMPLETE segs | **8741 → 8841** (+100) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Tip `S260821+` | **404** unpublished — tip-wait (**no invent**) |
| Mass | **NO-GO** |
| 3 default pins | **unchanged** (`pins_untouched=true`) |

**Return: 5352 → 5452 (+100).** Within Batch10 band (~50–100 official days). Remaining official 2004: **89**. Tip unpublished, not sealed.

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE local | POST local | POST remote |
|--------|----------:|-----------:|------------:|
| Dataset COMPLETE | 22 | 22 | 22 |
| Dataset PARTIAL | 4 | 4 | 4 |
| OTC COMPLETE | **5352** | **5452** | **5452** |
| OTC PARTIAL | 3432 | **3332** | **3332** |
| Platform COMPLETE segs | 8741 | **8841** | **8841** |
| empty COMPLETE | 0 | 0 | 0 |
| all_checks_pass | true | true | true |
| Mass | NO-GO | NO-GO | NO-GO |

Logs: `pre_complete22_health_local.json` · `post_complete22_health_local.json` · `post_complete22_health_remote.json`

---

## 2. Batch10 composition

| bucket | n | span | result |
|--------|--:|------|--------|
| 2004 archive newer-first | **100** | `2004-10-06…2004-05-17` | sealed COMPLETE |
| Tip `S260821`…`S260826` | — | unpublished | **404** tip-wait |
| Weekend / holiday 404 | — | not on archive index | stay PARTIAL (**no invent**) |

**CF worker:** `https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev`  
**Flow:** `/discover?year=2004` → official `month_csv` ∩ live PARTIAL ∧ `day < 2004-10-07` newer-first → `/fetch` → seal  
**Gate (FULL_OK_HISTORICAL):** HTTP **200** ∧ size **> 100_000** ∧ non-HTML ∧ parse **nz > 0** ∧ raw≈struct.  
**Wave id on receipts:** `w0820c_w106_otc_batch10` · policy `W106_planned_official_historical_partial_backfill`.

Artifacts: `otc_discover_2004.json` · `otc_batch10_items.json` · `otc_batch10_full_ok.json` · `otc_batch10_download_progress.jsonl` · `otc_seal_result.json` · `otc_batch10_summary.json` · `tip_probe_S260821plus.json`

### Discover ∩ PARTIAL

- Archive `archive2004.html` via CF `/discover`: **n_reference=248** (`month_csv` 246).  
- PARTIAL official 2004 days with `day < 2004-10-07`: **189** (pool).  
- Batch10 take 2004: **100** newer-first (newest remaining 2004 before span start).  
- Remaining official 2004 after this wave: **89**.  
- Official 2005 archive already exhausted (W105).

### Batch10 days (100 = 2004)

- 2004 (100): `2004-10-06` … `2004-05-17` (newer-first; see `otc_batch10_plan.json` `days_2004`).

CSV sizes **789,266–825,727** bytes (HTML ~46KB excluded). **html=0 · small=0 · empty COMPLETE=0**.

---

## 3. Seal / ledger

1. CF `/discover?year=2004` → official archive reference codes  
2. CF `/fetch` → local raw under `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/` (**100/100 OK**)  
3. Parse + normalize → facts upsert (triggers off during bulk)  
4. Signed SUCCESS receipt + `record_collection_receipt` (**100/100 SEALED**, run_id **909172…909271**)  
5. Tip `S260821+` probe — all **404**; **not sealed**  
6. `refresh_coverage_ledger` → segment COMPLETE (**5352→5452**)  
7. `sync_dataset_coverage_from_segments` → dataset **PARTIAL** held (5452/8784)  
8. `publish_ops_projection --apply-remote` · `ops_reeval_freshness` → FRESH (`projgen-ce39fba62cec4d038208945cd29e19ac`) · Mass **NO-GO**

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

OTC dataset remains **PARTIAL** (5452/8784) until true archive reconciliation criteria are met. **Mass NO-GO.** Dataset COMPLETE **22** held. 3-default pins **untouched**. GO/READY/live **not declared**.

Next: continue 2004 official archive newer-first (remaining ~89 official 2004 days before `2004-05-17`); 2005 official archive **done**; tip-wait `S260821+`.

---

## 6. Return

```json
{
  "otc_complete_pre": 5352,
  "otc_complete_post": 5452,
  "otc_partial_pre": 3432,
  "otc_partial_post": 3332,
  "delta": 100,
  "batch10_sealed_complete": 100,
  "n_2004": 100,
  "tip_sealed_complete": 0,
  "span_post": ["2004-05-17", "2026-08-20"],
  "platform_complete_post": 8841,
  "dataset_status": "PARTIAL",
  "empty_otc_complete": 0,
  "tip_probe_full_ok_n_unpublished": 0,
  "mass": "NO-GO",
  "pins_untouched": true,
  "remaining_official_2004": 89,
  "implementer": "GLM5.3",
  "orchestrator_implemented": false
}
```

**COMPLETE: 5352 → 5452 (+100).** 2004 official newer-first **100**. Dataset remains **PARTIAL**. Remaining official 2004: **89**.

GLM5.3 only. Grok did not implement.
