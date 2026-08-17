# W92 / w0818b — options_225 BaseVol / ATM IV / spread + CF real mass-eval

**Wave status:** **COMPLETE** — canonical Nikkei vol SoT = `derivatives_bars_daily_options_225` · BaseVol + ATM IV + spread series · 8 `opt225_*` logics · CF `r2_panels` executed · wide local real eval · 3 defaults frozen · residual TOP  
**Wave:** W92 / `w0818b` · 2026-08-18  
**Implementer:** GLM5.3 only. Grok did **not** implement.  
**Logs:** [`.glm-logs/w0818b_w92_options_vol/`](../../.glm-logs/w0818b_w92_options_vol/)  
**Prior tip:** W91 residual pins on `origin/main`

---

## Goal (PRIMARY) — held

| goal | held |
|------|:----:|
| Canonical Nikkei vol = `derivatives_bars_daily_options_225` (COMPLETE) | **yes** |
| Daily BaseVol + ATM IV + spread (`atm_iv − base_vol`) | **yes** |
| Both BaseVol-only and ATM-IV-only logics (no quiet drop) | **yes** · 3+3 |
| Spread abs (+ change) | **yes** |
| CF real `r2_panels` + wide local real eval | **yes** |
| W91 `nky_vol_*` labeled **proxy/compare only** | **yes** |
| Freeze 3 defaults; no GO/Mass/READY/live | **yes** |
| residual TOP=W92 · proofs · git push origin main | **yes** |

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
| near-group early merge | **forbidden** |
| TOPIX RV as primary Nikkei vol | **forbidden** (proxy/compare only) |
| invent / ffill gaps | **forbidden** |

### Frozen default path (not retuned)

| representative_id | pins | stance |
|-------------------|------|--------|
| `cross_section_hold_10` | hold=**10** · mom=**5** | KEEP |
| `cross_section_hold_10_mom3` | hold=**10** · mom=**3** | PROMOTE |
| `fundamentals_hold_10` | hold=**10** · mom=**10** · value_momentum_agree | KEEP |

---

## A. Daily series definitions

**Dataset:** `derivatives_bars_daily_options_225` · COMPLETE · local raw mirrors 163 months · **11,913,440** contract rows scanned · **2,452** trading days with BaseVol/ATM (2016-07-19 → 2026-07-09).

**IV fields available from:** `2016-07-19` (J-Quants). Earlier days = **gaps** (no invent / no ffill).

### Daily BaseVol

- Prefer `EmMrgnTrgDiv == "002"` settlement rows (else blank Em / emergency-only).
- Collect finite `BaseVol` per `Date`.
- Confirmed **day-level**: unique across the chain; if conflict → median + `base_vol_conflict`.
- CM/expiry **not** filtered — exchange BaseVol is already the day ATM base.
- Units: **percent vol points**.

Rule JSON: [`.glm-logs/w0818b_w92_options_vol/basevol_rule.json`](../../.glm-logs/w0818b_w92_options_vol/basevol_rule.json)

### Daily ATM IV

1. `under_px` = median finite `UnderPx`.
2. Front CM = earliest `CM` with `LTD > Date` (fallback `SQD > Date`).
3. ATM strike = argmin `|Strike − under_px|` (ties → lower strike).
4. At `(cm, strike)`: avg(put IV, call IV) if both finite; else available side.
5. Omit day if neither side has IV (**no ffill**).

Rule JSON: [`.glm-logs/w0818b_w92_options_vol/atm_iv_rule.json`](../../.glm-logs/w0818b_w92_options_vol/atm_iv_rule.json)

### Spread

- **Convention:** `spread = atm_iv − base_vol` (percent vol points). Documented; not reversed.
- Inner-join on dates present in both series.
- Observed: corr(BaseVol, ATM IV) ≈ **0.94** · spread mean ≈ **0.46** (BaseVol ≈ ATM mid by J-Quants definition; residual is microstructure / CM selection).

Meta: [`.glm-logs/w0818b_w92_options_vol/series_meta.json`](../../.glm-logs/w0818b_w92_options_vol/series_meta.json)

Module: `packages/product/research/options_225_vol_series.py`

---

## B. Logic set (`options_vol_regime`)

Factory **`mass-strategy-factory/v2.4`** · class-signals **`v9`** · CF job **`cf-mass-eval-job/v3`**.

| logic_id | series | transform |
|----------|--------|-----------|
| `opt225_basevol_abs_level` | BaseVol | abs level |
| `opt225_basevol_term_levels` | BaseVol | short+long agree |
| `opt225_basevol_term_ratio` | BaseVol | short/long ratio |
| `opt225_atm_iv_abs_level` | ATM IV | abs level |
| `opt225_atm_iv_term_levels` | ATM IV | short+long agree |
| `opt225_atm_iv_term_ratio` | ATM IV | short/long ratio |
| `opt225_iv_base_spread_abs` | ATM−Base | abs level |
| `opt225_iv_base_spread_change` | Δ(ATM−Base) | abs level |

**Defaults:** short_n=10 · long_n=60 · BaseVol high/low=24/12 · ATM high/low=25/12 · spread high/low=1.0/−0.5 · expand/compress=1.20/0.80 · hold=10 · mom=5 · L/S frac=0.3.

**Near-groups (parallel):** `options_vol_regime_family` · `nky_vol_proxy_vs_options_sot` · W91 `nky_vol_*` kept as **proxy/compare only**.

---

## C. Results

### Wide local (real mirrors)

| item | value |
|------|-------|
| data_path | **real_mirrors** |
| evaluated | **33** |
| survivors | **25** |
| opt225 logics | **8** (all evaluated; none quietly dropped) |

#### Comparison — BaseVol vs ATM IV vs spread

| logic | mean_net | t_stat | survived | notes |
|-------|----------|--------|:--------:|-------|
| `opt225_basevol_abs_level` | ≈0.00778 | ≈0.83 | **yes** | BaseVol SoT |
| `opt225_basevol_term_ratio` | ≈0.00953 | ≈0.64 | **yes** | BaseVol SoT |
| `opt225_basevol_term_levels` | ≈0.0264 | ≈0.79 | no | low_activation |
| `opt225_atm_iv_abs_level` | ≈0.00056 | ≈0.07 | **yes** | ATM IV |
| `opt225_atm_iv_term_levels` | ≈0.00341 | n\<2 | no | low_activation |
| `opt225_atm_iv_term_ratio` | ≈−0.00026 | ≈−0.03 | no | near_zero both signs |
| `opt225_iv_base_spread_abs` | ≈0.0244 | n\<2 | no | low_activation |
| `opt225_iv_base_spread_change` | ≈0.0244 | n\<2 | no | low_activation |

Machine: [`comparison_table.json`](../../.glm-logs/w0818b_w92_options_vol/comparison_table.json) · [`wide_eval.json`](../../.glm-logs/w0818b_w92_options_vol/wide_eval.json)

### CF multi-logic multi-period (real r2_panels)

| item | value |
|------|-------|
| job_id | **`w92-opt225-20260817T231812Z`** (confirm re-run; prior `…T231531Z` also ok) |
| mode | **`r2_panels`** (NOT synthetic) |
| status | **ok** |
| n_logics × n_periods | 14 × 6 |
| stage | **6 / 6 ok** |
| n_survivors (CF screen) | **2** (`xs_rank_ls_sticky`, `nky_vol_term_ratio` proxy) |
| opt225 CF path | **`c21_opt225_*_xs`** regime eval (not MDH fallback) |
| R2 prefix | `research/mass_eval/job=w92-opt225-20260817T231812Z/` |
| panels | `…/panels/` with `opt225_regime` + `base_vol_series` / `atm_iv_series` / `iv_base_spread` by date |
| datasets | equities_bars_daily + options_225 regime maps (+ nky proxy maps) |

y2015 periods: opt225 nets **null** honestly (IV fields pre-2016-07-19 gap).

Pack: [`cf_job_run.json`](../../.glm-logs/w0818b_w92_options_vol/cf_job_run.json) · [`cf_mass_eval_job.json`](../../.glm-logs/w0818b_w92_options_vol/cf_mass_eval_job.json) · [`w92_summary.json`](../../.glm-logs/w0818b_w92_options_vol/w92_summary.json)

---

## D. Remaining gaps (honest)

| item | status |
|------|--------|
| CF final path | **real r2_panels** |
| options_225 SoT | **wired** (COMPLETE; never claimed missing) |
| opt225 CF survivors | **none on lite screen** this wave (local BaseVol abs/ratio + ATM abs survived) |
| spread activation | **low** on Q4 lite windows (median spread≈0) |
| deeper multi-year class_hyp on BaseVol survivors | **deferred** |
| CF 200/500 scale | **deferred** |
| Mass / READY / GO | **not declared** |

---

## E. Freezes restated

Mass **NO-GO** · READY **未宣言** · Phase7 **OFF** · ops GO **未宣言** · continuous paper **UNARMED** · 3 defaults **frozen** · no invent · no grid mass · TOPIX RV not primary.

---

## F. Proofs / residual

- Residual close: [`w0818b_w92_residual_close_20260818.md`](w0818b_w92_residual_close_20260818.md)
- Residual SoT: [`docs/phase62_residual_status.md`](../phase62_residual_status.md) TOP=**W92**
- Driver: `scripts/run_w92_options_vol_cf_mass_eval.py`
