# W54 / w0815au_g1 — T1–T5 multi-day signal eval via single_shot only (Mass OFF)

**Wave:** W54 / w0815au_g1 · T1–T5  
**Mass / Phase7:** **NO-GO / OFF** (held · not armed)  
**READY:** **not** declared (no READY claim)  
**Order execution:** **none**  
**densify / tip collect as primary:** **none**  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Push:** **not** this task (G4)

**Primary this lane (G1):** multi-day as_of batch of approved-leg tip signal `c21_topix_relative_sign` via `single_shot` only · aggregate stats · R2 `batch_summary.json` · re-assert Mass/READY/order non-connect  

**Prior signal E2E:** [`w0815at_w53_signal_e2e_20260815.md`](w0815at_w53_signal_e2e_20260815.md) · job `w0815at-g2-signal-e2e`  
**Fixed signal spec:** [`c21_topix_relative_sign_spec_20260815.md`](c21_topix_relative_sign_spec_20260815.md) (W54: `candidate_only=False` · approved legs only)

**Live verified:** 2026-08-15 ~`11:03Z` UTC  
**Code HEAD at run:** `918c5b23eea60e19f1512cd094399ddfbb86cbb7` (+ local W54 multiday path)  
**Logs:** [`.glm-logs/w0815au_g1_multiday/`](../../.glm-logs/w0815au_g1_multiday/)

---

## Verdict

| gate | result |
|------|--------|
| **E2E overall** | **PASS** |
| T1 approved-only signal definition | **PASS** (`c21_topix_relative_sign` · all legs approved · `candidate_only=False`) |
| T2 multi as_of batch (5–10 tip trading days) | **PASS** (`n_days=6` · codes 3 · CF D1 tip) |
| T3 per-day aggregate | **PASS** (count / non-null rate / sign dist) |
| T4 R2 write + heads | **PASS** (batch_summary + 6 day artifacts + manifest · all exist) |
| T5 no mass / READY / orders | **PASS** (AST + freeze + unit + live metadata) |
| This proof | **written** (no READY claim) |

**Honesty:** pass means a **bounded tip-window** multi-as_of single-shot path read CF D1 hot tip once, computed COMPLETE-21 tip features for each trading-day as_of, derived the minimal approved-leg signal, aggregated stats, and wrote research artifacts to R2. Success does **not** mean Mass GO, Phase7 ON, READY publication, order routing, full-history research load, densify, or promotion of the signal beyond `candidate`.

---

## 1. T1 — signal definition (approved features only)

| field | value |
|-------|------:|
| **signal_id** | `c21_topix_relative_sign` |
| **version** | `1.0.0` |
| **status** | `candidate` (not READY) |
| **candidate_only** | **false** |
| **approved_legs_only** | **true** |

| role | feature_id | registry status | version |
|------|------------|-----------------|---------|
| primary | `topix_relative_1d` | **approved** (W53 O2) | 1.0.0 |
| filter | `is_trading_day` | **approved** (W52) | 1.0.0 |
| gate | `volume_change_1d` | **approved** (W52) | 1.0.0 |

**Formula:**

```text
value = sign(topix_relative_1d)
  if is_trading_day == 1.0
  and (volume_change_abs_min is None or |volume_change_1d| >= abs_min)
  else None
```

Default `volume_change_abs_min = None` (gate off).  
Code SoT: `packages/research_runtime/features/minimal_signal.py`  
Spec freeze: [`c21_topix_relative_sign_spec_20260815.md`](c21_topix_relative_sign_spec_20260815.md)  
Log: `signal_definition.json`

---

## 2. T2 — multi as_of batch (single_shot · CF D1 tip)

| field | value |
|-------|------:|
| **job_id** | `w0815au-g1-multiday` |
| **path** | `research.single_shot_job.execute_multiday_signal_eval` |
| **tip window** | `2026-08-01` … `2026-08-14` |
| **n_days** | **6** (within 5–10; tip calendar trading days in window) |
| **as_of days** | `2026-08-03` · `04` · `05` · `06` · `07` · `10` |
| **as_of clock** | each day `T15:30:00+09:00` |
| **codes** | `13010` · `72030` · `67580` |
| **datasets** | `equities_bars_daily` · `markets_calendar` · `indices_bars_daily_topix` |
| **plane** | D1 hot tip (`quant-ingest`) via wrangler remote · **not** local SQLite SoT |

| tip extract | raw count | extracted (code-filtered) |
|-------------|----------:|--------------------------:|
| `equities_bars_daily` | 26671 | **18** (3 codes × 6 bar days) |
| `markets_calendar` | 11 | **11** |
| `indices_bars_daily_topix` | 6 | **6** |

**Note:** tip calendar/topix in this window tops out at **2026-08-10** (6 trading days Mon 08-03 … Mon 08-10). First as_of day (`2026-08-03`) has null 1d features (no prior tip bar) — honest null rate, not densified.

---

## 3. T3 — per-day aggregate

| date | signal_count | non_null | non_null_rate | +1 | 0 | −1 | null |
|------|-------------:|---------:|--------------:|---:|--:|---:|-----:|
| 2026-08-03 | 3 | 0 | 0.00 | 0 | 0 | 0 | 3 |
| 2026-08-04 | 3 | 3 | 1.00 | 0 | 0 | 3 | 0 |
| 2026-08-05 | 3 | 3 | 1.00 | 0 | 0 | 3 | 0 |
| 2026-08-06 | 3 | 3 | 1.00 | 3 | 0 | 0 | 0 |
| 2026-08-07 | 3 | 3 | 1.00 | 2 | 0 | 1 | 0 |
| 2026-08-10 | 3 | 3 | 1.00 | 1 | 0 | 2 | 0 |

### Overall aggregate

| metric | value |
|--------|------:|
| **n_days** | **6** |
| **signal_count** | **18** |
| **non_null** | **15** |
| **null** | **3** |
| **non_null_rate** | **0.833** |
| **sign +1** | **6** |
| **sign 0** | **0** |
| **sign −1** | **9** |

Log: `batch_summary.json` · `summary.json`

---

## 4. T4 — R2 write + head confirm

Bucket: **`quant-structured`**  
Confirm: `wrangler r2 object get … --remote` (head-by-download).

| key | exists | bytes |
|-----|:------:|------:|
| `research/single_shot/job=w0815au-g1-multiday/batch_summary.json` | yes | 7326 |
| `research/single_shot/job=w0815au-g1-multiday/manifest.json` | yes | 1728 |
| `…/days/date=2026-08-03/signals.json` | yes | 6034 |
| `…/days/date=2026-08-04/signals.json` | yes | 6134 |
| `…/days/date=2026-08-05/signals.json` | yes | 6136 |
| `…/days/date=2026-08-06/signals.json` | yes | 6119 |
| `…/days/date=2026-08-07/signals.json` | yes | 6124 |
| `…/days/date=2026-08-10/signals.json` | yes | 6133 |

R2 put statuses: `put_ok` × **8**  
Log: `r2_heads.json` · `e2e_run.log`

---

## 5. T5 — hard closed: no mass / READY / orders

### Freeze constants

| constant | value |
|----------|------:|
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| ready_publication | **OFF** |
| ready_declared | **false** |
| order_execution | **false** |
| connected_to_mass_research_loop | **false** |
| local_sot | **false** |
| densify | **false** |
| signal candidate_only | **false** (legs approved; signal status still candidate) |

### AST / unit

Modules: `single_shot_job.py`, `minimal_signal.py`

* no `agents` / `mass_research` / `start_mass_research` / `require_mass_research_start` imports  
* no `VerifiedResearchReadiness` / READY mint path  
* no `OrderIntent` / `paper_service` / `place_order` / `submit_order`  

Unit: `tests/test_single_shot_research_job.py` multiday suite + existing T7/T9 freezes · **34** passed (file) with mass gate  
Log: `pytest_t5.log` · `t5_assert.json` · `freeze_status.json`

---

## 6. Code / artifact map

| item | path |
|------|------|
| Multiday API | `packages/product/research/single_shot_job.py` → `execute_multiday_signal_eval` |
| Signal pure compute | `packages/research_runtime/features/minimal_signal.py` |
| Signal spec | `docs/proof/c21_topix_relative_sign_spec_20260815.md` |
| Unit tests | `tests/test_single_shot_research_job.py` (W54 block) |
| R2 batch summary | `research/single_shot/job=w0815au-g1-multiday/batch_summary.json` |
| Logs | `.glm-logs/w0815au_g1_multiday/` |

---

## 7. Explicit non-claims

* **READY** not declared / not published  
* **Mass research** not started / not connected  
* **Phase7** not armed  
* **Orders** not emitted / paper execution not called  
* **densify** not run  
* **local SQLite** is not Source of Truth  
* Signal **status remains `candidate`** even with approved legs  

---

## Return card

| field | value |
|-------|------:|
| **n_days** | **6** |
| **summary stats** | signal_count=18 · non_null=15 · rate=0.833 · +1=6 · 0=0 · −1=9 · null=3 |
| **R2 path** | `research/single_shot/job=w0815au-g1-multiday/batch_summary.json` |
| **pass/fail** | **PASS** |
