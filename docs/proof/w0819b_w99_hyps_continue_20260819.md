# W99 / w0819b Track C — failure-constrained hyps continue

**Wave:** W99 / `w0819b` · Track C  
**Generator:** `llm-hyp-generator/v1.1` · provider **xAI grok-4.6**  
**Route:** `propose_profit_hypotheses` + cost/PIT/low-var gates  
**Artifacts:** [`.glm-logs/w0819b_w99_otc_sticky_dd/`](../../.glm-logs/w0819b_w99_otc_sticky_dd/) · `hyp_summary.json`  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| metric | value |
|--------|------:|
| n_requested | 6 |
| n_proposed | **6** |
| n_accepted | **5** |
| n_rejected (gen/eval) | **1 / 0** |
| n_evaluated | 5 |
| n_survivors | **2** |
| n_skipped_weak_catalog_map | 0 |
| reduce_weak_template_mapping | **True** |
| demoted/weak resurrected as main | **no** |
| promote_as_main | **false** |
| go | **false** |
| frozen_defaults_retuned | **false** |

**Pack: 6 / 5 / 2** (proposed / accepted / survivors). Survivors remain research-only — **not** main / **not** GO.

---

## Failure-mode constraints (held)

- no_sign_flip_single_regime_reliance  
- no_soft_eq_pressure  
- no_low_var_t_trust  
- no_window_only  
- no_dual_options_level  
- no_repolish_shape_rate_flow_demoted_fund_slow  
- no_hold_mom_frac_grid  
- reduce_map_onto_known_weak_templates  

---

## Representative accepted theses (sample)

1. `auction_imbalance_inventory_workoff` (flow) — close-auction imbalance beyond dealer absorption → multi-day inventory work-off  
2. `gpif_benchmark_gap_rebalance` (fund) — public-pension benchmark gap closure around fiscal/policy rebalance dates  
3. `revision_quality_uncrowded_residual` (multi_factor) — cheap + positive revisions + uncrowded residual  
4. `cross_share_unwind_overhang` (event) — cross-share reduction overhang via ToSTNeT/continuous  
5. `idio_rv_burst_quality_spread` (vol) — idiosyncratic RV burst → quality spread (not index-vol)

---

## Freezes held

- Mass = NO-GO · READY = false · ops GO = false · continuous paper = UNARMED  
- 3-default pins **untouched**  
- Survivors **not** promoted as main / GO
