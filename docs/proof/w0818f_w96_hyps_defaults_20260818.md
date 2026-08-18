# W96 / w0818f — failure-constrained hyps + frozen 3-default quality (2026-08-18)

**Wave:** `w0818f` / **W96** · Tracks B + C  
**Status:** research evidence only · **not** Mass / READY / ops GO / live  
**Prior tip:** W95 `942a43d` · OTC tip commit underneath `a780fb9`  
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

Hard prompt + reject gate:

1. Avoid single-regime sign-flip dependency (or disclose)
2. No soft≡pressure non-differentiation
3. No low-var inflated-t trust
4. No hold/mom/frac-only · no dual options-level-as-sole-edge
5. Do not re-polish demoted/weak shape · rate · flow · fund_slow
6. Always thesis / signal / position / datasets

### Provider path (honest)

| attempt | result |
|---------|--------|
| xAI grok-4.6 via `generate_strong_model_hypotheses` | empty / timeout (wrapper) |
| GLM | HTTP 429 balance |
| Workers AI `/v1/generate_hyps` | 404 not found |
| catalog_seed fallback | 8/8 eval · 4 survivors (disclosed fallback) |
| **Direct xAI grok-4.6** (W96 path) | **8 extracted · 8 accepted · 0 rejected** |

Primary evidence = **direct xAI grok-4.6** → `propose_profit_hypotheses` (cost / PIT / low-var gate).  
Catalog seed kept as disclosed fallback only — **not** promoted as main.

### Counts

| metric | value |
|--------|------:|
| n_requested | 8 |
| n_proposed | **8** |
| n_accepted | **8** |
| n_rejected | **0** |
| n_evaluated | **8** |
| n_survivors | **5** |
| wall | ~227s |

Logs: `hyp_xai_eval.json` · `hyp_xai_raw_content.txt` · `hyp_eval_catalog.json`

### Accepted theses (distinct mechanisms)

| logic_id | family |
|----------|--------|
| `tse_close_auction_dealer_inventory_fade` | flow |
| `etf_ap_create_redeem_amihud_xs_pressure` | fund |
| `real_jgb_shock_equity_cf_duration_xs` | rate |
| `gpa_ep_lowinv_revision_entry_pairs` | multi_factor |
| `tdnet_seisaku_hoyu_disposal_supply` | event |
| `parkinson_gk_vs_cc_liquidity_fade` | vol |
| `customer_residual_to_supplier_diffusion` | XS |
| `us_semi_residual_to_jp_spe_vs_domestic` | macro |

Eval maps unknown ids onto nearest executable catalog templates (thesis text retained).

### Ranking (survivors) — **not** main promotion

| rank | mapped logic_id | mean_net | t | sign | note |
|-----:|-----------------|---------:|--:|------|------|
| 1 | `mf_value_mom_rate` | 0.00715 | 2.94 | +1 | multi_factor map; research-only |
| 2 | `rate_abs_level_xs` | 0.00247 | 1.65 | −1 | **known weak_thesis family — not main** |
| 3 | `event_post_disclosure_hold` | 0.00735 | 0.98 | +1 | below stats bar for promote |
| 4 | `flow_margin_short_hard` | 0.00064 | 0.48 | +1 | **weak — not main** |
| 5 | `xs_rank_ls_sticky` | 0.00052 | 0.31 | −1 | near-zero |

**Do not promote** demoted/weak rate/flow/shape/fund_slow as main. Factory survivors ≠ production `research_candidate`.

---

## C. Frozen 3-default quality (NO RETUNE)

### Pins (unchanged)

| representative_id | hold | mom | mode | stance |
|-------------------|-----:|----:|------|--------|
| `cross_section_hold_10` | 10 | 5 | — | **KEEP** |
| `cross_section_hold_10_mom3` | 10 | 3 | — | **PROMOTE** |
| `fundamentals_hold_10` | 10 | 10 | `value_momentum_agree` | **KEEP** |

Asserted from `FROZEN_DEFAULT_PATH` · `frozen_pins.json` · **retune_performed=False**.

### Quality table (local class_hyp + CF `r2_panels`)

CF job: **`w96-defaults-20260818T141855Z`** · mode **`r2_panels`** · status **ok** · survivors **2**

| id | frozen | pins | local RC | local net | local t | local sign | CF net | CF t | CF sign | contradiction |
|----|--------|------|:--------:|----------:|--------:|-----------:|-------:|------:|--------:|---------------|
| `cross_section_hold_10` | **KEEP** | h=10 m=5 | True | 0.008343 | 1.586 | 1 | 0.00828 | 2.975 | original | — |
| `cross_section_hold_10_mom3` | **PROMOTE** | h=10 m=3 | True | 0.01189 | 3.032 | 1 | 0.006101 | 1.249 | original | PROMOTE_weaker_than_KEEP_on_CF_r2_panels_t_and_net |
| `fundamentals_hold_10` | **KEEP** | h=10 m=10 value_momentum_agree | True | 0.004477 | 1.775 | 1 | 0.001448 | 0.7093 | inverted | KEEP_fund_weak_CF_t_lt_1_sign_inverted |

### Contradictions — **record only** (pins NOT changed)

1. **`cross_section_hold_10_mom3` PROMOTE** — local multi-year still strong (t≈3.03, win=1.0, RC=true); CF `r2_panels` plane weaker than KEEP mom5 on t/net. **Stance held PROMOTE.**
2. **`fundamentals_hold_10` KEEP** — local RC=true sign=+1 t≈1.77; CF plane weak (t≈0.71) + **inverted** (W86 paper-flip known). **Stance held KEEP.**

Logs: `defaults_quality.json` · `defaults_quality_table.md` · `defaults_class_hyp_bundle.json` · `cf_defaults_job.json`

---

## Explicit non-claims

- Mass / READY / Phase7 / operational GO / continuous paper arm / live — **not**
- 3 defaults retune — **not**
- Promote hyp survivors or demoted weak as main — **not**
- COMPLETE 23 invent · OTC dataset COMPLETE · archive densify — **not**
- smile/surface ≡ BaseVol level — **not**

---

## Return

```json
{
  "hyps": {"provider": "xai/grok-4.6", "n_proposed": 8, "n_accepted": 8, "n_evaluated": 8, "n_survivors": 5},
  "defaults": {"pins_unchanged": true, "retune_performed": false, "contradictions_n": 2},
  "cf_defaults_job": "w96-defaults-20260818T141855Z",
  "mass": "NO-GO",
  "ready": false,
  "continuous_paper": "UNARMED"
}
```
