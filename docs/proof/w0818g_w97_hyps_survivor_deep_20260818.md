# W97 / w0818g — Track D failure-constrained hyp generation

**Wave:** W97 / `w0818g` · Track D  
**Generator:** `llm-hyp-generator/v1.1` · provider **xai** · model **grok-4.6**  
**Route:** always `propose_profit_hypotheses` · gates cost / PIT / low-var  
**Logs:** [`.glm-logs/w0818g_w97_otc_master_hyps/`](../../.glm-logs/w0818g_w97_otc_master_hyps/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Counts

| metric | n |
|--------|--:|
| proposed | **8** |
| accepted | **8** |
| evaluated | **8** |
| survivors | **5** |

## Failure-mode constraints (held)

- no_sign_flip_single_regime_reliance
- no_soft_eq_pressure
- no_low_var_t_trust
- no_window_only
- no_dual_options_level
- no_repolish_shape_rate_flow_demoted_fund_slow

## Eval ranking (survivors)

| rank | logic_id | mean_net | t_stat | sign |
|-----:|----------|---------:|-------:|-----:|
| 1 | `flow_margin_short_hard` | 0.006686 | 1.063 | -1 |
| 2 | `event_post_disclosure_hold` | 0.007352 | 0.983 | 1 |
| 3 | `rate_abs_level_xs` | 0.004435 | 0.868 | -1 |
| 4 | `xs_rank_ls_sticky` | 0.002133 | 0.479 | 1 |
| 5 | `vol_risk_adjusted_mom` | 0.002971 | 0.379 | -1 |

**Do not** promote demoted/weak as main · factory survivors ≠ production research_candidates · Mass **NO-GO**.

## Pins

3-default pins **unchanged** (`cross_section_hold_10` KEEP · `cross_section_hold_10_mom3` PROMOTE · `fundamentals_hold_10` KEEP).
