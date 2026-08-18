# W98 / w0819a — OTC planned historical backfill batch2 (2026-08-19)

**Wave:** `w0819a` / **W98** / Track A PRIORITY  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy:** Planned backfill of **officially available** historical PARTIAL days (NOT tip-only).  
**Forbidden held:** invent COMPLETE · empty COMPLETE · fake densify · Mass ON · Dataset COMPLETE force  
**Plan:** [`.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md`](../../.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md)  
**Artifacts:** [`.glm-logs/w0819a_w98_otc_master_xs/`](../../.glm-logs/w0819a_w98_otc_master_xs/)

**Live verified:** 2026-08-18T22:36Z (local seal + remote publish + health)

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **4551** |
| OTC COMPLETE AFTER (local + D1) | **4651** (**+100**) |
| OTC PARTIAL BEFORE → AFTER | **4232 → 4132** (−100) |
| Batch2 sealed COMPLETE | **100 / 100** (5 early-2008 + 95 pre-2008) |
| COMPLETE span AFTER | **2007-08-13 … 2026-08-19** (was `2008-01-11…`) |
| Dataset-level status | **PARTIAL** held (4651/8783) — never force COMPLETE |
| Platform COMPLETE segs | **7940 → 8040** (+100) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Tip `S260820+` | still **404** unpublished — left PARTIAL |
| Mass | **NO-GO** |

**Return: 4551 → 4651 (+100).**

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE local | PRE remote | POST local | POST remote |
|--------|----------:|-----------:|-----------:|------------:|
| Dataset COMPLETE | 22 | 22 | 22 | 22 |
| Dataset PARTIAL | 4 | 4 | 4 | 4 |
| OTC COMPLETE | **4551** | **4551** | **4651** | **4651** |
| OTC PARTIAL | 4232 | 4232 | **4132** | **4132** |
| Platform COMPLETE segs | 7940 | 7940 | **8040** | **8040** |
| empty COMPLETE | 0 | 0 | 0 | 0 |
| all_checks_pass | true | true | true | true |
| Mass | NO-GO | NO-GO | NO-GO | NO-GO |

Logs: `pre_complete22_health_local.json` · `pre_complete22_health_remote.json` · `post_complete22_health_local.json` · `post_complete22_health_remote.json`

---

## 2. Batch2 scope

| bucket | n | span | action |
|--------|--:|------|--------|
| **Early-2008 remainder** (W97 leftover) | **5** | `2008-01-10`…`2008-01-04` | CF `/fetch` + seal |
| **Pre-2008 archive newer-first** | **95** | `2007-12-28`…`2007-08-13` | CF `/discover` 2007 + `/fetch` + seal |
| **Tip probe** `S260820+` | 0 sealable | tip-wait | 404 all paths — stay PARTIAL |
| **Total sealed** | **100** | | FULL_OK_HISTORICAL only |

CF `/discover?year=2007`: HTTP **200**, `n_links=491`, `month_csv=245` (confirmed).  
Worker: `https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev`

**Gate (FULL_OK_HISTORICAL):** HTTP **200** ∧ size **> 100_000** (excludes HTML ~46KB) ∧ non-HTML ∧ parse **nz > 0** ∧ raw≈struct.  
Modern tip gate **> 1.5MB** unchanged. Official 2007–early-2008 CSVs are naturally ~0.99–1.06MB — sealing them is **not** fake densify.

---

## 3. Execution

| step | result |
|------|--------|
| Candidates | `otc_batch2_items.json` **n=100** |
| Tip probe | `S260820`/`S260821`/`S260822` — all paths **404** (`tip_probe_S260820plus.json`) |
| CF `/discover` 2007 | OK — archive index present |
| CF `/fetch` | **100/100 OK** → local raw `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/S{code}.csv` |
| Round1 seal | **80/80 SEALED** (run_id **908371…908450**) → COMPLETE **4551→4631** |
| Round2 seal | **20/20 SEALED** (run_id **908451…908470**) → COMPLETE **4631→4651** |
| `sync_dataset_coverage_from_segments` | OTC dataset stays **PARTIAL** (4651/8783) |
| `publish_ops_projection --apply-remote` | guard ok local=8040 ≥ remote → applied |
| `ops_reeval_freshness` | OK · `coverage_segments_untouched=1` · Mass NO-GO |

Seal: `seal_otc_batch2.py` / `seal_otc_batch2_round2.py` · download: `download_batch2.py`  
Return: `otc_batch2_return.json`

### Early-2008 days (5)

`2008-01-10`, `2008-01-09`, `2008-01-08`, `2008-01-07`, `2008-01-04`

### Pre-2008 days (95) — newer-first

`2007-12-28` … `2007-08-13` (weekday official `month_csv` on `archive2007.html`)

---

## 4. Explicit non-claims

- **OTC dataset COMPLETE** — **not** declared (still PARTIAL / PD-D5)  
- **COMPLETE 23** — not invented  
- **empty COMPLETE** — not minted (**0**)  
- **Weekend / holiday 404 densify** — **not** run  
- **Tip S260820+** — still unpublished 404 (no invent)  
- **Mass / READY / Phase7 / operational GO** — still closed  

---

## 5. Next (per plan)

1. Batch3+: continue pre-2008 archive newer-first from `2007-08-10`… toward `2002-08-02` (50–100/wave)  
2. Tip re-probe `S260820+` on next JSDA publish  
3. Keep dataset PARTIAL · Mass **NO-GO**

---

## 6. Return

```json
{
  "otc_complete_pre": 4551,
  "otc_complete_post": 4651,
  "otc_partial_pre": 4232,
  "otc_partial_post": 4132,
  "delta": 100,
  "batch2_sealed_complete": 100,
  "early2008_sealed": 5,
  "pre2008_sealed": 95,
  "span_post": ["2007-08-13", "2026-08-19"],
  "platform_complete_post": 8040,
  "dataset_status": "PARTIAL",
  "empty_otc_complete": 0,
  "tip_S260820plus": "404_unpublished",
  "logs": ".glm-logs/w0819a_w98_otc_master_xs/",
  "mass": "NO-GO"
}
```

**COMPLETE: 4551 → 4651 (+100).**
