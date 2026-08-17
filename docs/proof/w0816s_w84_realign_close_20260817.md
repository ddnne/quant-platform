# W84 / w0816s — research↔paper realign residual FRESH close

**Wave status:** **COMPLETE** — StrategySpec v3 realign · both default candidates **KEEP** · paper limited validity · parallel explore notes · OTC tip-wait 4499→4499 · COMPLETE 22 health · FRESH · residual pin · push  
**Wave:** W84 / `w0816s` · residual FRESH / commit / push  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Live verified:** `2026-08-17T12:09:47Z` · FRESH `projgen-c828a2b146114d79a7b5be9b67cf50c4` · coverage_segments FRESH-path untouched  
**Logs:** [`.glm-logs/w0816s_w84_realign/`](../../.glm-logs/w0816s_w84_realign/)  
**Prior:** W83 tip `4ca4ce5` · 2 default candidates · paper proxy xs **−1.96%** · fund **−4.06%** · OTC **4499**

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| operational GO | **未宣言** |
| continuous paper | **UNARMED** |
| live orders | **OFF** |
| simple_daily_sign | **not used** |
| S1–S5 un-reject | **forbidden** |
| mean-bp-only promotion | **forbidden** |
| event_post look-ahead revival | **forbidden** (W82 PIT only) |
| multi_day force-revive | **forbidden** |
| simplify research to match paper | **forbidden** |
| hide paper history / W83 negatives | **forbidden** |
| OTC bulk archive re-scan | **not run** (light tip only) |
| COMPLETE 23 invent | **forbidden** |
| NEW explore passers default-wire | **not done** (explore-only) |

**Success condition:** residual TOP = W84 landings · realign **KEEP both** · paper validity after align · parallel explore notes · OTC **4499→4499** tip-wait · GO **未宣言** · COMPLETE 22 held · push past W83 tip `4ca4ce5`.

---

## Task landings

| task | result | proof / log |
|------|--------|-------------|
| A+B research↔paper realign | **done** · StrategySpec **v3** sticky hold + CS rank + value×mom · both **KEEP** | [`w0816s_w84_research_paper_realign_20260817.md`](w0816s_w84_research_paper_realign_20260817.md) |
| C parallel explore | **done** · 4 NEW hard passers explore-only · flow near-miss · multi_day/event/macro reject | [`w0816s_w84_parallel_explore_20260817.md`](w0816s_w84_parallel_explore_20260817.md) |
| Paper limited (aligned) | **done** · xs **+1.54%** · fund **+4.72%** · W83 negatives retained as proxy history · continuous **UNARMED** | `paper_results.json` · `decisions.json` |
| OTC light tip | **done** · **4499 → 4499 (Δ0)** · dataset **PARTIAL** | `otc_tip_full_ok.json` |
| Health + FRESH + residual | **done** · this close · GO gates update · residual TOP W84 | this file · GO gates |
| COMPLETE 22 health | **pass** local+remote · COMPLETE **22** · OTC **4499** · segs **7888** · empty **0** | `health_w84_residual.log` · `health_w84_postfresh.log` |
| FRESH | `projgen-c828a2b146114d79a7b5be9b67cf50c4` · segs untouched · mass=NO-GO | `reeval_freshness_residual.log` |
| Pytest key surface | **61 green** | `pytest_w84_residual.log` |

---

## Default-path candidates after W84 realign

**Production research candidates on default path after W84: still 2 (KEEP).**  
**Mass / READY / operational GO / live: still closed.** Class_hyp `research_candidate=True` **≠** Mass/READY/ops GO.  
Research multi-year metrics **unchanged** (no research simplification).

| # | class / block | params | mean net | t | Sharpe | win | hard RC | paper limited (aligned) | decision | default-wired |
|---|---------------|--------|---------:|--:|-------:|----:|:------:|------------------------:|:--------:|:-------------:|
| 1 | **cross_section_hold_10** | sticky hold=**10** · **mom=5** | **+84.6bp** | **1.60** | **0.65** | 0.67 | **True** | **+1.54%** | **KEEP** | **yes** |
| 2 | **fundamentals_hold_10** | hold=**10** · **mom=10** value×mom | **+45.9bp** | **1.82** | **0.74** | 0.67 | **True** | **+4.72%** | **KEEP** | **yes** |

### Paper validity (W83 history kept)

| candidate | W83 proxy limited | W84 aligned limited | validity |
|-----------|------------------:|--------------------:|----------|
| xs hold10 | **−1.96%** (175 trades) | **+1.54%** (60 trades) | W83 negative = **expected proxy artifact** (daily top_k long-only ≠ sticky CS L-S); **not** bug · **not** edge falsification |
| fund hold10 | **−4.06%** (152 trades) | **+4.72%** (55 trades) | W83 negative = **expected** (mom-only proxy missing value leg); **not** bug |

Limited-window paper PnL is **not** alpha / significance / edge claim (positive or negative). Continuous paper remains **UNARMED**.

### StrategySpec v3 (align paper → research)

| capability | detail |
|------------|--------|
| version | `strategy-spec/v3` (v2 still parseable) |
| rebalance | `daily` + **`fixed_horizon`** + `hold_days` sticky empty mid-hold |
| rules | `threshold` · `top_k` · **`cross_section_rank`** · **`value_momentum_agree`** |
| features | approved `fundamental_value_score` (BPS/P\|EPS/P PIT) |
| engine | negative target weights allowed (simple short book) |

Residual approximations: portfolio MTM vs trade-level research mean · no margin/borrow · fund value CS median vs research global median.

---

## Parallel explore notes (Task C · not default-wired)

| # | class | variant | mean | t | Sharpe | win | hard RC | default-wired |
|---|-------|---------|-----:|--:|-------:|----:|:------:|:-------------:|
| 1 | cross_section | hold=10 **mom=3** | +120.1bp | **3.04** | **1.24** | **1.00** | **True** | **no** (explore) |
| 2 | cross_section | hold=10 mom=5 **frac=0.4** | +62.9bp | 1.69 | 0.69 | 0.67 | **True** | **no** (explore) |
| 3 | fundamentals | hold=**15** mom=10 agree | +91.5bp | 1.80 | 0.73 | 0.83 | **True** | **no** (explore) |
| 4 | fundamentals | hold=**5** mom=10 agree | +24.4bp | 1.92 | 0.78 | 0.83 | **True** | **no** (explore) |

| near-miss / reject | note |
|--------------------|------|
| flow hold=5 short_confirm | t=1.54 · Sharpe=0.63 · **occ fail** · near-miss |
| multi_day hold=7/10/15 | stats/econ fail · **no force-revive** |
| event_post PIT | still reject · no look-ahead revival |
| macro_conditioned | all negative residual · reject |

Explore paper (v2 proxy only) limited mostly **negative** honestly — not used to demote research hard passers; default path uses **aligned v3** path for the 2 KEPT candidates.

---

## OTC light tip FULL_OK

| metric | value |
|--------|------:|
| dataset | `jsda_otc_bond_reference_prices` |
| dataset status | **PARTIAL** (held) |
| COMPLETE segments | **4499** |
| span | **2008-03-25 … 2026-08-17** |
| W83 pin | 4499 |
| **4499 → ?** | **4499 → 4499 (Δ0)** |
| bulk archive re-scan | **not run** |

---

## COMPLETE 22 health

| source | all_checks_pass | COMPLETE | PARTIAL | fins | empty | OTC | bars_am | segs |
|--------|-----------------|----------|---------|------|-------|-----|---------|------|
| local SQLite | **true** | 22 | 4 | 104 | 0 | **4499** | 1 | **7888** |
| remote D1 (post-FRESH) | **true** | 22 | 4 | 104 | 0 | **4499** | 1 | **7888** |

Note: OTC **dataset** status remains **PARTIAL**. Platform COMPLETE datasets stay **22**. No invent 23.

Log: `.glm-logs/w0816s_w84_realign/health_w84_residual.log` · `health_w84_postfresh.log`

### FRESH

| field | value |
|-------|-------|
| gen | `projgen-c828a2b146114d79a7b5be9b67cf50c4` |
| now | `2026-08-17T12:09:47.338375+00:00` |
| coverage_segments_untouched | **1** |
| mass | **NO-GO** |

Log: `.glm-logs/w0816s_w84_realign/reeval_freshness_residual.log`

### Standard research eval (wiring_only · dry_run)

| field | value |
|-------|-------|
| checklist_version | `standard-research-eval-checklist/v2` |
| mode | `wiring_only` |
| dry_run | `true` |
| ready_declared | **False** |
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| operational_go | **False** |
| research_candidate (harness) | **False** |
| research_candidate_allowed | **False** |
| prefer_repo_linked | **True** |
| prefer_liquidity_linked | **True** |
| gate_pass_implies_* | all **False** |

Log: `.glm-logs/w0816s_w84_realign/standard_eval_wiring.json`

### Pytest counts (green)

| suite | n |
|-------|--:|
| `tests/test_strategy_spec_schema.py` | **13** (+v3 fixed_horizon · CS rank · value×mom) |
| `tests/test_paper_candidate_adapter.py` | **14** (+aligned builders) |
| `tests/test_class_signals.py` | **17** |
| `tests/test_standard_research_eval.py` | **17** |
| **total** | **61** |

Log: `.glm-logs/w0816s_w84_realign/pytest_w84_residual.log`

---

## Delivered code

| artifact | path | role |
|----------|------|------|
| StrategySpec **v3** schema | `packages/research_runtime/strategies/spec/schema.py` | fixed_horizon · CS rank · value×mom · v2 compat |
| Interpreter sticky + L-S | `packages/research_runtime/strategies/spec/interpreter.py` | empty mid-hold · CS weights · value×mom |
| Engine short book | `packages/research_runtime/core/engine.py` | negative target weights |
| Feature `fundamental_value_score` | `packages/research_runtime/features/complete21_min.py` | approved PIT value |
| Paper adapter v3 | `packages/product/research/paper_candidate_adapter.py` | aligned builders for xs/fund defaults |
| Tests | `tests/test_strategy_spec_schema.py` · `tests/test_paper_candidate_adapter.py` | v3 + adapter coverage |

---

## Explicit non-declarations (held)

- **READY** — not declared  
- **Mass** — **NO-GO / OFF**  
- **Phase7** — **OFF**  
- **operational GO** — **未宣言**  
- **Dataset COMPLETE 23** — not invented  
- **OTC dataset COMPLETE** — not forced (segment COMPLETE 4499 only; dataset PARTIAL)  
- **empty COMPLETE** — not minted (0 held)  
- **research_candidate → Mass/READY/ops GO** — never auto-connects  
- **paper continuous / unlimited arm** — **False**  
- **live orders** — **forbidden** this residual  
- **S1–S5 un-reject** — not done  
- **simple_daily_sign mass generation** — **forbidden** (default OFF)  
- **OTC bulk densify / archive re-scan** — not run  
- **limited paper PnL as edge / significance** — **not claimed** (positives after align; W83 negatives retained as proxy history)  
- **simplify research to match paper** — **forbidden** (research metrics unchanged)  
- **hide W83 paper negatives** — **forbidden** (shown as proxy artifacts)  
- **multi_day_hold production candidate** — **still demoted**  
- **event_post production candidate** — **still demoted** (PIT)  
- **mean-bp-only promotion** — **forbidden**  
- **NEW explore passers default-wire** — **not done** (xs mom=3 / frac=0.4 · fund hold15/hold5 explore-only)  

---

## Residual TOP (W84)

1. **Realign KEEP both** — `cross_section_hold_10` (mom=**5**) · `fundamentals_hold_10` (mom=**10**) · research metrics **unchanged**  
2. **StrategySpec v3** — sticky `fixed_horizon` + `cross_section_rank` + `value_momentum_agree` · paper aligned toward research  
3. **Paper validity** — W83 limited **xs −1.96%** · **fund −4.06%** were **proxy artifacts**; W84 aligned **xs +1.54%** · **fund +4.72%** · continuous **UNARMED** · not edge claim  
4. **Parallel explore notes** — 4 NEW hard passers **explore-only not default-wired** · flow near-miss · multi_day/event/macro **reject**  
5. **OTC tip-wait** — **4499→4499 (Δ0)** · dataset **PARTIAL** · no bulk re-scan  
6. **GO 未宣言** — Mass **NO-GO** · READY **未宣言** · operational GO **未宣言** · Phase7 **OFF**  
7. **COMPLETE 22 held** · empty **0** · no invent 23 · segs **7888** · costs v2 · stats bar · PIT integrity held  
8. **FRESH residual** — `projgen-c828a2b146114d79a7b5be9b67cf50c4` · coverage_segments untouched  
9. **W83 underneath** — 2 default candidates · parallel explore · paper proxy history · OTC 4499  

See also: [`w0816s_w84_go_gates_20260817.md`](w0816s_w84_go_gates_20260817.md)

---

## Prior tip / push

| item | value |
|------|-------|
| W83 tip (start) | `4ca4ce5` — docs pin after parallel default-candidate close |
| W83 feature tip | `12e3e46` — parallel default candidates + paper negatives + OTC tip-wait + FRESH close |
| W84 feature tip | *(this commit)* — StrategySpec v3 realign + KEEP both + paper validity + explore notes + FRESH close |
| This wave | commit + push on `main` past `4ca4ce5` |

---

## Related proofs

| doc | role |
|-----|------|
| Research↔paper realign (A+B) | [`w0816s_w84_research_paper_realign_20260817.md`](w0816s_w84_research_paper_realign_20260817.md) |
| Parallel explore (C) | [`w0816s_w84_parallel_explore_20260817.md`](w0816s_w84_parallel_explore_20260817.md) |
| GO gates | [`w0816s_w84_go_gates_20260817.md`](w0816s_w84_go_gates_20260817.md) |
| Residual SoT | [`docs/phase62_residual_status.md`](../phase62_residual_status.md) |
| W83 close | [`w0816r_w83_parallel_close_20260817.md`](w0816r_w83_parallel_close_20260817.md) |

---

## Logs index

```text
.glm-logs/w0816s_w84_realign/
  run_w84_realign.py · run_w84_parallel_explore.py · run_w84_paper_passers.py
  gap_tables.json · decisions.json · candidate_list.json
  class_hyp_multi_year_bundle.json · explore_table.json · explore_strong.json
  paper_results.json · paper_trial_card.json · paper_specs/
  otc_tip_full_ok.json
  health_w84_residual.log · health_w84_postfresh.log
  reeval_freshness_residual.log
  pytest_w84_residual.log
  standard_eval_wiring.json
```
