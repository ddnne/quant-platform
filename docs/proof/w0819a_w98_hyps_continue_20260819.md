# W98 / w0819a — Track D failure-constrained hyp generation (continue)

**Wave:** W98 / `w0819a` · Track D  
**Generator:** `llm-hyp-generator/v1.1` · wave tag **W98 / w0819a** · provider **xai** · model **grok-4.6**  
**Route:** always `propose_profit_hypotheses` · gates cost / PIT / low-var  
**Policy:** modest N · failure constraints · **reduce mapping onto known weak catalog templates** · do **not** resurrect demoted/weak as main · no hold/mom/frac grid  
**Recipe:** `scripts/run_w98_xs_sticky_deepdive.py` (Track D)  
**Logs:** [`.glm-logs/w0819a_w98_otc_master_xs/`](../../.glm-logs/w0819a_w98_otc_master_xs/) · `hyp_summary.json` · `w98_cd_summary.json`  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Counts

| metric | n |
|--------|--:|
| n_requested | **6** |
| n_proposed | **6** |
| n_accepted | **4** |
| n_rejected (gen+eval) | **2** (gen=2 · eval=0) |
| n_evaluated | **4** |
| n_survivors | **2** |
| n_skipped_weak_catalog_map | **0** |

**Headline counts:** **6 / 4 / 2** (proposed / accepted / survivors)

## Failure-mode constraints (held · v1.1+ · W98)

- no_sign_flip_single_regime_reliance
- no_soft_eq_pressure
- no_low_var_t_trust
- no_window_only
- no_dual_options_level
- no_repolish_shape_rate_flow_demoted_fund_slow
- no_hold_mom_frac_grid
- **reduce_map_onto_known_weak_templates** (rate → `rate_curve_shape_xs` not `rate_abs_level_xs`; flow weak cousins not remapped)

## Representative theses (accepted · distinct mechanisms)

| logic_id (LLM) | family | catalog map |
|----------------|--------|-------------|
| `toushin_etf_creation_ap_inventory` | fund | → `fund_value_mom_agree` |
| `jgb_steepener_loan_afs_bank_xs` | rate | → **`rate_curve_shape_xs`** (not weak `rate_abs_level_xs`) |
| `usd_funding_oplev_value_xs` | multi_factor | → `mf_value_mom_rate` |
| `edinet_buyback_execution_capacity` | event | → `event_post_disclosure_hold` |

2 proposals rejected at generation under failure-mode / schema constraints (not evaluated).

## Eval screens (catalog-mapped) — **not** main promotion

| mapped logic_id | survived | reject / note |
|-----------------|:--------:|---------------|
| `fund_value_mom_agree` | False | near_zero_after_cost |
| `rate_curve_shape_xs` | True | research-only · **not** weak abs-level remap |
| `mf_value_mom_rate` | False | inflated_t_low_variance |
| `event_post_disclosure_hold` | True | below promote bar · research-only |

### Eval ranking (survivors only)

| rank | logic_id | mean_net | t_stat | sign |
|-----:|----------|---------:|-------:|-----:|
| 1 | `event_post_disclosure_hold` | 0.007352 | 0.983 | +1 |
| 2 | `rate_curve_shape_xs` | 0.003819 | 0.906 | +1 |

**demoted_weak_mapped_survivors:** **[]** (empty — weak-template mapping reduced vs W97 where `rate_abs_level_xs` surfaced).  
**Do not** promote as main · factory survivors ≠ production research_candidates · Mass **NO-GO** · `promote_as_main=false` · `go=false`.

## Pins

3-default pins **unchanged** (`cross_section_hold_10` KEEP · `cross_section_hold_10_mom3` PROMOTE · `fundamentals_hold_10` KEEP) · `frozen_pins_assert(_after).json` · **pins_untouched=True**.
