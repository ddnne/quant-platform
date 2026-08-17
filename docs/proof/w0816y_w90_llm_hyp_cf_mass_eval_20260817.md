# W90 / w0816y — Strong-model hyp generation + CF multi-logic mass eval

**Wave status:** **COMPLETE** — grok-4.6 hyp gen · CF multi-logic multi-period job executed · wide local eval · 3 defaults frozen · residual TOP · push  
**Wave:** W90 / `w0816y` · 2026-08-17  
**Implementer:** GLM5.3 (Grok does **not** implement)  
**Logs:** [`.glm-logs/w0816y_w90_llm_cf/`](../../.glm-logs/w0816y_w90_llm_cf/)  
**Prior tip:** W89 `76e656b`

---

## Goal (PRIMARY) — held

| goal | held |
|------|:----:|
| Strong-model profit-hypothesis generation (not window tweaks) | **yes** · xAI **grok-4.6** |
| Convert → logic schema → near-dup vs catalog | **yes** · `propose_profit_hypotheses` |
| Pipeline runs without human seeds | **yes** |
| CF multi-logic × multi-period eval job | **yes** · Worker deployed + invoked |
| R2 artifacts under quant-structured | **yes** · `research/mass_eval/job={id}/` |
| Wide eval of LLM-accepted + catalog survivors | **yes** · 32 evaluated · 18 survivors |
| 3 defaults frozen (no retune) | **yes** |
| No Mass/READY/ops GO/live · continuous paper UNARMED | **yes** |
| No simple_daily_sign grid · no look-ahead · no S1–S5 un-reject | **yes** |
| Near-similar logics stay parallel | **yes** |

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

## A. Strong-model hypothesis generation (actual run)

| item | value |
|------|-------|
| **Status** | **ran** |
| **Model** | **grok-4.6** |
| **Provider** | **xai** (`https://api.x.ai/v1`) |
| **Entry** | `research.llm_hyp_generator.generate_and_evaluate_hypotheses` |
| **Downstream** | `propose_profit_hypotheses` (always through evaluator) |
| **n_proposed** | **10** |
| **n_accepted** | **10** |
| **n_evaluated** | **10** |
| **n_survivors** (LLM-only eval) | **1** |
| **window tweaks** | **forbidden** |
| **human seeds** | **none** |

### Representative hypotheses (LLM)

| logic_id | family | thesis (abbrev) |
|----------|--------|-----------------|
| `flow.residual_foreign_demand_float` | flow | Residual foreign cash-equity demand (ex trust-bank/ETF) informed about cycle |
| `fund.it_etf_creation_liquidity_pressure` | fund | Public IT/ETF creation lag into liquid benchmark names |
| `rate.real_jgb_alm_duration_rotation` | rate | Life/bank ALM rotation when 10y real JGB yields rise |
| `multi_factor.pbr_reform_quality_revision_intersection` | multi_factor | PBR&lt;1 reform ∩ high ROIC ∩ positive FY1 revisions |
| `event.low_coverage_afterhours_sue_pead` | event | Slow PEAD among low-coverage after-hours SUE names |
| `vol.vi_invert_idiosyncratic_quality_rotation` | vol | NKY-VI invert + IV&gt;RV → quality residual-vol rotation |
| `xs.dtc_revision_crowding_cover` | xs | High DTC shorts cover when FY1 revisions turn positive |
| `macro.china_pmi_asia_export_revenue_beta` | macro | China PMI / Asia export surprise → Greater-China revenue beta |

Machine: [`.glm-logs/w0816y_w90_llm_cf/llm_hyp_generation.json`](../../.glm-logs/w0816y_w90_llm_cf/llm_hyp_generation.json)

**Note:** LLM ad-hoc family labels (`flow`, `fund`, …) map to nearest executable catalog template for bar eval when logic_id is unknown; missing extra datasets → `n_periods_ok=0` (honest data_missing, not invent). Catalog survivors remain the executable backbone.

---

## B. CF multi-logic multi-period eval job (implemented + executed)

| item | value |
|------|-------|
| **Status** | **executed on CF** |
| **Worker** | `quant-platform-research-mass-eval` |
| **URL** | `https://quant-platform-research-mass-eval.taku-haga.workers.dev` |
| **Endpoint** | `POST /v1/mass-eval` |
| **job_id** | **`w90-wide-20260817T145205Z`** |
| **path_used** | **`cf_worker_mass_eval`** |
| **mode** | `synthetic` (lite multi-period panels on Worker) |
| **n_logics** | **32** |
| **n_periods** | **6** |
| **n_logic×period cells** | **192** |
| **n_evaluated** | **32** |
| **n_survivors** | **20** |
| **wall_time_ms** (worker) | **~1794** |
| **R2 bucket** | `quant-structured` |
| **R2 prefix** | `research/mass_eval/job=w90-wide-20260817T145205Z/` |

### R2 artifact paths

```
research/mass_eval/job=w90-wide-20260817T145205Z/manifest.json
research/mass_eval/job=w90-wide-20260817T145205Z/request.json
research/mass_eval/job=w90-wide-20260817T145205Z/summary.json
research/mass_eval/job=w90-wide-20260817T145205Z/results.json
research/mass_eval/job=w90-wide-20260817T145205Z/ranking.json
research/mass_eval/job=w90-wide-20260817T145205Z/panels_meta.json
research/mass_eval/job=w90-wide-20260817T145205Z/logic={logic_id}/result.json  (×32)
```

### Shard policy (documented lite)

- Lite multi-period on CF (synthetic Q4-style panels; wall-clock safe)
- Full rate/mf factor legs on pure-TS CF path: **not yet implemented** (fallback mdh knobs / nets_only)
- Heavy multi-year real-mirror eval remains local (`run_mass_factory` / `class_hyp_eval`) for promising survivors
- Queue fan-out 200/500: **not yet implemented** (cap documented)

Code: `platform/workers/research-mass-eval/` · `research.llm_hyp_generator.run_cf_multi_logic_eval_job` · `try_cf_minimal_mass_batch()` → **available**

Machine: [`.glm-logs/w0816y_w90_llm_cf/cf_mass_eval_job.json`](../../.glm-logs/w0816y_w90_llm_cf/cf_mass_eval_job.json)

---

## C. Wide evaluation (local real mirrors)

| metric | value |
|--------|------:|
| n_catalog_after_dedup | **22** |
| n_llm_merged | **10** |
| n_strategies (wide) | **32** |
| n_evaluated | **32** |
| n_survivors | **18** |
| fail_rate | **0.0** |
| wall_time_sec | **~1.78** |
| frozen_defaults_retuned | **False** |
| continuous_paper | **UNARMED** |
| human_main_candidates_selected | **False** |

### Results table (top by |t| · real mirrors · PIT + cost)

| logic_id | family | survived | mean_net | t_stat | sharpe | sign | n_ok |
|----------|--------|:--------:|---------:|-------:|-------:|:----:|-----:|
| flow_margin_short_soft | flow_demand | **yes** | +28.5bp | **1.53** | −0.67 | −1 | 6 |
| flow_margin_pressure | flow_demand | **yes** | +28.5bp | **1.53** | −0.67 | −1 | 6 |
| **mf_value_mom_rate** | multi_factor | **yes** | +46.3bp | **1.48** | **0.60** | +1 | 6 |
| mf_flow_price | multi_factor | **yes** | +63.2bp | 1.28 | −0.54 | −1 | 6 |
| flow_margin_short_hard | flow_demand | **yes** | +66.9bp | 1.06 | −0.45 | −1 | 6 |
| xs_rank_mom_slow | cross_section_relative | **yes** | +22.5bp | 1.06 | −0.47 | −1 | 6 |
| event_post_disclosure_hold | event_post | **yes** | +73.5bp | 0.98 | 0.40 | +1 | 6 |
| rate_curve_shape_xs | rate_factor | **yes** | +38.2bp | 0.91 | 0.37 | +1 | 6 |
| rate_abs_level_xs | rate_factor | **yes** | +44.4bp | 0.87 | −0.41 | −1 | 6 |
| mdh_short_horizon_mom | multi_day_hold | **yes** | +8.5bp | 0.87 | −0.52 | −1 | 6 |
| xs_rank_ls_sticky | cross_section_relative | **yes** | +21.3bp | 0.48 | 0.20 | +1 | 6 |
| vol_breakout_expand | vol_risk_adjusted | **yes** | +25.4bp | 0.42 | 0.17 | +1 | 6 |
| vol_risk_adjusted_mom | vol_risk_adjusted | **yes** | +29.7bp | 0.38 | −0.17 | −1 | 6 |
| fund_value_only | fundamentals_price | **yes** | +6.9bp | 0.29 | −0.15 | −1 | 6 |
| mdh_sticky_momentum | multi_day_hold | **yes** | +15.9bp | 0.23 | 0.09 | +1 | 6 |
| mdh_mean_reversion | multi_day_hold | **yes** | +15.9bp | 0.23 | −0.11 | −1 | 6 |
| event_post_long_horizon | event_post | **yes** | +16.9bp | 0.19 | −0.08 | −1 | 6 |
| xs_rank_ls_daily | cross_section_relative | no | −10.6bp | −3.93 | −1.60 | — | 6 |
| macro_repo_rate_change | macro_conditioned | no | −10.2bp | −1.63 | −0.67 | — | 6 |
| fund_value_mom_agree | fundamentals_price | no | +1.9bp | 0.06 | 0.03 | — | 6 |
| fund_value_mom_agree_slow | fundamentals_price | no | −1.8bp | −0.04 | −0.02 | — | 6 |
| (10 LLM-mapped ad-hoc) | various | no | data_missing | — | — | — | 0 |

Full table: [`.glm-logs/w0816y_w90_llm_cf/SUMMARY.md`](../../.glm-logs/w0816y_w90_llm_cf/SUMMARY.md) · `wide_eval.json`

**Most promising (held from W89):** `mf_value_mom_rate` t≈1.48 · Sharpe≈0.60 · chosen_sign=+1 — not auto-promoted.

---

## Catalog / factory version

| item | value |
|------|-------|
| factory | `mass-strategy-factory/v2.2` |
| wave | `W90 / w0816y` |
| logic templates | **22** (W89 catalog held) |
| class-signals | **v7** (held) |
| LLM generator | `llm-hyp-generator/v1` |
| CF mass-eval | `research-mass-eval/v1` |

---

## Modules / recipes

| path | role |
|------|------|
| `packages/product/research/llm_hyp_generator.py` | strong-model hyp gen + CF job driver |
| `packages/product/research/cf_mass_eval_job.py` | CF job helpers / wide eval pack |
| `packages/product/research/mass_strategy_factory.py` | factory v2.2 · CF status available · LLM strong entry |
| `platform/workers/research-mass-eval/` | CF Worker (TS) multi-logic multi-period |
| `scripts/run_w90_llm_cf_mass_eval.py` | end-to-end recipe |
| `scripts/run_mass_strategy_batch.py` | local factory batch (held) |

---

## Freezes / non-declarations (held)

- **READY** — 未宣言  
- **Mass** operational — **NO-GO**  
- **Phase7** — **OFF**  
- **operational GO** — 未宣言 / deferred  
- **continuous paper** — **UNARMED**  
- **3 defaults retune** — not done  
- **human main candidates** — not selected  
- **S1–S5 un-reject** — not done  
- **simple_daily_sign mass** — forbidden  
- **CF 200/500 queue fan-out** — not yet implemented  
- **full rate/mf factor legs on pure-TS CF** — not yet implemented  

---

## Pipeline wall

| stage | wall |
|-------|-----:|
| A LLM hyp gen (grok-4.6) | ~2 min |
| C wide local eval (32) | ~1.8 s |
| B CF job (32×6) | ~1.8 s worker + network |
| **total pipeline** | **~136.6 s** |

---

## Residual note

Language ban held: do **not** describe CF as "blocked". This wave **implemented and executed** the CF multi-logic multi-period job. Remaining gaps use **"not yet implemented"** (full factor legs on pure-TS; 200/500 fan-out).
