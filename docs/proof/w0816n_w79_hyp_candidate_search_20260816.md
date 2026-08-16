# W79 / w0816n — Task C: remaining hyp classes + candidate bar (economic net)

**Phase:** 仮説クラス実装残 + 複数年評価 + 経済ネット候補バー（READY 未宣言）  
**Wave:** W79 / `w0816n` · 2026-08-16  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Task:** **C** implement remaining class signals · multi-year eval · candidate yes/no  
**Logs:** [`.glm-logs/w0816n_w79_go_final/`](../../.glm-logs/w0816n_w79_go_final/)  
**Prior:** W78 multi_day_hold + macro_conditioned · W77 hyp classes + checklist v2 · S1–S5 `research_baseline_rejected`

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** (`ready_declared=False`) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| edge / significance / operational GO | **none** |
| densify / invent COMPLETE 23 | **none** |
| S1–S5 un-reject | **forbidden** (catalog untouched) |
| simple_daily_sign | **not used** (default OFF held) |
| weak consistent-negative as candidate | **forbidden** |
| Mass/READY auto-connect | **none** |
| auto `research_candidate` promote | **none** (harness always False) |
| push / commit | **not this task** |

---

## Candidate bar (W79)

A class is **discussion-candidate allowed** only if **all** of:

1. Checklist v2 surface complete (via `class_hyp_offline` / gate + costs + risk)
2. Robustness gate v2 with cost-aware net sign majority
3. Risk scenarios not catastrophic (`research_candidate_allowed` on risk block)
4. **Economic net meaningful:** positive net majority **and** mean net ≥ **20bp** per scored hold (`min_economic_net=0.002`)

Else → **`not_candidate`**. Weak consistent-negative (e.g. W78 macro) is explicitly **not_candidate** even if gate passes.

`research_candidate` stays **False** always (no auto-promote). Pass ≠ READY / Mass.

---

## Task C — Implementations

### Delivered code

| artifact | path | role |
|----------|------|------|
| Class signals v2 | `packages/research_runtime/features/class_signals.py` | +event_post · +flow_demand · +fundamentals_price · economic_net_meaningful · catalog |
| Offline multi-year eval v2 | `packages/product/research/class_hyp_eval.py` | fins/margin/short loaders · 3 new evals · CS multi-day improve · hold=10 variant · economic bar |
| Eval harness | `packages/product/research/eval_harness.py` | `class_hyp_offline` notes W79 surface |
| Features exports | `packages/research_runtime/features/__init__.py` | new signal ids + compute fns |
| Unit tests | `tests/test_class_signals.py` | 12 tests |

### Signal catalog (W79)

| signal_id | hypothesis_class | horizon | formula (research) | datasets |
|-----------|------------------|---------|--------------------|----------|
| `c21_multi_day_momentum_hold` | `multi_day_hold` | 5d / **10d improve** | sticky `sign(momentum_n)` hold | bars · calendar · topix |
| `c21_event_post_disclosure_hold` | `event_post` | 5d post-event | on fins `DiscDate`: `sign(surprise)`; hold 5d | **fins_summary** · bars · calendar |
| `c21_repo_conditioned_momentum` | `macro_conditioned` | regime | momentum × repo regime | bars + **jsda_tokyo_repo_rates** |
| `c21_cross_section_momentum_rank` | `cross_section_relative` | **5d sticky improve** | rank L-S + sticky multi-day | bars · calendar · topix |
| `c21_margin_flow_multiday` | `flow_demand` | 5d | `sign(margin_change)` sticky (**not S4 daily**) | **margin** · short · bars |
| `c21_fundamentals_price_value` | `fundamentals_price` | 20d | PIT value (BPS/P\|EPS/P) × momentum agree | **fins_summary** · bars |

### Formulas (not 1d simple daily sign)

**event_post**

```text
event      = fins_summary DiscDate (code-matched)
surprise   = FEPS - EPS  if both numeric
           else EPS - prior_EPS if prior present
           else skip (no invent)
entry      = sign(surprise) on event day only
R_hold     = close[t+5]/close[t] - 1
gross/net  = mean(entry * R_hold) − one_way/5
```

**flow_demand** (not S4 rehash)

```text
margin_chg = Δ(LongVol+ShrtVol) on margin observation dates
entry      = sign(margin_chg); sticky min_hold=5d (not 1d flip)
score      on margin rebalance days with multi-day forward return
optional   short_ratio S33=0050 confirm (off by default in multi-year)
```

**fundamentals_price**

```text
value_score = BPS/close if BPS else EPS/close (PIT last DiscDate ≤ bar date)
benchmark   = cross-panel median value_score
entry       = value_sign only when momentum_20 same sign (agree mode)
hold        sticky fixed_horizon 20d; amortized cost
```

### Explicit non-goals

- Not `simple_daily_sign` / not S1–S5 rehash or un-reject  
- Not Mass / READY / Phase7  
- Not order intents  
- Not invent COMPLETE 23 / densify  
- Weak consistent-negative is **not** a candidate  

---

## Data path (honest multi-year)

| item | value |
|------|-------|
| Bars SoT | W63 local mirrors `.glm-logs/w0815bd_w63_multiyear/r2_mirror/equities_bars_daily_y*_q4.ndjson` |
| Margin SoT | same dir `markets_margin_interest_y*_q4.ndjson` (fallback SQLite) |
| Fins SoT | local SQLite `jquants_records` dataset `fins_summary` · **30 codes · 1739 events** |
| Short SoT | SQLite `markets_short_ratio` S33=**0050** · **3063** dates |
| Repo SoT | SQLite `jsda_repo_rates` · **6740** overnight rows |
| Windows | Q4 · 2015/17/19/21/23/25 · max 80d · 30 codes |
| Tx cost | **10bp one-way** (amortized for multi-day holds) |
| Economic bar | mean net ≥ **20bp** + positive majority |

### PIT / gap disclosure

- Repo: bulk `available_at` ~2026 → research keys by **as_of_date** (disclosed; no invent fill).  
- Fins: research keys by **DiscDate** / event_time (disclosed).  
- Margin mirrors used for Q4 years; short is market-level (not name-level).  
- Sparse event counts (~27 scored events/period) disclosed — not densified.

---

## Results tables

### A. multi_day_hold · hold=5d · amortized 10bp/5

| period | gross | net | n_active |
|--------|------:|----:|---------:|
| y2015_q4 | +0.017019 | +0.016819 | 374 |
| y2017_q4 | −0.000115 | −0.000315 | 376 |
| y2019_q4 | +0.003257 | +0.003057 | 377 |
| y2021_q4 | −0.003415 | −0.003615 | 376 |
| y2023_q4 | −0.001246 | −0.001446 | 378 |
| y2025_q4 | +0.006025 | +0.005825 | 377 |

| bar | result |
|-----|--------|
| gate (gross/net majority) | **FAIL** (+3/−3) |
| economic net | fail (tied) |
| **candidate** | **no** · `not_candidate` |

### B. multi_day_hold improve · hold=**10d** · amortized 10bp/10

| period | gross | net | n_active |
|--------|------:|----:|---------:|
| y2015_q4 | +0.048880 | +0.048780 | 160 |
| y2017_q4 | +0.015161 | +0.015061 | 162 |
| y2019_q4 | −0.000795 | −0.000895 | 162 |
| y2021_q4 | −0.009085 | −0.009185 | 162 |
| y2023_q4 | +0.004315 | +0.004215 | 162 |
| y2025_q4 | +0.000321 | +0.000221 | 162 |

| bar | result |
|-----|--------|
| gate | **PASS** (net +4/−2) |
| economic net | **PASS** (mean net ≈ **+97bp**) |
| risk | OK (not catastrophic) |
| **research_candidate** | **False** (no auto-promote) |
| **research_candidate_allowed** | **True** (discussion only) |
| **candidate yes/no** | **yes_discussion_only** (not READY/Mass) |

### C. event_post · post-hold=5d

| period | gross | net | n_active (events scored) |
|--------|------:|----:|-------------------------:|
| y2015_q4 | +0.020401 | +0.020201 | 27 |
| y2017_q4 | +0.009085 | +0.008885 | 27 |
| y2019_q4 | +0.008626 | +0.008426 | 27 |
| y2021_q4 | −0.003430 | −0.003630 | 27 |
| y2023_q4 | +0.042999 | +0.042799 | 27 |
| y2025_q4 | −0.000322 | −0.000522 | 27 |

| bar | result |
|-----|--------|
| gate | **PASS** (net +4/−2; min_active relaxed to 5 for sparse events) |
| economic net | **PASS** (mean net ≈ **+127bp**) |
| risk | OK |
| **research_candidate** | **False** |
| **research_candidate_allowed** | **True** (discussion only) |
| **candidate yes/no** | **yes_discussion_only** |
| honesty | **small event sample (~27/period)** · surprise proxy imperfect · not production edge |

### D. macro_conditioned · rate_change · 10bp one-way

| period | gross | net | n_active |
|--------|------:|----:|---------:|
| y2015_q4 | −0.011949 | −0.012949 | 856 |
| y2017_q4 | +0.000287 | −0.000713 | 698 |
| y2019_q4 | −0.001601 | −0.002601 | 1021 |
| y2021_q4 | −0.001044 | −0.002044 | 971 |
| y2023_q4 | +0.000458 | −0.000542 | 927 |
| y2025_q4 | −0.004233 | −0.005233 | 816 |

| bar | result |
|-----|--------|
| gate | PASS (net majority −) |
| economic net | **FAIL** — **weak consistent-negative** (mean net ≈ −40bp) |
| **candidate** | **no** · `not_candidate_economic_net_not_meaningful` |

### E. cross_section_relative improve · sticky hold=5d

| period | gross | net | n_active |
|--------|------:|----:|---------:|
| y2015_q4 | −0.034056 | −0.034256 | 224 |
| y2017_q4 | −0.003662 | −0.003862 | 224 |
| y2019_q4 | −0.000369 | −0.000569 | 224 |
| y2021_q4 | −0.004524 | −0.004724 | 224 |
| y2023_q4 | −0.001746 | −0.001946 | 224 |
| y2025_q4 | +0.013427 | +0.013227 | 224 |

| bar | result |
|-----|--------|
| gate | PASS (net majority −) |
| economic | **FAIL** (weak − majority) |
| **candidate** | **no** |

### F. flow_demand · margin multi-day hold=5d

| period | gross | net | n_active |
|--------|------:|----:|---------:|
| y2015_q4 | +0.023004 | +0.022804 | 378 |
| y2017_q4 | −0.005248 | −0.005448 | 432 |
| y2019_q4 | −0.004781 | −0.004981 | 402 |
| y2021_q4 | −0.005987 | −0.006187 | 404 |
| y2023_q4 | +0.002481 | +0.002281 | 432 |
| y2025_q4 | +0.000151 | −0.000049 | 405 |

| bar | result |
|-----|--------|
| gate | **FAIL** (net +2/−4) |
| economic | fail (negative majority) |
| **candidate** | **no** |
| note | **Not S4** daily rehash — multi-day sticky on margin prints |

### G. fundamentals_price · hold=20d · value×momentum agree

| period | gross | net | n_active |
|--------|------:|----:|---------:|
| y2015_q4 | +0.004237 | +0.004187 | 28 |
| y2017_q4 | +0.016056 | +0.016006 | 19 |
| y2019_q4 | +0.015396 | +0.015346 | 29 |
| y2021_q4 | −0.026379 | −0.026429 | 37 |
| y2023_q4 | −0.012959 | −0.013009 | 37 |
| y2025_q4 | +0.012424 | +0.012374 | 29 |

| bar | result |
|-----|--------|
| gate | PASS (net +4/−2) |
| economic | **FAIL** — mean net ≈ **+14bp** **below** 20bp threshold |
| **candidate** | **no** · `not_candidate_economic_net_not_meaningful` |
| note | sparse active (value×momentum agree filter) · not catastrophic risk |

---

## Candidate yes/no per class (honest)

| class / variant | gate | economic net | risk OK | research_candidate_allowed | **yes/no** | note |
|-----------------|------|--------------|---------|----------------------------|------------|------|
| multi_day_hold (5d) | FAIL | no | — | False | **no** | sign split |
| multi_day_hold (10d improve) | PASS | **yes** | yes | True | **yes_discussion_only** | not auto-promote · not READY |
| event_post | PASS | **yes** | yes | True | **yes_discussion_only** | sparse events · discussion only |
| macro_conditioned | PASS | **no** (weak −) | yes | False | **no** | barred by economic rule |
| cross_section_relative (5d sticky) | PASS | **no** (weak −) | yes | False | **no** | |
| flow_demand | FAIL | no | — | False | **no** | |
| fundamentals_price | PASS | **no** (sub-threshold) | yes | False | **no** | +14bp < 20bp |
| S1–S5 | rejected baseline | n/a | n/a | n/a | **n/a** | **untouched** |

**Production / operational candidate: all no.**  
**READY / Mass: closed.**  
Two classes clear the research discussion bar (hold=10 multi_day · event_post); neither is auto-promoted.

---

## Checklist v2 (`run_standard_research_eval` · `class_hyp_offline`)

| field | value |
|-------|------:|
| checklist_version | `standard-research-eval-checklist/v2` |
| checklist_complete | **True** |
| research_candidate | **False** |
| research_candidate_allowed | True (completeness path; primary 5d multi_day_hold gate fail) |
| ready_declared | **False** |
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| gate_passed (primary multi_day_hold 5d) | **False** |

---

## Tests

| suite | result |
|-------|--------|
| `tests/test_class_signals.py` | **12 passed** |
| `tests/test_hypothesis_classes.py` + `tests/test_standard_research_eval.py` | **green** (combined regression **41 passed**) |

Logs: `.glm-logs/w0816n_w79_go_final/pytest_class_signals.log` · `pytest_regression.log`

---

## Machine artifacts

| file | content |
|------|---------|
| `.glm-logs/w0816n_w79_go_final/class_hyp_multi_year_bundle.json` | full multi-year bundle (all classes) |
| `.glm-logs/w0816n_w79_go_final/standard_eval_class_hyp.json` | checklist v2 run |
| `.glm-logs/w0816n_w79_go_final/results_table.json` | compact per-class results |
| `.glm-logs/w0816n_w79_go_final/class_signal_definitions.json` | declarative catalog |
| `.glm-logs/w0816n_w79_go_final/class_hyp_multi_year_eval.log` | stdout run log |

---

## Related

| artifact | path |
|----------|------|
| W78 class hyp impl+eval | [`w0816m_w78_hyp_impl_eval_20260816.md`](w0816m_w78_hyp_impl_eval_20260816.md) |
| W77 hyp space redesign | [`w0816k_w77_hypothesis_space_redesign_20260816.md`](w0816k_w77_hypothesis_space_redesign_20260816.md) |
| Checklist v2 | [`w0816k_w77_eval_checklist_v2_20260816.md`](w0816k_w77_eval_checklist_v2_20260816.md) |
| S1–S5 rejection | `packages/product/research/baseline_catalog.py` |

---

## Non-declarations (restated)

- **READY** not declared  
- **Mass** NO-GO · **Phase7** OFF  
- **No** S1–S5 un-reject  
- **No** simple_daily_sign mass generation  
- **No** weak consistent-negative as candidate  
- **No** edge / significance / operational GO  
- Discussion-only allow (hold10 / event_post) ≠ research_candidate ≠ READY/Mass  
- **No push / commit** this task  
