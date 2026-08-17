# W88 / w0816w — logic diversity factory (not param grids)

**Wave status:** **COMPLETE** — logic templates · near-dup · metrics unique_logic/after_dedup · 3 defaults frozen · local batch · CF blocked documented · residual TOP reforge · push  
**Wave:** W88 / `w0816w` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Logs:** [`.glm-logs/w0816w_w88_logic/`](../../.glm-logs/w0816w_w88_logic/)  
**Prior tip:** W87 `979157f` (mass factory N=100 family×param slots)

---

## Goal (PRIMARY) — held

Redefine generator around **distinct economic logic templates** (signal structure + portfolio rule + data source + thesis), not hold/mom/frac grids.

| goal | held |
|------|:----:|
| Logic templates with thesis / signal / position / datasets / logic_id / fingerprint | **yes** · **18** templates |
| Near-duplicate drops grid-only mutations | **yes** · threshold **0.85** · dropped **17** |
| Metrics: n_generated · n_unique_logic · n_after_dedup (not just N) | **yes** |
| Freeze 3 defaults (no retune mom3/mom5/fund) | **yes** · `frozen_defaults_retuned=False` |
| Eval only after dedup (distinct logics) | **yes** · eval_set=`after_dedup` · **18** eval |
| Minimal CF path or exact blocker | **yes** · **blocked** (documented) |
| Local batch runs | **yes** · wall **~6.5s** |
| No Mass/READY/ops GO/live · continuous paper UNARMED | **yes** |
| Not simple_daily_sign mass · not look-ahead | **yes** |

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
| simple_daily_sign as diversity | **forbidden** |
| S1–S5 un-reject | **forbidden** |
| look-ahead | **gen-time reject** |
| **3 default-path retune** | **forbidden** · pins held |
| human main candidates this wave | **not selected** |

### Frozen default path (not retuned)

| representative_id | pins | stance |
|-------------------|------|--------|
| `cross_section_hold_10` | hold=**10** · mom=**5** | KEEP |
| `cross_section_hold_10_mom3` | hold=**10** · mom=**3** | PROMOTE |
| `fundamentals_hold_10` | hold=**10** · mom=**10** · value_momentum_agree | KEEP |

Code: `FROZEN_DEFAULT_PATH` in `mass_strategy_factory.py`.

---

## Problem with W87 (addressed)

W87 N=100 **succeeded as capacity** but diversity risked counting **hold_days / momentum_window / long_frac** multi-axis slots as distinct strategies. User rejects that.

| W87 risk | W88 fix |
|----------|---------|
| Family × param grid flood | Primary unit = **logic template** |
| hold/mom/frac as diversity | Explicit **does_not_count** rules + near-dup |
| Metrics only N / family_dist | **n_unique_logic · n_after_dedup · n_numeric_variant** |
| Eval all 100 clones | Eval **after_dedup** only |

---

## Task A — logic templates

Each individual carries:

* `thesis` — what earns  
* `signal_definition` — entry / signal structure  
* `position_rule` — book / hold construction  
* `datasets_used` — info source  
* `logic_id` / `logic_fingerprint`  

**Catalog size:** **18** distinct templates (`LOGIC_TEMPLATES`).

| logic_id | family | thesis (short) |
|----------|--------|----------------|
| mdh_sticky_momentum | multi_day_hold | multi-day continuation |
| mdh_mean_reversion | multi_day_hold | multi-day reversion **entry** (not eval sign flip) |
| mdh_short_horizon_mom | multi_day_hold | short 5d hold economy |
| event_post_disclosure_hold | event_post | PIT post-disclosure drift |
| event_post_long_horizon | event_post | longer post-disc drift |
| xs_rank_ls_sticky | cross_section | sticky relative L-S |
| xs_rank_ls_daily | cross_section | daily rebalance L-S |
| xs_rank_mom_slow | cross_section | slow-rank L-S structure |
| macro_repo_rate_change | macro_conditioned | repo **change** regime |
| macro_repo_rate_level | macro_conditioned | repo **level** regime |
| fund_value_only | fundamentals_price | PIT value only |
| fund_value_mom_agree | fundamentals_price | value×mom agree |
| fund_value_mom_agree_slow | fundamentals_price | value×slow mom |
| flow_margin_pressure | flow_demand | margin multi-day |
| flow_margin_short_hard | flow_demand | margin + hard short confirm |
| flow_margin_short_soft | flow_demand | margin + soft short confirm |
| vol_risk_adjusted_mom | vol_risk_adjusted | \|mom\|/vol gate |
| vol_breakout_expand | vol_risk_adjusted | vol-expansion breakout gate |

Numeric knobs only after logic fixed; optional **one** coarse numeric fill per template for capacity (`allow_numeric_variants`) — marked `is_numeric_variant` and **near-dup dropped**.

### Diversity rules

**Counts as different if** differs in: info source, entry logic, position construction, economic thesis.

**Does NOT count:** hold_days only · momentum window only · frac 0.3→0.4 only · sign flip as separate strategy (sign is eval aspect).

---

## Task B — near-duplicate

| item | behavior |
|------|----------|
| Similarity features | signal family + position rule + datasets + structural keys + coarse knobs |
| Same `logic_fingerprint` | score **≥0.95** (grid twin) |
| Threshold | **0.85** (`DEFAULT_NEAR_DUP_THRESHOLD`) |
| Action | keep first of cluster · drop rest as `near_duplicate_grid_mutation` |

### Observed generation (seed=870816, n=100 capacity)

| metric | value |
|--------|------:|
| n_generated | **35** |
| n_unique_logic | **18** |
| n_numeric_variant | **17** |
| n_after_dedup | **18** |
| n_dropped_near_dup | **17** |
| logic_diversity_ok | **True** |
| n_families_used | **7** |
| anti_bias_ok | **True** |

**Interpretation:** capacity fill produced numeric twins; **after_dedup = unique_logic = 18**. Grid mass no longer counts as 100 strategies.

Machine: [`.glm-logs/w0816w_w88_logic/strategies_after_dedup.json`](../../.glm-logs/w0816w_w88_logic/strategies_after_dedup.json) · [`near_dup_dropped.json`](../../.glm-logs/w0816w_w88_logic/near_dup_dropped.json)

---

## Task C — eval

| step | held |
|------|:----:|
| Common evaluator (class_hyp pure bars + costs) | yes |
| Post-cost · both signs · t/Sharpe/activation | yes |
| Eval set = after_dedup only | **yes** · **18** |
| Fail-one-continue | yes · fail_rate **0.0** |
| 3 defaults frozen (not retuned) | **yes** |
| continuous paper UNARMED | **yes** |
| human main not selected | **yes** |

### Observed batch (real mirrors + sqlite)

| metric | value |
|--------|------:|
| n_strategies_evaluated | **18** |
| eval_set | **after_dedup** |
| fail_rate | **0.0** |
| wall_time_sec | **~6.503** |
| n_survivors | **13** |
| n_screen_rejected | **5** |

Reject reason histogram: `both_signs_near_zero_or_nonpositive` **5** · `near_zero_after_cost` **2**

Survivor logics (13): flow_margin_* (3) · xs_rank_* (2) · event_post_* (2) · mdh_* (3) · vol_* (2) · fund_value_only (1)

Lite tradeoff (unchanged): Q4 windows · max_codes=20 · max_days=80 · not production research_candidate SoT.

---

## Task D — CF minimal

| item | result |
|------|--------|
| Status | **blocked** |
| Blocker | No CF worker/queue job for mass logic-diversity factory. Existing CF path = `single_shot_job` (D1 tip signal + R2 artifact) — orthogonal to multi-period offline logic batch. |
| Scale | **deferred** (do not force 200/500) |
| Supported path | **local** `run_mass_factory` / `scripts/run_mass_strategy_batch.py` |

Code: `try_cf_minimal_mass_batch()`.

---

## Task E — LLM entry

| item | result |
|------|--------|
| Status | **unconnected** |
| Note | `idea_generator` emits ResearchIdea declarations only; not wired to logic factory profit-hypothesis prompts. |
| Future rule | Prompt for **different economic theses** (not window tweaks); **always through evaluator**. |

Code: `llm_logic_entry_status()`.

---

## Module / CLI

| item | path |
|------|------|
| Module | [`packages/product/research/mass_strategy_factory.py`](../../packages/product/research/mass_strategy_factory.py) · `mass-strategy-factory/v2` |
| CLI | [`scripts/run_mass_strategy_batch.py`](../../scripts/run_mass_strategy_batch.py) |
| Tests | [`tests/test_mass_strategy_factory.py`](../../tests/test_mass_strategy_factory.py) |
| This proof | `docs/proof/w0816w_w88_logic_diversity_factory_20260817.md` |

### Re-run recipe

```bash
.venv/bin/python scripts/run_mass_strategy_batch.py \
  --seed 870816 --n 100 \
  --out-dir .glm-logs/w0816w_w88_logic/

.venv/bin/python scripts/run_mass_strategy_batch.py \
  --synthetic --n 100 --out-dir /tmp/msf_syn
```

Tests: `tests/test_mass_strategy_factory.py` — logic templates · near-dup grid score · metrics · freezes · frozen defaults · fail-one · CF/LLM residual.

---

## Residual TOP (this wave)

1. **grid mass production → logic diversification** (held)  
2. **3 defaults frozen** (held · no retune)  
3. **GO deferred** · Mass/READY/ops GO closed · continuous paper UNARMED  

Next (not this wave): deepen multi-year class_hyp on distinct-logic survivors · optional LLM thesis prompts through evaluator · CF scale only if dedicated job lands.

---

## Explicit non-declarations

- READY / Mass ON / Phase7 / operational GO / live orders  
- continuous paper arm  
- factory survivors as production research_candidates  
- human main selection  
- hold/mom/frac grid as 100 strategies  
- retune mom5 / mom3 / fund defaults  
- simple_daily_sign mass gen  
- CF 200/500 scale  
