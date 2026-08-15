# W57 / w0815ax_g1 — Research signal eval report (universe expansion)

**Template:** [`templates/research_signal_eval_report_template.md`](templates/research_signal_eval_report_template.md) v1.0.0  
**Wave:** W57 / w0815ax_g1 · universe expansion (T1 sample codes · T2 multiday + nextday re-eval)  
**Report date:** 2026-08-15 ~`11:51Z` UTC  
**Label:** **小サンプル / 研究用・未宣言**  
**Mass / Phase7:** **NO-GO / OFF** (held · not armed)  
**READY:** **not** declared (no READY claim)  
**Order execution:** **none**  
**densify / tip collect as primary:** **none**  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Push:** **not** this report  
**Significance / edge claim:** **none** (explicitly denied)  
**Operational GO:** **none**

**Primary this lane (G1):** expand research tip code universe from W56 probe **3 → 30** liquid/diverse TSE codes · re-run multiday + next-day return eval at **n_days=20** under the same PIT / look-ahead policy · R2 under `job=w0815ax-g1-universe` · re-assert Mass/READY/order non-connect  

**Signal:** `c21_topix_relative_sign@1.0.0` · status `candidate` · `candidate_only=False` · approved legs only  
**Job id:** `w0815ax-g1-universe`  
**Logs:** [`.glm-logs/w0815ax_g1_universe/`](../../.glm-logs/w0815ax_g1_universe/)  
**Prior baseline (W56 expand20 · 3 codes):** [`w0815aw_w56_expand20_nextday_eval_20260815.md`](w0815aw_w56_expand20_nextday_eval_20260815.md) · job `w0815aw-g1-expand20`  
**Code HEAD at run:** `8381d9106167d65118f57509d67ed488419ceddf` (W56 post-lock; G1 eval path only — no densify)  
**Live verified:** 2026-08-15 ~`11:51Z` UTC · `executed_at_utc` batch `2026-08-15T11:50:36Z`

---

## 0. Verdict

| gate | result |
|------|--------|
| **E2E overall** | **PASS** |
| T1 code universe sample (D1 tip · not local SoT) | **PASS** (**n_codes=30** · target band 20–50) |
| T2 multiday + nextday re-eval on expanded universe | **PASS** (n_days=**20** · signal_count=**600**) |
| Look-ahead ban | **held** (feature as_of = T close; return T+1 only) |
| Mass / READY / orders / densify | **OFF** / **not declared** / **none** / **false** |
| This report | **written** (小サンプル / 研究用・未宣言 · no READY claim) |

**Honesty:** pass means a **bounded tip-window** multi-as_of single-shot path selected **30** tip-present equity codes (prefer liquid/diverse TSE probes with multi-day bars), read CF D1 hot tip once over `2026-07-01`…`2026-08-14`, computed COMPLETE-21 tip features for each trading-day as_of **T close only**, derived the minimal approved-leg signal, attached `R_{T→T+1}` when T+1 bar was PIT-available at evaluation_as_of = T+1 close, summarized **mean and median** returns by sign, and wrote research artifacts to R2. Success does **not** mean Mass GO, Phase7 ON, READY publication, order routing, statistical significance, densify, full-market PIT master universe, edge/alpha claim, or operational GO.

Sources: [`summary.json`](../../.glm-logs/w0815ax_g1_universe/summary.json) · [`t1_code_universe.json`](../../.glm-logs/w0815ax_g1_universe/t1_code_universe.json) · [`batch_summary.json`](../../.glm-logs/w0815ax_g1_universe/batch_summary.json) · [`t5_assert.json`](../../.glm-logs/w0815ax_g1_universe/t5_assert.json)

---

## 1. Data range

| field | value |
|-------|------:|
| **period_start** | `2026-07-01` |
| **period_end** | `2026-08-14` |
| **tip extract window** | `2026-07-01` … `2026-08-14` (same expand20 tip window as W56) |
| **tip trading days available** | **28** (`2026-07-01`…`2026-08-10` equities/topix plane) |
| **max_days** | **20** |
| **n_days (as_of)** | **20** (last 20 of tip calendar) |
| **as_of (signal) days** | `2026-07-13` · `14` · `15` · `16` · `17` · `21` · `22` · `23` · `24` · `27` · `28` · `29` · `30` · `31` · `2026-08-03` · `04` · `05` · `06` · `07` · `10` |
| **feature as_of clock** | each day `T15:30:00+09:00` |
| **evaluation_as_of** | next trading day `T15:30:00+09:00` when present |
| **datasets** | `equities_bars_daily` · `markets_calendar` · `indices_bars_daily_topix` |
| **plane** | D1 hot tip (`quant-ingest`) via wrangler remote · **not** local SQLite SoT |
| **history structured tip** | **not used** (`history_structured_tip_used=false`) |

### Tip extract honesty

| dataset | raw tip count (window) | extracted rows |
|---------|-----------------------:|---------------:|
| `equities_bars_daily` | 124367 | **840** (30 codes × 28 days) |
| `markets_calendar` | 42 | **42** |
| `indices_bars_daily_topix` | 28 | **28** |

* Tip bar / topix plane tops out at **2026-08-10** (no densify / no invent).  
* Last signal day `2026-08-10` has no T+1 in tip → honest null next-day returns (**30** code-rows = n_codes).  
* First as_of day `2026-07-13` has prior bars in tip (window starts `2026-07-01`) → 1d features non-null (signal non_null_rate overall **1.0**).  
* Log: `tip_window.json`

---

## 2. PIT definition (look-ahead policy)

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
| **ready_declared** | **false** |
| **mass_research** | **NO-GO** |

Code SoT: `NEXTDAY_LOOKAHEAD_POLICY` / `NEXTDAY_RESEARCH_LABEL` in `packages/product/research/single_shot_job.py` · harness re-export `packages/product/research/eval_harness.py`  
Log: [`lookahead_policy.json`](../../.glm-logs/w0815ax_g1_universe/lookahead_policy.json)

---

## 3. Universe

| field | value |
|-------|------:|
| **universe mode** | **expanded_from_baseline** (W56 3-code probes → 30-code tip probe list) |
| **n_codes** | **30** (within 20–50 band · target ~30) |
| **baseline (W56)** | **3** codes: `13010` · `72030` · `67580` |
| **selection policy** | prefer liquid/diverse TSE probes with multi-day tip bars (≥15 bar days in window among preferred list); D1 remote sample + preferred COUNT verify; **not** full PIT master |
| **code source plane** | CF D1 `quant-ingest` hot tip (`equities_bars_daily`) · sample_rows_scanned **4800** · distinct codes in sample **849** |
| **local SoT for codes** | **false** |
| **survivorship note** | tip probe list only — **not** full as-of master universe; liquidity / large-cap bias expected |

### Selected codes (30)

`13010` · `72030` · `67580` · `99840` · `83060` · `68610` · `65010` · `40630` · `80350` · `94320` · `45020` · `63670` · `60980` · `79740` · `69810` · `45680` · `80010` · `80020` · `80580` · `94330` · `29140` · `33820` · `46610` · `49010` · `51080` · `54010` · `57130` · `62730` · `63010` · `65030`

All 30 selected preferred codes had **28** tip bars in window (full tip calendar coverage). `96130` (preferred candidate) had **0** bars and was excluded.

Log: [`t1_code_universe.json`](../../.glm-logs/w0815ax_g1_universe/t1_code_universe.json)

---

## 4. Metrics

### 4.1 Signal definition (pin)

| field | value |
|-------|------:|
| **signal_id** | `c21_topix_relative_sign` |
| **version** | `1.0.0` |
| **status** | `candidate` (not READY) |
| **candidate_only** | **false** |
| **approved_legs_only** | **true** |

| role | feature_id | registry status | version |
|------|------------|-----------------|---------|
| primary | `topix_relative_1d` | **approved** | 1.0.0 |
| filter | `is_trading_day` | **approved** | 1.0.0 |
| gate | `volume_change_1d` | **approved** | 1.0.0 |

Spec: [`c21_topix_relative_sign_spec_20260815.md`](c21_topix_relative_sign_spec_20260815.md)  
Log: [`signal_definition.json`](../../.glm-logs/w0815ax_g1_universe/signal_definition.json)

### 4.2 Signal aggregate

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

### 4.3 Next-day return by sign

**Label: 小サンプル / 研究用・未宣言 — not a trading claim.**

| sign | count | non_null ret | null ret | null rate | **mean R** | **median R** |
|------|------:|-------------:|---------:|----------:|-----------:|-------------:|
| **+1** | 312 | 299 | 13 | 0.042 | **+0.00823** | **+0.00900** |
| **0** | 0 | 0 | 0 | — | — | — |
| **−1** | 288 | 271 | 17 | 0.059 | **−0.00202** | **−0.00098** |
| **null_signal** | 0 | 0 | 0 | — | — | — |
| **overall** | 600 | 570 | 30 | 0.050 | **+0.00336** | **+0.00305** |
| **signed only** | 600 | 570 | 30 | 0.050 | +0.00336 | +0.00305 |

**Not a trading claim.** n_days=20 · n_codes=30 still **小サンプル** (tip-only · liquid probe bias · ~570 signed non-null returns). No statistical significance test; no edge / alpha claim. Research labeling only.

### 4.4 vs prior baseline (W56 expand20 · 3 codes)

| metric | prior `w0815aw-g1-expand20` | this `w0815ax-g1-universe` | note |
|--------|----------------------------:|---------------------------:|------|
| n_codes | **3** | **30** | universe expansion (×10) |
| n_days | **20** | **20** | same tip window / max_days |
| signal_count | 60 | **600** | 20 × codes |
| signal non_null_rate | 1.0 | **1.0** | held |
| mean R +1 | +0.01075 (n_ret=31) | **+0.00823** (n_ret=299) | **not** significance |
| mean R −1 | −0.00459 (n_ret=26) | **−0.00202** (n_ret=271) | **not** significance |
| median R +1 | +0.01114 | **+0.00900** | research metric only |
| median R −1 | −0.00296 | **−0.00098** | research metric only |
| overall mean / median R | +0.00375 / +0.00177 | **+0.00336 / +0.00305** | research metric only |
| return null rate (overall) | 0.05 | **0.05** | tip edge (last day × n_codes) |

Log: `batch_summary.json` · `summary.json`

### 4.5 Artifacts (R2)

Bucket: **`quant-structured`**  
Prefix: `research/single_shot/job=w0815ax-g1-universe/`

| key | put status | notes |
|-----|:----------:|-------|
| `research/single_shot/job=w0815ax-g1-universe/batch_summary.json` | **put_ok** | local log copy 147319 bytes |
| `research/single_shot/job=w0815ax-g1-universe/manifest.json` | **put_ok** | key in batch summary |
| `…/days/date=2026-07-13/signals.json` … `…/date=2026-08-10/signals.json` | **put_ok** × **20** | per-day signals |

R2 put statuses: `put_ok` × **22** (batch_summary + manifest + 20 day signals)  
Head-by-download helper call in G1 log hit a local API signature bug (`head_r2_object() missing … 'key'`) — **puts themselves reported put_ok**; re-head optional for close lane, not required to invent metrics here.  
Log: `r2_heads.json` · `e2e_run.log`

### 4.6 Freeze surface

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
| significance_claimed | **false** |
| edge_claimed | **false** |
| label | **小サンプル / 研究用・未宣言** |
| harness_version | `research-eval-harness/v1` |

Log: [`freeze_status.json`](../../.glm-logs/w0815ax_g1_universe/freeze_status.json) · [`t5_assert.json`](../../.glm-logs/w0815ax_g1_universe/t5_assert.json)

---

## 5. Limitations

1. **Sample size** — tip-window only; n_days=20 and n_codes=30 remain **小サンプル** (not multi-year · not full market).  
2. **Universe is a probe list** — preferred liquid/diverse TSE names with tip coverage; **not** full-market PIT master; liquidity / large-cap bias.  
3. **No statistical inference** — no t-tests, p-values, bootstrap CIs, or multiple-testing correction. Cross-wave mean/median shifts are **descriptive only**.  
4. **Tip edge effects** — last as_of day lacks T+1 → **30** null returns (exactly n_codes); overall null rate **0.05**.  
5. **Plane** — D1 hot tip only; history R2 structured tip **not** pulled.  
6. **Signal status** remains `candidate` — legs approved without promoting the signal or minting READY.  
7. **Costs / capacity / borrow / impact** not modeled.  
8. **Survivorship** — fixed tip code list for the batch; does **not** rebuild daily PIT membership from equity master (master is permanent DEFER residual).  
9. **No out-of-sample split** in this report.  
10. **R2 head confirm** — G1 head helper call failed locally after put_ok; optional re-verify for close lane.

---

## 6. Explicit non-claims

* **READY** — not declared / not published / **not** an operational GO  
* **Mass research** — not started / not connected / **NO-GO**  
* **Phase7** — not armed / **OFF**  
* **Orders** — not emitted / paper execution not called  
* **densify** — not run as primary for this eval  
* **local SQLite** — not Source of Truth  
* **Dataset COMPLETE 22** — not invented; residual COMPLETE **21** held  
* **Signal status** — remains `candidate` (even with approved legs)  
* **Significance** — **no** statistical significance claimed  
* **Edge / alpha** — **no** trading edge claimed  
* **Operational GO** — **no** production / paper routing authorization  
* Outputs labeled **小サンプル / 研究用・未宣言**

---

## 7. Code / artifact map

| item | path |
|------|------|
| Multiday / nextday API | `packages/product/research/single_shot_job.py` → `execute_multiday_nextday_return_eval` |
| Eval harness entry | `packages/product/research/eval_harness.py` |
| Signal pure compute | `packages/research_runtime/features/minimal_signal.py` |
| Signal spec | `docs/proof/c21_topix_relative_sign_spec_20260815.md` |
| Report template | `docs/proof/templates/research_signal_eval_report_template.md` |
| Unit tests | `tests/test_single_shot_research_job.py` · `tests/test_eval_harness.py` |
| R2 batch summary | `research/single_shot/job=w0815ax-g1-universe/batch_summary.json` |
| Logs | `.glm-logs/w0815ax_g1_universe/` |
| Prior W56 expand20 | `docs/proof/w0815aw_w56_expand20_nextday_eval_20260815.md` |
| This report | `docs/proof/w0815ax_w57_research_signal_eval_report_20260815.md` |

---

## 8. Return card

| field | value |
|-------|------:|
| **pass/fail** | **PASS** |
| **R2 path** | `research/single_shot/job=w0815ax-g1-universe/batch_summary.json` |
| **n_days** | **20** |
| **n_codes** | **30** (baseline W56: **3**) |
| **signal non_null_rate** | **1.0** (600/600) |
| **sign mean R** | +1: **+0.00823** (n_ret=299) · 0: — · −1: **−0.00202** (n_ret=271) |
| **sign median R** | +1: **+0.00900** · 0: — · −1: **−0.00098** |
| **overall mean / median R** | **+0.00336** / **+0.00305** |
| **return null rate (overall)** | **0.05** (30/600) |
| **label** | **小サンプル / 研究用・未宣言** |
| **Mass / READY** | **OFF** / **not declared** |
| **significance / edge / operational GO** | **none** |
