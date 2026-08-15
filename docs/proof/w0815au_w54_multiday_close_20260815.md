# W54 / w0815au — COMPLETE 21 複数日シグナル評価 close (READY 未宣言) (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF / not declared**  
**empty COMPLETE:** **0** (ban held)  
**tip densify / tip collect:** **SKIP** (複数日シグナル評価; tip not primary)  
**densify:** **none** this wave  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Promotion:** **+1** this wave → **6** approved total (v**1.0.0**) · **4** remain candidate · **no force** beyond selective O2 pass  
**Multiday signal eval:** `c21_topix_relative_sign@1.0.0` · status **candidate** · **candidate_only=False** (legs approved) · Mass **OFF** · no orders · n_days=**6** · non_null **15/18**  
**Primary this wave:** multi-day tip **signal** batch (single_shot only) + selective O2 (`repo_rate_level` → approved) · residual 複数日シグナル評価 · G5 FINAL merge + **push**  
**Not:** READY declaration · Mass ON · Phase7 ON · densify · invent COMPLETE 22 · force remaining 4 · promote `return_1d_c21` · treat multiday signal as READY

**Live verified:** 2026-08-15 (JST) / G1 multiday ~`11:03Z` · G2 selective O2 ~`11:02Z` · G3 quality+residual ~`11:04–11:08Z` · G5 merge+push this close  
**Wave start HEAD (PRE_sha):** `918c5b23eea60e19f1512cd094399ddfbb86cbb7` (W53 post-lock)  
**Proof HEAD (post-push):** *(filled after G5 push)*  
**Projection (G3 T10 reclock; residual sync):** **FRESH** `projgen-3d29a3d673cc4214bd0913639fb52ad5` (pre-gen `projgen-d2cc11b67ad84724afaffbe4c000b59c`)

**Artifacts:**

| track | path |
|-------|------|
| G1 multiday signal eval | [`w0815au_w54_multiday_signal_eval_20260815.md`](w0815au_w54_multiday_signal_eval_20260815.md) · [`.glm-logs/w0815au_g1_multiday/`](../../.glm-logs/w0815au_g1_multiday/) · [`summary.json`](../../.glm-logs/w0815au_g1_multiday/summary.json) · [`batch_summary.json`](../../.glm-logs/w0815au_g1_multiday/batch_summary.json) · job `w0815au-g1-multiday` · **e2e_pass=true** |
| G2 selective O2 + promote | [`w0815au_w54_o2_promotion_20260815.md`](w0815au_w54_o2_promotion_20260815.md) · [`.glm-logs/w0815au_g2_o2/`](../../.glm-logs/w0815au_g2_o2/) · [`O2_RESULTS_MATRIX.json`](../../.glm-logs/w0815au_g2_o2/O2_RESULTS_MATRIX.json) · `complete21_min.py` · **+1** `repo_rate_level` |
| G3 quality + residual | [`.glm-logs/w0815au_g3_ops/`](../../.glm-logs/w0815au_g3_ops/) · T9 pytest **92** · T10 FRESH `projgen-3d29a3d…` · T11 residual § 複数日シグナル評価 · no push G3 |
| Residual SoT | [`docs/phase62_residual_status.md`](../phase62_residual_status.md) · § 複数日シグナル評価 |
| Catalog | [`complete21_min_feature_catalog_20260815.md`](complete21_min_feature_catalog_20260815.md) |
| Signal spec | [`c21_topix_relative_sign_spec_20260815.md`](c21_topix_relative_sign_spec_20260815.md) |
| Criteria | [`complete21_feature_candidate_to_approved_criteria_20260815.md`](complete21_feature_candidate_to_approved_criteria_20260815.md) |
| Prior W53 close | [`w0815at_w53_o2_signal_close_20260815.md`](w0815at_w53_o2_signal_close_20260815.md) |

---

## 1. Parallel agent split (W54 / w0815au)

| lane | tasks | owner / logs | outcome |
|------|-------|--------------|---------|
| **G1** | T1–T5 multi-day as_of signal batch via single_shot only (Mass OFF) | `.glm-logs/w0815au_g1_multiday/` · proof multiday_signal_eval | **E2E PASS** · n_days=**6** · non_null **15/18** · R2 batch_summary + 6 day signals · Mass **OFF** |
| **G2** | T6–T8 selective O2 (`repo_rate_level`) + careful promote (+1); no `return_1d_c21` | `.glm-logs/w0815au_g2_o2/` · proof o2_promotion | **O2 PASS** · **+1 approved** → total **6** · remain **4 candidate** · no force |
| **G3** | T9 pytest · T10 FRESH reclock · T11 residual 複数日シグナル評価 · tip densify SKIP · **no push** | `.glm-logs/w0815au_g3_ops/` | pytest **92** · **FRESH** `projgen-3d29a3d…` · residual section **added** · empty **0** · dc **21** · segs **3478** · OTC **93** |
| **G5 merge (this)** | unit tests · commit code+docs · multiday close proof · residual FRESH sync · **push** · SHA lock · remote re-verify | this proof | HEAD==origin · empty **0** · dc **21** · Phase7 **OFF** · READY **not** declared · promotion **6** · multiday **e2e_pass** · signal **candidate** / **candidate_only=False** |

CF-SoT held: **D1 = hot tip · R2 = history · COMPLETE = receipt-owned**.

**Not done:** densify · tip collect as primary · Phase7/Mass/READY · invent COMPLETE 22 · floor lower · force remaining 4 · promote `return_1d_c21` · signal→approved / READY claim.

---

## 2. Metrics held (remote D1 `quant-ingest`)

Source: [`.glm-logs/w0815au_g3_ops/FINAL_metrics.json`](../../.glm-logs/w0815au_g3_ops/FINAL_metrics.json) · G5 re-verify after push.

| Metric | value | role |
|--------|------:|------|
| Segment COMPLETE total | **3478** | held (Δ0 this wave) |
| Dataset COMPLETE | **21 / 26** | **PRIMARY** baseline (not invent 22) |
| PARTIAL | **5** permanent DEFER only | non-actionable |
| **actionable_gap** | **0** | W44 lock held |
| empty COMPLETE | **0** | ban held |
| JSDA OTC COMPLETE | **93** | tip island held · never dataset COMPLETE |
| raw_retention_manifests | **15915** | remote held (W46 tip secondary baseline **15869** held; not coverage primary) |
| FRESH generation | **`projgen-3d29a3d673cc4214bd0913639fb52ad5`** | G3 T10 reclock; residual sync this close |
| tip densify | **SKIP** | 複数日シグナル評価 only |
| Mass / READY / Phase7 | **NO-GO / not declared / OFF** | held |
| complete21 promotion | **6 approved** / **4 candidate** | W52 **2** + W53 O2 **+3** + W54 selective O2 **+1** · v**1.0.0** |
| multiday signal eval | `c21_topix_relative_sign@1.0.0` | status **candidate** · **candidate_only=False** · Mass **OFF** · n_days=**6** · non_null **15/18** |

### Residual phase section name

**`複数日シグナル評価（READY 未宣言）`** in `docs/phase62_residual_status.md`  
(W53 § O2強化・再評価 + W52 § approved/シグナル下地 + W51 § 特徴量込み E2E + W50 § 利用準備 E2E + W49 deepen + W48 groundwork held underneath; coverage baseline **W47 FINAL** held; this wave does **not** re-open densify).

### Dataset COMPLETE list (**21**) — held

`derivatives_bars_daily_futures` · `derivatives_bars_daily_options` · `derivatives_bars_daily_options_225` · `edinet_cross_shareholdings` · `edinet_large_volume_shareholders` · `edinet_major_shareholders` · `equities_bars_daily` · `equities_investor_types` · `fins_details` · `fins_dividend` · `fins_summary` · `indices_bars_daily` · `indices_bars_daily_topix` · `jsda_corporate_bond_transactions` · `jsda_tokyo_repo_rates` · `markets_breakdown` · `markets_calendar` · `markets_margin_alert` · `markets_margin_interest` · `markets_short_ratio` · `markets_short_sale_report`

**Still not Dataset COMPLETE (permanent DEFER residual):** `equities_master` · `equities_earnings_calendar` · `equities_bars_daily_am` · `jsda_otc_bond_reference_prices` (tip island **93** only) · `fins_earnings_date` (PARTIAL tip holes — W44 FINAL DEFER).

---

## 3. G1 — multiday signal eval (PASS)

Detailed proof: [`w0815au_w54_multiday_signal_eval_20260815.md`](w0815au_w54_multiday_signal_eval_20260815.md)  
Source: [`.glm-logs/w0815au_g1_multiday/summary.json`](../../.glm-logs/w0815au_g1_multiday/summary.json)

| field | value |
|-------|------:|
| **job_id** | `w0815au-g1-multiday` |
| **path** | `research.single_shot_job.execute_multiday_signal_eval` |
| **signal** | `c21_topix_relative_sign@1.0.0` |
| **status** | `candidate` |
| **candidate_only** | **false** (approved legs only) |
| **n_days** | **6** |
| **as_of days** | `2026-08-03` … `2026-08-10` (`T15:30:00+09:00`) |
| **codes** | `13010` · `72030` · `67580` |
| **signal_count** | **18** |
| **non_null** | **15** |
| **null** | **3** |
| **non_null_rate** | **0.833** |
| **sign +1 / −1 / 0** | **6 / 9 / 0** |
| **e2e_pass** | **true** |
| **Mass / orders / READY** | **OFF / none / not declared** |

### Per-day aggregate

| date | non_null | +1 | −1 | null |
|------|---------:|---:|---:|-----:|
| 2026-08-03 | 0 | 0 | 0 | 3 |
| 2026-08-04 | 3 | 0 | 3 | 0 |
| 2026-08-05 | 3 | 0 | 3 | 0 |
| 2026-08-06 | 3 | 3 | 0 | 0 |
| 2026-08-07 | 3 | 2 | 1 | 0 |
| 2026-08-10 | 3 | 1 | 2 | 0 |

**R2 (`quant-structured`):**  
`research/single_shot/job=w0815au-g1-multiday/batch_summary.json` · `manifest.json` · `days/date=…/signals.json` ×6 · put_ok ×8

**Honesty:** first as_of day nulls are tip-window 1d lag (no prior tip bar) — not densified.

---

## 4. G2 — selective O2 + promotion (+1 approved)

Detailed proof: [`w0815au_w54_o2_promotion_20260815.md`](w0815au_w54_o2_promotion_20260815.md)  
Machine matrix: [`.glm-logs/w0815au_g2_o2/O2_RESULTS_MATRIX.json`](../../.glm-logs/w0815au_g2_o2/O2_RESULTS_MATRIX.json)

| # | feature_id | job_id | tip | non_null | O2 | promote |
|--:|------------|--------|-----|---------:|----|---------|
| T6 | `repo_rate_level` | `w0815au-g2-o2-repo` | D1 `jsda_repo_rates` (54 rows) | **1** (sample 1.0) | **PASS** | **yes → approved@1.0.0** |

**Not promoted**

| feature_id | reason |
|------------|--------|
| `return_1d_c21` | T8 policy twin of approved v0 `return_1d` |
| `short_ratio_level` | not chosen (needs `section`; not default tip path) |
| `margin_alert_flag` | no O2 this wave |
| `futures_activity_proxy` | no O2 this wave |

### Approved after W54 (6 total)

| feature_id | wave | intended_role | version |
|------------|------|---------------|---------|
| `volume_change_1d` | W52 | signal | 1.0.0 |
| `is_trading_day` | W52 | utility | 1.0.0 |
| `topix_relative_1d` | W53 | signal | 1.0.0 |
| `disclosure_flag_fins` | W53 | signal | 1.0.0 |
| `margin_interest_change_1d` | W53 | signal | 1.0.0 |
| `repo_rate_level` | **W54** | state | **1.0.0** |

**Remain candidate (4 — no force):** `short_ratio_level` · `return_1d_c21` · `margin_alert_flag` · `futures_activity_proxy`

### Code / tip path side effects

* `single_shot_job`: JSDA tip extract from D1 `jsda_repo_rates` (not only `jquants_records`)
* `execute_multiday_signal_eval`: multi as_of batch + R2 `batch_summary.json`
* Signal **status** remains **`candidate`** (not READY / not strategy-default)

---

## 5. G3 — quality + residual (no push)

| gate | result |
|------|--------|
| T9 unit tests | **92 passed** (complete21 min · permanent_defer · single_shot multiday · mass gate) |
| T10 FRESH reclock | **FRESH** `projgen-3d29a3d673cc4214bd0913639fb52ad5` (ops_reeval_freshness; coverage_segments untouched; publish apply **SKIP**) |
| T11 residual | § **複数日シグナル評価（READY 未宣言）** added · PRE_sha `918c5b2…` |
| tip densify | **SKIP** |
| empty / dc / segs / OTC | **0 / 21 / 3478 / 93** |
| push | **not G3** (G5 this close) |

---

## 6. G5 merge — unit tests + commit + push

### Unit tests (merge)

```text
.venv/bin/python -m pytest \
  tests/test_complete21_min_features.py \
  tests/test_single_shot_research_job.py \
  tests/test_mass_research_gate.py \
  tests/test_permanent_defer_history_guard.py -q
# 92 passed
```

| suite | count |
|-------|------:|
| complete21 min features | 52 |
| single_shot research job | 28 |
| mass research gate | 6 |
| permanent defer history guard | 6 |
| **total** | **92** |

### Freeze surface (reconfirm)

| constant | value |
|----------|------:|
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| ready_publication | **OFF** |
| ready_declared | **false** |
| COMPLETE 21 count | **21** |
| permanent DEFER count | **5** |
| empty COMPLETE | **0** |
| approved features | **6** (`volume_change_1d` · `is_trading_day` · `topix_relative_1d` · `disclosure_flag_fins` · `margin_interest_change_1d` · `repo_rate_level`) |
| remain candidate | **4** |
| signal status | **candidate** · **candidate_only=false** |
| densify | **none** |

### Commits / SHA lock

| field | value |
|-------|-------|
| PRE_sha | `918c5b23eea60e19f1512cd094399ddfbb86cbb7` |
| POST_PUSH_SHA (feat commit) | *(filled after G5 push)* |
| origin/main (tip after fill) | *(filled after lock)* |
| HEAD == origin/main | *(filled after lock)* |

---

## 7. Explicit non-declarations (held)

- **READY** — not declared (複数日シグナル評価 only; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF** (multiday single_shot Mass OFF)
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)
- **Signal approved / strategy-default** — none (`c21_topix_relative_sign` remains status=candidate)
- **Dataset COMPLETE 22** — forbidden
- **densify / tip densify as primary** — none / SKIP
- **Force promote remaining 4** — not done (only selective O2-clear `repo_rate_level`)
- **Promote `return_1d_c21`** — policy no

---

## 8. Related code entry

```python
from research.single_shot_job import (
    execute_multiday_signal_eval,
    assert_mass_and_phase7_off,
)
from features.minimal_signal import SIGNAL_ID, CANDIDATE_ONLY  # c21_topix_relative_sign

assert_mass_and_phase7_off()
assert CANDIDATE_ONLY is False  # legs approved (W53+); status still candidate
ex = execute_multiday_signal_eval(
    job_id="w0815au-g1-multiday",
    codes=["13010", "72030", "67580"],
    as_of_days=[
        "2026-08-03", "2026-08-04", "2026-08-05",
        "2026-08-06", "2026-08-07", "2026-08-10",
    ],
    tip_period_start="2026-08-01",
    tip_period_end="2026-08-14",
    dry_run=False,
)
# ex.batch_summary_r2_key · aggregate non_null 15/18 · e2e_pass
# signal status remains candidate; Mass/READY/Phase7 still OFF
```
