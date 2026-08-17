# W85 / w0816t — multi-window paper for KEEP2 + Explore4 (StrategySpec v3)

**Wave:** W85 / `w0816t` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Tasks:** **A** multi-window paper KEEP2 · **B** Explore4 v3 paper + verdicts  
**Logs:** [`.glm-logs/w0816t_w85_paper/`](../../.glm-logs/w0816t_w85_paper/)  
**Prior:** W84 realign KEEP both · StrategySpec **v3** sticky + CS rank + value×mom · 4 explore hard passers

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| READY | **未宣言** |
| Mass | **NO-GO** |
| Phase7 | **OFF** |
| operational GO | **closed** |
| continuous / unlimited paper arm | **OFF / UNARMED** |
| live orders | **OFF** |
| mean-bp-only promotion | **forbidden** |
| simplify research to match paper | **forbidden** |
| hide paper negatives | **forbidden** |
| commit / push | **not this task** |

**Policy (W85):**

| rule | held |
|------|------|
| Multi-window paper (not only 30d): several 30–90d windows | **yes** · 10 windows |
| Paper negative: record with regime note; no auto-reject KEEP solely for one weak window | **yes** |
| Explore→default only if research+paper align with written reasons | **yes** · 1 promote |
| Weak paper stays explore | **yes** · 3 stay_explore |
| Liquidity-linked tx + repo series disclosed | **yes** · bucket=high · repo n=2688 (tenor-filtered) |
| StrategySpec v3 sticky hold + CS rank + value×mom | **yes** |

---

## Scope

### KEEP2 (default path entering W85)

| # | class / block | params | research (W84 multi-year) |
|---|---------------|--------|---------------------------|
| 1 | **cross_section_hold_10** | sticky hold=**10** · **mom=5** · frac=0.3 | +84.6bp · t=1.60 · Sharpe=0.65 · win=0.67 · hard RC |
| 2 | **fundamentals_hold_10** | hold=**10** · **mom=10** value×mom | +45.9bp · t=1.82 · Sharpe=0.74 · win=0.67 · hard RC |

### Explore4 (W84 NEW hard passers — paper then judge)

| # | class / variant | research (W84) |
|---|-----------------|----------------|
| 3 | xs hold=10 **mom=3** | +120.1bp · t=**3.04** · Sharpe=**1.24** · win=**1.00** |
| 4 | xs hold=10 mom=5 **frac=0.4** | +62.9bp · t=1.69 · Sharpe=0.69 · win=0.67 |
| 5 | fund hold=**15** mom=10 | +91.5bp · t=1.80 · Sharpe=0.73 · win=0.83 |
| 6 | fund hold=**5** mom=10 | +24.4bp · t=1.92 · Sharpe=0.78 · win=0.83 (econ borderline) |

---

## Seed + costs

### Multi-window paper DB

| field | value |
|-------|------:|
| path | `.glm-logs/w0816t_w85_paper/paper_db/w85_multi_window_paper.sqlite` |
| bar rows | **25 326** |
| calendar days | **938** |
| range | **2015-01-05 … 2025-12-30** |
| universe | 30 DEFAULT_EVAL_CODES |
| fins_summary | 2686 (template from W83 paper DB) |
| repo rows seeded | 24 192 (prod extract; series n_obs after tenor filter **2688**) |
| sources | W64 full NDJSON 2015/2019/2021/2023 · W63 Q4 2017/2025 |

**Coverage note:** W64 “full” NDJSON for 2015/2019/2021/2023 ends **mid-October** (not calendar year-end). True Q4 mirrors used only for 2017 + 2025. Truncated partial-Oct stubs were **not** used as 60d windows.

### Liquidity + repo cost surface

| field | value |
|-------|------:|
| base one-way | **10.0 bp** |
| liquidity ADV proxy | high (universe large-cap; ADV ≫ ¥1bn/day) |
| tx_mult | **1.0** |
| effective paper cost_bps | **10.0** |
| prefer_liquidity_linked | True |
| repo | disclosed date-matched; **no invent ffill** |
| paper engine residual | fixed one-way CostModel (no daily repo financing / short borrow charge in core paper runner) |

Log: `.glm-logs/w0816t_w85_paper/cost_surface.json`

---

## Multi-window calendar (10 windows)

| id | span | ~days | regime note |
|----|------|------:|-------------|
| w2015_spring | 2015-02-02 … 2015-04-30 | 62 | Abenomics mid-cycle; pre-summer calm |
| w2015_summer | 2015-06-01 … 2015-08-31 | 65 | China-scare lead-in (Aug stress) |
| w2017_q4 | 2017-10-02 … 2017-12-29 | 62 | Late-cycle bull; low-vol grind |
| w2019_spring | 2019-02-01 … 2019-04-26 | 59 | Post Dec-2018 rebound |
| w2019_summer | 2019-06-03 … 2019-08-30 | 63 | Trade-war vol; summer churn |
| w2021_spring | 2021-02-01 … 2021-04-30 | 62 | Reopening / value rotation pockets |
| w2021_summer | 2021-06-01 … 2021-08-31 | 63 | Delta / peak-growth fade |
| w2023_spring | 2023-03-01 … 2023-05-31 | 62 | JP large-cap rally (BOJ/governance) |
| w2023_h2_limited | 2023-08-31 … 2023-10-13 | 30 | W84 continuity window |
| w2025_q4 | 2025-10-01 … 2025-12-30 | 62 | Tip-era Q4 (OOS vs research full years) |

All runs: StrategySpec **v3** · `fixed_horizon` sticky · `next_close` · 10bp · continuous **UNARMED** · live **OFF**.

### W84 continuity check (same window / aligned path)

| candidate | W84 limited post-cost | W85 w2023_h2_limited | match |
|-----------|----------------------:|---------------------:|:-----:|
| xs hold10 mom5 | **+1.54%** | **+1.5416%** | **yes** |
| fund hold10 mom10 | **+4.72%** | **+4.7197%** | **yes** |

---

## Full multi-window paper tables

### 1. KEEP2 — `xs_hold10_mom5` (cross_section sticky hold=10 mom=5)

Research: **+84.6bp · t=1.60 · Sharpe=0.65 · win=0.67 · hard RC**

| window | post-cost % | maxDD % | trades | days | regime |
|--------|------------:|--------:|-------:|-----:|--------|
| w2015_spring | **+1.01** | −4.07 | 150 | 62 | mid-cycle calm |
| w2015_summer | **−3.45** | −6.03 | 152 | 65 | China-scare lead-in |
| w2017_q4 | **+7.65** | −1.73 | 149 | 62 | late bull |
| w2019_spring | **+7.64** | −2.43 | 123 | 59 | rebound |
| w2019_summer | **−6.50** | −6.85 | 149 | 63 | trade-war vol |
| w2021_spring | **−1.58** | −3.66 | 153 | 62 | reopening |
| w2021_summer | **+1.82** | −1.96 | 150 | 63 | mixed |
| w2023_spring | **−11.74** | −14.42 | 147 | 62 | strong beta rally (L-S hurt) |
| w2023_h2_limited | **+1.54** | −1.23 | 60 | 30 | W84 continuity |
| w2025_q4 | **−1.32** | −6.16 | 152 | 62 | tip Q4 |

| aggregate | value |
|-----------|------:|
| n_ok / pos / neg | **10 / 5 / 5** |
| mean post-cost | **−0.49%** |
| best / worst | +7.65% / −11.74% |
| window win-rate | **0.50** |
| **verdict** | **keep_default** |

**Paper-negative validity (KEEP — not auto-reject):**  
2023 spring (−11.7%) is a **regime** L-S failure under strong single-direction beta (JP governance rally) — not a pipeline bug (W84 continuity window still matches). 2019 summer / 2015 summer negatives are stress-vol regimes. Multi-window mean mildly negative but **not catastrophic** (policy: no auto-reject KEEP for weak windows). Research hard RC held. Continuous **UNARMED**.

---

### 2. KEEP2 — `fund_hold10_mom10` (fund sticky hold=10 mom=10 value×mom)

Research: **+45.9bp · t=1.82 · Sharpe=0.74 · win=0.67 · hard RC**

| window | post-cost % | maxDD % | trades | days | regime |
|--------|------------:|--------:|-------:|-----:|--------|
| w2015_spring | **−1.24** | −8.06 | 122 | 62 | mid-cycle |
| w2015_summer | **−9.55** | −10.42 | 122 | 65 | China-scare |
| w2017_q4 | **−6.23** | −9.96 | 129 | 62 | late bull |
| w2019_spring | **−0.87** | −5.49 | 101 | 59 | rebound |
| w2019_summer | **−6.27** | −7.68 | 125 | 63 | trade-war vol |
| w2021_spring | **+4.01** | −3.91 | 134 | 62 | reopening |
| w2021_summer | **−3.07** | −4.77 | 121 | 63 | mixed |
| w2023_spring | **−0.47** | −7.41 | 131 | 62 | beta rally |
| w2023_h2_limited | **+4.72** | −4.71 | 55 | 30 | W84 continuity |
| w2025_q4 | **+1.28** | −3.76 | 136 | 62 | tip Q4 |

| aggregate | value |
|-----------|------:|
| n_ok / pos / neg | **10 / 3 / 7** |
| mean post-cost | **−1.77%** |
| best / worst | +4.72% / −9.55% |
| window win-rate | **0.30** |
| **verdict** | **keep_default** |

**Paper-negative validity:** Multi-window paper is **honestly weak** (7/10 negative; mean −1.77%). Negatives cluster in risk-off / stress summers and 2017 late-bull (value×mom disagree regimes). **Not** auto-reject: research multi-year hard RC remains (t=1.82 · Sharpe=0.74); residual portfolio-MTM vs trade-level research mean applies; W84 continuity still **+4.72%**. Keep with **paper-negative regime notes** — continuous paper stays **UNARMED**; not live; not Mass/READY. Future waves may re-judge if multi-window paper remains persistently weak after more windows.

---

### 3. Explore4 — `xs_hold10_mom3` → **promote_default**

Research: **+120.1bp · t=3.04 · Sharpe=1.24 · win=1.00 · hard RC** (W84 standout)

| window | post-cost % | maxDD % | trades | days |
|--------|------------:|--------:|-------:|-----:|
| w2015_spring | −1.94 | −5.64 | 154 | 62 |
| w2015_summer | −0.16 | −2.19 | 154 | 65 |
| w2017_q4 | **+2.97** | −2.13 | 148 | 62 |
| w2019_spring | **+6.24** | −3.99 | 122 | 59 |
| w2019_summer | −6.64 | −8.21 | 147 | 63 |
| w2021_spring | **+2.74** | −3.15 | 150 | 62 |
| w2021_summer | **+3.26** | −1.82 | 147 | 63 |
| w2023_spring | −9.42 | −11.24 | 148 | 62 |
| w2023_h2_limited | **+2.01** | −1.44 | 59 | 30 |
| w2025_q4 | **+7.59** | −4.64 | 152 | 62 |

| aggregate | value |
|-----------|------:|
| n_ok / pos / neg | **10 / 6 / 4** |
| mean post-cost | **+0.66%** |
| best / worst | +7.59% / −9.42% |
| window win-rate | **0.60** |
| **verdict** | **promote_default** |

**Reasons (research + paper align):**

1. Research hard RC is the matrix standout (t=3.04 · Sharpe=1.24 · 6/6 periods).  
2. Multi-window paper mean **non-negative** (+0.66%) with **majority** positive windows (6/10 · win=0.60).  
3. Content is real (shorter mom lookback on sticky 10d — same family as W82 “mom must stay short” pin).  
4. W84 proxy paper was −18.9% under v2 daily top_k; aligned v3 sticky CS L-S flips the story (not proxy artifact).  
5. **Does not replace** mom=5 KEEP pin — wired as **parallel** default-path block.

**Wire:** `include_cross_section_hold_10_mom3=True` (default) · block key `cross_section_hold_10_mom3` · mom_n=3. Mass/READY/GO/live remain **OFF**.

---

### 4. Explore4 — `xs_hold10_mom5_frac40` → **stay_explore**

Research: **+62.9bp · t=1.69 · Sharpe=0.69 · win=0.67 · hard RC**

| aggregate | value |
|-----------|------:|
| n_ok / pos / neg | **10 / 4 / 6** |
| mean post-cost | **−1.56%** |
| best / worst | +5.36% / −11.06% |
| window win-rate | **0.40** |
| **verdict** | **stay_explore** |

**Reasons:** Research hard RC held, but multi-window paper is **weak** (mean −1.56% · win 0.40 · majority negative). Broader book (frac=0.4) does not improve paper path vs pin frac=0.3. Policy: weak paper stays explore. No default wire.

---

### 5. Explore4 — `fund_hold15_mom10` → **stay_explore**

Research: **+91.5bp · t=1.80 · Sharpe=0.73 · win=0.83 · hard RC**

| aggregate | value |
|-----------|------:|
| n_ok / pos / neg | **10 / 5 / 5** |
| mean post-cost | **−1.13%** |
| best / worst | +5.44% / −10.96% |
| window win-rate | **0.50** |
| **verdict** | **stay_explore** |

**Reasons:** Research strong mean, but multi-window paper mixed/negative mean (−1.13% · win 0.50) — **not** clear research↔paper alignment for default. Sticky hold=15 lower turnover does not rescue paper under residual portfolio MTM. Stay explore.

---

### 6. Explore4 — `fund_hold5_mom10` → **stay_explore**

Research: **+24.4bp · t=1.92 · Sharpe=0.78 · win=0.83 · hard RC** (econ borderline)

| aggregate | value |
|-----------|------:|
| n_ok / pos / neg | **10 / 6 / 4** |
| mean post-cost | **−1.40%** |
| best / worst | +7.93% / −12.86% |
| window win-rate | **0.60** |
| **verdict** | **stay_explore** |

**Reasons:** Window win-rate 0.60 but **mean post-cost negative** (−1.40%) with large summer drawdowns (higher turnover hold=5 cost sensitivity). Research econ only +24.4bp (barely above 20bp floor) — fragile. Not promote despite 6 positive windows. Weak/mixed paper + borderline econ → stay explore. Default fund path remains hold=10.

---

## Verdicts summary

| # | strategy | lane | research t / Sharpe / mean | paper mean / win / pos-neg | **verdict** | default-wired |
|---|----------|------|---------------------------:|---------------------------:|:-----------:|:-------------:|
| 1 | xs hold10 mom5 | KEEP2 | 1.60 / 0.65 / +84.6bp | −0.49% / 0.50 / 5-5 | **keep_default** | **yes** |
| 2 | fund hold10 mom10 | KEEP2 | 1.82 / 0.74 / +45.9bp | −1.77% / 0.30 / 3-7 | **keep_default** | **yes** |
| 3 | xs hold10 mom3 | Explore4 | **3.04 / 1.24 / +120bp** | **+0.66% / 0.60 / 6-4** | **promote_default** | **yes (W85)** |
| 4 | xs hold10 mom5 frac40 | Explore4 | 1.69 / 0.69 / +62.9bp | −1.56% / 0.40 / 4-6 | **stay_explore** | no |
| 5 | fund hold15 mom10 | Explore4 | 1.80 / 0.73 / +91.5bp | −1.13% / 0.50 / 5-5 | **stay_explore** | no |
| 6 | fund hold5 mom10 | Explore4 | 1.92 / 0.78 / +24.4bp | −1.40% / 0.60 / 6-4 | **stay_explore** | no |

**Reject:** none.

---

## Default-path after W85

**Production research candidates on default path: 3**

1. `cross_section_hold_10` · mom=**5** (W82 pin · KEEP2)  
2. `cross_section_hold_10_mom3` · mom=**3** (**W85 promote_default**)  
3. `fundamentals_hold_10` · mom=**10** (KEEP2)

| flag | status |
|------|--------|
| Mass / READY / operational GO | **still closed** |
| continuous paper | **UNARMED** |
| live | **OFF** |
| research_candidate → Mass/READY | **never auto-connects** |

### Code wire (promote_default only)

| artifact | change |
|----------|--------|
| `packages/product/research/class_hyp_eval.py` | `include_cross_section_hold_10_mom3=True` (default) · `cross_section_hold10_mom3_momentum_n=3` · emit block `cross_section_hold_10_mom3` · candidate_summary key · parallel to mom=5 pin (no replace) |
| `packages/product/research/paper_candidate_adapter.py` | wave → W85 · variant `hold_10_mom3` / `cross_section_hold_10_mom3` → mom=3 |
| `tests/test_class_signals.py` | asserts new default-path params |

---

## StrategySpec v3 (unchanged capability; used for all 6)

| capability | detail |
|------------|--------|
| version | `strategy-spec/v3` |
| rebalance | `fixed_horizon` + `hold_days` sticky empty mid-hold |
| xs rule | `cross_section_rank` long_frac/short_frac |
| fund rule | `value_momentum_agree` + `fundamental_value_score` + mom_n |
| costs | 10bp one-way · rebalance-only turnover under sticky |

**Residuals (documented, not simplified away):** portfolio MTM vs trade-level research mean · no margin/borrow on short · fund value CS median vs research global median · paper CostModel fixed bp (repo disclosed only).

---

## Pytest

| suite | result |
|-------|--------|
| `tests/test_class_signals.py` | green (incl. W85 mom3 default params) |
| `tests/test_paper_candidate_adapter.py` | green |
| `tests/test_strategy_spec_schema.py` | green |
| **total** | **44 passed** |

Log: `.glm-logs/w0816t_w85_paper/pytest_key.log`

---

## Log index

| path | content |
|------|---------|
| `.glm-logs/w0816t_w85_paper/run_w85_multi_window_paper.py` | seed + cost + specs + multi-window runner + judge |
| `.glm-logs/w0816t_w85_paper/run_all.log` | full stdout |
| `.glm-logs/w0816t_w85_paper/seed_meta.json` | DB seed |
| `.glm-logs/w0816t_w85_paper/cost_surface.json` | liquidity + repo |
| `.glm-logs/w0816t_w85_paper/paper_specs/` | StrategySpec v3 + envelopes × 6 |
| `.glm-logs/w0816t_w85_paper/paper_results.json` | all 60 runs |
| `.glm-logs/w0816t_w85_paper/window_table.json` | flat window table |
| `.glm-logs/w0816t_w85_paper/strategy_summaries.json` | per-strategy aggregates |
| `.glm-logs/w0816t_w85_paper/verdicts.json` | automated verdicts |
| `.glm-logs/w0816t_w85_paper/holistic_judgments.json` | final + wire notes |
| `.glm-logs/w0816t_w85_paper/paper_trial_card.json` | card |
| `.glm-logs/w0816t_w85_paper/runs/` | per-run stores |

---

## Freeze reaffirmation

| item | status |
|------|--------|
| any_research_candidate (default path) | **True** (3) |
| ready_declared | **False** |
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| operational_go | **False** |
| paper continuous | **UNARMED** |
| live | **OFF** |
| commit / push | **not done** |

---

## Summary table for orchestrator

| item | value |
|------|------:|
| windows | **10** (30–65 trading days; multi-year span 2015–2025) |
| strategies run | **6** (KEEP2 + Explore4) |
| runs ok | **60 / 60** |
| cost_bps | **10.0** (liq high · mult 1.0) |
| xs mom5 paper mean / win | **−0.49% / 0.50** · **keep_default** |
| fund hold10 paper mean / win | **−1.77% / 0.30** · **keep_default** (negatives recorded) |
| xs mom3 paper mean / win | **+0.66% / 0.60** · **promote_default** · **wired** |
| xs frac40 | **stay_explore** |
| fund hold15 | **stay_explore** |
| fund hold5 | **stay_explore** |
| default-path count | **3** |
| continuous / live / Mass/READY/GO | **OFF / OFF / closed** |
| commit/push | **no** |

**Return:** full tables above · proof this file · logs under `w0816t_w85_paper` · mom=3 default wire · **no push**.
