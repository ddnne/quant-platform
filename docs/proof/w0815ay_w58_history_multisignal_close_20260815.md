# W58 / w0815ay — COMPLETE 21 履歴拡大・複数シグナル比較 close (READY 未宣言) (2026-08-15)

**Mass / READY / Phase7:** still **NO-GO / OFF / not declared**  
**empty COMPLETE:** **0** (ban held)  
**tip densify / tip collect:** **SKIP** (履歴拡大・複数シグナル比較; tip not primary)  
**densify:** **none** this wave  
**Invent COMPLETE / Dataset COMPLETE 22:** **forbidden** (held **21**)  
**Promotion:** **held 9 approved** · **1** remain candidate · **no** promote this wave · **no** `return_1d_c21`  
**History expand (G1):** **history_expand_possible = NO** (R2 history exists; tip-only eval path · no R2→FeatureContext bridge) · tip max **n_days=28** · **n_codes=30** · mean R +1 **+0.00643** / −1 **−0.00148** · job `w0815ay-g1-history60` · label **小サンプル / 研究用・未宣言**  
**Multi-signal + cost (G2):** 3 signals · same W57 grid **30×20** · gross signed mean S1 **+0.00528** / S2 **−0.00078** / S3 **+0.00345** · net one-way (10bp) S1 **+0.00428** / S2 **−0.00178** / S3 **+0.00245** · cost **仮定に依存・研究用・運用GOではない** · job `w0815ay-g2-multisignal`  
**Primary this wave:** investigate 40–60 day history expand · stay tip max if blocked · multi-signal compare on approved COMPLETE-21 legs · research-only 10bp cost · residual 履歴拡大・複数シグナル比較 · G4 FINAL merge + **push**  
**Not:** READY declaration · Mass ON · Phase7 ON · densify · invent COMPLETE 22 · force remaining 1 · promote `return_1d_c21` · significance / edge / Mass claims · operational GO

**Live verified:** 2026-08-15 (JST) / G1 history ~`12:12Z` · G2 multi-signal ~`12:08Z` · G3 quality ~`12:03–12:09Z` · G4 merge+push this close  
**Wave start HEAD (PRE_sha):** `e86a4cc584891ad15b346294053c1e5705c9f286` (W57 post-lock)  
**Proof HEAD (post-push):** `35f3425ec60a648b74b484a009f0007201af5dcd`  
**Projection (G3 T11 reclock; residual sync):** **FRESH** `projgen-20e613d7a30943378004831cdc26c9b2` (pre-gen `projgen-30219278e4064f258021f02eb00bbbc9`)

**Artifacts:**

| track | path |
|-------|------|
| G1 history window eval | [`w0815ay_w58_history_window_eval_20260815.md`](w0815ay_w58_history_window_eval_20260815.md) · [`.glm-logs/w0815ay_g1_history/`](../../.glm-logs/w0815ay_g1_history/) · [`RETURN_CARD.json`](../../.glm-logs/w0815ay_g1_history/RETURN_CARD.json) · job `w0815ay-g1-history60` · **history_expand_possible=no** · tip max **28** · **n_codes=30** |
| G2 multi-signal compare | [`w0815ay_w58_multi_signal_compare_report_20260815.md`](w0815ay_w58_multi_signal_compare_report_20260815.md) · [`.glm-logs/w0815ay_g2_multisignal/`](../../.glm-logs/w0815ay_g2_multisignal/) · [`batch_summary.json`](../../.glm-logs/w0815ay_g2_multisignal/batch_summary.json) · job `w0815ay-g2-multisignal` · **e2e_pass=true** · **n_codes=30** · **n_days=20** |
| G3 quality + residual | [`.glm-logs/w0815ay_g3_ops/`](../../.glm-logs/w0815ay_g3_ops/) · T9 pytest **114** · T11 FRESH `projgen-20e613d7…` · T12 residual § 履歴拡大・複数シグナル比較 · no push G3 |
| G4 final merge | [`.glm-logs/w0815ay_g4_final/`](../../.glm-logs/w0815ay_g4_final/) · this proof · residual FINAL · push |
| Residual SoT | [`docs/phase62_residual_status.md`](../phase62_residual_status.md) · § 履歴拡大・複数シグナル比較 |
| Catalog | [`complete21_min_feature_catalog_20260815.md`](complete21_min_feature_catalog_20260815.md) |
| Signal spec | [`c21_topix_relative_sign_spec_20260815.md`](c21_topix_relative_sign_spec_20260815.md) |
| Prior W57 close | [`w0815ax_w57_universe_close_20260815.md`](w0815ax_w57_universe_close_20260815.md) |

---

## 1. Parallel agent split (W58 / w0815ay)

| lane | tasks | owner / logs | outcome |
|------|-------|--------------|---------|
| **G1** | T1–T3 history expand investigation (R2 JSONL + archive) · 40–60 day eval if possible · else tip max · mean/median R | `.glm-logs/w0815ay_g1_history/` · proof history_window_eval | **history_expand_possible=NO** · tip max **n_days=28** · **n_codes=30** · mean R +1 **+0.00643** / −1 **−0.00148** · R2 `job=w0815ay-g1-history60` · Mass **OFF** · **小サンプル** |
| **G2** | T4–T8 define 3 research signals · same 30×20 grid · compare · 10bp research cost · multi-signal report | `.glm-logs/w0815ay_g2_multisignal/` · multi_signal_compare_report | **E2E PASS** · S1/S2/S3 compare · cost **仮定に依存** · Mass **OFF** · **小サンプル / 研究用・未宣言** |
| **G3** | T9 pytest · T10 freeze · T11 FRESH · T12 residual 履歴拡大・複数シグナル · tip densify SKIP · **no push** | `.glm-logs/w0815ay_g3_ops/` | pytest **114** · **FRESH** `projgen-20e613d7…` · residual section · empty **0** · dc **21** · segs **3478** · OTC **93** · promotion held **9/1** |
| **G4 merge (this)** | unit tests · commit code+docs · history+multisignal close proof · residual FINAL · **push** · SHA lock · remote re-verify | this proof | HEAD==origin · empty **0** · dc **21** · Phase7 **OFF** · READY **not** declared · multi-signal **e2e_pass** · history expand **NO** |

CF-SoT held: **D1 = hot tip · R2 = history · COMPLETE = receipt-owned**.

**Not done:** densify · tip collect as primary · Phase7/Mass/READY · invent COMPLETE 22 · floor lower · force remaining 1 · promote `return_1d_c21` · signal→approved / READY claim · significance / edge claim · 40–60 day eval (blocked).

---

## 2. Metrics held (remote D1 `quant-ingest`)

Source: [`.glm-logs/w0815ay_g3_ops/FINAL_metrics.json`](../../.glm-logs/w0815ay_g3_ops/FINAL_metrics.json) · G4 re-verify [`.glm-logs/w0815ay_g4_final/`](../../.glm-logs/w0815ay_g4_final/).

| Metric | value | role |
|--------|------:|------|
| Segment COMPLETE total | **3478** | held (Δ0 this wave) |
| Dataset COMPLETE | **21 / 26** | **PRIMARY** baseline (not invent 22) |
| PARTIAL | **5** permanent DEFER only | non-actionable |
| **actionable_gap** | **0** | W44 lock held |
| empty COMPLETE | **0** | ban held (G4 re-verify) |
| JSDA OTC COMPLETE | **93** | tip island held · never dataset COMPLETE |
| raw_retention_manifests | **15915** | held (not coverage primary) |
| FRESH generation | **`projgen-20e613d7a30943378004831cdc26c9b2`** | G3 T11 reclock; residual sync this close |
| tip densify | **SKIP** | 履歴拡大・複数シグナル比較 only |
| Mass / READY / Phase7 | **NO-GO / not declared / OFF** | held |
| complete21 promotion | **9 approved** / **1 candidate** | held (no promote this wave) |
| history expand | **NO** (tip max 28) | R2 exists · bridge missing |
| multi-signal compare | 3 signals · 30×20 · **e2e_pass** | research-only · cost 10bp |

### Residual phase section name

**`履歴拡大・複数シグナル比較（READY 未宣言）`** in `docs/phase62_residual_status.md`  
(W57 § ユニバース拡大・研究レポート + W56 § 研究ハーネス・評価窓拡大 + W55 § 評価深化・翌日リターン突合 + W54 § 複数日シグナル評価 + W53 § O2強化・再評価 + W52 § approved/シグナル下地 + W51 § 特徴量込み E2E + W50 § 利用準備 E2E + W49 deepen + W48 groundwork held underneath; coverage baseline **W47 FINAL** held; this wave does **not** re-open densify).

### Dataset COMPLETE list (**21**) — held

`derivatives_bars_daily_futures` · `derivatives_bars_daily_options` · `derivatives_bars_daily_options_225` · `edinet_cross_shareholdings` · `edinet_large_volume_shareholders` · `edinet_major_shareholders` · `equities_bars_daily` · `equities_investor_types` · `fins_details` · `fins_dividend` · `fins_summary` · `indices_bars_daily` · `indices_bars_daily_topix` · `jsda_corporate_bond_transactions` · `jsda_tokyo_repo_rates` · `markets_breakdown` · `markets_calendar` · `markets_margin_alert` · `markets_margin_interest` · `markets_short_ratio` · `markets_short_sale_report`

**Still not Dataset COMPLETE (permanent DEFER residual):** `equities_master` · `equities_earnings_calendar` · `equities_bars_daily_am` · `jsda_otc_bond_reference_prices` (tip island **93** only) · `fins_earnings_date` (PARTIAL tip holes — W44 FINAL DEFER).

---

## 3. G1 — history expand investigation + tip-max eval

Detailed proof: [`w0815ay_w58_history_window_eval_20260815.md`](w0815ay_w58_history_window_eval_20260815.md)  
Source: [`.glm-logs/w0815ay_g1_history/RETURN_CARD.json`](../../.glm-logs/w0815ay_g1_history/RETURN_CARD.json)

### 3.1 Expand conclusion

| field | value |
|-------|------:|
| **history_expand_possible** | **no** |
| **R2 history present** | **yes** (JSONL multi-year + cold `archive/jquants_records`) |
| **Why blocked** | multiday eval path is **D1 tip extract only** · no Python R2→`FeatureContext` history bridge · Artifacts JOIN plane residual (discovery-only) |
| **Hot D1 cutoff** | **`2026-07-01`** → tip trading days **28** for bars/topix |
| **40–60 day eval** | **not run** (would invent pre-tip rows without bridge) |
| **Executed** | tip max **n_days=28** · **n_codes=30** (W57 universe) |

### 3.2 Tip-max nextday metrics (`c21_topix_relative_sign@1.0.0`)

| field | value |
|-------|------:|
| **job_id** | `w0815ay-g1-history60` |
| **n_days** | **28** (tip max; target 40–60 **not** met) |
| **n_codes** | **30** |
| **signal_count** | **840** (28 × 30) |
| **non_null / null** | **810 / 30** (first tip day null 1d features) |
| **non_null_rate** | **0.964** |
| **sign +1 / −1** | **424 / 386** |
| **mean R +1** | **+0.00643** (n_ret=411) |
| **mean R −1** | **−0.00148** (n_ret=369) |
| **median R +1 / −1** | **+0.00648 / −0.00093** |
| **overall mean / median R** | **+0.00295 / +0.00244** |
| **return null rate overall** | **0.036** |
| **pass/fail** | **PASS_TIP_MAX_ONLY** |
| **label** | **小サンプル / 研究用・未宣言** |
| **Mass / READY / significance** | **OFF / not declared / none** |

**R2 (`quant-structured`):**  
`research/single_shot/job=w0815ay-g1-history60/batch_summary.json` · `manifest.json` · `days/date=…/signals.json` ×28 · put_ok ×30

**Honesty:** R2 history **exists** but is **not wired** into this eval path. Success = honest blocker + tip-max research metrics. **Not** alpha / READY / trading / significance claim. **Not** 40–60 day achievement.

---

## 4. G2 — multi-signal compare + research cost

Detailed report: [`w0815ay_w58_multi_signal_compare_report_20260815.md`](w0815ay_w58_multi_signal_compare_report_20260815.md)  
Source: [`.glm-logs/w0815ay_g2_multisignal/RETURN_CARD.json`](../../.glm-logs/w0815ay_g2_multisignal/RETURN_CARD.json)

### 4.1 Signals (all legs approved · status candidate)

| id | formula (research) | non_null rate |
|----|--------------------|-------------:|
| **S1** `c21_topix_relative_sign@1.0.0` | `sign(topix_relative_1d)` if trading day | **1.000** (600/600) |
| **S2** `c21_volume_change_sign@1.0.0` | `sign(volume_change_1d)` if \|Δvol\|≥0.10 | **0.752** (451/600) |
| **S3** `c21_topix_rel_disclosure_filter@1.0.0` | S1 kept when `disclosure_flag_fins==1` | **0.295** (177/600) |

Shared grid: **n_codes=30** · **n_days=20** · as_of `2026-07-13…2026-08-10` · period `2026-07-01…2026-08-14` · W57 universe reuse · **candidate_only=False**.

### 4.2 Compare table (gross + cost)

| signal | +1 / −1 | mean R +1 | mean R −1 | gross signed mean | **net one-way (10bp)** | net RT (20bp) |
|--------|--------:|----------:|----------:|------------------:|----------------------:|--------------:|
| S1 topix_rel | 312 / 288 | **+0.00823** | **−0.00202** | **+0.00528** | **+0.00428** | **+0.00328** |
| S2 volume_sign | 206 / 245 | +0.00165 | +0.00298 | **−0.00078** | **−0.00178** | **−0.00278** |
| S3 topix+disc | 89 / 88 | +0.00718 | +0.00055 | **+0.00345** | **+0.00245** | **+0.00145** |

Overall market mean/median R (shared grid): **+0.00336 / +0.00305** · return null rate **0.05**.

### 4.3 Cost note (copy-forward)

Research-only net next-day return assumes a fixed **one-way cost of 10bp** per signed position. Round-trip equivalent is **20bp** if both sides are charged. Cost is subtracted as `|position| × cost` and does **not** model capacity, borrow, impact, or partial fills. **仮定に依存・研究用・運用GOではない** — not operational GO, not READY, not Mass, no significance / edge claim.

**R2 (`quant-structured`):**  
`research/single_shot/job=w0815ay-g2-multisignal/batch_summary.json` · `manifest.json` · `days/date=…/signals.json` ×20 · put_ok ×22

**Code:** `packages/research_runtime/features/minimal_signal.py` (multi-signal pure helpers) · `packages/product/research/single_shot_job.py` (`execute_multiday_multisignal_compare` · research cost attach)

---

## 5. G3 quality + residual (no push) · G4 merge gates

| gate | result |
|------|--------|
| G3 T9 unit tests | **114 passed** (complete21 min · permanent_defer · single_shot · mass gate · eval_harness) |
| G4 merge unit tests | **114 passed** (same suites re-run) |
| G3 T11 FRESH reclock | **FRESH** `projgen-20e613d7a30943378004831cdc26c9b2` (ops_reeval_freshness; coverage_segments untouched; publish apply **SKIP**) |
| Mass/Phase7/READY | **NO-GO / OFF / not declared** |
| residual | § **履歴拡大・複数シグナル比較（READY 未宣言）** · PRE_sha `e86a4cc…` · G4 FINAL push |
| tip densify | **SKIP** |
| empty / dc / segs / OTC | **0 / 21 / 3478 / 93** (G3 + G4 re-verify) |
| push | **G4 this close** (not G3) |
| promotion | **held 9 approved / 1 candidate** · **no** promote · **no** `return_1d_c21` |

### Unit tests (merge)

```text
.venv/bin/python -m pytest \
  tests/test_complete21_min_features.py \
  tests/test_single_shot_research_job.py \
  tests/test_eval_harness.py \
  tests/test_mass_research_gate.py \
  tests/test_permanent_defer_history_guard.py -q
# 114 passed
```

| suite | count |
|-------|------:|
| complete21 min features | 52 |
| single_shot research job | 36 |
| eval harness | 14 |
| mass research gate | 6 |
| permanent defer history guard | 6 |
| **total** | **114** |

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
| approved features | **9** (`volume_change_1d` · `is_trading_day` · `topix_relative_1d` · `disclosure_flag_fins` · `margin_interest_change_1d` · `repo_rate_level` · `short_ratio_level` · `futures_activity_proxy` · `margin_alert_flag`) |
| remain candidate | **1** (`return_1d_c21`) |
| signal status | **candidate** · **candidate_only=false** |
| densify | **none** |
| nextday label | **小サンプル / 研究用・未宣言** |
| cost label | **仮定に依存・研究用・運用GOではない** |

### Commits / SHA lock

| field | value |
|-------|-------|
| PRE_sha | `e86a4cc584891ad15b346294053c1e5705c9f286` |
| POST_PUSH_SHA (feat commit) | `35f3425ec60a648b74b484a009f0007201af5dcd` |
| fill_sha | `a6a3cb2be00ff7d779b3b52bf55116ff15674165` |
| lock_sha / origin/main tip |  |
| HEAD == origin/main | **true** (both ) |

---

## 6. Explicit non-declarations (held)

- **READY** — not declared (履歴拡大・複数シグナル比較 only; research metrics; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF**
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)
- **Signal approved / strategy-default** — none (all three signals remain status=candidate)
- **Dataset COMPLETE 22** — forbidden
- **densify / tip densify as primary** — none / SKIP
- **Force promote remaining 1** — not done
- **Promote `return_1d_c21`** — policy no
- **40–60 day history eval** — **not achieved** (tip max 28; bridge missing)
- **Universe / multi-signal mean returns as alpha** — **no** (小サンプル · research label only · tip only)
- **Statistical significance / edge** — **false**
- **Cost-adjusted PnL as operational GO** — **false** (**仮定に依存・研究用・運用GOではない**)

---

## 7. Related code entry

```python
from research.single_shot_job import (
    execute_multiday_nextday_return_eval,
    execute_multiday_multisignal_compare,
)
from features.minimal_signal import (
    SIGNAL_ID,  # c21_topix_relative_sign
    SIGNAL_ID_VOLUME_SIGN,
    SIGNAL_ID_TOPIX_DISC,
    CANDIDATE_ONLY,
)

assert CANDIDATE_ONLY is False  # legs approved; signal status still candidate

# G1 tip-max (history expand blocked)
ex1 = execute_multiday_nextday_return_eval(
    job_id="w0815ay-g1-history60",
    codes=[...],  # 30 tip codes
    period_start="2026-07-01",
    period_end="2026-08-14",
    max_days=28,
    dry_run=False,
)

# G2 multi-signal + 10bp research cost
ex2 = execute_multiday_multisignal_compare(
    job_id="w0815ay-g2-multisignal",
    codes=[...],
    period_start="2026-07-01",
    period_end="2026-08-14",
    max_days=20,
    one_way_cost=0.001,
    dry_run=False,
)
# label 小サンプル / 研究用・未宣言; cost 仮定に依存; Mass/READY/Phase7 still OFF
```

---

## 8. Return card (G4 FINAL)

| field | value |
|-------|------:|
| **history_expand_possible** | **no** |
| **n_days G1 tip max** | **28** (target 40–60 blocked) |
| **n_codes** | **30** |
| **G1 mean R +1 / −1** | **+0.00643 / −0.00148** |
| **G2 signals** | S1 topix_rel · S2 volume_sign · S3 topix+disc |
| **G2 gross signed mean** | S1 **+0.00528** · S2 **−0.00078** · S3 **+0.00345** |
| **G2 net one-way (10bp)** | S1 **+0.00428** · S2 **−0.00178** · S3 **+0.00245** |
| **cost label** | **仮定に依存・研究用・運用GOではない** |
| **label** | **小サンプル / 研究用・未宣言** |
| **Dataset COMPLETE** | **21** |
| **empty COMPLETE** | **0** |
| **COMPLETE segs** | **3478** |
| **OTC tip** | **93** |
| **FRESH** | `projgen-20e613d7a30943378004831cdc26c9b2` |
| **pytest** | **114 passed** |
| **promotion** | **9 approved / 1 candidate** (held) |
| **Mass / READY / Phase7** | **NO-GO / not declared / OFF** |
| **push** | **yes** (G4 this close) |

---

*End of W58 / w0815ay FINAL close. No densify · no Mass · no READY · no return_1d_c21 promote · no significance / edge / operational GO.*
