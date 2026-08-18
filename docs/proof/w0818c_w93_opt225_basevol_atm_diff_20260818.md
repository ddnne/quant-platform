# W93 / w0818c — options_225 BaseVol vs ATM IV differential + multi-year windows

**Wave status:** **COMPLETE** — deep-dive **both** BaseVol and ATM IV (never collapsed) · differential analysis primary · multi-year windows 2017–2019 / 2020–2022 / 2023–2025 (honest shards) · spread activation autopsy · ATM min_dte=6 fix · CF thickened `r2_panels` · 3 defaults frozen · residual TOP  
**Wave:** W93 / `w0818c` · 2026-08-18  
**Implementer:** GLM5.3 only. Grok did **not** implement.  
**Logs:** [`.glm-logs/w0818c_w93_opt225_diff/`](../../.glm-logs/w0818c_w93_opt225_diff/)  
**Prior tip:** W92 ~`b77568b` on `origin/main`

---

## Goal (PRIMARY) — held

| goal | held |
|------|:----:|
| Deep-dive **both** BaseVol and ATM IV (differential axis) | **yes** |
| Multi-year windows first (not mandatory full-span dump) | **yes** · w2017_2019 / w2020_2022 / w2023_2025 |
| No new human hyps — thicken existing options vol line | **yes** |
| TOPIX RV = proxy only; options_225 = SoT | **yes** |
| 3 defaults frozen; no GO/Mass/READY/live; no grid mass | **yes** |
| CF real preferred; must push | **yes** · primary `w93-opt225-20260818T120810Z` · corroborating `w93-opt225-20260818T121627Z` · `w93-thicken-20260818T121404Z` |
| residual TOP=W93 · proofs · git push | **yes** (this close) |

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

### Frozen default path (not retuned)

| representative_id | pins | stance |
|-------------------|------|--------|
| `cross_section_hold_10` | hold=**10** · mom=**5** | KEEP |
| `cross_section_hold_10_mom3` | hold=**10** · mom=**3** | PROMOTE |
| `fundamentals_hold_10` | hold=**10** · mom=**10** · value_momentum_agree | KEEP |

---

## A. Differential analysis (PRIORITY)

**Artifacts:** [`diff_series_stats.json`](../../.glm-logs/w0818c_w93_opt225_diff/diff_series_stats.json) · [`diff_results_table.json`](../../.glm-logs/w0818c_w93_opt225_diff/diff_results_table.json) · [`spread_activation_diagnosis.md`](../../.glm-logs/w0818c_w93_opt225_diff/spread_activation_diagnosis.md)

### Series after W93 min_dte fix (`research-options-225-vol-series/v1.1`)

| metric | pre-fix (W92) | post-fix (W93 min_dte=6) |
|--------|-----------------|---------------------------|
| n days | 2452 | 2452 |
| corr(BaseVol, ATM) pearson | ≈0.936 | **≈0.99994** |
| frac exact-zero spread | ≈86.7% | **≈99.76%** |
| spread mean | ≈0.46 | **≈0.0028** |
| spread abs max | ≈93.1 | **≈2.60** |
| n \|spread\|≥1 | 230 | **4** |
| frac active @ ±1.0/−0.5 | ≈9.9% | **≈0.16%** |

### Diagnosis — why spread logics had low activation

1. **J-Quants BaseVol ≈ ATM put/call mid by definition** (from 2016-07-19).
2. Pre-fix: **all** nonzero `atm_iv − base_vol` residuals sat exclusively at front-CM **DTE ∈ {1,2,3}** (SQ-week blow-ups; DTE≥5 always exact 0) — expiry noise, not a durable risk-premium structure.
3. Default thresholds `spread_high=1.0` / `spread_low=−0.5` therefore rarely fire → `low_activation` reject on lite windows.
4. **Not** a sign-convention bug.

### Minimal definition fix

- `DEFAULT_ATM_MIN_DTE_DAYS = 6`: skip front CM when LTD DTE < 6; roll to next eligible CM.
- Rebuild: 163 raw monthly files · 11,913,440 rows · 2452 days.
- Post-fix: BaseVol and ATM regime maps are effectively cointegrated duplicates for abs/term transforms.

### Noise vs structure (short)

Post-fix residual spread is microstructure / rare fallback only. **Spread abs/change logics are not informative** at frozen thresholds. **BaseVol and ATM families are interchangeable for level/term transforms** after the roll — differential delta ≈ 0 on matched windows. Keep both families in the catalog (policy: never quiet-drop) but treat them as SoT twins, not independent factors.

---

## B. Multi-year window eval

**Windows (honest to available mirrors):**

| window | label | shards used | data note |
|--------|-------|-------------|-----------|
| `w2017_2019` | 2017–2019 | `y2017_q4` + `y2019_full` | 2018 mirror absent |
| `w2020_2022` | 2020–2022 | `y2021_full` only | 2020/2022 mirrors absent |
| `w2023_2025` | 2023–2025 | `y2023_full` + `y2025_q4` | 2024 mirror absent |

Driver: `scripts/run_w93_opt225_diff_windows.py` · local real mirrors + CF `r2_panels`.

### Local — same transform → BaseVol vs ATM delta

| window | transform | BaseVol mean_net | ATM mean_net | Δ (base−atm) |
|--------|-----------|------------------|--------------|--------------|
| w2017_2019 | abs | ≈0.00677 | ≈0.00677 | **0.0** |
| w2017_2019 | term_levels | ≈0.00683 | ≈0.00683 | **0.0** |
| w2017_2019 | term_ratio | ≈−0.00964 | ≈−0.00964 | **0.0** |
| w2020_2022 | abs / term_* | null | null | — (single shard low/no active net) |
| w2023_2025 | abs | ≈−0.0257 | ≈−0.0257 | **0.0** |
| w2023_2025 | term_levels | ≈−0.0600 | null | — (ATM term_levels low act) |
| w2023_2025 | term_ratio | ≈0.00324 | ≈0.00324 | **0.0** |

Machine: [`window_eval_local.json`](../../.glm-logs/w0818c_w93_opt225_diff/window_eval_local.json) · [`diff_results_table.json`](../../.glm-logs/w0818c_w93_opt225_diff/diff_results_table.json)

### CF — same window shards · thickened panels

| item | value |
|------|-------|
| job_id (primary) | **`w93-opt225-20260818T120810Z`** |
| corroborating | **`w93-opt225-20260818T121627Z`** (full 8 logics × windows · survivors **4**) · **`w93-thicken-20260818T121404Z`** (thicken · survivors **3**) |
| mode | **`r2_panels`** (NOT synthetic) |
| status | **ok** |
| n_periods (shards) | 5 |
| n_survivors (CF screen, primary) | **2** |
| opt225 BaseVol vs ATM | **identical mean_net** on abs / term_ratio (twins) |
| spread abs/change | activation **0** · reject |
| R2 prefix | `research/mass_eval/job=w93-opt225-20260818T120810Z/` |

Per-window CF tables: [`cf_window_summary.json`](../../.glm-logs/w0818c_w93_opt225_diff/cf_window_summary.json)

Cost + PIT held; 3 defaults untouched.

---

## C. CF panel thicken

**Version:** `cf-mass-eval-job/v4` · wave W93.

Prefer-wired COMPLETE sidecars into staged panels (live sample all **DONE** × 5 shards):

| dataset | panel key | status |
|---------|-----------|--------|
| equities_bars_daily | `bars` | DONE |
| options_225 | `opt225_regime` / series maps | DONE |
| indices_bars_daily_topix | nky proxy | DONE (proxy label only) |
| jsda_tokyo_repo_rates | `repo_rate_regime` | DONE |
| markets_margin_interest | `flow_regime` / `margin_interest` | DONE |
| markets_short_ratio | `short_ratio_by_date` | DONE |
| fins_summary | `fund_regime` | DONE |
| markets_calendar | `calendar` | DONE |

**TODO:** CF pure-TS flow/fund factor legs consuming sidecars (macro_repo_* staged; flow/fund still local_only) · contiguous 3y bars mirrors.

Inventory: [`cf_wiring_inventory.json`](../../.glm-logs/w0818c_w93_opt225_diff/cf_wiring_inventory.json)

Local thicken re-eval included `macro_repo_rate_*` / `mf_value_mom_rate` / flow sample on the same window shards (factory path already had repo/fins/margin).

---

## D. Health / freezes restated

- COMPLETE **22** held (includes `derivatives_bars_daily_options_225`) · DEFER **4** · no invent **23**
- projection **FRESH** (`ops_reeval_freshness` 2026-08-18)
- Mass **NO-GO** · READY **未宣言** · Phase7 **OFF** · ops GO **未宣言** · continuous paper **UNARMED** · 3 defaults **frozen**

---

## E. Remaining gaps (honest)

| item | status |
|------|--------|
| Contiguous 3y bars mirrors (2018/2020/2022/2024) | **absent** — windows use available shards |
| Spread logics informative | **no** — definitional twin + min_dte removed SQ noise |
| CF flow/fund TS legs | **TODO** (sidecars staged) |
| CF 200/500 scale | **deferred** |
| Mass / READY / GO | **not declared** |

---

## F. Proofs / residual

- Residual close: [`w0818c_w93_residual_close_20260818.md`](w0818c_w93_residual_close_20260818.md)
- Residual SoT: [`docs/phase62_residual_status.md`](../phase62_residual_status.md) TOP=**W93**
- Driver: `scripts/run_w93_opt225_diff_windows.py`
- Series module: `packages/product/research/options_225_vol_series.py` **v1.1**
