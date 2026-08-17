# W89 / w0816x — Interest-rate factors + multi-factor logics + CF eval

**Wave status:** **COMPLETE** — rate factors (abs level + curve) · multi-factor (value×mom×rate, flow×price) · near-groups parallel · PIT+cost lite eval · CF blocked documented · LLM entry connected · 3 defaults frozen · residual TOP · push  
**Wave:** W89 / `w0816x` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Logs:** [`.glm-logs/w0816x_w89_rate_mf/`](../../.glm-logs/w0816x_w89_rate_mf/)  
**Prior tip:** W88 `aa65430` (logic diversity factory)

---

## Goal (PRIMARY) — held

| goal | held |
|------|:----:|
| Interest-rate factor logics (abs level + curve shape) | **yes** · 2 new templates |
| Multi-factor logics with thesis (value×mom×rate, flow×price) | **yes** · 2 new templates |
| Wire LOGIC_TEMPLATES / class_signals / evaluators | **yes** · factory v2.1 · signals v7 |
| PIT + cost eval | **yes** · lite multi-year Q4 · real mirrors + sqlite |
| Near-groups keep parallel (flow hard/soft, fund slow) | **yes** · labeled |
| 3 defaults frozen (no retune) | **yes** · `frozen_defaults_retuned=False` |
| CF prefer; local if blocked | **yes** · **blocked** documented; local mainline |
| Heavy multi-year only for promising | **yes** · lite first; promote note only |
| LLM profit-hypothesis entry (not window tweaks) | **yes** · `propose_profit_hypotheses` **connected** |
| No Mass/READY/ops GO/live · continuous paper UNARMED | **yes** |
| No invent data | **yes** · repo gaps disclose; no ffill |

---

## Explicit freezes (held)

| flag | value |
|------|-------|
| **READY** | **未宣言** |
| **Mass** (operational) | **NO-GO** |
| **Phase7** | **OFF** |
| operational GO | **未宣言 / deferred** |
| continuous paper | **UNARMED** |
| live orders | **OFF** |
| simple_daily_sign diversity | **forbidden** |
| S1–S5 un-reject | **forbidden** |
| look-ahead | **gen-time reject** |
| **3 default-path retune** | **forbidden** · pins held |
| near-group early merge | **forbidden** |
| human main candidates this wave | **not selected** |

### Frozen default path (not retuned)

| representative_id | pins | stance |
|-------------------|------|--------|
| `cross_section_hold_10` | hold=**10** · mom=**5** | KEEP |
| `cross_section_hold_10_mom3` | hold=**10** · mom=**3** | PROMOTE |
| `fundamentals_hold_10` | hold=**10** · mom=**10** · value_momentum_agree | KEEP |

---

## A. Interest-rate factor logics

Dataset: **`jsda_tokyo_repo_rates`** (COMPLETE; local sqlite 30330 rows; multi-tenor available).  
No invent. Gaps disclosed.

### 1. `rate_abs_level_xs` — absolute rate level factor

| field | definition |
|-------|------------|
| **thesis** | Absolute Tokyo repo funding level is a risk-appetite factor: low → risk-on keep CS relative-strength book; high → risk-off reverse CS book; mid → flat |
| **signal** | CS rank(mom) L-S signs, risk-adjusted by absolute repo `rate_level` (not unidirectional mom gate) |
| **position** | sticky fixed_horizon balanced L/S after rate-level book transform |
| **datasets** | equities_bars_daily · markets_calendar · indices_bars_daily_topix · **jsda_tokyo_repo_rates** |
| **family** | `rate_factor` |
| **distinct from** | `macro_repo_rate_level` (mom gate long_only/short_only) |

### 2. `rate_curve_shape_xs` — curve shape proxy (repo tenors only)

| field | definition |
|-------|------------|
| **thesis** | Funding term-structure steepness proxies risk appetite: steep → keep CS book; inverted → reverse; flat → no trade |
| **signal** | `curve_spread = rate(3M/T+1) − rate(overnight/翌日物/T+0)` on same as_of_date; CS rank mom L-S risk-adjusted by curve regime |
| **position** | sticky fixed_horizon balanced L/S after curve-shape book transform |
| **datasets** | bars + **jsda_tokyo_repo_rates** (multi-tenor) |
| **family** | `rate_factor` |
| **curve definition** | **Only observed JSDA Tokyo repo tenors** (overnight T+0/T+1, 1W–3W, 1M/3M/6M/1Y). This is a **funding term-structure proxy**, **not** a sovereign JGB/OIS curve. Missing either leg → gap (no invent/ffill). |

Code: `features.class_signals.compute_rate_level_xs_signal` / `compute_rate_curve_xs_signal` · `research.class_hyp_eval.evaluate_rate_*_on_bars` · `build_repo_curve_series`.

---

## B. Multi-factor logics (thesis required)

### 3. `mf_value_mom_rate` — value × mom × rate

| field | definition |
|-------|------------|
| **thesis** | Cheap winners under easy/mid funding and expensive losers under tight/mid funding earn a multi-day premium (three-factor agreement) |
| **signal** | value_mom_agree **AND** funding alignment (long only if rate not high; short only if rate not low) |
| **position** | sticky fixed_horizon hold of triple-agree signs |
| **datasets** | fins_summary · jsda_tokyo_repo_rates · equities_bars_daily · markets_calendar |
| **family** | `multi_factor` |
| **near-dup** | **not** same as `fund_value_mom_agree` (adds rate leg) |

### 4. `mf_flow_price` — flow × price

| field | definition |
|-------|------------|
| **thesis** | Margin demand earns multi-day only when price momentum confirms flow direction |
| **signal** | enter only when `sign(margin_change)==sign(price_mom)` |
| **position** | min_hold sticky; **price** confirm (not short-ratio confirm) |
| **datasets** | markets_margin_interest · equities_bars_daily · markets_calendar |
| **family** | `multi_factor` |
| **near-dup** | **not** same as flow hard/soft (different confirm source) |

No cartesian hold/mom/frac grids.

---

## C. Near-groups (parallel — do not merge)

| group_id | members | policy |
|----------|---------|--------|
| `flow_margin_confirm` | flow_margin_pressure · flow_margin_short_hard · flow_margin_short_soft · **mf_flow_price** | keep hard/soft/pressure parallel; mf is multi-factor cousin |
| `fund_value_mom` | fund_value_mom_agree · fund_value_mom_agree_slow · **mf_value_mom_rate** | keep slow parallel; mf adds rate |
| `rate_macro_family` | macro_repo_rate_change · macro_repo_rate_level · **rate_abs_level_xs** · **rate_curve_shape_xs** | macro = mom gate; rate_* = CS factor |

Code: `NEAR_LOGIC_GROUPS` / `near_logic_groups_document()`.

---

## D. CF evaluation

| item | result |
|------|--------|
| Status | **blocked** |
| Exact blocker | No CF worker/queue job for mass logic-diversity / multi-period offline factory. Existing CF path = `single_shot_job` (D1 tip signal + R2 artifact) — orthogonal to multi-period rate/multi-factor batch. |
| Scale | **deferred** (do not force 200/500) |
| Supported path | **local** `run_mass_factory` / `scripts/run_mass_strategy_batch.py` |
| Artifacts | local [`.glm-logs/w0816x_w89_rate_mf/`](../../.glm-logs/w0816x_w89_rate_mf/) (R2 mass-factory path not present; standard single_shot R2 not used for this batch) |

Code: `try_cf_minimal_mass_batch()`.

---

## E. LLM / profit-hypothesis entry

| item | result |
|------|--------|
| Status | **connected** |
| Entry | `research.mass_strategy_factory.propose_profit_hypotheses` |
| Rules | Require thesis / signal / position / datasets; **forbid** window-only tweaks; **always through evaluator** |
| Declaration helper | `research.idea_generator.generate_idea_payloads` (still ResearchIdea only) |
| Smoke | 4 rate+mf proposals → n_accepted=4 · evaluated=4 · all survived lite screen |

Machine: [`.glm-logs/w0816x_w89_rate_mf/profit_hypothesis_eval.json`](../../.glm-logs/w0816x_w89_rate_mf/profit_hypothesis_eval.json)

---

## Catalog size (W89)

**22** distinct logic templates (`LOGIC_TEMPLATES`; was 18 in W88).

| logic_id | family | new? |
|----------|--------|:----:|
| rate_abs_level_xs | rate_factor | **W89** |
| rate_curve_shape_xs | rate_factor | **W89** |
| mf_value_mom_rate | multi_factor | **W89** |
| mf_flow_price | multi_factor | **W89** |
| (+ 18 W88 templates held) | … | held |

Version: `mass-strategy-factory/v2.1` · `class-signals/v7`.

---

## Batch eval (real mirrors + sqlite · seed=870816)

| metric | value |
|--------|------:|
| n_generated | **43** |
| n_unique_logic | **22** |
| n_numeric_variant | **21** |
| n_after_dedup | **22** |
| n_dropped_near_dup | **21** |
| logic_diversity_ok | **True** |
| n_families_used | **9** |
| n_strategies_evaluated | **22** (after_dedup) |
| n_survivors | **17** |
| n_screen_rejected | **5** |
| fail_rate | **0.0** |
| wall_time_sec | **~6.866** |
| frozen_defaults_retuned | **False** |
| continuous_paper | **UNARMED** |
| human_main_candidates_selected | **False** |

Reject histogram: `both_signs_near_zero_or_nonpositive` **5** · `near_zero_after_cost` **2**

### New rate + multi-factor results (lite · PIT + cost)

| logic_id | survived | mean_net | t_stat | sharpe_period | chosen_sign | note |
|----------|:--------:|---------:|-------:|--------------:|:-----------:|------|
| **mf_value_mom_rate** | **yes** | +46.3bp | **1.48** | **0.60** | +1 | **most promising** multi-factor |
| **mf_flow_price** | **yes** | +63.2bp | 1.28 | −0.54 | −1 | flow near-group cousin |
| **rate_curve_shape_xs** | **yes** | +38.2bp | 0.91 | 0.37 | +1 | curve CS factor |
| **rate_abs_level_xs** | **yes** | +44.4bp | 0.87 | −0.41 | −1 | abs level CS factor |

### Near-group comparison (lite)

| group | survivors | note |
|-------|-----------|------|
| flow hard/soft/pressure | all 3 **survived** | top ranks (soft/pressure t≈1.53) |
| fund value×mom / slow | **both rejected** (near-zero / both-signs) | mf_value_mom_rate **survived** (rate leg adds edge in lite) |
| rate macro family | macro_repo_* **rejected**; rate_* **survived** | CS risk-adj ≠ mom gate |

### Promising → multi-year policy

- Lite not dead for: **mf_value_mom_rate** (t≈1.48, Sharpe≈0.60), mf_flow_price, rate_* (weaker t).  
- **Heavy multi-year / distributed deferred** this wave — only promote when lite promising; re-eval via deeper `class_hyp` before any research_candidate claim.  
- **Not** production research_candidate · **not** Mass/READY/GO.

Tradeoff (unchanged): Q4 windows · max_codes=20 · max_days=80 · not production SoT.

Recipe:

```bash
.venv/bin/python scripts/run_mass_strategy_batch.py \
  --seed 870816 --n 100 \
  --out-dir .glm-logs/w0816x_w89_rate_mf/
```

---

## Module / CLI

| item | path |
|------|------|
| Factory | `packages/product/research/mass_strategy_factory.py` · v2.1 |
| Signals | `packages/research_runtime/features/class_signals.py` · v7 |
| Eval | `packages/product/research/class_hyp_eval.py` · rate/mf evaluators + curve series |
| CLI | `scripts/run_mass_strategy_batch.py` |
| Profit hyp entry | `propose_profit_hypotheses` |
| Cost / sign | `cost_models` · `sign_selection` (reused) |
| Tests | `tests/test_mass_strategy_factory.py` · `tests/test_class_signals.py` (pass) |

---

## Residual TOP (W89)

1. **rate + multi-factor logics** — landed · lite survivors noted · deeper multi-year only for promising (`mf_value_mom_rate` first)  
2. **CF status** — **blocked** (no mass-logic worker; local mainline)  
3. **defaults frozen** — mom5 / mom3 / fund · not retuned  
4. **near-groups parallel** — flow hard/soft · fund slow · rate cousins · do not merge  
5. **GO deferred** · Mass/READY/ops GO closed · continuous paper UNARMED  

---

## Explicit non-declarations

- READY / Mass ON / Phase7 / operational GO / continuous paper arm / live  
- factory survivors as production research_candidates  
- 3 defaults retune  
- hold/mom/frac grid as diversity  
- CF 200/500 scale  
- near-group merge  
- S1–S5 un-reject  
- invent data / ffill repo  

---

## Underneath held

- W88 logic-diversity factory (templates · near-dup · unique_logic metrics)  
- W87 factory pipeline skeleton  
- W86 sign flip · paper repo · compare · 3 defaults chosen_sign=+1  
- COMPLETE 22 · OTC tip-wait · S1–S5 rejected  
