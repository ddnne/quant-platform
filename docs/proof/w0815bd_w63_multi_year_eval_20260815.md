# W63 / w0815bd — Multi-year research evaluation (S1 + S4)

**Phase:** 複数年研究評価（READY 未宣言）  
**Wave:** W63 / w0815bd  
**Generated:** 2026-08-15T14:08:08.252847+00:00  
**SoT:** R2 `quant-structured` history · D1 tip not long-history SoT · local mirrors disposable  
**Harness:** `design_yearly_eval_windows` · `run_multi_year_s1_eval` · `run_multi_year_extra_hyp_eval`  
**Logs:** [`.glm-logs/w0815bd_w63_multiyear/`](../../.glm-logs/w0815bd_w63_multiyear/)  

## Explicit non-declarations

- **READY** — not declared (robustness_gate pass does **not** connect)
- **Mass** — **NO-GO**
- **Phase7** — **OFF**
- **No** edge / significance / operational GO claim
- **No** densify invent · COMPLETE remains **21** / DEFER **5**

## Year windows (designed)

| period_id | year | window | period_start | period_end | max_days | s4_eligible (inventory) |
|-----------|-----:|--------|--------------|------------|---------:|-------------------------|
| y2015_q4 | 2015 | q4 | 2015-09-01 | 2015-12-29 | 50 | yes (2013–2023,2025–2026; 2024 gap not in list) |
| y2017_q4 | 2017 | q4 | 2017-09-01 | 2017-12-29 | 50 | yes (2013–2023,2025–2026; 2024 gap not in list) |
| y2019_q4 | 2019 | q4 | 2019-09-01 | 2019-12-29 | 50 | yes (2013–2023,2025–2026; 2024 gap not in list) |
| y2021_q4 | 2021 | q4 | 2021-09-01 | 2021-12-29 | 50 | yes (2013–2023,2025–2026; 2024 gap not in list) |
| y2023_q4 | 2023 | q4 | 2023-09-01 | 2023-12-29 | 50 | yes (2013–2023,2025–2026; 2024 gap not in list) |
| y2025_q4 | 2025 | q4 | 2025-09-01 | 2025-12-29 | 50 | yes (2013–2023,2025–2026; 2024 gap not in list) |

Fixed universe: **30** liquid TSE codes (same as W60/W61). Non-contiguous years OK.

## Data availability (honest gaps)

| dataset | inventory | handling this wave |
|---------|-----------|--------------------|
| `equities_bars_daily` | JSONL 2008–2026 | live R2 JSONL → code-filtered disposable mirror per year |
| `indices_bars_daily_topix` | JSONL gap **2024–2025** | **archive** full-history mirror (W59) |
| `markets_calendar` | JSONL tip 2026 only | **archive** + research PIT repair (`calendar_ingest_pollution`) |
| `markets_margin_interest` | gap year **2024** empty | years in list all have margin mirrors; **no invent densify** |

See also [`w0815bb_w61_coverage_inventory_20260815.md`](w0815bb_w61_coverage_inventory_20260815.md).

## S1 multi-year results (`c21_topix_relative_sign`)

- years requested **6** · ok **6** · skipped **0** · error **0**
- year_split / fail_one_year_safe: **True** / **True**
- history_source: **r2**

| period | n_days | n_codes | mean R +1 | mean R −1 | gross signed mean | n_active |
|--------|-------:|--------:|----------:|----------:|------------------:|---------:|
| y2015_q4 | 50 | 30 | +0.003104 | -0.001362 | **+0.002144** | 1470 |
| y2017_q4 | 50 | 30 | +0.001036 | +0.001329 | **-0.000363** | 1470 |
| y2019_q4 | 50 | 30 | +0.002225 | -0.000393 | **+0.001253** | 1470 |
| y2021_q4 | 50 | 30 | +0.001370 | -0.000566 | **+0.000976** | 1470 |
| y2023_q4 | 50 | 30 | +0.002408 | -0.000225 | **+0.001250** | 1470 |
| y2025_q4 | 50 | 30 | -0.001126 | +0.000688 | **-0.000901** | 1470 |

### Research robustness gate (S1)

- **passed:** `True`
- reasons: ['all required research gate criteria met']
- majority_sign: `1` (+ = long-relative-outperform print majority)
- n_eligible: `6`
- ready_declared / operational_go / connected_to_ready / connected_to_mass: **False** / **False** / **False** / **False**

> Gate pass is a **research checklist** only. It does **not** mint READY or arm Mass.

## S4 multi-year results (`c21_margin_change_sign`) — optional years with margin

- years requested **6** · ok **6** · skipped **0** · error **0**

| period | n_days | non_null_rate | gross signed mean | n_active |
|--------|-------:|--------------:|------------------:|---------:|
| y2015_q4 | 50 | 1.0 | **-0.000697** | 1500 |
| y2017_q4 | 50 | 1.0 | **-0.000153** | 1500 |
| y2019_q4 | 50 | 1.0 | **-0.000971** | 1494 |
| y2021_q4 | 50 | 1.0 | **-0.000514** | 1495 |
| y2023_q4 | 50 | 1.0 | **-0.000104** | 1500 |
| y2025_q4 | 50 | 1.0 | **-0.000792** | 1500 |

### Research robustness gate (S4)

- **passed:** `True`
- reasons: ['all required research gate criteria met']
- majority_sign: `-1`
- n_eligible: `6`
- freeze: ready **False** · Mass **NO-GO** · connected_to_ready **False**

## Interpretation (research-only)

- S1 gross signed mean is **positive in 4/6** non-contiguous Q4 windows (2015,2019,2021,2023) and negative in 2017/2025 — **not** stable enough for ops; gate soft-pass on sign majority only.
- S4 margin-change sign is **negative in 6/6** windows — consistent print direction but magnitude is small and **no** cost-adjusted edge claim.
- Tip-path / short-window wins remain untrusted without multi-year context (W62 lesson held).
- **小サンプル / 研究用・未宣言**

## Artifacts

| file | role |
|------|------|
| `designed_windows.json` | year window design |
| `prep_report.json` | per-year R2 pull / filter stats |
| `s1_multi_year_results.json` | full S1 batch + gate |
| `s4_multi_year_results.json` | full S4 batch + gate |
| `availability_table.json` | compact availability |
| `summary.json` | rollup |
| `freeze_status.json` | Mass/Phase7/READY freezes |

## Regression holds

- tip path APIs unchanged (default `history_source=d1_tip`)
- Mass research gate OFF tests pass
- robustness_gate pass ↛ READY/Mass

