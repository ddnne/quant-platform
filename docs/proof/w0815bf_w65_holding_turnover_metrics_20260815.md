# W65 / w0815bf — Holding-period / turnover research metrics (optional B)

**Phase:** 保有・回転の研究用メトリクス（READY 未宣言）  
**Wave:** W65 / w0815bf  
**Generated:** 2026-08-15  
**Module:** `packages/product/research/holding_metrics.py`  
**Logs:** [`.glm-logs/w0815bf_w65_baselines/`](../../.glm-logs/w0815bf_w65_baselines/)  
**Prior cost context:** W64 cost-aware multi-year (`docs/proof/w0815be_w64_cost_multi_year_eval_20260815.md`)

## Explicit non-declarations

- **READY** — not declared
- **Mass** — **NO-GO**
- **Phase7** — **OFF**
- **No** edge / significance / operational GO claim
- Labels: **仮定に依存・研究用・未宣言**
- Cost amortization is a **research illustration only** (not a trading model)

## Delivered APIs (pure / unit-tested)

| API | role |
|-----|------|
| `sign_from_value` | map raw → `+1/0/−1/None` |
| `run_lengths_for_sign_sequence` | consecutive same **non-zero** sign run lengths |
| `run_length_distribution` | mean / median / p50 / p90 + histogram |
| `histogram_run_lengths` | bucket counts (1, 2, 3, 4–5, 6–10, 11+) |
| `panel_run_lengths_by_code` | per-code runs from (day, code, sign) panel |
| `panel_run_length_stats` | aggregate panel stats + freeze flags |
| `extract_sign_panel_from_batch_summary` | best-effort panel from staged `batch_summary` |
| `cost_amortization_table` | `effective_daily_cost ≈ one_way / N` rows |
| `cost_amortization_report` | freeze-wrapped amortization document |
| `holding_metrics_report` | run-length + amortization package |
| `holding_metrics_document` | public surface + freeze constants |

Freeze constants (always closed): `MASS_RESEARCH="NO-GO"`, `PHASE7="OFF"`, `READY_DECLARED=False`, `OPERATIONAL_GO=False`, `EDGE_CLAIMED=False`.

### Run-length rule

- Chronological per-(day, code) discrete signs
- Run = consecutive **same non-zero** sign (`+1` or `−1`)
- `0` (flat) and `None` (missing) **break** the current run
- Sign flip ends the run and starts a new one

### Cost amortization (研究用イラスト)

Fixed research assumption: **one_way = 10bp = 0.001** (matches W64 / robustness_gate).

| hold N (days) | effective daily (one-way) | bp/day | effective daily (RT=2×) | RT bp/day |
|--------------:|--------------------------:|-------:|------------------------:|----------:|
| 1 | 0.001 | 10.0 | 0.002 | 20.0 |
| 2 | 0.0005 | 5.0 | 0.001 | 10.0 |
| 3 | ≈0.000333 | ≈3.33 | ≈0.000667 | ≈6.67 |
| 5 | 0.0002 | 2.0 | 0.0004 | 4.0 |
| 10 | 0.0001 | 1.0 | 0.0002 | 2.0 |
| 20 | 0.00005 | 0.5 | 0.0001 | 1.0 |

Formula: `effective_daily_cost ≈ one_way_cost / hold_days_N` · **仮定に依存・研究用・運用モデルではない**.

## Optional S1 sample (staged artifacts — no live R2 re-download)

**Source:** W63 staged multiday `batch_summary.json` under  
`.glm-logs/w0815bd_w63_multiyear/r2_stage/research/single_shot/job=w0815bd-w63-s1-*`  
**Output:** `.glm-logs/w0815bf_w65_baselines/holding_metrics_s1.json`  
**Signal:** S1 `c21_topix_relative_sign` · Q4 windows y2015/17/19/21/23/25 · 50d · 30 codes (artifact metadata)

### Reconstruction note

- Full per-(day, code) rows are **not** stored in batch_summary (only `sample_values` ≤10 + aggregate `sign_distribution`).
- For periods where each day is **unanimous** (all codes same sign), majority expansion is exact.
- y2015–y2023_q4: unanimous → `sign_distribution_majority_expanded_unanimous`
- y2025_q4: mixed days present → fell back to **partial** `sample_values` only
- **Live S1 hold distribution re-eval deferred / optional sample only**

### Pooled panel run-length (all reconstructed records)

| stat | value |
|------|------:|
| n_runs | 4249 |
| mean | **≈1.88 days** |
| median / p50 | **2.0** |
| p90 | **4.0** |
| min / max | 1 / (see histogram) |
| turnover_proxy `1/mean` | **≈0.53 / day** |

Day-level majority series (one series per period, not × codes): mean **≈1.82**, p50 **1**, p90 **3**, n_runs **161**.

### Per-period mean hold (panel)

| period | mean | p50 | p90 | n_runs | panel source |
|--------|-----:|----:|----:|-------:|--------------|
| y2015_q4 | 1.72 | 1 | 3 | 870 | unanimous expand |
| y2017_q4 | 2.08 | 2 | 4 | 720 | unanimous expand |
| y2019_q4 | 2.50 | 2 | 4 | 600 | unanimous expand |
| y2021_q4 | 1.67 | 1 | 3 | 900 | unanimous expand |
| y2023_q4 | 1.67 | 1 | 3 | 900 | unanimous expand |
| y2025_q4 | 1.93 | 2 | 4 | 259 | sample_values partial |

### Illustration vs 10bp one-way

At pooled mean hold ≈ **1.88 d**, simple amortization gives  
`effective_daily ≈ 10bp / 1.88 ≈ **5.3 bp/day**` (one-way illustration).

This does **not** rescue S1 after W64 cost FAIL; it only shows that with ~2-day mean hold, nearly full one-way cost hits every other day. **≠ READY / Mass / edge.**

## Tests

`tests/test_holding_metrics.py`

- known run-length sequence
- zero / null break runs
- distribution mean/median/p50/p90 + histogram
- amortization table numbers (10bp → N=1,2,5,10)
- API dicts freeze Mass OFF / READY false / no edge
- batch_summary extract synthetic unanimous panel

## Non-goals (held)

- no Mass arm · no Phase7 · no READY · no densify · no edge claim  
- no live R2 re-eval required for this wave  
- no promotion of any signal to strategy-default
