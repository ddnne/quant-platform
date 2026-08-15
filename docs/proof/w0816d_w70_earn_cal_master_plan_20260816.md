# W70 / w0816d — Task D earn_cal / master investigation only (minimal probe)

**Wave:** W70 / `w0816d`  
**Task:** D — `equities_earnings_calendar` + `equities_master` **investigation only**  
**As of (live D1):** `2026-08-15T16:39:18Z`  
**Repo tip at write:** `0f76e407fac2a3c907162f34c02a685c76f7296f`  
**Mass / READY / Phase7:** **not touched**  
**Commit / push:** **not done**  
**Grok implements:** **no** (this wave is probe + plan only)

## Policy held

| gate | value |
|------|-------|
| bulk D1 writes | **0** (read-only D1 queries + tip POST only) |
| empty COMPLETE | **FORBIDDEN** · **held** |
| force Dataset COMPLETE invent | **FORBIDDEN** · **held** |
| densify earn history 199 segs | **FORBIDDEN** · residual dry-run only (`executed=0`) |
| permanent DEFER | **PD-D4-EARN-CAL** · **PD-D2-MASTER** (active) |
| Mass / READY | **OFF** |

Artifacts: [`.glm-logs/w0816d_w70_tip/`](../../.glm-logs/w0816d_w70_tip/) · `FINAL_metrics.json`

---

## 1. Live D1 status counts

Remote DB `quant-ingest` via wrangler. Platform COMPLETE segs **3482** · Dataset COMPLETE **22**.

| dataset | COMPLETE | PARTIAL | COMPLETE span | PARTIAL span | permanent DEFER |
|---------|---------:|--------:|---------------|--------------|-----------------|
| `equities_earnings_calendar` | **1** | **199** | `2026-08` | `2010-01…2026-07` | **PD-D4-EARN-CAL** |
| `equities_master` | **220** | **94** | `2008-05…2026-08` | `2000-07…2008-04` | **PD-D2-MASTER** |

### dataset_coverage (aggregate row — not segment SoT)

| dataset | status | observed_start | observed_end | row_count |
|---------|--------|----------------|--------------|----------:|
| `equities_earnings_calendar` | **PARTIAL** | `2010-01-04` | `2026-08-14T00:00:00+09:00` | 333 |
| `equities_master` | **PARTIAL** | `2008-05-01` | `2026-08-12T00:00:00+09:00` | 8072621 |

### Tip segments (ledger)

| dataset | tip months `2026-01…08` |
|---------|-------------------------|
| earn_cal | `2026-01…07` **PARTIAL** residual · **`2026-08` COMPLETE** (`receipt_run_id=900492`) |
| master | all `2026-01…08` **COMPLETE** (continuous island from `2008-05`) |

### raw_retention_manifests

| dataset | n_total | n_nz | n_zero |
|---------|--------:|-----:|-------:|
| earn_cal | 503→**507+** after tip probe | 502→nz tip continues | 1 |
| master | 538 | 461 | 77 |

Logs: `status_counts.json`, `dataset_coverage.json`, `earn_tip_segment.json`, `master_tip_segment.json`, `*_raw_manifests_nz.json`

---

## 2. Tip fetch probe — `equities_earnings_calendar` (LIVE API)

**Question:** can tip fetch return **nz** via API?  
**Answer:** **YES — nz** (not empty).

**Path:** direct `POST …/v1/run?dataset=equities_earnings_calendar[&from=&to=]`  
**Worker:** `quant-platform-ingestion-premium.taku-haga.workers.dev`  
**Pool:** general · manual single-shot ×4 (not residual densify)

| label | from → to | HTTP | status | rowsInserted | rawBytes | empty vs nz | R2 run_id (newest band) |
|-------|-----------|-----:|--------|-------------:|---------:|:-----------:|-------------------------|
| `tip_no_params` | _(none)_ | **200** | pass | **1** | 150 | **nz** | **14082** |
| `tip_month_2026-08` | 2026-08-01 → 2026-08-16 | **200** | pass | **1** | 150 | **nz** | **14084** |
| `explicit_2026-08-15` | 2026-08-15 | **200** | pass | **1** | 150 | **nz** | **14086** |
| `explicit_2026-08-16` | 2026-08-16 | **200** | pass | **1** | 150 | **nz** | **14087** |

**LIVE_API_EMPTY:** **false**

### Date proof (R2 page bodies)

| run_id | params | row_count | page Date hist | note |
|-------:|--------|----------:|----------------|------|
| 14082 | `{}` (dataset only) | 1 | **`2026-08-17`×1** | next-bday tip (Sun 16 → Mon 17 announcements) |
| 14084 | from/to tip month | 1 | **`2026-08-17`×1** | range params **ignored** for body Date |
| 14087 | from=to=2026-08-16 | 1 | **`2026-08-17`×1** | same tip body |

Sample row: `Code=46510`, `Date=2026-08-17`, FY/Sector present.

**Tip month seal impact:** **none** — `2026-08` already COMPLETE; tip densify keeps current month raw warm only. **No new month to seal** (2026-09 not open).

### Residual history dry-run (NOT executed)

```text
mode=dry-run plan_jobs=199 queued=199 executed=0 cutoff=2026-08-14
by_dataset={"equities_earnings_calendar": 199}
first=2010-01 … last=2026-07  endpoint_query_mode=range
```

**Execute forbidden** under PD-D4-EARN-CAL: range shells return tip `Date` → `window_ok=0` for history months (prior waves; reconfirmed tip Date behavior above).

Logs: `earn_tip_collect_results.json`, `earn_tip_date_proof.json`, `manifests/earn_*`, `pages/`, `dry_earn_residual_*.json`, `dry_earn_residual_run.log`

---

## 3. Master — PARTIAL surgical seal scan (capped, no mass write)

### PARTIAL taxonomy (94)

| band | n | span | collection_receipts | coverage `receipt_run_id` |
|------|--:|------|---------------------|---------------------------|
| **PRE_PLAN** | **73** | `2000-07…2006-07` | **0** any receipt | all null |
| **MISDATE** | **21** | `2006-08…2008-04` | **63 SUCCESS** (nz raw+struct 47k–77k) across 21 segs | all null (not linked) |

### “raw+structured but missing receipt” candidates?

| class | n | sealable? |
|-------|--:|-----------|
| PARTIAL with **no receipt rows at all** | **73** PRE_PLAN | **No** — below J-Quants subscription floor (`2006-08-13`); no honest raw |
| PARTIAL with SUCCESS receipt nz raw+struct but `receipt_run_id` null | **21** MISDATE | **No** — Date gate fail (`window_ok=0`) |
| **True surgical seal** (window_ok Date ∈ segment month + missing COMPLETE link) | **0** | — |

### Date gate evidence (prior probe, re-used — no mass R2)

From [`.glm-logs/w0815b_g10_master/probe_summary.json`](../../.glm-logs/w0815b_g10_master/probe_summary.json):

- planner band probed **21/21**
- **window_ok = 0** · **window_bad = 21**
- unique bad Date: **`2008-05-07` only** (requested e.g. `2006-12-01…31` → body Date stuck on 2008-05-07)

Sample residual_best: segs `2006-09`, `2006-12`, `2007-01`, `2007-02`, `2008-04` all `dates=["2008-05-07"]`.

**Verdict:** **0 surgical seal candidates.** Linking MISDATE SUCCESS receipts to COMPLETE would invent segment months from misdated tip-like dumps — **FORBIDDEN**.

Logs: `master_partial_taxonomy.json`, `master_misdate_success_segs.json`, `master_partial_with_success_no_link.json`, `master_seal_candidate_verdict.json`, `master_prior_window_probe.json`

---

## 4. Next safe steps only

### A. `equities_earnings_calendar` (PD-D4-EARN-CAL)

| step | safe? | action |
|------|:-----:|--------|
| Keep cron tip collect | **yes** | already nz hourly; densifies tip month only |
| Seal tip month | **n/a** | `2026-08` already COMPLETE |
| Residual densify 199 | **no** | permanent DEFER / NO_DENSIFY |
| Dataset COMPLETE invent | **no** | would require product de-scope of history or vendor historical API |
| Alternate history path | **later** | use **`fins_earnings_date`** (now 104/104 COMPLETE after W68) for publication history events — separate dataset, not earn_cal rewrite |
| Product decision | **later** | either vendor range API appears, or lower `history_target_start` / expected segs under explicit product gate — **not** floor-raise invent |

### B. `equities_master` (PD-D2-MASTER)

| step | safe? | action |
|------|:-----:|--------|
| Hold COMPLETE island `2008-05…2026-08` (220) | **yes** | do not re-open |
| Mass densify 94 | **no** | permanent DEFER |
| Surgical seal MISDATE on existing SUCCESS receipts | **no** | window_ok=0 |
| Surgical re-probe 1–2 MISDATE months if vendor Date behavior changes | **maybe** | only if fresh raw proves `Date ∈ segment month`; then seal path only for those months |
| PRE_PLAN 73 | **no** | subscription floor; no planner jobs |
| Raise history floor past residual to force Dataset COMPLETE | **no** | invent — banned |

### C. Cross-cutting

| rule | hold |
|------|------|
| empty-raw COMPLETE | forbidden |
| densify-as-success metric | no |
| bulk D1 / mass receipt write this residual | no |
| Mass / READY / Phase7 | NO-GO / OFF until product re-opens |

### Suggested future order (when product re-opens)

1. **earn_cal** — product/catalog decision (de-scope history **or** alternate source mapping); tip-only ops continue.  
2. **master MISDATE** — only after proven in-window Date raw (surgical, not bulk 21).  
3. **master PRE_PLAN** — only if subscription entitlement expands before 2006-08-13.

---

## 5. Honesty / return card

| field | value |
|-------|------:|
| earn COMPLETE / PARTIAL | **1 / 199** (unchanged) |
| master COMPLETE / PARTIAL | **220 / 94** (unchanged) |
| tip fetch empty vs nz | **nz** (rowsInserted=1, Date=`2026-08-17`) |
| history densify 199 | **0 executed** |
| master surgical seal candidates | **0** |
| D1 bulk writes | **0** |
| COMPLETE issued this wave | **0** |
| permanent DEFER held | PD-D4-EARN-CAL · PD-D2-MASTER |
| commit / push | **no** |

---

## Artifacts index

| path | content |
|------|---------|
| `.glm-logs/w0816d_w70_tip/status_counts.json` | live COMPLETE/PARTIAL counts |
| `.glm-logs/w0816d_w70_tip/dataset_coverage.json` | aggregate coverage rows |
| `.glm-logs/w0816d_w70_tip/earn_tip_collect_results.json` | live tip POST ×4 |
| `.glm-logs/w0816d_w70_tip/earn_tip_date_proof.json` | R2 Date hist for tip runs |
| `.glm-logs/w0816d_w70_tip/dry_earn_residual_*.json` | residual plan 199 dry-run |
| `.glm-logs/w0816d_w70_tip/master_*` | PARTIAL taxonomy + seal verdict |
| `.glm-logs/w0816d_w70_tip/FINAL_metrics.json` | machine summary |
| `.glm-logs/w0816d_w70_tip/d1q.py` | remote D1 helper used |
