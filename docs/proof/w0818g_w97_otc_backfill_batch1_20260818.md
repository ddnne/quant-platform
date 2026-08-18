# W97 / w0818g — OTC planned historical backfill batch1 (2026-08-18)

**Wave:** `w0818g` / **W97** / Track A PRIORITY  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy change:** **NOT tip-only.** Planned backfill of **officially available** historical PARTIAL days.  
**Forbidden held:** invent COMPLETE · empty COMPLETE · fake densify · Mass ON · Dataset COMPLETE force  
**Plan:** [`.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md`](../../.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md)  
**Artifacts:** [`.glm-logs/w0818g_w97_otc_master_hyps/`](../../.glm-logs/w0818g_w97_otc_master_hyps/)

**Live verified:** 2026-08-18T14:54Z (local seal + remote publish + health)

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **4501** |
| OTC COMPLETE AFTER (local + D1) | **4551** (**+50**) |
| OTC PARTIAL BEFORE → AFTER | **4282 → 4232** (−50) |
| Batch1 sealed COMPLETE | **50 / 50** early-2008 official archive CSVs |
| COMPLETE span AFTER | **2008-01-11 … 2026-08-19** (was `2008-03-25…`) |
| Dataset-level status | **PARTIAL** held (4551/8783) — never force COMPLETE |
| Platform COMPLETE segs | **7890 → 7940** (+50) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Mass | **NO-GO** |

**Return: 4501 → 4551 (+50).**

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE local | PRE remote | POST local | POST remote |
|--------|----------:|-----------:|-----------:|------------:|
| Dataset COMPLETE | 22 | 22 | 22 | 22 |
| Dataset PARTIAL | 4 | 4 | 4 | 4 |
| OTC COMPLETE | **4501** | **4501** | **4551** | **4551** |
| OTC PARTIAL | 4282 | 4282 | **4232** | **4232** |
| Platform COMPLETE segs | 7890 | 7890 | **7940** | **7940** |
| empty COMPLETE | 0 | 0 | 0 | 0 |
| fins COMPLETE segs | 104 | 104 | 104 | 104 |
| bars_am COMPLETE | 1 | 1 | 1 | 1 |
| all_checks_pass | true | true | true | true |
| Mass | NO-GO | NO-GO | NO-GO | NO-GO |

Logs: `pre_complete22_health_local.json` · `pre_complete22_health_remote.json` · `post_complete22_health_local.json` · `post_complete22_health_remote.json`

---

## 2. Inventory (PARTIAL n=4282 PRE)

| class | n | notes |
|-------|--:|-------|
| TOTAL PARTIAL | **4282** | `2002-08-02…2026-08-15` |
| Weekend | **2509** | leave PARTIAL (404 expected) |
| Weekday holes | **1773** | holidays + early-2008 size + pre-2008 archive |
| Pre-2008 | **1978** | official `archive20XX.html` present |
| Post-2008 | **2304** | weekends + holidays + early-2008 residual |
| Post-2008 weekday | **361** | mostly JP holidays 404 |
| W82 residual still PARTIAL (official HTTP200 CSV ~1.0MB) | **55** | Batch1 source |
| Pre-2008 official archive still PARTIAL (weekday) | **1331** | Batches 2+ |

Tip advance `S260820+`: still **404** (unpublished). Holiday island holes (e.g. `S260811`, `S260720`): **404** — left PARTIAL (**no invent**).

Artifact: `otc_partial_inventory.json` · `otc_pre2008_official_partial.json` · `otc_w82_residual_still_partial.json`

---

## 3. JSDA naming / CF `/fetch` (confirmed, reuse W96/W80)

**Worker:** `https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev`

```text
# modern tip flat
…/files/{YYYY}/S{YYMMDD}.csv

# historical month subdir (Batch1)
…/files/{YYYY}/{MM}/S{YYMMDD}.csv

# year index
…/baisanchi/archive{YYYY}.html
```

Example sealed: `…/files/2008/01/S080111.csv` (HTTP 200, ~1.04MB, `text/csv`).

**Gate used (FULL_OK_HISTORICAL):** HTTP **200** ∧ size **> 100_000** (excludes HTML ~46KB) ∧ parse **nz > 0** ∧ raw≈struct.  
Modern tip gate **> 1.5MB** unchanged for tip-advance days. Early-2008 / pre-2008 official CSVs are naturally ~0.5–1.1MB — sealing them is **not** fake densify.

---

## 4. Batch1 execution

| step | result |
|------|--------|
| Candidates | `otc_batch1_items.json` **n=50** newer-first within early-2008 residual (`2008-06-06`…`2008-01-11`) |
| CF `/fetch` | **50/50 OK** → local raw `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/S{code}.csv` |
| Round1 | 12 days already had SUCCESS receipts → ledger refresh → COMPLETE (**4501→4513**) |
| Round2 seal | **38/38 SEALED** (run_id **908333…908370** band) → COMPLETE (**4513→4551**) |
| `sync_dataset_coverage_from_segments` | OTC dataset stays **PARTIAL** (honest) |
| `publish_ops_projection --apply-remote` | guard ok local=7940 → remote applied |
| `ops_reeval_freshness` | OK · `coverage_segments_untouched=1` · Mass NO-GO |
| Remainder early-2008 | **5** days (`2008-01-10`…`2008-01-04`) left for batch2 |

Seal tool: `seal_otc_batch1.py` · download: `download_batch1.py`  
Return: `otc_batch1_return.json`

### Batch1 days (50)

`2008-06-06`, `2008-03-24`, `2008-03-21`, `2008-03-19`, `2008-03-18`, `2008-03-17`, `2008-03-14`, `2008-03-13`, `2008-03-12`, `2008-03-11`, `2008-03-10`, `2008-03-07`, `2008-03-06`, `2008-03-05`, `2008-03-04`, `2008-03-03`, `2008-02-29`, `2008-02-28`, `2008-02-27`, `2008-02-26`, `2008-02-25`, `2008-02-22`, `2008-02-21`, `2008-02-20`, `2008-02-19`, `2008-02-18`, `2008-02-15`, `2008-02-14`, `2008-02-13`, `2008-02-12`, `2008-02-08`, `2008-02-07`, `2008-02-06`, `2008-02-05`, `2008-02-04`, `2008-02-01`, `2008-01-31`, `2008-01-30`, `2008-01-29`, `2008-01-28`, `2008-01-25`, `2008-01-24`, `2008-01-23`, `2008-01-22`, `2008-01-21`, `2008-01-18`, `2008-01-17`, `2008-01-16`, `2008-01-15`, `2008-01-11`

---

## 5. Explicit non-claims

- **OTC dataset COMPLETE** — **not** declared (still PARTIAL / PD-D5)  
- **COMPLETE 23** — not invented  
- **empty COMPLETE** — not minted (**0**)  
- **Weekend / holiday 404 densify** — **not** run  
- **Pre-2008 bulk** — not this batch (planned batches 2+)  
- **Tip S260820+** — still unpublished 404  
- **Mass / READY / Phase7 / operational GO** — still closed  

---

## 6. Next (per plan)

1. Batch2: remainder early-2008 (**5**) + start pre-2008 archive newer-first (`2007-12-28`…) size **50–100**  
2. Tip re-probe `S260820+` on next JSDA publish  
3. Keep dataset PARTIAL · Mass **NO-GO**

---

## 7. Return

```json
{
  "otc_complete_pre": 4501,
  "otc_complete_post": 4551,
  "otc_partial_pre": 4282,
  "otc_partial_post": 4232,
  "delta": 50,
  "batch1_sealed_complete": 50,
  "span_post": ["2008-01-11", "2026-08-19"],
  "platform_complete_post": 7940,
  "dataset_status": "PARTIAL",
  "empty_otc_complete": 0,
  "plan": ".glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md",
  "mass": "NO-GO"
}
```

**COMPLETE: 4501 → 4551 (+50).**
