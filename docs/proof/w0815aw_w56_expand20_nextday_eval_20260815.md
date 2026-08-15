# W56 / w0815aw_g1 — T1–T4 expand multi-day nextday eval to ~20 trading days

**Wave:** W56 / w0815aw_g1 · T1–T4  
**Label:** **小サンプル / 研究用・未宣言** (all nextday outputs)  
**Mass / Phase7:** **NO-GO / OFF** (held · not armed)  
**READY:** **not** declared (no READY claim)  
**Order execution:** **none**  
**densify / tip collect as primary:** **none**  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Push:** **not** this task  
**Significance / edge claim:** **none** (explicitly denied)

**Primary this lane (G1):** expand research-only multiday + next-day return eval toward **~20 trading days** within available CF D1 tip window · re-aggregate sign-wise **mean and median** next-day return · R2 under `job=w0815aw-g1-expand20` · re-assert Mass/READY/order non-connect · look-ahead policy held  

**Prior nextday (W55):** [`w0815av_w55_nextday_return_eval_20260815.md`](w0815av_w55_nextday_return_eval_20260815.md) · job `w0815av-g1-nextday` · **n_days=6**  
**Signal:** `c21_topix_relative_sign@1.0.0` · `candidate_only=False` · status `candidate` · approved legs only

**Live verified:** 2026-08-15 ~`11:34Z` UTC  
**Code HEAD at run:** `c8423531cfe691eb6001e8f46d488310cc1e029b` (+ local W56 expand20 path: median + 小サンプル label + max_days default 20)  
**Logs:** [`.glm-logs/w0815aw_g1_expand20/`](../../.glm-logs/w0815aw_g1_expand20/)

---

## Verdict

| gate | result |
|------|--------|
| **E2E overall** | **PASS** |
| T1 expand to ~20 trading days (or max available) | **PASS** (**n_days=20** · tip had 28) |
| T2 re-aggregate sign-wise mean/**median** + null rates + counts | **PASS** |
| T3 always label **小サンプル / 研究用・未宣言** · no significance / no edge | **PASS** |
| T4 R2 write + proof | **PASS** (`job=w0815aw-g1-expand20` · this doc) |
| Look-ahead ban | **held** (feature as_of = T close; return T+1 only) |
| This proof | **written** (小サンプル / 研究用・未宣言 · no READY claim) |

**Honesty:** pass means a **bounded tip-window** multi-as_of single-shot path read CF D1 hot tip once over an extended extract (`2026-07-01`…`2026-08-14`), discovered **28** trading days in tip, selected the last **20** as_of days, computed COMPLETE-21 tip features for each trading-day as_of **T close only**, derived the minimal approved-leg signal, attached `R_{T→T+1}` when T+1 bar was PIT-available at evaluation_as_of = T+1 close, summarized **mean and median** returns by sign, and wrote research artifacts to R2. Success does **not** mean Mass GO, Phase7 ON, READY publication, order routing, statistical significance, densify, edge claim, or promotion of the signal beyond `candidate`.

---

## 0. Look-ahead policy (held · frozen)

| field | value |
|-------|------:|
| **feature_as_of** | signal day **T** session close (`T15:30:00+09:00`) |
| **feature PIT** | `available_at <= feature_as_of` (T+1 bars never enter features) |
| **return** | `close(T+1) / close(T) − 1` |
| **evaluation_as_of** | next trading day **T+1** session close |
| **return PIT** | both T and T+1 bars require `available_at <= evaluation_as_of` |
| **tip edge** | missing T+1 → `next_day_return = null` (counted in null rate) |
| **label** | 小サンプル / 研究用・未宣言 |
| **significance_claimed** | **false** |
| **edge_claimed** | **false** |

Code SoT: `NEXTDAY_LOOKAHEAD_POLICY` / `NEXTDAY_RESEARCH_LABEL` in `packages/product/research/single_shot_job.py`  
Log: `lookahead_policy.json`

---

## 1. T1 — expand tip window to ~20 trading days

| field | value |
|-------|------:|
| **job_id** | `w0815aw-g1-expand20` |
| **path** | `research.single_shot_job.execute_multiday_nextday_return_eval` |
| **wrapper** | `execute_multiday_signal_eval(..., attach_nextday_returns=True)` |
| **tip extract window** | `2026-07-01` … `2026-08-14` (**extended** from W55 `2026-08-01`…`14`) |
| **tip trading days available** | **28** (`2026-07-01`…`2026-08-10`) |
| **max_days** | **20** |
| **n_days (as_of)** | **20** (last 20 of tip calendar; target met) |
| **as_of (signal) days** | `2026-07-13` · `14` · `15` · `16` · `17` · `21` · `22` · `23` · `24` · `27` · `28` · `29` · `30` · `31` · `2026-08-03` · `04` · `05` · `06` · `07` · `10` |
| **feature as_of clock** | each day `T15:30:00+09:00` |
| **evaluation_as_of** | next trading day `T15:30:00+09:00` when present |
| **codes** | `13010` · `72030` · `67580` |
| **datasets** | `equities_bars_daily` · `markets_calendar` · `indices_bars_daily_topix` |
| **plane** | D1 hot tip (`quant-ingest`) via wrangler remote · **not** local SQLite SoT |
| **history structured tip** | **not required** (D1 tip alone yielded ≥20) |

### Tip extract honesty

| dataset | raw tip count (window) | extracted rows |
|---------|-----------------------:|---------------:|
| `equities_bars_daily` | 124367 | **84** (3 codes × 28 days) |
| `markets_calendar` | 42 | **42** |
| `indices_bars_daily_topix` | 28 | **28** |

* Tip bar / topix plane tops out at **2026-08-10** (no densify / no invent).  
* Last signal day `2026-08-10` has no T+1 in tip → honest null next-day returns (3 code-rows).  
* First as_of day `2026-07-13` has prior bars in tip (window starts `2026-07-01`) → 1d features non-null (signal non_null_rate overall **1.0**).  
* History R2 structured tip **not** pulled — D1 tip alone reached target.

---

## 2. T2 — sign-wise mean / median next-day return

### Signal aggregate

| metric | value |
|--------|------:|
| **n_days** | **20** |
| **signal_count** | **60** (20 × 3 codes) |
| **non_null** | **60** |
| **null** | **0** |
| **non_null_rate** | **1.0** |
| **sign +1** | **32** |
| **sign 0** | **0** |
| **sign −1** | **28** |

### Next-day return by sign (**小サンプル / 研究用・未宣言**)

| sign | count | non_null ret | null ret | null rate | **mean R** | **median R** |
|------|------:|-------------:|---------:|----------:|-----------:|-------------:|
| **+1** | 32 | 31 | 1 | 0.031 | **+0.01075** | **+0.01114** |
| **0** | 0 | 0 | 0 | — | — | — |
| **−1** | 28 | 26 | 2 | 0.071 | **−0.00459** | **−0.00296** |
| **null_signal** | 0 | 0 | 0 | — | — | — |
| **overall** | 60 | 57 | 3 | 0.050 | **+0.00375** | **+0.00177** |
| **signed only** | 60 | 57 | 3 | 0.050 | +0.00375 | +0.00177 |

**Not a trading claim.** n_days=20 still **小サンプル** (tip-only · 3 codes · ~57 signed non-null returns). No statistical significance test; no edge / alpha claim. Research labeling only.

Log: `batch_summary.json` · `summary.json`

---

## 3. T3 — label + non-claims (hard)

| constant | value |
|----------|------:|
| **label** | **小サンプル / 研究用・未宣言** |
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| ready_publication | **OFF** |
| ready_declared | **false** |
| order_execution | **false** |
| connected_to_mass_research_loop | **false** |
| local_sot | **false** |
| densify | **false** |
| attach_nextday_returns | **true** |
| **significance_claimed** | **false** |
| **edge_claimed** | **false** |
| no_feature_lookahead | **true** |

Unit: `tests/test_single_shot_research_job.py` W55/W56 block · **36** passed (file)  
Log: `pytest_t4.log` · `t5_assert.json` · `freeze_status.json`

---

## 4. T4 — R2 write + head confirm

Bucket: **`quant-structured`**  
Prefix: `research/single_shot/job=w0815aw-g1-expand20/`  
Confirm: `wrangler r2 object get … --remote` (head-by-download via `head_r2_object`).

| key | exists | bytes |
|-----|:------:|------:|
| `research/single_shot/job=w0815aw-g1-expand20/batch_summary.json` | yes | 104437 |
| `research/single_shot/job=w0815aw-g1-expand20/manifest.json` | yes | 7680 |
| `…/days/date=2026-07-13/signals.json` … `…/date=2026-08-10/signals.json` | yes × **20** | ~12k each |

R2 put statuses: `put_ok` × **22** (batch_summary + manifest + 20 day signals)  
Log: `r2_heads.json` · `e2e_run.log`

---

## 5. Code / artifact map

| item | path |
|------|------|
| Multiday + nextday API | `packages/product/research/single_shot_job.py` → `execute_multiday_nextday_return_eval` / `attach_nextday_returns` |
| Helpers | `attach_next_day_returns` · `summarize_nextday_by_sign` (mean+**median**) · `build_equity_close_index` · `NEXTDAY_LOOKAHEAD_POLICY` · `NEXTDAY_RESEARCH_LABEL` |
| Signal pure compute | `packages/research_runtime/features/minimal_signal.py` |
| Unit tests | `tests/test_single_shot_research_job.py` (W55/W56 block) |
| R2 batch summary | `research/single_shot/job=w0815aw-g1-expand20/batch_summary.json` |
| Logs | `.glm-logs/w0815aw_g1_expand20/` |
| Prior W55 proof | `docs/proof/w0815av_w55_nextday_return_eval_20260815.md` |

---

## 6. Explicit non-claims

* **READY** not declared / not published  
* **Mass research** not started / not connected  
* **Phase7** not armed  
* **Orders** not emitted / paper execution not called  
* **densify** not run  
* **local SQLite** is not Source of Truth  
* Signal **status remains `candidate`**  
* Mean/median returns are **not** alpha / edge claims (**小サンプル**)  
* **No statistical significance** claimed  
* Outputs labeled **小サンプル / 研究用・未宣言**

---

## Return card

| field | value |
|-------|------:|
| **pass/fail** | **PASS** |
| **R2 path** | `research/single_shot/job=w0815aw-g1-expand20/batch_summary.json` |
| **n_days** | **20** |
| **tip available trading days** | **28** (extract window met target without history tip) |
| **sign mean R** | +1: **+0.01075** (n_ret=31) · 0: — · −1: **−0.00459** (n_ret=26) |
| **sign median R** | +1: **+0.01114** · 0: — · −1: **−0.00296** |
| **overall mean / median R** | **+0.00375** / **+0.00177** |
| **return null rate (overall)** | **0.05** (3/60) |
| **signal non_null_rate** | **1.0** (60/60) |
| **label** | **小サンプル / 研究用・未宣言** |
| **Mass / READY** | **OFF** / **not declared** |
