# W55 / w0815av_g1 — T1–T4 multi-day signal + next-day return alignment (research only)

**Wave:** W55 / w0815av_g1 · T1–T4  
**Label:** **研究用・未宣言** (all outputs)  
**Mass / Phase7:** **NO-GO / OFF** (held · not armed)  
**READY:** **not** declared (no READY claim)  
**Order execution:** **none**  
**densify / tip collect as primary:** **none**  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Push:** **not** this task  

**Primary this lane (G1):** attach next-day close-to-close return to multiday tip signal batch via `single_shot` only · mean return by signal sign · R2 under `job=w0815av-g1-nextday` · re-assert Mass/READY/order non-connect · look-ahead policy frozen  

**Prior multiday (W54):** [`w0815au_w54_multiday_signal_eval_20260815.md`](w0815au_w54_multiday_signal_eval_20260815.md) · job `w0815au-g1-multiday`  
**Signal:** `c21_topix_relative_sign@1.0.0` · `candidate_only=False` · status `candidate`

**Live verified:** 2026-08-15 ~`11:20Z` UTC  
**Code HEAD at run:** `205392f54ca832d67867fe96c149867f52586def` (+ local W55 nextday path)  
**Logs:** [`.glm-logs/w0815av_g1_nextday/`](../../.glm-logs/w0815av_g1_nextday/)

---

## Verdict

| gate | result |
|------|--------|
| **E2E overall** | **PASS** |
| T1 attach next-day return per code/day | **PASS** (PIT-gated; tip edge → null) |
| T2 mean next-day return by sign (+1/0/−1) | **PASS** (counts + null rates) |
| T3 R2 write + proof | **PASS** (`job=w0815av-g1-nextday` · this doc) |
| T4 no mass / READY + look-ahead documented | **PASS** (AST + unit + freeze + policy) |
| This proof | **written** (研究用・未宣言 · no READY claim) |

**Honesty:** pass means a **bounded tip-window** multi-as_of single-shot path read CF D1 hot tip once, computed COMPLETE-21 tip features for each trading-day as_of **T close only**, derived the minimal approved-leg signal, attached `R_{T→T+1}` when T+1 bar was PIT-available at evaluation_as_of = T+1 close, summarized mean returns by sign, and wrote research artifacts to R2. Success does **not** mean Mass GO, Phase7 ON, READY publication, order routing, statistical significance, densify, or promotion of the signal beyond `candidate`.

---

## 0. Look-ahead policy (frozen)

| field | value |
|-------|------:|
| **feature_as_of** | signal day **T** session close (`T15:30:00+09:00`) |
| **feature PIT** | `available_at <= feature_as_of` (T+1 bars never enter features) |
| **return** | `close(T+1) / close(T) − 1` |
| **evaluation_as_of** | next trading day **T+1** session close |
| **return PIT** | both T and T+1 bars require `available_at <= evaluation_as_of` |
| **tip edge** | missing T+1 → `next_day_return = null` (counted in null rate) |
| **label** | 研究用・未宣言 |

Code SoT: `NEXTDAY_LOOKAHEAD_POLICY` in `packages/product/research/single_shot_job.py`  
Log: `lookahead_policy.json`

---

## 1. T1 — attach next-day return

| field | value |
|-------|------:|
| **job_id** | `w0815av-g1-nextday` |
| **path** | `research.single_shot_job.execute_multiday_nextday_return_eval` |
| **wrapper** | `execute_multiday_signal_eval(..., attach_nextday_returns=True)` |
| **tip window** | `2026-08-01` … `2026-08-14` |
| **n_days** | **6** |
| **as_of (signal) days** | `2026-08-03` · `04` · `05` · `06` · `07` · `10` |
| **feature as_of clock** | each day `T15:30:00+09:00` |
| **evaluation_as_of** | next trading day `T15:30:00+09:00` when present |
| **codes** | `13010` · `72030` · `67580` |
| **datasets** | `equities_bars_daily` · `markets_calendar` · `indices_bars_daily_topix` |
| **plane** | D1 hot tip (`quant-ingest`) via wrangler remote · **not** local SQLite SoT |

Per observation fields added when possible:

* `next_day_return`, `next_day_date`, `close_T`, `close_T1`
* `feature_as_of`, `evaluation_as_of`
* `next_day_return_pit_ok`, `next_day_return_null_reason`

**Note:** tip calendar/topix in this window tops out at **2026-08-10**. Last signal day has no T+1 bar → honest null next-day returns (3 rows). First day (`2026-08-03`) has null **signal** (no prior tip bar for 1d features) but can still have T→T+1 returns.

---

## 2. T2 — mean next-day return by signal sign

### Signal aggregate (same window as W54)

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

### Next-day return by sign (研究用・未宣言)

| sign | count | non_null ret | null ret | null rate | **mean R_{T→T+1}** |
|------|------:|-------------:|---------:|----------:|-------------------:|
| **+1** | 6 | 5 | 1 | 0.167 | **+0.01362** (~1.36%) |
| **0** | 0 | 0 | 0 | — | — |
| **−1** | 9 | 7 | 2 | 0.222 | **+0.00594** (~0.59%) |
| **null_signal** | 3 | 3 | 0 | 0.0 | −0.01192 |
| **overall** | 18 | 15 | 3 | 0.167 | +0.00493 |
| **signed only** | 15 | 12 | 3 | 0.200 | +0.00914 |

**Not a trading claim.** Tiny tip window (n≈12 signed non-null returns); both +1 and −1 mean returns are positive in this sample — noise expected. Research labeling only.

Log: `batch_summary.json` · `summary.json`

---

## 3. T3 — R2 write + head confirm

Bucket: **`quant-structured`**  
Prefix: `research/single_shot/job=w0815av-g1-nextday/`  
Confirm: `wrangler r2 object get … --remote` (head-by-download).

| key | exists | bytes |
|-----|:------:|------:|
| `research/single_shot/job=w0815av-g1-nextday/batch_summary.json` | yes | 31290 |
| `research/single_shot/job=w0815av-g1-nextday/manifest.json` | yes | 5135 |
| `…/days/date=2026-08-03/signals.json` | yes | 11288 |
| `…/days/date=2026-08-04/signals.json` | yes | 11404 |
| `…/days/date=2026-08-05/signals.json` | yes | 11397 |
| `…/days/date=2026-08-06/signals.json` | yes | 11379 |
| `…/days/date=2026-08-07/signals.json` | yes | 11407 |
| `…/days/date=2026-08-10/signals.json` | yes | 11182 |

R2 put statuses: `put_ok` × **8**  
Log: `r2_heads.json` · `e2e_run.log`

---

## 4. T4 — hard closed: no mass / READY / orders + look-ahead tests

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
| attach_nextday_returns | **true** |
| label | **研究用・未宣言** |
| no_feature_lookahead | **true** |

### AST / unit

Modules: `single_shot_job.py` (nextday helpers + multiday flag)

* no `agents` / `mass_research` / `start_mass_research` / `require_mass_research_start` imports  
* no `VerifiedResearchReadiness` / READY mint path  
* no `OrderIntent` / `paper_service` / `place_order` / `submit_order`  
* `NEXTDAY_LOOKAHEAD_POLICY` documents feature as_of = T close, eval as_of = T+1 close  
* unit: attach formula + PIT fail + tip-edge null + mean-by-sign + batch R2 shape  

Unit: `tests/test_single_shot_research_job.py` W55 suite + W54 multiday + T7/T9 freezes · **35** passed (file)  
Log: `pytest_t4.log` · `t5_assert.json` · `freeze_status.json` · `lookahead_policy.json`

---

## 5. Code / artifact map

| item | path |
|------|------|
| Multiday + nextday API | `packages/product/research/single_shot_job.py` → `execute_multiday_nextday_return_eval` / `attach_nextday_returns` |
| Helpers | `attach_next_day_returns` · `summarize_nextday_by_sign` · `build_equity_close_index` · `NEXTDAY_LOOKAHEAD_POLICY` |
| Signal pure compute | `packages/research_runtime/features/minimal_signal.py` |
| Unit tests | `tests/test_single_shot_research_job.py` (W55 block) |
| R2 batch summary | `research/single_shot/job=w0815av-g1-nextday/batch_summary.json` |
| Logs | `.glm-logs/w0815av_g1_nextday/` |

---

## 6. Explicit non-claims

* **READY** not declared / not published  
* **Mass research** not started / not connected  
* **Phase7** not armed  
* **Orders** not emitted / paper execution not called  
* **densify** not run  
* **local SQLite** is not Source of Truth  
* Signal **status remains `candidate`**  
* Mean returns are **not** alpha / edge claims (n small · tip only)  
* Outputs labeled **研究用・未宣言**

---

## Return card

| field | value |
|-------|------:|
| **pass/fail** | **PASS** |
| **R2 path** | `research/single_shot/job=w0815av-g1-nextday/batch_summary.json` |
| **n_days** | **6** |
| **sign-mean returns** | +1: **+0.01362** (n_ret=5) · 0: — · −1: **+0.00594** (n_ret=7) · null_signal: −0.01192 (n_ret=3) |
| **return null rate (overall)** | **0.167** (3/18) |
| **label** | 研究用・未宣言 |
