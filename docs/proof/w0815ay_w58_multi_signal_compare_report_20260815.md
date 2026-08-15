# W58 / w0815ay_g2 — Multi-signal compare report (T4–T8)

**Template:** [`templates/research_signal_eval_report_template.md`](templates/research_signal_eval_report_template.md) v1.0.0  
**Wave:** W58 / w0815ay_g2 · multi-signal compare + research cost (T4–T8)  
**Report date:** 2026-08-15 ~`12:08Z` UTC  
**Label:** **小サンプル / 研究用・未宣言**  
**Cost label:** **仮定に依存・研究用・運用GOではない**  
**Mass / Phase7:** **NO-GO / OFF** (held · not armed)  
**READY:** **not** declared (no READY claim)  
**Order execution:** **none**  
**densify / tip collect as primary:** **none**  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Push:** **not** this report  
**Significance / edge claim:** **none** (explicitly denied)  
**Operational GO:** **none**

**Primary this lane (G2):** define **3** research signals from registry-**approved** COMPLETE-21 features only · re-run multiday + next-day return eval on the **same** W57 universe (**30** codes) and period (**20** as_of days) · compare sign-wise mean/median R · attach optional research-only net PnL under one-way **10bp** cost · R2 under `job=w0815ay-g2-multisignal`

| field | value |
|-------|------:|
| **Wave / lane** | W58 / w0815ay_g2 · T4–T8 |
| **Report date** | 2026-08-15 ~`12:08Z` UTC |
| **Label** | **小サンプル / 研究用・未宣言** |
| **Mass / Phase7** | **NO-GO / OFF** |
| **READY** | **not** declared |
| **Order execution** | **none** |
| **densify / tip collect as primary** | **none** |
| **Invent COMPLETE / Dataset COMPLETE 22** | **forbidden** (held **21**) |
| **Push** | **not** this report |
| **Significance / edge claim** | **none** |
| **Signals** | `c21_topix_relative_sign@1.0.0` · `c21_volume_change_sign@1.0.0` · `c21_topix_rel_disclosure_filter@1.0.0` · status `candidate` · `candidate_only=False` |
| **Job id** | `w0815ay-g2-multisignal` |
| **Logs** | [`.glm-logs/w0815ay_g2_multisignal/`](../../.glm-logs/w0815ay_g2_multisignal/) |
| **Prior baseline** | W57 universe expand · job `w0815ax-g1-universe` · [`w0815ax_w57_research_signal_eval_report_20260815.md`](w0815ax_w57_research_signal_eval_report_20260815.md) |
| **Code HEAD at run** | `e86a4cc584891ad15b346294053c1e5705c9f286` (W57 post-lock base + G2 multi-signal path) |
| **Live verified** | 2026-08-15 ~`12:08Z` UTC · `executed_at_utc` batch `2026-08-15T12:07:53Z` |

---

## 0. Verdict (honest)

| gate | result |
|------|--------|
| **E2E overall** | **PASS** |
| T4 signal definitions (3 · approved legs only) | **PASS** |
| T5 same universe/period multi-signal compare | **PASS** (n_codes=**30** · n_days=**20** · signal_count=**600**/signal) |
| T6 research report | **written** (this file) |
| T7–T8 research cost (10bp one-way) | **attached** · **仮定に依存・研究用・運用GOではない** |
| Look-ahead ban | **held** (feature as_of = T close; return T+1 only) |
| Mass / READY / orders / densify | **OFF** / **not declared** / **none** / **false** |
| This report | **written** (小サンプル / 研究用・未宣言 · no READY claim) |

**Honesty:** pass means a **bounded tip-window** multi-as_of single-shot path re-used the W57 **30**-code tip probe list, read CF D1 hot tip once over `2026-07-01`…`2026-08-14` (incl. `fins_summary` + `markets_margin_interest` for S3 legs), computed five approved COMPLETE-21 tip features for each trading-day as_of **T close only**, derived **three** research signals, attached `R_{T→T+1}` when T+1 bar was PIT-available at evaluation_as_of = T+1 close, summarized mean/median returns by sign **per signal**, attached research-only net signed PnL under a fixed **10bp** one-way cost assumption, and wrote research artifacts to R2. Success does **not** mean Mass GO, Phase7 ON, READY publication, order routing, statistical significance, densify, full-market PIT master universe, edge/alpha claim, or operational GO. Cost-adjusted numbers are **仮定に依存・研究用・運用GOではない**.

Sources: [`summary.json`](../../.glm-logs/w0815ay_g2_multisignal/summary.json) · [`batch_summary.json`](../../.glm-logs/w0815ay_g2_multisignal/batch_summary.json) · [`t5_assert.json`](../../.glm-logs/w0815ay_g2_multisignal/t5_assert.json) · [`cost_assumption.json`](../../.glm-logs/w0815ay_g2_multisignal/cost_assumption.json)

---

## 1. Data range

| field | value |
|-------|------:|
| **period_start** | `2026-07-01` |
| **period_end** | `2026-08-14` |
| **tip extract window** | `2026-07-01` … `2026-08-14` (same as W57 G1) |
| **tip trading days available** | **28** (equities/topix plane) |
| **max_days / min_days** | **20** / **5** |
| **n_days (as_of)** | **20** (fixed W57 as_of list) |
| **as_of (signal) days** | `2026-07-13` · `14` · `15` · `16` · `17` · `21` · `22` · `23` · `24` · `27` · `28` · `29` · `30` · `31` · `2026-08-03` · `04` · `05` · `06` · `07` · `10` |
| **feature as_of clock** | each day `T15:30:00+09:00` |
| **evaluation_as_of** (nextday) | next trading day `T15:30:00+09:00` when present |
| **datasets** | `equities_bars_daily` · `markets_calendar` · `indices_bars_daily_topix` · `fins_summary` · `markets_margin_interest` |
| **plane** | D1 hot tip (`quant-ingest`) via wrangler remote · **not** local SQLite SoT |
| **history structured tip** | **not used** |

### Tip extract honesty

| dataset | raw tip count (window) | extracted rows |
|---------|-----------------------:|---------------:|
| `equities_bars_daily` | 124367 | **840** (30 codes × 28 days) |
| `markets_calendar` | 42 | **42** |
| `indices_bars_daily_topix` | 28 | **28** |
| `fins_summary` | 3021 | **35** (code-filtered tip sample) |
| `markets_margin_interest` | 21277 | **150** (code-filtered tip sample) |

* Tip bar / topix plane tops out at **2026-08-10** (no densify / no invent).  
* Last signal day `2026-08-10` has no T+1 in tip → honest null next-day returns (**30** code-rows = n_codes per signal).  
* First as_of day `2026-07-13` has prior bars in tip (window starts `2026-07-01`) → 1d features non-null for baseline.  
* `fins_summary` tip rows are sparse vs bars → S3 disclosure filter reduces non-null rate (honest).  
* Log: [`tip_window.json`](../../.glm-logs/w0815ay_g2_multisignal/tip_window.json)

---

## 2. PIT definition (look-ahead policy)

| field | value |
|-------|------:|
| **feature_as_of** | signal day **T** session close (`T15:30:00+09:00`) |
| **feature PIT** | `available_at <= feature_as_of` (T+1 bars **never** enter features) |
| **return** | `close(T+1) / close(T) − 1` |
| **evaluation_as_of** | next trading day **T+1** session close |
| **return PIT** | both T and T+1 bars require `available_at <= evaluation_as_of` |
| **tip edge** | missing T+1 → `next_day_return = null` (counted in null rate) |
| **label** | 小サンプル / 研究用・未宣言 |
| **significance_claimed** | **false** |
| **edge_claimed** | **false** |
| **ready_declared** | **false** |
| **mass_research** | **NO-GO** |

Code SoT: `NEXTDAY_LOOKAHEAD_POLICY` / `NEXTDAY_RESEARCH_LABEL` in `packages/product/research/single_shot_job.py`  
Log: [`lookahead_policy.json`](../../.glm-logs/w0815ay_g2_multisignal/lookahead_policy.json)

---

## 3. Universe

| field | value |
|-------|------:|
| **universe mode** | **fixed_list** (reuse W57 expanded tip probe list) |
| **n_codes** | **30** |
| **codes** | `13010` · `72030` · `67580` · `99840` · `83060` · `68610` · `65010` · `40630` · `80350` · `94320` · `45020` · `63670` · `60980` · `79740` · `69810` · `45680` · `80010` · `80020` · `80580` · `94330` · `29140` · `33820` · `46610` · `49010` · `51080` · `54010` · `57130` · `62730` · `63010` · `65030` |
| **baseline (prior wave)** | W57 · **30** codes · job `w0815ax-g1-universe` |
| **selection policy** | **same list as W57** — no re-sample; multi-signal fairness on identical code/day grid |
| **survivorship note** | tip probe list only — **not** full PIT master universe; liquidity / large-cap bias expected |
| **code source plane** | CF D1 tip sample (W57); **not** local SoT |
| **local SoT for codes** | **false** |

Log: [`universe.json`](../../.glm-logs/w0815ay_g2_multisignal/universe.json)

---

## 4. Metrics

### 4.1 Signal definitions (T4 pin)

All three signals: status **`candidate`** · `candidate_only=False` · **approved legs only** · not READY.

#### S1 — baseline `c21_topix_relative_sign@1.0.0`

| role | feature_id | registry status | version |
|------|------------|-----------------|---------|
| primary | `topix_relative_1d` | **approved** | 1.0.0 |
| filter | `is_trading_day` | **approved** | 1.0.0 |
| gate | `volume_change_1d` | **approved** | 1.0.0 (gate **off** this run) |

```text
value = sign(topix_relative_1d) if is_trading_day==1
        (volume_change_abs_min = None)
```

#### S2 — `c21_volume_change_sign@1.0.0`

| role | feature_id | registry status | version |
|------|------------|-----------------|---------|
| primary | `volume_change_1d` | **approved** | 1.0.0 |
| filter | `is_trading_day` | **approved** | 1.0.0 |
| abs threshold | `|volume_change_1d| >= 0.10` | — | research pin |

```text
value = sign(volume_change_1d)
  if is_trading_day==1 and |volume_change_1d| >= 0.10
  else None
```

#### S3 — `c21_topix_rel_disclosure_filter@1.0.0`

| role | feature_id | registry status | version |
|------|------------|-----------------|---------|
| primary | `topix_relative_1d` | **approved** | 1.0.0 |
| filter | `is_trading_day` | **approved** | 1.0.0 |
| secondary filter | `disclosure_flag_fins` | **approved** | 1.0.0 |

```text
value = sign(topix_relative_1d)
  if is_trading_day==1 and disclosure_flag_fins==1
  else None
```

**Documented alternative (not selected as primary S3 this wave):** `margin_interest_change_1d` non-null filter (approved · tip rows extracted for completeness; not used in S3 formula).

Log: [`signal_definitions.json`](../../.glm-logs/w0815ay_g2_multisignal/signal_definitions.json)  
Code: `packages/research_runtime/features/minimal_signal.py` · `execute_multiday_multisignal_compare` in `packages/product/research/single_shot_job.py`

### 4.2 Compare table (T5 · same universe/period)

**Label: 小サンプル / 研究用・未宣言 — not a trading claim.**

| signal_id | non_null | rate | +1 / −1 | mean R +1 | median R +1 | mean R −1 | median R −1 | gross signed mean (active) | n_active |
|-----------|---------:|-----:|--------:|----------:|------------:|----------:|------------:|---------------------------:|---------:|
| `c21_topix_relative_sign` | **600** | **1.000** | 312 / 288 | **+0.00823** | **+0.00900** | **−0.00202** | **−0.00098** | **+0.00528** | 600 |
| `c21_volume_change_sign` | **451** | **0.752** | 206 / 245 | +0.00165 | +0.00193 | +0.00298 | +0.00278 | **−0.00078** | 451 |
| `c21_topix_rel_disclosure_filter` | **177** | **0.295** | 89 / 88 | +0.00718 | +0.00805 | +0.00055 | +0.00034 | **+0.00345** | 177 |

Shared grid: **n_days=20** · **n_codes=30** · **signal_count=600** per signal · overall return null rate **0.05** (tip edge on last as_of day).

**Research read (not significance):**

* S1 baseline reproduces W57 sign-wise means on the same grid (cross-check: +1 **+0.00823** / −1 **−0.00202**).  
* S2 volume-sign with 10% abs threshold fires often (~75%) but **gross signed mean is negative** on this tip window (mean R of −1 bucket exceeds +1).  
* S3 disclosure filter is sparse (tip `fins_summary` · non_null **29.5%**); when it fires, gross signed mean remains positive but below S1 and with far fewer active rows.  
* **No** ranking is an operational recommendation. **No** t-test / p-value / bootstrap.

### 4.3 Per-signal aggregates (detail)

#### S1 `c21_topix_relative_sign`

| metric | value |
|--------|------:|
| signal_count | 600 |
| non_null / null | 600 / 0 |
| non_null_rate | 1.0 |
| sign +1 / 0 / −1 | 312 / 0 / 288 |

| sign | count | non_null ret | null ret | null rate | **mean R** | **median R** |
|------|------:|-------------:|---------:|----------:|-----------:|-------------:|
| **+1** | 312 | 299 | 13 | 0.0417 | **+0.00823** | **+0.00900** |
| **0** | 0 | 0 | 0 | — | — | — |
| **−1** | 288 | 271 | 17 | 0.0590 | **−0.00202** | **−0.00098** |
| **overall** | 600 | 570 | 30 | 0.05 | +0.00336 | +0.00305 |

#### S2 `c21_volume_change_sign` (`|Δvol|≥0.10`)

| metric | value |
|--------|------:|
| signal_count | 600 |
| non_null / null | 451 / 149 |
| non_null_rate | 0.7517 |
| sign +1 / 0 / −1 | 206 / 0 / 245 |

| sign | count | non_null ret | null ret | null rate | **mean R** | **median R** |
|------|------:|-------------:|---------:|----------:|-----------:|-------------:|
| **+1** | 206 | (from batch) | | | **+0.00165** | **+0.00193** |
| **−1** | 245 | | | | **+0.00298** | **+0.00278** |
| **null_signal** | 149 | | | | — | — |

#### S3 `c21_topix_rel_disclosure_filter`

| metric | value |
|--------|------:|
| signal_count | 600 |
| non_null / null | 177 / 423 |
| non_null_rate | 0.295 |
| sign +1 / 0 / −1 | 89 / 0 / 88 |

| sign | count | **mean R** | **median R** |
|------|------:|-----------:|-------------:|
| **+1** | 89 | **+0.00718** | **+0.00805** |
| **−1** | 88 | **+0.00055** | **+0.00034** |
| **null_signal** | 423 | — | — |

### 4.4 Research-only cost (T7–T8)

**Label: 仮定に依存・研究用・運用GOではない**

| assumption | value |
|------------|------:|
| **one-way cost** | **10 bp** = **0.001** |
| **round-trip cost** | **20 bp** = **0.002** (if both entry and exit charged) |
| **signed PnL (gross)** | `position × next_day_return` with `position = sign(signal) ∈ {+1,0,−1}` |
| **net one-way** | `gross − \|position\| × 0.001` |
| **net round-trip** | `gross − \|position\| × 0.002` |
| **not modeled** | capacity · borrow · impact · partial fills · fees schedule · overnight risk |
| **operational GO** | **false** |

| signal_id | n_active | n_with_pnl | gross mean (active) | **net one-way mean** | **net RT mean** | median gross | median net 1w |
|-----------|---------:|-----------:|--------------------:|---------------------:|----------------:|-------------:|--------------:|
| `c21_topix_relative_sign` | 600 | 570 | +0.00528 | **+0.00428** | **+0.00328** | +0.00449 | +0.00349 |
| `c21_volume_change_sign` | 451 | 425 | −0.00078 | **−0.00178** | **−0.00278** | −0.00076 | −0.00176 |
| `c21_topix_rel_disclosure_filter` | 177 | 147 | +0.00345 | **+0.00245** | **+0.00145** | +0.00322 | +0.00222 |

**Cost note (copy-forward):** Research-only net next-day return assumes a fixed one-way cost of **10bp** per signed position. Round-trip equivalent is **20bp** if both sides are charged. Cost is subtracted as `|position| × cost` and does **not** model capacity, borrow, impact, or partial fills. **仮定に依存・研究用・運用GOではない** — not operational GO, not READY, not Mass, no significance / edge claim.

Log: [`cost_assumption.json`](../../.glm-logs/w0815ay_g2_multisignal/cost_assumption.json)

### 4.5 Artifacts (R2)

Bucket: **`quant-structured`**  
Prefix: `research/single_shot/job=w0815ay-g2-multisignal/`

| key | exists | notes |
|-----|:------:|-------|
| `…/batch_summary.json` | **yes** (put_ok) | multi-signal compare + cost |
| `…/manifest.json` | **yes** (put_ok) | freeze surface |
| `…/days/date=*/signals.json` | **yes** ×20 | per-day three-signal body |

Local mirror: [`.glm-logs/w0815ay_g2_multisignal/batch_summary.json`](../../.glm-logs/w0815ay_g2_multisignal/batch_summary.json)  
R2 puts: **22** × `put_ok` (batch + 20 days + manifest)

---

## 5. Limitations

1. **Sample size** — tip-window only; n_days=20 · n_codes=30 remain **小サンプル**.  
2. **Universe is a probe list** — not full-market PIT master; liquid/large-cap bias (W57 selection).  
3. **No statistical inference** — no t-tests, p-values, bootstrap CIs, or multiple-testing correction.  
4. **Tip edge effects** — last as_of day lacks T+1 → null returns (30 rows).  
5. **Plane** — D1 hot tip only; history R2 not re-materialized.  
6. **Signal status** remains `candidate` — legs approved without promoting signals.  
7. **Costs** — fixed 10bp one-way only; **仮定に依存**; capacity / borrow / impact **not** modeled.  
8. **Survivorship** — fixed tip code list does not re-build daily PIT membership.  
9. **No out-of-sample split** — single tip window.  
10. **S3 sparsity** — `fins_summary` tip extract yields only **35** rows → disclosure filter non_null **29.5%**; not a full disclosure history panel.  
11. **S2 threshold** — `|Δvol|≥0.10` is a research pin, not optimized / not cross-validated.  
12. **Margin filter** documented as alternative only; not primary S3 this wave.  
13. **overall_mean_R** is universe close-to-close mean (shared grid), not signal-aligned alpha; use **gross/net signed mean** for signed-PnL compare.

---

## 6. Explicit non-claims

* **READY** — not declared / not published / not an operational GO  
* **Mass research** — not started / not connected / **NO-GO**  
* **Phase7** — not armed / **OFF**  
* **Orders** — not emitted / paper execution not called  
* **densify** — not run as primary for this eval  
* **local SQLite** — not Source of Truth  
* **Dataset COMPLETE 22** — not invented; residual COMPLETE **21** held  
* **Signal status** — remains `candidate` (even though legs are approved)  
* **Significance** — **no** statistical significance claimed  
* **Edge / alpha** — **no** trading edge claimed  
* **Operational GO** — **no** production / paper routing authorization  
* **Cost net** — research assumption only (**仮定に依存・研究用・運用GOではない**)  
* Outputs labeled **小サンプル / 研究用・未宣言**

---

## 7. Code / artifact map

| item | path |
|------|------|
| Multi-signal pure compute | `packages/research_runtime/features/minimal_signal.py` |
| Multi-signal + cost eval | `packages/product/research/single_shot_job.py` (`execute_multiday_multisignal_compare`) |
| Eval harness (baseline pipeline) | `packages/product/research/eval_harness.py` |
| Live runner | `.glm-logs/w0815ay_g2_multisignal/run_multisignal.py` |
| R2 batch summary | `research/single_shot/job=w0815ay-g2-multisignal/batch_summary.json` |
| Logs | `.glm-logs/w0815ay_g2_multisignal/` |
| This report | `docs/proof/w0815ay_w58_multi_signal_compare_report_20260815.md` |
| Prior W57 report | `docs/proof/w0815ax_w57_research_signal_eval_report_20260815.md` |
| Baseline signal spec | `docs/proof/c21_topix_relative_sign_spec_20260815.md` |

---

## 8. Return card

| field | value |
|-------|------:|
| **pass/fail** | **PASS** |
| **R2 path** | `research/single_shot/job=w0815ay-g2-multisignal/batch_summary.json` |
| **n_days** | **20** |
| **n_codes** | **30** |
| **signal ids** | `c21_topix_relative_sign` · `c21_volume_change_sign` · `c21_topix_rel_disclosure_filter` |
| **non_null rates** | S1 **1.00** · S2 **0.752** · S3 **0.295** |
| **gross signed mean (active)** | S1 **+0.00528** · S2 **−0.00078** · S3 **+0.00345** |
| **net one-way mean (10bp)** | S1 **+0.00428** · S2 **−0.00178** · S3 **+0.00245** |
| **net RT mean (20bp)** | S1 **+0.00328** · S2 **−0.00278** · S3 **+0.00145** |
| **return null rate (overall)** | **0.05** |
| **label** | **小サンプル / 研究用・未宣言** |
| **cost label** | **仮定に依存・研究用・運用GOではない** |
| **Mass / READY** | **OFF** / **not declared** |
| **significance / edge / operational GO** | **none** |

---

*End of W58 multi-signal compare research report. No READY · no Mass · no densify · no push · no operational GO.*
