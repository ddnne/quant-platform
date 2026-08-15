# W57 / w0815ax_g1 — T1–T4 expand code universe 20–50 for 20-day nextday eval

**Wave:** W57 / w0815ax_g1 · T1–T4  
**Label:** **小サンプル / 研究用・未宣言** (all nextday outputs)  
**Mass / Phase7:** **NO-GO / OFF** (held · not armed)  
**READY:** **not** declared (no READY claim)  
**Order execution:** **none**  
**densify / tip collect as primary:** **none**  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Push:** **not** this task  
**Significance / edge claim:** **none** (explicitly denied)

**Primary this lane (G1):** expand research-only multiday + next-day return eval to **20–50 equities** with CF D1 tip bars (prefer liquid / diverse) · keep ~**20 trading days** (W56 expand20 approach) · re-aggregate sign-wise **mean and median** next-day return · R2 under `job=w0815ax-g1-universe` · re-assert Mass/READY/order non-connect · look-ahead policy held  

**Prior expand20 (W56):** [`w0815aw_w56_expand20_nextday_eval_20260815.md`](w0815aw_w56_expand20_nextday_eval_20260815.md) · job `w0815aw-g1-expand20` · **n_days=20** · **n_codes=3**  
**Signal:** `c21_topix_relative_sign@1.0.0` · `candidate_only=False` · status `candidate` · approved legs only

**Live verified:** 2026-08-15 ~`11:51Z` UTC  
**Code HEAD at run:** `8381d9106167d65118f57509d67ed488419ceddf`  
**Logs:** [`.glm-logs/w0815ax_g1_universe/`](../../.glm-logs/w0815ax_g1_universe/)

---

## Verdict

| gate | result |
|------|--------|
| **E2E overall** | **PASS** |
| T1 select 20–50 codes with tip bars (CF D1, not local SoT) | **PASS** (**n_codes=30** · all 28 tip days) |
| T2 re-run harness (~20 trading days · approved-leg signal) | **PASS** (**n_days=20**) |
| T3 sign-wise mean/**median** + null rates + counts | **PASS** |
| T4 labels **小サンプル / 研究用・未宣言** · no significance · no READY · R2 + proof | **PASS** (`job=w0815ax-g1-universe` · this doc) |
| Look-ahead ban | **held** (feature as_of = T close; return T+1 only) |
| This proof | **written** (小サンプル / 研究用・未宣言 · no READY claim) |

**Honesty:** pass means a **bounded tip-window** multi-as_of single-shot path read CF D1 hot tip once over extract `2026-07-01`…`2026-08-14`, selected **30** liquid/diverse codes with multi-day tip bars, discovered **28** trading days in tip, selected the last **20** as_of days, computed COMPLETE-21 tip features for each trading-day as_of **T close only**, derived the minimal approved-leg signal, attached `R_{T→T+1}` when T+1 bar was PIT-available at evaluation_as_of = T+1 close, summarized **mean and median** returns by sign, and wrote research artifacts to R2. Success does **not** mean Mass GO, Phase7 ON, READY publication, order routing, statistical significance, densify, edge claim, or promotion of the signal beyond `candidate`.

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

## 1. T1 — select 20–50 codes with available tip bars

| field | value |
|-------|------:|
| **plane** | CF D1 `quant-ingest` hot tip (`jquants_records`) · **not** local SQLite SoT |
| **tip extract window** | `2026-07-01` … `2026-08-14` |
| **selection policy** | prefer liquid / diverse TSE probes; require multi-day tip bars (≥15 preferred; all selected had **28**) |
| **preferred probe pool** | 50 liquid names across auto / tech / finance / retail / materials / telecom / pharma / trading houses |
| **preferred with 28 tip days** | **49 / 50** (`96130` = 0 → dropped) |
| **n_codes selected** | **30** (within band **20–50**) |
| **selected codes** | `13010` · `72030` · `67580` · `99840` · `83060` · `68610` · `65010` · `40630` · `80350` · `94320` · `45020` · `63670` · `60980` · `79740` · `69810` · `45680` · `80010` · `80020` · `80580` · `94330` · `29140` · `33820` · `46610` · `49010` · `51080` · `54010` · `57130` · `62730` · `63010` · `65030` |

Log: `t1_code_universe.json`

---

## 2. T2 — re-run harness (~20 days · expanded universe)

| field | value |
|-------|------:|
| **job_id** | `w0815ax-g1-universe` |
| **path** | `research.eval_harness.run_nextday_return_eval` → `execute_multiday_nextday_return_eval` |
| **signal** | `c21_topix_relative_sign@1.0.0` · status `candidate` · **candidate_only=False** |
| **approved legs** | `topix_relative_1d` · `is_trading_day` · `volume_change_1d` (all registry-approved) |
| **tip extract window** | `2026-07-01` … `2026-08-14` (same as W56) |
| **tip trading days available** | **28** (`2026-07-01`…`2026-08-10`) |
| **max_days** | **20** |
| **n_days (as_of)** | **20** (last 20 of tip calendar; target met) |
| **as_of (signal) days** | `2026-07-13` · `14` · `15` · `16` · `17` · `21` · `22` · `23` · `24` · `27` · `28` · `29` · `30` · `31` · `2026-08-03` · `04` · `05` · `06` · `07` · `10` |
| **feature as_of clock** | each day `T15:30:00+09:00` |
| **evaluation_as_of** | next trading day `T15:30:00+09:00` when present |
| **n_codes** | **30** |
| **feature_row_limit** | **2000** (needed for 30 × 28 tip bars) |
| **datasets** | `equities_bars_daily` · `markets_calendar` · `indices_bars_daily_topix` |
| **plane** | D1 hot tip via wrangler remote · **not** local SQLite SoT |
| **history structured tip** | **not required** (D1 tip alone yielded ≥20 days + full code coverage) |

### Tip extract honesty

| dataset | raw tip count (window) | extracted rows |
|---------|-----------------------:|---------------:|
| `equities_bars_daily` | 124367 | **840** (30 codes × 28 days) |
| `markets_calendar` | 42 | **42** |
| `indices_bars_daily_topix` | 28 | **28** |

* Tip bar / topix plane tops out at **2026-08-10** (no densify / no invent).  
* Last signal day `2026-08-10` has no T+1 in tip → honest null next-day returns (**30** code-rows = overall null return count).  
* First as_of day `2026-07-13` has prior bars in tip (window starts `2026-07-01`) → 1d features non-null (signal non_null_rate overall **1.0**).  
* History R2 structured tip **not** pulled — D1 tip alone reached target.

---

## 3. T3 — sign-wise mean / median next-day return

### Signal aggregate

| metric | value |
|--------|------:|
| **n_days** | **20** |
| **n_codes** | **30** |
| **signal_count** | **600** (20 × 30) |
| **non_null** | **600** |
| **null** | **0** |
| **non_null_rate** | **1.0** |
| **sign +1** | **312** |
| **sign 0** | **0** |
| **sign −1** | **288** |

### Next-day return by sign (**小サンプル / 研究用・未宣言**)

| sign | count | non_null ret | null ret | null rate | **mean R** | **median R** |
|------|------:|-------------:|---------:|----------:|-----------:|-------------:|
| **+1** | 312 | 299 | 13 | 0.042 | **+0.00823** | **+0.00900** |
| **0** | 0 | 0 | 0 | — | — | — |
| **−1** | 288 | 271 | 17 | 0.059 | **−0.00202** | **−0.00098** |
| **null_signal** | 0 | 0 | 0 | — | — | — |
| **overall** | 600 | 570 | 30 | 0.050 | **+0.00336** | **+0.00305** |
| **signed only** | 600 | 570 | 30 | 0.050 | +0.00336 | +0.00305 |

**Not a trading claim.** n_days=20 × n_codes=30 is still **小サンプル** (tip-only · research window · no OOS). No statistical significance test; no edge / alpha claim. Research labeling only.

### Vs W56 (3-code expand20) — descriptive only, not significance

| metric | W56 (n_codes=3) | W57 (n_codes=30) |
|--------|----------------:|-----------------:|
| signal_count | 60 | **600** |
| +1 mean R | +0.01075 | **+0.00823** |
| −1 mean R | −0.00459 | **−0.00202** |
| overall mean R | +0.00375 | **+0.00336** |
| overall median R | +0.00177 | **+0.00305** |
| return null rate | 0.05 | **0.05** |
| signal non_null_rate | 1.0 | **1.0** |

Log: `batch_summary.json` · `summary.json`

---

## 4. T4 — labels + non-claims + R2

### Hard labels / freeze

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

Log: `t5_assert.json` · `freeze_status.json` · `signal_definition.json`

### R2 write + head confirm

Bucket: **`quant-structured`**  
Prefix: `research/single_shot/job=w0815ax-g1-universe/`  
Confirm: `wrangler r2 object get … --remote` (head-by-download via `head_r2_object`).

| key | exists | bytes |
|-----|:------:|------:|
| `research/single_shot/job=w0815ax-g1-universe/batch_summary.json` | yes | 150140 |
| `research/single_shot/job=w0815ax-g1-universe/manifest.json` | yes | 8063 |
| `…/days/date=2026-07-13/signals.json` | yes | 60714 |
| `…/days/date=2026-08-10/signals.json` | yes | 59469 |
| `…/days/date=*/signals.json` | yes × **20** | ~59–61k each |

R2 put statuses: `put_ok` × **22** (batch_summary + manifest + 20 day signals)  
Log: `r2_heads.json` · `e2e_run.log`

---

## 5. Code / artifact map

| item | path |
|------|------|
| Eval harness entry | `packages/product/research/eval_harness.py` → `run_nextday_return_eval` |
| Multiday + nextday API | `packages/product/research/single_shot_job.py` → `execute_multiday_nextday_return_eval` |
| Helpers | `attach_next_day_returns` · `summarize_nextday_by_sign` (mean+**median**) · `build_equity_close_index` · `NEXTDAY_LOOKAHEAD_POLICY` · `NEXTDAY_RESEARCH_LABEL` |
| Signal pure compute | `packages/research_runtime/features/minimal_signal.py` |
| R2 batch summary | `research/single_shot/job=w0815ax-g1-universe/batch_summary.json` |
| Logs | `.glm-logs/w0815ax_g1_universe/` |
| Prior W56 proof | `docs/proof/w0815aw_w56_expand20_nextday_eval_20260815.md` |

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
* **No push** from this task  

---

## Return card

| field | value |
|-------|------:|
| **pass/fail** | **PASS** |
| **R2 path** | `research/single_shot/job=w0815ax-g1-universe/batch_summary.json` |
| **n_codes** | **30** (band 20–50) |
| **n_days** | **20** |
| **tip available trading days** | **28** (extract window met target without history tip) |
| **sign mean R** | +1: **+0.00823** (n_ret=299) · 0: — · −1: **−0.00202** (n_ret=271) |
| **sign median R** | +1: **+0.00900** · 0: — · −1: **−0.00098** |
| **overall mean / median R** | **+0.00336** / **+0.00305** |
| **return null rate (overall)** | **0.05** (30/600) |
| **signal non_null_rate** | **1.0** (600/600) |
| **label** | **小サンプル / 研究用・未宣言** |
| **Mass / READY** | **OFF** / **not declared** |
| **significance / edge** | **false** / **false** |
