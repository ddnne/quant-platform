# W84 / w0816s — research↔paper realign (2 default candidates)

**Wave:** W84 / `w0816s` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Tasks:** **A** gap tables + realistic StrategySpec/adapter/runner fixes · **B** remeasure + paper-negative validity  
**Candidates:** `cross_section_hold_10` mom=**5** · `fundamentals_hold_10` mom=**10**  
**Logs:** [`.glm-logs/w0816s_w84_realign/`](../../.glm-logs/w0816s_w84_realign/)  
**Prior:** W83 parallel default wire · paper limited proxy **xs −1.96%** · **fund −4.06%**

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

**Policy:** Align **paper / StrategySpec / adapters toward realistic research**. Paper negative is **not** auto-reject — analyze regime + thesis + costs/execution; keep if valid for fair comparison OR demote if weak/bug. Always show **t / Sharpe / win-rate**; flexible holistic judgment.

---

## Task A — gap tables + realistic fixes

### 1. Diff: research eval vs paper StrategySpec

#### cross_section_hold_10 (mom=5 · hold=10)

| dimension | Research | Paper **pre-W84** (proxy) | Paper **post-W84** (v3) | alignable? |
|-----------|----------|---------------------------|-------------------------|------------|
| **Entry** | rank(mom_n=5); top 30% +1 / bottom 30% −1 | top_k=5 momentum (long-only) | `cross_section_rank` long_frac=0.3 short_frac=0.3 | **Yes** |
| **Exit / hold** | sticky fixed_horizon 10d | daily rebalance (no sticky) | `rebalance=fixed_horizon` hold_days=10; empty intents mid-hold (shares stick) | **Yes** |
| **Costs** | 10bp one-way · liq mult · amort/10 | 10bp · daily churn | 10bp · rebalance-only turnover | **Yes** |
| **Universe** | 30 large-cap DEFAULT_EVAL_CODES | same 30 | same 30 | **Yes** |
| **Rebalance** | every 10 sessions | daily | fixed_horizon 10d | **Yes** |
| **PIT** | bars ≤ t | next_close | next_close | **Partial** (both non-look-ahead) |
| **Scoring** | trade-level mean signed multi-day R | portfolio MTM | portfolio MTM | **Residual** |

#### fundamentals_hold_10 (mom=10 · hold=10 · value×mom agree)

| dimension | Research | Paper **pre-W84** (proxy) | Paper **post-W84** (v3) | alignable? |
|-----------|----------|---------------------------|-------------------------|------------|
| **Entry** | value (BPS/P\|EPS/P PIT) vs global median × mom_n=10 agree; L/S | top_k=5 mom_n=10 only (value leg **missing**) | `value_momentum_agree` + `fundamental_value_score` + mom_n=10 | **Yes** (benchmark residual) |
| **Exit / hold** | sticky fixed_horizon 10d | daily | fixed_horizon 10d sticky shares | **Yes** |
| **Costs** | 10bp · liq · amort/10 | 10bp daily churn | 10bp rebalance-only | **Yes** |
| **Universe** | 30 | 30 | 30 | **Yes** |
| **Rebalance** | every 10 sessions | daily | fixed_horizon 10d | **Yes** |
| **PIT** | fins_asof DiscDate/Time | n/a (no value) | fins_summary PIT + bars | **Yes** |
| **Scoring** | trade-level mean | portfolio MTM | portfolio MTM | **Residual** |

### 2. Code changes (align paper → research)

| artifact | change |
|----------|--------|
| `strategies/spec/schema.py` | **strategy-spec/v3**: `fixed_horizon` + `hold_days`; rules `cross_section_rank`, `value_momentum_agree`; v2 still parseable |
| `strategies/spec/interpreter.py` | sticky hold (empty intents mid-horizon → shares untouched); CS rank L-S weights; value×mom agree with CS median |
| `core/engine.py` | allow negative target weights (simple short book for paper L-S) |
| `features/complete21_min.py` | approved `fundamental_value_score` (BPS/P\|EPS/P PIT) |
| `research/paper_candidate_adapter.py` | v2 adapter: builders for xs CS + fund value×mom; sticky envelopes |

### 3. Residual approximations (unavoidable only)

1. **Portfolio MTM vs trade-level research mean** — research scores mean of signed multi-day returns on active code-days; paper is equal-weight portfolio mark-to-market (long book 50% / short book 50% when both sides present).  
2. **No margin / borrow model** on short leg (cash-adjusted simple short).  
3. **Fund value benchmark** — paper uses same-bar CS median of *visible* value scores; research uses global-window median of value scores in the eval period.  
4. **Event_post** still proxy (disclosure_flag ≠ signed surprise) — out of scope for the 2 default candidates.

**No** “ignore hold / ignore cost” hacks.

---

## Task B — remeasure + validity

### 5. Research multi-year recompute (unchanged definitions)

Source: `.glm-logs/w0816s_w84_realign/class_hyp_multi_year_bundle.json`  
Windows: y2015_full · y2017_q4 · y2019_full · y2021_full · y2023_full · y2025_q4 · 30 codes · liq 10bp.

| block | mean net | t | Sharpe | win-rate | hard RC | note |
|-------|---------:|--:|-------:|---------:|:------:|------|
| **cross_section_hold_10** mom=5 | **+84.6bp** | **1.60** | **0.65** | **0.67** | **True** | matches W83 |
| **fundamentals_hold_10** mom=10 | **+45.9bp** | **1.82** | **0.74** | **0.67** | **True** | matches W83 |
| cross_section hold=5 (primary) | −10.9bp | −0.44 | −0.18 | 0.50 | False | context |
| fundamentals hold=20 (primary) | +70.9bp | 1.04 | 0.42 | 0.67 | False | occ fail |
| multi_day_hold 10d | +21.1bp | 0.62 | 0.25 | 0.67 | False | noisy |
| event_post PIT | +5.9bp | 0.25 | 0.10 | 0.67 | False | demoted W82 |

No research-side simplification. Metrics stable after paper-only alignment.

### 6. Limited paper re-trial (aligned StrategySpec v3)

DB: W83 offline seed (`.glm-logs/w0816r_w83_parallel/paper_db/w83_paper_trial.sqlite`) · same 30 codes · 10bp · next_close · continuous **UNARMED**.

| trial | class | window | post-cost | maxDD | trades | days |
|-------|-------|--------|----------:|------:|-------:|-----:|
| single-shot | xs hold10 aligned | 5d Draft | **+0.52%** | −0.15% | 16 | 5 |
| **limited** | xs hold10 aligned | 30d Paper | **+1.54%** | −1.23% | **60** | 30 |
| single-shot | fund hold10 aligned | 5d Draft | **+1.93%** | −0.10% | 12 | 5 |
| **limited** | fund hold10 aligned | 30d Paper | **+4.72%** | −4.71% | **55** | 30 |

#### vs W83 proxy (same window / DB)

| candidate | W83 proxy limited post | W83 trades | **W84 aligned post** | **W84 trades** |
|-----------|-----------------------:|-----------:|---------------------:|---------------:|
| xs hold10 | **−1.96%** | 175 | **+1.54%** | **60** |
| fund hold10 | **−4.06%** | 152 | **+4.72%** | **55** |

Sticky hold + true CS L-S / value×mom collapsed daily churn and flipped limited-window PnL. **Not** an alpha / significance claim — still a short autumn window rehearsal.

### 7. Paper-negative validity (W83 negatives; W84 path non-negative)

W83 limited paper was **negative** under irreducible proxy. After W84 alignment the same window is **positive**. Validity analysis still required for honesty and for any future negative windows.

| axis | xs hold10 | fund hold10 |
|------|-----------|-------------|
| **Market regime (2023-08-31…10-13)** | Post-summer bounce into early-Oct risk-off in JP large-cap; ~30 trading days · ~3 sticky rebalance cycles — under-powered vs 6 multi-year windows | same window |
| **Thesis** | CS mom rank L-S sticky 10d; mom lookback **pinned at 5** (content-match mom=10 destroys research residual) | PIT value × mom=10 agree sticky 10d (value_only fails research) |
| **W83 negative expected?** | **Yes** — daily top_k long-only ≠ CS L-S sticky; cost drag from 175 trades | **Yes** — momentum-only proxy ≠ value×mom; 152 trades |
| **Bug?** | **No** (proxy fidelity gap, not pipeline bug) | **No** |
| **W84 limited** | **+1.54%** post · 60 trades — consistent with thesis under better fidelity | **+4.72%** post · 55 trades |
| **Costs / execution** | 10bp one-way · next_close · sticky share hold | same |

### 8. Decisions (holistic; t/Sharpe/win-rate always shown)

| candidate | mean | t | Sharpe | win-rate | research RC | paper limited | **decision** | reasons (summary) |
|-----------|-----:|--:|-------:|---------:|:-----------:|--------------:|:------------:|-------------------|
| **cross_section_hold_10** | +84.6bp | **1.60** | **0.65** | **0.67** | True | **+1.54%** | **KEEP** | Hard bar pass; W82 mom=5 pin held; paper path now expresses sticky CS L-S; W83 negative was expected proxy artifact not edge falsification; borderline t kept with written reasons (payoff 3.6 · small maxDD · multi-year). Not Mass/READY/GO. |
| **fundamentals_hold_10** | +45.9bp | **1.82** | **0.74** | **0.67** | True | **+4.72%** | **KEEP** | Stronger stats than xs; content improve vs hold=20; value×mom now on StrategySpec; paper limited supportive under residuals; not promotion to live. |

**Neither demoted.** Paper negatives at W83 were **expected** under proxy, not unexpected edge collapse. No bug. Continuous paper remains **UNARMED**.

### Production research candidates after W84

**2** default-path research candidates retained:

1. `cross_section_hold_10` (mom=5)  
2. `fundamentals_hold_10` (mom=10)

Mass / READY / operational GO / live: **still closed**.

---

## Freeze reaffirmation

| item | status |
|------|--------|
| any_research_candidate (default path) | **True** (2) |
| ready_declared | **False** |
| mass_research | **NO-GO** |
| phase7 | **OFF** |
| operational_go | **False** |
| paper continuous | **UNARMED** |
| live | **OFF** |
| commit / push | **not done** |

---

## Log index

| path | content |
|------|---------|
| `.glm-logs/w0816s_w84_realign/gap_tables.json` | research vs paper diffs |
| `.glm-logs/w0816s_w84_realign/class_hyp_multi_year_bundle.json` | full multi-year recompute |
| `.glm-logs/w0816s_w84_realign/candidate_summary_compact.json` | candidate bar extract |
| `.glm-logs/w0816s_w84_realign/paper_specs/` | StrategySpec v3 + envelopes |
| `.glm-logs/w0816s_w84_realign/paper_results.json` | paper trials |
| `.glm-logs/w0816s_w84_realign/paper_trial_card.json` | card |
| `.glm-logs/w0816s_w84_realign/decisions.json` | keep/conditional/demote |
| `.glm-logs/w0816s_w84_realign/run_w84_realign.py` | runner |
| `.glm-logs/w0816s_w84_realign/pytest_key.log` | unit tests |

---

## Summary table for orchestrator

| item | value |
|------|------:|
| xs mean / t / Sharpe / win | **+84.6bp / 1.60 / 0.65 / 0.67** |
| fund mean / t / Sharpe / win | **+45.9bp / 1.82 / 0.74 / 0.67** |
| xs paper limited post-cost | **+1.54%** (was −1.96% proxy) |
| fund paper limited post-cost | **+4.72%** (was −4.06% proxy) |
| xs decision | **KEEP** |
| fund decision | **KEEP** |
| StrategySpec | **v3** sticky + CS L-S + value×mom |
| continuous paper | **OFF** |
| Mass/READY/GO | **closed** |
| commit/push | **no** |

**Return:** decisions table above · proof this file · logs under `w0816s_w84_realign` · **no push**.
