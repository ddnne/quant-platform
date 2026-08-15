# W58 / w0815ay_g1 — T1–T3 history window expand investigation + tip-max eval

**Wave:** W58 / w0815ay_g1 · T1–T3  
**Label:** **小サンプル / 研究用・未宣言** (all nextday outputs)  
**Mass / Phase7:** **NO-GO / OFF** (held · not armed)  
**READY:** **not** declared (no READY claim)  
**Order execution:** **none**  
**densify / tip collect as primary:** **none**  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Push:** **not** this task  
**Significance / edge claim:** **none** (explicitly denied)

**Primary this lane (G1):** investigate whether R2 structured history (`quant-structured` live JSONL and/or `archive/jquants_records`) can extend multiday nextday eval beyond D1 tip (~28 trading days) to **40–60 trading days** for `equities_bars_daily` + `indices_bars_daily_topix` + `markets_calendar`. If possible, run CF-SoT eval with **20–30 codes** (W57 universe). If not, stay tip max and document honest blockers.

**Prior (W57):** [`w0815ax_w57_universe_expand_eval_20260815.md`](w0815ax_w57_universe_expand_eval_20260815.md) · job `w0815ax-g1-universe` · **n_days=20** · **n_codes=30**  
**Signal:** `c21_topix_relative_sign@1.0.0` · `candidate_only=False` · status `candidate` · approved legs only

**Live verified:** 2026-08-15 ~`12:12Z` UTC  
**Code HEAD at run:** `e86a4cc584891ad15b346294053c1e5705c9f286`  
**Logs:** [`.glm-logs/w0815ay_g1_history/`](../../.glm-logs/w0815ay_g1_history/)

---

## Verdict

| gate | result |
|------|--------|
| **T1 history expand investigation** | **DONE** — **history_expand_possible = NO** |
| **T2 40–60 day eval** | **NOT RUN** (blocked; data path cannot invent pre-tip history) |
| **T3 tip-max stay + proof** | **PASS** (**n_days=28** tip max · **n_codes=30**) |
| Look-ahead ban | **held** (feature as_of = T close; return T+1 only) |
| Mass / READY / densify / push | **OFF / not declared / none / none** |
| This proof | **written** (小サンプル / 研究用・未宣言 · no READY claim) |

**Honesty:** R2 **does** hold long structured history for the three datasets (JSONL + cold archive). The research multiday eval path **does not** load that history — it is a **D1 hot tip extract only** path. Hot cutoff is **`2026-07-01`**, yielding **28** trading days for bars/topix. Without an R2→FeatureContext history bridge (Artifacts JOIN plane still residual), **40–60 day evaluation is not possible without inventing data**. This wave stayed on **tip max (28)** with the W57 30-code universe and wrote research artifacts to R2. Success does **not** mean Mass GO, Phase7 ON, READY, edge claim, or 40–60 day window achieved.

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

## 1. T1 — history expand investigation

### 1.1 Question

Can R2 structured history extend eval beyond D1 tip (~28 trading days) to **40–60** for:

* `equities_bars_daily`
* `indices_bars_daily_topix`
* `markets_calendar`

### 1.2 Live D1 tip extent (CF SoT · remote)

| dataset | row count | min event day | max event day | distinct trading days |
|---------|----------:|---------------|---------------|----------------------:|
| `equities_bars_daily` | 124367 | **2026-07-01** | **2026-08-10** | **28** |
| `indices_bars_daily_topix` | 28 | **2026-07-01** | **2026-08-10** | **28** |
| `markets_calendar` | 42 | **2026-07-01** | **2026-08-11** | (calendar grain) |

Log: `d1_tip_extent.json` · `d1_trading_days.json` · `d1_topix_days.json`

**Hot cutoff:** `2026-07-01` (ops / CF-native plane · cold `<2026-07-01` archived out of D1).

### 1.3 R2 history presence (proved · not invented)

`POST /v1/ops/artifacts-join-plan` (`artifacts-join-plan/v1`, mass **NO-GO**) for the three datasets (`from=2026-04-01`…`to=2026-08-14`):

| dataset | r2_jsonl keys listed | truncated | r2_archive keys listed | truncated |
|---------|---------------------:|:---------:|-----------------------:|:---------:|
| `equities_bars_daily` | 50 | **yes** | 50 | **yes** |
| `indices_bars_daily_topix` | 50 | **yes** | 12 | no |
| `markets_calendar` | 50 | **yes** | 17 | no |

Sample object GET (wrangler remote · bucket `quant-structured`):

| key | bytes | content note |
|-----|------:|--------------|
| `structured/jsonl/equities_bars_daily/dt=2008-05-07/…mmwbjs.jsonl` | 11 337 054 | `event_time` **2008-05-07** · bars payload for Code `13010` etc. |
| `archive/jquants_records/indices_bars_daily_topix/batch/08088fff-…_after227044.ndjson` | 131 402 | 400 rows · sample event span **2009-12-21…2011-08-09** |
| `structured/jsonl/markets_calendar/dt=2026-08-01/…4qn6pm.jsonl` | 4 648 | live JSONL calendar shard |

Logs: `artifacts_join_plan.json` · `r2_samples/` · `r2_get_*.log` · `t1_investigation_findings.json`

**Conclusion on data existence:** R2 history **exists** far beyond the tip window (multi-year JSONL + cold archive batches).

### 1.4 Why eval cannot use it today (honest blockers)

| blocker | detail |
|---------|--------|
| **Tip-only extract path** | `execute_multiday_signal_eval` / `run_nextday_return_eval` → `extract_d1_tip_feature_rows` only (remote D1 `jquants_records`). Docstring: *“CF D1 tip only”*. |
| **Missing R2 history bridge** | `design_artifact_paths().history_input_patterns` documents `structured/jsonl/…` and `archive/jquants_records/…` as **input design notes**. There is **no** Python loader that merges R2 cold rows into the multiday tip `FeatureContext`. Grep: only those pattern strings under product/research. |
| **Hot D1 cutoff** | Pre-`2026-07-01` structured rows were archived then deleted from D1 (cf-arch final gate: cold jquants=0). Extending `period_start` below cutoff returns empty pre-tip facts on D1. |
| **Artifacts JOIN plane residual** | `artifacts-join-plan/v1` is **discovery-only** (keys + D1 hot SQL). Final gate residual explicitly listed JOIN plane as unbuilt; true Parquet JOIN is follow-on. |

**history_expand_possible:** **`no`**  
**Not** “R2 empty.” **Yes** “eval path is tip-only · bridge missing · do not invent.”

Log: `t1_investigation_findings.json` · `tip_window.json`

---

## 2. T2 — 40–60 day eval (not possible)

| field | value |
|-------|------:|
| **requested** | 40–60 trading days · codes 20–30 · CF SoT · look-ahead ban |
| **executed as 40–60** | **no** |
| **reason** | blockers in §1.4 — would require new R2 history bridge (out of this task · inventing pre-tip rows forbidden) |

No densify. No Mass. No push.

---

## 3. T3 — stay tip max · tip-max eval ran

| field | value |
|-------|------:|
| **job_id** | `w0815ay-g1-history60` |
| **path** | `research.eval_harness.run_nextday_return_eval` → `execute_multiday_nextday_return_eval` |
| **tip extract window** | `2026-07-01` … `2026-08-14` |
| **tip trading days available** | **28** (`2026-07-01`…`2026-08-10`) |
| **max_days** | **28** (tip max; target 40–60 not reachable) |
| **n_days (as_of)** | **28** |
| **n_codes** | **30** (W57 universe reuse) |
| **feature_row_limit** | **2000** |
| **datasets** | `equities_bars_daily` · `markets_calendar` · `indices_bars_daily_topix` |
| **plane** | D1 hot tip via wrangler remote · **not** local SQLite SoT |
| **history_structured_tip_used** | **false** |

### Tip extract honesty

| dataset | raw tip count (window) | extracted rows |
|---------|-----------------------:|---------------:|
| `equities_bars_daily` | 124367 | **840** (30 × 28) |
| `markets_calendar` | 42 | **42** |
| `indices_bars_daily_topix` | 28 | **28** |

### Signal aggregate (tip max)

| metric | value |
|--------|------:|
| **n_days** | **28** |
| **signal_count** | **840** (28 × 30) |
| **non_null** | **810** |
| **null** | **30** (day **2026-07-01** · no prior bar in tip for 1d features) |
| **non_null_rate** | **0.9643** |
| **sign +1** | **424** |
| **sign 0** | **0** |
| **sign −1** | **386** |
| **sign null** | **30** |

### Next-day return by sign (**小サンプル / 研究用・未宣言**)

| sign | count | non_null ret | null ret | null rate | **mean R** | **median R** |
|------|------:|-------------:|---------:|----------:|-----------:|-------------:|
| **+1** | 424 | 411 | 13 | 0.031 | **+0.00643** | **+0.00648** |
| **0** | 0 | 0 | 0 | — | — | — |
| **−1** | 386 | 369 | 17 | 0.044 | **−0.00148** | **−0.00093** |
| **null_signal** | 30 | 30 | 0 | 0.0 | +0.00980 | +0.02149 |
| **overall** | 840 | 810 | 30 | 0.036 | **+0.00295** | **+0.00244** |
| **signed only** | 810 | 780 | 30 | 0.037 | **+0.00269** | **+0.00208** |

**Not a trading claim.** n_days=28 still **小サンプル** (tip-only · 30 codes · first tip day null 1d features · tip-edge null returns). No statistical significance; no edge / alpha claim.

Log: `batch_summary.json` · `r2_batch_summary.json` · `execution.json` · `e2e_run.log`

---

## 4. R2 write + head confirm

Bucket: **`quant-structured`**  
Prefix: `research/single_shot/job=w0815ay-g1-history60/`

| key | exists | bytes |
|-----|:------:|------:|
| `research/single_shot/job=w0815ay-g1-history60/batch_summary.json` | yes | 206950 |
| `research/single_shot/job=w0815ay-g1-history60/manifest.json` | yes | 9153 |
| `…/days/date=2026-07-01/signals.json` | yes | 60032 |
| `…/days/date=2026-08-10/signals.json` | yes | 59470 |
| per-day signals | yes × **28** | — |

R2 put statuses: `put_ok` × **30** (batch_summary + manifest + 28 day signals)  
Log: `r2_heads.json`

---

## 5. Code / artifact map

| item | path |
|------|------|
| Eval harness | `packages/product/research/eval_harness.py` → `run_nextday_return_eval` |
| Multiday + nextday API | `packages/product/research/single_shot_job.py` → `execute_multiday_nextday_return_eval` · **tip-only** |
| History patterns (design only) | `design_artifact_paths()["history_input_patterns"]` |
| Artifacts discovery | worker `ops_artifacts_plan.ts` · `/v1/ops/artifacts-join-plan` |
| Cold archive writer | `ops_cold_archive.ts` → `archive/jquants_records/{ds}/batch/…` |
| Live JSONL writer | `r2_structured_writer.ts` → `structured/jsonl/{ds}/dt=…` |
| Investigation log | `.glm-logs/w0815ay_g1_history/t1_investigation_findings.json` |
| R2 batch summary | `research/single_shot/job=w0815ay-g1-history60/batch_summary.json` |
| Prior W57 proof | `docs/proof/w0815ax_w57_universe_expand_eval_20260815.md` |

---

## 6. Explicit non-claims

* **READY** not declared / not published  
* **Mass research** not started / not connected  
* **Phase7** not armed  
* **Orders** not emitted / paper execution not called  
* **densify** not run  
* **local SQLite** is not Source of Truth  
* **40–60 trading days not achieved** (tip max **28**)  
* R2 history **exists** but is **not** wired into this eval path  
* Signal **status remains `candidate`**  
* Mean/median returns are **not** alpha / edge claims (**小サンプル**)  
* **No statistical significance** claimed  
* Outputs labeled **小サンプル / 研究用・未宣言**

---

## Return card

| field | value |
|-------|------:|
| **history_expand_possible** | **no** |
| **n_days achieved** | **28** (tip max; target 40–60 **not** met) |
| **n_codes** | **30** |
| **sign mean R** | +1: **+0.00643** (n_ret=411) · −1: **−0.00148** (n_ret=369) |
| **sign median R** | +1: **+0.00648** · −1: **−0.00093** |
| **overall mean / median R** | **+0.00295** / **+0.00244** |
| **signal non_null_rate** | **0.964** (810/840) |
| **return null rate (overall)** | **0.036** (30/840) |
| **R2 path** | `research/single_shot/job=w0815ay-g1-history60/batch_summary.json` |
| **label** | **小サンプル / 研究用・未宣言** |
| **Mass / READY** | **OFF** / **not declared** |
| **pass/fail** | **PASS_TIP_MAX_ONLY** (investigation complete · 40–60 blocked honestly) |
