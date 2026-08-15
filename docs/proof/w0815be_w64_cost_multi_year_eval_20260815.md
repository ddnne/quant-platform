# W64 / w0815be — Cost-aware multi-year research evaluation (S1 + S4)

**Phase:** コスト込み複数年研究評価（READY 未宣言）  
**Wave:** W64 / w0815be  
**Generated:** 2026-08-15T14:37:19+00:00  
**SoT:** R2 `quant-structured` history · D1 tip not long-history SoT · local mirrors disposable  
**Harness:** `run_multi_year_s1_eval` · `run_multi_year_extra_hyp_eval` · `evaluate_research_robustness_gate` v2  
**Logs:** [`.glm-logs/w0815be_w64_cost_full/`](../../.glm-logs/w0815be_w64_cost_full/)  
**Prior:** W63 Q4 multi-year gross soft PASS (`docs/proof/w0815bd_w63_multi_year_eval_20260815.md`)

## Explicit non-declarations

- **READY** — not declared (gate pass does **not** connect)
- **Mass** — **NO-GO**
- **Phase7** — **OFF**
- **No** edge / significance / operational GO claim
- **No** densify invent · COMPLETE remains **21** / DEFER **5**
- Gate pass (even cost-aware) ≠ READY / Mass / GO

## Research cost assumption (fixed)

| field | value |
|-------|------:|
| one_way_cost | **10 bp = 0.001** |
| round_trip | **20 bp = 0.002** |
| formula_one_way | `net = gross_signed_mean_active − one_way_cost` |
| formula_round_trip | `net = gross_signed_mean_active − 2×one_way_cost` |
| label | **仮定に依存・研究用・運用GOではない** |

Why 10bp one-way: matches existing single_shot research cost convention; change only with explicit reason.

## Gate v2 (cost-aware)

`packages/product/research/robustness_gate.py` · version **research-robustness-gate/v2**

| criterion | rule | required |
|-----------|------|----------|
| multi_period | ≥2 eligible periods | yes |
| sign_majority | strict majority same **gross** sign | yes |
| not_catastrophic | no period \|gross\| > 0.05 | yes |
| **net_sign_majority** | strict majority same sign of **net = gross − 10bp** | **yes (default on)** |
| wf_not_full_flip | optional train/test no full flip | no |

- `require_net_sign_majority=False` → gross-only legacy (still research-only)
- Gross-only soft PASS is **insufficient** when cost gate is on
- Fail after cost is a **valid research outcome** (not a bug)

## A. W63 Q4 recompute with cost (S1 / S4)

Windows: y2015/17/19/21/23/25_q4 · **50d** · **30 codes** · `history_source=r2`  
Source gross from W63 live; net derived with fixed 10bp one-way.

### S1 topix_rel — Q4 cost table

| period | gross | net_one_way (−10bp) | net_rt (−20bp) | gross_sign | net_sign | n_active |
|--------|------:|--------------------:|---------------:|-----------:|---------:|---------:|
| y2015_q4 | +0.002144 | **+0.001144** | +0.000144 | + | + | 1470 |
| y2017_q4 | −0.000363 | **−0.001363** | −0.002363 | − | − | 1470 |
| y2019_q4 | +0.001253 | **+0.000253** | −0.000747 | + | + | 1470 |
| y2021_q4 | +0.000976 | **−0.000024** | −0.001024 | + | − | 1470 |
| y2023_q4 | +0.001250 | **+0.000250** | −0.000750 | + | + | 1470 |
| y2025_q4 | −0.000901 | **−0.001901** | −0.002901 | − | − | 1470 |

| gate view | result |
|-----------|--------|
| gross_only (W63) | **PASS** (majority + : 4+/2−) |
| cost-aware v2 | **FAIL** (net sign +3 / −3 — no strict majority) |

**Research verdict S1 Q4:** cost after 10bp **destroys** the soft majority. Residual after cost is ~0–11bp on “winning” years; not a strategy candidate. **≠ READY/Mass.**

### S4 margin_change — Q4 cost table

| period | gross | net_one_way (−10bp) | net_rt (−20bp) | gross_sign | net_sign | n_active |
|--------|------:|--------------------:|---------------:|-----------:|---------:|---------:|
| y2015_q4 | −0.000697 | **−0.001697** | −0.002697 | − | − | 1500 |
| y2017_q4 | −0.000153 | **−0.001153** | −0.002153 | − | − | 1500 |
| y2019_q4 | −0.000971 | **−0.001971** | −0.002971 | − | − | 1494 |
| y2021_q4 | −0.000514 | **−0.001514** | −0.002514 | − | − | 1495 |
| y2023_q4 | −0.000104 | **−0.001104** | −0.002104 | − | − | 1500 |
| y2025_q4 | −0.000792 | **−0.001792** | −0.002792 | − | − | 1500 |

| gate view | result |
|-----------|--------|
| gross_only (W63) | **PASS** (majority − : 6/6) |
| cost-aware v2 | **PASS** (majority net − : 6/6) |

**Research verdict S4 Q4:** cost-aware majority holds (all −), but magnitudes are **tiny** (~1–10bp gross; after cost more negative). This is a **consistent weak negative print**, not an edge claim and **not** a Mass/READY candidate. Pass still ≠ GO.

## B. Full-year (longer) window expansion — S1

### Availability (honest)

| year | bars sample | trading days filtered | day span | full-year runnable? | notes |
|-----:|-------------|----------------------:|----------|---------------------|-------|
| 2015 | JSONL sample 80 keys | 197 | 2015-01-05 … 2015-10-21 | **yes** (bar-span bound, max 100d) | not calendar Dec end |
| 2017 | — | — | — | **skipped** this wave | Q4-only recompute sufficient for cost gate; full-year optional |
| 2019 | 80 keys | 192 | 2019-01-04 … 2019-10-18 | **yes** | same |
| 2021 | 80 keys | 193 | 2021-01-04 … 2021-10-15 | **yes** | same |
| 2023 | 80 keys | 193 | 2023-01-04 … 2023-10-13 | **yes** | same |
| 2025 | — | — | — | **skipped** full-year | tip/near-tip; Q4 already eval'd |

First full-year attempt used `period_end=Dec-29` while bar sample ended mid-Oct → all nextday R null. **Re-run bounds period to actual bar day span** (honest; no invent).

### S1 full bar-span (max 100d · 30 codes · cost-aware)

| period | n_days | gross | net_one_way | net_sign | n_active |
|--------|-------:|------:|------------:|---------:|---------:|
| y2015_full | 100 | **−0.004830** | −0.005830 | − | 2970 |
| y2019_full | 100 | **+0.001201** | +0.000201 | + | 2970 |
| y2021_full | 100 | **−0.000363** | −0.001363 | − | 2970 |
| y2023_full | 100 | **+0.000350** | −0.000650 | − | 2970 |

| gate view | result |
|-----------|--------|
| gross sign majority | **FAIL** (+2 / −2) |
| cost-aware net majority | **FAIL** (no majority; net mostly −) |

**Research verdict S1 full-span:** longer windows do **not** rescue S1. Sign majority collapses; cost pushes residual further toward zero/negative. Confirms Q4 soft PASS was window-sensitive and cost-fragile.

## C. Data gaps (inventory held / no densify)

| dataset | gap | handling |
|---------|-----|----------|
| `indices_bars_daily_topix` JSONL | **2024–2025** | archive full-history (W59); PIT held |
| `markets_margin_interest` | **2024** empty | not forced; years with margin only |
| full-year bars | sample ends ~Oct (not full calendar year) | period bound to bar span; **no invent Dec** |
| new holes this wave | none beyond known | inventory note only |

## Freeze (held)

| flag | value |
|------|-------|
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| ready_declared | **false** |
| operational_go | **false** |
| COMPLETE / DEFER | **21 / 5** |
| return_1d_c21 promote | **forbidden** |

## Summary verdict (wave purpose)

Wave purpose was: *after multi-year × cost, is anything left?*

| hyp | window | cost-aware | residual |
|-----|--------|------------|----------|
| S1 | Q4 6y | **FAIL** (+3/−3 net) | soft gross PASS overstated |
| S4 | Q4 6y | PASS (all −) but **weak** | not strategy candidate |
| S1 | full ~100d 4y | **FAIL** | no rescue |

**No path to READY / Mass / Phase7.** Cost-after multi-year is the correct stricter research bar; failure is success for this wave's purpose.
