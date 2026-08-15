# W64 / w0815be — Cost-aware multi-year research close

**Status:** research evaluation complete · **READY 未宣言** · Mass **NO-GO** · Phase7 **OFF**

## Delivered

1. **Gate v2:** `robustness_gate.py` — default `net_sign_majority` (net = gross − 10bp one-way); helpers `research_net_one_way`, `annotate_period_rows_with_cost`
2. **Harness:** `run_multi_year_s1_eval` / `run_multi_year_extra_hyp_eval` wire cost + `require_net_sign_majority` (default True)
3. **W63 Q4 recompute cost-after:** S1 **cost FAIL** · S4 cost PASS (weak all −) — tables in eval proof
4. **Full-year expand:** S1 bar-span-bound ~100d on 2015/19/21/23 — gross and cost majority **FAIL**
5. **Gaps honest:** topix 2024–25 archive · margin 2024 empty · bar sample not invent to Dec
6. **Tests:** gate + harness + r2_feature_context green; Mass OFF freezes held
7. **FRESH:** `projgen-31ae63a75b9a477a8b7e6f9d34f6f630` · coverage_segments untouched · mass=NO-GO
8. **Proofs:** this close + `w0815be_w64_cost_multi_year_eval_20260815.md`
9. **Logs:** [`.glm-logs/w0815be_w64_cost_full/`](../../.glm-logs/w0815be_w64_cost_full/)

## Gate table (cost-aware · research only)

| signal | window | gross_only | cost-aware | READY | Mass |
|--------|--------|------------|------------|-------|------|
| S1 topix_rel | Q4 6y | PASS (+ maj) | **FAIL** (+3/−3 net) | 未宣言 | NO-GO |
| S4 margin | Q4 6y | PASS (− maj) | **PASS** (− maj; weak) | 未宣言 | NO-GO |
| S1 topix_rel | full ~100d 4y | **FAIL** | **FAIL** | 未宣言 | NO-GO |

## Cost definition

- one_way **10bp (0.001)** · RT **20bp**
- `net_one_way = gross_signed_mean_active − 0.001`
- label: 仮定に依存・研究用・運用GOではない

## Wave purpose outcome

「符号の多数決」→「コスト後も残るか」へ一段厳しく評価した。

- S1: **コスト後に多数崩落** → soft PASS 過大評価を確定
- S4: コスト後も符号多数は残るが **大きさは消える級**（候補にしない）
- 通年化でも S1 は救済されない
- **残らなくても成功**（不合格確定）· **Mass / READY に進まない**

## Non-goals (held)

- no Mass arm · no Phase7 · no READY · no densify · no COMPLETE 22 invent · no promote `return_1d_c21` · no Artifacts mass gen · no orders
