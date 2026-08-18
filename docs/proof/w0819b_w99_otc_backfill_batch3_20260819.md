# W99 / w0819b — OTC planned historical backfill batch3 (2026-08-19)

**Wave:** `w0819b` / **W99** / Track A  
**Dataset:** `jsda_otc_bond_reference_prices` (PD-D5-JSDA-OTC)  
**Policy:** planned official PARTIAL backfill (NOT tip-only densify invent)  
**Forbidden held:** invent COMPLETE · empty COMPLETE · fake densify · Mass ON · Dataset COMPLETE force  
**Plan:** [`.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md`](../../.glm-logs/w0818g_w97_otc_master_hyps/otc_backfill_plan.md) (Batch3)  
**Artifacts:** [`.glm-logs/w0819b_w99_otc_sticky_dd/`](../../.glm-logs/w0819b_w99_otc_sticky_dd/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| Check | Result |
|-------|--------|
| OTC COMPLETE BEFORE | **4651** |
| OTC COMPLETE AFTER (local + D1) | **4751** (**+100**) |
| OTC PARTIAL BEFORE → AFTER | **4132 → 4032** (−100) |
| Batch3 scope | pre-2008 archive newer-first before span start `2007-08-13` |
| COMPLETE span AFTER | **2007-03-19 … 2026-08-19** (was `2007-08-13…`) |
| Dataset-level status | **PARTIAL** held (4751/8783) — never force COMPLETE |
| Platform COMPLETE segs | **8040 → 8140** (+100) |
| empty COMPLETE (OTC) | **0** |
| Dataset COMPLETE (platform) | **22** held |
| Tip `S260820+` | **404** unpublished — tip-wait (**no invent**) |
| Mass | **NO-GO** |

**Return: 4651 → 4751 (+100).** Within Batch3 band (~50–100 official days).

---

## 1. PRE / POST COMPLETE22 health

| Metric | PRE local | POST local | POST remote |
|--------|----------:|-----------:|------------:|
| Dataset COMPLETE | 22 | 22 | 22 |
| Dataset PARTIAL | 4 | 4 | 4 |
| OTC COMPLETE | **4651** | **4751** | **4751** |
| OTC PARTIAL | 4132 | **4032** | **4032** |
| Platform COMPLETE segs | 8040 | **8140** | **8140** |
| empty COMPLETE | 0 | 0 | 0 |
| all_checks_pass | true | true | true |
| Mass | NO-GO | NO-GO | NO-GO |

Logs: `pre_complete22_health_local.json` · `post_complete22_health_local.json` · `post_complete22_health_remote.json`

---

## 2. Batch3 composition

| bucket | n | span | result |
|--------|--:|------|--------|
| Pre-2008 archive newer-first | **100** | `2007-08-10…2007-03-19` | sealed COMPLETE |
| Tip `S260820`…`S260825` | — | unpublished | **404** tip-wait |
| Weekend / holiday 404 | — | — | stay PARTIAL (**no invent**) |

**CF worker:** `https://quant-platform-jsda-otc-probe-w80.taku-haga.workers.dev`  
**Flow:** `/discover?year=2007` → official `month_csv` ∩ live PARTIAL → `/fetch` → seal  
**Gate (FULL_OK_HISTORICAL):** HTTP **200** ∧ size **> 100_000** ∧ non-HTML ∧ parse **nz > 0** ∧ raw≈struct.  
**Wave id on receipts:** `w0819b_w99_otc_batch3` · policy `W99_planned_official_historical_partial_backfill`.

Artifacts: `otc_discover_2007.json` · `otc_batch3_items.json` · `otc_batch3_full_ok.json` · `otc_batch3_download_progress.jsonl` · `otc_seal_result.json` · `otc_batch3_summary.json` · `tip_probe_S260820plus.json`

### Discover ∩ PARTIAL

- Archive `archive2007.html` via CF `/discover`: **n_reference=247** (`month_csv` 245).  
- Still PARTIAL official days with `day < 2007-08-13`: **150** (pool).  
- Batch3 take: **100** newer-first.

### Batch3 days (100)

`2007-08-10`, `2007-08-09`, `2007-08-08`, `2007-08-07`, `2007-08-06`, `2007-08-03`, `2007-08-02`, `2007-08-01`, `2007-07-31`, `2007-07-30`, `2007-07-27`, `2007-07-26`, `2007-07-25`, `2007-07-24`, `2007-07-23`, `2007-07-20`, `2007-07-19`, `2007-07-18`, `2007-07-17`, `2007-07-13`, `2007-07-12`, `2007-07-11`, `2007-07-10`, `2007-07-09`, `2007-07-06`, `2007-07-05`, `2007-07-04`, `2007-07-03`, `2007-07-02`, `2007-06-29`, `2007-06-28`, `2007-06-27`, `2007-06-26`, `2007-06-25`, `2007-06-22`, `2007-06-21`, `2007-06-20`, `2007-06-19`, `2007-06-18`, `2007-06-15`, `2007-06-14`, `2007-06-13`, `2007-06-12`, `2007-06-11`, `2007-06-08`, `2007-06-07`, `2007-06-06`, `2007-06-05`, `2007-06-04`, `2007-06-01`, `2007-05-31`, `2007-05-30`, `2007-05-29`, `2007-05-28`, `2007-05-25`, `2007-05-24`, `2007-05-23`, `2007-05-22`, `2007-05-21`, `2007-05-18`, `2007-05-17`, `2007-05-16`, `2007-05-15`, `2007-05-14`, `2007-05-11`, `2007-05-10`, `2007-05-09`, `2007-05-08`, `2007-05-07`, `2007-05-02`, `2007-05-01`, `2007-04-27`, `2007-04-26`, `2007-04-25`, `2007-04-24`, `2007-04-23`, `2007-04-20`, `2007-04-19`, `2007-04-18`, `2007-04-17`, `2007-04-16`, `2007-04-13`, `2007-04-12`, `2007-04-11`, `2007-04-10`, `2007-04-09`, `2007-04-06`, `2007-04-05`, `2007-04-04`, `2007-04-03`, `2007-04-02`, `2007-03-30`, `2007-03-29`, `2007-03-28`, `2007-03-27`, `2007-03-26`, `2007-03-23`, `2007-03-22`, `2007-03-20`, `2007-03-19`

---

## 3. Seal / ledger

1. CF `/discover?year=2007` → official archive reference codes  
2. CF `/fetch` → local raw under `data/raw/jsda/jsda_otc_bond_reference_prices/{day}/` (**100/100 OK**, sizes ~0.95–1.01MB)  
3. Parse + normalize → facts upsert (triggers off during bulk)  
4. Signed SUCCESS receipt + `record_collection_receipt` (**100/100 SEALED**, run_id **908471…908570**)  
5. `refresh_coverage_ledger` → segment COMPLETE (**4651→4751**)  
6. `sync_dataset_coverage_from_segments` → dataset **PARTIAL** held (4751/8783)  
7. `publish_ops_projection --apply-remote` · `ops_reeval_freshness` → FRESH · Mass **NO-GO**

Empty COMPLETE **0**. No invent / no fake densify.

---

## 4. Tip probe `S260820+`

| code | result |
|------|--------|
| `S260820` | **404** all paths |
| `S260821` | **404** all paths |
| `S260822` | **404** all paths |
| `S260825` | **404** all paths |
| `full_ok_n` | **0** |

Tip-wait only. **No invent.** Artifact: `tip_probe_S260820plus.json`.

---

## 5. Dataset status

OTC dataset remains **PARTIAL** until true archive reconciliation criteria are met. **Mass NO-GO.**

Next: continue pre-2008 archive newer-first (remaining ~50 official 2007 days before `2007-03-19`, then 2006→…); tip-wait `S260820+`.

---

## 6. Return

```json
{
  "otc_complete_pre": 4651,
  "otc_complete_post": 4751,
  "otc_partial_pre": 4132,
  "otc_partial_post": 4032,
  "delta": 100,
  "batch3_sealed_complete": 100,
  "span_post": ["2007-03-19", "2026-08-19"],
  "platform_complete_post": 8140,
  "dataset_status": "PARTIAL",
  "empty_otc_complete": 0,
  "tip_probe_full_ok_n": 0,
  "mass": "NO-GO"
}
```

**COMPLETE: 4651 → 4751 (+100).**
