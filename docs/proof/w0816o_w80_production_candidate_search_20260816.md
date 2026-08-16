# W80 / w0816o — Task A+B: production candidate re-eval (occurrence rates)

**Phase:** 生産研究候補の再評価（発生率 + 流動性コスト + 経済ネット + checklist v2）  
**Wave:** W80 / `w0816o` · 2026-08-16  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Task:** **A+B** multi_day_hold 10d + event_post production re-eval · optional other classes  
**Logs:** [`.glm-logs/w0816o_w80_candidate/`](../../.glm-logs/w0816o_w80_candidate/)  
**Prior:** W79 discussion_only (multi_day 10d · event_post) · research_candidate always False

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** (`ready_declared=False`) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| operational GO | **未宣言** |
| edge / significance | **none** |
| densify / invent COMPLETE 23 | **none** |
| S1–S5 un-reject | **forbidden** |
| simple_daily_sign | **not used** (default OFF) |
| weak consistent-negative as candidate | **forbidden** |
| Mass/READY auto-connect from gate pass | **none** |
| live orders / paper arm | **not this task** (paper adapter separate, UNARMED) |
| push / commit | **not this task** |

---

## Policy (W80)

| rule | held |
|------|------|
| Event sufficiency = **occurrence rate** (events/trading days or per code-day), multi-year coverage — **not absolute count alone** | **yes** |
| Rate OK but window short → **extend window and re-eval** (do not reject on count) | **yes** |
| Economic net bar + checklist v2 + liquidity/repo costs + risk scenarios | **yes** |
| Weak consistent-negative → **not_candidate** | **yes** |
| simple_daily_sign NO; S1–S5 NO un-reject | **yes** |
| Mass/READY/operational GO never auto-connect | **yes** |
| **research_candidate may be True** if production bar met (still not Mass/READY) | **yes** |

### Production criteria (all required)

1. Checklist v2 complete (class_hyp path: `checklist_complete=True`)
2. Robustness gate pass (cost-aware net sign majority)
3. Risk scenarios not catastrophic (`research_candidate_allowed` on risk)
4. Economic net meaningful: positive majority **and** mean net ≥ **20bp**
5. Occurrence / activation rate sufficient (rate-based thresholds below)
6. Multi-year: ≥ **4** ok periods, no extreme single-year positive-net skew (≤75% share)

When all pass → `research_candidate=True` · `candidate_yes_no=yes`  
Else if gate+econ only → `discussion_only`  
Else → `not_candidate`

### Occurrence thresholds (research defaults · disclosed)

| metric | threshold | applies |
|--------|----------:|---------|
| multi_day activation_rate (`n_active / n_code_days`) | ≥ **0.04** | multi_day_hold · flow · cs · macro |
| event events_per_trading_day **or** events_per_code_year_annualized | ≥ **0.05** / ≥ **0.5** | event_post |
| min years for research_candidate | **4** | all |
| max single-year share of positive net mass | **0.75** | all |

---

## Delivered code

| artifact | path | role |
|----------|------|------|
| Class signals v3 | `packages/research_runtime/features/class_signals.py` | occurrence rates · skew · production_candidate_bar · wave W80 |
| Offline multi-year eval v3 | `packages/product/research/class_hyp_eval.py` | full-year windows · liquidity one_way_eff · fins_earnings_date thicken · research_candidate=True when bar met |
| Features exports | `packages/research_runtime/features/__init__.py` | new helpers |
| Tests | `tests/test_class_signals.py` | +occurrence · +production bar · **14 passed** |

---

## Data path (W80 extended)

| item | value |
|------|-------|
| Bars SoT | W63 Q4 mirrors + **W64 full-year** (2015/19/21/23 · ~Jan–Oct) |
| Periods | `y2015_full` · `y2017_q4` · `y2019_full` · `y2021_full` · `y2023_full` · `y2025_q4` |
| Fins SoT | SQLite `fins_summary` **1739** + **`fins_earnings_date` 984** → merged **2569** calendar rows / 30 codes |
| Event thicken | earnings PubDate\|SchDate fills calendar; surprise still needs fins_summary EPS/FEPS (**no invent**) |
| Repo / short / margin | same as W79 (SQLite + margin ndjson) |
| Tx cost | **10bp one-way base** · **liquidity-linked** tx_mult (panel ADV → bucket; large-cap **high** → mult=1.0) |
| Economic bar | mean net ≥ **20bp** + positive majority |

### Window extension honesty

W79 Q4-only left event_post with ~27 scored events/period (absolute count sparse).  
Occurrence **rate** was already OK (~3.7 events/code-year annualized). Per policy, windows were **extended** to full-year where mirrors exist (not rejected on count). Scored events rose to **372** across 6 periods (~74–83 on full years).

---

## Results tables

### A. multi_day_hold · hold=5d · liquidity one_way_eff

| period | gross | net | n_active | liq | td |
|--------|------:|----:|---------:|-----|---:|
| y2015_full | −0.005407 | −0.005607 | 1021 | high | 197 |
| y2017_q4 | −0.000115 | −0.000315 | 376 | high | 80 |
| y2019_full | +0.003604 | +0.003404 | 993 | high | 192 |
| y2021_full | +0.002113 | +0.001913 | 995 | high | 193 |
| y2023_full | −0.000311 | −0.000511 | 997 | high | 193 |
| y2025_q4 | +0.001579 | +0.001379 | 378 | high | 80 |

| bar | result |
|-----|--------|
| gate | **FAIL** |
| economic net | fail (mean ~0.4bp) |
| occurrence | **OK** (activation_rate ≈ **0.189**) |
| **research_candidate** | **False** |
| **yes/no** | **no** · `not_candidate` |

### B. multi_day_hold · hold=**10d** · liquidity · production

| period | gross | net | n_active | liq | td |
|--------|------:|----:|---------:|-----|---:|
| y2015_full | +0.006592 | +0.006492 | 482 | high | 197 |
| y2017_q4 | +0.015161 | +0.015061 | 162 | high | 80 |
| y2019_full | +0.000929 | +0.000829 | 486 | high | 192 |
| y2021_full | −0.007904 | −0.008004 | 486 | high | 193 |
| y2023_full | −0.005104 | −0.005204 | 485 | high | 193 |
| y2025_q4 | +0.003559 | +0.003459 | 162 | high | 80 |

| bar | result |
|-----|--------|
| gate | **PASS** (net +4 / −2) |
| economic net | **PASS** (mean net ≈ **+21.1bp** ≥ 20bp) |
| occurrence | **PASS** (activation_rate ≈ **0.090** ≥ 0.04; n_active=2263 rate-based) |
| multi-year skew | **PASS** (no extreme single-year dominance) |
| risk | **OK** (not catastrophic) |
| liquidity | ADV **high** all periods · tx_mult=**1.0** (disclosed) |
| **research_candidate** | **True** |
| ready_declared / mass | **False / NO-GO** |
| **yes/no** | **yes** · production research candidate |

Note: full-year re-eval lowers mean net vs W79 Q4-only (~97bp → ~21bp) but still clears the economic bar. Liquidity cost does not change large-cap panel (high bucket).

### C. event_post · post-hold=5d · thickened calendar · production

| period | gross | net | n_scored | n_events | td | events/td |
|--------|------:|----:|---------:|---------:|---:|----------:|
| y2015_full | +0.003438 | +0.003238 | 74 | 94 | 197 | 0.38 |
| y2017_q4 | +0.012955 | +0.012755 | 25 | 30 | 80 | 0.31 |
| y2019_full | +0.008443 | +0.008243 | 83 | 168 | 192 | 0.43 |
| y2021_full | +0.004200 | +0.004000 | 83 | 167 | 193 | 0.43 |
| y2023_full | +0.004310 | +0.004110 | 80 | 164 | 193 | 0.41 |
| y2025_q4 | −0.000322 | −0.000522 | 27 | 71 | 80 | 0.34 |

| bar | result |
|-----|--------|
| gate | **PASS** (net +5 / −1; min_active relaxed to 5 for sparse events) |
| economic net | **PASS** (mean net ≈ **+53.0bp**) |
| occurrence | **PASS** (events/td ≈ **0.40**; events/code-year ann. ≈ **3.61** ≥ 0.5) |
| multi-year skew | **PASS** |
| risk | **OK** |
| thicken | fins_earnings_date merged · surprise still fins_summary only |
| **research_candidate** | **True** |
| ready_declared / mass | **False / NO-GO** |
| **yes/no** | **yes** · production research candidate |

Honesty: surprise proxy imperfect (FEPS−EPS / prior EPS); earnings-date-only rows without EPS do not invent surprise (skipped).

### D–G. optional classes (same bar)

| class | gate | econ | occ | skew | mean net | **yes/no** | note |
|-------|------|------|-----|------|---------:|------------|------|
| multi_day_hold 5d | FAIL | no | yes | yes | ~0bp | **no** | sign split |
| multi_day_hold **10d** | PASS | **yes** | **yes** | **yes** | **+21bp** | **yes** | **research_candidate** |
| event_post | PASS | **yes** | **yes** | **yes** | **+53bp** | **yes** | **research_candidate** |
| macro_conditioned | PASS | **no** (weak −) | yes | no | −24bp | **no** | barred by economic rule |
| cross_section 5d sticky | FAIL | no | yes | no | −11bp | **no** | |
| flow_demand | FAIL | no | yes | no | +118bp* | **no** | *mean high but negative majority / gate fail; not S4 |
| fundamentals_price | PASS | **yes** | **no** (rate 0.025&lt;0.04) | yes | +71bp | **no_discussion_only** | sparse value×mom agree |

\* flow_demand mean is positive but gate fails (sign majority / active pattern); not production.

---

## Candidate yes/no (production)

| class / variant | research_candidate | candidate_yes_no | mean net | occurrence | note |
|-----------------|--------------------|------------------|----------|------------|------|
| multi_day_hold 5d | False | **no** | ~0bp | act 0.189 | not_candidate |
| **multi_day_hold 10d** | **True** | **yes** | **+21.1bp** | act **0.090** | production research candidate |
| **event_post** | **True** | **yes** | **+53.0bp** | **3.61**/code-yr | production research candidate |
| macro_conditioned | False | **no** | −24bp | act 0.42 | weak consistent-negative |
| cross_section | False | **no** | −11bp | act 0.11 | |
| flow_demand | False | **no** | mixed | act 0.05 | gate fail |
| fundamentals_price | False | **no_discussion_only** | +71bp | act 0.025 | rate below floor |
| S1–S5 | n/a | n/a | n/a | n/a | **untouched** |

**Production research candidates: multi_day_hold 10d + event_post.**  
**READY / Mass / operational GO: still closed.**  
**Paper path: separate UNARMED adapter (Task D); not armed by this re-eval.**

---

## Checklist / freezes

| field | value |
|-------|------:|
| checklist_version (harness wiring_only) | `standard-research-eval-checklist/v2` |
| class_hyp path checklist_complete | **True** (production bar input) |
| ready_declared | **False** |
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| operational_go | **False** |
| prefer_liquidity_linked | **True** |
| prefer_repo_linked | **True** |
| any_research_candidate | **True** (research only) |

---

## Tests

| suite | result |
|-------|--------|
| `tests/test_class_signals.py` | **14 passed** |

Log: `.glm-logs/w0816o_w80_candidate/pytest_class_signals.log`

---

## Machine artifacts

| file | content |
|------|---------|
| `.glm-logs/w0816o_w80_candidate/class_hyp_multi_year_bundle.json` | full multi-year bundle v3 |
| `.glm-logs/w0816o_w80_candidate/results_table.json` | compact per-class nets + rates |
| `.glm-logs/w0816o_w80_candidate/candidate_summary.json` | yes/no summary |
| `.glm-logs/w0816o_w80_candidate/class_hyp_multi_year_eval.log` | stdout-style run log |
| `.glm-logs/w0816o_w80_candidate/class_signal_definitions.json` | catalog document |
| `.glm-logs/w0816o_w80_candidate/standard_eval_class_hyp.json` | wiring_only harness snapshot |
| `.glm-logs/w0816o_w80_candidate/pytest_class_signals.log` | unit tests |

---

## Related

| artifact | path |
|----------|------|
| W79 hyp candidate search | [`w0816n_w79_hyp_candidate_search_20260816.md`](w0816n_w79_hyp_candidate_search_20260816.md) |
| W79 liquidity costs | [`w0816n_w79_liquidity_linked_cost_20260816.md`](w0816n_w79_liquidity_linked_cost_20260816.md) |
| W80 paper adapter UNARMED | [`w0816o_w80_paper_adapter_unarmed_20260816.md`](w0816o_w80_paper_adapter_unarmed_20260816.md) |
| Checklist v2 | [`w0816k_w77_eval_checklist_v2_20260816.md`](w0816k_w77_eval_checklist_v2_20260816.md) |

---

## Non-declarations (restated)

- **READY** not declared  
- **Mass** NO-GO · **Phase7** OFF · **operational GO** 未宣言  
- **No** S1–S5 un-reject · **no** simple_daily_sign mass gen  
- **No** weak consistent-negative as candidate  
- **research_candidate=True** ≠ READY ≠ Mass ≠ order authority  
- Paper receptacle remains **UNARMED** (separate Task D)  
- **No push / commit** this task  
