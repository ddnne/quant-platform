# W95 / w0818e — skew/CM-term/Δ deep-dive + rate/flow/fund failure decomp

**Wave status:** **COMPLETE** — both tracks advanced · fund2017 giant-t demoted · low-variance t-gate (v6) · shape research-only (not promoted) · 3 defaults frozen · residual TOP  
**Wave:** W95 / `w0818e` · 2026-08-18  
**Implementer:** GLM5.3 only. Grok did **not** implement.  
**Logs:** [`.glm-logs/w0818e_w95_shape_factor_decomp/`](../../.glm-logs/w0818e_w95_shape_factor_decomp/)  
**Prior tip:** W94 `d855116`

---

## Goal (held)

| goal | held |
|------|:----:|
| A. Shape deep-dive (skew / CM-term / Δ) — few-point sens + binds | **yes** |
| Per-window sign/act/t tables · 2020–22 vs level note | **yes** |
| Weak → say weak; **not** promote as main candidates | **yes** |
| B. rate / flow / fund failure decomp | **yes** |
| fund 2017 giant-t reproduce → artifact → demote | **yes** |
| Classify: data_gap vs weak_thesis vs impl_bug | **yes** |
| Fix only worth-fixing (low-variance t-gate) → re-eval | **yes** · v6 |
| C. Promising-few re-eval (shape + repaired; no dead blast) | **yes** |
| 3 defaults frozen; no GO/Mass/READY/live; no grid mass | **yes** |
| BaseVol=canonical · ATM=compare-only · spread=off-mainline | **yes** |
| Do **not** claim smile≡level | **yes** |
| residual TOP=W95 · proofs · git push | **yes** (this close) |

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
| **3 default-path retune** | **forbidden** · pins held |
| TOPIX RV as primary Nikkei vol | **forbidden** (proxy only) |
| invent / ffill gaps | **forbidden** |
| smile/surface ≡ level claim | **forbidden** |
| grid mass | **forbidden** |

### Frozen default path (not retuned)

| representative_id | pins | stance |
|-------------------|------|--------|
| `cross_section_hold_10` | hold=**10** · mom=**5** | KEEP |
| `cross_section_hold_10_mom3` | hold=**10** · mom=**3** | PROMOTE |
| `fundamentals_hold_10` | hold=**10** · mom=**10** · value_momentum_agree | KEEP |

---

## A. Shape deep-dive (skew / CM-term / Δ)

**Driver:** `scripts/run_w95_shape_deepdive.py`  
**Series:** research-options-225-vol-series/v1.2 · fullspan skew/CM-term **2452** · ΔBaseVol **2451**

### Coarse sensitivity (few points only — no grid)

| series | default hi/lo | alt points |
|--------|---------------|------------|
| skew | 3.0 / 0.5 | looser 2.0/1.0 · tighter 4.5/0.0 |
| cm_term | 2.0 / −1.0 | narrow 1.0/−0.5 · wide 3.0/−2.0 |
| basevol_delta | 1.0 / −1.0 | tight 0.5/−0.5 · wide 1.5/−1.5 |

**Headline:** skew sign stable (−1) across thresholds; cm_term **wide** kills w2020_2022 (act=0); Δ wide fails w2017. Thresholds matter at edges but defaults remain the research pin. **Not** promoted.

### Shape×CS binds (few)

mom={5 default, 3 bind} at default thresholds. mom3 sometimes lifts nets (esp. w2023) but cm_term bind **sign-flips** vs default on some shards — unstable. **Not** a frozen-default retune; **not** promoted.

### Per-window (local default sens + CF re-eval)

Local + CF agree on failure-mode vs level:

| window | skew | cm_term | ΔBaseVol | BaseVol level | note |
|--------|:----:|:-------:|:--------:|:-------------:|------|
| w2017_2019 | T | T | T | T / F(low_act CF) | skew/Δ sign ≠ level |
| w2020_2022 | T | T | T | **F/F** | level dead; shape alive |
| w2023_2025 | T | T | T | T | signs align (−1) this shard |

CF promising job: **`w95-shape-20260818T133241Z`** · mode **`r2_panels`** · window surv rows (post sign_selection fix) include shape survivors; level dead on w2020_2022.

Machine: [`shape_sens_bind_table.md`](../../.glm-logs/w0818e_w95_shape_factor_decomp/shape_sens_bind_table.md) · [`cf_promising_reeval_table.md`](../../.glm-logs/w0818e_w95_shape_factor_decomp/cf_promising_reeval_table.md) · [`divergence_2020_22.md`](../../.glm-logs/w0818e_w95_shape_factor_decomp/divergence_2020_22.md)

### 2020–22 divergence vs level (short note)

BaseVol abs level **dies** (act=0) on w2020_2022 while skew / CM-term / Δ remain active (act≈0.03–0.06). Shape/change features are **not** a restate of level regime. **Explicit non-claim:** smile / term / Δ ≢ BaseVol level; ATM compare-only; spread off-mainline.

### Promotion stance

**WEAK / research-only.** Do **not** promote skew / CM-term / Δ as main candidates this wave. Signs flip across windows; economic nets thin; n=2 window t can inflate (gated).

---

## B. rate / flow / fund failure decomp

**Drivers:** `scripts/run_w95_factor_failure_decomp.py` · `scripts/run_w95_shape_factor_decomp.py`  
**Source:** W94 thick job `w94-thick-20260818T125009Z` · live re-eval **`w95-decomp-20260818T133302Z`** · worker **research-mass-eval/v6**

### Rate — change vs level · activation · sign-flip

| window | change net/act/sign | level net/act/sign |
|--------|---------------------|--------------------|
| w2017_2019 | +0.012 / 0.077 / +1 | +0.009 / 0.079 / +1 |
| w2020_2022 | +0.014 / 0.074 / −1 | +0.002 / 0.081 / −1 |
| w2023_2025 | +0.013 / 0.083 / +1 | −0.001 / 0.078 / — |

- Activation healthy (~0.07–0.08); **mdh_fb=0** (sidecar consumed)  
- Sign flips 2017→2021→2023  
- **Classification:** **weak_thesis** (not data gap, not impl bug)  
- Prefer change over level for further probes; **do not promote**

### Flow — definition / refresh / missingness

| mode | definition |
|------|------------|
| pressure | margin_interest_change only (`short_confirm_mode=off`) |
| hard | margin AND same-sign short; missing short → no entry |
| soft | short gap → margin-only; conflict → keep margin |

- Refresh: entry only on margin observation days; sticky `min_hold`  
- **soft≡pressure** on these panels (identical period nets) → soft non-differentiating  
- hard lowers act without producing durable edge  
- Sign flips 2017→2023  
- **Classification:** **weak_thesis** (+ soft near-dup); missingness makes soft non-informative but eval path OK (mdh_fb=0)  
- **Not** impl bug; **not** worth code fix beyond disclose soft≡off

### Fund 2017 giant-t — reproduce → artifact → demote

| item | value |
|------|-------|
| logic | `fund_value_mom_agree_slow` |
| window | w2017_2019 (y2017_q4 + y2019_full) |
| nets | ≈0.008229 · 0.008337 |
| **raw ungated t** | **≈153.18** |
| CV | ≈0.009 ≪ 5% floor |
| gated t | **null** · reason `low_variance_artifact` |
| 5-period aggregate t | ≈1.73 (ordinary) |
| action | **demote** · screen reject `inflated_t_low_variance` |

**Conclusion:** single-window / low-variance **artifact** (n=2 near-equal nets), not an edge and not a data bug in fins. Demoted from survivors / promising / window-headline. Keep near-group parallel.

### Worth-fixing item (done)

| fix | status |
|-----|--------|
| Low-variance / inflated-t gate in `stats_metrics` + CF worker v6 + `screen_strategy_result` | **landed** |
| Live CF re-eval demotes `fund_value_mom_agree_slow` | **yes** · survivors 8→**7** |

### Taxonomy counts (logic×window)

| label | n |
|-------|--:|
| data_gap | 12 (mostly single-shard w2020_2022 t-null) |
| weak_thesis | 23 |
| impl_bug | 1 (`fund_value_mom_agree_slow` denom inflation — fixed by gate) |

Full: [`failure_taxonomy.md`](../../.glm-logs/w0818e_w95_shape_factor_decomp/failure_taxonomy.md) · [`fund_2017_t_audit.json`](../../.glm-logs/w0818e_w95_shape_factor_decomp/fund_2017_t_audit.json)

---

## C. Promising-few re-eval

Narrow set: shape primary + level compare + mom3 binds + light anchors.  
**Excluded:** demoted fund_slow + dead rate/flow/fund/mf blast.

| path | job / table | note |
|------|-------------|------|
| local | `promising_reeval_local_table.md` | shape + binds |
| CF | `w95-shape-20260818T133241Z` · `r2_panels` | window tables post sign_selection fix |
| decomp CF | `w95-decomp-20260818T133302Z` · v6 | fund demotion confirmed |

**Survivors not forced to exactly 2.** Shape window survivors exist but **promote_as_main_candidate=false**. Cost/PIT/sign rules held; 3 defaults not retuned.

---

## Versions / wiring

| component | version / wave |
|-----------|----------------|
| class-signals | v10 / W95 |
| mass-strategy-factory | v2.5 / W95 |
| options_225 series | v1.2 / W95 |
| cf-mass-eval-job | **v6** / W95 |
| research-mass-eval worker | **v6** / W95 |
| COMPLETE | **22** held · DEFER 4 · no invent 23 |

---

## Residual TOP (W95)

1. **Canonical level** — BaseVol mainline; ATM compare-only; spread off-mainline  
2. **Skew / CM-term / Δ** — deep-dived; research-only; **not** main candidates; ≠ level (esp. 2020–22)  
3. **Rate / flow / fund** — weak_thesis / soft≡off / fund2017 artifact demoted; low-variance gate live  
4. **3 defaults frozen** — mom5 · mom3 · fund; not retuned  
5. **GO deferred** · Mass/READY/ops GO closed · continuous paper **UNARMED**

---

## Explicit non-declarations

- READY / Mass ON / Phase7 / operational GO / GO final — **not**  
- continuous paper arm — **UNARMED**  
- human main candidate selection — **not this wave**  
- smile ≡ level — **forbidden / not claimed**  
- 3 defaults retune — **not done**  
- shape/skew as production research_candidates — **not**

---

## Artifacts

| path | content |
|------|---------|
| `shape_sens_bind_table.md` | local sens + binds |
| `divergence_2020_22.md` | level-dead / shape-alive note |
| `factor_failure_decomp.md` / `failure_taxonomy.md` | decomp + taxonomy |
| `fund_2017_t_audit.json` | giant-t reproduce + gate |
| `cf_{rate,flow,fund,mf,window}_table.md` | gated window tables |
| `cf_promising_reeval_table.md` | shape promising CF |
| `SUMMARY.md` / `w95_summary.json` | machine summary |
