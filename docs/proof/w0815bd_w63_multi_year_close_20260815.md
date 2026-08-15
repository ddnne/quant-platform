# W63 / w0815bd — Multi-year research evaluation close

**Status:** research evaluation complete · **READY 未宣言** · Mass **NO-GO** · Phase7 **OFF**

## Delivered

1. APIs: `design_yearly_eval_windows`, `run_multi_year_s1_eval`, `run_multi_year_extra_hyp_eval`, `multi_year_availability_table` in `packages/product/research/eval_harness.py`
2. Live R2 multi-year S1 (6/6 ok) + S4 (6/6 ok) for years 2015,2017,2019,2021,2023,2025 Q4 · 50d · 30 codes
3. Robustness gate: S1 **PASS** (majority +) · S4 **PASS** (majority −) — **pass ≠ READY/Mass**
4. Honest gaps: topix JSONL 2024–25 → archive · calendar archive PIT · margin 2024 empty (not in year list; documented)
5. Year-split: fail-one-year-safe (unit-tested)
6. Proof: this file + `w0815bd_w63_multi_year_eval_20260815.md` + `w0815bd_w63_year_availability_20260815.md`
7. Tests: multi-year isolation + Mass OFF freezes

## Gate table

| signal | n_eligible years | majority sign | gate | READY | Mass |
|--------|-----------------:|--------------:|------|-------|------|
| S1 topix_rel | 6 | 1 | **PASS** | 未宣言 | NO-GO |
| S4 margin_change | 6 | -1 | **PASS** | 未宣言 | NO-GO |

## Non-goals (held)

- no Mass arm · no Phase7 · no READY · no densify · no COMPLETE 22 invent · no promote `return_1d_c21`

