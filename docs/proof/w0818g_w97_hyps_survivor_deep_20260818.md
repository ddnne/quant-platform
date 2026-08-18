# W97 / w0818g — Track D failure-constrained hyp generation (continue)

**Wave:** W97 / `w0818g` · Track D  
**Generator:** `llm-hyp-generator/v1.1` · wave tag **W97 / w0818g** · provider **xai** · model **grok-4.6**  
**Route:** always `propose_profit_hypotheses` · gates cost / PIT / low-var  
**Policy:** modest N · no hold/mom/frac grid · do **not** resurrect demoted/weak as main  
**Recipe:** `scripts/run_w97_survivor_deep_eval.py` (Track D)  
**Logs:** [`.glm-logs/w0818g_w97_otc_master_hyps/`](../../.glm-logs/w0818g_w97_otc_master_hyps/) · `hyp_summary.json` · `w97_cd_summary.json`  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Counts

| metric | n |
|--------|--:|
| n_requested | **6** |
| n_proposed | **6** |
| n_accepted | **6** |
| n_rejected (gen+eval) | **0** |
| n_evaluated | **6** |
| n_survivors | **2** |

## Failure-mode constraints (held · v1.1+)

- no_sign_flip_single_regime_reliance
- no_soft_eq_pressure
- no_low_var_t_trust
- no_window_only
- no_dual_options_level
- no_repolish_shape_rate_flow_demoted_fund_slow
- no_hold_mom_frac_grid

## Representative theses (distinct mechanisms)

| logic_id | family |
|----------|--------|
| `foreign_float_util_pressure_xs` | flow |
| `te_gap_trust_turn_recon` | fund |
| `jgb_2s10s_duration_gap_xs` | rate |
| `activist_increase_cash_lowpayout` | event |
| `post_earn_idio_rvcrush_beat_guide` | vol |
| `dual_china_pmi_neer_stable_china_share` | macro |

Eval maps unknown ids onto nearest executable catalog templates (thesis text retained).

## Eval screens (catalog-mapped) — **not** main promotion

| mapped logic_id | survived | reject / note |
|-----------------|:--------:|---------------|
| `rate_abs_level_xs` | True | **known weak_thesis family — research-only / not main** |
| `event_post_disclosure_hold` | True | below promote bar · research-only |
| `flow_margin_short_hard` | False | inflated_t_low_variance |
| `fund_value_mom_agree` | False | near_zero_after_cost |
| `vol_risk_adjusted_mom` | False | near_zero_after_cost |
| `macro_repo_rate_change` | False | near_zero + inflated_t_low_variance |

### Eval ranking (survivors only)

| rank | logic_id | mean_net | t_stat | sign |
|-----:|----------|---------:|-------:|-----:|
| 1 | `rate_abs_level_xs` | 0.007367 | 2.172 | −1 |
| 2 | `event_post_disclosure_hold` | 0.007352 | 0.983 | +1 |

**Do not** promote demoted/weak as main · `rate_abs_level_xs` flagged `demoted_weak_mapped_survivors` · factory survivors ≠ production research_candidates · Mass **NO-GO**.

## Pins

3-default pins **unchanged** (`cross_section_hold_10` KEEP · `cross_section_hold_10_mom3` PROMOTE · `fundamentals_hold_10` KEEP) · `frozen_pins_assert(_after).json` · **pins_untouched=True**.
