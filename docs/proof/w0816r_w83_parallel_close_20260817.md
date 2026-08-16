# W83 / w0816r — parallel multi-strategy residual FRESH close

**Wave status:** **COMPLETE** — default-path 2 candidates · parallel explore matrix · paper limited honest negatives · OTC tip-wait 4499→4499 · COMPLETE 22 health · FRESH · residual pin · push  
**Wave:** W83 / `w0816r` · parallel strategy search residual FRESH / commit / push  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Live verified:** `2026-08-16T22:19:42Z` · FRESH `projgen-94a53a62ee314253972bde91f2e4cb4f` · coverage_segments FRESH-path untouched  
**Logs:** [`.glm-logs/w0816r_w83_parallel/`](../../.glm-logs/w0816r_w83_parallel/)  
**Prior:** W82 event_post PIT demote · optional xs hold=10 KEEP (not default-wired) · multi_day 10d demoted · 0 production default candidates · tip `4696f36`

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
| multi_day 10d force-revive | **forbidden** |
| OTC bulk archive re-scan | **not run** (light tip only) |
| COMPLETE 23 invent | **forbidden** |

**Success condition:** residual TOP = W83 landings · **2 default research candidates** wired · paper limited **negatives** shown honestly · OTC **4499→4499** tip-wait · GO **未宣言** · COMPLETE 22 held · push past W82 tip `4696f36`.

---

## Task landings

| task | result | proof / log |
|------|--------|-------------|
| Parallel multi-family explore | **done** · all families; 2 hard-bar passers | [`w0816r_w83_parallel_strategy_search_20260817.md`](w0816r_w83_parallel_strategy_search_20260817.md) |
| Default path rewire | **done** · `cross_section_hold_10` (mom=5) + `fundamentals_hold_10` (mom=10) | class_hyp_eval **v6** · defaults `include_*=True` |
| Paper limited (passers only) | **done** · xs **−1.96%** · fund **−4.06%** honest · continuous **UNARMED** | `paper_results.json` · `paper_trial_card.json` |
| OTC light tip | **done** · **4499 → 4499 (Δ0)** · dataset **PARTIAL** | `otc_tip_full_ok.json` |
| Health + FRESH + residual | **done** · this close · GO gates update · residual TOP W83 | this file · GO gates |
| COMPLETE 22 health | **pass** local+remote · COMPLETE **22** · OTC **4499** · segs **7888** · empty **0** | `health_w83_*.log` |
| FRESH | `projgen-94a53a62ee314253972bde91f2e4cb4f` · segs untouched · mass=NO-GO | `reeval_freshness_residual.log` |
| Pytest key surface | **58 green** | `pytest_w83_residual.log` |

---

## Default-path candidates (W83)

**Production research candidates on default path after W83: 2.**  
**Mass / READY / operational GO / live: still closed.** Class_hyp `research_candidate=True` **≠** Mass/READY/ops GO.

| # | class / block | params | mean net | t | Sharpe | win | hard RC | holistic | default-wired |
|---|---------------|--------|---------:|--:|-------:|----:|:------:|----------|:-------------:|
| 1 | **cross_section_hold_10** | sticky hold=**10** · **mom=5** (W82 pin) | **+84.6bp** | **1.60** | **0.65** | 0.67 | **True** | **default_candidate** | **yes** |
| 2 | **fundamentals_hold_10** | hold=**10** · **mom=10** value×mom agree | **+45.9bp** | **1.82** | **0.74** | 0.67 | **True** | **default_candidate** | **yes** |

Primary defaults still present (not candidates): xs hold=5 · fund hold=20/mom=20 · multi_day 5+10 · event PIT · flow hold=5 · macro.

### Content caveat (xs)

* **momentum_n must stay 5** for sticky hold=10. Explore mom=10 collapses residual (+6.6bp · t=0.24) — do not “content-match” blindly.

---

## Parallel table summary (default multi-year path)

Windows: full+Q4 (`y2015_full` · `y2017_q4` · `y2019_full` · `y2021_full` · `y2023_full` · `y2025_q4`) · 30 large-cap · liquidity one-way · costs v2.

| class / block | mean net | t | Sharpe | win-rate | hard RC | **holistic** |
|---------------|---------:|--:|-------:|---------:|:------:|--------------|
| multi_day_hold 5d | +0.4bp | 0.03 | 0.01 | 0.50 | False | **reject** |
| multi_day_hold 10d | +21.1bp | 0.62 | 0.25 | 0.67 | False | **reject** (noisy; no force-revive) |
| event_post PIT | +5.9bp | 0.25 | 0.10 | 0.67 | False | **reject** (no look-ahead revival) |
| macro_conditioned | −24.1bp | −3.16 | −1.29 | 0.00 | False | **reject** |
| cross_section hold=5 | −10.9bp | −0.44 | −0.18 | 0.50 | False | **reject** |
| **cross_section hold=10 mom=5** | **+84.6bp** | **1.60** | **0.65** | **0.67** | **True** | **default_candidate** |
| flow_demand hold=5 | +117.9bp* | 0.76 | 0.31 | 0.33 | False | **reject** (*mean high, majority neg) |
| fundamentals hold=20 mom=20 | +70.9bp | 1.04 | 0.42 | 0.67 | False | **conditional** (discussion_only) |
| **fundamentals hold=10 mom=10** | **+45.9bp** | **1.82** | **0.74** | **0.67** | **True** | **default_candidate** |

Rejected explore (not default-wired): multi_day hold=20 · event PIT hold=10 · flow hold=10/20 + short_confirm · fund value_only / hold=40 · xs mom=10 / hold=20 / frac=0.2 · macro rate_level.

---

## Paper (passers only) — honest negatives

Continuous scheduler **UNARMED**. Live **OFF**. Fidelity = **StrategySpec v2 proxy** (momentum_n top_k). Gap irreducible under v2 (no sticky CS L-S ranks; fund value leg not expressible).

| trial | class | window | post-cost | maxDD | trades | note |
|-------|-------|--------|----------:|------:|-------:|------|
| single-shot | xs hold10 proxy | 5d Draft | **+1.16%** | −0.13% | 27 | dry healthy |
| **limited** | xs hold10 proxy | 30d Paper | **−1.96%** | −5.14% | 175 | **honest negative** |
| single-shot | fund hold10 proxy | 5d Draft | **+2.17%** | −0.27% | 23 | dry healthy |
| **limited** | fund hold10 proxy | 30d Paper | **−4.06%** | −10.35% | 152 | **honest negative** |

Limited-window proxy PnL is **not** alpha / significance / edge claim.

---

## OTC light tip FULL_OK

| metric | value |
|--------|------:|
| dataset | `jsda_otc_bond_reference_prices` |
| dataset status | **PARTIAL** (held) |
| COMPLETE segments | **4499** |
| span | **2008-03-25 … 2026-08-17** |
| W82 pin | 4499 |
| **4499 → ?** | **4499 → 4499 (Δ0)** |
| bulk archive re-scan | **not run** |

---

## COMPLETE 22 health

| source | all_checks_pass | COMPLETE | PARTIAL | fins | empty | OTC | bars_am | segs |
|--------|-----------------|----------|---------|------|-------|-----|---------|------|
| local SQLite | **true** | 22 | 4 | 104 | 0 | **4499** | 1 | **7888** |
| remote D1 (post-FRESH) | **true** | 22 | 4 | 104 | 0 | **4499** | 1 | **7888** |

Note: OTC **dataset** status remains **PARTIAL**. Platform COMPLETE datasets stay **22**. No invent 23.

Log: `.glm-logs/w0816r_w83_parallel/health_w83_residual.log` · `health_w83_postfresh.log`

### FRESH

| field | value |
|-------|-------|
| gen | `projgen-94a53a62ee314253972bde91f2e4cb4f` |
| now | `2026-08-16T22:19:42.919337+00:00` |
| coverage_segments_untouched | **1** |
| mass | **NO-GO** |

Log: `.glm-logs/w0816r_w83_parallel/reeval_freshness_residual.log`

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

Log: `.glm-logs/w0816r_w83_parallel/standard_eval_wiring.json`

### Pytest counts (green)

| suite | n |
|-------|--:|
| `tests/test_class_signals.py` | **17** (+W83 wave/default params · xs sticky) |
| `tests/test_paper_candidate_adapter.py` | 12 |
| `tests/test_standard_research_eval.py` | 17 |
| `tests/test_hypothesis_classes.py` | 12 |
| **total** | **58** |

Log: `.glm-logs/w0816r_w83_parallel/pytest_w83_residual.log`

---

## Delivered code

| artifact | path | role |
|----------|------|------|
| Class signals **v6** | `packages/research_runtime/features/class_signals.py` | wave **W83 / w0816r** |
| Offline multi-year eval **v6** | `packages/product/research/class_hyp_eval.py` | default-path **xs hold=10** + **fund hold=10** blocks |
| Tests | `tests/test_class_signals.py` | +W83 wave/default params · **17** |
| Explore runner | `.glm-logs/w0816r_w83_parallel/run_w83_parallel_search.py` | parallel multi-family matrix |

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
- **limited paper PnL as edge / significance** — **not claimed** (negatives shown)  
- **multi_day_hold 10d production candidate** — **still demoted**  
- **event_post production candidate** — **still demoted** (PIT)  
- **mean-bp-only promotion** — **forbidden**  
- **xs mom=10 as default** — **rejected** (explore collapse)  

---

## Residual TOP (W83)

1. **2 default research candidates wired** — `cross_section_hold_10` (mom=**5**) · `fundamentals_hold_10` (mom=**10**)  
2. **Parallel explore matrix** — multi_day / event_post PIT / macro / flow / xs hold=5 / fund hold=20 **rejected** or conditional; xs mom=10 **rejected**  
3. **Paper limited honest negatives** — xs **−1.96%** · fund **−4.06%** · continuous **UNARMED** · StrategySpec v2 gap irreducible  
4. **OTC tip-wait** — **4499→4499 (Δ0)** · dataset **PARTIAL** · no bulk re-scan  
5. **GO 未宣言** — Mass **NO-GO** · READY **未宣言** · operational GO **未宣言** · Phase7 **OFF**  
6. **COMPLETE 22 held** · empty **0** · no invent 23 · segs **7888** · costs v2 · stats bar · PIT integrity held  
7. **FRESH residual** — `projgen-94a53a62ee314253972bde91f2e4cb4f` · coverage_segments untouched  
8. **xs content caveat** — mom lookback **must remain 5** for hold=10; mom=10 not a better content match  
9. **W82 underneath** — event_post PIT demote · multi_day demote · costs v2 · research entry linked  

See also: [`w0816r_w83_go_gates_20260817.md`](w0816r_w83_go_gates_20260817.md)

---

## Prior tip / push

| item | value |
|------|-------|
| W82 tip (start) | `4696f36` — docs pin after event+paper+OTC close |
| W82 feature tip | `e7d73fb` — event_post PIT demote + paper gap + OTC 4485→4499 |
| W83 feature tip | `12e3e46` — parallel default candidates + paper negatives + OTC tip-wait + FRESH close |
| This wave | commit + push on `main` past `4696f36` |

---

## Related proofs

| doc | role |
|-----|------|
| Parallel explore + rewire | [`w0816r_w83_parallel_strategy_search_20260817.md`](w0816r_w83_parallel_strategy_search_20260817.md) |
| GO gates | [`w0816r_w83_go_gates_20260817.md`](w0816r_w83_go_gates_20260817.md) |
| Residual SoT | [`docs/phase62_residual_status.md`](../phase62_residual_status.md) |
| W82 close | [`w0816q_w82_event_paper_otc_close_20260817.md`](w0816q_w82_event_paper_otc_close_20260817.md) |

---

## Logs index

```text
.glm-logs/w0816r_w83_parallel/
  run_w83_parallel_search.py
  explore_table.json · explore_*.json
  class_hyp_multi_year_bundle.json
  candidate_summary.json · candidate_list.json · holistic_judgments.json
  detail_cross_section_hold_10.json · detail_fundamentals_hold_10.json
  paper_results.json · paper_trial_card.json · paper_*
  otc_tip_full_ok.json
  health_local.json · health_w83_residual.log · health_w83_postfresh.log
  reeval_freshness_residual.log
  pytest_w83.log · pytest_w83_residual.log
  standard_eval_wiring.json
```
