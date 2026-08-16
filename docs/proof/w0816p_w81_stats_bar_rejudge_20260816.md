# W81 / w0816p — Task A (+ optional D): statistical bar re-judge research_candidates

**Phase:** 生産研究候補の統計バー再判定（t-stat / Sharpe / win-rate 等、コスト後）  
**Wave:** W81 / `w0816p` · 2026-08-16  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Task:** **A** multi_day_hold 10d + event_post re-judge · **optional D** same bar on other classes  
**Logs:** [`.glm-logs/w0816p_w81_stats/`](../../.glm-logs/w0816p_w81_stats/)  
**Prior:** W80 production candidates = multi_day_hold 10d + event_post (`research_candidate=True` on mean bp bar only)

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** (`ready_declared=False`) |
| **Mass** | **NO-GO** |
| **Phase7** | **OFF** |
| operational GO | **未宣言** |
| edge / significance | **none** (t-stat is a research filter, not a p-value claim) |
| densify / invent COMPLETE 23 | **none** |
| S1–S5 un-reject | **forbidden** |
| simple_daily_sign | **not used** |
| weak consistent-negative as candidate | **forbidden** |
| Mass/READY auto-connect from gate pass | **none** |
| live orders / paper arm | **not this task** |
| push / commit | **not this task** |

---

## Policy (W81) — raise bar beyond mean bp

W80 promoted candidates when **mean net ≥ 20bp** + occurrence + multi-year + gate + risk.  
That is **too weak alone**: multi_day_hold 10d cleared ~21bp with **t≈0.62** and **Sharpe≈0.25** and large negative years (2021/2023).

W81 requires **statistical quality after costs** on **period nets** (independent year-windows):

| rule | held |
|------|------|
| Require **\|t\|**, **Sharpe**, **period win-rate**, **positive year count** — not mean bp alone | **yes** |
| Noisy (low t/Sharpe, unstable yearly signs) → demote `research_candidate` → `discussion_only` (or `not_candidate`) | **yes** |
| Costs: liquidity-linked one-way (repo series disclosed for short/financing context) | **yes** |
| multi_day_hold **10d** + **event_post** first; optional same bar on other classes | **yes** |
| No simple_daily_sign / S1–S5 un-reject | **yes** |
| Mass/READY/operational GO never auto-on | **yes** |

### Explicit statistical bars (documented rationale)

Primary unit = **period net** = mean of hold-period signed returns in that year-window **minus amortized one-way cost** (liquidity-modulated).

| metric | floor | definition | rationale |
|--------|------:|------------|-----------|
| **\|t\|** (period nets vs 0) | **≥ 1.5** | `t = mean / (s/√n)`, sample std, n=ok periods | With n≈6, \|t\|&lt;1.0 is noise; 1.5 is a modest research floor (not a significance claim / not p&lt;0.05) |
| **Sharpe (period)** | **≥ 0.50** | `mean(period_net) / std(period_net)` · `periods_per_year=1` | Each period ≈ one independent year-window residual; no extra √N (that would be t). 0.5 ≈ half a unit of mean per unit risk — weak but non-noise |
| **Period win-rate** | **≥ 0.60** | share of periods with net &gt; 0 | Yearly **sign stability**; 3/6 = coin flip |
| **Positive periods** | **≥ 4** | count of net&gt;0 years | Aligns with multi-year depth; blocks 3–3 splits |
| **Economic net floor** (W80 kept) | **≥ 20bp** mean | positive majority + mean | Still required; not replaced |
| **Occurrence / skew / gate / risk / checklist** | W80 unchanged | rate-based, multi-year | Still required |

**Optional (not hard-gated this wave):** payoff ≥ 1.0; \|max DD\| of cumulative period nets; Calmar; IR vs 0 (same scale as period Sharpe).

**Trade-level Sharpe (reported, not primary gate):** on hold nets  
`(mean/std) * √(245 / hold_days)` — disclosed per period for multi_day / event_post.

**Demote rule:** if W80 core (gate+econ+occ+years+skew+checklist+risk) passes but stats bar fails →  
`verdict = discussion_only_noisy_stats` (or `discussion_only_stats_bar`) · `research_candidate=False`.

---

## Delivered code

| artifact | path | role |
|----------|------|------|
| Stats metrics helpers | `packages/product/research/stats_metrics.py` | t-stat · Sharpe · winrate · payoff · maxDD · Calmar · IR · `stats_bar_check` |
| Class signals **v4** | `packages/research_runtime/features/class_signals.py` | wave W81 · stats defaults · `production_candidate_bar` requires `stats_ok` |
| Offline multi-year eval **v4** | `packages/product/research/class_hyp_eval.py` | period stats + demote wiring · trade_stats on multi_day/event |
| Tests | `tests/test_class_signals.py` | production bar demote + stats helpers |

---

## Data / cost path (same as W80 + stats)

| item | value |
|------|-------|
| Bars SoT | W63 Q4 + W64 full (2015/19/21/23) · Q4 2017/2025 |
| Periods | `y2015_full` · `y2017_q4` · `y2019_full` · `y2021_full` · `y2023_full` · `y2025_q4` |
| Codes | 30 large-cap DEFAULT_EVAL_CODES |
| Fins | SQLite fins_summary + fins_earnings_date thicken (no invent surprise) |
| Tx cost | **10bp one-way base** · **liquidity-linked** ADV → bucket; panel **high** → tx_mult=**1.0** |
| Repo | JSDA overnight series loaded; mean disclosed for L/S financing context (no invent fill) |
| Economic bar | mean net ≥ **20bp** + positive majority |
| Stats bar | \|t\|≥**1.5** · Sharpe≥**0.50** · win-rate≥**0.60** · ≥**4** pos years |

---

## Results tables

### A. multi_day_hold · hold=**10d** · liquidity · **stats re-judge** (primary)

| period | gross | net | n_active | liq | trade t | trade Sharpe_ann | trade winrate |
|--------|------:|----:|---------:|-----|--------:|-----------------:|--------------:|
| y2015_full | +65.9bp | +64.9bp | 482 | high | 0.39 | 0.09 | — |
| y2017_q4 | +151.6bp | +150.6bp | 162 | high | 2.21 | 0.86 | — |
| y2019_full | +9.3bp | +8.3bp | 486 | high | 0.29 | 0.07 | — |
| y2021_full | −79.0bp | −80.0bp | 486 | high | −2.60 | −0.58 | — |
| y2023_full | −51.0bp | −52.0bp | 485 | high | −1.23 | −0.28 | — |
| y2025_q4 | +35.6bp | +34.6bp | 162 | high | 0.48 | 0.19 | — |

| metric | value | bar | pass? |
|--------|------:|-----|:-----:|
| mean net | **+21.1bp** | ≥20bp | **yes** |
| **t-stat** (period nets) | **0.62** | \|t\|≥1.5 | **no** |
| **Sharpe** (period) | **0.25** | ≥0.50 | **no** |
| win-rate (periods) | 0.667 (4/6) | ≥0.60 | yes |
| positive periods | 4 | ≥4 | yes |
| payoff | 0.98 | soft | — |
| max DD (cum period nets) | −1.32% | soft | — |
| Calmar | 0.16 | soft | — |
| gate / econ / occ / skew / risk | PASS | W80 | yes |
| **research_candidate (W80)** | True | — | — |
| **research_candidate (W81)** | **False** | stats | **demote** |
| **decision** | **demote** → `discussion_only_noisy_stats` | | |
| ready / mass | False / NO-GO | | |

**Honesty:** Mean net barely clears 20bp; two full years (2021, 2023) are strongly negative. Period t and Sharpe fail → **not** a production research candidate under the raised bar. Keep as **discussion_only** (gate+econ still interesting for research notes).

---

### B. event_post · post-hold=5d · thickened calendar · **stats re-judge** (primary)

| period | gross | net | n_scored | td | events/td | trade t | trade Sharpe_ann |
|--------|------:|----:|---------:|---:|----------:|--------:|-----------------:|
| y2015_full | +34.4bp | +32.4bp | 74 | 197 | 0.38 | 0.58 | 0.47 |
| y2017_q4 | +129.5bp | +127.5bp | 25 | 80 | 0.31 | 0.92 | 1.29 |
| y2019_full | +84.4bp | +82.4bp | 83 | 192 | 0.43 | 1.15 | 0.89 |
| y2021_full | +42.0bp | +40.0bp | 83 | 193 | 0.43 | 0.67 | 0.51 |
| y2023_full | +43.1bp | +41.1bp | 80 | 193 | 0.41 | 0.69 | 0.54 |
| y2025_q4 | −3.2bp | −5.2bp | 27 | 80 | 0.34 | −0.04 | −0.05 |

| metric | value | bar | pass? |
|--------|------:|-----|:-----:|
| mean net | **+53.0bp** | ≥20bp | **yes** |
| **t-stat** | **2.83** | \|t\|≥1.5 | **yes** |
| **Sharpe** (period) | **1.15** | ≥0.50 | **yes** |
| win-rate | **0.833** (5/6) | ≥0.60 | **yes** |
| positive periods | **5** | ≥4 | **yes** |
| payoff | **12.4** | soft | — |
| max DD (cum period nets) | **−5.2bp** | soft | — |
| Calmar | **10.2** | soft | — |
| occurrence | events/td≈0.40 · ~3.6/code-yr | rate OK | **yes** |
| gate / risk / skew | PASS | | yes |
| **research_candidate (W81)** | **True** | all | **keep** |
| **decision** | **keep** | | |
| ready / mass | False / NO-GO | | |

**Honesty:** Surprise proxy still imperfect (FEPS−EPS / prior EPS); earnings-date-only rows without EPS do not invent surprise. Stats are stronger than multi_day 10d; still research-only, not READY.

---

### C. multi_day_hold · hold=5d (optional same bar)

| metric | value | decision |
|--------|------:|----------|
| mean net | +0.4bp | |
| t / Sharpe / win-rate | 0.03 / 0.01 / 0.50 | |
| gate | FAIL | |
| **decision** | **not_candidate** | unchanged |

### D. optional other classes (same bar)

| class | mean net | t | Sharpe | winrate | maxDD | gate | econ | stats | **decision** |
|-------|----------:|--:|-------:|--------:|------:|------|------|-------|--------------|
| multi_day_hold 5d | +0.4bp | 0.03 | 0.01 | 0.50 | −0.59% | FAIL | no | no | **not_candidate** |
| **multi_day_hold 10d** | **+21.1bp** | **0.62** | **0.25** | 0.67 | −1.32% | PASS | yes | **no** | **demote** (discussion_only_noisy_stats) |
| **event_post** | **+53.0bp** | **2.83** | **1.15** | **0.83** | −0.05% | PASS | yes | **yes** | **keep** research_candidate |
| macro_conditioned | −24.1bp | −3.16 | −1.29 | 0.00 | −1.45% | PASS | no | no | **not_candidate** (weak −) |
| cross_section 5d | −10.9bp | −0.44 | −0.18 | 0.50 | −1.44% | FAIL | no | no | **not_candidate** |
| flow_demand | +117.9bp* | 0.76 | 0.31 | 0.33 | −2.25% | FAIL | no | no | **not_candidate** (*mean high, majority neg / gate fail) |
| fundamentals_price | +70.9bp | 1.04 | 0.42 | 0.67 | −1.09% | PASS | yes | no | **discussion_only** (occ rate + stats fail) |

---

## Candidate yes/no (W81 after stats bar)

| class / variant | W80 research_candidate | W81 research_candidate | decision | mean net | t | Sharpe | note |
|-----------------|------------------------|------------------------|----------|----------|---|--------|------|
| multi_day_hold 5d | False | False | not_candidate | ~0bp | 0.03 | 0.01 | |
| **multi_day_hold 10d** | **True** | **False** | **demote** | +21bp | **0.62** | **0.25** | noisy; discussion_only |
| **event_post** | **True** | **True** | **keep** | +53bp | **2.83** | **1.15** | sole production research candidate |
| macro_conditioned | False | False | not_candidate | −24bp | −3.16 | −1.29 | weak consistent-negative |
| cross_section | False | False | not_candidate | −11bp | −0.44 | −0.18 | |
| flow_demand | False | False | not_candidate | mixed | 0.76 | 0.31 | |
| fundamentals_price | False | False | discussion_only | +71bp | 1.04 | 0.42 | occ + stats fail |
| S1–S5 | n/a | n/a | n/a | n/a | n/a | n/a | **untouched** |

**Production research candidates after W81: event_post only.**  
**multi_day_hold 10d demoted to discussion_only (noisy stats).**  
**READY / Mass / operational GO: still closed.**

---

## Freeze reaffirmation

| item | status |
|------|--------|
| any_research_candidate | **True** (event_post only) |
| ready_declared | **False** |
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| operational_go | **False** |
| connected_to_ready / mass | **False** |
| simple_daily_sign / S1–S5 un-reject | **no** |
| commit / push | **not done** (per wave instruction) |

---

## Log index

| file | content |
|------|---------|
| `.glm-logs/w0816p_w81_stats/class_hyp_multi_year_bundle.json` | full v4 eval bundle |
| `.glm-logs/w0816p_w81_stats/candidate_summary.json` | per-class keep/demote |
| `.glm-logs/w0816p_w81_stats/results_table.json` | years + stats + production criteria |
| `.glm-logs/w0816p_w81_stats/class_hyp_multi_year_eval.log` | run log |
| `.glm-logs/w0816p_w81_stats/pytest_class_signals.log` | unit tests |
| `.glm-logs/w0816p_w81_stats/stats_metrics_document.json` | bar definitions |
| `.glm-logs/w0816p_w81_stats/class_signal_definitions.json` | class-signals/v4 document |
