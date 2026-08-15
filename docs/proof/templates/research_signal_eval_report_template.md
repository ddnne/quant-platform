# Research signal eval report template

**Template id:** `research_signal_eval_report_template`  
**Version:** `1.0.0`  
**Purpose:** Reusable research-only writeup for single-shot / eval-harness signal batches (multiday ± next-day return).  
**Audience:** Research operators · wave proofs · residual close notes  

**Hard rules (every filled instance must obey):**

* **Label** outputs **小サンプル / 研究用・未宣言** when next-day returns are attached (or **研究用・未宣言** for signal-only batches).  
* **No READY** claim · **no Mass GO** · **no Phase7 ON** · **no operational GO** · **no significance / edge / alpha claim**.  
* **No densify** as primary · **no invent COMPLETE 22** · **no order execution**.  
* Local SQLite is **not** Source of Truth (CF D1 tip · R2 history · COMPLETE = receipt-owned).

Fill every `{{placeholder}}`. Delete optional blocks you do not use. Do not invent numbers.

---

## Header (fill)

| field | value |
|-------|------:|
| **Wave / lane** | `{{wave_id}}` / `{{lane_id}}` · `{{task_ids}}` |
| **Report date** | `{{report_date}}` (UTC or JST; state which) |
| **Label** | **小サンプル / 研究用・未宣言** (or 研究用・未宣言 if signal-only) |
| **Mass / Phase7** | **NO-GO / OFF** |
| **READY** | **not** declared |
| **Order execution** | **none** |
| **densify / tip collect as primary** | **none** |
| **Invent COMPLETE / Dataset COMPLETE 22** | **forbidden** (held **21**) |
| **Push** | **not** this report (unless a separate close lane) |
| **Significance / edge claim** | **none** (explicitly denied) |
| **Signal** | `{{signal_id}}@{{signal_version}}` · status `{{signal_status}}` · `candidate_only={{candidate_only}}` |
| **Job id** | `{{job_id}}` |
| **Logs** | `.glm-logs/{{log_dir}}/` |
| **Prior baseline** | `{{prior_proof_link_or_job}}` |
| **Code HEAD at run** | `{{git_sha}}` |
| **Live verified** | `{{live_verified_timestamp}}` |

**Primary this lane:** `{{one_line_primary}}`

---

## 0. Verdict (honest)

| gate | result |
|------|--------|
| **E2E overall** | `{{PASS\|FAIL\|PENDING}}` |
| Look-ahead ban | **held** (feature as_of = T close; return T+1 only when attached) |
| Mass / READY / orders | **OFF** / **not declared** / **none** |
| This report | **written** (研究用 · no READY claim) |

**Honesty:** `{{1-3 sentences: what pass means and what it explicitly does not mean}}`

---

## 1. Data range

| field | value |
|-------|------:|
| **period_start** | `{{period_start}}` |
| **period_end** | `{{period_end}}` |
| **tip extract window** | `{{tip_window_note}}` |
| **tip trading days available** | `{{tip_available_trading_days}}` |
| **max_days / min_days** | `{{max_days}}` / `{{min_days}}` |
| **n_days (as_of)** | `{{n_days}}` |
| **as_of (signal) days** | `{{as_of_days_list_or_range}}` |
| **feature as_of clock** | each day `T15:30:00+09:00` (or `{{clock}}`) |
| **evaluation_as_of** (if nextday) | next trading day `T15:30:00+09:00` when present |
| **datasets** | `{{dataset_ids}}` |
| **plane** | D1 hot tip (`quant-ingest`) via wrangler remote · **not** local SQLite SoT |
| **history structured tip** | `{{used\|not_required\|note}}` |

### Tip extract honesty

| dataset | raw tip count (window) | extracted rows |
|---------|-----------------------:|---------------:|
| `{{ds1}}` | `{{raw1}}` | `{{ext1}}` |
| `{{ds2}}` | `{{raw2}}` | `{{ext2}}` |
| `{{ds3}}` | `{{raw3}}` | `{{ext3}}` |

* Tip plane tops out at **`{{tip_last_date}}`** (no densify / no invent).  
* Edge cases (missing T+1, first-day null 1d features, etc.): `{{edge_notes}}`.

---

## 2. PIT definition (look-ahead policy)

| field | value |
|-------|------:|
| **feature_as_of** | signal day **T** session close (`T15:30:00+09:00`) |
| **feature PIT** | `available_at <= feature_as_of` (T+1 bars **never** enter features) |
| **return** (if attached) | `close(T+1) / close(T) − 1` |
| **evaluation_as_of** | next trading day **T+1** session close |
| **return PIT** | both T and T+1 bars require `available_at <= evaluation_as_of` |
| **tip edge** | missing T+1 → `next_day_return = null` (counted in null rate) |
| **label** | 小サンプル / 研究用・未宣言 |
| **significance_claimed** | **false** |
| **edge_claimed** | **false** |
| **ready_declared** | **false** |
| **mass_research** | **NO-GO** |

Code SoT: `NEXTDAY_LOOKAHEAD_POLICY` / `NEXTDAY_RESEARCH_LABEL` in `packages/product/research/single_shot_job.py` (and/or `eval_harness` re-exports).  
Log: `lookahead_policy.json` (when produced).

---

## 3. Universe

| field | value |
|-------|------:|
| **universe mode** | `{{fixed_list \| tip_discover \| expanded_from_baseline}}` |
| **n_codes** | `{{n_codes}}` |
| **codes** | `{{code_list}}` |
| **baseline (prior wave)** | `{{prior_codes_and_n}}` |
| **selection policy** | `{{how_codes_were_chosen}}` |
| **survivorship note** | tip probe list only — **not** full PIT master universe; not anti-survivorship complete |
| **code source plane** | `{{D1 tip sample / preferred liquid probes / …}}` |
| **local SoT for codes** | **false** |

Optional universe audit table:

| code | tip bar count (window) | days covered | notes |
|------|-----------------------:|-------------:|-------|
| `{{code}}` | `{{n}}` | `{{days}}` | `{{note}}` |

---

## 4. Metrics

### 4.1 Signal definition (pin)

| field | value |
|-------|------:|
| **signal_id** | `{{signal_id}}` |
| **version** | `{{signal_version}}` |
| **status** | `candidate` (not READY) |
| **candidate_only** | `{{true\|false}}` |
| **approved_legs_only** | **true** (when `candidate_only=false`) |

| role | feature_id | registry status | version |
|------|------------|-----------------|---------|
| primary | `{{feat_primary}}` | approved | `{{v}}` |
| filter | `{{feat_filter}}` | approved | `{{v}}` |
| gate | `{{feat_gate}}` | approved | `{{v}}` |

### 4.2 Signal aggregate

| metric | value |
|--------|------:|
| **n_days** | `{{n_days}}` |
| **signal_count** | `{{signal_count}}` |
| **non_null** | `{{non_null}}` |
| **null** | `{{null}}` |
| **non_null_rate** | `{{non_null_rate}}` |
| **sign +1** | `{{plus}}` |
| **sign 0** | `{{zero}}` |
| **sign −1** | `{{minus}}` |

### 4.3 Next-day return by sign (when attached)

**Label: 小サンプル / 研究用・未宣言 — not a trading claim.**

| sign | count | non_null ret | null ret | null rate | **mean R** | **median R** |
|------|------:|-------------:|---------:|----------:|-----------:|-------------:|
| **+1** | | | | | | |
| **0** | | | | | | |
| **−1** | | | | | | |
| **null_signal** | | | | | | |
| **overall** | | | | | | |
| **signed only** | | | | | | |

Optional vs prior baseline:

| metric | prior (`{{prior_job}}`) | this run | note |
|--------|------------------------:|---------:|------|
| n_codes | | | universe expansion only if intended |
| n_days | | | |
| mean R +1 | | | **not** significance |
| mean R −1 | | | **not** significance |
| median R +1 | | | |
| median R −1 | | | |

Log: `batch_summary.json` · `summary.json`

### 4.4 Artifacts (R2)

Bucket: **`quant-structured`**  
Prefix: `research/single_shot/job={{job_id}}/`

| key | exists | bytes |
|-----|:------:|------:|
| `…/batch_summary.json` | | |
| `…/manifest.json` | | |
| `…/days/date=*/signals.json` | | |

---

## 5. Limitations

Document every material limit. Starter set (edit / extend):

1. **Sample size** — tip-window only; n_days and n_codes remain **小サンプル** even after expansion.  
2. **Universe is a probe list** — not full-market PIT master; selection may prefer liquid names → liquidity / large-cap bias.  
3. **No statistical inference** — no t-tests, p-values, bootstrap CIs, or multiple-testing correction in this report.  
4. **Tip edge effects** — last as_of day often lacks T+1 → null returns; first days may null 1d features without prior bars.  
5. **Plane** — D1 hot tip only; history R2 not re-materialized unless explicitly noted.  
6. **Signal status** remains `candidate` — legs may be approved without promoting the signal.  
7. **Costs / capacity / borrow / impact** not modeled.  
8. **Survivorship** — fixed tip code list does not re-build daily PIT membership.  
9. **No out-of-sample split** unless this report defines one.  
10. **Other:** `{{extra_limitations}}`

---

## 6. Explicit non-claims

Copy-forward as a checklist (do not soften):

* **READY** — not declared / not published / not an operational GO  
* **Mass research** — not started / not connected / **NO-GO**  
* **Phase7** — not armed / **OFF**  
* **Orders** — not emitted / paper execution not called  
* **densify** — not run as primary for this eval  
* **local SQLite** — not Source of Truth  
* **Dataset COMPLETE 22** — not invented; residual COMPLETE **21** held  
* **Signal status** — remains `candidate` (even if legs are approved)  
* **Significance** — **no** statistical significance claimed  
* **Edge / alpha** — **no** trading edge claimed  
* **Operational GO** — **no** production / paper routing authorization  
* Outputs labeled **小サンプル / 研究用・未宣言** (or 研究用・未宣言)

---

## 7. Code / artifact map

| item | path |
|------|------|
| Multiday / nextday API | `packages/product/research/single_shot_job.py` |
| Eval harness entry | `packages/product/research/eval_harness.py` |
| Signal pure compute | `packages/research_runtime/features/minimal_signal.py` |
| Signal spec (if any) | `docs/proof/{{signal_spec}}.md` |
| Unit tests | `tests/test_single_shot_research_job.py` · `tests/test_eval_harness.py` |
| R2 batch summary | `research/single_shot/job={{job_id}}/batch_summary.json` |
| Logs | `.glm-logs/{{log_dir}}/` |
| This report | `docs/proof/{{this_report_filename}}` |

---

## 8. Return card

| field | value |
|-------|------:|
| **pass/fail** | `{{PASS\|FAIL\|PENDING}}` |
| **R2 path** | `research/single_shot/job={{job_id}}/batch_summary.json` |
| **n_days** | `{{n_days}}` |
| **n_codes** | `{{n_codes}}` |
| **signal non_null_rate** | `{{rate}}` |
| **sign mean R** | +1: `{{…}}` · 0: `{{…}}` · −1: `{{…}}` |
| **sign median R** | +1: `{{…}}` · 0: `{{…}}` · −1: `{{…}}` |
| **return null rate (overall)** | `{{…}}` |
| **label** | **小サンプル / 研究用・未宣言** |
| **Mass / READY** | **OFF** / **not declared** |
| **significance / edge / operational GO** | **none** |

---

## Fill notes (for authors)

1. Prefer numbers from `.glm-logs/{{log_dir}}/summary.json` + `batch_summary.json` over narrative.  
2. If G1 (or peer lane) artifacts are not yet landed, leave fields as `PENDING` / `{{TBD}}` and re-fill when logs + R2 heads exist — do **not** invent metrics.  
3. Universe expansion reports must contrast prior n_codes vs this n_codes under the same PIT / look-ahead policy.  
4. Never upgrade label, never claim READY/Mass/significance from this template alone.
