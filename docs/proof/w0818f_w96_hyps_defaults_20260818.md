# W96 / w0818f — failure-constrained hyps + frozen 3-default quality (2026-08-18)

**Wave:** `w0818f` / **W96** · Tracks B + C  
**Status:** research evidence only · **not** Mass / READY / ops GO / live  
**Prior tip:** W95 `942a43d` · OTC tip underneath Track A  
**Logs:** [`.glm-logs/w0818f_w96_data_hyps_defaults/`](../../.glm-logs/w0818f_w96_data_hyps_defaults/)  
**Recipe:** `scripts/run_w96_hyps_and_defaults.py` · `packages/product/research/llm_hyp_generator.py` **v1.1**  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Freezes held

| freeze | status |
|--------|--------|
| Mass research | **NO-GO** |
| READY | **not declared** |
| Phase7 | **OFF** |
| operational GO | **未宣言** |
| continuous paper | **UNARMED** |
| live orders | **false** |
| 3 defaults retune | **Forbidden / not done** |
| BaseVol | **canonical** |
| ATM | **compare-only** |
| spread | **off-mainline** |
| COMPLETE 23 invent | **none** |
| shape/rate/flow/demoted fund re-opt | **not run** |

---

## B. Failure-constrained new hyps

### Constraints injected (`llm-hyp-generator/v1.1`)

Hard prompt + reject gate (W95 failure-mode):

1. Avoid single-regime sign-flip dependency (or disclose)
2. No soft≡pressure non-differentiation
3. No low-var inflated-t trust
4. No hold/mom/frac-only · no dual options-level-as-sole-edge · no window-only
5. Do not re-polish demoted/weak shape · rate · flow · fund_slow
6. Always thesis / signal / position / datasets

### Provider path

| attempt | result |
|---------|--------|
| **xAI grok-4.6** via `generate_and_evaluate_hypotheses` (auth.json) | **ok** · primary |
| route | always → `propose_profit_hypotheses` (cost / PIT / low-var) |

### Counts

| metric | value |
|--------|------:|
| n_requested | 8 |
| n_proposed | **8** |
| n_accepted | **8** |
| n_rejected (gen+eval entry) | **0** |
| n_evaluated | **8** |
| n_survivors | **5** |
| provider / model | xai / **grok-4.6** |
| wall (B+C full) | ~243s |

Logs: `hyp_summary.json` · `llm_hyp_generation.json` · `llm_hyp_eval_screens.json` · `llm_hyp_eval_ranking.json` · `w96_bc_summary.json`

### Representative theses (distinct mechanisms)

| logic_id | family |
|----------|--------|
| `margin_absorb_inst_sell_unwind` | flow |
| `crowded_toushin_redemption_firesale` | fund |
| `realrate_netcash_vs_debtor_xs` | rate |
| `accruals_x_st_funding_tightness` | multi_factor |
| `mgmt_guidance_vs_street_revision_drift` | event |
| `residual_vol_no_news_liquidity` | vol |
| `ccc_improvement_fcf_surprise` | xs |
| `meti_invship_customer_producer_rotation` | macro |

Eval maps unknown ids onto nearest executable catalog templates (thesis text retained).

### Eval screens (catalog-mapped) — **not** main promotion

| mapped logic_id | survived | reject / note |
|-----------------|:--------:|---------------|
| `flow_margin_short_hard` | True | research-only · **not** main (W95 flow weak_thesis family) |
| `event_post_disclosure_hold` | True | below promote bar |
| `rate_abs_level_xs` | True | **known weak_thesis family — not main** |
| `xs_rank_ls_sticky` | True | research-only |
| `vol_risk_adjusted_mom` | True | research-only |
| `fund_value_mom_agree` | False | near_zero_after_cost |
| `mf_value_mom_rate` | False | **inflated_t_low_variance** (gate held) |
| `macro_repo_rate_change` | False | near_zero + **inflated_t_low_variance** |

**Do not promote** demoted/weak rate/flow/shape/fund_slow as main. Factory survivors ≠ production `research_candidate`.

---

## C. Frozen 3-default quality (NO RETUNE)

### Pins (unchanged)

| representative_id | hold | mom | mode | stance |
|-------------------|-----:|----:|------|--------|
| `cross_section_hold_10` | 10 | 5 | — | **KEEP** |
| `cross_section_hold_10_mom3` | 10 | 3 | — | **PROMOTE** |
| `fundamentals_hold_10` | 10 | 10 | `value_momentum_agree` | **KEEP** |

Asserted from `FROZEN_DEFAULT_PATH` · **retune_performed=False**.

### Quality table (preferred: CF `r2_panels`)

CF job: **`w96-defaults-20260818T142144Z`** · mode **`r2_panels`** · status **ok** · window×default survivors **9/9**  
Machine: `default_quality_table.json` / `default_quality_table.md`

| representative_id | pinned | pins | surv_windows | mean_net_avg | t_avg | low_var | metrics_suggest | contradiction |
|-------------------|--------|------|-------------:|-------------:|------:|--------:|-----------------|---------------|
| `cross_section_hold_10` | **KEEP** | h=10 m=5 | 3/3 | 0.013066 | 2.5179 | 0 | SUPPORTS_PROMOTE | — (KEEP compatible; pins held) |
| `cross_section_hold_10_mom3` | **PROMOTE** | h=10 m=3 | 3/3 | 0.008653 | 3.3906 | 0 | SUPPORTS_PROMOTE | window-mild only (w2020/w2023 t thin → SUPPORTS_KEEP; **pins held**) |
| `fundamentals_hold_10` | **KEEP** | h=10 m=10 value_mom_agree | 3/3 | 0.002818 | 0.6303 | 0 | SUPPORTS_KEEP | — |

### Per-window (CF)

| window | id | pinned | mean_net | t | act | sign | surv | suggest |
|--------|-----|--------|---------:|--:|----:|------|:----:|---------|
| w2017_2019 | xs mom5 | KEEP | 0.010942 | 1.34 | 0.039 | +1 | T | SUPPORTS_KEEP |
| w2017_2019 | xs mom3 | PROMOTE | 0.008870 | 5.50 | 0.039 | +1 | T | SUPPORTS_PROMOTE |
| w2017_2019 | fund | KEEP | 0.001231 | 0.42 | 0.066 | +1 | T | SUPPORTS_KEEP |
| w2020_2022 | xs mom5 | KEEP | 0.010171 | — | 0.038 | +1 | T | SUPPORTS_KEEP |
| w2020_2022 | xs mom3 | PROMOTE | 0.004222 | — | 0.038 | −1 | T | SUPPORTS_KEEP *(mild vs PROMOTE; recorded)* |
| w2020_2022 | fund | KEEP | 0.002610 | — | 0.068 | +1 | T | SUPPORTS_KEEP |
| w2023_2025 | xs mom5 | KEEP | 0.018085 | 3.70 | 0.039 | +1 | T | SUPPORTS_PROMOTE |
| w2023_2025 | xs mom3 | PROMOTE | 0.012868 | 1.28 | 0.039 | +1 | T | SUPPORTS_KEEP *(mild; recorded)* |
| w2023_2025 | fund | KEEP | 0.004614 | 0.84 | 0.072 | −1 | T | SUPPORTS_KEEP |

**If PROMOTE/KEEP contradicts metrics → record only; do not change pins.** Done.

Local corroboration: `default_quality_local.json` (same 3 pins × 3 windows; gates cost/PIT/low-var).

---

## Explicit non-declarations

- Mass ON / READY / Phase7 / operational GO / continuous paper arm / live — **none**
- 3 defaults retune — **forbidden / not done**
- Promote demoted/weak rate/flow/shape/fund_slow as main — **none**
- smile/surface ≡ BaseVol level — **forbidden**
- invent COMPLETE 23 / OTC densify — **none** (Track A tip-only)

---

## Artifacts

| path | role |
|------|------|
| `scripts/run_w96_hyps_and_defaults.py` | B+C driver |
| `llm_hyp_generator.py` v1.1 | W95 failure-mode constraints |
| `hyp_summary.json` | n_proposed/accepted/rejected/survivors + theses |
| `default_quality_table.json/md` | frozen 3-default quality + contradictions |
| CF `w96-defaults-20260818T142144Z` | r2_panels multi-year defaults |
| `w96_bc_summary.json` | combined B+C summary |
