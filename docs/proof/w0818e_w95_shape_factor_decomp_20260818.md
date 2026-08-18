# W95 / w0818e — rate/flow/fund failure decomposition + fund 2017 giant-t audit

**Wave:** W95 / w0818e  
**Source CF job (W94):** `w94-thick-20260818T125009Z`  
**Live CF job (W95):** `w95-decomp-20260818T133302Z`  
**Worker:** `research-mass-eval/v6`  
**Logs:** [`.glm-logs/w0818e_w95_shape_factor_decomp/`](../../.glm-logs/w0818e_w95_shape_factor_decomp/)

Freezes held: Mass NO-GO · READY 未宣言 · Phase7 OFF · ops GO 未宣言 · continuous paper UNARMED · 3 defaults not retuned · TOPIX proxy only.

---

## 1. Fund 2017 giant-t — ARTIFACT_CONFIRMED

| item | value |
|------|------:|
| logic | `fund_value_mom_agree_slow` |
| window | w2017_2019 (y2017_q4 + y2019_full) |
| nets | 0.008229 / 0.008337 |
| raw ungated t | **153.1848** |
| CV | 0.0092 (≪ 5% floor) |
| gated t | **null** (`low_variance_artifact`) |
| aggregate 5-period t | 1.73 (OK; not the claim) |

**Conclusion:** n=2 near-identical shard nets inflate `t = m/(s/√n)`. Not edge. Taxonomy: **impl_bug** (denom / missing low-var gate).

**Fix applied:**
- `stats_metrics.t_stat_vs_zero` + worker `tStatVsZero` null t when small-n CV < 5% and \|t\| > 12
- pairwise subset demotion → screen reject `inflated_t_low_variance`
- survivor demotion: W94 8 → W95/CF-v6 **7** (fund_slow excluded)

Audit: [`fund_2017_t_audit.json`](../../.glm-logs/w0818e_w95_shape_factor_decomp/fund_2017_t_audit.json)

---

## 2. Rate — change vs level

| window | change mean/t/sign/act | level mean/t/sign/act |
|--------|------------------------:|----------------------:|
| w2017_2019 | +1.19% / 1.89 / +1 / 0.077 | +0.92% / 1.19 / +1 / 0.079 |
| w2020_2022 | +1.45% / — / −1 / 0.074 | +0.22% / — / −1 / 0.081 |
| w2023_2025 | +1.28% / 1.04 / +1 / 0.082 | −0.09% / −0.43 / — / 0.078 |

- **Sign flips** on change: + (2017) → − (2021) → + (2023)
- **Activation** stable ~7–8% (sidecar consumed, mdh_fb=0)
- Level weaker / near-zero late; not a substitute for change
- Taxonomy: **weak_thesis** (not impl_bug)

---

## 3. Flow — eval OK, thesis weak

- Sidecar: `markets_margin_interest` + `markets_short_ratio`(0050) → `flow_regime`; worker `evalFlowDemand`; mdh_fb=0
- **soft ≡ pressure** on these panels (conflict keeps margin / short-gap → margin-only) → near-duplicate **weak_thesis**
- **hard** lowers act (≈0.01–0.10) but signs still flip 2017→2023
- Margin prints sparse (not daily) → low act by design; **not** refresh-lag bug
- Taxonomy: **weak_thesis** (+ soft near-dup); eval path not broken

---

## 4. Taxonomy (logic × window)

Primary labels in [`failure_taxonomy.md`](../../.glm-logs/w0818e_w95_shape_factor_decomp/failure_taxonomy.md):

| label | n | meaning |
|-------|--:|---------|
| data_gap | 12 | sparse shard windows (esp. w2020_2022 single shard) |
| weak_thesis | 23 | unstable sign / soft near-dup / lite reject without wiring defect |
| impl_bug | 1 | fund_slow 2017 inflated-t denom |

---

## 5. High-value fixes shipped

| fix | where |
|-----|-------|
| low-variance t gate | `packages/product/research/stats_metrics.py`, `platform/workers/research-mass-eval/src/metrics.ts` |
| pairwise demote / screen | `mass_strategy_factory.screen_strategy_result`, worker `eval.ts` |
| window reagg passes `sign_selection` + gated t | `scripts/run_w94_thick_factor_windows.py` |
| W95 driver | `scripts/run_w95_shape_factor_decomp.py` |
| worker bump | `research-mass-eval/v6` (deployed) |

No Mass/READY/GO/live arming. No frozen-default retune.

---

## 6. Artifacts

- `fund_2017_t_audit.json` · `survivors_demotion.json` · `failure_taxonomy.md`
- `rate_decomp.json` · `flow_decomp.json` · `cf_{rate,flow,fund}_table.md`
- `cf_mass_eval_job.json` / `cf_mass_eval_response.json` (job `w95-decomp-20260818T133302Z`)
- `cf_v6_live_fund_check.json`
