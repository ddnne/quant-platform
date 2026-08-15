# W65 / w0815bf — Simple daily sign baseline close

**Status:** **closed** · Task D quality residual commit push  
**Wave:** W65 / w0815bf · 不合格ベースライン固定  
**Implementer:** GLM5.3 (Grok did not implement code)  
**READY 未宣言** · Mass **NO-GO** · Phase7 **OFF** · **no edge**  
**Generated / closed:** 2026-08-15

## Deliverables (landed)

| # | artifact | path / note |
|---|----------|-------------|
| 1 | Rejection proof | [`w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md`](w0815bf_w65_simple_daily_sign_baselines_rejected_20260815.md) — S1–S5 definition · short-window · multi-year gross · cost-after · 結論 非候補 |
| 2 | Research-only catalog | `packages/product/research/baseline_catalog.py` — `research_status=research_baseline_rejected` · wave · reasons · cost_gate_result · freeze Mass/READY false |
| 3 | Catalog unit tests | `tests/test_baseline_catalog.py` — S1–S5 present · Mass/READY false · gate pass ≠ READY |
| 4 | Holding metrics module | `packages/product/research/holding_metrics.py` — run-length · amortization · freeze-wrapped reports |
| 5 | Holding unit tests | `tests/test_holding_metrics.py` |
| 6 | Holding proof | [`w0815bf_w65_holding_turnover_metrics_20260815.md`](w0815bf_w65_holding_turnover_metrics_20260815.md) · optional S1 sample log `.glm-logs/w0815bf_w65_baselines/holding_metrics_s1.json` |
| 7 | Data gap inventory | [`w0815bf_w65_data_gap_priority_20260815.md`](w0815bf_w65_data_gap_priority_20260815.md) · machine log `data_gap_priority.json` · **P0 = 0** |
| 8 | Residual SoT pin | [`docs/phase62_residual_status.md`](../phase62_residual_status.md) TOP = W65 |
| 9 | FRESH projection | `projgen-3ec43f655e4f4ef08a636d33bc88f43e` · log `.glm-logs/w0815bf_w65_baselines/reeval_freshness.log` · coverage_segments untouched · mass=NO-GO |
| 10 | This close | deliverables · freeze · non-goals |

## Regression (Task D)

```
.venv/bin/python -m pytest \
  tests/test_baseline_catalog.py \
  tests/test_holding_metrics.py \
  tests/test_research_robustness_gate.py \
  tests/test_eval_harness.py \
  tests/test_r2_feature_context.py -q --tb=line
```

**Result:** all passed (no failures introduced).

## Gate / catalog table (research only)

| signal | multi-year gross | cost-aware | catalog status | READY | Mass |
|--------|------------------|------------|----------------|-------|------|
| S1 `c21_topix_relative_sign` | W63 soft PASS | W64 **FAIL** (+3/−3 net) | `research_baseline_rejected` | 未宣言 | NO-GO |
| S2 `c21_volume_change_sign` | not multi-year eval'd | not multi-year eval'd | `research_baseline_rejected` | 未宣言 | NO-GO |
| S3 `c21_topix_rel_disclosure_filter` | not multi-year eval'd | not multi-year eval'd | `research_baseline_rejected` | 未宣言 | NO-GO |
| S4 `c21_margin_change_sign` | W63 soft PASS (all −) | W64 PASS weak all − | `research_baseline_rejected` | 未宣言 | NO-GO |
| S5 `c21_short_ratio_delta_sign` | not multi-year eval'd (W62 FAIL) | not multi-year eval'd | `research_baseline_rejected` | 未宣言 | NO-GO |

## Holding metrics summary (S1 optional sample · research-only)

| stat | value |
|------|------:|
| source | W63 staged batch_summary (unanimous expand / partial sample) |
| n_runs (panel) | 4249 |
| mean hold | **≈1.88 days** |
| median / p50 | **2.0** |
| p90 | **4.0** |
| turnover_proxy `1/mean` | **≈0.53 / day** |
| amort illustration (10bp / 1.88) | **≈5.3 bp/day** one-way |

≠ READY / Mass / edge. Does not rescue S1 after W64 cost FAIL.

## Data gap priority (inventory only)

| id | gap | priority | action |
|----|-----|----------|--------|
| G1 | topix JSONL 2024–2025 | **P1** | ARCHIVE_OK · DO_NOT_DENSIFY |
| G2 | calendar JSONL tip-only | **P1** | ARCHIVE_OK + PIT · DO_NOT_DENSIFY |
| G3 | margin JSONL 2024 empty | **P1** | HOLD · empty_allowed |
| G4 | short JSONL 2024–2025 | **P2** | HOLD |
| G5–G9 | bar span / pre-2008 / fins sparse / tip plane / aa pollution | **P2** or **P1** | HOLD / ARCHIVE_OK |

**P0 count = 0** for current S1/S4 multi-year research path. COMPLETE **21** / DEFER **5** held. No densify.

## Cost definition (held from W64)

- one_way **10bp (0.001)** · RT **20bp**
- `net_one_way = gross_signed_mean_active − 0.001`
- label: 仮定に依存・研究用・運用GOではない

## Wave purpose outcome

単純日次 sign ベースライン（S1–S5）を **不合格として固定**。

- 残らなくても成功（不合格確定）
- **Mass / READY に進まない**
- S4 cost soft PASS も候補にしない（弱すぎる）
- holding metrics / gap inventory are research hygiene only

## Freezes (held)

| flag | value |
|------|-------|
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| ready_declared | **false** |
| operational_go | **false** |
| edge_claimed | **false** |
| COMPLETE / DEFER | **21 / 5** |
| COMPLETE segs | **3478** |
| OTC | **93** |
| actionable densify gap | **0** |
| P0 research-path gaps | **0** |
| FRESH | `projgen-3ec43f655e4f4ef08a636d33bc88f43e` |

## Non-goals (held)

- no Mass arm · no Phase7 · no READY · no densify · no COMPLETE 22 invent  
- no promote `return_1d_c21` · no Artifacts mass gen · no orders  
- no invent multi-year numbers for S2/S3/S5  
- no significance / edge / operational GO claim  
- no live multi-year re-campaign this wave (rejection uses W61–W64 evidence)

## Quality residual

| check | result |
|-------|--------|
| pytest (5 files) | **pass** |
| ops_reeval_freshness | **OK** · `projgen-3ec43f655e4f4ef08a636d33bc88f43e` · mass=NO-GO |
| residual TOP | W65 live verified |
| commit / push | Task D — W65 files only |

## Prior

- W64 cost multi-year: [`w0815be_w64_cost_multi_year_close_20260815.md`](w0815be_w64_cost_multi_year_close_20260815.md)
- W63 multi-year gross: [`w0815bd_w63_multi_year_close_20260815.md`](w0815bd_w63_multi_year_close_20260815.md)
- W62 gate + S4/S5: [`w0815bc_w62_gate_hyp_close_20260815.md`](w0815bc_w62_gate_hyp_close_20260815.md)
- W61 multi-period: [`w0815bb_w61_multi_period_close_20260815.md`](w0815bb_w61_multi_period_close_20260815.md)

*End of W65 / w0815bf close. READY 未宣言 · Mass NO-GO · Phase7 OFF · no edge.*
