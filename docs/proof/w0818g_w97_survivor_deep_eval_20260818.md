# W97 / w0818g — Track C deep multi-year eval of W96 5 survivors

**Wave:** W97 / `w0818g` · Track C  
**Policy:** lite W96 survivors ≠ final · CF `r2_panels` preferred · cost+PIT+sign+low-var · research-only if unstable · **no** GO/main-promote  
**Recipe:** `scripts/run_w97_survivor_deep_eval.py`  
**Logs:** [`.glm-logs/w0818g_w97_otc_master_hyps/`](../../.glm-logs/w0818g_w97_otc_master_hyps/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Survivors under test (from W96 `hyp_xai_eval` ranking)

1. `mf_value_mom_rate`
2. `rate_abs_level_xs`
3. `event_post_disclosure_hold`
4. `flow_margin_short_hard`
5. `xs_rank_ls_sticky`

## CF deep job

| field | value |
|-------|-------|
| job_id | `w97-survivors-20260818T145732Z` |
| status | `ok` |
| mode | `cf_r2_panels` |
| window survivor cells | **13/15** |
| research_only | **5/5** |
| unstable_or_weak | **4** |
| promote_as_main | **False** |
| go_eligible | **False** |
| 3-default pins | **unchanged / not retuned** |

## Multi-year table (preferred CF)

| window | logic | mean_net | t | act | sharpe | sign | surv | low_var | rejects |
|---|---|---:|---:|---:|---:|---|:---:|:---:|---|
| w2017_2019 | `mf_value_mom_rate` | 0.005259 | 0.7026 | 0.0444 | 0.497 | 1 | True | False | — |
| w2017_2019 | `rate_abs_level_xs` | 0.005351 | 0.6501 | 0.0849 | 0.460 | 1 | True | False | — |
| w2017_2019 | `event_post_disclosure_hold` | -0.000016 | -0.0740 | 0.1843 | -0.052 | — | False | False | near_zero_after_cost,both_signs_near_zero_or_nonpositive |
| w2017_2019 | `flow_margin_short_hard` | -0.000122 | -0.0343 | 0.0548 | -0.024 | — | False | False | near_zero_after_cost,both_signs_near_zero_or_nonpositive |
| w2017_2019 | `xs_rank_ls_sticky` | 0.010942 | 1.3363 | 0.0392 | 0.945 | 1 | True | False | — |
| w2020_2022 | `mf_value_mom_rate` | 0.005008 | — | 0.0424 | — | -1 | True | False | — |
| w2020_2022 | `rate_abs_level_xs` | 0.012357 | — | 0.0833 | — | -1 | True | False | — |
| w2020_2022 | `event_post_disclosure_hold` | 0.001542 | — | 0.1826 | — | -1 | True | False | — |
| w2020_2022 | `flow_margin_short_hard` | 0.047642 | — | 0.0132 | — | 1 | True | False | — |
| w2020_2022 | `xs_rank_ls_sticky` | 0.010171 | — | 0.0385 | — | 1 | True | False | — |
| w2023_2025 | `mf_value_mom_rate` | 0.001773 | 0.3937 | 0.0476 | 0.278 | 1 | True | False | — |
| w2023_2025 | `rate_abs_level_xs` | 0.002855 | 0.1560 | 0.0849 | 0.110 | 1 | True | False | — |
| w2023_2025 | `event_post_disclosure_hold` | 0.005816 | 1.6581 | 0.1834 | 1.172 | -1 | True | False | — |
| w2023_2025 | `flow_margin_short_hard` | 0.004514 | 1.1489 | 0.0545 | 0.812 | -1 | True | False | — |
| w2023_2025 | `xs_rank_ls_sticky` | 0.018085 | 3.6995 | 0.0392 | 2.616 | 1 | True | False | — |

## Classification (per logic)

| logic | stance | surv windows | sign_flip | promote |
|-------|--------|-------------:|:---------:|:-------:|
| `mf_value_mom_rate` | UNSTABLE_RESEARCH_ONLY | 3/3 | True | False |
| `rate_abs_level_xs` | UNSTABLE_RESEARCH_ONLY | 3/3 | True | False |
| `event_post_disclosure_hold` | UNSTABLE_RESEARCH_ONLY | 2/3 | False | False |
| `flow_margin_short_hard` | UNSTABLE_RESEARCH_ONLY | 2/3 | True | False |
| `xs_rank_ls_sticky` | STABLE_RESEARCH_ONLY | 3/3 | False | False |

**Headline:** all 5 remain **research-only**; `xs_rank_ls_sticky` most stable (no sign flip); rate/flow still carry prior weak_thesis / flip risk; **not** main · **not** GO.

## Freezes held

Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言 · continuous paper UNARMED · 3 defaults frozen · no invent · no live
