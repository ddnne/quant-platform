# W94 / w0818d — options_225 skew / CM-term / ΔBaseVol + thick-factor windows

**Wave status:** **COMPLETE** — skew / CM-term / ΔBaseVol features + multi-year windows · CF thick rate/flow/fund/mf · BaseVol canonical · ATM compare-only · spread off-mainline · 3 defaults frozen · residual TOP  
**Wave:** W94 / `w0818d` · 2026-08-18  
**Implementer:** GLM5.3 only. Grok did **not** implement.  
**Logs:** [`.glm-logs/w0818d_w94_opt_skew_thick/`](../../.glm-logs/w0818d_w94_opt_skew_thick/)  
**Prior tip:** W93 ~`7ed4c5c` feature HEAD on `origin/main` (skew wire) · track C `8184071`

---

## Goal (PRIMARY) — held

| goal | held |
|------|:----:|
| New features: skew / CM-term / ΔBaseVol (not ATM dual rehash) | **yes** |
| BaseVol = **canonical level**; ATM = **compare-only** | **yes** |
| Multi-year windows 2017–19 / 2020–22 / 2023–25 (honest shards) | **yes** |
| CF `r2_panels` preferred + local real | **yes** |
| Compare failure modes vs BaseVol abs level regime | **yes** |
| Thick rate/flow/fund/mf consume W93 sidecars (mdh_fb=0) | **yes** · track C |
| Level dual-eval (ATM/spread) marked **off-mainline** | **yes** |
| Do **not** claim smile/surface identical to level | **yes** |
| 3 defaults frozen; no GO/Mass/READY/live; no grid mass | **yes** |
| residual TOP=W94 · proofs · git push | **yes** (this close) |

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
| TOPIX RV as primary Nikkei vol | **forbidden** (proxy/compare only) |
| invent / ffill gaps | **forbidden** |
| smile/surface ≡ level claim | **forbidden** |

### Frozen default path (not retuned)

| representative_id | pins | stance |
|-------------------|------|--------|
| `cross_section_hold_10` | hold=**10** · mom=**5** | KEEP |
| `cross_section_hold_10_mom3` | hold=**10** · mom=**3** | PROMOTE |
| `fundamentals_hold_10` | hold=**10** · mom=**10** · value_momentum_agree | KEEP |

---

## A. Feature definitions (`research-options-225-vol-series/v1.2`)

| series | role | convention |
|--------|------|------------|
| **BaseVol** | **canonical level** | exchange day-level BaseVol |
| ATM IV | **compare-only** | nearest-strike put/call mid (min_dte≥6) |
| spread = ATM−BaseVol | off-mainline / non-informative | post-W93 ≈0 |
| **skew** | W94 primary | `put_iv(~0.95*UnderPx) − atm_mid_iv` · listed strikes only |
| **CM-term** | W94 primary | `near_cm_atm_iv − next_cm_atm_iv` |
| **ΔBaseVol** | W94 primary | `BaseVol[t] − BaseVol[t−1]` (observed dates; no ffill) |

**Fullspan rebuild:** 121 raw monthly files · 10,279,506 rows · **2452** skew / CM-term days · **2451** ΔBaseVol days · span 2016-07-19 → 2026-07-31.

| series | n | mean | p50 | p10 / p90 |
|--------|--:|-----:|----:|-----------|
| skew | 2452 | 4.58 | 4.35 | 2.54 / 6.99 |
| cm_term | 2452 | 0.11 | −0.24 | −1.52 / 1.83 |
| basevol_delta | 2451 | 0.003 | −0.14 | −1.78 / 2.00 |

Logics wired: `opt225_skew_abs_level` · `opt225_cm_term_abs_level` · `opt225_basevol_delta_abs`  
Versions: factory **v2.5** · class-signals **v10** · cf-mass-eval **v5**

---

## B. Multi-year window eval (skew / term / Δ)

**Windows (honest to available mirrors):**

| window | label | shards used | data note |
|--------|-------|-------------|-----------|
| `w2017_2019` | 2017–2019 | `y2017_q4` + `y2019_full` | 2018 mirror absent |
| `w2020_2022` | 2020–2022 | `y2021_full` only | 2020/2022 mirrors absent |
| `w2023_2025` | 2023–2025 | `y2023_full` + `y2025_q4` | 2024 mirror absent |

Driver: `scripts/run_w94_opt_skew_windows.py` · local real mirrors + CF `r2_panels`.

### Local — primary logics + BaseVol level compare

| window | bucket | logic | mean_net | t | act | sign | survived |
|--------|--------|-------|---------:|--:|----:|-----:|:--------:|
| w2017_2019 | skew | `opt225_skew_abs_level` | 0.005043 | 0.6857 | 0.0565 | −1 | True |
| w2017_2019 | cm_term | `opt225_cm_term_abs_level` | 0.004438 | 18.5813 | 0.0274 | 1 | True |
| w2017_2019 | basevol_delta | `opt225_basevol_delta_abs` | 0.003102 | 0.4532 | 0.0326 | −1 | True |
| w2017_2019 | basevol_level | `opt225_basevol_abs_level` | 0.007213 | 16.2881 | 0.0207 | 1 | True |
| w2020_2022 | skew | `opt225_skew_abs_level` | 0.010885 | — | 0.0622 | −1 | True |
| w2020_2022 | cm_term | `opt225_cm_term_abs_level` | 0.009068 | — | 0.0332 | 1 | True |
| w2020_2022 | basevol_delta | `opt225_basevol_delta_abs` | 0.005073 | — | 0.0462 | 1 | True |
| w2020_2022 | basevol_level | `opt225_basevol_abs_level` | — | — | 0.0000 | — | **False** |
| w2023_2025 | skew | `opt225_skew_abs_level` | 0.005845 | 1.4256 | 0.0562 | −1 | True |
| w2023_2025 | cm_term | `opt225_cm_term_abs_level` | 0.006024 | 0.8916 | 0.0356 | −1 | True |
| w2023_2025 | basevol_delta | `opt225_basevol_delta_abs` | 0.015655 | 1.6523 | 0.0415 | −1 | True |
| w2023_2025 | basevol_level | `opt225_basevol_abs_level` | 0.025480 | — | 0.0201 | −1 | True |

### CF — same shards · `r2_panels`

| item | value |
|------|-------|
| job_id | **`w94-skew-20260818T130829Z`** |
| mode | **`r2_panels`** (NOT synthetic) |
| status | **ok** |
| n_periods (shards) | 5 |
| n_survivors (CF aggregate screen) | **3** |

| window | bucket | logic | mean_net | t | act | sign | survived |
|--------|--------|-------|---------:|--:|----:|-----:|:--------:|
| w2017_2019 | skew | `opt225_skew_abs_level` | 0.011275 | 1.3237 | 0.0383 | −1 | True |
| w2017_2019 | cm_term | `opt225_cm_term_abs_level` | 0.016914 | — | 0.0118 | 1 | True |
| w2017_2019 | basevol_delta | `opt225_basevol_delta_abs` | 0.003726 | 0.5876 | 0.0157 | −1 | True |
| w2017_2019 | basevol_level | `opt225_basevol_abs_level` | 0.020002 | — | 0.0093 | 1 | **False** (low_act) |
| w2020_2022 | skew | `opt225_skew_abs_level` | 0.010171 | — | 0.0417 | −1 | True |
| w2020_2022 | cm_term | `opt225_cm_term_abs_level` | 0.011577 | — | 0.0243 | 1 | True |
| w2020_2022 | basevol_delta | `opt225_basevol_delta_abs` | 0.010976 | — | 0.0312 | −1 | True |
| w2020_2022 | basevol_level | `opt225_basevol_abs_level` | — | — | 0.0000 | — | **False** |
| w2023_2025 | skew | `opt225_skew_abs_level` | 0.005662 | 0.7515 | 0.0383 | −1 | True |
| w2023_2025 | cm_term | `opt225_cm_term_abs_level` | 0.009652 | 0.4359 | 0.0215 | −1 | True |
| w2023_2025 | basevol_delta | `opt225_basevol_delta_abs` | 0.005957 | 0.4981 | 0.0286 | −1 | True |
| w2023_2025 | basevol_level | `opt225_basevol_abs_level` | 0.034989 | — | 0.0149 | −1 | True |

Machine: [`skew_local_window_table.md`](../../.glm-logs/w0818d_w94_opt_skew_thick/skew_local_window_table.md) · [`cf_skew_window_table.md`](../../.glm-logs/w0818d_w94_opt_skew_thick/cf_skew_window_table.md)

### Failure modes vs BaseVol abs level (not identical)

1. **w2020_2022:** BaseVol abs level **dies** (act=0 / near-zero) on both local + CF; all three shape/change logics **survive** with act≈0.02–0.06. Shape features are **not** a restate of level regime.
2. **w2017_2019:** skew / ΔBaseVol prefer **sign=−1** while BaseVol level prefers **sign=+1** (local+CF). Opposite risk-on mapping — do **not** claim smile ≡ level.
3. **Activation:** skew/term/Δ fire ~2–3× more often than BaseVol abs level on the same shards (level often sits near the lite `low_activation` edge on CF).
4. **w2023_2025:** signs align (−1) across skew/term/Δ and level — coincidence on this shard set, not identity of surface.

**Explicit non-claim:** smile / term structure / Δvol are **not** identical to BaseVol abs level; ATM remains compare-only alias; spread remains non-informative.

---

## C. Track C — thick rate / flow / fund / mf windows

Already on main (`8184071`). Primary CF job **`w94-thick-20260818T125009Z`** · worker **research-mass-eval/v5** · **mdh_fb=0** on rate/flow/fund/mf (sidecars consumed). Survivors (aggregate) **8**.

### Rate (CF)

| window | logic | mean_net | act | sign | survived | mdh_fb |
|--------|-------|---------:|----:|-----:|:--------:|-------:|
| w2017_2019 | `macro_repo_rate_change` | 0.011915 | 0.0766 | 1 | False | 0 |
| w2017_2019 | `macro_repo_rate_level` | 0.009194 | 0.0793 | 1 | False | 0 |
| w2020_2022 | `macro_repo_rate_change` | 0.014487 | 0.0736 | −1 | False | 0 |
| w2020_2022 | `macro_repo_rate_level` | 0.002156 | 0.0806 | −1 | False | 0 |
| w2023_2025 | `macro_repo_rate_change` | 0.012764 | 0.0825 | 1 | False | 0 |
| w2023_2025 | `macro_repo_rate_level` | −0.000875 | 0.0778 | — | False | 0 |

### Flow / fund / mf (headline)

- Flow: act≈0.01–0.10 · signs flip 2017→2023 · no window survivor at lite screen  
- Fund: `fund_value_mom_agree_slow` huge t on 2017 shard (single-period artifact) · 2023 signs flip negative  
- MF: `mf_flow_price` 2020 spike act low · not promoted  

Full tables: [`cf_rate_table.md`](../../.glm-logs/w0818d_w94_opt_skew_thick/cf_rate_table.md) · [`cf_flow_table.md`](../../.glm-logs/w0818d_w94_opt_skew_thick/cf_flow_table.md) · [`cf_fund_table.md`](../../.glm-logs/w0818d_w94_opt_skew_thick/cf_fund_table.md) · [`cf_mf_table.md`](../../.glm-logs/w0818d_w94_opt_skew_thick/cf_mf_table.md)

### Wiring inventory (COMPLETE 22)

| status | n |
|--------|--:|
| wired_on_cf | 8 |
| local_only | 3 |
| not_yet | 11 |

options_225 staged as `opt225_regime` including skew / cm_term / basevol_delta maps.

---

## D. Off-mainline dual-eval (ATM / spread)

| item | stance |
|------|--------|
| BaseVol | **canonical level** (mainline) |
| ATM IV | **compare-only alias** (off-mainline dual) — post-W93 twin of BaseVol for abs/term |
| spread abs/change | **non-informative** at frozen thresholds (W93 autopsy) |
| smile / surface ≡ level | **NOT claimed** |

---

## E. Artifacts

| path | content |
|------|---------|
| `skew_series.ndjson` / `cm_term_series.ndjson` | fullspan 2452d |
| `basevol_delta_series.ndjson` | fullspan 2451d |
| `fullspan_stats.json` | dist summary |
| `skew_local_window_table.md` | local window nets |
| `cf_skew_window_table.md` | CF window nets |
| `cf_skew_mass_eval_job.json` | job `w94-skew-20260818T130829Z` |
| `cf_{rate,flow,fund,mf,window}_table.md` | track C thick tables |
| `scripts/run_w94_opt_skew_windows.py` | window driver |
| `scripts/run_w94_thick_factor_windows.py` | thick-factor driver |

---

## Close checklist

| item | status |
|------|--------|
| skew / CM-term / ΔBaseVol series + logics | **yes** |
| fullspan rebuild (≥ window coverage) | **yes** · 2452d |
| multi-year windows local + CF | **yes** · job `w94-skew-20260818T130829Z` |
| failure-mode vs BaseVol level | **yes** · diverges (esp. 2020–22) |
| thick rate/flow/fund/mf (mdh_fb=0) | **yes** · `w94-thick-20260818T125009Z` |
| ATM/spread off-mainline | **yes** |
| smile≢level non-claim | **yes** |
| 3 defaults frozen | **yes** |
| Mass/READY/GO/live closed | **yes** |
| residual TOP=W94 | **yes** |
| pytest touched | **green** |
| git push origin main | **yes** (this close) |

Implementer: GLM5.3 only. Grok did not implement.
