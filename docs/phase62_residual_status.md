# Phase 6.2 / 6.3 residual status

**Live residual SoT** (agents: prefer this file over any `phase62*_status` / final_report).  
**Live verified:** 2026-08-15 (JST) / **W63** 複数年研究評価 S1+S4（READY 未宣言） · COMPLETE segs **3478** · Dataset COMPLETE **21** · PARTIAL **5** DEFER · **actionable_gap = 0** · empty COMPLETE **0** · **OTC 93** · Mass/READY/Phase7 **NO-GO/OFF** · FRESH `projgen-96d5a48f6fe243509562da2694b5f476` · **CF-SoT** held · promotion **9 approved** / **1 candidate** no-promote · multi-year S1 gate soft **PASS** (majority +) · multi-year S4 gate soft **PASS** (majority −) · years 2015/17/19/21/23/25 Q4 · topix JSONL gap 2024–25 archive · margin 2024 empty held · **gate pass ≠ READY/Mass** · **no significance / no edge / no operational GO**
**Repo tip:**  — W63 multi-year S1+S4 · COMPLETE **21** / segs **3478** / OTC **93** / READY **未宣言** · FRESH 

## 複数年研究評価 S1 + S4（READY 未宣言）

**Phase name:** equities_bars 複数年窓 S1 再評価 + S4 margin（宣言なし）  
**Wave:** W63 / w0815bd  
**Close:** [`docs/proof/w0815bd_w63_multi_year_close_20260815.md`](proof/w0815bd_w63_multi_year_close_20260815.md)  
**Eval:** [`docs/proof/w0815bd_w63_multi_year_eval_20260815.md`](proof/w0815bd_w63_multi_year_eval_20260815.md) · availability [`docs/proof/w0815bd_w63_year_availability_20260815.md`](proof/w0815bd_w63_year_availability_20260815.md)  
**APIs:** `design_yearly_eval_windows` · `run_multi_year_s1_eval` · `run_multi_year_extra_hyp_eval` · `multi_year_availability_table` (`eval_harness.py`) · year-split fail-one-year-safe  
**Windows:** y2015_q4 · y2017_q4 · y2019_q4 · y2021_q4 · y2023_q4 · y2025_q4 · **50d** · **30 codes** · `history_source=r2`  
**S1 gate:** soft **PASS** (6/6 eligible · majority sign **+** · not catastrophic) — **≠ READY/Mass**  
**S4 gate:** soft **PASS** (6/6 eligible · majority sign **−**) — years with margin only; 2024 gap not forced  
**Gaps (honest):** topix JSONL **2024–2025** → archive · calendar archive + PIT · margin **2024** empty by inventory · no densify invent  
**Logs:** [`.glm-logs/w0815bd_w63_multiyear/`](../.glm-logs/w0815bd_w63_multiyear/)  
**Prior W62 gate + S4/S5:** held underneath

| gate | status |
|------|--------|
| READY | **未宣言** (multi-year gate pass does not connect) |
| Mass / Phase7 | **NO-GO / OFF** |
| Dataset COMPLETE | **21** |
| COMPLETE segs | **3478** |
| empty COMPLETE | **0** |
| OTC | **93** |
| densify | **none** |
| Multi-year S1 | **6/6 ok** · gate soft PASS · not GO |
| Multi-year S4 | **6/6 ok** · gate soft PASS · not GO |
| Year-split | **fail-one-year-safe** |

### Explicit non-declarations (held)

- **READY** — not declared  
- **Mass** — **NO-GO / OFF**  
- **Phase7** — **OFF**

## 研究用頑健性ゲート + 別仮説 S4/S5（READY 未宣言）

**Phase name:** 研究用頑健性ゲート固定 + 別仮説最大2本（宣言なし）  
**Wave:** W62 / w0815bc  
**Close:** [`docs/proof/w0815bc_w62_gate_hyp_close_20260815.md`](proof/w0815bc_w62_gate_hyp_close_20260815.md)  
**Gate:** `packages/product/research/robustness_gate.py` · [`docs/proof/w0815bc_w62_research_robustness_gate_20260815.md`](proof/w0815bc_w62_research_robustness_gate_20260815.md) · multi_period≥2 · sign majority · not catastrophic · optional WF no full flip · **pass ≠ READY/Mass/GO**  
**S1–S3 examples (W61 metrics):** S1 soft **PASS** / hard-WF **FAIL** · S2/S3 soft **PASS** — still **未宣言**  
**S4/S5:** [`docs/proof/w0815bc_w62_extra_hyp_s4_s5_20260815.md`](proof/w0815bc_w62_extra_hyp_s4_s5_20260815.md) · margin_change_sign / short_ratio_delta_sign · S4 soft **PASS** (weak) · S5 **FAIL** · w2024 empty · aa `archive_ingest_pollution`  
**Logs:** [`.glm-logs/w0815bc_w62_gate_hyp/`](../.glm-logs/w0815bc_w62_gate_hyp/)  
**Prior W61 multi-period + WF:** held underneath

| gate | status |
|------|--------|
| READY | **未宣言** (gate pass does not connect) |
| Mass / Phase7 | **NO-GO / OFF** |
| Dataset COMPLETE | **21** |
| COMPLETE segs | **3478** |
| empty COMPLETE | **0** |
| OTC | **93** |
| densify | **none** |
| Robustness gate | **landed research-only** |
| S4/S5 | evaluated · **not GO** |

### Explicit non-declarations (held)

- **READY** — not declared  
- **Mass** — **NO-GO / OFF**  
- **Phase7** — **OFF**

## 複数期間シグナル再評価 + 研究用ウォークフォワード（READY 未宣言）

**Phase name:** COMPLETE 21 複数期間 S1/S2/S3 再評価 + 研究用 WF（宣言なし）  
**Wave:** W61 / w0815bb  
**Close:** [`docs/proof/w0815bb_w61_multi_period_close_20260815.md`](proof/w0815bb_w61_multi_period_close_20260815.md)  
**Multi-period:** [`.glm-logs/w0815bb_w61_multiperiod/`](../.glm-logs/w0815bb_w61_multiperiod/) · report [`docs/proof/w0815bb_w61_multi_period_multisignal_20260815.md`](proof/w0815bb_w61_multi_period_multisignal_20260815.md) · `history_source=r2` · codes **30** · windows **w2022q4 (40d)** · **w2023q4 (40d)** · **w2024q4 (50d)** · **w2025q1 (25d)**  

| period | S1 meanR +1 / −1 | S1 gross | S2 nn | S3 nn | S3 gross |
|--------|------------------:|---------:|------:|------:|---------:|
| w2022q4 | −0.00010 / −0.00105 | +0.00043 | **0** | 0.95 | +0.00021 |
| w2023q4 | **+0.00243 / −0.00141** | **+0.00188** | **0** | 0.96 | +0.00209 |
| w2024q4 | −0.00018 / −0.00024 | ~0 | 0.047 | 0.64 | +0.00069 |
| w2025q1 | −0.0203 / −0.0189 | −0.00032 | 0.64 | 1.00 | −0.00032 |

· tip-20d S1 separation **not** stable across long R2 periods · only mild same-direction print on **w2023q4** · **小サンプル / 研究用・未宣言**  
**Walk-forward (research):** API `split_asof_days_walk_forward` + `run_research_walk_forward_multisignal` · w2024q4 train 25d / test 25d · **threshold_tuning=false** · train S1 gross **−** / test S1 gross **+** (unstable within-window) · proof [`docs/proof/w0815bb_w61_walk_forward_research_20260815.md`](proof/w0815bb_w61_walk_forward_research_20260815.md)  
**Coverage inventory:** [`docs/proof/w0815bb_w61_coverage_inventory_20260815.md`](proof/w0815bb_w61_coverage_inventory_20260815.md) · topix JSONL gap 2024–2025 (archive used) · margin/short JSONL year gaps (empty_allowed, not invented)  
**Harness:** `run_multi_period_multisignal_compare` · `run_research_walk_forward_multisignal` · freezes Mass **NO-GO** / Phase7 **OFF**  
**Prior W60 long multi-signal + bridge expand:** held underneath

| gate | status |
|------|--------|
| READY | **未宣言** |
| Mass / Phase7 | **NO-GO / OFF** |
| Dataset COMPLETE | **21** |
| COMPLETE segs | **3478** |
| empty COMPLETE | **0** |
| OTC | **93** |
| permanent DEFER | **5** |
| densify | **none** |
| Multi-period | **4/4 ok** · no invent fills |
| Research WF | **landed** · fixed defs · not GO |
| tip densify | **SKIP** |

### Explicit non-declarations (held)

- **READY** — not declared  
- **Mass** — **NO-GO / OFF**  
- **Phase7** — **OFF**

## 長期窓マルチシグナル比較 + 橋拡張（READY 未宣言）

**Phase name:** COMPLETE 21 長期窓マルチシグナル比較 + 橋拡張（宣言なし）  
**Wave:** W60 / w0815ba  
**Close proof:** [`docs/proof/w0815ba_w60_long_multisignal_close_20260815.md`](proof/w0815ba_w60_long_multisignal_close_20260815.md)  
**Long multi-signal (A):** [`.glm-logs/w0815ba_w60_long_multisignal/`](../.glm-logs/w0815ba_w60_long_multisignal/) · [`summary.json`](../.glm-logs/w0815ba_w60_long_multisignal/summary.json) · job `w0815ba-g1-long-multisignal` · `history_source=r2` · **n_days=50** · **n_codes=30** · period `2024-09-02…2024-12-18` · S1/S2/S3 same definitions as W58 · report [`docs/proof/w0815ba_w60_long_multisignal_compare_20260815.md`](proof/w0815ba_w60_long_multisignal_compare_20260815.md) · R2 `research/single_shot/job=w0815ba-g1-long-multisignal/batch_summary.json`  

| signal | non_null rate | mean R +1 | mean R −1 | gross signed mean | net 10bp one-way |
|--------|--------------:|----------:|----------:|------------------:|-----------------:|
| S1 topix_rel | **1.000** | **−0.000182** | **−0.000245** | ~0 | **−0.000973** |
| S2 volume_sign | **0.047** | −0.00381 | −0.00165 | **−0.000275** | **−0.001275** |
| S3 topix+disc | **0.636** | +0.000369 | −0.000977 | **+0.000688** | **−0.000312** |

· tip-20d (W58) S1 separation **not** held on long window (reconfirm W59) · S2 fire-rate collapses 0.75→0.047 · S3 denser via R2 fins but still **no** edge claim · **小サンプル / 研究用・未宣言**  
**Bridge expand (B):** [`docs/proof/w0815ba_w60_bridge_expand_20260815.md`](proof/w0815ba_w60_bridge_expand_20260815.md) · datasets **markets_margin_interest** · **markets_short_ratio** · **fins_summary** · **markets_margin_alert** · live extract counts 1200 / 790 / 77 / 500 · `AVAILABLE_AT_REPAIR_POLICY` documented · DEFER 5 hard reject held · multi-signal path accepts `history_source=r2`  
**Ops / FRESH:** [`.glm-logs/w0815ba_w60_ops/`](../.glm-logs/w0815ba_w60_ops/) · FRESH `projgen-acdc868d174e4304ae93da453c01f057` · segs **3478** · dc **21** · empty **0** · OTC **93** · Mass **NO-GO** · Phase7 **OFF**  
**Promotion:** held **9 approved** / **1 candidate** (`return_1d_c21`) · **no promote**  
**Prior W59 R2 bridge + S1 long eval:** held underneath

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 長期窓マルチシグナル比較 + 橋拡張（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言** |
| Mass | **NO-GO / OFF** |
| Phase7 | **OFF** |
| empty COMPLETE | **0** |
| Dataset COMPLETE | **21** |
| COMPLETE segs | **3478** |
| OTC tip island | **93** |
| permanent DEFER | **5** hard reject |
| tip densify | **SKIP** |
| densify | **none** |
| Projection | **FRESH** `projgen-acdc868d174e4304ae93da453c01f057` |
| Long multi-signal | **PASS** · 50d×30 · S1/S2/S3 · tip vs long delta documented · no edge |
| Bridge expand | **margin / short / fins / alert** loadable under PIT · aa policy explicit |
| Promotion | **9 approved** · **1 candidate** no-promote |
| Unit tests | r2_feature_context + eval_harness + complete21 min + permanent_defer + mass gate **pass** |

**Primary this phase:** long-window multi-signal fairness (S1/S2/S3) vs tip-20d + expand R2 FeatureContext bridge to high-value COMPLETE datasets — research-only.  
**Not:** READY / Mass / Phase7 / densify / COMPLETE 22 / promote `return_1d_c21` / look-ahead / significance / orders.

### Explicit non-declarations (held)

- **READY** — not declared  
- **Mass Autonomous Research** — **NO-GO / OFF**  
- **Phase7** — **OFF**

## R2→FeatureContext 研究用橋（READY 未宣言）

**Phase name:** COMPLETE 21 R2→FeatureContext 研究用橋（宣言なし）  
**Wave:** W59 / w0815az (T1–T14 · G5 FINAL merge + push)  
**Close proof:** [`docs/proof/w0815az_w59_bridge_close_20260815.md`](proof/w0815az_w59_bridge_close_20260815.md)  
**Bridge (G1 · research-only):** [`.glm-logs/w0815az_g1_bridge/`](../.glm-logs/w0815az_g1_bridge/) · module [`packages/product/research/r2_feature_context.py`](../packages/product/research/r2_feature_context.py) · tests [`tests/test_r2_feature_context.py`](../tests/test_r2_feature_context.py) (**23 passed**) · proof [`docs/proof/w0815az_w59_r2_feature_context_bridge_20260815.md`](proof/w0815az_w59_r2_feature_context_bridge_20260815.md) · inventory [`t1_r2_inventory.json`](../.glm-logs/w0815az_g1_bridge/t1_r2_inventory.json) · schema map [`t2_schema_mapping.json`](../.glm-logs/w0815az_g1_bridge/t2_schema_mapping.json) · **T1–T5 DONE** — R2 JSONL+archive inventory · FeatureContext schema map · research loader · PIT (`available_at` required / `<= as_of`) · DEFER 5 hard reject · wired `history_source="r2"|"d1_tip"` into `execute_multiday_signal_eval` / nextday / eval_harness · default remains **`d1_tip`** (backward compatible) · S1 MVP datasets `equities_bars_daily` · `indices_bars_daily_topix` · `markets_calendar` · COMPLETE 21 inventory-mapped · local SQLite mirror **disposable only / not SoT** · **can_build_40d_asof=yes** · label **研究用・未宣言**  
**Verify (G2):** [`.glm-logs/w0815az_g2_verify/`](../.glm-logs/w0815az_g2_verify/) · [`RETURN_CARD.json`](../.glm-logs/w0815az_g2_verify/RETURN_CARD.json) · **40d_ok=yes** · pytest **131** · **tip_path_ok=true**  
**Long-window S1 (G3 pre-bridge DEFER → G3b live success):** G3 [`.glm-logs/w0815az_g3_long/`](../.glm-logs/w0815az_g3_long/) · **PASS_DEFER** pre-bridge (superseded) · G3b [`.glm-logs/w0815az_g3b_long/`](../.glm-logs/w0815az_g3b_long/) · [`RETURN_CARD.json`](../.glm-logs/w0815az_g3b_long/RETURN_CARD.json) · proof [`docs/proof/w0815az_w59_long_window_signal_eval_20260815.md`](proof/w0815az_w59_long_window_signal_eval_20260815.md) · job `w0815az-g3-long` · **long_eval_ran=yes** · **n_days=50** · **n_codes=30** · `history_source=r2` · period `2024-09-02…2024-12-18` · mean R +1 **−0.000182** / −1 **−0.000245** · overall **−0.000213** · non_null_rate **1.0** · return_null_rate **0.02** · R2 `research/single_shot/job=w0815az-g3-long/batch_summary.json` · **PASS_LONG_R2** · **小サンプル / 研究用・未宣言** · **no significance / no edge**  
**Ops / quality / residual (G4 T12–T14):** [`.glm-logs/w0815az_g4_ops/`](../.glm-logs/w0815az_g4_ops/) · [`FINAL_metrics.json`](../.glm-logs/w0815az_g4_ops/FINAL_metrics.json) · [`switch_check.json`](../.glm-logs/w0815az_g4_ops/switch_check.json) · [`SUMMARY.txt`](../.glm-logs/w0815az_g4_ops/SUMMARY.txt)  
**G5 final merge:** [`.glm-logs/w0815az_g5_final/`](../.glm-logs/w0815az_g5_final/) · empty **0** · dc **21** · segs **3478** · OTC **93** · pytest **137** · push **yes**  
**Promotion:** held **9 approved** / **1 candidate** (`return_1d_c21`) · **no promote this wave** · policy no-promote: `return_1d_c21`  
**FRESH (G4 T13):** reclock `projgen-38b19559dba646dcb463409c78f3bc9e` (pre age wall **~1503s** >300; coverage_segments untouched; publish apply **SKIP**)  
**Unit tests (G5 merge):** complete21 min (approved **9**) + permanent_defer + single_shot + mass gate + eval_harness + r2_feature_context · **137 passed**  
**Mass / Phase7 (G4/G5):** **NO-GO / OFF** reconfirmed · READY **not declared** · no arming switches  
**Catalog:** [`docs/proof/complete21_min_feature_catalog_20260815.md`](proof/complete21_min_feature_catalog_20260815.md) (code SoT = `complete21_min.py` **9 approved / 1 candidate**) · bridge module `research/r2_feature_context.py`  
**Prior W58 履歴拡大・複数シグナル比較:** § 履歴拡大・複数シグナル比較 held underneath · W57 ユニバース · coverage baseline **W47 FINAL** held

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 R2→FeatureContext 研究用橋（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** (research bridge only) |
| Mass | **NO-GO / OFF** — **reconfirmed** this wave (G4 T12 freezes + G5 merge) |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave |
| empty COMPLETE | **0** (remote verify G4 + G5) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| COMPLETE segs | **3478** (remote verify held · Δ0) |
| OTC tip island | **93** held |
| permanent DEFER | **5** held (hard reject on R2 history load) |
| tip densify | **SKIP** (T14; not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `a220af1d63a1ee0a24e5d212ebdfd9e8c3cfa9b2` (G5 FINAL merge) · PRE_sha `b079899a119576e5dc0e815390263e74bbdcb89b` |
| Projection | **FRESH** `projgen-38b19559dba646dcb463409c78f3bc9e` (G4 T13 ops_reeval_freshness; residual FRESH sync; publish apply **SKIP** no segment drift; fail-closed no force) |
| R2→FeatureContext bridge | G1 **landed** — research-only loader · `history_source=r2` optional · PIT + DEFER 5 · **can_build_40d_asof=yes** · Mass **not** connected · READY **not** declared |
| Long-window S1 live eval | G3b **PASS_LONG_R2** · **long_eval_ran=yes** · **n_days=50** · **n_codes=30** · mean R near **0** · research-only · **no** edge claim |
| Promotion | **held 9 approved** · remain **1 candidate** · **no** `return_1d_c21` promote |
| Unit tests | **137 passed** (complete21 min · permanent_defer · single_shot · mass gate · eval_harness · r2_feature_context) |
| raw_retention | **15915** held (not coverage primary) |

**Primary this phase:** land research-only R2 structured history → FeatureContext bridge (COMPLETE 21 inventory · S1 MVP · PIT · DEFER fail-closed) · live 40–60 day S1 long eval via R2 · residual R2→FeatureContext 研究用橋 on held COMPLETE **21** / DEFER **5** — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON · treat bridge as READY · force remaining candidate · promote `return_1d_c21` · significance / edge / operational GO claim.

### Explicit non-declarations (held)

- **READY** — not declared (R2→FeatureContext 研究用橋 only; research path; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF**
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## 履歴拡大・複数シグナル比較（READY 未宣言）

**Phase name:** COMPLETE 21 履歴拡大・複数シグナル比較（宣言なし）  
**Wave:** W58 / w0815ay (T1–T12 · G4 FINAL merge + push)  
**Close proof:** [`docs/proof/w0815ay_w58_history_multisignal_close_20260815.md`](proof/w0815ay_w58_history_multisignal_close_20260815.md)  
**History expand (G1 · tip max only · 小サンプル):** [`.glm-logs/w0815ay_g1_history/`](../.glm-logs/w0815ay_g1_history/) · [`RETURN_CARD.json`](../.glm-logs/w0815ay_g1_history/RETURN_CARD.json) · job `w0815ay-g1-history60` · **history_expand_possible=NO** (R2 JSONL+archive **exists**; multiday eval is **D1 tip-only** · no R2→FeatureContext bridge) · D1 tip `equities_bars_daily` **2026-07-01…2026-08-10** (n rows **124367** · trading days **28**) · TOPIX tip days **28** · cold join plan window **2026-04-01…2026-08-14** · **n_days=28** tip max · **n_codes=30** · mean R +1 **+0.00643** / −1 **−0.00148** · median +1 **+0.00648** / −1 **−0.00093** · proof [`docs/proof/w0815ay_w58_history_window_eval_20260815.md`](proof/w0815ay_w58_history_window_eval_20260815.md) · R2 `research/single_shot/job=w0815ay-g1-history60/batch_summary.json` · **40–60 day eval NOT possible** without invent  
**Multi-signal compare (G2 · research metrics · 小サンプル):** [`.glm-logs/w0815ay_g2_multisignal/`](../.glm-logs/w0815ay_g2_multisignal/) · [`summary.json`](../.glm-logs/w0815ay_g2_multisignal/summary.json) · [`RETURN_CARD.json`](../.glm-logs/w0815ay_g2_multisignal/RETURN_CARD.json) · [`batch_summary.json`](../.glm-logs/w0815ay_g2_multisignal/batch_summary.json) · job `w0815ay-g2-multisignal` · **n_codes=30** · **n_days=20** · as_of `2026-07-13…2026-08-10` · period `2026-07-01…2026-08-14` · signals **S1** `c21_topix_relative_sign@1.0.0` · **S2** `c21_volume_change_sign@1.0.0` (|Δvol|≥0.10) · **S3** `c21_topix_rel_disclosure_filter@1.0.0` · all legs **approved** · status **candidate** · **candidate_only=False** · Mass **OFF** · no orders · no READY · label **小サンプル / 研究用・未宣言** · cost label **仮定に依存・研究用・運用GOではない** (one-way **10bp** / RT **20bp**) · report [`docs/proof/w0815ay_w58_multi_signal_compare_report_20260815.md`](proof/w0815ay_w58_multi_signal_compare_report_20260815.md) · compare (gross signed mean active / mean R +1 / −1):

| signal | non_null | +1 n | −1 n | mean R +1 | mean R −1 | median R +1 | median R −1 | gross signed mean | net one-way mean |
|--------|----------|------|------|-----------|-----------|-------------|-------------|-------------------|------------------|
| S1 topix_rel | **600/600** (1.0) | 312 | 288 | **+0.00823** | **−0.00202** | **+0.00900** | **−0.00098** | **+0.00528** | **+0.00428** |
| S2 volume_sign | **451/600** (0.752) | 206 | 245 | +0.00165 | +0.00298 | +0.00193 | +0.00278 | **−0.00078** | **−0.00178** |
| S3 topix+disc | **177/600** (0.295) | 89 | 88 | +0.00718 | +0.00055 | +0.00805 | +0.00034 | **+0.00345** | **+0.00245** |

· overall mean/median R (shared market) **+0.00336** / **+0.00305** · null_return_rate overall **0.05** · look-ahead policy held · R2 `research/single_shot/job=w0815ay-g2-multisignal/batch_summary.json` · **e2e_pass=true** · **no significance / no edge / no operational GO**  
**Ops / quality / residual (G3):** [`.glm-logs/w0815ay_g3_ops/`](../.glm-logs/w0815ay_g3_ops/) · [`FINAL_metrics.json`](../.glm-logs/w0815ay_g3_ops/FINAL_metrics.json) · [`switch_check.json`](../.glm-logs/w0815ay_g3_ops/switch_check.json) · [`SUMMARY.txt`](../.glm-logs/w0815ay_g3_ops/SUMMARY.txt)  
**G4 final merge:** [`.glm-logs/w0815ay_g4_final/`](../.glm-logs/w0815ay_g4_final/) · empty **0** · dc **21** · segs **3478** · OTC **93** · pytest **114** · push **yes**  
**Promotion (G3):** held **9 approved** / **1 candidate** (`return_1d_c21`) · **no promote this wave** · policy no-promote: `return_1d_c21`  
**FRESH (G3 T11):** reclock `projgen-20e613d7a30943378004831cdc26c9b2` (pre age wall **~805s** >300; coverage_segments untouched; publish apply **SKIP**)  
**Unit tests (G4 merge):** complete21 min (approved **9**) + permanent_defer + single_shot + mass gate + eval_harness · **114 passed**  
**Mass / Phase7 (G3 T10):** **NO-GO / OFF** reconfirmed · READY **not declared** · no arming switches  
**Catalog:** [`docs/proof/complete21_min_feature_catalog_20260815.md`](proof/complete21_min_feature_catalog_20260815.md) (code SoT = `complete21_min.py` **9 approved / 1 candidate**) · multi-signal defs in `features/minimal_signal.py` + `research/single_shot_job.py`  
**Prior W57 ユニバース拡大・研究レポート:** § ユニバース拡大・研究レポート held underneath · W56 研究ハーネス · coverage baseline **W47 FINAL** held

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 履歴拡大・複数シグナル比較（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** (research metrics only) |
| Mass | **NO-GO / OFF** — **reconfirmed** this wave (G3 T10) |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave (G3 T10) |
| empty COMPLETE | **0** (remote verify G3 + G4) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| COMPLETE segs | **3478** (remote verify held · Δ0) |
| OTC tip island | **93** held |
| permanent DEFER | **5** held |
| tip densify | **SKIP** (T12; not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `35f3425ec60a648b74b484a009f0007201af5dcd` (G4 FINAL merge) · PRE_sha `e86a4cc584891ad15b346294053c1e5705c9f286` |
| Projection | **FRESH** `projgen-20e613d7a30943378004831cdc26c9b2` (G3 T11 ops_reeval_freshness; residual FRESH sync; publish apply **SKIP** no segment drift; fail-closed no force) |
| History expand | G1 **NO** — tip max **28** · target 40–60 **blocked** (R2 history exists; tip-only eval path; no invent) · mean R +1 **+0.00643** / −1 **−0.00148** · Mass **not** connected |
| Multi-signal compare | G2 **PASS** — 3 signals · n_codes=**30** · n_days=**20** · cost 10bp research-only · Mass **not** connected · no orders · **小サンプル / 研究用・未宣言** · no significance / no edge |
| Promotion | **held 9 approved** · remain **1 candidate** · **no** `return_1d_c21` promote |
| Unit tests | **114 passed** (complete21 min · permanent_defer · single_shot · mass gate · eval_harness) |
| raw_retention | **15915** held (not coverage primary) |

**Primary this phase:** history expand investigation (honest tip-max when 40–60 blocked) · multi-signal compare (S1 topix_rel / S2 volume_sign / S3 topix+disclosure) with research-only cost · residual 履歴拡大・複数シグナル比較 on held COMPLETE **21** / DEFER **5** — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON · treat multi-signal as READY · force remaining candidate · promote `return_1d_c21` · significance / edge / operational GO claim · claim 40–60 day history eval.

### Explicit non-declarations (held)

- **READY** — not declared (履歴拡大・複数シグナル比較 only; research metrics; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF**
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## ユニバース拡大・研究レポート（READY 未宣言）

**Phase name:** COMPLETE 21 ユニバース拡大・研究レポート（宣言なし）  
**Wave:** W57 / w0815ax (T1–T12 · G4 FINAL merge + push)  
**Universe close proof:** [`docs/proof/w0815ax_w57_universe_close_20260815.md`](proof/w0815ax_w57_universe_close_20260815.md)  
**Universe expand eval (G1 · research metrics · 小サンプル):** [`.glm-logs/w0815ax_g1_universe/`](../.glm-logs/w0815ax_g1_universe/) · job `w0815ax-g1-universe` · **n_codes=30** · **n_days=20** · signal `c21_topix_relative_sign@1.0.0` · `status=candidate` · **candidate_only=False** · Mass **OFF** · no orders · no READY · label **小サンプル / 研究用・未宣言** · mean R +1 **+0.00823** / −1 **−0.00202** · median +1 **+0.00900** / −1 **−0.00098** · proof [`docs/proof/w0815ax_w57_universe_expand_eval_20260815.md`](proof/w0815ax_w57_universe_expand_eval_20260815.md) · research report [`docs/proof/w0815ax_w57_research_signal_eval_report_20260815.md`](proof/w0815ax_w57_research_signal_eval_report_20260815.md)  
**Ops / quality / residual (G3):** [`.glm-logs/w0815ax_g3_ops/`](../.glm-logs/w0815ax_g3_ops/) · [`FINAL_metrics.json`](../.glm-logs/w0815ax_g3_ops/FINAL_metrics.json) · [`switch_check.json`](../.glm-logs/w0815ax_g3_ops/switch_check.json) · [`SUMMARY.txt`](../.glm-logs/w0815ax_g3_ops/SUMMARY.txt)  
**Optional O2 (G3 T7):** [`.glm-logs/w0815ax_g3_o2/`](../.glm-logs/w0815ax_g3_o2/) · [`t7_margin_alert_flag_summary.json`](../.glm-logs/w0815ax_g3_o2/t7_margin_alert_flag_summary.json) · feature `margin_alert_flag` · tip `markets_margin_alert` · **o2_pass** (non_null **5** · tip rows **1094** · sample **1.0**) · **promoted → approved** (version pin **1.0.0**) · policy no-promote: `return_1d_c21` · proof [`docs/proof/w0815ax_w57_o2_margin_alert_20260815.md`](proof/w0815ax_w57_o2_margin_alert_20260815.md)  
**Promotion (G3):** `packages/research_runtime/features/complete21_min.py` · this wave **+1 approved**: `margin_alert_flag` · **total 9 approved** (W52–W56 **8** + W57 `margin_alert_flag`) · remain **1 candidate** (`return_1d_c21`)  
**FRESH (G3 T11):** reclock `projgen-30219278e4064f258021f02eb00bbbc9` (pre age wall **~940s** >300; coverage_segments untouched; publish apply **SKIP**)  
**Unit tests (G4 merge):** complete21 min (approved **9+**) + permanent_defer + single_shot + mass gate + eval_harness · **114 passed**  
**Mass / Phase7 (G3 T10):** **NO-GO / OFF** reconfirmed · READY **not declared** · no arming switches  
**Catalog:** [`docs/proof/complete21_min_feature_catalog_20260815.md`](proof/complete21_min_feature_catalog_20260815.md) (code SoT = `complete21_min.py` **9 approved / 1 candidate**)  
**Prior W56 研究ハーネス・評価窓拡大:** § 研究ハーネス・評価窓拡大 held underneath · W55 評価深化 · W54 複数日 · coverage baseline **W47 FINAL** held

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 ユニバース拡大・研究レポート（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** (research report only) |
| Mass | **NO-GO / OFF** — **reconfirmed** this wave (G3 T10) |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave (G3 T10) |
| empty COMPLETE | **0** (remote verify G3 + G4 re-verify) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| COMPLETE segs | **3478** (remote verify held · Δ0) |
| OTC tip island | **93** held |
| permanent DEFER | **5** held |
| tip densify | **SKIP** (T12; not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `8357a0dfa543ef97a953d5583f4ac48ba1257618` (G4 FINAL merge) · PRE_sha `8381d9106167d65118f57509d67ed488419ceddf` |
| Projection | **FRESH** `projgen-30219278e4064f258021f02eb00bbbc9` (G3 T11 ops_reeval_freshness; residual FRESH sync; publish apply **SKIP** no segment drift; fail-closed no force) |
| Universe expand eval | G1 **PASS** — n_codes=**30** · n_days=**20** · mean+median by sign · Mass **not** connected · no orders · **小サンプル / 研究用・未宣言** · no significance / no edge |
| Research report | G2 **written** — template + filled · 小サンプル · no READY claim |
| Optional O2 | G3 T7 **PASS** — `margin_alert_flag` tip E2E non-null **5** · **+1 approved** |
| Promotion | **+1 this wave** → **9 approved** total · remain **1 candidate** · no READY claim · **no** `return_1d_c21` |
| Unit tests | **114 passed** (complete21 min · permanent_defer · single_shot · mass gate · eval_harness) |
| raw_retention | **15915** held (not coverage primary) |

**Primary this phase:** expand tip code universe **3 → 30** · multiday + nextday research eval (n_days=20) · research signal eval report · optional O2 (`margin_alert_flag`) on held COMPLETE **21** / DEFER **5** — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON · treat universe expand as READY · force remaining candidate · promote `return_1d_c21` · significance / edge claim.

### Explicit non-declarations (held)

- **READY** — not declared (ユニバース拡大・研究レポート only; research metrics; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF**
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## 研究ハーネス・評価窓拡大（READY 未宣言）

**Phase name:** COMPLETE 21 研究ハーネス・評価窓拡大（宣言なし）  
**Wave:** W56 / w0815aw (T1–T12 · G4 FINAL merge + push)  
**Expand20 close proof:** [`docs/proof/w0815aw_w56_expand20_close_20260815.md`](proof/w0815aw_w56_expand20_close_20260815.md)  
**Ops / quality / residual (G3):** [`.glm-logs/w0815aw_g3_ops/`](../.glm-logs/w0815aw_g3_ops/) · [`FINAL_metrics.json`](../.glm-logs/w0815aw_g3_ops/FINAL_metrics.json) · [`switch_check.json`](../.glm-logs/w0815aw_g3_ops/switch_check.json) · [`SUMMARY.txt`](../.glm-logs/w0815aw_g3_ops/SUMMARY.txt)  
**Expand20 nextday eval (G1 · research metrics · 小サンプル):** [`.glm-logs/w0815aw_g1_expand20/`](../.glm-logs/w0815aw_g1_expand20/) · [`summary.json`](../.glm-logs/w0815aw_g1_expand20/summary.json) · [`batch_summary.json`](../.glm-logs/w0815aw_g1_expand20/batch_summary.json) · `execute_multiday_nextday_return_eval` · job `w0815aw-g1-expand20` · **n_days=20** (tip available **28**) as_of days `2026-07-13…2026-08-10` · codes `13010/72030/67580` · signal `c21_topix_relative_sign@1.0.0` · `status=candidate` · **candidate_only=False** · Mass **OFF** · no orders · no READY · label **小サンプル / 研究用・未宣言** · signal aggregate non_null **60/60** (rate **1.0**) sign `+1:32` / `-1:28` · **nextday mean_R** `+1:+0.01075` / `-1:-0.00459` · **median_R** `+1:+0.01114` / `-1:-0.00296` · overall mean/median `+0.00375` / `+0.00177` · null_return_rate overall **0.05** · look-ahead policy held · R2 `research/single_shot/job=w0815aw-g1-expand20/batch_summary.json` · **e2e_pass=true** · proof [`docs/proof/w0815aw_w56_expand20_nextday_eval_20260815.md`](proof/w0815aw_w56_expand20_nextday_eval_20260815.md)  
**Eval harness (G2):** `packages/product/research/eval_harness.py` · tests `tests/test_eval_harness.py` (**14**) · README · pipeline approved-leg signal → multiday → nextday → R2 batch_summary · Mass/READY/Phase7 closed  
**Optional O2 (G3 T8):** [`.glm-logs/w0815aw_g3_o2/`](../.glm-logs/w0815aw_g3_o2/) · [`t8_futures_activity_proxy_summary.json`](../.glm-logs/w0815aw_g3_o2/t8_futures_activity_proxy_summary.json) · feature `futures_activity_proxy` · tip `derivatives_bars_daily_futures` · **o2_pass** (non_null≥1 · value **1408195.0**) · **promoted → approved** (version pin **1.0.0**) · not chosen: `margin_alert_flag` · policy no-promote: `return_1d_c21` · proof [`docs/proof/w0815aw_w56_o2_futures_20260815.md`](proof/w0815aw_w56_o2_futures_20260815.md)  
**Promotion (G3):** `packages/research_runtime/features/complete21_min.py` · this wave **+1 approved**: `futures_activity_proxy` · **total 8 approved** (W52–W55 **7** + W56 `futures_activity_proxy`) · remain **2 candidate** (`margin_alert_flag` · `return_1d_c21`)  
**FRESH (G3 T10):** reclock `projgen-4a73478f55d84323870198094f875450` (pre age wall **~1000s** >300; coverage_segments untouched; publish apply **SKIP**)  
**Unit tests (G4 merge):** complete21 min (approved **8+**) + permanent_defer + single_shot + eval_harness + mass gate · **114 passed** (G3 core **100** + harness **14**)  
**Catalog:** [`docs/proof/complete21_min_feature_catalog_20260815.md`](proof/complete21_min_feature_catalog_20260815.md) (code SoT = `complete21_min.py` **8 approved / 2 candidate**)  
**Prior W55 評価深化・翌日リターン突合:** § 評価深化・翌日リターン突合 held underneath · W54 複数日 · W53 O2強化 · coverage baseline **W47 FINAL** held

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 研究ハーネス・評価窓拡大（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** (research harness only) |
| Mass | **NO-GO / OFF** (expand20 / harness single_shot Mass **OFF**) |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave |
| empty COMPLETE | **0** (remote verify G3 + G4 re-verify) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| COMPLETE segs | **3478** (remote verify held · Δ0) |
| OTC tip island | **93** held |
| permanent DEFER | **5** held |
| tip densify | **SKIP** (T12; not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `4965739d751eed1c7ae3a8b2dfe84c6893751837` (G4 FINAL merge) · PRE_sha `c8423531cfe691eb6001e8f46d488310cc1e029b` |
| Projection | **FRESH** `projgen-4a73478f55d84323870198094f875450` (G3 T10 ops_reeval_freshness; residual FRESH sync; publish apply **SKIP** no segment drift; fail-closed no force) |
| Expand20 nextday eval | G1 **PASS** — n_days=**20** · mean+median by sign · Mass **not** connected · no orders · **小サンプル / 研究用・未宣言** · no significance / no edge |
| Eval harness | G2 **landed** — `eval_harness.py` · **14** tests · closed Mass/READY/Phase7 |
| Optional O2 | G3 T8 **PASS** — `futures_activity_proxy` tip E2E non-null · **+1 approved** |
| Promotion | **+1 this wave** → **8 approved** total · remain **2 candidate** · no READY claim |
| Unit tests | **114 passed** (complete21 min · permanent_defer · single_shot · eval_harness · mass gate) |
| raw_retention | **15915** held (not coverage primary) |

**Primary this phase:** expand tip multiday **nextday** eval (~20 trading days) + stable **eval harness** + optional O2 (`futures_activity_proxy`) on held COMPLETE **21** / DEFER **5** — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON · treat expand20 as READY · force remaining 2 candidates · promote `return_1d_c21` · significance / edge claim.

### Explicit non-declarations (held)

- **READY** — not declared (研究ハーネス・評価窓拡大 only; research metrics; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF** (expand20 / harness single_shot Mass OFF)
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## 評価深化・翌日リターン突合（READY 未宣言）

**Phase name:** COMPLETE 21 評価深化・翌日リターン突合（宣言なし）  
**Wave:** W55 / w0815av (T1–T12 · G5 FINAL merge + push)  
**Nextday close proof:** [`docs/proof/w0815av_w55_nextday_close_20260815.md`](proof/w0815av_w55_nextday_close_20260815.md)  
**Ops / quality / residual (G3):** [`.glm-logs/w0815av_g3_ops/`](../.glm-logs/w0815av_g3_ops/) · [`FINAL_metrics.json`](../.glm-logs/w0815av_g3_ops/FINAL_metrics.json) · [`switch_check.json`](../.glm-logs/w0815av_g3_ops/switch_check.json) · [`SUMMARY.txt`](../.glm-logs/w0815av_g3_ops/SUMMARY.txt)  
**Nextday return alignment (G1 · research metrics):** [`.glm-logs/w0815av_g1_nextday/`](../.glm-logs/w0815av_g1_nextday/) · [`summary.json`](../.glm-logs/w0815av_g1_nextday/summary.json) · [`batch_summary.json`](../.glm-logs/w0815av_g1_nextday/batch_summary.json) · `execute_multiday_nextday_return_eval` · job `w0815av-g1-nextday` · **n_days=6** as_of days `2026-08-03…2026-08-10` · codes `13010/72030/67580` · signal `c21_topix_relative_sign@1.0.0` · `status=candidate` · **candidate_only=False** · Mass **OFF** · no orders · no READY · label **研究用・未宣言** · signal aggregate non_null **15/18** (rate **0.8333333333333334**) sign `+1:6` / `-1:9` / `null:3` · **nextday mean_R** `+1:0.013616` / `-1:0.005943` / overall `0.004928` · null_return_rate overall **0.16666666666666666** · look-ahead policy: feature as_of=T close; return=`close(T+1)/close(T)-1` with evaluation_as_of=T+1 close; **no feature look-ahead** · R2 `research/single_shot/job=w0815av-g1-nextday/batch_summary.json` · **e2e_pass=true** · proof [`docs/proof/w0815av_w55_nextday_return_eval_20260815.md`](proof/w0815av_w55_nextday_return_eval_20260815.md)  
**Selective O2 (G2):** [`.glm-logs/w0815av_g2_o2/`](../.glm-logs/w0815av_g2_o2/) · [`t5_short_ratio_level_summary.json`](../.glm-logs/w0815av_g2_o2/t5_short_ratio_level_summary.json) · feature `short_ratio_level` · tip `markets_short_ratio` S33 sections · **o2_pass** (non_null≥1) · **promoted → approved** (version pin **1.0.0**) · policy no-promote: `return_1d_c21` · proof [`docs/proof/w0815av_w55_o2_short_ratio_20260815.md`](proof/w0815av_w55_o2_short_ratio_20260815.md)  
**Promotion (G2):** `packages/research_runtime/features/complete21_min.py` · this wave **+1 approved**: `short_ratio_level` · **total 7 approved** (W52–W54 **6** + W55 `short_ratio_level`) · remain **3 candidate** (`futures_activity_proxy` · `margin_alert_flag` · `return_1d_c21`)  
**FRESH (G3 T9):** reclock `projgen-b7c349edd3fb454a806ede864cf80bcf` (pre age wall **~679s** >300; coverage_segments untouched; publish apply **SKIP**)  
**Unit tests (G5 merge):** complete21 min (approved **7+**) + permanent_defer + single_shot (nextday) + mass gate · **100 passed**  
**Catalog:** [`docs/proof/complete21_min_feature_catalog_20260815.md`](proof/complete21_min_feature_catalog_20260815.md) (code SoT = `complete21_min.py` **7 approved / 3 candidate**)  
**Prior W54 複数日シグナル評価:** § 複数日シグナル評価 held underneath · W53 O2強化 · W52 approved/シグナル下地 · coverage baseline **W47 FINAL** held

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 評価深化・翌日リターン突合（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** (research metrics only) |
| Mass | **NO-GO / OFF** (nextday single_shot batch Mass **OFF**) |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave (G3 T10) |
| empty COMPLETE | **0** (remote verify G3 + G5 re-verify) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| COMPLETE segs | **3478** (remote verify held · Δ0) |
| OTC tip island | **93** held |
| permanent DEFER | **5** held |
| tip densify | **SKIP** (not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `4d727623ead2f30ce37b8e7850b1c278cc94a943` (G5 FINAL merge) · PRE_sha `205392f54ca832d67867fe96c149867f52586def` |
| Projection | **FRESH** `projgen-b7c349edd3fb454a806ede864cf80bcf` (G3 T9 ops_reeval_freshness; residual FRESH sync; publish apply **SKIP** no segment drift; fail-closed no force) |
| Nextday return eval | G1 **PASS** — multiday signal + R_{T→T+1} attach · mean-by-sign · Mass **not** connected · no orders · **研究用・未宣言** |
| Selective O2 | G2 **PASS** — `short_ratio_level` tip E2E non-null · **+1 approved** |
| Promotion | **+1 this wave** → **7 approved** total · remain **3 candidate** · no READY claim |
| Unit tests | **100 passed** (complete21 min · permanent_defer · single_shot · mass gate) |
| raw_retention | **15915** held (not coverage primary; W46 tip secondary **15869** held) |

**Primary this phase (research metrics only):** nextday tip **return alignment** (signal sign × R_{T→T+1}) + selective O2 (`short_ratio_level`) on held COMPLETE **21** / DEFER **5** — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON · treat nextday eval as READY · force remaining 3 candidates · promote `return_1d_c21`.

### Explicit non-declarations (held)

- **READY** — not declared (評価深化・翌日リターン突合 only; research metrics; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF** (nextday single_shot Mass OFF)
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## 複数日シグナル評価（READY 未宣言）

**Phase name:** COMPLETE 21 複数日シグナル評価（宣言なし）  
**Wave:** W54 / w0815au (T1–T12 · G5 FINAL merge + push)  
**Multiday close proof:** [`docs/proof/w0815au_w54_multiday_close_20260815.md`](proof/w0815au_w54_multiday_close_20260815.md)  
**Ops / quality / residual (G3):** [`.glm-logs/w0815au_g3_ops/`](../.glm-logs/w0815au_g3_ops/) · [`FINAL_metrics.json`](../.glm-logs/w0815au_g3_ops/FINAL_metrics.json) · [`switch_check.json`](../.glm-logs/w0815au_g3_ops/switch_check.json) · [`SUMMARY.txt`](../.glm-logs/w0815au_g3_ops/SUMMARY.txt)  
**Multiday signal batch (G1):** [`.glm-logs/w0815au_g1_multiday/`](../.glm-logs/w0815au_g1_multiday/) · [`summary.json`](../.glm-logs/w0815au_g1_multiday/summary.json) · [`batch_summary.json`](../.glm-logs/w0815au_g1_multiday/batch_summary.json) · `execute_multiday_signal_eval` · job `w0815au-g1-multiday` · **n_days=6** as_of days `2026-08-03`…`2026-08-10` · codes `13010`/`72030`/`67580` · signal `c21_topix_relative_sign@1.0.0` · `status=candidate` · **candidate_only=False** · Mass **OFF** · no orders · no READY · aggregate non_null **15/18** (rate **0.833**) sign `+1:6` / `-1:9` / `null:3` · R2 `research/single_shot/job=w0815au-g1-multiday/` · **e2e_pass=true** · proof [`docs/proof/w0815au_w54_multiday_signal_eval_20260815.md`](proof/w0815au_w54_multiday_signal_eval_20260815.md)  
**Selective O2 (G2):** [`.glm-logs/w0815au_g2_o2/`](../.glm-logs/w0815au_g2_o2/) · [`O2_RESULTS_MATRIX.json`](../.glm-logs/w0815au_g2_o2/O2_RESULTS_MATRIX.json) · feature `repo_rate_level` · tip `jsda_tokyo_repo_rates` · **o2_pass** (non_null≥1) · **promoted → approved** (version pin **1.0.0**) · not chosen: `short_ratio_level` · policy no-promote: `return_1d_c21` · proof [`docs/proof/w0815au_w54_o2_promotion_20260815.md`](proof/w0815au_w54_o2_promotion_20260815.md)  
**Promotion (G2):** `packages/research_runtime/features/complete21_min.py` · this wave **+1 approved**: `repo_rate_level` · **total 6 approved** (W52 `volume_change_1d` · `is_trading_day` + W53 `topix_relative_1d` · `disclosure_flag_fins` · `margin_interest_change_1d` + W54 `repo_rate_level`) · remain **4 candidate** · criteria [`docs/proof/complete21_feature_candidate_to_approved_criteria_20260815.md`](proof/complete21_feature_candidate_to_approved_criteria_20260815.md)  
**FRESH (G3 T10):** reclock `projgen-3d29a3d673cc4214bd0913639fb52ad5` (pre age wall **~1880s** >300; coverage_segments untouched; publish apply **SKIP**)  
**Unit tests (G5 merge):** complete21 min (approved **6+**) + permanent_defer + single_shot (multiday) + mass gate · **92 passed**  
**Catalog:** [`docs/proof/complete21_min_feature_catalog_20260815.md`](proof/complete21_min_feature_catalog_20260815.md) (code SoT = `complete21_min.py` **6 approved / 4 candidate**)  
**Prior W53 O2強化・再評価:** § O2強化・再評価 held underneath · W52 approved/シグナル下地 · W51 feature E2E · W50 usage E2E · W49 deepen · W48 groundwork · coverage baseline **W47 FINAL** held

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 複数日シグナル評価（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** |
| Mass | **NO-GO / OFF** (multiday single_shot batch Mass **OFF**) |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave |
| empty COMPLETE | **0** (remote verify G3 + G5 re-verify) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| COMPLETE segs | **3478** (remote verify held · Δ0) |
| OTC tip island | **93** held |
| permanent DEFER | **5** held |
| tip densify | **SKIP** (not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `93c45d92d1c6de1abf0d7e0856c1894b56aecd2a` (G5 FINAL merge) · PRE_sha `918c5b23eea60e19f1512cd094399ddfbb86cbb7` |
| Projection | **FRESH** `projgen-3d29a3d673cc4214bd0913639fb52ad5` (G3 T10 ops_reeval_freshness; residual FRESH sync; publish apply **SKIP** no segment drift; fail-closed no force) |
| Multiday signal eval | G1 **PASS** — 6 trading-day as_of batch · single tip extract reuse · R2 batch_summary + per-day signals · Mass **not** connected · no orders |
| Selective O2 | G2 **PASS** — `repo_rate_level` tip E2E non-null · **+1 approved** |
| Promotion | **+1 this wave** → **6 approved** total · remain **4 candidate** · no READY claim |
| Unit tests | **92 passed** (complete21 min · permanent_defer · single_shot · mass gate) |
| raw_retention | **15915** (remote verify; not coverage primary; W46 tip secondary **15869** held) |

**Primary this phase:** multiday tip **signal** evaluation batch (5–10 trading days) + selective O2 (`repo_rate_level`) on held COMPLETE **21** / DEFER **5** — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON · treat multiday signal as READY · force remaining 4 candidates · promote `return_1d_c21`.

### Explicit non-declarations (held)

- **READY** — not declared (複数日シグナル評価 only; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF** (multiday single_shot Mass OFF)
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## O2強化・再評価（READY 未宣言）

**Phase name:** COMPLETE 21 O2強化・再評価（宣言なし）  
**Wave:** W53 / w0815at (T1–T12 · G5 FINAL merge + push)  
**O2/signal close proof:** [`docs/proof/w0815at_w53_o2_signal_close_20260815.md`](proof/w0815at_w53_o2_signal_close_20260815.md)  
**O2 promotion proof:** [`docs/proof/w0815at_w53_o2_promotion_20260815.md`](proof/w0815at_w53_o2_promotion_20260815.md)  
**Signal 2nd E2E proof:** [`docs/proof/w0815at_w53_signal_e2e_20260815.md`](proof/w0815at_w53_signal_e2e_20260815.md) · spec [`docs/proof/c21_topix_relative_sign_spec_20260815.md`](proof/c21_topix_relative_sign_spec_20260815.md)  
**Ops / residual (G4):** [`.glm-logs/w0815at_g4_ops/`](../.glm-logs/w0815at_g4_ops/) · [`ops_snapshot.json`](../.glm-logs/w0815at_g4_ops/ops_snapshot.json) · [`switch_check.json`](../.glm-logs/w0815at_g4_ops/switch_check.json) · [`FINAL_metrics.json`](../.glm-logs/w0815at_g4_ops/FINAL_metrics.json)  
**O2 feature E2E (G1):** [`.glm-logs/w0815at_g1_o2/`](../.glm-logs/w0815at_g1_o2/) · [`O2_RESULTS_MATRIX.json`](../.glm-logs/w0815at_g1_o2/O2_RESULTS_MATRIX.json) · tip single_shot feature jobs · **o2_pass**: `topix_relative_1d` · `disclosure_flag_fins` · `margin_interest_change_1d` (PIT path; Aug tip margin weekly lag held)  
**Promotion (G1):** `packages/research_runtime/features/complete21_min.py` · this wave **+3 approved** (version pin **1.0.0**): `topix_relative_1d` · `disclosure_flag_fins` · `margin_interest_change_1d` · **total 5 approved** (incl. W52 `volume_change_1d` · `is_trading_day`) · remain **5 candidate** · criteria [`docs/proof/complete21_feature_candidate_to_approved_criteria_20260815.md`](proof/complete21_feature_candidate_to_approved_criteria_20260815.md)  
**Signal 2nd E2E (G2):** `packages/research_runtime/features/minimal_signal.py` · signal `c21_topix_relative_sign@1.0.0` · `status=candidate` · **candidate_only=False** (primary/filter/gate legs approved) · Mass **OFF** · no orders · no READY · job `w0815at-g2-signal-e2e` · codes `67580`/`83060` · as_of `2026-08-07T15:30:00+09:00` (**≠** W52) · **e2e_pass=true** · R2 `…/signals/` · logs [`.glm-logs/w0815at_g2_signal/`](../.glm-logs/w0815at_g2_signal/)  
**Smokes / FRESH (G3):** [`.glm-logs/w0815at_g3_ops/`](../.glm-logs/w0815at_g3_ops/) · T8 bars×short_sale_report **pass** · T9 FRESH reclock `projgen-d2cc11b67ad84724afaffbe4c000b59c` · T10 freeze pytest **84** (pre-G1 expand)  
**Catalog:** [`docs/proof/complete21_min_feature_catalog_20260815.md`](proof/complete21_min_feature_catalog_20260815.md) (code SoT = `complete21_min.py` **5 approved / 5 candidate**)  
**Unit tests (merge):** features + permanent_defer + single_shot + mass gate · **87 passed**  
**Prior W52 approved/シグナル下地:** § approved/シグナル下地 held underneath · W51 feature E2E · W50 usage E2E · W49 deepen · W48 groundwork · coverage baseline **W47 FINAL** held

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 O2強化・再評価（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** |
| Mass | **NO-GO / OFF** (signal 2nd E2E Mass **OFF**) |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave |
| empty COMPLETE | **0** (remote verify G4 + G5 re-verify) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| COMPLETE segs | **3478** (remote verify held · Δ0) |
| OTC tip island | **93** held |
| permanent DEFER | **5** held |
| tip densify | **SKIP** (T12 · not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `664c88e0821c12fc7a85ad04434e8a0b19737873` (G5 FINAL merge) · PRE_sha `b6dc56a7ec771c1408a5477c7857752da4856dcf` |
| Projection | **FRESH** `projgen-d2cc11b67ad84724afaffbe4c000b59c` (peer G3 T9 ops_reeval_freshness; residual FRESH sync; publish apply **SKIP** no segment drift; fail-closed no force) |
| O2 feature E2E | G1 **PASS** — tip FeatureContext → R2 for `topix_relative_1d` · `disclosure_flag_fins` · `margin_interest_change_1d` (margin Jul tip + PIT as_of) · Mass **not** connected |
| Promotion | **+3 this wave** → **5 approved** total · `topix_relative_1d` · `disclosure_flag_fins` · `margin_interest_change_1d` (+ W52 `volume_change_1d` · `is_trading_day`) · v**1.0.0** · remain **5 candidate** · no READY claim |
| Signal 2nd E2E | Mass **OFF** · `c21_topix_relative_sign@1.0.0` · status **candidate** · **candidate_only=False** · no order execution · R2 `…/signals/` · job `w0815at-g2-signal-e2e` |
| Unit tests | **87 passed** (complete21 min · permanent_defer · single_shot · mass gate) |
| raw_retention | **15915** (remote count at G4; not coverage primary; W46 tip secondary **15869** held) |

**Primary this phase:** O2 (CF tip feature-level E2E) 強化 + re-eval promotion (**+3**) + second tip **signal** E2E on held COMPLETE **21** / DEFER **5** — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON · treat signal as READY · force remaining 5 candidates.

### Explicit non-declarations (held)

- **READY** — not declared (O2強化・再評価 only; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF** (signal 2nd E2E Mass OFF)
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## approved/シグナル下地（READY 未宣言）

**Phase name:** COMPLETE 21 approved/シグナル下地（宣言なし）  
**Wave:** W52 / w0815as (T1–T12 · G5 FINAL merge + push)  
**Promotion/signal close proof:** [`docs/proof/w0815as_w52_promotion_signal_close_20260815.md`](proof/w0815as_w52_promotion_signal_close_20260815.md)  
**Ops / residual (G4):** [`.glm-logs/w0815as_g4_ops/`](../.glm-logs/w0815as_g4_ops/) · [`ops_snapshot.json`](../.glm-logs/w0815as_g4_ops/ops_snapshot.json) · [`switch_check.json`](../.glm-logs/w0815as_g4_ops/switch_check.json) · [`FINAL_metrics.json`](../.glm-logs/w0815as_g4_ops/FINAL_metrics.json)  
**Promotion (G1):** `packages/research_runtime/features/complete21_min.py` · **2 approved** at W52 close (cap max **2** · version pin **1.0.0**): `volume_change_1d` (`intended_role=signal`) · `is_trading_day` (`intended_role=utility`) · remain **8 candidate** at close · criteria [`docs/proof/complete21_feature_candidate_to_approved_criteria_20260815.md`](proof/complete21_feature_candidate_to_approved_criteria_20260815.md) · eval [`docs/proof/w0815as_w52_feature_promotion_eval_20260815.md`](proof/w0815as_w52_feature_promotion_eval_20260815.md) · **superseded** by W53 O2 +3 above  
**Signal E2E (G2):** `packages/research_runtime/features/minimal_signal.py` · signal `c21_topix_relative_sign@1.0.0` · `status=candidate` · **candidate_only=True** at W52 close · Mass **OFF** · no orders · no READY · single_shot path writes under `…/signals/` · job `w0815as-g2-signal-e2e` · proof [`docs/proof/w0815as_w52_signal_e2e_20260815.md`](proof/w0815as_w52_signal_e2e_20260815.md)  
**Smokes / FRESH (G3):** [`.glm-logs/w0815as_g3_ops/`](../.glm-logs/w0815as_g3_ops/) · T8 bars×short_ratio **pass** · T9 FRESH reclock `projgen-97e38cc4670f4003901a2ca3b1b0ba37` · T10 pytest **32**  
**Catalog:** [`docs/proof/complete21_min_feature_catalog_20260815.md`](proof/complete21_min_feature_catalog_20260815.md)  
**Unit tests (merge):** features + permanent_defer + single_shot + mass gate · **84 passed**  
**Prior W51 feature E2E:** § 特徴量込み E2E held underneath · W50 usage E2E · W49 deepen · W48 groundwork · coverage baseline **W47 FINAL** held

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 approved/シグナル下地（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** |
| Mass | **NO-GO / OFF** (signal E2E Mass **OFF**) |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave |
| empty COMPLETE | **0** (remote verify G4 + G5 re-verify) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| COMPLETE segs | **3478** (remote verify held · Δ0) |
| OTC tip island | **93** held |
| permanent DEFER | **5** held |
| tip densify | **SKIP** (T12 · not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `7f5f0051e9e5a114a01a74c73ba29a3fc90a669f` (G5 FINAL merge) · PRE_sha `816fed4d98e8ad6dbec26f0152a36e013f574167` |
| Projection | **FRESH** `projgen-97e38cc4670f4003901a2ca3b1b0ba37` (peer G3 T9 ops_reeval_freshness; residual FRESH sync; publish apply **SKIP** no segment drift; fail-closed no force) — **superseded** by W53 reclock above |
| Promotion | **2 approved** at W52 close (cap max **2**) · `volume_change_1d` · `is_trading_day` · v**1.0.0** · remain **8 candidate** at close · no READY claim |
| Signal E2E | Mass **OFF** · `c21_topix_relative_sign@1.0.0` · **candidate_only** at W52 · no order execution · R2 `…/signals/` |
| Unit tests | **84 passed** (complete21 min · permanent_defer · single_shot · mass gate) |
| raw_retention | **15915** (remote count at G4; not coverage primary; W46 tip secondary **15869** held) |

**Primary this phase:** candidate→**approved** promotion wave (max **2**) + minimal tip **signal** groundwork on held COMPLETE **21** / DEFER **5** — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON · promote >2 · treat signal as READY.

### Explicit non-declarations (held)

- **READY** — not declared (approved/シグナル下地 only; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF** (signal E2E Mass OFF)
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## 特徴量込み E2E（READY 未宣言）

**Phase name:** COMPLETE 21 特徴量込み E2E（宣言なし）  
**Wave:** W51 / w0815ar (T1–T12 · G5 FINAL merge + push)  
**Feature E2E close proof:** [`docs/proof/w0815ar_w51_feature_e2e_close_20260815.md`](proof/w0815ar_w51_feature_e2e_close_20260815.md)  
**Single-shot feature E2E proof:** [`docs/proof/w0815ar_w51_feature_e2e_20260815.md`](proof/w0815ar_w51_feature_e2e_20260815.md)  
**Single-shot feature E2E (G1):** [`.glm-logs/w0815ar_g1_e2e/`](../.glm-logs/w0815ar_g1_e2e/) · job `w0815ar-g1-e2e` · tip FeatureContext → candidate features → R2 `quant-structured` · **e2e_pass=true** · DEFER 5 fail-closed · READY **not** declared  
**Features expand (G2):** `packages/research_runtime/features/complete21_min.py` · **10** candidate features (W50 7 + expand 3: `return_1d_c21` · `margin_alert_flag` · `futures_activity_proxy`) · status=`candidate` · DEFER dataset_guard held · promotion **none**  
**Catalog:** [`docs/proof/complete21_min_feature_catalog_20260815.md`](proof/complete21_min_feature_catalog_20260815.md) · criteria draft [`docs/proof/complete21_feature_candidate_to_approved_criteria_20260815.md`](proof/complete21_feature_candidate_to_approved_criteria_20260815.md)  
**Smokes expand (G3):** [`.glm-logs/w0815ar_g3_smoke/`](../.glm-logs/w0815ar_g3_smoke/) · T8a bars×margin_alert · T8b bars×markets_breakdown · **all pass** · FRESH reclock T9  
**Ops / residual (G4):** [`.glm-logs/w0815ar_g4_ops/`](../.glm-logs/w0815ar_g4_ops/) · [`ops_snapshot.json`](../.glm-logs/w0815ar_g4_ops/ops_snapshot.json) · [`switch_check.json`](../.glm-logs/w0815ar_g4_ops/switch_check.json) · [`FINAL_metrics.json`](../.glm-logs/w0815ar_g4_ops/FINAL_metrics.json)  
**Unit tests (merge):** features + permanent_defer + single_shot + mass gate · **80 passed**  
**Prior W50 E2E:** § 利用準備 E2E held underneath · W49 deepen · W48 groundwork · coverage baseline **W47 FINAL** held

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 特徴量込み E2E（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** |
| Mass | **NO-GO / OFF** |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave |
| empty COMPLETE | **0** (remote verify held) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| COMPLETE segs | **3478** (remote verify held · Δ0) |
| OTC tip island | **93** held |
| permanent DEFER | **5** held |
| tip densify | **SKIP** (T12 · not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `8e64328f8f0513c2d9f1514256fec44be35ae020` (G5 FINAL merge) · PRE_sha `ea4a151fd3f2a9d4d40c3a967ea2e04ad89a3938` |
| Projection | **FRESH** `projgen-48993e3f05814d759576c01f65196041` (peer G3 T9 ops_reeval_freshness; G4 residual-only; publish apply **SKIP** no segment drift; fail-closed no force) |
| Single-shot features → R2 | G1 **PASS** — tip FeatureContext computes **3** default candidates (`volume_change_1d` · `is_trading_day` · `topix_relative_1d`) · R2 put ×4 (input_plan/result/**features**/manifest) · Mass **not** connected |
| Features catalog | **10** candidates · COMPLETE 21 only · status=`candidate` · no READY claim · no promotion |
| Smokes expand | G3 T8a/T8b **pass** · READY **not** declared |
| Unit tests | **80 passed** (complete21 min · permanent_defer · single_shot · mass gate) |
| raw_retention | **15892** (remote count at G4; not coverage primary) |

**Primary this phase:** single_shot **computes candidate features → R2** on held COMPLETE **21** / DEFER **5** baseline — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON · feature promotion to approved.

### Explicit non-declarations (held)

- **READY** — not declared (特徴量込み E2E only; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF**
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## 利用準備 E2E（READY 未宣言）

**Phase name:** COMPLETE 21 利用準備 E2E（宣言なし）  
**Wave:** W50 / w0815aq (T1–T12 · G5 FINAL merge + push)  
**Usage E2E proof:** [`docs/proof/w0815aq_w50_usage_e2e_20260815.md`](proof/w0815aq_w50_usage_e2e_20260815.md)  
**Single-shot CF E2E proof:** [`docs/proof/w0815aq_w50_single_shot_e2e_20260815.md`](proof/w0815aq_w50_single_shot_e2e_20260815.md)  
**Ops logs:** [`.glm-logs/w0815aq_g4_ops/`](../.glm-logs/w0815aq_g4_ops/) · [`ops_snapshot.json`](../.glm-logs/w0815aq_g4_ops/ops_snapshot.json) · [`switch_check.json`](../.glm-logs/w0815aq_g4_ops/switch_check.json) · [`FINAL_metrics.json`](../.glm-logs/w0815aq_g4_ops/FINAL_metrics.json)  
**Single-shot CF E2E (G1):** [`.glm-logs/w0815aq_g1_e2e/`](../.glm-logs/w0815aq_g1_e2e/) · job `w0815aq-g1-e2e` · D1 tip → R2 `quant-structured` · **e2e_pass=true** · DEFER 5 fail-closed  
**Smokes expand (G3):** [`.glm-logs/w0815aq_g3_smoke/`](../.glm-logs/w0815aq_g3_smoke/) · T8a bars×short_sale · T8b bars×investor_types · **all pass** · FRESH reclock peer T9  
**Features expand:** `packages/research_runtime/features/complete21_min.py` · **7** candidate features (W49 3 + expand 4: `margin_interest_change_1d` · `short_ratio_level` · `is_trading_day` · `repo_rate_level`) · DEFER dataset_guard held  
**Unit tests (merge):** features + permanent_defer + single_shot + mass gate · **56 passed**  
**Prior deepen:** W49 § 利用準備深化 held underneath · W48 § 利用準備フェーズ開始 held

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 利用準備 E2E（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** |
| Mass | **NO-GO / OFF** |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave |
| empty COMPLETE | **0** (remote verify held) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| COMPLETE segs | **3478** (remote verify held · Δ0) |
| OTC tip island | **93** held |
| tip densify | **SKIP** (T12 · not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `d0dad82592145f80da22c700c6336ffd0fcfa2fe` (G5 FINAL merge) · PRE_sha `dc2a70539665fa16306ea742c021f010b21ee223` |
| Projection | **FRESH** `projgen-0fb233bde5df4a8ca66b73bbbf78905d` (peer G3 T9 ops_reeval_freshness; G4 residual-only; publish apply **SKIP** no segment drift; fail-closed no force) |
| Single-shot CF E2E | G1 **PASS** — D1 tip extract + R2 put (input_plan/result/manifest) · Mass **not** connected |
| Features expand | **7** candidates · COMPLETE 21 only · status=`candidate` · no READY claim |
| Smokes expand | G3 T8a/T8b **pass** · READY **not** declared |
| Unit tests | **56 passed** (complete21 min · permanent_defer · single_shot · mass gate) |
| raw_retention | **15892** (remote count at G4; not coverage primary) |

**Primary this phase:** utilization-prep E2E on held coverage baseline — single_shot CF path · features expand · smokes expand — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON.

### Explicit non-declarations (held)

- **READY** — not declared (利用準備 E2E only; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF**
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## 利用準備深化（READY 未宣言）

**Phase name:** COMPLETE 21 利用準備深化（宣言なし）  
**Wave:** W49 / w0815ap (T1–T12 deepen · G5 FINAL merge + push)  
**Usage deepen proof:** [`docs/proof/w0815ap_w49_usage_deepen_20260815.md`](proof/w0815ap_w49_usage_deepen_20260815.md)  
**Ops logs:** [`.glm-logs/w0815ap_g4_ops/`](../.glm-logs/w0815ap_g4_ops/) · [`ops_snapshot.json`](../.glm-logs/w0815ap_g4_ops/ops_snapshot.json) · [`switch_check.json`](../.glm-logs/w0815ap_g4_ops/switch_check.json) · [`FINAL_metrics.json`](../.glm-logs/w0815ap_g4_ops/FINAL_metrics.json)  
**Smokes expanding:** [`.glm-logs/w0815ap_g1_smoke/`](../.glm-logs/w0815ap_g1_smoke/) · T1–T4 expanded tip PIT joins **4 pass**  
**Features skeleton:** [`docs/proof/complete21_min_feature_catalog_20260815.md`](proof/complete21_min_feature_catalog_20260815.md) · `packages/research_runtime/features/complete21_min.py` · `dataset_guard.py`  
**Single-shot job skeleton:** `packages/product/research/single_shot_job.py` · [`.glm-logs/w0815ap_g3_job/`](../.glm-logs/w0815ap_g3_job/) · Mass loop **not** connected  
**Unit tests (merge):** features + permanent_defer + single_shot + mass gate · **37 passed**  
**Prior W48 groundwork:** [`docs/proof/w0815ao_w48_usage_readiness_20260815.md`](proof/w0815ao_w48_usage_readiness_20260815.md) · residual § 利用準備フェーズ開始 held underneath

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 利用準備深化（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** |
| Mass | **NO-GO / OFF** |
| Phase7 | **OFF** (foundation / fail-closed only) — **reconfirmed** this wave |
| empty COMPLETE | **0** (remote verify held) |
| Dataset COMPLETE | **21** (remote verify held; not invent 22) |
| tip densify | **SKIP** (T12 · not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `c916c3271d8a07f988e89aa21b3ebaf46bf3cdae` (G5 FINAL merge) |
| Projection | **FRESH** `projgen-b47cea8b663f41c09b62e3324a4603a4` (ops_reeval_freshness T10 age large ~1535s; publish apply **SKIP** local==remote 3478; fail-closed no force) |
| Smokes expanding | G1 T1–T4 **4 pass** (bars×margin · bars×edinet_major · bars×tokyo_repo · fins_summary×dividend; READY **not** declared) |
| Features skeleton | COMPLETE 21 min catalog + `volume_change_1d` / `topix_relative_1d` / `disclosure_flag_fins` (candidate) + DEFER dataset_guard |
| Single-shot job | skeleton only · R2 path · Mass **not** connected · `single_shot_job.py` |
| Unit tests | **37 passed** (complete21 min · permanent_defer · single_shot · mass gate) |

**Primary this phase:** deepen utilization-prep on held coverage baseline — expanded smokes · features skeleton · single-shot job stub — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON.

### Explicit non-declarations (held)

- **READY** — not declared (利用準備深化 only; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF**
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## 利用準備フェーズ開始（READY 未宣言）

**Phase name:** COMPLETE 21 利用準備（宣言なし）  
**Wave:** W48 / w0815ao (T1–T10 FINAL merge)  
**Usage readiness proof:** [`docs/proof/w0815ao_w48_usage_readiness_20260815.md`](proof/w0815ao_w48_usage_readiness_20260815.md)  
**CF read paths + DEFER guard:** [`docs/proof/complete21_cf_read_paths_20260815.md`](proof/complete21_cf_read_paths_20260815.md)  
**Ops logs:** [`.glm-logs/w0815ao_g3_ops/`](../.glm-logs/w0815ao_g3_ops/) · [`ops_snapshot.json`](../.glm-logs/w0815ao_g3_ops/ops_snapshot.json) · [`switch_check.json`](../.glm-logs/w0815ao_g3_ops/switch_check.json) · smokes [`.glm-logs/w0815ao_g2_smoke/`](../.glm-logs/w0815ao_g2_smoke/)

| gate | status |
|------|--------|
| Phase name | **COMPLETE 21 利用準備（宣言なし）** |
| Coverage baseline FINAL | **held** (W47 FINAL · Dataset COMPLETE **21/26** · segs **3478** · **actionable_gap=0**) |
| READY | **未宣言 / not declared** |
| Mass | **NO-GO / OFF** |
| Phase7 | **OFF** (foundation / fail-closed only) |
| empty COMPLETE | **0** (remote verify held) |
| tip densify | **SKIP** (not primary this phase) |
| densify | **none** |
| push | **POST_PUSH_SHA** `7e504c63e4e70cb21c7315c8bcc1d59fb4e9a77a` |
| Projection | **FRESH** `projgen-17345de1e40b4aabb5496c18b22d3182` (ops_reeval_freshness; publish apply **SKIP** local==remote 3478) — **superseded** by W49 reclock above |
| G1 DEFER guard | `permanent_defer.py` + `QuantDataAccess` history fail-closed · tests **6 passed** |
| G2 smokes T4–T6 | **all pass** (tip PIT joins; READY **not** declared) |

**Primary this phase:** enter utilization-prep posture on held coverage baseline — **without** READY / Mass / Phase7 declaration.  
**Not:** densify · tip primary · invent COMPLETE 22 · Phase7 ON · READY GO · mass ON.

### Explicit non-declarations (held)

- **READY** — not declared (利用準備 only; no production READY GO)
- **Mass Autonomous Research** — **NO-GO / OFF**
- **Phase7** — **OFF** (no `PHASE7_*` / `MASS_RESEARCH_ENABLE` arming switch)

## W47 / w0815an — residual FINAL (coverage dense complete · gap 0 · no densify)

**Ops close proof:** [`docs/proof/w0815an_w47_baseline_ops_20260815.md`](proof/w0815an_w47_baseline_ops_20260815.md)  
**Usage notes:** [`docs/proof/coverage_baseline_21_usage_notes_20260815.md`](proof/coverage_baseline_21_usage_notes_20260815.md)  
**Machine twin:** [`.glm-logs/w0815an_g2_residual/BASELINE_W47.json`](../.glm-logs/w0815an_g2_residual/BASELINE_W47.json)  
**Live D1 (g1_ops POST):** COMPLETE segs **3478** · Dataset COMPLETE **21** · empty COMPLETE **0** · OTC **93** · **FRESH** `projgen-1a965a00414c4810b25ee77943d1a0f8` (reeval; age ~89s at capture) · PRE_sha `2bfd3ee7fbfe645f00a6bcec04f0bcf771804fc8` · pre-gen `projgen-f74d5496490141c8940d81317b8aaf7f`  
**Prior collect:** W46 tip secondary raw **15869** held · **no densify** this wave · **no tip collect** this wave · tip densify **SKIP**  
**Push:** **POST_PUSH_SHA** `2da6085f9c34804578b7438baf144ce23d99462b`
## Coverage baseline (W47 FINAL)
- Dataset COMPLETE: 21 / 26
- COMPLETE segs: 3478
- PARTIAL = 5 permanent DEFER only (no actionable gap)
- Mass/READY/Phase7: NO-GO/OFF
- Collect densify loops for coverage: ENDED (ops tip secondary only if ever)

**actionable_gap = 0** (W44 lock re-verified W45–W46; W47 residual FINAL)

| gate | status |
|------|--------|
| COMPLETE segs | **3478** held |
| Dataset COMPLETE | **21 / 26** held — **not** invent 22 |
| PARTIAL datasets | **5** = permanent DEFER only |
| **actionable_gap** | **= 0** (W44 lock re-verified W45–W46) |
| empty COMPLETE | **0** (ban held) |
| JSDA OTC tip island | **93** held · never dataset COMPLETE target |
| Permanent DEFER | **5** IDs (canonical table below) |
| NO_DENSIFY | **6** residual classes (same IDs; densify ban held) |
| Coverage densify loops | **ENDED** |
| Mass / READY / Phase7 | **NO-GO / OFF** |
| Floors / contract | **unchanged** — W38 + W42 mb **2015-04-01** still SoT · **not lowered** |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Projection | **FRESH** `projgen-1a965a00414c4810b25ee77943d1a0f8` (G1 ops reclock) |
| tip densify / tip collect | **SKIP** this wave |
| raw_retention (held) | **15869** (W46 tip secondary; not coverage primary) |

**Primary success:** coverage residual **FINAL** — Dataset COMPLETE **21** + COMPLETE segs **3478** + **actionable_gap = 0**.  
**Not:** densify-as-success · tip-as-primary · invent COMPLETE 22 · lower floors · Phase7 ON.

### Permanent DEFER + NO_DENSIFY (canonical — one place · W47 FINAL)

**Policy:** densify **FORBIDDEN** on all rows · empty-raw COMPLETE **forbidden** · invent COMPLETE **forbidden** · coverage densify loops **ENDED**.  
**NO_DENSIFY class count = 6** (PD-D2-MASTER splits PRE_PLAN + MISDATE). Permanent DEFER ID count = **5**.

| id | dataset | residual / n | residual_class | densify |
|----|---------|-------------:|----------------|---------|
| **PD-D2-MASTER** | `equities_master` | **94** (MISDATE 21 + PRE_PLAN 73) | MISDATE `2006-08…2008-04` + PRE_PLAN `2000-07…2006-07` | **FORBIDDEN** unless in-window Date raw |
| **PD-D4-EARN-CAL** | `equities_earnings_calendar` | **~199** | TIP_ONLY_VENDOR history | **FORBIDDEN** |
| **PD-D4-BARS-AM** | `equities_bars_daily_am` | **~31** | TIP_ONLY_VENDOR AM (`date_mode=today`) | **FORBIDDEN** |
| **PD-D5-JSDA-OTC** | `jsda_otc_bond_reference_prices` | archive beyond tip; tip island **93** | ARCHIVE_SITE_FAIL long-tail | **FORBIDDEN** archive densify · **never** dataset COMPLETE target |
| **PD-MX-EARN-TIP** | `fins_earnings_date` | **4** (`2026-01…04`) | NO_RAW_FOR_MONTH_TIP | **FORBIDDEN** · FINAL · **not** Dataset COMPLETE |

| # | permanent ref | residual_class | n | note |
|--:|---------------|----------------|--:|------|
| 1 | PD-D2-MASTER | PRE_PLAN | 73 | active NO_DENSIFY |
| 2 | PD-D2-MASTER | MISDATE | 21 | active NO_DENSIFY |
| 3 | PD-D4-BARS-AM | TIP_ONLY_VENDOR | 31 | active NO_DENSIFY |
| 4 | PD-D4-EARN-CAL | TIP_ONLY_VENDOR | 199 | active NO_DENSIFY |
| 5 | PD-D5-JSDA-OTC | ARCHIVE_SITE_FAIL | archive | active NO_DENSIFY · tip island 93 only |
| 6 | PD-MX-EARN-TIP | NO_RAW_FOR_MONTH_TIP | 4 | active NO_DENSIFY |

**Retry (summary only):** master → in-window Date raw; earn_cal/bars_am → vendor history API or catalog de-scope; OTC → FULL_OK day-by-day only (never COMPLETE); earn tip → vendor nz for `2026-01…04`. Full re-try prose: W44 lock [`.glm-logs/w0815ak_g2_defer/PERMANENT_DEFER_W44.json`](../.glm-logs/w0815ak_g2_defer/PERMANENT_DEFER_W44.json) · historical D1–D10 audit → §DEFER inventory (pointer).

### Dataset COMPLETE list (**21**) — held; includes `markets_breakdown`

`derivatives_bars_daily_futures` · `derivatives_bars_daily_options` · `derivatives_bars_daily_options_225` · `edinet_cross_shareholdings` · `edinet_large_volume_shareholders` · `edinet_major_shareholders` · `equities_bars_daily` · `equities_investor_types` · `fins_details` · `fins_dividend` · `fins_summary` · `indices_bars_daily` · `indices_bars_daily_topix` · `jsda_corporate_bond_transactions` · `jsda_tokyo_repo_rates` · **`markets_breakdown`** · `markets_calendar` · `markets_margin_alert` · `markets_margin_interest` · `markets_short_ratio` · `markets_short_sale_report`

### Residual PARTIAL after W47 (all non-actionable · permanent DEFER locked)

| dataset | PARTIAL n | disposition |
|---------|----------:|-------------|
| `equities_master` | **94** | permanent DEFER PD-D2-MASTER |
| `equities_earnings_calendar` | **199** | permanent DEFER PD-D4-EARN-CAL |
| `equities_bars_daily_am` | **31** | permanent DEFER PD-D4-BARS-AM |
| `jsda_otc_bond_reference_prices` | archive beyond tip | permanent DEFER PD-D5-JSDA-OTC (tip COMPLETE **93**) |
| `fins_earnings_date` | **4** | permanent DEFER PD-MX-EARN-TIP `2026-01…04` (**not** Dataset COMPLETE) |

## W46 / w0815am — continuous collect ops (JQ tip secondary + JSDA OTC probe + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815am_w46_collect_ops_20260815.md`](proof/w0815am_w46_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815am_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815am_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815am_g2_jsda/jsda_summary.json`](../.glm-logs/w0815am_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815am_g3_gap/SUMMARY.json`](../.glm-logs/w0815am_g3_gap/SUMMARY.json)

| gate | status |
|------|--------|
| COMPLETE segs | **3478 held (Δ0)** — **PRIMARY** |
| Dataset COMPLETE | **21 held** — **PRIMARY** (not invent 22) |
| raw_retention_manifests | **15816 → 15869 (+53)** — **SECONDARY** tip only |
| JSDA OTC | **93 held** · FULL_OK_NEW **0** · tip still **S260817** · residual holes **404** · CF probe (local TCP blocked) · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| Tip densify | **secondary** — raw **+53** · general 27p/0f @495 · fins 3p/0f @100 · 0×429 · seal **0** |
| Gap | actionable_n **0** · actionable_jq_n **0** · densify **none** · empty COMPLETE **0** · verdict GAP_HELD_NO_ACTIONABLE |
| Permanent DEFER | **5** held (W44 FINAL: PD-D2-MASTER · PD-D4-EARN-CAL · PD-D4-BARS-AM · PD-D5-JSDA-OTC · PD-MX-EARN-TIP) |
| NO_DENSIFY | **6** classes · densify ban **held** |
| Floors / contract | **unchanged** this wave (W38 + W42 mb **2015-04-01** still SoT) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-f74d5496490141c8940d81317b8aaf7f` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `f5e759e5cd49bca21b7eff9015828db9829b474b` |

**Primary success:** COMPLETE segs **Δ0** + Dataset COMPLETE **21** held.  
**Secondary only:** tip raw **+53** (→ **15869**). **OTC:** no new FULL_OK. **Not** tip-as-primary. **Not** densify-as-success. DEFER densify ban held.

### Residual PARTIAL after W46 (all non-actionable · permanent DEFER locked)

| dataset | PARTIAL n | disposition |
|---------|----------:|-------------|
| `equities_master` | **94** | permanent DEFER PD-D2-MASTER |
| `equities_earnings_calendar` | **199** | permanent DEFER PD-D4-EARN-CAL |
| `equities_bars_daily_am` | **31** | permanent DEFER PD-D4-BARS-AM |
| `jsda_otc_bond_reference_prices` | archive beyond tip | permanent DEFER PD-D5-JSDA-OTC (tip COMPLETE **93**) |
| `fins_earnings_date` | **4** | **FINAL** permanent DEFER PD-MX-EARN-TIP `2026-01…04` (**not** re-open densify; **not** Dataset COMPLETE) |

## W45 / w0815al — continuous collect ops (JQ tip secondary + JSDA OTC probe + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815al_w45_collect_ops_20260815.md`](proof/w0815al_w45_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815al_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815al_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815al_g2_jsda/jsda_summary.json`](../.glm-logs/w0815al_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815al_g3_gap/SUMMARY.json`](../.glm-logs/w0815al_g3_gap/SUMMARY.json)

| gate | status |
|------|--------|
| COMPLETE segs | **3478 held (Δ0)** — **PRIMARY** |
| Dataset COMPLETE | **21 held** — **PRIMARY** (not invent 22) |
| raw_retention_manifests | **15786 → 15816 (+30)** — **SECONDARY** tip only |
| JSDA OTC | **93 held** · FULL_OK_NEW **0** · tip still **S260817** · residual holes **404** · CF probe (local TCP blocked) · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| Tip densify | **secondary** — raw **+30** · general 27p/0f @495 · fins 3p/0f @100 · 0×429 · seal **0** |
| Gap | actionable_n **0** · actionable_jq_n **0** · densify **none** · empty COMPLETE **0** · verdict GAP_HELD_NO_ACTIONABLE |
| Permanent DEFER | **5** held (W44 FINAL: PD-D2-MASTER · PD-D4-EARN-CAL · PD-D4-BARS-AM · PD-D5-JSDA-OTC · PD-MX-EARN-TIP) |
| NO_DENSIFY | **6** classes · densify ban **held** |
| Floors / contract | **unchanged** this wave (W38 + W42 mb **2015-04-01** still SoT) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-df5c8d692bec4b8194719ceb4733e084` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `6989770038bd5badb93c92f8f2793dbc611f462c` |

**Primary success:** COMPLETE segs **Δ0** + Dataset COMPLETE **21** held.  
**Secondary only:** tip raw **+30** (→ **15816**). **OTC:** no new FULL_OK. **Not** tip-as-primary. **Not** densify-as-success. DEFER densify ban held.

### Residual PARTIAL after W45 (all non-actionable · permanent DEFER locked)

| dataset | PARTIAL n | disposition |
|---------|----------:|-------------|
| `equities_master` | **94** | permanent DEFER PD-D2-MASTER |
| `equities_earnings_calendar` | **199** | permanent DEFER PD-D4-EARN-CAL |
| `equities_bars_daily_am` | **31** | permanent DEFER PD-D4-BARS-AM |
| `jsda_otc_bond_reference_prices` | archive beyond tip | permanent DEFER PD-D5-JSDA-OTC (tip COMPLETE **93**) |
| `fins_earnings_date` | **4** | **FINAL** permanent DEFER PD-MX-EARN-TIP `2026-01…04` (**not** re-open densify; **not** Dataset COMPLETE) |

## W44 / w0815ak — permanent DEFER lock + earn tip4 FINAL (FINAL)

**Ops / residual proof:** [`docs/proof/w0815ak_w44_defer_lock_20260815.md`](proof/w0815ak_w44_defer_lock_20260815.md)  
**Machine:** earn tip4 [`.glm-logs/w0815ak_g1_earn/earn_tip4_final.json`](../.glm-logs/w0815ak_g1_earn/earn_tip4_final.json) · DEFER [`.glm-logs/w0815ak_g2_defer/PERMANENT_DEFER_W44.json`](../.glm-logs/w0815ak_g2_defer/PERMANENT_DEFER_W44.json) · NO_DENSIFY [`.glm-logs/w0815ak_g2_defer/NO_DENSIFY_W44.json`](../.glm-logs/w0815ak_g2_defer/NO_DENSIFY_W44.json) · ops [`.glm-logs/w0815ak_g3_ops/FINAL_metrics.json`](../.glm-logs/w0815ak_g3_ops/FINAL_metrics.json)

| gate | status |
|------|--------|
| COMPLETE segs | **3478 held** |
| Dataset COMPLETE | **21 held** — **not** invent 22 |
| JSDA OTC | **93 held** (tip island; archive still DEFER) |
| empty COMPLETE | **0** (ban held) |
| T1 fins_earnings_date tip4 | **FINAL permanent DEFER** all **4** PD-MX-EARN-TIP · sealed_n **0** · defer_n **4** · NO_RAW_FOR_MONTH · densify **0** · **not** re-open densify · **not** Dataset COMPLETE |
| Permanent DEFER | **5** locked (PD-D2-MASTER · PD-D4-EARN-CAL · PD-D4-BARS-AM · PD-D5-JSDA-OTC · PD-MX-EARN-TIP) |
| NO_DENSIFY | **6** active classes aligned |
| Floors / contract | **unchanged** this wave (W38 + W42 mb **2015-04-01** still SoT) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-7c2404dd29644aa4bc4e00675fc1f288` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `19ee21f892542500de9bf8fcef0887c3716489dd` |

**Primary success:** residual **FINAL permanent DEFER lock** (earn tip4 + master / bars_am / earn_cal / otc long-tail). Metrics **held**. **Not** densify-as-success. **Not** tip-as-primary. **Not** invent COMPLETE 22.

**Secondary only (not W44 primary):** W43 tip collect raw **+30** · complete_segs **Δ0**.

### Dataset COMPLETE list (**21**) — held; includes `markets_breakdown`

`derivatives_bars_daily_futures` · `derivatives_bars_daily_options` · `derivatives_bars_daily_options_225` · `edinet_cross_shareholdings` · `edinet_large_volume_shareholders` · `edinet_major_shareholders` · `equities_bars_daily` · `equities_investor_types` · `fins_details` · `fins_dividend` · `fins_summary` · `indices_bars_daily` · `indices_bars_daily_topix` · `jsda_corporate_bond_transactions` · `jsda_tokyo_repo_rates` · **`markets_breakdown`** · `markets_calendar` · `markets_margin_alert` · `markets_margin_interest` · `markets_short_ratio` · `markets_short_sale_report`

### Residual PARTIAL after W44 (all non-actionable · permanent DEFER locked)

| dataset | PARTIAL n | disposition |
|---------|----------:|-------------|
| `equities_master` | **94** | permanent DEFER PD-D2-MASTER |
| `equities_earnings_calendar` | **199** | permanent DEFER PD-D4-EARN-CAL |
| `equities_bars_daily_am` | **31** | permanent DEFER PD-D4-BARS-AM |
| `jsda_otc_bond_reference_prices` | archive beyond tip | permanent DEFER PD-D5-JSDA-OTC (tip COMPLETE **93**) |
| `fins_earnings_date` | **4** | **FINAL** permanent DEFER PD-MX-EARN-TIP `2026-01…04` (**not** re-open densify; **not** Dataset COMPLETE) |

### Permanent DEFER + NO_DENSIFY (W44 lock — superseded canonical)

**Canonical (one place):** → **§W47 Permanent DEFER + NO_DENSIFY**.  
W44 was the lock wave that FINALIZED PD-MX-EARN-TIP + reaffirmed the other four; machine drafts [`.glm-logs/w0815ak_g2_defer/PERMANENT_DEFER_W44.json`](../.glm-logs/w0815ak_g2_defer/PERMANENT_DEFER_W44.json) · [`NO_DENSIFY_W44.json`](../.glm-logs/w0815ak_g2_defer/NO_DENSIFY_W44.json). Duplicate long tables collapsed at W47.

## W42 / w0815ai — residual close (mb floor + tip4 DEFER + OTC absorb) (FINAL)

**Ops / residual proof:** [`docs/proof/w0815ai_w42_close_20260815.md`](proof/w0815ai_w42_close_20260815.md)  
**Machine:** mb [`.glm-logs/w0815ai_g1_mb/`](../.glm-logs/w0815ai_g1_mb/) · earn tip4 [`.glm-logs/w0815ai_g2_earn/`](../.glm-logs/w0815ai_g2_earn/) · DEFER [`.glm-logs/w0815ai_g3_defer/PERMANENT_DEFER_W42.json`](../.glm-logs/w0815ai_g3_defer/PERMANENT_DEFER_W42.json) · OTC absorb [`.glm-logs/w0815ai_g4_ops/`](../.glm-logs/w0815ai_g4_ops/) · T11 [`.glm-logs/w0815ai_g6_close/`](../.glm-logs/w0815ai_g6_close/)

| gate | status |
|------|--------|
| COMPLETE segs | **3478 held** (T6 absorb **3461→3478 Δ+17** from W41 OTC seals) |
| Dataset COMPLETE | **20 → 21 (+1)** — **PRIMARY** (`markets_breakdown` via floor **2015-04-01**) |
| JSDA OTC | **93 held** (T6 remote **76→93 +17**; tip island; archive still DEFER) |
| T1 mb `2015-03` | **FLOOR_RAISE_TO_2015_04** · OOS PARTIAL prune · seal **0** · dataset **COMPLETE** |
| T2 fins_earnings_date tip4 | all **4 PERMANENT DEFER** PD-MX-EARN-TIP · NO_RAW_FOR_MONTH · densify **0** · **not** Dataset COMPLETE |
| Permanent DEFER | **5** locked (PD-D2-MASTER · PD-D4-EARN-CAL · PD-D4-BARS-AM · PD-D5-JSDA-OTC · PD-MX-EARN-TIP) |
| Floors / contract | mb floor raise only (`089144c`); W38 other floors still SoT |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-9c224abe0e164223b39395020d7e5116` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `7d97b67bc9b74aa241df63c8d0ad9a1bf51f5384` |

**Primary success:** Dataset COMPLETE **+1** (`markets_breakdown`). **Absorb:** OTC **+17** / COMPLETE segs **+17** (W41). **Not** densify-as-success. **Not** tip-as-primary.

### Dataset COMPLETE list (**21**) — includes `markets_breakdown`

`derivatives_bars_daily_futures` · `derivatives_bars_daily_options` · `derivatives_bars_daily_options_225` · `edinet_cross_shareholdings` · `edinet_large_volume_shareholders` · `edinet_major_shareholders` · `equities_bars_daily` · `equities_investor_types` · `fins_details` · `fins_dividend` · `fins_summary` · `indices_bars_daily` · `indices_bars_daily_topix` · `jsda_corporate_bond_transactions` · `jsda_tokyo_repo_rates` · **`markets_breakdown`** · `markets_calendar` · `markets_margin_alert` · `markets_margin_interest` · `markets_short_ratio` · `markets_short_sale_report`

### Residual PARTIAL after W42 (all non-actionable)

| dataset | PARTIAL n | disposition |
|---------|----------:|-------------|
| `equities_master` | **94** | permanent DEFER PD-D2-MASTER |
| `equities_earnings_calendar` | **199** | permanent DEFER PD-D4-EARN-CAL |
| `equities_bars_daily_am` | **31** | permanent DEFER PD-D4-BARS-AM |
| `jsda_otc_bond_reference_prices` | archive beyond tip | permanent DEFER PD-D5-JSDA-OTC (tip COMPLETE **93**) |
| `fins_earnings_date` | **4** | permanent DEFER PD-MX-EARN-TIP `2026-01…04` (**not** Dataset COMPLETE) |

### Permanent DEFER list (W42 lock) — pointer

Five IDs locked (PD-D2-MASTER · PD-D4-EARN-CAL · PD-D4-BARS-AM · PD-D5-JSDA-OTC · PD-MX-EARN-TIP). **Canonical table:** → **§W47 Permanent DEFER + NO_DENSIFY**. Machine: [`.glm-logs/w0815ai_g3_defer/PERMANENT_DEFER_W42.json`](../.glm-logs/w0815ai_g3_defer/PERMANENT_DEFER_W42.json).

## W41 / w0815ah — continuous collect ops (JSDA OTC PRIMARY + JQ tip secondary + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815ah_w41_collect_ops_20260815.md`](proof/w0815ah_w41_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815ah_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815ah_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815ah_g2_jsda/jsda_summary.json`](../.glm-logs/w0815ah_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815ah_g3_gap/SUMMARY.json`](../.glm-logs/w0815ah_g3_gap/SUMMARY.json) · ops [`.glm-logs/w0815ah_ops/POST_remote.json`](../.glm-logs/w0815ah_ops/POST_remote.json)

| gate | status |
|------|--------|
| COMPLETE segs | **3461 → 3478 (Δ+17)** — **PRIMARY** (OTC residual seals) |
| Dataset COMPLETE | **20 held** — **PRIMARY** (W38 contract still SoT; OTC still PARTIAL dataset-level) |
| JSDA OTC | **76→93 (+17)** — **PRIMARY / HIGHLIGHT** · FULL_OK_NEW **17** S260401…S260423 weekdays · R2 put 17/17 OK · tip still S260817 · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| Tip densify | **secondary** — raw **15703→15750 (+47)** · general 27p/0f @495 · fins 3p/0f @100 · 0×429 · seal **0** |
| Gap | actionable_n **0** · actionable_jq_n **0** · densify **none** · empty COMPLETE **0** · verdict GAP_HELD_NO_ACTIONABLE |
| mb 2015-03 | **held** DEFER_thin_partial_month · densify **not** re-run |
| Permanent DEFER | **5** held (PD-D2-MASTER · PD-D4-EARN-CAL · PD-D4-BARS-AM · PD-D5-JSDA-OTC · PD-MX-EARN-TIP) |
| Floors / contract | **unchanged** this wave (W38 `ba3c811` still SoT) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-56113e9f4ca54796b9fc547a3f2ac8c6` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `7960e193c929c9df2bfa63b5adcb6dcff32dd90d` |

**Primary success:** COMPLETE segs **+17** (OTC FULL_OK_NEW residual Apr weekdays) + Dataset COMPLETE held 20.  
**Highlight:** OTC **76→93**. **Secondary only:** tip raw +47. **Not** tip-as-primary. **Not** densify-as-success.

### Residual PARTIAL after W41 (all non-actionable)

| dataset | PARTIAL n | disposition |
|---------|----------:|-------------|
| `equities_master` | **94** | permanent DEFER PD-D2-MASTER |
| `equities_earnings_calendar` | **199** | permanent DEFER PD-D4-EARN-CAL |
| `equities_bars_daily_am` | **31** | permanent DEFER PD-D4-BARS-AM |
| `jsda_otc_bond_reference_prices` | **8688** | permanent DEFER PD-D5-JSDA-OTC (tip COMPLETE **93**; was 8705/76) |
| `fins_earnings_date` | **4** | permanent DEFER PD-MX-EARN-TIP `2026-01…04` |
| `markets_breakdown` | **1** | **DEFER_thin_partial_month** `2015-03` (W39 densify once rows=0; first full COMPLETE **2015-04**) |

## W40 / w0815ag — continuous collect ops (JQ tip + JSDA OTC seal + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815ag_w40_collect_ops_20260815.md`](proof/w0815ag_w40_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815ag_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815ag_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815ag_g2_jsda/jsda_summary.json`](../.glm-logs/w0815ag_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815ag_g3_gap/SUMMARY.json`](../.glm-logs/w0815ag_g3_gap/SUMMARY.json) · ops [`.glm-logs/w0815ag_ops/POST_remote.json`](../.glm-logs/w0815ag_ops/POST_remote.json)

| gate | status |
|------|--------|
| COMPLETE segs | **3457 → 3461 (Δ+4)** — **PRIMARY** (OTC residual seals) |
| Dataset COMPLETE | **20 held** — **PRIMARY** (W38 contract still SoT; OTC still PARTIAL dataset-level) |
| JSDA OTC | **72→76 (+4)** — **HIGHLIGHT** · FULL_OK_NEW **4** S260424/427/428/430 · R2 put OK · tip still S260817 · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| Tip densify | **secondary** — raw **15673→15703 (+30)** · general 27p/0f @495 · fins 3p/0f @100 · 0×429 · seal **0** |
| Gap | actionable_n **0** · densify **none** · empty COMPLETE **0** · verdict GAP_HELD_NO_ACTIONABLE |
| mb 2015-03 | **held** DEFER_thin_partial_month · densify **not** re-run |
| Permanent DEFER | **5** held (PD-D2-MASTER · PD-D4-EARN-CAL · PD-D4-BARS-AM · PD-D5-JSDA-OTC · PD-MX-EARN-TIP) |
| Floors / contract | **unchanged** this wave (W38 `ba3c811` still SoT) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-c362f07dd19f494ab798c6aca2aa3a93` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `924ca1895b4734e7bd0d828aa634a136fcdf08c2` |

**Primary success:** COMPLETE segs **+4** (OTC FULL_OK_NEW residual) + Dataset COMPLETE held 20.  
**Highlight:** OTC **72→76**. **Secondary only:** tip raw +30. **Not** tip-as-primary. **Not** densify-as-success.

### Residual PARTIAL after W40 (all non-actionable)

| dataset | PARTIAL n | disposition |
|---------|----------:|-------------|
| `equities_master` | **94** | permanent DEFER PD-D2-MASTER |
| `equities_earnings_calendar` | **199** | permanent DEFER PD-D4-EARN-CAL |
| `equities_bars_daily_am` | **31** | permanent DEFER PD-D4-BARS-AM |
| `jsda_otc_bond_reference_prices` | **8705** | permanent DEFER PD-D5-JSDA-OTC (tip COMPLETE **76**; was 8709/72) |
| `fins_earnings_date` | **4** | permanent DEFER PD-MX-EARN-TIP `2026-01…04` |
| `markets_breakdown` | **1** | **DEFER_thin_partial_month** `2015-03` (W39 densify once rows=0; first full COMPLETE **2015-04**) |

## W39 / w0815af — continuous collect ops (JQ tip + JSDA/MB + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815af_w39_collect_ops_20260815.md`](proof/w0815af_w39_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815af_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815af_g1_tip/FINAL_metrics.json) · JSDA+MB [`.glm-logs/w0815af_g2_jsda_mb/jsda_summary.json`](../.glm-logs/w0815af_g2_jsda_mb/jsda_summary.json) · gap [`.glm-logs/w0815af_g3_gap/SUMMARY.json`](../.glm-logs/w0815af_g3_gap/SUMMARY.json)

| gate | status |
|------|--------|
| COMPLETE segs | **3457 → 3457 (Δ0)** — **PRIMARY** |
| Dataset COMPLETE | **20 held** — **PRIMARY** (W38 contract still SoT) |
| Tip densify | **secondary** — raw **15642→15673 (+31)** · general 27p/0f @495 · fins 3p/0f @100 · 0×429 · seal **0** |
| JSDA OTC | **72→72** · FULL_OK_NEW **0** · S260817 refetch only · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| mb 2015-03 | densify once rows=**0** → **DEFER_thin_partial_month** · HAS_RAW_SEALABLE **false** · seal **0** |
| Gap | actionable_n **0** · densify **none** · empty COMPLETE **0** · verdict GAP_HELD_NO_ACTIONABLE |
| Permanent DEFER | **5** held (PD-D2-MASTER · PD-D4-EARN-CAL · PD-D4-BARS-AM · PD-D5-JSDA-OTC · PD-MX-EARN-TIP) |
| Floors / contract | **unchanged** this wave (W38 `ba3c811` still SoT) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-870c78f492424ab6a93267adf5d37375` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `2e436bfcb2ec1759b6bfb32727a98ea3d5fbf3cd` |

**Primary success:** COMPLETE segs Δ0 + Dataset COMPLETE held 20.  
**Secondary only:** tip raw +31. **Not** tip-as-primary. **Not** densify-as-success.

### Residual PARTIAL after W39 (unchanged set; all non-actionable)

| dataset | PARTIAL n | disposition |
|---------|----------:|-------------|
| `equities_master` | **94** | permanent DEFER PD-D2-MASTER |
| `equities_earnings_calendar` | **199** | permanent DEFER PD-D4-EARN-CAL |
| `equities_bars_daily_am` | **31** | permanent DEFER PD-D4-BARS-AM |
| `jsda_otc_bond_reference_prices` | **8709** | permanent DEFER PD-D5-JSDA-OTC (tip COMPLETE **72**) |
| `fins_earnings_date` | **4** | permanent DEFER PD-MX-EARN-TIP `2026-01…04` |
| `markets_breakdown` | **1** | **DEFER_thin_partial_month** `2015-03` (W39 densify once rows=0; first full COMPLETE **2015-04**) |

## W38 / w0815ae — contract floor raise + residual DEFER re-align + reeval (FINAL)

**Contract commit:** `ba3c81157c1528784e4909ca7e03e7c8076553c2` — `contract(w0815ae/W38): raise history_target_start to proven observed floors` (**11** raises)  
**Residual DEFER docs:** `ddbd823af28953bea659adfa970dd7301b81e3e3`  
**Floor catalog (evidence):** [`docs/proof/observed_floor_catalog_20260815.md`](proof/observed_floor_catalog_20260815.md)  
**Contract review proof (FINAL):** [`docs/proof/w0815ae_w38_contract_floor_raise_20260815.md`](proof/w0815ae_w38_contract_floor_raise_20260815.md)  
**Machine:** [`.glm-logs/w0815ae_defer/PERMANENT_DEFER.json`](../.glm-logs/w0815ae_defer/PERMANENT_DEFER.json) · [`.glm-logs/w0815ae_defer/NO_DENSIFY_AFTER_CONTRACT_DRAFT.json`](../.glm-logs/w0815ae_defer/NO_DENSIFY_AFTER_CONTRACT_DRAFT.json) · [`.glm-logs/w0815ae_contract/contract_diff.json`](../.glm-logs/w0815ae_contract/contract_diff.json) · [`.glm-logs/w0815ae_reeval/REEVAL_DELTA.json`](../.glm-logs/w0815ae_reeval/REEVAL_DELTA.json)

| gate | status |
|------|--------|
| Contract floors | **applied** — **11** `history_target_start` raises to proven observed floors (`ba3c811`) |
| Floor catalog | **linked** — [`observed_floor_catalog_20260815.md`](proof/observed_floor_catalog_20260815.md) (W29 evidence; W38 implements catalog §2 candidates minus master) |
| NO_DENSIFY re-align | **18 → 6** active required-window classes (**12** OUT_OF_SCOPE after raise) |
| Permanent DEFER | **5** entries (D2 master · D4 earn_cal · D4 bars_am · D5 OTC archive · MX-EARN-TIP) |
| densify | **none** (no densify this wave; permanent DEFER densify forbidden) |
| tip densify | **not primary** (T7 held) — no tip collect loop this wave |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| COMPLETE segs | **3457 → 3457 (Δ0)** |
| Dataset COMPLETE | **11 → 20 (+9)** |
| empty COMPLETE | **0 → 0** (ban held) |
| raw_retention_manifests | **not remeasured** (no tip collect; held W36 **15589**) |
| Projection | **FRESH** `projgen-c54a409aaeef424e9c13394b82bd720b` |
| Push | **POST_PUSH_SHA** `afd7189647331de2d977f3ce2018ca34135bb5c1` |

### history_target_start raises (old → new)

Proven-floor raises landed in `packages/data_plane/data_contracts/collection_coverage.json` (+ aligned copies). Evidence: catalog §1 + contract_diff.

| dataset | old `history_target_start` | new `history_target_start` | pre-floor residual cured (OOS) | catalog / defer |
|---------|---------------------------:|---------------------------:|--------------------------------|-----------------|
| `equities_bars_daily` | 2004-01-05 | **2008-05-01** | 52 segs (31 NO_RAW + 21 EMPTY) `2004-01…2008-04` | D7 · catalog |
| `indices_bars_daily_topix` | 2008-01-01 | **2008-05-01** | 4 empty shells `2008-01…04` | D1 · catalog |
| `indices_bars_daily` | 2008-01-01 | **2008-05-01** | 4 empty / missing receipt `2008-01…04` | D1 · catalog |
| `fins_summary` | 2008-01-08 | **2008-07-01** | 6 empty shells `2008-01…06` | D10 · catalog |
| `fins_dividend` | 2008-01-08 | **2013-02-01** | 61 EMPTY_SHELL `2008-01…2013-01` | MX-DIV · catalog |
| `fins_details` | 2008-01-08 | **2018-01-01** | 120 PRE2018 empty `2008-01…2017-12` | MX-DET · catalog |
| `fins_earnings_date` | 2010-01-04 | **2018-01-01** | 96 NO_RAW pre-floor `2010-01…2017-12` (**tip 2026-01…04 still DEFER**) | MX-EARN-PRE OOS · MX-EARN-TIP survives |
| `markets_breakdown` | 2013-01-04 | **2015-03-26** | 27 segs pre-source-floor `2013-01…2015-03` | D3 · catalog |
| `markets_short_sale_report` | 2013-01-04 | **2013-11-01** | 10 empty shells `2013-01…10` | D9 · catalog |
| `edinet_cross_shareholdings` | 2018-01-04 | **2020-05-01** | 28 empty pre-island `2018-01…2020-04` | D6 · catalog |
| `edinet_large_volume_shareholders` | 2018-01-04 | **2021-07-01** | 42 empty pre-island `2018-01…2021-06` | D6 · catalog |

**Explicitly not raised (4):**

| dataset | keep `history_target_start` | reason |
|---------|----------------------------:|--------|
| `equities_master` | 2000-07-13 | D2 MISDATE not always-empty; permanent DEFER |
| `equities_earnings_calendar` | 2010-01-04 | D4 tip-only; catalog de-scope ≠ floor raise |
| `equities_bars_daily_am` | 2024-01-04 | D4 tip-only AM `date_mode=today` |
| `jsda_otc_bond_reference_prices` | 2002-08-02 | D5 archive site capability; do **not** raise to tip island |

Aligned copies (same raise set): `canonical_datasets.json#historical_start` · `coverage.py#EXPECTED_START` · `range_batch_scheduler.py#TRACK_A_FOCUS_RANGES`.

### NO_DENSIFY re-align (after contract)

W29 lock had **18** never-densify residual classes. After W38 floor raises:

```
W29 NO_DENSIFY 18 classes
  ├─ OUT_OF_SCOPE (12)  — pre-floor residual entirely before new history_target_start
  │    D1×2, D3, D6×2, D7×2, D9, D10, MX-DIV, MX-DET, MX-EARN-PRE
  └─ STILL_DEFER (6)    — required-window residual remains (active NO_DENSIFY)
       D2×2 master, D4×2 earn/am, D5 OTC archive, MX-EARN-TIP
```

**Check:** 12 + 6 = 18.

#### OUT_OF_SCOPE after raise (archive note only — densify never required)

Pre-floor residual falls **strictly before** new `history_target_start`. Not a required-window densify/DEFER gate target. PARTIAL rows may remain in D1 inventory until human-gate prune/reagg — densify still **forbidden**; empty-raw COMPLETE still **forbidden**.

| DEFER id | dataset | residual class / span | n | new floor | disposition |
|----------|---------|----------------------|--:|----------:|-------------|
| **D1** | `indices_bars_daily_topix` | EMPTY_SHELL `2008-01…04` | 4 | 2008-05-01 | **OUT_OF_SCOPE** |
| **D1** | `indices_bars_daily` | EMPTY/missing receipt `2008-01…04` | 4 | 2008-05-01 | **OUT_OF_SCOPE** |
| **D3** | `markets_breakdown` | EMPTY_PRE_SOURCE_FLOOR `2013-01…2015-03` | 27 | 2015-03-26 | **OUT_OF_SCOPE** |
| **D6** | `edinet_cross_shareholdings` | EMPTY_PRE_ISLAND `2018-01…2020-04` | 28 | 2020-05-01 | **OUT_OF_SCOPE** |
| **D6** | `edinet_large_volume_shareholders` | EMPTY_PRE_ISLAND `2018-01…2021-06` | 42 | 2021-07-01 | **OUT_OF_SCOPE** |
| **D7** | `equities_bars_daily` | NO_RAW_OOS `2004-01…2006-07` | 31 | 2008-05-01 | **OUT_OF_SCOPE** |
| **D7** | `equities_bars_daily` | EMPTY_UNDER_SUBSCRIPTION `2006-08…2008-04` | 21 | 2008-05-01 | **OUT_OF_SCOPE** |
| **D9** | `markets_short_sale_report` | EMPTY_PRE_HISTORY `2013-01…10` | 10 | 2013-11-01 | **OUT_OF_SCOPE** |
| **D10** | `fins_summary` | EMPTY_PRE_HISTORY `2008-01…06` | 6 | 2008-07-01 | **OUT_OF_SCOPE** |
| **MX-DIV** | `fins_dividend` | EMPTY_SHELL `2008-01…2013-01` | 61 | 2013-02-01 | **OUT_OF_SCOPE** |
| **MX-DET** | `fins_details` | DEFER_PRE2018_EMPTY `2008-01…2017-12` | 120 | 2018-01-01 | **OUT_OF_SCOPE** |
| **MX-EARN-PRE** | `fins_earnings_date` | NO_RAW_FOR_MONTH_PRE_FLOOR `2010-01…2017-12` | 96 | 2018-01-01 | **OUT_OF_SCOPE** |

#### STILL_DEFER within required window (active NO_DENSIFY — **6** classes)

| DEFER id | dataset | residual class / span | n | floor after W38 | permanent ref |
|----------|---------|----------------------|--:|-----------------|---------------|
| **D2** | `equities_master` | PRE_PLAN `2000-07…2006-07` | 73 | 2000-07-13 (unchanged) | PD-D2-MASTER |
| **D2** | `equities_master` | MISDATE `2006-08…2008-04` | 21 | 2000-07-13 (unchanged) | PD-D2-MASTER |
| **D4** | `equities_earnings_calendar` | TIP_ONLY_VENDOR history residual | ~199 | 2010-01-04 (unchanged) | PD-D4-EARN-CAL |
| **D4** | `equities_bars_daily_am` | TIP_ONLY_VENDOR history residual | ~31 | 2024-01-04 (unchanged) | PD-D4-BARS-AM |
| **D5** | `jsda_otc_bond_reference_prices` | ARCHIVE_SITE_FAIL beyond tip COMPLETE **72** | archive | 2002-08-02 (unchanged) | PD-D5-JSDA-OTC |
| **MX-EARN-TIP** | `fins_earnings_date` | NO_RAW_FOR_MONTH_TIP `2026-01…04` | 4 | 2018-01-01 (**raised**; tip holes remain inside window) | PD-MX-EARN-TIP |

**Policy held:** empty-raw COMPLETE **forbidden** · tip densify **not primary** this wave (T7 held; secondary only on non-DEFER tip holes in collect waves) · Mass/READY/Phase7 **NO-GO/OFF** · CF-SoT D1 hot tip / R2 history / receipt-owned COMPLETE · D8 Batch Z **OFF** (not a densify class).

### Permanent DEFER list (will not be cured by floor raise this wave)

Definition: residual class with **no honest floor-raise cure** this wave (or tip residual that **survives** a raise). Densify remains **forbidden**.

| id | DEFER | dataset(s) | class / span | why permanent | retry condition |
|----|-------|------------|--------------|---------------|-----------------|
| **PD-D2-MASTER** | D2 | `equities_master` | MISDATE `2006-08…2008-04` (n=21) + PRE_PLAN `2000-07…2006-07` (n=73) | Tip-misdated Date (`~2008-05-07`); not always-empty product window; raising floor would invent COMPLETE without vendor fix | Fresh R2 with **in-scope Date** + window_ok seal path; no invent COMPLETE |
| **PD-D4-EARN-CAL** | D4 | `equities_earnings_calendar` | TIP_ONLY history (~199) | Vendor next-bday / tip-dated only; history de-scope is catalog change, not floor bump | Vendor historical range API **or** catalog de-scope; prefer `fins_earnings_date` for event history |
| **PD-D4-BARS-AM** | D4 | `equities_bars_daily_am` | TIP_ONLY history (~31) | `date_mode=today` AM session — not historical OHLC | Vendor historical AM API **or** use `equities_bars_daily` / catalog de-scope |
| **PD-D5-JSDA-OTC** | D5 | `jsda_otc_bond_reference_prices` | ARCHIVE beyond tip **72** | Site capability (timeout/404/403); do **not** raise to tip island | JSDA HTTP **200** full CSV **and** R2 raw for target day → seal day-by-day |
| **PD-MX-EARN-TIP** | MX-EARN-TIP | `fins_earnings_date` | tip holes `2026-01…04` (n=4) | Floor raise → `2018-01-01` clears **pre-floor only**; tip known-empty stays required-window DEFER | Vendor nz for tip residual months; no densify-as-success |

**Evidence:** [`PERMANENT_DEFER.json`](../.glm-logs/w0815ae_defer/PERMANENT_DEFER.json) · catalog §1 / §2 do-not-raise · master/earn/am/otc proofs under `docs/proof/w0815*`.

### Reeval POST metrics (live verified)

Source: [`.glm-logs/w0815ae_reeval/REEVAL_DELTA.json`](../.glm-logs/w0815ae_reeval/REEVAL_DELTA.json) · PRE `06:04:54Z` · POST `06:11:48Z`.

| Metric | PRE | POST | Δ |
|--------|----:|-----:|--:|
| COMPLETE segs | **3457** | **3457** | **0** |
| Dataset COMPLETE | **11** | **20** | **+9** |
| empty COMPLETE | **0** | **0** | held |
| FRESH | (W36 prior) | `projgen-c54a409aaeef424e9c13394b82bd720b` | reclocked |
| raw_retention_manifests | **15589** (W36) | **not remeasured** | no tip collect |

**Flipped to Dataset COMPLETE (+9):** `equities_bars_daily` · `indices_bars_daily` · `indices_bars_daily_topix` · `fins_summary` · `fins_dividend` · `fins_details` · `markets_short_sale_report` · `edinet_cross_shareholdings` · `edinet_large_volume_shareholders`.

**Still PARTIAL (6):** master **94** · earn_cal **199** · bars_am **31** · otc **8709** · fins_earnings_date tip **4** · markets_breakdown **1** (`2015-03` thin-floor under `history_target_start=2015-03-26` — still DEFER thin-floor; first full COMPLETE **2015-04**).

**Path:** inventory replan (OOS PARTIAL prune + sticky COMPLETE) · fail-closed publish local=remote **3457** · observed reeval ×11 · FRESH. **No densify. No tip collect loop. No invent COMPLETE.**

**Non-actions this wave:** densify · tip collect as primary · empty-raw COMPLETE · Mass/READY/Phase7 · invent COMPLETE by prune without reagg policy · raise master/D4/D5 floors.

## W36 / w0815ac — continuous collect ops (JQ tip + JSDA + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815ac_w36_collect_ops_20260815.md`](proof/w0815ac_w36_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815ac_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815ac_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815ac_g2_jsda/jsda_summary.json`](../.glm-logs/w0815ac_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815ac_g3_gap/GAP_REPORT.json`](../.glm-logs/w0815ac_g3_gap/GAP_REPORT.json)

| gate | status |
|------|--------|
| Tip densify | **secondary** — COMPLETE **Δ0** · raw **+30** (general 27p + fins 3p); logs `w0815ac_g1_tip` |
| JSDA OTC | **72→72** · FULL_OK_NEW **0** · S260817 refetch only · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| Gap | post_floor_sealable **0** · densify **none** · HAS_RAW_SEALABLE **0** · verdict GAP_HELD_NO_SEALABLE |
| Floors / NO_DENSIFY | **held** (W29 lock; 18 classes; catalog unchanged) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-cbb5d486b6e942769ad8fcd08b1dbc7b` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `596e721a4e38759c5f8c7120eec904c9e6cf7437` |

## W35 / w0815ab — continuous collect ops (JQ tip + JSDA + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815ab_w35_collect_ops_20260815.md`](proof/w0815ab_w35_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815ab_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815ab_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815ab_g2_jsda/jsda_summary.json`](../.glm-logs/w0815ab_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815ab_g3_gap/GAP_REPORT.json`](../.glm-logs/w0815ab_g3_gap/GAP_REPORT.json)

| gate | status |
|------|--------|
| Tip densify | **secondary** — COMPLETE **Δ0** · raw **+30** (general 27p + fins 3p); logs `w0815ab_g1_tip` |
| JSDA OTC | **72→72** · FULL_OK_NEW **0** · S260817 refetch only · corp/repo COMPLETE skip · hot D1 **SKIP** 252 (D1 7403 intermittent retried OK) |
| Gap | post_floor_sealable **0** · densify **none** · HAS_RAW_SEALABLE **0** · verdict GAP_HELD_NO_SEALABLE |
| Floors / NO_DENSIFY | **held** (W29 lock; 18 classes; catalog unchanged) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-340eac0c5eda4e8b8ffdadb0b37cafa4` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `fb626604fe46c3d17a609981b62208cb02ca9d10` |

## W34 / w0815aa — continuous collect ops (JQ tip + JSDA + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815aa_w34_collect_ops_20260815.md`](proof/w0815aa_w34_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815aa_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815aa_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815aa_g2_jsda/jsda_summary.json`](../.glm-logs/w0815aa_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815aa_g3_gap/GAP_REPORT.json`](../.glm-logs/w0815aa_g3_gap/GAP_REPORT.json)

| gate | status |
|------|--------|
| Tip densify | **secondary** — COMPLETE **Δ0** · raw **+30** (general 27p + fins 3p); logs `w0815aa_g1_tip` |
| JSDA OTC | **72→72** · FULL_OK_NEW **0** · S260817 refetch only · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| Gap | post_floor_sealable **0** · densify **none** · HAS_RAW_SEALABLE **0** · verdict GAP_HELD_NO_SEALABLE |
| Floors / NO_DENSIFY | **held** (W29 lock; 18 classes; catalog unchanged) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-f0ee1d48d335445eb7f42c75c872e7da` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `730d333cc3d3caab39238d52d1e7be3fe9af3904` |

## W33 / w0815z — continuous collect ops (JQ tip + JSDA + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815z_w33_collect_ops_20260815.md`](proof/w0815z_w33_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815z_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815z_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815z_g2_jsda/jsda_summary.json`](../.glm-logs/w0815z_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815z_g3_gap/GAP_REPORT.json`](../.glm-logs/w0815z_g3_gap/GAP_REPORT.json)

| gate | status |
|------|--------|
| Tip densify | **secondary** — COMPLETE **Δ0** · raw **+56** (general 27p + fins 3p); logs `w0815z_g1_tip` |
| JSDA OTC | **72→72** · FULL_OK_NEW **0** · S260817 refetch only · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| Gap | post_floor_sealable **0** · densify **none** · HAS_RAW_SEALABLE **0** · verdict GAP_HELD_NO_SEALABLE |
| Floors / NO_DENSIFY | **held** (W29 lock; 18 classes; catalog unchanged) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-061b5d38668a4e6d8537757c28350d78` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `3927ca4d81950828dfe292364b976ca461d31d2a` |

## W32 / w0815y — continuous collect ops (JQ tip + JSDA + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815y_w32_collect_ops_20260815.md`](proof/w0815y_w32_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815y_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815y_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815y_g2_jsda/jsda_summary.json`](../.glm-logs/w0815y_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815y_g3_gap/GAP_REPORT.json`](../.glm-logs/w0815y_g3_gap/GAP_REPORT.json)

| gate | status |
|------|--------|
| Tip densify | **secondary** — COMPLETE **Δ0** · raw **+30** (general 27p + fins 3p); logs `w0815y_g1_tip` |
| JSDA OTC | **72→72** · FULL_OK_NEW **0** · S260817 refetch only · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| Gap | post_floor_sealable **0** · densify **none** · HAS_RAW_SEALABLE **0** · verdict GAP_HELD_NO_SEALABLE |
| Floors / NO_DENSIFY | **held** (W29 lock; 18 classes; catalog unchanged) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-b5f2325ca773478cb3c9e2eb1839e4d9` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `b44c23c7f3af6e36ef7bafe37195cc3b12c369e8` |

## W31 / w0815x — continuous collect ops (JQ tip + JSDA + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815x_w31_collect_ops_20260815.md`](proof/w0815x_w31_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815x_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815x_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815x_g2_jsda/jsda_summary.json`](../.glm-logs/w0815x_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815x_g3_gap/GAP_REPORT.json`](../.glm-logs/w0815x_g3_gap/GAP_REPORT.json)

| gate | status |
|------|--------|
| Tip densify | **secondary** — COMPLETE **Δ0** · raw **+56** (general 27p + fins 3p); logs `w0815x_g1_tip` |
| JSDA OTC | **72→72** · FULL_OK_NEW **0** · S260817 refetch only · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| Gap | post_floor_sealable **0** · densify **none** · HAS_RAW_SEALABLE **0** · verdict GAP_HELD_NO_SEALABLE |
| Floors / NO_DENSIFY | **held** (W29 lock; 18 classes; catalog unchanged) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-20ecd21e86c34b45bf21d82c39d5f84d` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `74894912ac4851bbd5a837183e000a160a11e5e3` |

## W30 / w0815w — continuous collect ops (JQ tip + JSDA + gap) (FINAL)

**Ops close proof:** [`docs/proof/w0815w_w30_collect_ops_20260815.md`](proof/w0815w_w30_collect_ops_20260815.md)  
**Machine:** tip [`.glm-logs/w0815w_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815w_g1_tip/FINAL_metrics.json) · JSDA [`.glm-logs/w0815w_g2_jsda/jsda_summary.json`](../.glm-logs/w0815w_g2_jsda/jsda_summary.json) · gap [`.glm-logs/w0815w_g3_gap/GAP_REPORT.json`](../.glm-logs/w0815w_g3_gap/GAP_REPORT.json)

| gate | status |
|------|--------|
| Tip densify | **secondary** — COMPLETE **Δ0** · raw **+56** (general 27p + fins 3p); logs `w0815w_g1_tip` |
| JSDA OTC | **72→72** · FULL_OK_NEW **0** · S260817 refetch only · corp/repo COMPLETE skip · hot D1 **SKIP** 252 |
| Gap | post_floor_sealable **0** · densify **none** · HAS_RAW_SEALABLE **0** · verdict GAP_HELD_NO_SEALABLE |
| Floors / NO_DENSIFY | **held** (W29 lock; 18 classes; catalog unchanged) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-c4240127142b4d9b83e53f02866018a7` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `b18a06175a3bb4ed3f3c84c6f1dd573a309e1e10` |

## W29 / w0815v — floor catalog + NO_DENSIFY + tip ops close (FINAL)

**Canonical floor catalog:** [`docs/proof/observed_floor_catalog_20260815.md`](proof/observed_floor_catalog_20260815.md)  
**Ops close proof:** [`docs/proof/w0815v_w29_floor_contract_ops_20260815.md`](proof/w0815v_w29_floor_contract_ops_20260815.md)  
**Machine:** [`.glm-logs/w0815v_floor/unified_floor_catalog.json`](../.glm-logs/w0815v_floor/unified_floor_catalog.json) · [`.glm-logs/w0815v_floor/NO_DENSIFY_FIXED.json`](../.glm-logs/w0815v_floor/NO_DENSIFY_FIXED.json) · [`.glm-logs/w0815v_floor/t8_t9_post_floor/NO_HOLES.json`](../.glm-logs/w0815v_floor/t8_t9_post_floor/NO_HOLES.json) · tip [`.glm-logs/w0815v_g1_tip/FINAL_metrics.json`](../.glm-logs/w0815v_g1_tip/FINAL_metrics.json)  
**Peer floors:** T1 fins · T2 bars/master · T3 edinet/mb/ssr · T4 indices under `.glm-logs/w0815v_floor/`

| gate | status |
|------|--------|
| Floors | **locked** — sealable observed floors recorded for all residual + COMPLETE governed datasets |
| Tip densify | **secondary** — COMPLETE **Δ0** · raw **+30** (general 27p + fins 3p); logs `w0815v_g1_tip` |
| Post-floor holes | **NO_HOLES** — sealable closed **0** · densify **false** · only tip DEFER `fins_earnings_date` 2026-01…04 |
| Contract `history_target_start` raise | **propose only** (12 candidates; **0** implemented this wave) |
| empty-raw COMPLETE / Mass / READY / Phase7 | **ban / NO-GO / OFF** |
| Projection | **FRESH** `projgen-76084a30143043febab9babe9327aa2f` |
| CF-SoT | D1 **hot tip** · R2 **history** · COMPLETE **receipt-owned** |
| Push | **POST_PUSH_SHA** `d3c9f54b5237c7f18f692483601a706b5ee620b0` |

### NO_DENSIFY_FIXED (never re-densify residual class)

**W29 baseline:** **18** classes (formal D1–D7,D9,D10 + matrix MX-\*). **Do not densify** unless DEFER re-try condition is met.  
**W38 supersession:** after contract floor raises (`ba3c811`), **active required-window** NO_DENSIFY = **6** classes; **12** classes are **OUT_OF_SCOPE** archive (see **§W38** above). Historical 18-row table retained for audit:

| DEFER id | dataset(s) | residual class / span | n | W38 disposition | never densify reason |
|----------|------------|----------------------|--:|-----------------|----------------------|
| **D1** | `indices_bars_daily_topix` | EMPTY `2008-01…04` | 4 | **OOS** (floor→2008-05-01) | API empty shells |
| **D1** | `indices_bars_daily` | EMPTY/missing receipt `2008-01…04` | 4 | **OOS** (floor→2008-05-01) | same band |
| **D2** | `equities_master` | PRE_PLAN `2000-07…2006-07` | 73 | **STILL_DEFER** | no sealable raw |
| **D2** | `equities_master` | MISDATE `2006-08…2008-04` | 21 | **STILL_DEFER** | tip-misdated Date |
| **D3** | `markets_breakdown` | EMPTY pre-source-floor `2013-01…2015-03` | 27 | **OOS** (floor→2015-03-26) | source floor 2015-03-26 |
| **D4** | `equities_earnings_calendar` | TIP_ONLY history residual | ~199 | **STILL_DEFER** | vendor next-bday only |
| **D4** | `equities_bars_daily_am` | TIP_ONLY history residual | ~31 | **STILL_DEFER** | today-mode AM only |
| **D5** | `jsda_otc_bond_reference_prices` | ARCHIVE beyond tip COMPLETE **72** | archive | **STILL_DEFER** | site timeout/404/403 |
| **D6** | `edinet_cross_shareholdings` | EMPTY pre-island `2018-01…2020-04` | 28 | **OOS** (floor→2020-05-01) | empty-raw residual |
| **D6** | `edinet_large_volume_shareholders` | EMPTY pre-island `2018-01…2021-06` | 42 | **OOS** (floor→2021-07-01) | empty-raw residual |
| **D7** | `equities_bars_daily` | NO_RAW `2004-01…2006-07` | 31 | **OOS** (floor→2008-05-01) | OOS / entitlement |
| **D7** | `equities_bars_daily` | EMPTY `2006-08…2008-04` | 21 | **OOS** (floor→2008-05-01) | empty API under sub |
| **D9** | `markets_short_sale_report` | EMPTY pre-history `2013-01…10` | 10 | **OOS** (floor→2013-11-01) | first nz 2013-11 |
| **D10** | `fins_summary` | EMPTY pre-history `2008-01…06` | 6 | **OOS** (floor→2008-07-01) | first nz 2008-07 |
| **MX-DIV** | `fins_dividend` | EMPTY_SHELL `2008-01…2013-01` | 61 | **OOS** (floor→2013-02-01) | W27-G1 matrix forever-skip |
| **MX-DET** | `fins_details` | DEFER_PRE2018 `2008-01…2017-12` | 120 | **OOS** (floor→2018-01-01) | W27-G3 matrix forever-skip |
| **MX-EARN-PRE** | `fins_earnings_date` | NO_RAW pre-floor `2010-01…2017-12` | 96 | **OOS** (floor→2018-01-01) | W27-G2 matrix |
| **MX-EARN-TIP** | `fins_earnings_date` | tip known-empty `2026-01…04` | 4 | **STILL_DEFER** | W27-G2; no densify-as-success |

**JSDA floors (residual):** OTC archive **D5** (still DEFER) · `jsda_tokyo_repo_rates` **COMPLETE** 1/1 · `jsda_corporate_bond_transactions` **COMPLETE** 12/12 · earn_calendar / bars_am **D4** tip-only (still DEFER).

**Contract raise candidates:** W29 catalog §2 proposed **12**; W38 **implemented 11** (all proven always-empty floors); **master not raised** (D2 permanent DEFER).

## W27-G6 unified matrix — 残 seg × raw 有無

**Proof:** [`docs/proof/w0815t_g6_matrix_close_ops_20260815.md`](proof/w0815t_g6_matrix_close_ops_20260815.md) · logs `.glm-logs/w0815t_g6_ops/matrix/unified_matrix_summary.json`  
**Rule:** seal only **HAS_RAW_SEALABLE** (nz COMPLETE raw + window_ok + PARTIAL). Tip densify only for **non-DEFER** NO_RAW tip holes (prefer DEFER fix). Empty-raw COMPLETE **forbidden**.

| dataset | 残 seg | raw 有 (HAS_RAW_SEALABLE) | raw 空 | raw 無 | closed Δ | disposition |
|---------|-------:|-------------------------:|-------:|-------:|----------:|-------------|
| `fins_dividend` | 61 | **0** | 61 | 0 | **0** | DEFER empty pre-history (G1) |
| `fins_earnings_date` | 100 | **0** | 0 | 100 | **0** | DEFER pre2018 + tip `2026-01…04` (G2) |
| `fins_details` | 120 | **0** | 120 | 0 | **0** | DEFER_PRE2018_EMPTY (G3) |
| `equities_bars_daily` | 52 | **0** | 21 | 31 | **0** | DEFER_PRE_FLOOR D7 (G4) |
| `edinet_cross_shareholdings` | 28 | **0** | 28 | 0 | **0** | DEFER_EMPTY_API D6 (G5) |
| `edinet_large_volume_shareholders` | 42 | **0** | 42 | 0 | **0** | DEFER_EMPTY_API D6 (G5) |
| `edinet_major_shareholders` | 0 | **0** | 0 | 0 | **0** | COMPLETE 104/104 held |
| `fins_summary` | 6 | **0** | 6 | 0 | **0** | DEFER D10 |
| `markets_short_sale_report` | 10 | **0** | 10 | 0 | **0** | DEFER D9 |
| `indices_bars_daily` / `_topix` | 4+4 | **0** | 4+4 | 0 | **0** | DEFER D1 |
| `markets_breakdown` | 27 | **0** | 27 | 0 | **0** | DEFER D3 |
| `equities_master` | 94 | **0** | 0 | 94* | **0** | DEFER D2 misdate/pre-plan |
| `equities_earnings_calendar` / `bars_am` | 199+31 | **0** | 0 | 0 | **0** | DEFER D4 tip |
| `jsda_otc_bond_reference_prices` | 8709 | **0** | 0 | 8709 | **0** | DEFER D5 archive |
| **TOTAL HAS_RAW_SEALABLE** | — | **0** | — | — | **0** | **0 ok** |

\* master: params may look OK; data Date not in-window (misdate) → not sealable.

## W20 column / NULL audit (short)

**Canonical:** [`docs/proof/column_null_audit_20260815.md`](proof/column_null_audit_20260815.md) · G4 [`w0815m_g4_jsda_audit_20260815.md`](proof/w0815m_g4_jsda_audit_20260815.md) · hot tip [`jsda_hot_d1_publish_20260815.md`](proof/jsda_hot_d1_publish_20260815.md)  
**W24-G1 re-verify (2026-08-15 10:34JST):** audit §9 · logs `.glm-logs/w0815q_g1_audit_reverify/` · CF SoT re-sample **HOLDS** (master short typed 0% null n=200; fins+margin keyset equal 1.0; **no new mapping bugs**)  
**W25-G1 CF-SoT language lock (2026-08-15):** docs clarify D1 = hot tip · R2 = history · COMPLETE = **receipt-owned**; local research SQLite = **mirror only** (not authority / not “local SoT”)  
**W27-G6 re-confirm:** no remaining affirmative “local SoT” language in column_null_audit / JSDA proofs; CF = D1 hot / R2 history / receipt-owned **CONFIRMED**

### Residual short audit summary (W25-G1)

| Item | Status |
|------|--------|
| **Fixed keys** | master **S17 / S33 / Mkt** (+ names) · bars **AAdj\*** false all-day Adj alias → **FIXED** `df6271d` |
| **Source always-null DEFER** | fins forecast/unit · options EC/EH/EL/EO/SQD · ExRT · listing_date · JSDA corp schema-superset (isin/counterparty/face/amount) — **do not invent** |
| **tokyo_repo** | D1 **hot tip 252** + full history **R2 / local mirror** · COMPLETE **receipt-owned** · **not loss** (plane-split honesty `4fcef08` + hot publish) |
| Generic payload drop | **none** (G3 deep same-row; W24-G1 re-sample fins+margin keyset_equal=**1.0**) |
| Mass / READY / Phase7 / empty-raw COMPLETE | **NO-GO / OFF / ban held** |

**CF SoT:** D1 = **hot tip** · R2 = **history** · coverage COMPLETE = **receipt-owned**. Local research SQLite = **mirror / research convenience** — **not** authority.

Coverage DEFERs **D1–D10** (D10 fins_summary residual 6 formalized **W19-G6 T13**). Column-audit **does not** promote dataset COMPLETE.

## Live snapshot (remote D1 `quant-ingest`)
| Item | Value |
|------|--------|
| Dataset COMPLETE | **20** (**W38** PRE **11** → POST **20** **+9** via floor replan; sticky COMPLETE; no new segs) — prior 11 held + **`equities_bars_daily`** · **`indices_bars_daily`** · **`indices_bars_daily_topix`** · **`fins_summary`** · **`fins_dividend`** · **`fins_details`** · **`markets_short_sale_report`** · **`edinet_cross_shareholdings`** · **`edinet_large_volume_shareholders`** |
| Dataset COMPLETE surfaces | **aligned** — `dataset_coverage.status` **20** COMPLETE / **6** PARTIAL (W38 reeval; proof [`w0815ae_w38_contract_floor_raise_20260815.md`](proof/w0815ae_w38_contract_floor_raise_20260815.md)) |
| Dataset STALE | **0** |
| Segment COMPLETE total | **3457** (remote; **W38** PRE/POST **3457** **+0** primary — floor replan OOS prune only, sticky COMPLETE; prior **W36** **3457** **+0**; **no** empty COMPLETE) |
| empty COMPLETE | **0** (ban held PRE/POST W38) |
| Segment other | PARTIAL (master **94** · earn_cal **199** · bars_am **31** · otc **8709** · fins_earnings_date tip **4** · markets_breakdown **1** `2015-03` thin-floor) — not mass-READY |
| calendar segments | **224 COMPLETE / 0 PARTIAL** |
| JSDA OTC COMPLETE segs | **72** — tip/recent sealed; further tip/archive **DEFER** site timeout/404/403 (D5 permanent) |
| JSDA corporate COMPLETE segs | **12** — years **`2015`…`2026`** (full annual TORIHIKI; dataset **COMPLETE**) |
| **markets_short_ratio** | segs **164/164 COMPLETE** + `dataset_coverage` **COMPLETE** |
| **derivatives_bars_daily_futures** | segs **164/164 COMPLETE** + `dataset_coverage` **COMPLETE** |
| **derivatives_bars_daily_options_225** | segs **164/164 COMPLETE** + `dataset_coverage` **COMPLETE** |
| **derivatives_bars_daily_options** | segs **164/164 COMPLETE** + `dataset_coverage` **COMPLETE** |
| **markets_short_sale_report** | dataset **COMPLETE** (**W38** floor → **2013-11-01**; COMPLETE segs **154**; pre-floor PARTIAL OOS) |
| **fins_summary** | dataset **COMPLETE** (**W38** floor → **2008-07-01**; COMPLETE segs **218**; pre-floor PARTIAL OOS) |
| **markets_breakdown** | COMPLETE **137** / PARTIAL **1** (`2015-03` thin under floor **2015-03-26**) — **W38** raised floor from `2013-01-04`; still DEFER thin-floor (first full COMPLETE **2015-04**) |
| A3 sealed (partial datasets) | sticky COMPLETE retained → COMPLETE **3457** (W38 no new seals) |
| Remote `raw_retention_manifests` | **15589** total (**W38** not remeasured — no tip collect; held **W36** tip POST **15589**; prior chain W35…W27 unchanged) |
| Track A + P0 execute | **w0713…w0815ae** + **W38** contract floors + reeval + **W36** tip collect + peers; **Worker pass ≠ COMPLETE** |
| master | `scd2_event_sourcing` / D1 hot — still PARTIAL **94** (D2 permanent DEFER; floor **not** raised) |
| projection | **FRESH** — `projgen-c54a409aaeef424e9c13394b82bd720b` (**W38** reeval publish; segs sticky **3457**; prior **W36** `projgen-cbb5d486…` / **W35** `projgen-340eac0c…`) |
| sticky COMPLETE | **fixed** segment_id fallback + post-sticky dataset aggregate + COMPLETE inventory retain past UTC target_end (`coverage_ledger.py`) |
| Full publish guard | `scripts/publish_ops_projection.py` fail-closed |
| Targeted freshness | `scripts/ops_reeval_freshness.py` (no segment rewrite) |
| Observed window re-eval | `scripts/ops_reeval_observed_window.py` (SUCCESS receipts `raw_row_count>0`; no segment rewrite / no COMPLETE claim) |
| Layout migration | **DONE** — libraries under `packages/{edge,data_plane,research_runtime,product}`; import leaf names unchanged |
| Track A (historical raw accel) | **EXECUTE DONE** — PRE raw **1488** → … → T13–T15 **7430** → T9/G5 peers → T5 fins → t5_div_pre → live raw **7825** |
| Track B1 (LLM-friendly) | **landed** + residual/docs SoT live-sync; B1-e partial (ops/coverage/receipt CLIs); Batch Z still **DEFER** |
| Mass / READY / B0 | **NO-GO** |
| Phase 7 | **OFF / foundation only** — **must remain OFF**; no mass arming, no production READY, no Phase7 switch ON |

## DEFER inventory (retry conditions) — historical D1–D10 pointer (W47)

**Canonical live residual:** → **§W47 Permanent DEFER + NO_DENSIFY** (5 PD IDs · 6 NO_DENSIFY classes · **actionable_gap = 0**).  
**Do not re-run densify** unless re-try condition is met. Empty-raw COMPLETE **forbidden**. Floors W38 + W42 mb **2015-04-01** **not lowered**.

| era | disposition |
|-----|-------------|
| **W47 FINAL** | active PARTIAL = **5** permanent DEFER only (PD-D2-MASTER · PD-D4-EARN-CAL · PD-D4-BARS-AM · PD-D5-JSDA-OTC · PD-MX-EARN-TIP) |
| **W44 lock** | FINAL permanent DEFER reaffirm + PD-MX-EARN-TIP; machine [`.glm-logs/w0815ak_g2_defer/`](../.glm-logs/w0815ak_g2_defer/) |
| **W38** | contract floor raise · active NO_DENSIFY **18→6** · **12** OOS pre-floor archive · Permanent DEFER **5** · see **§W38** |
| **W29** | NO_DENSIFY_FIXED **18** classes catalog · [`observed_floor_catalog_20260815.md`](proof/observed_floor_catalog_20260815.md) |
| **W11–W28** | D1–D10 formalization chain (audit only) |

### Historical D1–D10 refs (short — evidence only; most OOS after W38)

| ID | dataset(s) | historical residual | W47 status | re-try (one-liner) | proof |
|----|------------|---------------------|------------|--------------------|-------|
| D1 | topix / indices bars | empty `2008-01…04` | **OOS** (W38 floor) | vendor nz **or** human-gate floor | [`w0815b_g8_topix_indices_20260815.md`](proof/w0815b_g8_topix_indices_20260815.md) |
| **D2** | `equities_master` | MISDATE 21 + PRE_PLAN 73 | **PD-D2-MASTER** active | in-window Date raw + window_ok | [`w0815b_g10_master_20260815.md`](proof/w0815b_g10_master_20260815.md) |
| D3 | `markets_breakdown` | thin/pre-floor | **COMPLETE** (W42 floor **2015-04-01**) | n/a coverage | [`w0815ai_w42_close_20260815.md`](proof/w0815ai_w42_close_20260815.md) |
| **D4** | earn_cal · bars_am | tip-only ~199 / ~31 | **PD-D4-EARN-CAL** · **PD-D4-BARS-AM** | vendor history API / de-scope | [`w0815b_g11_earn_am_20260815.md`](proof/w0815b_g11_earn_am_20260815.md) |
| **D5** | jsda_otc | archive beyond tip island | **PD-D5-JSDA-OTC** (tip **93**) | FULL_OK day-by-day only · never COMPLETE | [`w0815n_g1_jsda_otc_20260815.md`](proof/w0815n_g1_jsda_otc_20260815.md) |
| D6 | EDINET cross/large | pre-island empty | **OOS / COMPLETE** island | nz filings before seal | [`w0815r_g4_edinet_otc_20260815.md`](proof/w0815r_g4_edinet_otc_20260815.md) |
| D7 | equities_bars_daily | pre-2008-05 gap | **OOS** (floor) | nz raw / floor accept | [`bars_p0_gap_2004_2008_reverify_20260813.md`](proof/bars_p0_gap_2004_2008_reverify_20260813.md) |
| D8 | Batch Z / Mass·READY·Phase7 | arming | **DEFER / OFF** | ADR amendment only; Phase7 **OFF** | [`adr_llm_friendly_refactor.md`](architecture/adr_llm_friendly_refactor.md) |
| D9 | short_sale | pre-2013-11 empty | **OOS** (W38 floor) | vendor nz / floor | [`w0815h_g1_short_sale_20260815.md`](proof/w0815h_g1_short_sale_20260815.md) |
| D10 | fins_summary | pre-2008-07 empty | **OOS** (W38 floor) · dataset COMPLETE | vendor nz / floor | [`w0815j_g1_fins_summary_20260815.md`](proof/w0815j_g1_fins_summary_20260815.md) |
| **MX-EARN-TIP** | `fins_earnings_date` | tip `2026-01…04` | **PD-MX-EARN-TIP** active | vendor nz tip months | W44 / §W47 |

**Ops policy:** resume dead acq **only** if residual is **non-DEFER** (not in permanent DEFER / active NO_DENSIFY). Dual-issue banned while peer `issue_receipts*` / `issue_driver` **or peer ops_loop** alive. Fail-closed publish when `local COMPLETE < remote`.

### Host POST/min (multi-track session, state jsonl + run log)

| Track | host POST/min | n | note |
|-------|--------------:|--:|------|
| w0815ae W38 contract+reeval | **n/a** (no tip densify) | COMPLETE segs **Δ0** · Dataset COMPLETE **+9** · densify **none** | **W38 / w0815ae** parallel: T1 contract **11** `history_target_start` raises (`ba3c811`) · T4 Permanent DEFER **5** · T5 NO_DENSIFY **18→6** · T2/T3 reeval OOS PARTIAL prune + sticky COMPLETE + fail-closed publish local=remote **3457** · FRESH `projgen-c54a409aaeef424e9c13394b82bd720b` · Dataset COMPLETE **11→20** · empty **0** · tip densify **not primary** · markets_breakdown residual **1** (`2015-03` thin) · proof [`w0815ae_w38_contract_floor_raise_20260815.md`](proof/w0815ae_w38_contract_floor_raise_20260815.md) |
| w0815ac W36 collect ops | general **1.69** (n=27 @495rpm cfg) / fins **4.87** (n=3 @100rpm) | **+0** seal / raw **+30** · post_floor sealable **0** | **W36 / w0815ac** parallel: T1 tip general week-chunks **27p/0f** (w=8 rpm**495**; 0×429; rows **567351**) + fins tip **3p/0f** (w=2 rpm**100**; rows **7155**); T2 JSDA OTC FULL_OK new **0** (S260817 refetch already sealed; tip advance 404/timeout); corp/repo COMPLETE skip; hot D1 **SKIP** (n=252 max=`2026-08-10`); T3 gap post_floor_sealable **0** densify **none** HAS_RAW_SEALABLE **0**; seal/issue **0** (tip already COMPLETE); fail-closed publish local=remote **3457** no force; FRESH `projgen-cbb5d486b6e942769ad8fcd08b1dbc7b`; remote COMPLETE **3457→3457** raw **15559→15589** (+30); Dataset COMPLETE **11**; OTC **72** held; empty **0**; floors/NO_DENSIFY held; DEFER densify **not** executed; peers not killed; proof [`w0815ac_w36_collect_ops_20260815.md`](proof/w0815ac_w36_collect_ops_20260815.md) |
| w0815z W33 collect ops | general **5.03** (n=27 @495rpm cfg) / fins **7.94** (n=3 @100rpm) | **+0** seal / raw **+56** · post_floor sealable **0** | **W33 / w0815z** parallel: T1 tip general week-chunks **27p/0f** (w=8 rpm**495**; 0×429; rows **567338**) + fins tip **3p/0f** (w=2 rpm**100**; rows **7155**); T2 JSDA OTC FULL_OK new **0** (S260817 refetch already sealed; tip advance 404/timeout); corp/repo COMPLETE skip; hot D1 **SKIP** (n=252 max=`2026-08-10`); T3 gap post_floor_sealable **0** densify **none** HAS_RAW_SEALABLE **0**; seal/issue **0** (tip already COMPLETE); fail-closed publish local=remote **3457** no force; FRESH `projgen-061b5d38668a4e6d8537757c28350d78`; remote COMPLETE **3457→3457** raw **15420→15476** (+56); Dataset COMPLETE **11**; OTC **72** held; empty **0**; floors/NO_DENSIFY held; DEFER densify **not** executed; peers not killed; proof [`w0815z_w33_collect_ops_20260815.md`](proof/w0815z_w33_collect_ops_20260815.md) |
| w0815y W32 collect ops | general **5.51** (n=27 @495rpm cfg) / fins **7.88** (n=3 @100rpm) | **+0** seal / raw **+30** · post_floor sealable **0** | **W32 / w0815y** parallel: T1 tip general week-chunks **27p/0f** (w=8 rpm**495**; 0×429; rows **567351**) + fins tip **3p/0f** (w=2 rpm**100**; rows **7155**); T2 JSDA OTC FULL_OK new **0** (S260817 refetch already sealed; tip advance 404/timeout); corp/repo COMPLETE skip; hot D1 **SKIP** (n=252 max=`2026-08-10`); T3 gap post_floor_sealable **0** densify **none** HAS_RAW_SEALABLE **0**; seal/issue **0** (tip already COMPLETE); fail-closed publish local=remote **3457** no force; FRESH `projgen-b5f2325ca773478cb3c9e2eb1839e4d9`; remote COMPLETE **3457→3457** raw **15390→15420** (+30); Dataset COMPLETE **11**; OTC **72** held; empty **0**; floors/NO_DENSIFY held; DEFER densify **not** executed; peers not killed; proof [`w0815y_w32_collect_ops_20260815.md`](proof/w0815y_w32_collect_ops_20260815.md) |
| w0815x W31 collect ops | general **4.98** (n=27 @495rpm cfg) / fins **7.97** (n=3 @100rpm) | **+0** seal / raw **+56** · post_floor sealable **0** | **W31 / w0815x** parallel: T1 tip general week-chunks **27p/0f** (w=8 rpm**495**; 0×429; rows **567338**) + fins tip **3p/0f** (w=2 rpm**100**; rows **7155**); T2 JSDA OTC FULL_OK new **0** (S260817 refetch already sealed; tip advance 404/timeout); corp/repo COMPLETE skip; hot D1 **SKIP** (n=252 max=`2026-08-10`); T3 gap post_floor_sealable **0** densify **none** HAS_RAW_SEALABLE **0**; seal/issue **0** (tip already COMPLETE); fail-closed publish local=remote **3457** no force; FRESH `projgen-20ecd21e86c34b45bf21d82c39d5f84d`; remote COMPLETE **3457→3457** raw **15311→15367** (+56); Dataset COMPLETE **11**; OTC **72** held; empty **0**; floors/NO_DENSIFY held; DEFER densify **not** executed; peers not killed; proof [`w0815x_w31_collect_ops_20260815.md`](proof/w0815x_w31_collect_ops_20260815.md) |
| w0815w W30 collect ops | general **5.09** (n=27 @495rpm cfg) / fins **7.84** (n=3 @100rpm) | **+0** seal / raw **+56** · post_floor sealable **0** | **W30 / w0815w** parallel: T1 tip general week-chunks **27p/0f** (w=8 rpm**495**; 0×429; rows **567338**) + fins tip **3p/0f** (w=2 rpm**100**; rows **7155**); T2 JSDA OTC FULL_OK new **0** (S260817 refetch already sealed; tip advance 404/timeout); corp/repo COMPLETE skip; hot D1 **SKIP** (n=252 max=`2026-08-10`); T3 gap post_floor_sealable **0** densify **none** HAS_RAW_SEALABLE **0**; seal/issue **0** (tip already COMPLETE); fail-closed publish local=remote **3457** no force; FRESH `projgen-c4240127142b4d9b83e53f02866018a7`; remote COMPLETE **3457→3457** raw **15255→15311** (+56); Dataset COMPLETE **11**; OTC **72** held; empty **0**; floors/NO_DENSIFY held; DEFER densify **not** executed; peers not killed; proof [`w0815w_w30_collect_ops_20260815.md`](proof/w0815w_w30_collect_ops_20260815.md) |
| w0815v W29 floor+ops close | general **5.43** (n=27 @495rpm cfg) / fins **8.05** (n=3 @100rpm) | **+0** seal / raw **+30** · post_floor closed **0** | **W29 / w0815v** parallel: floor catalog T1–T4 + NO_DENSIFY_FIXED **18** classes + contract proposals **0** implemented; T8–T9 post-floor **NO_HOLES** densify false seal **0**; tip T10 general week-chunks **27p/0f** (w=8 rpm**495**; 0×429; rows **567351**) + fins tip **3p/0f** (w=2 rpm**100**; rows **7155**); JSDA FULL_OK new **0**; fail-closed publish local=remote **3457** no force; FRESH `projgen-76084a30…`; remote COMPLETE **3457→3457** raw **15225→15255** (+30); Dataset COMPLETE **11**; OTC **72** held; empty **0**; HAS_RAW_SEALABLE **0**; DEFER densify **not** executed; last_run monitor no peer ops_loop kill; tip finished; proof [`w0815v_w29_floor_contract_ops_20260815.md`](proof/w0815v_w29_floor_contract_ops_20260815.md) · catalog [`observed_floor_catalog_20260815.md`](proof/observed_floor_catalog_20260815.md) |
| w0815u g1 collect (W28-G1) | general **5.04** (n=27 @495rpm cfg) / fins **8.0** (n=3 @100rpm) | **+0** seal / raw **+30** | **W28-G1** continuous all-sources: general tip week-chunks **27p/0f** (w=8 rpm**495**; 0×429; rows **567351** incl options/futures/edinet_major/master tip) + fins tip **3p/0f** (w=2 rpm**100**; rows **7155**); JSDA OTC FULL_OK new **0** (S260817 already-sealed refetch 200; tip advance 404; residual timeout); corp/repo COMPLETE skip; hot D1 **SKIP** (n=252 max=`2026-08-10`); seal/issue **0** (tip already COMPLETE); fail-closed publish local=remote **3457** no force; FRESH `projgen-57a33eaa…`; C8 pass×18 tip datasets; remote COMPLETE **3457→3457** raw **15145→15175** (+30); Dataset COMPLETE **11**; OTC **72** held; empty **0**; DEFER densify **not** executed (dry only); proof [`w0815u_g1_collect_20260815.md`](proof/w0815u_g1_collect_20260815.md) |
| w0815t g6 matrix close ops (W27-G6) | — | **+0** seal / session **+0** segs | **W27-G6** T6–T15: peer matrices G1–G5 **HAS_RAW_SEALABLE=0** → closed **0** by dataset; tip densify **SKIP** (G2 tip NO_RAW is DEFER); CF-SoT language **CONFIRMED** (no local SoT); unified **残 seg × raw 有無** table; dual-coord peer `w0815s_g4_ops` then fail-closed publish local=remote **3457** no force; FRESH `projgen-2ef0e4ae…`; remote COMPLETE **3457→3457** raw **15145→15145** (+0); Dataset COMPLETE **11** held; OTC **72** held; fins_summary **218**/PARTIAL **6** held; empty **0**; DEFER D1–D10 densify **not** re-run; peers not killed; tokyo_repo local **30303** / D1 hot **252**; general ~495 note / fins separate; proof [`w0815t_g6_matrix_close_ops_20260815.md`](proof/w0815t_g6_matrix_close_ops_20260815.md) |
| w0815s g4 ops (W26-G4) | — | **+0** issue / session **+0** segs | **W26-G4** continuous ops (~02:24–02:47Z): ready-seal gap **0** all 14 cycles; no peer ops_loop dual; fail-closed publish ×N (c1 + c13/c14 + final; no force); FRESH `projgen-2d336b6e…` (later reclocked by W27); remote COMPLETE **3457→3457** raw **15125→15145** (+20 peer tip densify); Dataset COMPLETE **11** held; OTC **72** held; fins_summary **218**/PARTIAL **6** held; empty **0**; DEFER D1–D10 densify **not** re-run; last_run monitor no peer kill (`w0815s_g2_tip` / `g3_seal` / `g1_jsda` left alone); **CF-SoT** language **CONFIRMED**; tokyo_repo local **30303** / D1 hot **252**; general ~495 note / fins separate; proof [`w0815s_g4_ops_20260815.md`](proof/w0815s_g4_ops_20260815.md) |
| w0815r g5 ops (W25-G5) | — | **+0** issue / session **+0** segs | **W25-G5** continuous ops T11–T16: dual-coord peer `w0815q_g6_ops` (publish defer cycles 1–3; peer dead cycle 4+ → fail-closed publish ×N no force); ready-seal gap **0** all 14 cycles; FRESH `projgen-9ee87879…`; remote COMPLETE **3457→3457** raw **15102→15125** (+23 peer densify); Dataset COMPLETE **11** held; OTC **72** held; fins_summary **218**/PARTIAL **6** held; empty **0**; DEFER D1–D10 densify **not** re-run; last_run monitor no peer kill; **CF-SoT** language **CONFIRMED** (W24-G1 §9 + W25-G1 lock); tokyo_repo local **30303** / D1 hot **252**; general ~495 note / fins separate; proof [`w0815r_g5_ops_20260815.md`](proof/w0815r_g5_ops_20260815.md) |
| w0815r g4 edinet/otc (W25-G4) | — | **+0** seal | **W25-G4** T8–T10: EDINET residual nz scan sealable **0** (cross 28 + large 42 DEFER_EMPTY_API; no forever densify); OTC tip/recent FULL_OK **0** (tip **404** + site timeout/403; held **72**); corp/repo COMPLETE skip; hot D1 **SKIP** (local=D1 tip `2026-08-10` n=252); ops publish **SKIP** (no seal delta); FRESH reclock; COMPLETE **3457** held; Dataset COMPLETE **11**; empty **0**; proof [`w0815r_g4_edinet_otc_20260815.md`](proof/w0815r_g4_edinet_otc_20260815.md) |
| w0815q g6 ops (W24-G6) | — | **+0** issue / session **+0** segs | **W24-G6** continuous ops T13–T17: jsda last_run PARTIAL **diag NO_RECOVER** (D5 DEFER; seal_delta 0); dual-coord peer `w0815p_g4_ops` (c1) + `w0815r_g5_ops` (c12–14; no kill); ready-seal gap **0** all 14 cycles; fail-closed publish ×N (no force); FRESH `projgen-eafc6c4a…`; remote COMPLETE **3457→3457** raw **15100→15104** (+4 peer); Dataset COMPLETE **11** held; OTC **72** held; fins_summary **218**/PARTIAL **6** held; empty **0**; DEFER D1–D10 densify **not** re-run; **column_null_audit** origin **CONFIRMED**; tokyo_repo local **30303** / D1 hot **252**; general ~495 note / fins separate; proof [`w0815q_g6_ops_20260815.md`](proof/w0815q_g6_ops_20260815.md) |
| w0815q g5 tip coverage (W24-G5) | bars host ~9.9 (n=2 @495rpm cfg) | **+0** seal / raw **+2** | **W24-G5** T7–T11: fins tip **SKIP** (holes 0); bars tip week-chunks **2p/0f** (w=8 rpm**495**; 0×429; rows **40001**); EDINET residual nz scan sealable **0** (cross 28 + large 42 DEFER_EMPTY_API); seal/issue **0**; fail-closed publish local=remote **3457**; FRESH `projgen-432e34ac…`; raw **15100→15102**; Dataset COMPLETE **11**; empty **0**; DEFER densify **SKIP**; proof [`w0815q_g5_tip_coverage_20260815.md`](proof/w0815q_g5_tip_coverage_20260815.md) |
| w0815p g4 ops (W23-G4) | — | **+0** issue / session **+0** segs | **W23-G4** continuous ops: ready-seal gap **0** all 14 cycles; dual-issue gate free mid-window; fail-closed publish ×N (no force); FRESH `projgen-fc3440c7…`; remote COMPLETE **3457→3457** raw **15064→15101** (+37 peer densify); Dataset COMPLETE **11** held; OTC **72** held; fins_summary **218**/PARTIAL **6** held; empty **0**; DEFER D1–D10 densify **not** re-run; peers not killed; tokyo_repo local **30303** / D1 hot **252**; general ~495 note / fins separate; proof [`w0815p_g4_ops_20260815.md`](proof/w0815p_g4_ops_20260815.md) |
| w0815p g2 tip densify (W23-G2) | general ~37.4 host rpm / fins ~8.1 | **+0** seal / raw **+21** | **W23-G2** JQ tip densify `2026-08-01…` (no DEFER): general week-chunks **17p/0f** (w=8 rpm**495**; 0×429; rowsInserted **93308** incl breakdown tip) + fins tip **3p/0f** (w=2 rpm**100**; rows **7155**); tip months already COMPLETE → seal/issue **0**; receipt-plane reeval C8 pass bars/margin/mb/fins/topix/…; fail-closed publish local=remote **3457**; FRESH `projgen-4f5ea492…`; raw **15079→15100**; Dataset COMPLETE **11**; empty **0**; DEFER densify **SKIP**; proof [`w0815p_g2_tip_densify_20260815.md`](proof/w0815p_g2_tip_densify_20260815.md) |
| w0815o g4 ops (W22-G4) | — | **+0** issue / session **+15** segs | **W22-G4** continuous ops: dual-issue **coord** with peer `w0815n_g4_ops` (skip issue+publish thrash while peer ops_loop alive cycles 1–10; peer dead cycle 11+ → fail-closed publish ×N no force); ready-seal gap **0** all 14 cycles; FRESH `projgen-f0c85058…`; remote COMPLETE **3442→3457** raw **15037→15057** (+20); Dataset COMPLETE **11** held; OTC **57→72** peer tip; fins_summary **218**/PARTIAL **6** held; empty **0**; DEFER D1–D10 densify **not** re-run; peers not killed; tokyo_repo local **30303** / D1 hot **252**; general ~495 note / fins separate; proof [`w0815o_g4_ops_20260815.md`](proof/w0815o_g4_ops_20260815.md) |
| w0815n g4 ops (W21-G4) | — | **+0** issue / session **+15** segs | **W21-G4** continuous ops: ready-seal scan **0** gap all 14 cycles; dual-issue + peer-ops gate (defer publish ×10 while `w0815o_g4_ops` alive); fail-closed final publish (no force); FRESH `projgen-7b3b8bf6…`; remote COMPLETE **3442→3457** raw **15020→15057** (+37); Dataset COMPLETE **11** held; OTC **57→72** peer **W21-G1**; empty **0**; DEFER D1–D10 densify **not** re-run; peers not killed; general ~495 note / fins separate; proof [`w0815n_g4_ops_20260815.md`](proof/w0815n_g4_ops_20260815.md) |
| w0815o g2 tip densify (W22-G2) | general ~36.3 host rpm / fins ~8.1 | **+0** seal / raw **+20** | **W22-G2** JQ tip densify `2026-08-01…14` (no DEFER): general week-chunks **17p/0f** (w=8 rpm**495**; 0×429; rowsInserted **93308** incl breakdown tip) + fins tip **3p/0f** (w=2 rpm**100**; rows **7155**); tip months already COMPLETE → seal/issue **0**; receipt-plane reeval C8 pass bars/margin/mb/fins/topix; fail-closed publish local=remote **3442**; FRESH `projgen-50230079…`; raw **15037→15057**; Dataset COMPLETE **11**; empty **0**; DEFER densify **SKIP**; proof [`w0815o_g2_tip_densify_20260815.md`](proof/w0815o_g2_tip_densify_20260815.md) |
| w0815n g3 tip densify (W21-G3) | general ~31.7 host rpm / fins ~3.5 | **+0** seal / raw **+17** | **W21-G3** JQ tip densify short window `2026-08-01…14` (no DEFER): general week-chunks **13p/2f** + margin_interest month retry **1p** (w=6 rpm450; 0×429) + fins tip **3p** (w=1 rpm100); tip months already COMPLETE → seal/issue **0**; receipt-plane reeval observed_end →**2026-08-14/15** C8 pass×12; fail-closed publish local=remote **3442**; FRESH `projgen-e398ed2a…`; raw **15020→15037**; Dataset COMPLETE **11**; empty **0**; DEFER densify **SKIP**; proof [`w0815n_g3_tip_densify_20260815.md`](proof/w0815n_g3_tip_densify_20260815.md) |
| w0815n g2 seal harvest (W21-G2) | — | **+0** seal/issue | **W21-G2** JQ window_ok harvest re-scan: cache-first **6682** manifests → **2824** best params-wok; params_wok unsealed **219** (earn **199** + master **20**) all DEFER; **data-Date REJECT** (earn tip `2026-08-14`; master misdate `2008-05-07`); true harvest **0**; tip densify non-DEFER **0**; DEFER densify **skip**; options **164** skip; fail-closed publish local=remote **3442**; FRESH `projgen-94809de8…`; raw mid-window **15037** (W21-G3 tip); Dataset COMPLETE **11**; empty **0**; proof [`w0815n_g2_seal_harvest_20260815.md`](proof/w0815n_g2_seal_harvest_20260815.md) |
| w0815k g6 ops (W19-G6) | — | **+0** issue / session **+2** segs | **W19-G6** continuous ops: dual-issue **coord** with peer `w0815j_g5_ops` (skip issue+publish thrash while peer ops_loop alive cycles 1–7; peer dead cycle 8+ → fail-closed publish ×N no force); ready-seal gap **0** all 12 cycles; FRESH `projgen-a0aa0e3a…`; remote COMPLETE **3440→3442** raw **15020→15020** (+0); Dataset COMPLETE **11** held; OTC **55→57** peer tip mid-window; fins_summary **218**/PARTIAL **6** held; empty **0**; **T13 DEFER** fins_summary `2008-01…06` formal + short_sale/topix/master/breakdown/earn/am/EDINET empty held; densify **not** re-run; peers not killed; general ~495 note / fins separate; proof [`w0815k_g6_ops_20260815.md`](proof/w0815k_g6_ops_20260815.md) |
| w0815j g5 ops (W18-G5) | — | **+0** issue / session **+8** segs | **W18-G5** continuous ops: ready-seal scan **0** gap all 14 cycles; dual-issue gate free; fail-closed publish ×N (no force); FRESH `projgen-3c068e1c…`; remote COMPLETE **3434→3442** raw **14997→15020** (+23); Dataset COMPLETE **11** held; OTC **49→57** peer G4 tip; fins_summary **218** held; empty **0**; DEFER D1–D9 densify **not** re-run; peers not killed; general ~495 note / fins separate; proof [`w0815j_g5_ops_20260815.md`](proof/w0815j_g5_ops_20260815.md) |
| w0815j g2 seal harvest (W18-G2) | — | **+0** seal/issue | **W18-G2** JQ window_ok harvest: cache-first scan **4626** manifests; params_wok unsealed **219** (earn **199** + master **20**) all DEFER; **data-Date REJECT** (earn tip `2026-08-14`; master misdate `2008-05-07`); true harvest **0**; tip densify non-DEFER **0**; DEFER densify **skip**; options **164** skip; fail-closed publish local=remote **3440**; FRESH reclock; raw **15020**; Dataset COMPLETE **11**; empty **0**; proof [`w0815j_g2_seal_harvest_20260815.md`](proof/w0815j_g2_seal_harvest_20260815.md) |
| w0815i g5 ops (W17-G5) | — | **+9** issue / session **+17** segs | **W17-G5** continuous ops: dual-issue gate (skip while peer options `issue_restore_fast`/`issue_receipts` + peer fins issue alive → later G5 fins_summary ready-seal **+9**); fail-closed publish ×N (no force); FRESH `projgen-a9473edc…`; remote COMPLETE **3409→3426** raw **14953→14991** (+38); Dataset COMPLETE **11** held (options via W15-G1); options segs **157→164** peer; fins_summary **200→210** (G5 **+9** + peer); empty **0**; **T15 DEFER** short_sale `2013-01…10` formal + topix/idx/master/breakdown/earn/am/EDINET empty held; densify **not** re-run; peers not killed; general ~495 note / fins separate; proof [`w0815i_g5_ops_20260815.md`](proof/w0815i_g5_ops_20260815.md) |
| w0815g g1 options (W15-G1) | — | **+29** segs / **+1** dataset COMPLETE | **W15-G1** residual options: peer densify ALIVE→DEAD 126/126; surgical full-month reagg **29/29** ready from week R2; issue **22/22** ok (+7 already COMPLETE mid-session); options segs **135→164**; `dataset_coverage` **COMPLETE** verify; fail-closed publish; FRESH `projgen-a1b1ff51…`; remote COMPLETE **3380→3421**; Dataset COMPLETE **10→11**; empty **0**; peers not killed; proof [`w0815g_g1_options_20260815.md`](proof/w0815g_g1_options_20260815.md) |
| w0815h g6 ops (W16-G6) | — | **+0** issue / session **+18** segs | **W16-G6** continuous ops: dual-issue gate (G1 `issue_restore_fast` + `issue_receipts` alive entire window → G6 owned issue **0**); fail-closed publish ×N (no force); FRESH `projgen-6899460e…`; remote COMPLETE **3391→3409** raw **14910→14953** (+43); Dataset COMPLETE **10** held; options segs **142→157** peer; OTC **48→49** peer; fins_summary **198→200** peer; empty **0**; DEFER densify **not** re-run; peers not killed; general ~495 note / fins separate; proof [`w0815h_g6_ops_20260815.md`](proof/w0815h_g6_ops_20260815.md) |
| w0815g g4 ops (W15-G4) | — | **+7** issue / session **+11** segs | **W15-G4** continuous ops: full-month ready-seal issue options **+7** (`2018-09`, `2021-03/04/05/06/07/08`); dual-issue gate (skip while G1 issue_as_ready alive); fail-closed publish (no force); FRESH `projgen-462e902c…`; remote COMPLETE **3380→3391** raw **14856→14910** (+54); Dataset COMPLETE **10** held; options segs **135→142**; OTC **45→48** peer; fins **197→198** peer; empty **0**; DEFER densify **not** re-run; peers not killed; general ~495 note / fins separate; proof [`w0815g_g4_ops_20260815.md`](proof/w0815g_g4_ops_20260815.md) |
| w0815f g4 ops (W14-G4) | — | **+8** issue / session **+13** segs | **W14-G4** continuous ops: ready-seal issue options **+8** (`2018-08/10/11/12`, `2020-03/04/06/09`); dual-issue gate (skip cycles 2–4 while G1 issue_restore_fast alive); fail-closed publish (no force); FRESH `projgen-767b7073…`; remote COMPLETE **3347→3360** raw **14657→14717** (+60); Dataset COMPLETE **10** held; options segs **105→115**; OTC **43→45** peer; fins **196→197** peer; empty **0**; DEFER densify **not** re-run; peers not killed; general ~495 note / fins separate; proof [`w0815f_g4_ops_20260815.md`](proof/w0815f_g4_ops_20260815.md) |
| w0815e g5 ops (W13-G5) | — | **+6** issue / session **+17** segs | **W13-G5** continuous ops: ready-seal issue options **+6** (`2014-05/07/08/09/10/11`); dual-issue gate (skip while G1 issue_restore_fast alive); fail-closed publish (no force); FRESH `projgen-70a08329…`; remote COMPLETE **3308→3325** raw **14408→14499** (+91); Dataset COMPLETE **10** held (futures+o225 via **W13-G3**); options segs **76→83**; OTC **34→43** peer; empty **0**; DEFER densify **not** re-run; peers not killed; general ~495 note / fins separate; proof [`w0815e_g5_ops_20260815.md`](proof/w0815e_g5_ops_20260815.md) |
| w0815e g3 ds complete (W13-G3) | — | **+0** segs / **+2** dataset COMPLETE | **W13-G3** surgical re-agg only: futures + o225 segs already **164/164** (W12-G4) with C* pass → `dataset_coverage` PARTIAL→**COMPLETE** (stale status_counts 80/84 fixed); short_ratio COMPLETE **held**; Dataset COMPLETE **8→10**; COMPLETE segs **3308** Δ**0**; fail-closed publish (no force); FRESH `projgen-155ea34a…`; empty **0**; peers not killed; proof [`w0815e_g3_dataset_complete_20260815.md`](proof/w0815e_g3_dataset_complete_20260815.md) |
| w0815d g5 ops (W12-G5) | — | **+12** issue / session **+36** segs | **W12-G5** continuous ops: ready-seal issue futures **+6** options **+6**; dual-issue gate; fail-closed publish (no force); FRESH `projgen-305d4bb4…`; remote COMPLETE **3252→3288** raw **14188→14262** (+74); Dataset COMPLETE **8** held (short_ratio via W12-G3); empty **0**; DEFER densify **not** re-run; peers not killed; general ~495 note / fins separate; proof [`w0815d_g5_ops_20260815.md`](proof/w0815d_g5_ops_20260815.md) |
| w0815 g1 general (W9-G1) | **5.82** (W3) / **~9–13** (W2) | **294+** / **46** | **W9-G1** general densify: W1 w=12 rpm495 **429 storm** aborted; W2 margin partial; W3 partition **deriv+edinet** w=6 rpm350 **193p/101f** rowsInserted **8.5M**; R2 seal map **32/32** COMPLETE (futures **+35** o225 **+16** options **+2**); FRESH `projgen-7662cb5d…`; remote COMPLETE **2854→3111** raw **13328→14131**; empty **0**; peers not killed; proof [`w0815_g1_general_20260815.md`](proof/w0815_g1_general_20260815.md) |
| w0815c g7 ops (T15–T20) | — | **+31** segs (session) | **W11-G7** ready-seal issue (G7 direct options_225 **2018-01** run **903413** + ops_loop/peers); fail-closed publish; FRESH reclock; DEFER inventory; COMPLETE **3015→3046**; raw **14067→14095**; Dataset COMPLETE **7** held; empty **0**; peers not killed; proof [`w0815c_g7_ops_20260815.md`](proof/w0815c_g7_ops_20260815.md) |
| w0815c g1 margin (T1+T2) | — | **+2** segs | **W11-G1** join G4 ready; issue alert **2024-07/2025-02** runs **903410/903412**; interest re-agg only; Dataset COMPLETE **5→7**; COMPLETE segs **3021**; FRESH `projgen-e686fa9e…`; empty **0**; peers not killed; proof [`w0815c_g1_margin_20260815.md`](proof/w0815c_g1_margin_20260815.md) |
| w0815c g3 bars residual (T5) | — | **0** (held **220**) | **W11-G3** post-floor residual verify: peer W9-G3 seal **7/7** already COMPLETE remote; densify **skipped** (residual **[]**); DEFER pre-2008-05 **52**; publish local=remote **3023**; reeval observed_end **2026-08-14** C8 lag **0**; FRESH `projgen-a47f87a2…`; empty **0**; peers not killed; proof [`w0815c_g3_bars_20260815.md`](proof/w0815c_g3_bars_20260815.md) |
| w0815c g6 edinet residual (T13–T14) | — | **0** seal | **W11-G6** seal-only (G1 dual-run ban); R2 residual nz scan cross **28** + large **42** → sealable **[]**; zero-row densify **28/28**+**42/42**; G1 empty densify **50p/0nz**; COMPLETE major/cross/large **104/76/62 held (+0)**; **DEFER_EMPTY_API**; FRESH `projgen-193e28ba…`; empty **0**; peers not killed; proof [`w0815c_g6_edinet_20260815.md`](proof/w0815c_g6_edinet_20260815.md) |
| w0815 g6 ops (continuous) | — | **147** | **W9-G6** seal→issue **+147** (runs **903247–903393**); COMPLETE **2854→3001**; raw **13269→14042** (+773); dataset COMPLETE **5**; FRESH `projgen-044f4b42…`; empty **0**; peers not killed; proof [`w0815_g6_ops_20260815.md`](proof/w0815_g6_ops_20260815.md) |
| MB solo | **10.97** | 409 | general pool |
| bars solo | **6.22** | 280 | general; 0×429; pass 264 / fail 16 |
| fins paced | **1.09–1.16** | 102 | fins pool; runner `host_jobs_per_min=1.09` |
| t5 fins family (G4 snap) | **1.34–1.37** | **76/288** | historical partial snap (superseded by FINAL) |
| t5 fins family (**FINAL**) | **1.68** | **288** | serial paced **DONE**; runner **287/1** + 2022-05 recover → unique **288**; PID dead; flag DONE |
| t5_div_pre (`fins_dividend` 2008–2017) | **4.69** | **120** | **120 pass / 0 fail**; PID **43684** natural exit; empty shells 2008-01…2013-01; nz **59** months |
| topix3 w1 / w2 | **93.48** / **62.79** | 192 / 192 | residual months (fast burst); orch re-dispatch after bars |
| t4 topix | **142.41** | 192 | all pass; burst |
| t7 master | **3.58** | 147 | 118p/29f → retry 29/29 |
| t8 misc | **9.93** | 432 | 407p/25f → retry 25/25 |
| t5 margin+earn | **7.51** | 346 | 344p/2f → retry 2/2 (2017-01/02); w=2 rpm=495 |
| merged mb+bars+topix3+fins | **12.56** | 1175 | G8 wave2 re-measure |
| merged + peers t4/t7/t8 | **17.63** | 1896 | concurrent acq included |
| w0713 t7 margin_inv (**FINAL**) | **9.61** | **970** | **G7 T9+T10 DONE**; wave1 **918p/52f** + retry **52/52** → **970/970**; C8 margin **pass** lag2; seals **+0** |
| w0713 t6_deriv_edinet | **1.52** | 60 | G6 main 41p/19f + retry 48/48; w=1 rpm=50/35; seals **+60** |
| w0713 t1 bars exec / retry | **7.16** / **7.50** | 120 / 22 | G1 close; pass 86/34 + retry 21/1 |
| w0713 t3 topix | **54.28** | 192 | all pass |
| w0713 t2 master | **4.97** | 147 | G2 close; 63p/84f (seal used R2 window-ok, not worker-pass alone) |
| w0814 g4 master residual | **23.12** / **20.3** | 21 / 21 | **G4** residual; wave1 **0p/21f** + retry **0p/21f** (400×1 + 429×20); seal window_ok **0** |
| w0814h g10 master residual | **1.28** | **21** | **W8-G10** densify **20p/1f** (400 sub `2006-08`; 0×429; w=1 rpm80); seal window_ok **0** (misdate `2008-05-07`); COMPLETE **220→220** |
| w0814 g1 bars | **13.74** | **200** | 124p/76f; max-jobs 200 natural |
| w0814 g3 topix | **34.74** | **142** | 81p/61f; seals → COMPLETE **220** |
| w0814 g2 mb residual/retry | **14.26** / **5.07** | 120 / 80 | residual **48p/72f** + retry **80p/0f**; seal+issue **+36** → COMPLETE **105** |
| w0814 g7 edinet retry | **4.26** | **36** | **36/36** pass |
| w0814 g5 fins residual | **2.0** | **48** | **G5** serial paced **48/48** pass; seal+issue **+48**; COMPLETE fins **54/47/26/26** |
| w0814 g8 misc seal | — | **80** | **G8** R2 seal+issue **+80**; C8 margin pass lag2 held; acq execute DEFER |
| w0814 all-sources G10 close | — | — | mid proof [`w0814_all_sources_wave_20260814.md`](proof/w0814_all_sources_wave_20260814.md) |
| w0814 all-sources **FINAL** | — | — | proof [`w0814_all_sources_final_20260814.md`](proof/w0814_all_sources_final_20260814.md) PRE **9687/942** → POST **10701/1376** |
| w0814b g1 bars | — | **200** | **199p/1f**; seal wave deferred / peers |
| w0814b g2 mb residual | **15.97** | **100** | **100p/0f** pre-source densify; R2 seal **32/32** + issue **+21** / peer **+11** → mb **105→137** |
| w0814b g3 idx | **4.61** | **100** | **100p/0f**; topix gap **4/4** empty DEFER; seal+issue **+96** → idx COMPLETE **33→129**; topix **220→220** |
| w0814b g6 edinet | **2.13** | **36** | **36p/0f**; seal+issue **+36** → COMPLETE **32→44** each; observed_start **`2023-01-01`** |
| w0814b g7 misc seal | — | **80** | **W2-G7** R2 seal **80/80** + issue/restore; wave months **+80** (unique restore **+34** after peer race); C8 margin **pass lag2 held**; acq execute DEFER (dry-run **660**) |
| w0814b g5 deriv residual | **~1.3** | **34+** | **W2-G5** paced rpm45; futures/o225 **2023 12/12**; options 2025 weeks cont.; seals **+27** → futures/opt/o225 **44/8/44** |
| w0814c g3 deriv residual | **~1.3** | **24+** | **W3-G3** paced rpm45; futures/o225 **2022 12/12**; options seal **2025-07…12**; seals **+30** → futures/opt/o225 **56/14/56** |
| w0814b g4 fins residual | **1.85** | **48** | **W2-G4** serial paced **48/48** pass (0×429); seal+issue **+48**; COMPLETE fins **54/47/26/26→66/59/38/38** |
| w0814c g2 fins residual | **1.81** | **48** | **W3-G2** serial paced **48/48** pass (0×429); seal+issue **+48**; COMPLETE fins **66/59/38/38→78/71/50/50** |
| w0814d g2 fins residual | **1.59** | **48** | **W4-G2** serial paced **48/48** pass (0×429); seal+issue **+46** (details tip already COMPLETE → 10); COMPLETE fins **78/71/50/50→90/81/62/62** |
| w0814e g2 fins residual | **1.33** | **48** | **W5-G2** serial paced **48/48** pass (0×429); seal+issue **+48** (12×4; div honest **2017-02…12+2019-01**); COMPLETE fins **90/81/62/62→102/93/74/74** |
| w0814g all-sources **G7 close** | — | — | proof [`w0814g_all_sources_wave_20260814.md`](proof/w0814g_all_sources_wave_20260814.md) PRE raw **12901**/COMPLETE **2646** → POST **13160/2691** (+259/+45); G7 issue margin_interest **+16** alert **+12** bars **+6** + peer G6 OTC **+8** + peer alert race **+3**; C8 pass×5; FRESH `projgen-07300919…`; empty **0**; peers not killed |
| w0814h g13 ops (T14–T18) | — | — | proof [`w0814h_g13_ops_20260814.md`](proof/w0814h_g13_ops_20260814.md) concurrent ops slice PRE raw **13056**/COMPLETE **2651** → POST **13160/2691**; G13 issue margin_alert residual **+3**; peers not killed |
| w0814g g1 bars | **6.56** | **140** | **W7-G1** acq **129p/11f** + R2 seal **25/25** + issue **+25** → COMPLETE bars **188→213**; proof [`w0814g_g1_bars_20260814.md`](proof/w0814g_g1_bars_20260814.md) |
| w0814g g2 fins residual | **1.51** | **36** | **W7-G2** serial paced **36/36** pass (0×429; details unsealed-raw **0**); R2 seal **36/36** + issue **+36** runs **903199–903234**; COMPLETE fins **114/104/86/86→126/104/98/98**; FRESH `projgen-0a9248f4…`; empty **0**; proof [`w0814g_g2_fins_20260814.md`](proof/w0814g_g2_fins_20260814.md) |
| w0815 g2 fins residual | wave1 **49.6** / wave2 **14.0** (429-storm) | plan **446** / seal **74** | **W9-G2** acq **0p/104f** 429 abort (w6→w2); window_ok seal **72/74** + issue **+72** runs **903255–903345**; COMPLETE fins **126/104/98/98→162/104/132/100**; platform **2962**; FRESH `projgen-c3ab279a…`; empty **0**; proof [`w0815_g2_fins_20260815.md`](proof/w0815_g2_fins_20260815.md) |
| w0814g g3 deriv residual | **~0.4** host jobs/min | **27+** | **W7-G3** paced options 2023-H2 weeks **27/27** + futures 2018 mid (**10p/1f** HTTP500); R2 week-merge seal+issue options **+5** (`2023-07…11` runs **903242–903246**); COMPLETE futures/opt/o225 **92/32/92→92/37/92**; kill ban held (orch alive); proof [`w0814g_g3_deriv_20260814.md`](proof/w0814g_g3_deriv_20260814.md) |
| w0815b g9 mb residual | **9.01** | **5+1** | **W10-G9** mar weeks **5/5 pass rows=0** + floor `2015-03-26…04-01` **rowsInserted=3628** (run **12408**); sealable **[]**; COMPLETE **137→137**; **DEFER_pre2015_empty**; proof [`w0815b_g9_breakdown_20260815.md`](proof/w0815b_g9_breakdown_20260815.md) |
| w0814g g5 edinet | **2.09** | **36** | **W7-G5** main **36/36** pass (0×429) + large residual **18/18** empty; seal+issue **+12** (major **+12**; cross/large **+0** empty DEFER); COMPLETE **92/76/62→104/76/62**; observed_start major **`2018-01-04`** / cross **`2020-05-01`** / large **`2021-07-01`** |
| w0814f all-sources **G7 close** | — | — | proof [`w0814f_all_sources_wave_20260814.md`](proof/w0814f_all_sources_wave_20260814.md) PRE **12481/2446** → POST **12791/2499** (+53) |
| w0814b all-sources **G9 close** | — | — | proof [`w0814b_all_sources_wave_20260814.md`](proof/w0814b_all_sources_wave_20260814.md) PRE **10702/1376** → POST **11242/1478** |
| w0814c g7 earn+am residual | — | **230** | **W3-G7** dry-run **230** (earn 199 + am 31); acq+seal **DEFER** tip-Date / today-mode; COMPLETE **1/1** held |
| w0814c g5 idx residual/retry | **7.62** / **4.02** | 95 / 28 | **W3-G5** wave1 **67p/28f** + retry **28/28** (0×429); seal+issue **+91** → idx **129→220** |
| w0814c g5 mb residual seal | — | **27** | pre-2015 probe sealable **0** → **DEFER_pre2015_empty**; COMPLETE **137→137** |
| w0814d g5 mb residual seal | — | **27** | **W4-G5** re-probe sealable **0** → **DEFER_pre2015_empty**; optional acq dry-run plan **117**/queued **50** execute DEFER; COMPLETE **137→137** |
| w0814h g9 mb residual execute | **~11–14** | **27** | **W8-G9** execute **27/27 pass** `rowsInserted=0` (0×429; w=2 rpm200); probe sealable **0** → **DEFER_pre2015_empty**; COMPLETE **137→137**; mb raw COMPLETE **998→1025** (+27 empty shells) |
| w0814d all-sources **G8 close** | — | — | proof [`w0814d_all_sources_wave_20260814.md`](proof/w0814d_all_sources_wave_20260814.md) PRE **11713/2034** → POST **11976/2074** (+40) |
| w0814e all-sources **G7 close** | — | — | proof [`w0814e_all_sources_wave_20260814.md`](proof/w0814e_all_sources_wave_20260814.md) PRE **12070/2241** → POST **12317/2283** (+42) |
| w0814e g5 edinet | **1.79** | **36** | **W5-G5** main **35p/1f** + retry cross 2020-06 + large H1 **6/6** empty; seal+issue **+20** (major **+12**, cross **+8** H2; large **+0** empty DEFER); COMPLETE **68/68/62→80/76/62**; observed_start major **`2020-01-01`** / cross **`2020-05-01`** / large **`2021-07-01`** |
| w0814d g6 edinet | **1.88** | **36** | **W4-G6** main **34p/2f** + retry large feb/may; seal+issue **+30** (major/cross **+12**, large **+6** H2; H1 empty DEFER); COMPLETE **56→68/68/62**; observed_start **`2021-01-01`** / large **`2021-07-01`** |
| w0814g g4 misc seal | — | **80** | **W7-G4** R2 seal **80/80** + issue/restore; wave months **+80** (unique restore **+33** after peer race); margin **113→129** / alert **114→130** / short_ratio **128→144** / short_sale **99→115** / investor **106→164** (wave **+16** + peer densify **+42**); C8 margin **pass lag2 held**; acq execute DEFER (dry-run **260**) |
| w0814f g4 misc seal | — | **80** | **W6-G4** R2 seal **80/80** + issue/restore; wave months **+80** (unique restore **+45** after peer race); margin **97→113** / alert **98→114** / short_ratio **112→128** / short_sale **83→99** / investor **90→106**; C8 margin **pass lag2 held**; acq execute DEFER (dry-run **340**) |
| w0814e g4 misc seal | — | **80** | **W5-G4** R2 seal **80/80** + issue/restore; wave months **+80** (unique restore **+40** after peer race); margin **81→97** / alert **82→98** / short_ratio **96→112** / short_sale **67→83** / investor **74→90**; C8 margin **pass lag2 held**; acq execute DEFER (dry-run **420**) |
| w0814d g4 misc seal | — | **80** | **W4-G4** R2 seal **80/80** + issue/restore; wave months **+80** (unique restore **+45** after peer race); margin **65→81** / alert **66→82** / short_ratio **80→96** / short_sale **51→67** / investor **58→74**; C8 margin **pass lag2 held**; acq execute DEFER (dry-run **500**) |
| w0814d g3 options residual | — | **4+** | **W4-G3** full-month options **2025-01…04** → COMPLETE **14→18**; 05/06 seal cont.; **not** killed |
| w0814e g3 deriv residual | **~0.4** host jobs/min | **52** | **W5-G3** paced **51p/1f** (1×503 retry pass); options H2 weeks + futures/o225 **2020 24/24**; R2 seal+issue **+30**; COMPLETE futures/opt/o225 **68/20/68→80/26/80**; kill ban held → WAVE_DONE |
| w0814c all-sources **G9 close** | — | — | proof [`w0814c_all_sources_wave_20260814.md`](proof/w0814c_all_sources_wave_20260814.md) PRE **11281/1727** → POST **11656/1789** (+62) |
| w0814c g4 misc seal | — | **80** | **W3-G4** R2 seal **80/80** + issue/restore; wave months **+80** (unique restore **+53** after peer race); margin **49→65** / alert **50→66** / short_ratio **64→80** / short_sale **35→51** / investor **42→58**; C8 margin **pass lag2 held**; acq execute DEFER (dry-run **580**) |
| w0713 t4 mb residual | **10.34** | 44 | G4 close; last-state week-jobs **40p/4f** |
| proof | — | — | G1–G9 + w0814 FINAL + w0814b/c/d + **w0814e G3 deriv +30** + G2 fins +48 + G4 misc +80 + G5 edinet + G6/G7 peers 20260814 |

### observed_* (remote D1, key datasets)

| dataset | status | COMPLETE segs | observed_start | observed_end | raw manifests (COMPLETE) | notes |
|---------|--------|--------------:|----------------|--------------|--------------------------:|-------|
| `equities_bars_daily` | **PARTIAL** | **220** | **`2008-05-01`** | **`2026-08-14`** | n=3659 / c=3158 / nz=2917 | prior **213** + **W9-G3 w0815_g3_bars +7** (`2013-05/07` + `2025-06…10`); **W11-G3 w0815c_g3_bars** residual verify post-floor PARTIAL **0**; pre-2008-05 DEFER **52**; C8 **pass** lag **0**; worker pass ≠ COMPLETE; proof [`w0815c_g3_bars_20260815.md`](proof/w0815c_g3_bars_20260815.md) |
| `indices_bars_daily_topix` | **PARTIAL** | **220** | **`2008-01-01`** | **`2026-08-15`** | — | COMPLETE segs **220**; gap `2008-01…04` empty DEFER re-verified **W10-G8 w0815b_g8** acq **4/4** `row_count=0` (runs **12348–12353**; R2 `{"data":[]}`); C8 **pass** lag **0**; dataset **not** COMPLETE (human-gate: contract floor→`2008-05-01` + prune; proof [`w0815b_g8_topix_indices_20260815.md`](proof/w0815b_g8_topix_indices_20260815.md)) |
| `equities_master` | **PARTIAL** | **220** | **`2006-08-13`** | **`2026-08-13`** | — | **G2** COMPLETE **94→220 (+126)**; **G4** residual acq **0p/21f×2** window_ok **0**; **W8-G10 w0814h_g10_master** densify **20p/1f** (w1 rpm80; 0×429) + newest R2 still misdate `2008-05-07` → seal **0** COMPLETE **220→220**; DEFER **21** misdate + **73** pre-plan `2000-07…2006-07`; C8 **pass** lag **1**; scd2 hot |
| `markets_breakdown` | **PARTIAL** | **137** | **`2015-03-26`** | **`2026-08-14`** | — | prior **105** + **W2-G2 +32** → **137**; **W8-G9** + **W10-G9 w0815b_g9** re-probe sealable **0** / floor densify **rowsInserted=3628** run **12408** (`2013-01…2015-02` empty + `2015-03` thin) **DEFER_pre2015_empty**; contract `history_target` **2013-01-04** held; C8 **pass** lag **1**; proof [`w0815b_g9_breakdown_20260815.md`](proof/w0815b_g9_breakdown_20260815.md) |
| `fins_summary` | **PARTIAL** | **218** | **`2008-07-01`** | **`2026-08-14`** | — | prior **198** + **W17 peers/G5 issue** → **210** + **W17-G2 tip residual** → **218** held; PARTIAL residual **6** (`2008-01…06` empty shells) **W19-G6 T13 DEFER formal** (W18-G1 R2 empty proof); C8 **pass**; dataset **not** COMPLETE; proof [`w0815k_g6_ops_20260815.md`](proof/w0815k_g6_ops_20260815.md), [`w0815j_g1_fins_summary_20260815.md`](proof/w0815j_g1_fins_summary_20260815.md) |
| `markets_margin_interest` | **COMPLETE** | **164**/164 | **`2013-01-04`** | **`2026-08-13`** | — | segs full prior waves; **W11-G1** surgical re-aggregate + fail-closed publish → **`dataset_coverage=COMPLETE`**; **C8 pass** lag **2** held; proof [`w0815c_g1_margin_20260815.md`](proof/w0815c_g1_margin_20260815.md) |
| `markets_margin_alert` | **COMPLETE** | **164**/164 | **`2012-12-28T00:00:00+09:00`** | **`2026-08-12`** | — | residual **`2024-07`/`2025-02`** issue runs **903410/903412** (G4 raw + lock-retry upsert); **W11-G1** re-aggregate → **COMPLETE**; proof [`w0815c_g1_margin_20260815.md`](proof/w0815c_g1_margin_20260815.md) |
| `equities_earnings_calendar` | **PARTIAL** | **1** | **`2010-01-04`** | **`2026-08-14`** | — | **W3-G7** residual dry-run **199**; R2 scan window_ok **0/180** tip-dated `Date`; acq+seal **DEFER**; C8 **pass** lag **0**; COMPLETE only **2026-08** |
| `markets_short_ratio` | **PARTIAL** | **150** | **`2013-01-04`** | **`2026-08-13`** | — | prior **128** + **W7-G4 misc +16** `2021-01…2022-04` (runs **903179–903194**); C8 **pass** lag **1** |
| `markets_calendar` | **COMPLETE** | 224 | 2008-01-01 | 2026-08-12 | — | sticky full + aggregate fix |
| `jsda_tokyo_repo_rates` | **COMPLETE** | 1 | 2012-10-29 | 2026-08-10 | — | dataset COMPLETE **receipt-owned** (G9); D1 **hot tip 252** (`>=2026-07-01`); full history **R2 + local mirror 30303** (mirror not SoT; **not loss**) via `publish_jsda_hot_to_d1.py` ([`jsda_hot_d1_publish_20260815.md`](proof/jsda_hot_d1_publish_20260815.md); CF-SoT honesty [`column_null_audit_20260815.md`](proof/column_null_audit_20260815.md)) |
| `jsda_otc_bond_reference_prices` | **PARTIAL** | **72** | **`2026-05-27`** | **`2026-08-17`** | — | prior **57** + **W21-G1 tip +15** → **72** (G4 ops publish absorb); history **DEFER** site timeout (D5); dataset **not** COMPLETE; proof [`w0815n_g1_jsda_otc_20260815.md`](proof/w0815n_g1_jsda_otc_20260815.md), [`w0815n_g4_ops_20260815.md`](proof/w0815n_g4_ops_20260815.md) |
| `jsda_corporate_bond_transactions` | **COMPLETE** | **12** | **`2015-11-02`** | **`2026-08-14`** | — | **G9 +11** full annual TORIHIKI2015–2026 (runs **901244–901255**); dataset **COMPLETE** |
| `fins_details` | **PARTIAL** | **104** | **`2018-01-01`** | **`2026-08-14`** | — | continuous **2018-01…2026-08**; **W9-G2** unsealed-with-raw **0** (no seal this wave); C8 **pass** lag **1**; dataset **not** COMPLETE |
| `equities_investor_types` | **COMPLETE** | **164** | **`2012-12-28`** | **`2026-08-12`** | — | inventory **164/164** since **W8-G12 T13**; **W10-G12** surgical re-aggregate promoted `dataset_coverage` PARTIAL→**COMPLETE** (stale status_counts 106/58 fixed); C8 **pass**; proof [`w0815b_g12_complete_divergence_20260815.md`](proof/w0815b_g12_complete_divergence_20260815.md) |
| `equities_bars_daily_am` | **PARTIAL** | **1** | **`2026-08-01`** | **`2026-08-13`** | n=112 / nz=37 | **W3-G7** dry-run **31** (`endpoint_query_mode=today`); nz raw tip-day only; window_ok **0**; acq+seal **DEFER**; C8 **pass** lag **1**; COMPLETE only **2026-08** |
| `edinet_cross_shareholdings` | PARTIAL | **76** | **`2020-05-01`** | **`2026-08-14`** | nz=104 (none residual) | COMPLETE **76**/104; residual **28** `2018-01…2020-04`; **W11-G6 w0815c_g6** R2 residual nz scan sealable **[]** (zero-row densify **28/28** + G1 empty_pass **20**/nz **0**); **DEFER_EMPTY_API**; C8 **pass** lag **1**; dataset **not** COMPLETE; proof [`w0815c_g6_edinet_20260815.md`](proof/w0815c_g6_edinet_20260815.md) |
| `edinet_major_shareholders` | **COMPLETE** | **104** | **`2018-01-04`** | **`2026-08-14`** | — | segs **104/104** since **W7-G5**; `dataset_coverage=COMPLETE` (W10-G12); **W11-G6** verify-only (skip re-acq); C8 **pass** lag **1** |
| `edinet_large_volume_shareholders` | PARTIAL | **62** | **`2021-07-01`** | **`2026-08-14`** | nz=133 (none residual) | COMPLETE **62**/104; residual **42** `2018-01…2021-06`; **W11-G6 w0815c_g6** R2 residual nz scan sealable **[]** (zero-row densify **42/42** + G1 empty_pass **30**/nz **0**); **DEFER_EMPTY_API**; C8 **pass** lag **1**; dataset **not** COMPLETE; proof [`w0815c_g6_edinet_20260815.md`](proof/w0815c_g6_edinet_20260815.md) |
| `fins_dividend` | **PARTIAL** | **132** | **`2013-02-01`** | **`2026-08-14`** | — | prior **98** + **W9-G2 +34** (`2021-02…2022-02` + `2022-05…2023-12` + `2026-05`); gap **2022-03/04** empty pages; residual **2024-01…2026-04**; C8 **pass** lag **1**; dataset **not** COMPLETE |
| `fins_earnings_date` | **PARTIAL** | **100** | **`2018-01-01`** | **`2026-12-11`** (future-dated events) | — | prior **98** + **W9-G2 +2** (`2026-05/06`); hole **2026-01…04** no_raw; **W19-G2** seal-first window_ok **0** densify skip (empty shells); C8 **pass** lag **1**; dataset **not** COMPLETE; proof [`w0815k_g2_fins_earn_20260815.md`](proof/w0815k_g2_fins_earn_20260815.md) |
| `markets_short_sale_report` | PARTIAL | **115** | **`2012-01-10`** | **`2026-08-13`** | — | prior **99** + **W7-G4 misc +16** `2021-11…2023-02` (runs **903162–903177**); C8 **pass** lag **1**; observed_start reeval **2012-01-10** |
| `indices_bars_daily` | PARTIAL | **220** | **`2008-05-01`** | **`2026-08-14`** | — | COMPLETE segs **220**; residual PARTIAL **4** (`2008-01…04` empty DEFER re-verified **W10-G8 w0815b_g8** acq **4/4** `row_count=0` runs **12360/12364/12369/12381**); observed_start **2008-05-01** held; C8 **pass** lag **1**; dataset **not** COMPLETE (proof [`w0815b_g8_topix_indices_20260815.md`](proof/w0815b_g8_topix_indices_20260815.md)) |
| `derivatives_bars_daily_futures` | **COMPLETE** | **164** | **`2013-01-04`** | **`2026-08-14`** | — | segs **164/164** since **W12-G4** residual seal; **W13-G3** surgical re-aggregate promoted `dataset_coverage` PARTIAL→**COMPLETE** (stale status_counts 80/84 fixed); C8 **pass** lag **1**; proof [`w0815e_g3_dataset_complete_20260815.md`](proof/w0815e_g3_dataset_complete_20260815.md) |
| `derivatives_bars_daily_options` | **COMPLETE** | **164** | **`2013-01-04`** | **`2026-08-14`** | — | segs **164/164** via **W15-G1** surgical full-month reagg of week densify R2 (**29** residual months `2018-09`+`2021-03…2023-06`) + issue; `dataset_coverage` **COMPLETE** (C1–C5+C8 pass); residual PARTIAL **0**; proof [`w0815g_g1_options_20260815.md`](proof/w0815g_g1_options_20260815.md) |
| `derivatives_bars_daily_options_225` | **COMPLETE** | **164** | **`2013-01-04`** | **`2026-08-14`** | — | segs **164/164** since **W12-G4** residual seal; **W13-G3** surgical re-aggregate promoted `dataset_coverage` PARTIAL→**COMPLETE** (stale status_counts 80/84 fixed); C8 **pass** lag **1**; proof [`w0815e_g3_dataset_complete_20260815.md`](proof/w0815e_g3_dataset_complete_20260815.md) |

## Proof index (aggregate — do not orphan)

### Continuous collect ops (W30–W33)
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/w0815z_w33_collect_ops_20260815.md`](proof/w0815z_w33_collect_ops_20260815.md) | **W33 / w0815z** T1–T3: COMPLETE **Δ0** primary · tip raw **+56** secondary; general 27p/0f @495 · fins 3p/0f @100 · 0×429; JSDA OTC **72** FULL_OK_NEW **0**; post_floor_sealable **0** densify **none**; FRESH `projgen-061b5d38668a4e6d8537757c28350d78`; empty COMPLETE **0**; Phase7 OFF; push SHA lock |
| [`docs/proof/w0815y_w32_collect_ops_20260815.md`](proof/w0815y_w32_collect_ops_20260815.md) | **W32 / w0815y**: COMPLETE **Δ0** · raw **+30**; FRESH `projgen-b5f2325c…`; OTC **72**; densify none |
| [`docs/proof/w0815x_w31_collect_ops_20260815.md`](proof/w0815x_w31_collect_ops_20260815.md) | **W31 / w0815x**: COMPLETE **Δ0** · raw **+56**; FRESH `projgen-20ecd21e…`; OTC **72**; densify none |
| [`docs/proof/w0815w_w30_collect_ops_20260815.md`](proof/w0815w_w30_collect_ops_20260815.md) | **W30 / w0815w**: COMPLETE **Δ0** · raw **+56**; FRESH `projgen-c4240127…`; OTC **72**; densify none |

### Floor catalog / NO_DENSIFY / ops close (W29)
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/observed_floor_catalog_20260815.md`](proof/observed_floor_catalog_20260815.md) | **W29-G1 / w0815v**: unified observed floors vs `history_target_start` for all residual + COMPLETE governed datasets; **12** contract raise **proposals** (0 implemented); **NO_DENSIFY_FIXED** 18 classes; floors locked; tip densify secondary; CF-SoT held; empty-raw ban held |
| [`docs/proof/w0815v_w29_floor_contract_ops_20260815.md`](proof/w0815v_w29_floor_contract_ops_20260815.md) | **W29 T11–T14 close**: parallel agent split; COMPLETE **Δ0** primary · tip raw **+30** secondary; post_floor **NO_HOLES** closed **0**; contract changes **none**; FRESH `projgen-76084a30…`; HAS_RAW_SEALABLE **0**; empty COMPLETE **0**; last_run no peer kill; push SHA lock |

### Column / NULL audit (W20)
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/column_null_audit_20260815.md`](proof/column_null_audit_20260815.md) | **W20-G5 unified** merge G1–G4: dataset×key tables; always-null list + cause class; **tokyo_repo_rows=0** plane-split; per-dataset 問題なし/要修正/DEFER; Mass NO-GO; **W24-G1 §9 re-verify 2026-08-15 10:34JST** CF SoT HOLDS (master short typed + fins/margin no key drop; no new bugs) |
| [`docs/proof/w0815m_g4_jsda_audit_20260815.md`](proof/w0815m_g4_jsda_audit_20260815.md) | **W20-G4**: JSDA tokyo_repo honesty + OTC/corp/repo field coverage; `storage_plane_status` divergence flags |

### COMPLETE seals
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/w0815r_g5_ops_20260815.md`](proof/w0815r_g5_ops_20260815.md) | **W25-G5 w0815r_g5_ops** T11–T16: continuous ops dual-coord with peer `w0815q_g6_ops` + fail-closed publish; G5 ready-seal issue **+0** (ready gap empty); remote COMPLETE **3457→3457** raw **15102→15125** (+23 peer); Dataset COMPLETE **11** held; OTC **72** held; FRESH `projgen-9ee87879…`; empty **0**; DEFER D1–D10 densify **not** re-run; last_run monitor no peer kill; **CF-SoT** language confirmed (W24-G1+W25-G1); peers not killed |
| [`docs/proof/w0815n_g4_ops_20260815.md`](proof/w0815n_g4_ops_20260815.md) | **W21-G4 w0815n_g4_ops**: continuous ops dual-issue + peer-ops gate (defer publish ×10 while `w0815o_g4_ops` alive) + fail-closed final publish; G4 ready-seal issue **+0** (ready gap empty); remote COMPLETE **3442→3457** raw **15020→15057** (+37); Dataset COMPLETE **11** held; OTC **57→72** peer **W21-G1**; FRESH `projgen-7b3b8bf6…`; empty **0**; DEFER D1–D10 densify **not** re-run (short_sale `2013-01…10` + fins_summary `2008-01…06` + empty families held); peers not killed |
| [`docs/proof/w0815k_g6_ops_20260815.md`](proof/w0815k_g6_ops_20260815.md) | **W19-G6 w0815k_g6_ops**: continuous ops dual-coord with peer `w0815j_g5_ops` + fail-closed publish; G6 ready-seal issue **+0** (ready gap empty); remote COMPLETE **3440→3442** raw **15020** held; Dataset COMPLETE **11** held; OTC **55→57** peer tip; FRESH `projgen-a0aa0e3a…`; empty **0**; **T13 DEFER** fins_summary residual **`2008-01…06`** formal + short_sale/topix/master/breakdown/earn/am/EDINET empty held; densify **not** re-run; peers not killed |
| [`docs/proof/w0815j_g5_ops_20260815.md`](proof/w0815j_g5_ops_20260815.md) | **W18-G5 w0815j_g5_ops**: continuous ops dual-issue gate + fail-closed publish; G5 ready-seal issue **+0** (ready gap empty); remote COMPLETE **3434→3442** raw **14997→15020** (+23); Dataset COMPLETE **11** held; OTC **49→57** peer G4; FRESH `projgen-3c068e1c…`; empty **0**; DEFER D1–D9 densify **not** re-run (short_sale `2013-01…10` + empty families held); peers not killed |
| [`docs/proof/w0815i_g5_ops_20260815.md`](proof/w0815i_g5_ops_20260815.md) | **W17-G5 w0815i_g5_ops**: continuous ops dual-issue gate + fail-closed publish; G5 ready-seal issue fins_summary **+9**; remote COMPLETE **3409→3426** raw **14953→14991** (+38); Dataset COMPLETE **11** held; options **157→164** peer; FRESH `projgen-a9473edc…`; empty **0**; **T15 DEFER** short_sale `2013-01…10` formal + topix/idx/master/breakdown/earn/am/EDINET empty held; densify **not** re-run; peers not killed |
| [`docs/proof/w0815g_g1_options_20260815.md`](proof/w0815g_g1_options_20260815.md) | **W15-G1 w0815g_g1_options**: residual options surgical full-month reagg **29/29** from week R2 (peer densify 126/126 not killed); issue **22/22**; options segs **135→164** + `dataset_coverage` **COMPLETE**; Dataset COMPLETE **10→11**; FRESH `projgen-a1b1ff51…`; remote COMPLETE **3380→3421**; empty **0**; peers not killed |
| [`docs/proof/w0815g_g4_ops_20260815.md`](proof/w0815g_g4_ops_20260815.md) | **W15-G4 w0815g_g4_ops**: continuous ops full-month ready-seal issue options **+7**; dual-issue gate (skip while G1 issue_as_ready alive); fail-closed publish; FRESH `projgen-462e902c…`; remote COMPLETE **3380→3391** raw **14856→14910** (+54); Dataset COMPLETE **10** held; options **135→142**; OTC **45→48** peer; fins **197→198** peer; empty **0**; DEFER densify **not** re-run; peers not killed |
| [`docs/proof/w0815f_g4_ops_20260815.md`](proof/w0815f_g4_ops_20260815.md) | **W14-G4 w0815f_g4_ops**: continuous ops ready-seal issue options **+8**; dual-issue gate (skip while G1 issue_restore_fast alive); fail-closed publish; FRESH `projgen-767b7073…`; remote COMPLETE **3347→3360** raw **14657→14717** (+60); Dataset COMPLETE **10** held; options **105→115**; OTC **43→45** peer; fins **196→197** peer; empty **0**; DEFER densify **not** re-run; peers not killed |
| [`docs/proof/w0815e_g5_ops_20260815.md`](proof/w0815e_g5_ops_20260815.md) | **W13-G5 w0815e_g5_ops**: continuous ops ready-seal issue options **+6**; dual-issue gate; fail-closed publish; FRESH `projgen-70a08329…`; remote COMPLETE **3308→3325** raw **14408→14499** (+91); Dataset COMPLETE **10** held (futures+o225 via W13-G3); options **76→83**; OTC **34→43** peer; empty **0**; DEFER densify **not** re-run; peers not killed |
| [`docs/proof/w0815e_g3_dataset_complete_20260815.md`](proof/w0815e_g3_dataset_complete_20260815.md) | **W13-G3 w0815e_g3**: surgical re-agg only — futures + o225 segs already **164/164** (W12-G4) C* pass → `dataset_coverage` PARTIAL→**COMPLETE** (stale status_counts 80/84→164); short_ratio COMPLETE **held**; Dataset COMPLETE **8→10**; COMPLETE segs **3308** Δ**0**; fail-closed publish; FRESH `projgen-155ea34a…`; empty **0**; peers not killed |
| [`docs/proof/w0815_g1_general_20260815.md`](proof/w0815_g1_general_20260815.md) | **W9-G1 w0815_g1_general**: general densify (W1 429-storm abort; W2 margin partial; W3 deriv+edinet partition w=6 rpm350 host **5.82**/min **193p/101f** rows **8.5M**); R2 seal map **32/32** (futures **2013**/`2018` + o225 **2018** + options **2023-12**); issue unique runs **903435–903505** band; COMPLETE futures/opt/o225 **92/37/92→127/39/108** (+35/+2/+16); platform remote **2854→3111** raw **13328→14131**; observed_start futures/o225/options **`2013-01-04`**; FRESH `projgen-7662cb5d…`; empty **0**; peers not killed |
| [`docs/proof/w0815c_g6_edinet_20260815.md`](proof/w0815c_g6_edinet_20260815.md) | **W11-G6 T13–T14 w0815c_g6_edinet**: residual R2 nz scan only (G1 dual-run ban / seal-only); cross residual **28** + large residual **42** sealable **[]** (all empty-shell densified; G1 **50** empty_pass / **0** nz); major **104/104** verify skip; COMPLETE **104/76/62→104/76/62 (+0)**; **DEFER_EMPTY_API** re-try when nz manifests appear; empty **0**; FRESH `projgen-193e28ba…`; peers not killed |
| [`docs/proof/w0815c_g3_bars_20260815.md`](proof/w0815c_g3_bars_20260815.md) | **W11-G3 w0815c_g3_bars** residual verify (non-DEFER): PRE COMPLETE **220**/PARTIAL **52** (all pre-2008-05 DEFER); peer W9-G3 seal **7/7** held; densify skip; publish **3023**; reeval observed_end **2026-08-14** C8 lag **0**; FRESH `projgen-a47f87a2…`; empty **0**; peers not killed |
| [`docs/proof/w0815_g3_bars_20260815.md`](proof/w0815_g3_bars_20260815.md) | **W9-G3 w0815_g3_bars** residual seal **+7**: week-combine R2 seal **7/7** (`2013-05/07` + `2025-06…10`); issue runs **903254/903370–903373/903384/903409**; COMPLETE bars **213→220**; empty **0** |
| [`docs/proof/w0815b_g12_complete_divergence_20260815.md`](proof/w0815b_g12_complete_divergence_20260815.md) | **W10-G12 T19**: reconcile Dataset COMPLETE **3** (`dataset_coverage`) vs **5** (`backfill_status`); investor **164/164** + edinet_major **104/104** surgical re-aggregate → dataset COMPLETE **5**; fail-closed publish; empty **0**; FRESH reclock; peers not killed |
| [`docs/proof/w0814g_g1_bars_20260814.md`](proof/w0814g_g1_bars_20260814.md) | **W7-G1 w0814g_g1_bars**: week-chunk acq **140** (**129p/11f** host **6.56**/min 0×429); R2 week-combine seal **25/25** (`2023-01…12` + `2024-04…12` + `2025-01/02/03/05`); issue **+25** (runs **903053–903241** band); COMPLETE bars **188→213** (+25); platform **2849**; observed_start **`2008-05-01`** held; C8 pass lag 1; empty **0**; FRESH `projgen-44485224…`; peers not killed |
| [`docs/proof/w0814g_g3_deriv_20260814.md`](proof/w0814g_g3_deriv_20260814.md) | **W7-G3 w0814g_g3_deriv residual**: paced options 2023-H2 **27/27** + futures 2018 mid; R2 week-merge seal **5/5**; issue **+5** (runs **903242–903246**); COMPLETE futures/opt/o225 **92/32/92→92/37/92** (+0/+5/+0); platform **2854**; C8 pass×3; empty **0**; kill ban held; FRESH `projgen-a5a69f19…` |
| [`docs/proof/w0814g_g4_misc_20260814.md`](proof/w0814g_g4_misc_20260814.md) | **W7-G4 w0814g_g4_misc** next seal wave: dry-run **260** (execute DEFER); R2 seal **80/80** (`2021-01…2022-04` ×3 + short_sale `2021-11…2023-02` + investor `2021-09…2022-12`); issue/restore; COMPLETE margin **113→129** / alert **114→130** / short_ratio **128→144** / short_sale **99→115** / investor **106→164** (**+80** wave months; unique restore **+33** after peer race; investor densify peers **+42** beyond map); **C8 margin pass lag2 held**; platform **2802**; empty **0**; FRESH `projgen-eef8d845…` |
| [`docs/proof/w0814g_g5_edinet_20260814.md`](proof/w0814g_g5_edinet_20260814.md) | **W7-G5 w0814g_g5_edinet**: acq 2018 **36/36** host **2.09**/min (0×429) + large residual **18/18** empty re-probe; R2 seal **12/12** nz (major 12; cross/large empty DEFER); issue **+12** (runs **903146–903157**); COMPLETE major/cross/large **92/76/62→104/76/62** (+12/+0/+0); platform POST **2765**; observed_start major **`2018-01-04`** / cross **`2020-05-01`** / large **`2021-07-01`**; C8 pass lag 4/4/1; empty **0**; FRESH `projgen-9ca76e5b…` |
| [`docs/proof/w0814g_all_sources_wave_20260814.md`](proof/w0814g_all_sources_wave_20260814.md) | **W7-G7 w0814g all-sources close**: PRE tip `fc55930` raw **12901** COMPLETE **2646** → POST raw **13160** COMPLETE **2691** (+45); margin_interest **113→129** / alert **114→129** / bars **188→194** / OTC **26→34**; reeval×5 C8 pass (margin lag2 held); FRESH `projgen-07300919…`; empty **0**; peers not killed |
| [`docs/proof/w0814h_g13_ops_20260814.md`](proof/w0814h_g13_ops_20260814.md) | **W8-G13 w0814h_g13_ops T14–T18**: ready-seal issue **+3** margin_alert residual (`2021-08`/`2022-01`/`2022-03`); concurrent ops slice with W7-G7 publish window; empty **0**; peers not killed |
| [`docs/proof/w0815b_g8_topix_indices_20260815.md`](proof/w0815b_g8_topix_indices_20260815.md) | **W10-G8 w0815b_g8 T1+T2** topix/idx residual `2008-01…04` re-verify: acq **8/8** pass (rpm **80** w1; 0×429); R2+D1 **row_count=0** (topix **12348–12353** / idx **12360–12381**); **no seal**; COMPLETE **220/220 held**; empty **0**; FRESH `projgen-6ffab6ba…`; dataset COMPLETE **NO** — human-gate contract floor `2008-05-01` + prune |
| [`docs/proof/w0814h_g8_topix_indices_20260814.md`](proof/w0814h_g8_topix_indices_20260814.md) | **W8-G8 T1+T2** topix/idx residual `2008-01…04` re-verify: acq **8/8** pass (rpm **80** w1; 0×429); R2+D1 **row_count=0** all months (runs topix **11570–11574** / idx **11576–11603**); **no seal**; COMPLETE **220/220 → 220/220 (+0)**; empty **0**; FRESH `projgen-c61de815…`; peers not killed; dataset COMPLETE **blocked** by empty API class |
| [`docs/proof/w0814f_g3_deriv_20260814.md`](proof/w0814f_g3_deriv_20260814.md) | **W6-G3 w0814f_g3_deriv residual**: paced acq options 2024-H1 weeks + futures/o225 **2019** (**50p/1f** 500-retry); R2 seal **30/30**; issue **+30** (runs **903008–903037**); COMPLETE futures/opt/o225 **80/26/80→92/32/92**; platform **2646**; C8 pass×3; empty **0**; kill ban held; FRESH `projgen-ec2c02f2…` |
| [`docs/proof/w0814f_g4_misc_20260814.md`](proof/w0814f_g4_misc_20260814.md) | **W6-G4 w0814f_g4_misc** next seal wave: dry-run **340** (execute DEFER); R2 seal **80/80** (`2019-09…2020-12` ×3 + short_sale `2020-07…2021-10` + investor holes/`2020-08…2021-08`); issue/restore; COMPLETE margin **97→113** / alert **98→114** / short_ratio **112→128** / short_sale **83→99** / investor **90→106** (**+80** wave); unique restore **+45** after peer race; **C8 margin pass lag2 held**; platform **2551**; empty **0**; FRESH `projgen-d0ba7aaa…` |
| [`docs/proof/w0814f_g5_edinet_20260814.md`](proof/w0814f_g5_edinet_20260814.md) | **W6-G5 w0814f_g5_edinet**: acq 2019 **36/36** host **2.89**/min (0×429) + large residual **18/18** empty re-probe; R2 seal **12/12** nz (major 12; cross/large empty DEFER); issue **+12** (runs **902885–902896**); COMPLETE major/cross/large **80/76/62→92/76/62** (+12/+0/+0); platform POST **2506**; observed_start major **`2019-01-01`** / cross **`2020-05-01`** / large **`2021-07-01`**; C8 pass lag 4/4/1; empty **0**; FRESH `projgen-9facca2d…` |
| [`docs/proof/w0814f_all_sources_wave_20260814.md`](proof/w0814f_all_sources_wave_20260814.md) | **W6-G7 w0814f all-sources close**: PRE raw **12481**/COMPLETE **2446** → POST **12791/2499** (+53); G7 issue margin **+16/+16** short_ratio **+3** bars **+7** edinet_major **+5** + peer G6 OTC **+6**; C8 pass×5; FRESH `projgen-83bd002e…`; empty **0**; peers not killed |
| [`docs/proof/w0814e_g3_deriv_20260814.md`](proof/w0814e_g3_deriv_20260814.md) | **W5-G3 w0814e_g3_deriv residual**: paced acq options H2 weeks + futures/o225 **2020** (**51p/1f** 503-retry); R2 seal **30/30**; issue **+30** (runs **902807–902836**); COMPLETE futures/opt/o225 **68/20/68→80/26/80**; platform **2446**; C8 pass×3; empty **0**; kill ban held; FRESH `projgen-66629f92…` |
| [`docs/proof/w0814e_g2_fins_20260814.md`](proof/w0814e_g2_fins_20260814.md) | **W5-G2 w0814e_g2_fins residual**: acq **48/48** host **1.33**/min (0×429); R2 seal **48/48**; issue **+48** (12×4; runs **902734–902781**); fins COMPLETE **90/81/62/62→102/93/74/74**; platform **2391**; C8 pass×4; empty **0**; fins pool only; FRESH `projgen-f215f184…` |
| [`docs/proof/w0814e_g4_misc_20260814.md`](proof/w0814e_g4_misc_20260814.md) | **W5-G4 w0814e_g4_misc** next seal wave: dry-run **420** (execute DEFER); R2 seal **80/80** (`2018-05…2019-08` ×4 + short_sale `2019-03…2020-06`); issue/restore; COMPLETE margin **81→97** / alert **82→98** / short_ratio **96→112** / short_sale **67→83** / investor **74→90** (**+80** wave); unique restore **+40** after peer race; **C8 margin pass lag2 held**; platform **2343**; empty **0**; FRESH `projgen-56eacf5d…` |
| [`docs/proof/w0814e_g5_edinet_20260814.md`](proof/w0814e_g5_edinet_20260814.md) | **W5-G5 w0814e_g5_edinet**: acq 2020 **36** (main 35p/1f + retry cross Jun) host **1.79**/min (0×429) + large H1 **6/6** empty re-probe; R2 seal **20/20** nz (major 12 + cross H2 8; large empty DEFER); issue **+20** (runs **902674–902693**); COMPLETE major/cross/large **68/68/62→80/76/62** (+12/+8/+0); platform POST **2303**; observed_start major **`2020-01-01`** / cross **`2020-05-01`** / large **`2021-07-01`**; C8 pass lag 4/4/1; empty **0**; FRESH `projgen-60481611…` |
| [`docs/proof/w0814d_g2_fins_20260814.md`](proof/w0814d_g2_fins_20260814.md) | **W4-G2 w0814d_g2_fins residual**: acq **48/48** host **1.59**/min (0×429); R2 seal **46/46**; issue **+46** (12+10+12+12; runs **902566–902611**); fins COMPLETE **78/71/50/50→90/81/62/62**; platform **2221**; C8 pass×4; empty **0**; fins pool only; FRESH `projgen-32918dfa…` |
| [`docs/proof/w0814d_g3_deriv_20260814.md`](proof/w0814d_g3_deriv_20260814.md) | **W4-G3 w0814d_g3_deriv residual**: acq futures/o225 **2021 24/24** host ~rpm45; options seal **2025-01…06** (peer H1 weeks left alive); R2 seal+issue **+30**; COMPLETE futures/opt/o225 **56/14/56→68/20/68**; platform **2175**; C8 pass×3; empty **0**; FRESH `projgen-f2423bee…` |
| [`docs/proof/w0814d_g4_misc_20260814.md`](proof/w0814d_g4_misc_20260814.md) | **W4-G4 w0814d_g4_misc** next seal wave: dry-run **500** (execute DEFER); R2 seal **80/80** (`2017-01…2018-04` ×4 + short_sale `2017-11…2019-02`); issue/restore; COMPLETE margin **65→81** / alert **66→82** / short_ratio **80→96** / short_sale **51→67** / investor **58→74** (**+80** wave); unique restore **+45** after peer race; **C8 margin pass lag2 held**; platform **2163**; empty **0**; FRESH `projgen-2432d9e0…` |
| [`docs/proof/w0814d_g6_edinet_20260814.md`](proof/w0814d_g6_edinet_20260814.md) | **W4-G6 w0814d_g6_edinet**: acq 2021 **36** (main 34p/2f + retry feb/may) host **1.88**/min (0×429); R2 seal **30/30** nz (major/cross 12 + large H2 6; H1 empty DEFER); issue **+30** (runs **902467–902496**); COMPLETE major/cross/large **56→68/68/62** (+12/+12/+6); platform POST **2106**; observed_start **`2021-01-01`** / large **`2021-07-01`**; C8 pass lag 4/4/1; empty **0**; FRESH `projgen-96816054…` |
| [`docs/proof/w0814d_all_sources_wave_20260814.md`](proof/w0814d_all_sources_wave_20260814.md) | **W4-G8 w0814d all-sources close**: PRE tip `f9bf2e1` raw **11713** COMPLETE **2034** → POST raw **11976** COMPLETE **2074** (+40); margin **81**/alert **82**/short_ratio **83**/options **18**/OTC **18**; reeval×5 C8 pass (margin lag2 held); FRESH `projgen-05052c4e…`; empty **0**; peers not killed |
| [`docs/proof/w0814d_g5_mb_20260814.md`](proof/w0814d_g5_mb_20260814.md) | **W4-G5 w0814d_g5_mb**: residual seal re-probe sealable **0** pre-2015 **DEFER_pre2015_empty** (empty shells **26** + thin `2015-03` max_rows **3628**); optional acq dry-run plan **117**/queued **50** execute **DEFER**; COMPLETE **137→137 (+0)**; C8 pass lag1; empty **0**; FRESH `projgen-075b61ae…` |
| [`docs/proof/w0815b_g9_breakdown_20260815.md`](proof/w0815b_g9_breakdown_20260815.md) | **W10-G9 w0815b_g9_breakdown**: re-probe residual 27 sealable **[]**; mar weeks 5/5 rows=0 + floor `2015-03-26…04-01` **3628**; COMPLETE **137→137**; observed_start **2015-03-26**; empty **0**; **DEFER_pre2015_empty** |
| [`docs/proof/w0814h_g9_breakdown_20260814.md`](proof/w0814h_g9_breakdown_20260814.md) | **W8-G9 w0814h_g9_mb**: residual execute **27/27 pass** `rowsInserted=0` (w=2 rpm200; 0×429); probe sealable **0** → **DEFER_pre2015_empty**; COMPLETE **137→137 (+0)**; mb raw COMPLETE **998→1025** (+27 empty shells); C8 pass lag1; empty **0**; FRESH `projgen-a815af2b…` |
| [`docs/proof/w0814c_g4_misc_20260814.md`](proof/w0814c_g4_misc_20260814.md) | **W3-G4 w0814c_g4_misc** next seal wave: dry-run **580** (execute DEFER); R2 seal **80/80** (`2015-09…2016-12` ×4 + short_sale `2016-07…2017-10`); issue/restore; COMPLETE margin **49→65** / alert **50→66** / short_ratio **64→80** / short_sale **35→51** / investor **42→58** (**+80** wave); unique restore **+53** after peer race; **C8 margin pass lag2 held**; platform **1956**; empty **0**; FRESH `projgen-c0739f41…` |
| [`docs/proof/w0814c_g3_deriv_20260814.md`](proof/w0814c_g3_deriv_20260814.md) | **W3-G3 w0814c_g3_deriv residual**: acq futures/o225 **2022 24/24** host ~rpm45; options seal **2025-07…12** + H1 acq cont.; R2 seal+issue **+30**; COMPLETE futures/opt/o225 **44/8/44→56/14/56**; platform **1986**; C8 pass×3; empty **0**; FRESH `projgen-df80f965…` |
| [`docs/proof/w0814c_g6_edinet_20260814.md`](proof/w0814c_g6_edinet_20260814.md) | **W3-G6 w0814c_g6_edinet**: acq 2022 **36/36** (main 34p/2f + retry 3/3) host **2.51**/min (0×429); R2 seal **36/36** (pass1 33 + lock-retry 3); issue **+24** (runs **902249–902272**) + peer race **+12** → COMPLETE **44→56** each (+12×3); platform POST **1891**; observed_start **`2022-01-01`**; C8 pass lag 4/4/1; empty **0**; FRESH `projgen-b85f736b…` |
| [`docs/proof/w0814c_g5_idx_mb_20260814.md`](proof/w0814c_g5_idx_mb_20260814.md) | **W3-G5 w0814c_g5**: idx residual acq **95** (67p/28f + retry **28/28**, rpm **7.62/4.02**, 0×429); R2 seal+issue **+91** → idx COMPLETE **129→220**; mb residual seal probe sealable **0** pre-2015 **DEFER** (COMPLETE **137→137**); platform **1867**; C8 pass lag1×2; empty **0**; FRESH `projgen-463803f9…` |
| [`docs/proof/w0814c_all_sources_wave_20260814.md`](proof/w0814c_all_sources_wave_20260814.md) | **W3-G9 w0814c all-sources close**: PRE tip `4164545` raw **11281** COMPLETE **1727** → POST raw **11656** COMPLETE **1789** (+62); margin **64**/alert **62**/idx **143**/options **11**/cross **55**/OTC **17**; reeval×5 C8 pass; FRESH `projgen-00c6312e…`; empty **0**; peers not killed |
| [`docs/proof/w0814c_g2_fins_20260814.md`](proof/w0814c_g2_fins_20260814.md) | **W3-G2 w0814c_g2_fins residual**: acq **48/48** host **1.81**/min (0×429); R2 seal **48/48**; issue **+48** (12×4; runs **902375–902422**); fins COMPLETE **66/59/38/38→78/71/50/50**; platform **2034**; C8 pass×4; empty **0**; fins pool only; FRESH `projgen-f760cd86…` |
| [`docs/proof/w0814c_g7_earn_am_20260814.md`](proof/w0814c_g7_earn_am_20260814.md) | **W3-G7 w0814c_g7_earn_am**: residual dry-run **230** (earn **199** + am **31**); seal window_ok **0** (earn tip-dated `Date` 180/180; am `date_mode=today` tip snapshots); acq+seal **DEFER**; COMPLETE earn/am **1→1**; C8 pass lag0/1; empty **0**; platform **1733** (peer OTC) |
| [`docs/proof/w0814b_g4_fins_residual_20260814.md`](proof/w0814b_g4_fins_residual_20260814.md) | **W2-G4 w0814b_g4_fins residual**: acq **48/48** host **1.85**/min (0×429); R2 seal **48/48**; issue **+48** (12×4; runs **901987–902034**); fins COMPLETE **54/47/26/26→66/59/38/38**; platform **1727**; C8 pass×4; empty **0**; fins pool only; FRESH `projgen-5fe71c60…` |
| [`docs/proof/w0814b_g3_indices_20260814.md`](proof/w0814b_g3_indices_20260814.md) | **W2-G3 w0814b_g3**: topix gap `2008-01…04` acq **4/4** empty DEFER; idx residual acq **100/100** (rpm **4.61**, 0×429); seal+issue **+96** → idx COMPLETE **33→129**; topix **220→220**; empty **0**; FRESH `projgen-dcfb986b…`; platform **1727** |
| [`docs/proof/w0814b_g7_misc_20260814.md`](proof/w0814b_g7_misc_20260814.md) | **W2-G7 w0814b_g7_misc** next seal wave: dry-run **660** (execute DEFER); R2 seal **80/80** (`2014-05…2015-08` ×4 + short_sale `2015-03…2016-06`); issue/restore; COMPLETE margin **33→49** / alert **34→50** / short_ratio **48→64** / short_sale **19→35** / investor **26→42** (**+80** wave); unique restore **+34** after peer race; **C8 margin pass lag2 held**; platform **1566**; empty **0**; FRESH `projgen-8c049964…` |
| [`docs/proof/w0814b_g6_edinet_20260814.md`](proof/w0814b_g6_edinet_20260814.md) | **W2-G6 w0814b_g6_edinet**: acq 2023 **36/36** host **2.13**/min (0×429); R2 seal **36/36** (pass1 31 + lock-retry 5); issue **+36** (run **901863–901898**); COMPLETE **32→44** each (+12×3); platform POST **1566**; observed_start **`2023-01-01`**; C8 pass lag 4/4/1; empty **0**; FRESH `projgen-005375cf…` |
| [`docs/proof/w0814b_all_sources_wave_20260814.md`](proof/w0814b_all_sources_wave_20260814.md) | **W2-G9 w0814b all-sources close**: PRE tip `be7ad33` raw **10702** COMPLETE **1376** → POST raw **11242**/c **9670** COMPLETE **1478** (+102); margin **49**/alert **47**/short_ratio **64**/mb **116**/idx **61**/options **8**/OTC **11**; reeval×5 C8 pass; FRESH `projgen-16cfbaa5…`; empty **0**; peers not killed |
| [`docs/proof/w0814_all_sources_final_20260814.md`](proof/w0814_all_sources_final_20260814.md) | **FINAL w0814 all-sources**: PRE tip `cac338b` raw **9687** COMPLETE **942** → POST raw **10701**/c **9129** COMPLETE **1376** (+434); mb **69→105**; reeval×5 C8 pass; FRESH `projgen-f1d9b952…` age=0; empty **0**; peers not killed |
| [`docs/proof/w0814b_g2_breakdown_20260814.md`](proof/w0814b_g2_breakdown_20260814.md) | **W2-G2 w0814b_g2_mb**: residual acq **100p/0f** host **15.97** (pre-source densify); R2 seal **32/32** (`2021-04…2023-11`); issue **+21** (**901957–901977**) + peer **+11** → COMPLETE **105→137**; C8 pass lag1; empty **0**; FRESH `projgen-881ff280…` |
| [`docs/proof/w0814_g2_breakdown_20260814.md`](proof/w0814_g2_breakdown_20260814.md) | **G2 w0814_g2_mb**: residual **48p/72f** + retry **80p/0f** host **14.26/5.07**; R2 seal **36/36**; issue **+36** (`2018-04…2021-03` **901702–901738**); COMPLETE **69→105**; platform **1376**; C8 pass lag1; empty **0** |
| [`docs/proof/w0815_g2_fins_20260815.md`](proof/w0815_g2_fins_20260815.md) | **W9-G2 w0815_g2_fins residual**: plan **446** acq **0p/104f** 429 (w6→w2 abort); window_ok seal **72/74** + issue **+72** runs **903255–903345**; fins COMPLETE **126/104/98/98→162/104/132/100**; platform **2962**; C8 pass×4 lag1; FRESH `projgen-c3ab279a…`; empty **0**; peers not killed |
| [`docs/proof/w0814_g5_fins_residual_20260814.md`](proof/w0814_g5_fins_residual_20260814.md) | **G5 w0814_g5_fins residual**: acq **48/48** host **2.0**/min; R2 seal **48/48**; issue **+48** (12×4); remote COMPLETE **1339**; fins COMPLETE **54/47/26/26**; C8 pass×4; empty **0**; fins pool only |
| [`docs/proof/w0814_g7_edinet_20260814.md`](proof/w0814_g7_edinet_20260814.md) | **G7 w0814_g7_edinet**: acq 2024 (main 3p/33f + retry **36/36**); seals **+36** (major/cross/large **+12** each); COMPLETE **20→32** each; platform **1260**; observed_start **`2024-01-01`**; empty **0**; FRESH `projgen-ce19380…` |
| [`docs/proof/w0814_g8_misc_20260814.md`](proof/w0814_g8_misc_20260814.md) | **G8 misc w0814_g8_misc**: R2 seal+issue **+80** (margin/alert/short_ratio/short_sale/investor ×16); COMPLETE **1212**; C8 margin **pass lag2 held**; earn history DEFER tip-Date; acq execute DEFER (G7 970/970); empty **0**; FRESH `projgen-5be221…` |
| [`docs/proof/w0814_all_sources_wave_20260814.md`](proof/w0814_all_sources_wave_20260814.md) | **G10 w0814 all-sources wave close**: PRE tip `cac338b` raw **9687** COMPLETE **942** → POST raw **10662**/c **9090** COMPLETE **1106** (+164); topix **82→220**; futures **20→32**; host rpm g1 **13.74** / g3 topix **34.74** / g2 mb **14.38**; reeval×5 C8 pass; FRESH `projgen-d28bfce…` age=0; empty **0**; peers not killed |
| [`docs/proof/w0814c_g8_jsda_20260814.md`](proof/w0814c_g8_jsda_20260814.md) | **W3-G8 JSDA**: OTC tip/recent **+6** (`2026-07-22`…`24`/`27`…`29` runs **902114–902119**) → COMPLETE **17**; corporate+repo COMPLETE skip; remote COMPLETE **1733**; empty **0**; FRESH `projgen-efc306a7…`; further tip/history **DEFER** site timeout |
| [`docs/proof/w0814b_g8_jsda_20260814.md`](proof/w0814b_g8_jsda_20260814.md) | **W2-G8 JSDA**: OTC tip/recent **+2** (`2026-07-30/31` runs **901821/901820**) → COMPLETE **11**; corporate **12/12** + repo COMPLETE verify; remote COMPLETE **1442**; empty **0**; FRESH `projgen-1e79a513…`; further tip/history **DEFER** site timeout; year-archive sort fix |
| [`docs/proof/w0814_g9_jsda_20260814.md`](proof/w0814_g9_jsda_20260814.md) | **G9 JSDA**: OTC **+3** (`2026-08-03/04/05` runs **901241–901243**) → COMPLETE **9**; corporate **+11** annual 2015–2025 + full 2026 re-seal → **12/12 dataset COMPLETE** (runs **901244–901255**); repo verify COMPLETE; remote COMPLETE **1056**; empty **0**; FRESH `projgen-e1b67b…`; history DEFER |
| [`docs/proof/w0814h_g10_master_20260814.md`](proof/w0814h_g10_master_20260814.md) | **W8-G10 `w0814h_g10_master` residual**: planner **21** densify **20p/1f** (400 sub `2006-08`; host 1.28/min; 0×429); newest R2 window_ok **0** (Date=`2008-05-07`); COMPLETE **220→220 (+0)**; DEFER **21** misdate + **73** pre-plan; C8 pass lag1; FRESH `projgen-92b097b8…`; empty **0**; peers not killed |
| [`docs/proof/w0814_g4_master_residual_20260814.md`](proof/w0814_g4_master_residual_20260814.md) | **G4 `w0814_g4_master` residual**: plan **21** (`2006-08…2008-04`); acq wave1 **0p/21f** + retry **0p/21f** (400 sub + 429×20); seal window_ok **0** / window_bad **21** DEFER; COMPLETE **220→220 (+0)**; C8 pass lag1; FRESH `projgen-14c0bb…`; empty **0** |
| [`docs/proof/w0713_instruction_final_20260814.md`](proof/w0713_instruction_final_20260814.md) | **W0713 instruction final T1–T17**: PRE tip `83fe7c0` raw **7917** COMPLETE **585** 停滞4 **12/94/32/32** → POST raw **9687**/c **8567** COMPLETE **942** 停滞4 **42/220/82/69**; reeval×5 C8 pass; FRESH `projgen-98b032…` age=0; empty **0**; Mass NO-GO; Phase7 OFF |
| [`docs/proof/g7_t9_t10_margin_inv_20260814.md`](proof/g7_t9_t10_margin_inv_20260814.md) | **G7 T9+T10 `w0713_t7_margin_inv`**: plan **970** → wave1 **918p/52f** + retry **52/52** = **970/970**; host POST/min **9.61**; raw **8008→9687**; short_sale start **2013-11-01**; **C8 margin pass lag2 held**; COMPLETE +N **0**; empty **0**; FRESH `projgen-f15c9…` |
| [`docs/proof/w0713_t6_deriv_edinet_20260814.md`](proof/w0713_t6_deriv_edinet_20260814.md) | **G6 T7+T8 w0713_t6_deriv_edinet**: acq 2025 (main 41p/19f + retry 48/48); seals **+60** (futures/opt225/edinet×3 **2025-01…12**); COMPLETE **882→942**; observed_start **`2025-01-01`**; options full 2025 **DEFER**; empty **0**; FRESH `projgen-08c14…` |
| [`docs/proof/w0713_t4_breakdown_close_20260814.md`](proof/w0713_t4_breakdown_close_20260814.md) | **G4 T4 markets_breakdown close**: residual week-jobs **40p/4f**; R2 seal map **36/36** ready; issue **+36** (`2015-04…2018-03` **900927–900962**); COMPLETE **32→69 (+37)**; platform COMPLETE **882**; empty **0**; FRESH `projgen-b8c5…` |
| [`docs/proof/w0713_t2_master_close_20260814.md`](proof/w0713_t2_master_close_20260814.md) | **G2 T2 equities_master close**: backfill **63p/84f**; window-ok seal **+126** COMPLETE **94→220**; 21 misdated months DEFER; empty **0** |
| [`docs/proof/w0713_t1_bars_close_20260814.md`](proof/w0713_t1_bars_close_20260814.md) | **G1 T1 equities_bars_daily close**: exec **86p/34f** + retry **21p/1f**; R2 seal **30** ready; COMPLETE **12→42 (+30)**; empty **0** |
| [`docs/proof/w0713_t5_fins_residual_seal_20260814.md`](proof/w0713_t5_fins_residual_seal_20260814.md) | **G5 w0713_t5_fins residual seal**: R2 raw-only **48/48** ready; issue **+18** (summary **+12** / details **+1** / div **+1** / earn_date **+4**); remote COMPLETE **742**; fins COMPLETE **42/35/14/14**; raw_n **9455**; C8 pass×4; empty COMPLETE **0**; no fins/general pool acq |
| [`docs/proof/w0713_wave_close_20260814.md`](proof/w0713_wave_close_20260814.md) | **G10 T15+T16+T17 wave close**: stagnant-4 COMPLETE **bars 12→13 / master 94→132 / topix 32→82 / breakdown 32→33**; raw **7917→9387**; COMPLETE segs **585→729**; FRESH `projgen-7b6c…` age=0; empty COMPLETE **0**; peers not killed |
| [`docs/proof/w0713_t13_t14_ops_20260814.md`](proof/w0713_t13_t14_ops_20260814.md) | **G9 T13+T14**: projection PRE age ~**16983s** → POST age≈0 (`projgen-d4677ef…`); receipts **+27** (details **+11** / div **+11** / earn_date **+5** issued); remote COMPLETE **677**; raw_n **9324**; empty COMPLETE **0**; no cf_premium |
| [`docs/proof/g8_t11_otc_t12_indices_20260814.md`](proof/g8_t11_otc_t12_indices_20260814.md) | **G8 T11+T12**: OTC **+1** (`2026-08-14` run **900661**); `indices_bars_daily` **+5** (2024-01/08/09/10/12); remote COMPLETE **677**; raw_n **9200**; FRESH `projgen-c1aacf…`; further OTC/history **DEFER** |
| [`docs/proof/t5_dividend_pre2018_20260814.md`](proof/t5_dividend_pre2018_20260814.md) | **t5_div_pre**: `fins_dividend` **2008-01…2017-12** plan **120** → **120 pass / 0 fail**; host jobs/min **4.69**; reeval `observed_start` **`2013-02-01`** (was 2018-01-01); COMPLETE segs **585** Δ0; raw_n **7825**; empty COMPLETE **0** |
| [`docs/proof/t5_fins_family_20260813.md`](proof/t5_fins_family_20260813.md) | **T5 fins family FINAL**: runner **287/1** (fail=`fins_details` 2022-05 CF1102) + split/daily recover → unique **288**; host jobs/min **1.68**; observed summary **2008-07-01** / details·div·earn **2018-01-01** → end **2026-08-13** C8 pass; receipts this close **+0** (T12 peer **+45** already); **superseded on div start** by t5_div_pre → **2013-02-01** |
| [`docs/proof/t12_receipts_wave_20260814.md`](proof/t12_receipts_wave_20260814.md) | **T12 fins receipts**: fins_details **+20** + fins_summary **+25** → remote COMPLETE **585**; empty-raw ban held; no acq launch |
| [`docs/proof/t9_options_near_close_20260814.md`](proof/t9_options_near_close_20260814.md) | **T9 options_near close**: week-chunk 9/9 pass (retry 2/2); seals **+2** (2026-06/07 run_ids **900587/900586**) → then T12 → **585**; reeval C8 pass |
| [`docs/proof/instruction_t1t16_close_20260814.md`](proof/instruction_t1t16_close_20260814.md) | **T13–T15 final sync + T1–T16 instruction close** (2026-08-14 JST): reeval×5 + FRESH age=0; raw **7430**/6535; COMPLETE segs **538** Δ0; empty COMPLETE **0**; Mass NO-GO; acq not killed |
| [`docs/proof/t6_deriv_edinet_20260813.md`](proof/t6_deriv_edinet_20260813.md) | **G6 T9+T10** t6_deriv_edinet: worker 22p/1f; seals **+18** vs G7 (futures+5 major+4 cross+2 options_225+7) → COMPLETE **538**; reeval C8 pass; options_near not killed |
| [`docs/proof/t4_t7_t8_parallel_acq_reeval_20260813.md`](proof/t4_t7_t8_parallel_acq_reeval_20260813.md) | T4/T7/T8 parallel acq + **54/54** fail-retry + observed reeval; raw **5265→7289** (target Δ n **+1398**); **no** empty COMPLETE |
| [`docs/proof/t1_master_misc_close_20260813.md`](proof/t1_master_misc_close_20260813.md) | T1/G1 monitor queue-close master/misc (fail residual → closed by T478 retry) |
| [`docs/proof/g7_t11_otc_t12_receipts_20260813.md`](proof/g7_t11_otc_t12_receipts_20260813.md) | G7 T11 OTC **+0 DEFER** (timeout); T12 receipts **+10** → COMPLETE **520** |
| [`docs/proof/mb_2015dir_reeval_edinet_plus4_20260813.md`](proof/mb_2015dir_reeval_edinet_plus4_20260813.md) | T5/T9/T10: breakdown `observed_start=2015-03-26`; OTC **+0**; EDINET **+4** → COMPLETE **510** |
| [`docs/proof/t4_breakdown_wave_20260813.md`](proof/t4_breakdown_wave_20260813.md) | T4/G3 MB week-chunk midhole (GW2019 empty expected); reeval `observed_start=2015-03-26` |
| [`docs/proof/complete_plus3_margin_ssr_jun2026_20260813.md`](proof/complete_plus3_margin_ssr_jun2026_20260813.md) | A3 **+3** margin 2026-06/08 + short_sale 2026-06 → COMPLETE **506** |
| [`docs/proof/complete_plus2_margin_ssr_jul2026_20260813.md`](proof/complete_plus2_margin_ssr_jul2026_20260813.md) | A3 **+2** margin + short_sale **2026-07** R2 raw+struct → COMPLETE **503** |
| [`docs/proof/complete_plus7_jul2026_remote_struct_20260813.md`](proof/complete_plus7_jul2026_remote_struct_20260813.md) | A3 **+7** remote 2026-07 struct + R2 raw → COMPLETE **501** |
| [`docs/proof/complete_plus4_investor_edinet_20260813.md`](proof/complete_plus4_investor_edinet_20260813.md) | A3 **+4** investor 2019-12 + edinet×3 2026-08 → COMPLETE **494** |
| [`docs/proof/complete_plus8_r2_raw_seal_20260813.md`](proof/complete_plus8_r2_raw_seal_20260813.md) | A3 **+8** via R2 raw mirror + parallel receipts → COMPLETE **490** |
| [`docs/proof/complete_plus23_parallel_receipts_20260812.md`](proof/complete_plus23_parallel_receipts_20260812.md) | A3 parallel receipts **+71** → COMPLETE **479** |
| [`docs/proof/complete_plus3_struct_hint_20260812.md`](proof/complete_plus3_struct_hint_20260812.md) | A3 +3 (earnings/fins) → **481** |
| [`docs/proof/complete_plus1_bars_202608_20260812.md`](proof/complete_plus1_bars_202608_20260812.md) | bars/2026-08 re-seal → **482** |
| [`docs/proof/complete_plus3_otc_20260812.md`](proof/complete_plus3_otc_20260812.md) | JSDA OTC honest +3 path |
| [`docs/proof/complete_plus1_20260812.md`](proof/complete_plus1_20260812.md) | earlier +1 COMPLETE procedure evidence |
| [`docs/proof/sticky_complete_verify_20260812.md`](proof/sticky_complete_verify_20260812.md) | sticky COMPLETE demotion guard live |

### Track A / raw throughput / bars history
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/t5_fins_family_20260813.md`](proof/t5_fins_family_20260813.md) | **T5 FINAL 288** (runner 287/1 + recover); observed deepens + C8 pass ×4; G4 partial snap superseded |
| [`docs/proof/wave2256_final_close_20260813.md`](proof/wave2256_final_close_20260813.md) | **G8-final** closed circuit: reeval×5 + FRESH age=0 (`projgen-a059…`); session PRE raw **6447**→POST **7385**; COMPLETE segs **510→538**; empty COMPLETE **0**; Mass NO-GO; Phase7 OFF; acq not killed |
| [`docs/proof/p0_multi_track_wave2_20260813.md`](proof/p0_multi_track_wave2_20260813.md) | **G8 closed circuit** T13+T14+T15: reeval×5 + FRESH age=0 (`projgen-8927…`); raw PRE **6447**→POST **6477** (+30); COMPLETE segs **510** Δ0; host rpm bars **6.22** / topix w1 **93.48** / merged **12.56** / +peers **17.63**; no kill acq |
| [`docs/proof/p0_high_rate_parallel_acq_20260813.md`](proof/p0_high_rate_parallel_acq_20260813.md) | **High-rate parallel** PRE raw **3535**→re-verify **6378** (+2843); host rpm mb 10.97 / bars 6.22 / topix3 **93.48→62.79** / merged **12.31**; bars/fins/topix drivers done; observed_* + margin C8 **pass**; projection FRESH age=0 |
| [`docs/proof/p0_multi_track_throughput_20260813.md`](proof/p0_multi_track_throughput_20260813.md) | **Multi-track** MB/bars/fins/topix host POST/min + raw Δ **+839** (5279→6118) + reeval (fins start **2014-01-01**, breakdown **2015-03-26**, C8 pass, projection FRESH) |
| [`docs/proof/track_a_dryrun_20260812.md`](proof/track_a_dryrun_20260812.md) | Track A planner dry-run |
| [`docs/proof/raw_throughput_PRE_20260812.md`](proof/raw_throughput_PRE_20260812.md) / [`.json`](proof/raw_throughput_PRE_20260812.json) | PRE baseline |
| [`docs/proof/raw_throughput_PRE_AEXEC_20260812.md`](proof/raw_throughput_PRE_AEXEC_20260812.md) | PRE_AEXEC |
| [`docs/proof/raw_throughput_POST_AEXEC_20260812.md`](proof/raw_throughput_POST_AEXEC_20260812.md) | POST_AEXEC summary |
| [`docs/proof/raw_throughput_POST_AEXEC_20260812T141214Z.md`](proof/raw_throughput_POST_AEXEC_20260812T141214Z.md) | timestamped POST |
| [`docs/proof/raw_throughput_POST_AEXEC_20260812T142910Z.md`](proof/raw_throughput_POST_AEXEC_20260812T142910Z.md) | timestamped POST |
| [`docs/proof/raw_throughput_POST_AEXEC_20260812T143446Z.md`](proof/raw_throughput_POST_AEXEC_20260812T143446Z.md) | POST final snapshot (local mirror; remote raw SoT separate) |
| [`docs/proof/remote_raw_POST_AEXEC_snippet.txt`](proof/remote_raw_POST_AEXEC_snippet.txt) | remote raw snippet |
| [`docs/proof/bars_observed_start_move_20260812.md`](proof/bars_observed_start_move_20260812.md) | code path: receipt ∪ hot → `observed_*` |
| [`docs/proof/bars_history_observed_start_20260812.md`](proof/bars_history_observed_start_20260812.md) | bars PRE/POST **`observed_start=2008-05-01`**; raw →1889 |
| [`docs/proof/bars_gap_20060812_20080430_20260812.md`](proof/bars_gap_20060812_20080430_20260812.md) | full week-chunk gap dispatch 2006-08→2008-04 (empty shells) |
| [`docs/proof/bars_p0_gap_midhole_20260813.md`](proof/bars_p0_gap_midhole_20260813.md) | gap DEFER + mid-hole fill 2011–2025 |
| [`docs/proof/bars_p0_gap_2004_2008_reverify_20260813.md`](proof/bars_p0_gap_2004_2008_reverify_20260813.md) | **reverify** 2004–2008-04: API floor 2006-08-13 + empty `data[]`; `observed_start` stays **2008-05-01** |

### P0 / P1 other datasets (margin, topix, quality)
| Proof | What it closes |
|-------|----------------|
| [`docs/proof/p0_other_datasets_margin_topix_20260812.md`](proof/p0_other_datasets_margin_topix_20260812.md) | margin latest+Jul → **PARTIAL**; topix hist → **`observed_start=2008-01-01`** |
| [`docs/proof/p1_markets_margin_interest_stale_defer_20260812.md`](proof/p1_markets_margin_interest_stale_defer_20260812.md) | prior STALE root-cause / history DEFER (superseded on status only by P0) |
| [`docs/proof/p0_reeval_20260812.md`](proof/p0_reeval_20260812.md) | earlier reeval / projection freshness (historical COMPLETE 400) |
| [`docs/proof/p0_finish_projection_breakdown_20260813.md`](proof/p0_finish_projection_breakdown_20260813.md) | P0 finish: projection FRESH + breakdown `observed_start` **2015-04-01** restore |
| [`docs/proof/p0_margin_projection_20260813.md`](proof/p0_margin_projection_20260813.md) | margin observed_end + earlier projection freshness |
| [`docs/proof/p0_margin_c8_projection_20260813.md`](proof/p0_margin_c8_projection_20260813.md) | margin C8 receipt-plane lag (1d≤7) + projection reclock FRESH age=0 |
| [`docs/proof/p0_margin_observed_end_restore_20260813.md`](proof/p0_margin_observed_end_restore_20260813.md) | **P0** observed_end **2026-08-04→2026-08-12** restore (no execute; lag 9d FAIL→1d PASS) |
| [`docs/proof/p0_margin_c8_detail_pass_20260813.md`](proof/p0_margin_c8_detail_pass_20260813.md) | **P0** detail_json C8 **fail→pass** (receipt SoT) + projection FRESH + planner sub floor 2006-08-13 |
| [`docs/proof/g5_margin_earn_history_20260813.md`](proof/g5_margin_earn_history_20260813.md) | **G5** margin history → `observed_start=2013-01-04` + earn 199 segs; C8 pass; PARTIAL honest; t7/t8 untouched |
| [`docs/proof/p0_storage_plane_evidence.md`](proof/p0_storage_plane_evidence.md) | storage plane evidence |
| [`docs/proof/data_quality_scan_20260812.md`](proof/data_quality_scan_20260812.md) | quality scan |
| [`docs/proof/phase63_completion_20260812.md`](proof/phase63_completion_20260812.md) | Phase 6.3 guard/freshness tooling land |

### Ops notes (not proofs of COMPLETE)
- [`docs/operations/safe_complete_one_segment.md`](operations/safe_complete_one_segment.md)
- [`docs/operations/phase7_foundation_off.md`](operations/phase7_foundation_off.md)
- [`docs/operations/phase63_live_sync.md`](operations/phase63_live_sync.md) *(historical COMPLETE 400; use this residual for live counts)*
- [`docs/operations/projection_publish_guard.md`](operations/projection_publish_guard.md)

## DONE vs DEFER

| Area | Status |
|------|--------|
| Sticky COMPLETE + inventory status fix | **DONE** (+ segment_id fallback + aggregate recompute 2026-08-13) |
| Publish fail-closed guard | **DONE** |
| Honest segment COMPLETE path (raw + signed SUCCESS) | **DONE** (OTC **6**; A3 … + G7/G6/T9/T12 fins + **G8 OTC +1 + indices +5** + w0713 peers; total COMPLETE **677**) |
| JSDA min COMPLETE (otc/corp/tokyo) | **DONE** (otc **6**; corp/tokyo ≥1 each; further OTC **DEFER** site timeout + R2 MISS) |
| G8 T11 OTC + T12 indices_bars_daily | **DONE** (OTC **+1** 2026-08-14; indices COMPLETE segs **2→7** full months; proof `g8_t11_otc_t12_indices_20260814.md`) |
| Physical layout → `packages/*` planes | **DONE** (Batches 0–E; import names leaf top-level) |
| Track A planner / throughput / execute | **DONE** (infra + live execute; raw continuing under mid-hole) |
| Track B1 docs hub + plane import guards | **DONE** |
| Track B residual live-sync + docs SoT banners | **DONE** (COMPLETE **677** / raw **9200** / G8 closed; Phase7 OFF) |
| G8 closed circuit (reeval + freshness + throughput proof) | **DONE** (wave2 + **G8-final** reeval×5 + FRESH age=0; peers not killed) |
| T13–T15 final sync + T1–T16 instruction close | **DONE** (2026-08-14: reeval×5 C8 pass; FRESH `projgen-daa4…`; raw **7430**; COMPLETE **538** Δ0; proof `instruction_t1t16_close_20260814.md`) |
| W0713 T1–T17 instruction final close | **DONE** (2026-08-14 ~00:49Z: remote D1 measure; reeval×5 C8 pass; FRESH `projgen-98b032…` age=0; raw **9687**/c **8567**; COMPLETE **942**; 停滞4 **42/220/82/69**; empty **0**; proof `w0713_instruction_final_20260814.md`) |
| W0814 all-sources G10 closed circuit | **DONE** (2026-08-14 ~01:32Z: monitor ~18m; reeval×5 C8 pass; FRESH `projgen-d28bfce…`; raw **10662**; COMPLETE **1106**; topix **220**; empty **0**; proof `w0814_all_sources_wave_20260814.md`) |
| W0814 G2 markets_breakdown residual seal | **DONE** — residual **48p/72f** + retry **80p/0f**; seal+issue **+36** (`2018-04…2021-03`); COMPLETE **69→105**; platform **1376**; C8 pass lag1; empty **0**; proof [`w0814_g2_breakdown_20260814.md`](proof/w0814_g2_breakdown_20260814.md) |
| W2-G2 w0814b markets_breakdown residual seal | **DONE** — acq **100p/0f** host **15.97**; R2 seal **32/32** (`2021-04…2023-11`); issue **+21** + peer **+11** → COMPLETE **105→137**; C8 pass lag1; empty **0**; proof [`w0814b_g2_breakdown_20260814.md`](proof/w0814b_g2_breakdown_20260814.md) |
| W0814 all-sources FINAL wave sync | **DONE** (2026-08-14 ~02:38Z: remote measure; reeval×5 C8 pass; FRESH `projgen-f1d9b952…` age=0; raw **10701**/c **9129**; COMPLETE **1376**; mb **105**; empty **0**; proof `w0814_all_sources_final_20260814.md`) |
| W0814b all-sources W2-G9 close | **DONE** (2026-08-14 ~03:29Z: issue margin/alert/short_ratio/mb; publish fail-closed; reeval×5 C8 pass; FRESH `projgen-16cfbaa5…`; raw **11242**/c **9670**; COMPLETE **1478**; empty **0**; peers not killed; proof `w0814b_all_sources_wave_20260814.md`) |
| W0814c all-sources W3-G9 close | **DONE** (2026-08-14 ~04:56Z: issue margin/alert/idx/edinet/options from peer seals; publish fail-closed; reeval×5 C8 pass; FRESH `projgen-00c6312e…`; raw **11656**; COMPLETE **1789** (+62); empty **0**; peers not killed; proof `w0814c_all_sources_wave_20260814.md`) |
| W3-G5 w0814c_g5 idx residual + mb residual seal | **DONE** — idx acq **95** (67p/28f + retry **28/28**, rpm **7.62/4.02**); seal+issue **+91** → idx **129→220**; mb pre-2015 sealable **0 DEFER** (**137→137**); platform **1867**; C8 pass lag1×2; empty **0**; FRESH `projgen-463803f9…`; proof [`w0814c_g5_idx_mb_20260814.md`](proof/w0814c_g5_idx_mb_20260814.md) |
| W4-G5 w0814d_g5_mb residual seal (pre-2015) | **DEFER** — re-probe sealable **0**; empty shells **26** + thin `2015-03`; optional acq dry-run **117**/50 execute DEFER; COMPLETE **137→137**; C8 pass lag1; proof [`w0814d_g5_mb_20260814.md`](proof/w0814d_g5_mb_20260814.md) |
| W8-G10 w0814h_g10_master residual | **DEFER** — densify planner **21** **20p/1f** (w=1 rpm80; 0×429; `2006-08` HTTP400 sub edge); post-densify R2 still misdate `2008-05-07` window_ok **0**; pre-plan **73** (`2000-07…2006-07`) outside planner; COMPLETE **220→220**; C8 pass lag1; FRESH `projgen-92b097b8…`; proof [`w0814h_g10_master_20260814.md`](proof/w0814h_g10_master_20260814.md) |
| W8-G9 w0814h_g9_mb residual execute (pre-2015) | **DEFER** — execute **27/27 pass** `rowsInserted=0` (w=2 rpm200; 0×429); probe sealable **0** (empty **26** + thin `2015-03` max **3628**); no seal/issue; COMPLETE **137→137**; mb raw COMPLETE **998→1025**; C8 pass lag1; FRESH `projgen-a815af2b…`; proof [`w0814h_g9_breakdown_20260814.md`](proof/w0814h_g9_breakdown_20260814.md) |
| W4-G6 w0814d_g6_edinet (2021 year) | **DONE** — acq main **34p/2f** + retry; seal+issue **+30** (major/cross **+12**, large **+6** H2; H1 empty DEFER); COMPLETE **56→68/68/62**; platform **2106**; C8 pass lag4/4/1; empty **0**; FRESH `projgen-96816054…`; proof [`w0814d_g6_edinet_20260814.md`](proof/w0814d_g6_edinet_20260814.md) |
| G6 t6_deriv_edinet (T9+T10) seal + reeval | **DONE** (worker 22p/1f; +18 seals vs G7 → **538**; options_near closed by T9 2026-08-14) |
| T9 options_near week-chunk + seal | **DONE** (9/9 pass; COMPLETE **+2** Jun/Jul; later T12 → **585**) |
| T12 fins raw seals (details+summary) | **DONE** (**+45** → COMPLETE **585**; empty-raw ban; proof `t12_receipts_wave_20260814.md`) |
| G5 w0713_t5_fins residual seal (summary+details+div+earn) | **DONE** — R2 raw-only **48/48** ready; issue **+18** (summary **+12** / details **+1** / div **+1** / earn_date **+4**); remote COMPLETE **742**; fins COMPLETE **42/35/14/14**; C8 pass×4; empty COMPLETE **0**; no fins/general pool acq; proof [`w0713_t5_fins_residual_seal_20260814.md`](proof/w0713_t5_fins_residual_seal_20260814.md) |
| G5 w0814_g5_fins residual (summary+details+div+earn) | **DONE** — acq **48/48** pass host **2.0**; R2 seal **48/48**; issue **+48**; remote COMPLETE **1339**; fins COMPLETE **54/47/26/26**; C8 pass×4; empty **0**; fins pool only; proof [`w0814_g5_fins_residual_20260814.md`](proof/w0814_g5_fins_residual_20260814.md) |
| W2-G4 w0814b_g4_fins residual (summary+details+div+earn) | **DONE** — acq **48/48** pass host **1.85** (0×429); R2 seal **48/48**; issue **+48**; fins COMPLETE **66/59/38/38**; platform **1727**; C8 pass×4; empty **0**; fins pool only; proof [`w0814b_g4_fins_residual_20260814.md`](proof/w0814b_g4_fins_residual_20260814.md) |
| W3-G2 w0814c_g2_fins residual (summary+details+div+earn) | **DONE** — acq **48/48** pass host **1.81** (0×429); R2 seal **48/48**; issue **+48**; fins COMPLETE **78/71/50/50**; platform **2034**; C8 pass×4; empty **0**; fins pool only; proof [`w0814c_g2_fins_20260814.md`](proof/w0814c_g2_fins_20260814.md) |
| W4-G2 w0814d_g2_fins residual (summary+details+div+earn) | **DONE** — acq **48/48** pass host **1.59** (0×429); R2 seal **46/46**; issue **+46** (details **+10** tip already COMPLETE); fins COMPLETE **90/81/62/62**; platform **2221**; C8 pass×4; empty **0**; fins pool only; proof [`w0814d_g2_fins_20260814.md`](proof/w0814d_g2_fins_20260814.md) |
| W9-G2 w0815_g2_fins residual (summary+details+div+earn) | **DONE** — plan **446** acq **0p/104f** 429 abort; window_ok seal **72/74** + issue **+72**; fins COMPLETE **162/104/132/100**; platform **2962**; C8 pass×4; FRESH `projgen-c3ab279a…`; empty **0**; fins pool only; proof [`w0815_g2_fins_20260815.md`](proof/w0815_g2_fins_20260815.md) |
| W3-G7 w0814c_g7_earn_am residual (earn + bars_am) | **DEFER** — dry-run **230**; earn tip-dated `Date` window_ok **0/180**; am `date_mode=today` tip snapshots only; COMPLETE **1/1** held; C8 pass; proof [`w0814c_g7_earn_am_20260814.md`](proof/w0814c_g7_earn_am_20260814.md) |
| bars `observed_start` receipt-plane union | **DONE** (remote **`2008-05-01`**) |
| multi-track bars/fins/topix paced execute + host rpm proof | **DONE** (bars 280; fins FINAL 288; topix3 192; see multi-track + T5 proof) |
| fins_summary `observed_start` history deepen | **DONE** (remote **`2008-07-01`** via T5 pre-2014 paced 72/72 + FINAL reeval; empty 2008-01…06 shells; COMPLETE segs **66** via T12+G5+W2-G4 waves not dataset COMPLETE) |
| T5 fins family (summary+details+div+earn 288) | **DONE** — runner **287/1** (`fins_details` 2022-05 CF1102) + split/daily recover → unique **288**; host jobs/min **1.68**; reeval ×4 C8 pass; observed div/earn start **2018-01-01** at close; PID dead / flag DONE; proof [`t5_fins_family_20260813.md`](proof/t5_fins_family_20260813.md) |
| t5_div_pre `fins_dividend` 2008-01…2017-12 | **DONE** — plan **120** / **120 pass / 0 fail**; host jobs/min **4.69**; PID **43684** natural exit; reeval `observed_start` **`2013-02-01`**; empty shells 2008-01…2013-01; COMPLETE **585** Δ0; raw_n **7825**; proof [`t5_dividend_pre2018_20260814.md`](proof/t5_dividend_pre2018_20260814.md) |
| bars gap **2004-01 → 2008-04** deepen / pre-May-2008 `observed_start` | **DEFER** (catalog wants 2004; subscription floor **2006-08-13**; empty `data[]` through 2008-04; raw_n=0 on gap receipts — see reverify proof) |
| topix `observed_start` receipt-plane | **DONE** (remote **`2008-01-01`**; `observed_end` **`2026-08-13`**) |
| W10-G8 T1+T2 topix/idx residual `2008-01…04` | **DEFER** — re-verify acq **8/8** empty shells (`row_count=0` topix **12348–12353** / idx **12360–12381**); no seal; COMPLETE **220/220 held**; dataset COMPLETE **NO** without human-gate floor `2008-05-01`+prune; proof [`w0815b_g8_topix_indices_20260815.md`](proof/w0815b_g8_topix_indices_20260815.md) |
| W8-G8 T1+T2 topix/idx residual `2008-01…04` | **DEFER** (prior) — empty shells; proof [`w0814h_g8_topix_indices_20260814.md`](proof/w0814h_g8_topix_indices_20260814.md) |
| margin STALE → PARTIAL (freshness) | **DONE** (remote PARTIAL; `observed_end=2026-08-13`; **detail_json C8 pass** lag 1d≤7 via `receipt_observed_end`; not dataset COMPLETE) |
| margin history raw + earn segments (G5 t5_margin_earn) | **DONE** (margin worker **147/147** after retry; earn **199/199**; `observed_start` **2013-01-04** / earn **2010-01-04**; C8 pass; COMPLETE seals still DEFER) |
| planner OOS before subscription floor | **DONE** (`JQUANTS_SUBSCRIPTION_FLOOR=2006-08-13`; fail id 2522 class blocked) |
| Extra COMPLETE without raw | **DEFER** / **Forbidden** |
| OTC full archive COMPLETE | **DEFER** (thousands of trading days remain; G8 sealed tip day only) |
| `indices_bars_daily` history COMPLETE beyond 7 segs | **DEFER** (acq pass 21 months; seal only full-month raw+struct) |
| W13-G3 w0815e_g3 (futures+o225 dataset COMPLETE) | **DONE** — segs already **164/164** each (W12-G4); surgical re-aggregate both → `dataset_coverage` **COMPLETE**; short_ratio COMPLETE **held**; Dataset COMPLETE **8→10**; segs Δ**0**; FRESH `projgen-155ea34a…`; empty **0**; peers not killed; proof [`w0815e_g3_dataset_complete_20260815.md`](proof/w0815e_g3_dataset_complete_20260815.md) |
| W11-G1 w0815c_g1_margin (T1+T2 alert+interest dataset COMPLETE) | **DONE** — alert residual **+2** (`2024-07`/`2025-02` runs **903410/903412**); interest segs already 164/164; surgical re-aggregate both → `dataset_coverage` **COMPLETE**; Dataset COMPLETE **5→7**; FRESH `projgen-e686fa9e…`; empty **0**; peers not killed; proof [`w0815c_g1_margin_20260815.md`](proof/w0815c_g1_margin_20260815.md) |
| G8 misc residual seal (margin family + investor) | **DONE** (+80; proof `w0814_g8_misc_20260814.md`) |
| W7-G4 w0814g_g4_misc next seal (margin family + investor) | **DONE** — R2 seal **80/80**; issue/restore; wave months **+80** (unique restore **+33** after peer race); margin **113→129** / alert **114→130** / short_ratio **128→144** / short_sale **99→115** / investor **106→164** (wave **+16** + peer densify **+42**); **C8 margin pass lag2 held**; platform **2802**; empty **0**; FRESH `projgen-eef8d845…`; acq execute DEFER (dry-run **260**); proof [`w0814g_g4_misc_20260814.md`](proof/w0814g_g4_misc_20260814.md) |
| W6-G4 w0814f_g4_misc next seal (margin family + investor) | **DONE** — R2 seal **80/80**; issue/restore; wave months **+80** (unique restore **+45** after peer race); margin **97→113** / alert **98→114** / short_ratio **112→128** / short_sale **83→99** / investor **90→106**; **C8 margin pass lag2 held**; platform **2551**; empty **0**; FRESH `projgen-d0ba7aaa…`; acq execute DEFER (dry-run **340**); proof [`w0814f_g4_misc_20260814.md`](proof/w0814f_g4_misc_20260814.md) |
| W6-G3 w0814f_g3_deriv residual (options 2024 H1 + futures/o225 2019) | **DONE** — paced **50p/1f** (futures 2019-05 HTTP500 retry); R2 seal **30/30**; issue **+30** (runs **903008–903037**); COMPLETE futures/opt/o225 **80/26/80→92/32/92**; platform **2646**; C8 pass×3 lag1; empty **0**; kill ban / WAVE_DONE natural; FRESH `projgen-ec2c02f2…`; proof [`w0814f_g3_deriv_20260814.md`](proof/w0814f_g3_deriv_20260814.md) |
| JSDA corporate years 2015–2025 | **DEFER** |
| breakdown `observed_start` pre-2024 depth | **DONE** (remote **`2015-03-26`** via receipt reeval; MB solo 2016–2023 week done; 2015-dir partial; re-reeval after every full publish) |
| Mass / READY / Phase7 switch ON | **NO-GO** (Phase7 **OFF** maintained) |
| applied_cursor materialization | **DEFER** |
| Batch Z (`quant_platform.*` imports) | **DEFER** (ADR Accepted; out of B1) |
| B1-c full dead-code purge | **partial** — inventory only; no unsafe deletes (false-positive import scans) |
| B1-d test tier nav | **partial** — `tests/README.md` G0/G1/G2 landed; matrix split open |
| B1-e script bootstrap | **partial** — ops/coverage + receipt CLIs on `_bootstrap`; fingerprints `parents[N]` fixed; remaining scripts incremental |

## Note on COMPLETE counts
- **Dataset-level COMPLETE = 2** means only two datasets have *all* required segments COMPLETE.
- **Segment COMPLETE = 882** counts every COMPLETE segment across datasets (calendar 224 + G1 bars / G2 master / G3 topix / G4 breakdown / fins / JSDA / A3 / T9… seals, etc.).
- Next honest +N requires additional **real raw** (R2 or official fetch) + structured + signed SUCCESS; do not invent.
- Post-G6: major/cross/large_volume/futures/options_225 all **2026-01…08** COMPLETE; options **2026-06/07/08** (T9).
- W5-G2 w0814e_g2_fins: fins_summary COMPLETE segs **102**; fins_details **93**; dividend **74**; earnings_date **74**; remaining history months **DEFER** next seal wave (summary **2016-08…**, details **2025-09…2026-07** tip holes, div **2019-02…**, earn **2024+**).
- W4-G2 w0814d_g2_fins: fins_summary COMPLETE segs **90**; fins_details **81**; dividend **62**; earnings_date **62**; superseded residual frontier by W5-G2 (was next after **90/81/62/62**).
- W3-G2 w0814c_g2_fins: fins_summary COMPLETE segs **78**; fins_details **71**; dividend **50**; earnings_date **50**; superseded residual frontier by W4-G2 (was next after **78/71/50/50**).
- W2-G4 w0814b_g4_fins: fins_summary COMPLETE segs **66**; fins_details **59**; dividend **38**; earnings_date **38**; superseded residual frontier by W3-G2 (was next after **66/59/38/38**).
- **W3-G7 earn/am:** residual dry-run **230**; history seal **DEFER** (earn tip-dated `Date`; am today-mode tip-only); COMPLETE remain **1/1** (`2026-08`); empty **0**.
- **G1 bars:** COMPLETE **42** (`2008-05…2010-10` + tip islands); further history after 2010-10 **DEFER** next seal wave.
- **G2/G4/W8-G10 master:** COMPLETE **220**; densify residual **20p/1f** still misdated `2008-05-07` → seal **0**; **21** misdate + **73** pre-plan **DEFER** (not sealed).
- **G4/G2/w0814b breakdown:** COMPLETE **137** (`2015-04…2023-11` continuous + tips); pre-2015-03 **DEFER** empty shells.
- **W3-G5 w0814c_g5 mb residual:** probe **27** PARTIAL pre-2015; sealable **0** → COMPLETE **137** held; empty **0**.
- **W3-G5 w0814c_g5 idx residual:** acq **95**+retry **28/28**; seal+issue **+91** → COMPLETE **220**; residual **2008-01…04** empty DEFER; platform **1867**; FRESH `projgen-463803f9…`.
- **W8-G8 topix/idx residual:** re-verify acq **8/8** empty (`row_count=0` runs **11570–11603**); COMPLETE **220/220 held**; empty COMPLETE **0**; FRESH `projgen-c61de815…`; dataset COMPLETE still blocked.
- **W2-G9 w0814b close:** PRE raw **10702**/COMPLETE **1376** → POST **11242/1478**; FRESH `projgen-16cfbaa5…`; empty **0**; peers not killed.
- **W3-G9 w0814c close:** PRE raw **11281**/COMPLETE **1727** → POST **11656/1789** (+62); FRESH `projgen-00c6312e…`; empty **0**; peers not killed (g1/g2/g3/g4 cont.).
- G8: OTC tip **2026-08-14** sealed; `indices_bars_daily` **7** COMPLETE months; further OTC/history **DEFER**.
- t5_div_pre: `fins_dividend` worker **120/120** pre-2018; `observed_start` **2013-02-01**; later G9/G5 sealed **2018-01…12**.
- OTC archive +N blocked when `market.jsda.or.jp` times out and no R2 raw for candidate days (CF worker can still land tip files).
- Full publish resets breakdown/margin `observed_*` toward hot facts — always re-run `ops_reeval_observed_window.py` for focus datasets after apply.
- Coordinate `cf_premium_backfill` on **general** with live peers; prefer ≤40 RPM single worker. Mass / READY **NO-GO**. Fins residual acq uses **fins pool only** (`--fins-rpm` / `--fins-workers`).
- T5 close: runner natural exit (PID dead); **no** empty COMPLETE; issue_receipts this close **+0** (T12 already sealed ready months).
- t5_div_pre: PID **43684** natural exit; **no** kill / **no** double-run; empty COMPLETE **0**.
- G5 w0713_t5_fins: seal-only (no acq); issue **+18**; empty COMPLETE **0**; peers not killed.
- G5 w0814_g5_fins: acq **48/48** + seal/issue **+48**; empty COMPLETE **0**; fins pool only; peers not killed.
- W5-G2 w0814e_g2_fins: acq **48/48** + seal/issue **+48**; empty COMPLETE **0**; fins pool only serial paced; peers not killed; div seal honest **2017-02…12+2019-01** (skip 2018 COMPLETE island).
- W4-G2 w0814d_g2_fins: acq **48/48** + seal/issue **+46**; empty COMPLETE **0**; fins pool only serial paced; peers not killed; details seal **10** (tip `2024-01/02` already COMPLETE).
- W3-G2 w0814c_g2_fins: acq **48/48** + seal/issue **+48**; empty COMPLETE **0**; fins pool only serial paced; peers not killed.
- W2-G4 w0814b_g4_fins: acq **48/48** + seal/issue **+48**; empty COMPLETE **0**; fins pool only serial paced; peers not killed; publish SIGTERM recovered same fail-closed command.
- G4 w0713_t4_mb: residual backfill natural exit; seal-only +36 issue; empty COMPLETE **0**; peers not killed.
- G2 w0814_g2_mb: residual+retry natural exit; seal+issue **+36**; COMPLETE **105**; empty COMPLETE **0**; peers not killed; FINAL sync raw **10701** / COMPLETE **1376**.
- W2-G2 w0814b_g2_mb: residual acq **100p/0f**; seal **32/32** + issue **+21**/peer **+11**; COMPLETE **137**; empty COMPLETE **0**; peers not killed; platform POST **1654**.

## Phase 7 OFF (explicit)
Phase 7 remains **foundation-only / OFF**. Stubs under `knowledge/`, `selection/`, `gateway/`, `research/` are scaffolding.  
Fail-closed surface: `agents/mass_research.py`, `research/readiness.py`, `selection/budget_ledger.py`.  
Ops note: [`docs/operations/phase7_foundation_off.md`](operations/phase7_foundation_off.md).  
Architecture: [`docs/architecture/phase7_fail_closed.md`](architecture/phase7_fail_closed.md).

## Agent pointers
- LLM nav map: [`docs/architecture/llm_nav_map.md`](architecture/llm_nav_map.md)
- Layout SoT: [`docs/architecture/repo_layout_migration.md`](architecture/repo_layout_migration.md)
- LLM-friendly refactor ADR: [`docs/architecture/adr_llm_friendly_refactor.md`](architecture/adr_llm_friendly_refactor.md) (**Accepted**)
- Complete segment checklist: [`docs/complete_segment_checklist.md`](complete_segment_checklist.md) (counts live **only** here)
